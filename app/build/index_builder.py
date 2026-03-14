"""
Blocking index build functions for the dataset builder.
All functions are designed to run in a ThreadPoolExecutor (or directly in a subprocess).

progress_cb(step_name: str, pct: float, detail: str = "") is called to report progress.
  - step_name: "encoding" | "training" | "adding" | "building" | "saving"
  - pct: 0.0–100.0
  - detail: human-readable string, e.g. "2400/10000"
"""
import os
import re
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import faiss
import numpy as np
import torch
from torch.utils.data import DataLoader

from .config import (
    get_ivfpq_nlist, get_ivfpq_m, get_ivfpq_nbits,
    get_hnsw_m, get_hnsw_ef_construction,
    get_encoding_batch_size, get_max_per_shard, get_db_batch_size, get_add_batch_size,
)
from .db_operations import blocking_create_protein_table, blocking_insert_protein_batch

EMBEDDING_DIM = 1280


# ---------------------------------------------------------------------------
# FASTA parsing helpers
# ---------------------------------------------------------------------------

def parse_fasta_header(header_string: str):
    accession = header_string
    ko = None
    ec = None

    ko_match = re.search(r'KO:(K\d{5})', header_string)
    if ko_match:
        ko = ko_match.group(1)

    ec_match = re.search(r'EC:([\d\.\-n]+)', header_string)
    if ec_match:
        ec = ec_match.group(1)

    split_pos = -1
    ko_pos = header_string.find('_KO:')
    ec_pos = header_string.find('_EC:')

    if ko_pos != -1 and ec_pos != -1:
        split_pos = min(ko_pos, ec_pos)
    elif ko_pos != -1:
        split_pos = ko_pos
    elif ec_pos != -1:
        split_pos = ec_pos

    if split_pos != -1:
        accession = header_string[:split_pos]

    return accession, ko, ec


def fasta_data_iterator(fasta_file_path: str):
    """
    Memory-efficient streaming FASTA iterator.
    Yields: (original_header, accession, ko, ec, sequence, seq_len, ph_val)
    """
    header = None
    sequence_parts = []

    with open(fasta_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line.startswith('>'):
                if header:
                    full_sequence = "".join(sequence_parts)
                    original_header = header.lstrip('>')
                    accession, ko, ec = parse_fasta_header(original_header)
                    yield (original_header, accession, ko, ec, full_sequence, len(full_sequence), None)

                header = line
                sequence_parts = []
            else:
                sequence_parts.append(line)

        if header:
            full_sequence = "".join(sequence_parts)
            original_header = header.lstrip('>')
            accession, ko, ec = parse_fasta_header(original_header)
            yield (original_header, accession, ko, ec, full_sequence, len(full_sequence), None)


# ---------------------------------------------------------------------------
# OOM-safe ESM2 batch encoder
# ---------------------------------------------------------------------------

def _make_collate_fn(tokenizer):
    def collate_fn(batch):
        return tokenizer(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)
    return collate_fn


def _batch_encode_sequences(
    sequences,
    model,
    tokenizer,
    batch_size: int = None,
    pooling: str = 'mean',
    progress_cb: Optional[Callable] = None,
):
    """
    OOM-safe batch encoding. On CUDA OOM, halves batch size and retries.
    Calls progress_cb("encoding", pct, "done/total") after each batch.
    Returns: np.ndarray (N, EMBEDDING_DIM) float32
    """
    if batch_size is None:
        batch_size = get_encoding_batch_size()

    total = len(sequences)
    device = next(model.parameters()).device
    embeddings = []
    done = 0
    i = 0

    while i < total:
        batch_seqs = sequences[i: i + batch_size]
        collate_fn = _make_collate_fn(tokenizer)
        batch = collate_fn(batch_seqs)
        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]

        success = False
        current_batch_size = batch_size
        for attempt in range(4):
            try:
                ids = input_ids.to(device)
                mask = attention_mask.to(device)
                with torch.no_grad():
                    outputs = model(input_ids=ids, attention_mask=mask)
                features = outputs.last_hidden_state
                masked = features * mask.unsqueeze(2)
                if pooling == 'mean':
                    pooled = masked.sum(dim=1) / mask.sum(dim=1, keepdim=True)
                elif pooling == 'max':
                    pooled = torch.max(masked, dim=1).values
                else:
                    pooled = features[:, 0, :]
                embeddings.append(pooled.detach().cpu().numpy())
                done += len(batch_seqs)
                success = True
                break
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                current_batch_size = max(1, current_batch_size // 2)
                print(
                    f"[index_builder] OOM at batch i={i}, "
                    f"reducing batch_size to {current_batch_size}"
                )
                batch_seqs = sequences[i: i + current_batch_size]
                batch = collate_fn(batch_seqs)
                input_ids = batch["input_ids"]
                attention_mask = batch["attention_mask"]

        if not success:
            raise RuntimeError(f"Failed to encode batch at index {i} after OOM retries.")

        batch_size = current_batch_size
        i += len(batch_seqs)

        if progress_cb:
            pct = round(done / total * 100, 1)
            progress_cb("encoding", pct, f"{done}/{total}")

    result = np.concatenate(embeddings, axis=0).astype('float32')
    torch.cuda.empty_cache()
    return result


# ---------------------------------------------------------------------------
# Phase 1: Import FASTA into PostgreSQL
# ---------------------------------------------------------------------------

def blocking_fasta_to_db(
    fasta_path: str,
    db_table: str,
    progress_cb: Optional[Callable] = None,
) -> int:
    blocking_create_protein_table(db_table)

    db_batch_size = get_db_batch_size()
    current_id = 0
    batch = []

    for record in fasta_data_iterator(fasta_path):
        original_header, accession, ko, ec, sequence, seq_len, ph_val = record
        batch.append((original_header, accession, ko, ec, sequence, seq_len, ph_val))

        if len(batch) >= db_batch_size:
            blocking_insert_protein_batch(db_table, batch, current_id)
            current_id += len(batch)
            batch = []
            if progress_cb:
                progress_cb("importing", None)

    if batch:
        blocking_insert_protein_batch(db_table, batch, current_id)
        current_id += len(batch)

    if progress_cb:
        progress_cb("importing_done", current_id)

    return current_id


# ---------------------------------------------------------------------------
# Single-shard GPU build helpers
# ---------------------------------------------------------------------------

def _build_flat_shard(vecs: np.ndarray, shard_path: str) -> None:
    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    index.add(vecs)
    faiss.write_index(index, shard_path)


def _build_ivfpq_shard(
    vecs: np.ndarray,
    shard_path: str,
    nlist: int,
    m: int,
    nbits: int,
    gpu_id: int,
    add_batch_size: int,
    progress_cb: Optional[Callable] = None,
) -> None:
    """Build one IVF-PQ shard on the specified GPU (or CPU if gpu_id < 0)."""
    n = vecs.shape[0]
    quantizer = faiss.IndexFlatL2(EMBEDDING_DIM)
    index_cpu = faiss.IndexIVFPQ(quantizer, EMBEDDING_DIM, nlist, m, nbits)
    index_cpu.nprobe = 16

    sample_size = max(nlist * 40, min(200_000, n))
    if sample_size < nlist:
        sample_size = n
    perm = np.random.permutation(n)[:sample_size]
    train_vecs = np.ascontiguousarray(vecs[perm])

    use_gpu = torch.cuda.is_available() and gpu_id >= 0

    if use_gpu:
        from app.core.gpu import create_faiss_gpu_resources, create_gpu_cloner_options
        res = create_faiss_gpu_resources(gpu_id)
        try:
            index_gpu = faiss.index_cpu_to_gpu(res, gpu_id, index_cpu, create_gpu_cloner_options())
            if progress_cb:
                progress_cb("training", 0.0, "")
            index_gpu.train(train_vecs)
            if progress_cb:
                progress_cb("training", 100.0, "done")

            added = 0
            for i in range(0, n, add_batch_size):
                batch = np.ascontiguousarray(vecs[i: i + add_batch_size])
                index_gpu.add(batch)
                added += batch.shape[0]
                if progress_cb:
                    pct = round(added / n * 100, 1)
                    progress_cb("adding", pct, f"{added}/{n}")

            index_cpu = faiss.index_gpu_to_cpu(index_gpu)
            index_cpu.nprobe = 16
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"[index_builder] OOM on GPU {gpu_id} during FAISS build, falling back to CPU.")
            use_gpu = False

    if not use_gpu:
        if progress_cb:
            progress_cb("training", 0.0, "")
        index_cpu.train(train_vecs)
        if progress_cb:
            progress_cb("training", 100.0, "done")
        added = 0
        for i in range(0, n, add_batch_size):
            batch = np.ascontiguousarray(vecs[i: i + add_batch_size])
            index_cpu.add(batch)
            added += batch.shape[0]
            if progress_cb:
                pct = round(added / n * 100, 1)
                progress_cb("adding", pct, f"{added}/{n}")

    faiss.write_index(index_cpu, shard_path)


def _build_hnsw_shard(
    vecs: np.ndarray,
    shard_path: str,
    hnsw_m: int,
    ef_construction: int,
    progress_cb: Optional[Callable] = None,
) -> None:
    n = vecs.shape[0]
    index = faiss.IndexHNSWFlat(EMBEDDING_DIM, hnsw_m)
    index.hnsw.efConstruction = ef_construction
    add_batch = get_add_batch_size()
    added = 0
    for i in range(0, n, add_batch):
        batch = np.ascontiguousarray(vecs[i: i + add_batch])
        index.add(batch)
        added += batch.shape[0]
        if progress_cb:
            pct = round(added / n * 100, 1)
            progress_cb("adding", pct, f"{added}/{n}")
    faiss.write_index(index, shard_path)


# ---------------------------------------------------------------------------
# Multi-GPU parallel shard build orchestrator
# ---------------------------------------------------------------------------

def _parallel_build_shards(
    shard_chunks: list[np.ndarray],
    output_dir: str,
    algorithm: str,
    build_kwargs: dict,
    progress_cb: Optional[Callable] = None,
) -> int:
    """
    Build multiple shards in parallel across available GPUs.
    Each thread gets its own GPU (round-robin) and its own FAISS resources.
    Returns total vectors indexed.
    """
    from app.core.gpu import get_available_devices
    devices = get_available_devices()
    n_shards = len(shard_chunks)
    total_indexed = 0
    completed = [0]  # mutable counter for progress aggregation
    lock = threading.Lock()

    def build_one(shard_id: int, vecs: np.ndarray) -> int:
        gpu_id = devices[shard_id % len(devices)] if devices else -1
        shard_path = os.path.join(output_dir, f"shard_{shard_id:03d}.faiss")

        def shard_cb(step, pct, detail=""):
            # Aggregate: overall pct = (completed_shards + this_shard_pct/100) / n_shards * 100
            with lock:
                overall = round(
                    (completed[0] + pct / 100.0) / n_shards * 100, 1
                )
            if progress_cb:
                progress_cb(step, overall, f"shard {shard_id + 1}/{n_shards} {detail}")

        if algorithm == "flat":
            _build_flat_shard(vecs, shard_path)
            if progress_cb:
                with lock:
                    completed[0] += 1
                progress_cb("building", round(completed[0] / n_shards * 100, 1),
                            f"{completed[0]}/{n_shards} shards")
        elif algorithm == "ivfpq":
            _build_ivfpq_shard(
                vecs, shard_path,
                build_kwargs["nlist"], build_kwargs["m"], build_kwargs["nbits"],
                gpu_id, build_kwargs["add_batch_size"],
                shard_cb,
            )
            with lock:
                completed[0] += 1
        elif algorithm == "hnsw":
            _build_hnsw_shard(
                vecs, shard_path,
                build_kwargs["hnsw_m"], build_kwargs["ef_construction"],
                shard_cb,
            )
            with lock:
                completed[0] += 1

        return vecs.shape[0]

    max_workers = max(1, len(devices)) if devices else 1
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(build_one, sid, chunk): sid
            for sid, chunk in enumerate(shard_chunks)
        }
        for fut in as_completed(futures):
            total_indexed += fut.result()

    return total_indexed


# ---------------------------------------------------------------------------
# Phase 2a: Build Flat (FlatL2) index
# ---------------------------------------------------------------------------

def blocking_build_flat(
    sequences: list,
    model,
    tokenizer,
    output_dir: str,
    progress_cb: Optional[Callable] = None,
) -> int:
    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    max_per_shard = get_max_per_shard()
    n_shards = max(1, math.ceil(total / max_per_shard))
    shard_size = math.ceil(total / n_shards)

    # Encoding phase (0–60%)
    def enc_cb(step, pct, detail):
        if progress_cb:
            progress_cb(step, round(pct * 0.6, 1), detail)

    all_vecs = _batch_encode_sequences(sequences, model, tokenizer, progress_cb=enc_cb)

    # Build phase (60–100%)
    shard_chunks = [
        np.ascontiguousarray(all_vecs[sid * shard_size: (sid + 1) * shard_size])
        for sid in range(n_shards)
        if all_vecs[sid * shard_size: (sid + 1) * shard_size].shape[0] > 0
    ]

    def build_cb(step, pct, detail=""):
        if progress_cb:
            progress_cb(step, round(60.0 + pct * 0.4, 1), detail)

    total_indexed = _parallel_build_shards(
        shard_chunks, output_dir, "flat", {}, build_cb
    )
    del all_vecs
    return total_indexed


# ---------------------------------------------------------------------------
# Phase 2b: Build IVF-PQ index
# ---------------------------------------------------------------------------

def blocking_build_ivfpq(
    sequences: list,
    model,
    tokenizer,
    output_dir: str,
    nlist: int = None,
    m: int = None,
    nbits: int = None,
    progress_cb: Optional[Callable] = None,
) -> int:
    nlist = nlist if nlist is not None else get_ivfpq_nlist()
    m = m if m is not None else get_ivfpq_m()
    nbits = nbits if nbits is not None else get_ivfpq_nbits()
    add_batch_size = get_add_batch_size()

    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    max_per_shard = get_max_per_shard()
    n_shards = max(1, math.ceil(total / max_per_shard))
    shard_size = math.ceil(total / n_shards)

    # Encoding phase (0–60%)
    def enc_cb(step, pct, detail):
        if progress_cb:
            progress_cb(step, round(pct * 0.6, 1), detail)

    all_vecs = _batch_encode_sequences(sequences, model, tokenizer, progress_cb=enc_cb)

    # Build phase (60–100%)
    shard_chunks = [
        np.ascontiguousarray(all_vecs[sid * shard_size: (sid + 1) * shard_size])
        for sid in range(n_shards)
        if all_vecs[sid * shard_size: (sid + 1) * shard_size].shape[0] > 0
    ]

    def build_cb(step, pct, detail=""):
        if progress_cb:
            progress_cb(step, round(60.0 + pct * 0.4, 1), detail)

    total_indexed = _parallel_build_shards(
        shard_chunks, output_dir, "ivfpq",
        {"nlist": nlist, "m": m, "nbits": nbits, "add_batch_size": add_batch_size},
        build_cb,
    )
    del all_vecs
    return total_indexed


# ---------------------------------------------------------------------------
# Phase 2c: Build HNSW index
# ---------------------------------------------------------------------------

def blocking_build_hnsw(
    sequences: list,
    model,
    tokenizer,
    output_dir: str,
    hnsw_m: int = None,
    ef_construction: int = None,
    progress_cb: Optional[Callable] = None,
) -> int:
    hnsw_m = hnsw_m if hnsw_m is not None else get_hnsw_m()
    ef_construction = ef_construction if ef_construction is not None else get_hnsw_ef_construction()

    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    max_per_shard = get_max_per_shard()
    n_shards = max(1, math.ceil(total / max_per_shard))
    shard_size = math.ceil(total / n_shards)

    # Encoding phase (0–60%)
    def enc_cb(step, pct, detail):
        if progress_cb:
            progress_cb(step, round(pct * 0.6, 1), detail)

    all_vecs = _batch_encode_sequences(sequences, model, tokenizer, progress_cb=enc_cb)

    # Build phase (60–100%)
    shard_chunks = [
        np.ascontiguousarray(all_vecs[sid * shard_size: (sid + 1) * shard_size])
        for sid in range(n_shards)
        if all_vecs[sid * shard_size: (sid + 1) * shard_size].shape[0] > 0
    ]

    def build_cb(step, pct, detail=""):
        if progress_cb:
            progress_cb(step, round(60.0 + pct * 0.4, 1), detail)

    total_indexed = _parallel_build_shards(
        shard_chunks, output_dir, "hnsw",
        {"hnsw_m": hnsw_m, "ef_construction": ef_construction},
        build_cb,
    )
    del all_vecs
    return total_indexed
