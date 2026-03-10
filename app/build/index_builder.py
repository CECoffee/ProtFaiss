"""
Blocking index build functions for the dataset builder.
All functions are designed to run in a ThreadPoolExecutor.

progress_cb(step_name: str, pct: float) is called to report progress.
It bridges thread updates to the event loop via asyncio.run_coroutine_threadsafe.
"""
import os
import re
import math
from typing import Callable, Optional

import faiss
import numpy as np
import torch
from torch.utils.data import DataLoader

from .config import (
    HNSW_M, HNSW_EF_CONSTRUCTION,
    IVFPQ_NLIST, IVFPQ_M, IVFPQ_NBITS,
)
from .db_operations import blocking_create_protein_table, blocking_insert_protein_batch

# ESM2 encoding constants
EMBEDDING_DIM = 1280
ENCODING_BATCH = 32
MAX_PER_SHARD = 500_000
DB_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# FASTA parsing helpers (adapted from tools/insert_fasta_to_db.py)
# ---------------------------------------------------------------------------

def parse_fasta_header(header_string: str):
    """
    Parse a FASTA header string to extract accession, KO and EC numbers.
    Returns: (accession, ko, ec)
    """
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
# ESM2 batch encoder (adapted from tools/build_index_ivfpq.py)
# ---------------------------------------------------------------------------

def _make_collate_fn(tokenizer):
    def collate_fn(batch):
        return tokenizer(batch, return_tensors="pt", padding=True, max_length=2048, truncation=True)
    return collate_fn


def _batch_encode_sequences(sequences, model, tokenizer, batch_size=ENCODING_BATCH, pooling='mean'):
    """
    Encode a list of protein sequences to ESM2 embeddings.
    Returns: np.ndarray (N, EMBEDDING_DIM) float32
    """
    collate_fn = _make_collate_fn(tokenizer)
    loader = DataLoader(
        sequences,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=collate_fn,
    )
    device = next(model.parameters()).device
    embeddings = []

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            features = outputs.last_hidden_state  # (B, L, D)
            masked = features * attention_mask.unsqueeze(2)
            if pooling == 'mean':
                pooled = masked.sum(dim=1) / attention_mask.sum(dim=1, keepdim=True)
            elif pooling == 'max':
                pooled = torch.max(masked, dim=1).values
            else:
                pooled = features[:, 0, :]
            embeddings.append(pooled.detach().cpu().numpy())

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
    """
    Import a FASTA file into a new PostgreSQL table.
    Returns total number of sequences inserted.
    """
    blocking_create_protein_table(db_table)

    current_id = 0
    batch = []

    for record in fasta_data_iterator(fasta_path):
        original_header, accession, ko, ec, sequence, seq_len, ph_val = record
        batch.append((original_header, accession, ko, ec, sequence, seq_len, ph_val))

        if len(batch) >= DB_BATCH_SIZE:
            blocking_insert_protein_batch(db_table, batch, current_id)
            current_id += len(batch)
            batch = []
            if progress_cb:
                progress_cb("importing", None)  # pct=None means indeterminate during import

    if batch:
        blocking_insert_protein_batch(db_table, batch, current_id)
        current_id += len(batch)

    if progress_cb:
        progress_cb("importing_done", current_id)

    return current_id


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
    """
    Build a sharded FlatL2 FAISS index from a list of sequences.
    Returns total vectors indexed.
    """
    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    n_shards = max(1, math.ceil(total / MAX_PER_SHARD))
    shard_size = math.ceil(total / n_shards)

    total_indexed = 0

    for shard_id in range(n_shards):
        shard_seqs = sequences[shard_id * shard_size: (shard_id + 1) * shard_size]
        if not shard_seqs:
            continue

        vecs = _batch_encode_sequences(shard_seqs, model, tokenizer)

        index = faiss.IndexFlatL2(EMBEDDING_DIM)
        index.add(vecs)

        shard_path = os.path.join(output_dir, f"shard_{shard_id:03d}.faiss")
        faiss.write_index(index, shard_path)
        total_indexed += len(shard_seqs)

        if progress_cb:
            pct = int((shard_id + 1) / n_shards * 100)
            progress_cb("building", pct)

        del vecs

    return total_indexed


# ---------------------------------------------------------------------------
# Phase 2b: Build IVF-PQ index
# ---------------------------------------------------------------------------

def blocking_build_ivfpq(
    sequences: list,
    model,
    tokenizer,
    output_dir: str,
    nlist: int = IVFPQ_NLIST,
    m: int = IVFPQ_M,
    nbits: int = IVFPQ_NBITS,
    progress_cb: Optional[Callable] = None,
) -> int:
    """
    Build a sharded IVF-PQ FAISS index from a list of sequences.
    Returns total vectors indexed.
    """
    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    n_shards = max(1, math.ceil(total / MAX_PER_SHARD))
    shard_size = math.ceil(total / n_shards)
    train_sample = max(nlist * 40, min(200_000, total))

    total_indexed = 0
    use_gpu = torch.cuda.is_available()

    for shard_id in range(n_shards):
        shard_seqs = sequences[shard_id * shard_size: (shard_id + 1) * shard_size]
        if not shard_seqs:
            continue

        vecs = _batch_encode_sequences(shard_seqs, model, tokenizer)
        n = vecs.shape[0]

        quantizer = faiss.IndexFlatL2(EMBEDDING_DIM)
        index_cpu = faiss.IndexIVFPQ(quantizer, EMBEDDING_DIM, nlist, m, nbits)
        index_cpu.nprobe = 16

        sample_size = min(n, train_sample)
        if sample_size < nlist:
            # fallback: use all vectors for training
            sample_size = n
        perm = np.random.permutation(n)[:sample_size]
        train_vecs = np.ascontiguousarray(vecs[perm])

        if use_gpu:
            res = faiss.StandardGpuResources()
            index_gpu = faiss.index_cpu_to_gpu(res, 0, index_cpu)
            index_gpu.train(train_vecs)
            # Add in batches to avoid OOM
            add_batch = 200_000
            for i in range(0, n, add_batch):
                batch = np.ascontiguousarray(vecs[i:i + add_batch])
                index_gpu.add(batch)
            index_cpu = faiss.index_gpu_to_cpu(index_gpu)
            index_cpu.nprobe = 16
        else:
            index_cpu.train(train_vecs)
            index_cpu.add(vecs)

        shard_path = os.path.join(output_dir, f"shard_{shard_id:03d}.faiss")
        faiss.write_index(index_cpu, shard_path)
        total_indexed += n

        if progress_cb:
            pct = int((shard_id + 1) / n_shards * 100)
            progress_cb("building", pct)

        del vecs

    return total_indexed


# ---------------------------------------------------------------------------
# Phase 2c: Build HNSW index
# ---------------------------------------------------------------------------

def blocking_build_hnsw(
    sequences: list,
    model,
    tokenizer,
    output_dir: str,
    hnsw_m: int = HNSW_M,
    ef_construction: int = HNSW_EF_CONSTRUCTION,
    progress_cb: Optional[Callable] = None,
) -> int:
    """
    Build a sharded HNSW FAISS index from a list of sequences (CPU only).
    Returns total vectors indexed.
    """
    os.makedirs(output_dir, exist_ok=True)
    total = len(sequences)
    n_shards = max(1, math.ceil(total / MAX_PER_SHARD))
    shard_size = math.ceil(total / n_shards)
    total_indexed = 0

    for shard_id in range(n_shards):
        shard_seqs = sequences[shard_id * shard_size: (shard_id + 1) * shard_size]
        if not shard_seqs:
            continue

        vecs = _batch_encode_sequences(shard_seqs, model, tokenizer)

        index = faiss.IndexHNSWFlat(EMBEDDING_DIM, hnsw_m)
        index.hnsw.efConstruction = ef_construction
        index.add(vecs)

        shard_path = os.path.join(output_dir, f"shard_{shard_id:03d}.faiss")
        faiss.write_index(index, shard_path)
        total_indexed += len(shard_seqs)

        if progress_cb:
            pct = int((shard_id + 1) / n_shards * 100)
            progress_cb("building", pct)

        del vecs

    return total_indexed
