"""
Blocking export/import functions for dataset 7z archives.

Archive structure:
  manifest.json             -- metadata envelope
  input.fasta               -- always present
  indices/                  -- always present (one or more .faiss shards)
    shard_000.faiss
    ...

All functions are synchronous (blocking), safe to call from a subprocess
or a ThreadPoolExecutor.  They have no FastAPI or asyncio dependencies.
"""
import glob
import json
import os
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

ARCHIVE_FORMAT_VERSION = 1


def _safe_relative(path: str) -> bool:
    """True if *path* is a safe relative path (no traversal, not absolute)."""
    if os.path.isabs(path):
        return False
    norm = os.path.normpath(path)
    parts = norm.replace("\\", "/").split("/")
    return ".." not in parts


# ---------------------------------------------------------------------------
# Rebuild FASTA from PostgreSQL (fallback when input.fasta is missing)
# ---------------------------------------------------------------------------

def blocking_fasta_from_db(
    db_table: str,
    output_path: str,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> int:
    """
    Stream all sequences from *db_table* and write them as a FASTA file
    to *output_path*.  Returns the number of sequences written.

    Used as a fallback when the original input.fasta file has been deleted.
    """
    from app.core.db import get_pool

    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{db_table}"')
            total = cur.fetchone()[0]

        if progress_cb:
            progress_cb("rebuilding_fasta", 0.0)

        written = 0
        with conn.cursor(name="fasta_export_cursor") as cur:
            cur.itersize = 1000
            cur.execute(
                f'SELECT original_header, sequence FROM "{db_table}" ORDER BY id'
            )
            with open(output_path, "w", encoding="utf-8") as fh:
                for original_header, sequence in cur:
                    fh.write(f">{original_header}\n{sequence}\n")
                    written += 1
                    if progress_cb and total and written % 1000 == 0:
                        progress_cb(
                            "rebuilding_fasta",
                            round(written / total * 100, 1),
                        )

        if progress_cb:
            progress_cb("rebuilding_fasta", 100.0)

        return written
    finally:
        pool.putconn(conn)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def blocking_export_dataset(
    fasta_path: str,
    dataset_id: str,
    manifest_data: Dict,
    output_path: str,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> str:
    """
    Create a 7z archive at *output_path* containing the dataset.
    Always includes FASTA and all FAISS index shards.

    manifest_data: dict with at least name, algorithm, num_sequences, num_indexed.
    Returns output_path on success.
    """
    import py7zr
    from app.core import config_loader
    from app.core.config import DATASETS_ROOT as _DATASETS_ROOT_DEFAULT
    index_dir = os.path.join(
        config_loader.get("storage", "datasets_root", "") or _DATASETS_ROOT_DEFAULT,
        dataset_id, "indices",
    )

    # Collect index files (sorted for reproducibility)
    index_files: List[str] = []
    if os.path.isdir(index_dir):
        index_files = sorted(glob.glob(os.path.join(index_dir, "*.faiss")))

    manifest = {
        "version": ARCHIVE_FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "name": manifest_data.get("name", ""),
            "algorithm": manifest_data.get("algorithm", ""),
            "num_sequences": manifest_data.get("num_sequences") or 0,
            "num_indexed": manifest_data.get("num_indexed") or 0,
        },
        "files": {
            "fasta": "input.fasta",
            "indices": [f"indices/{os.path.basename(f)}" for f in index_files],
        },
        "index_params": {
            "algorithm": manifest_data.get("algorithm", ""),
            "embedding_dim": 1280,
        },
    }

    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    total_steps = 2 + len(index_files)  # manifest + fasta + each .faiss
    step = 0

    if progress_cb:
        progress_cb("exporting", 0.0)

    with py7zr.SevenZipFile(output_path, mode="w") as archive:
        # manifest.json
        archive.writestr(manifest_bytes, "manifest.json")
        step += 1
        if progress_cb:
            progress_cb("exporting", round(step / total_steps * 100, 1))

        # FASTA
        archive.write(fasta_path, "input.fasta")
        step += 1
        if progress_cb:
            progress_cb("exporting", round(step / total_steps * 100, 1))

        # FAISS shards (stored raw; LZMA2 handles compression)
        for idx_file in index_files:
            archive.write(idx_file, f"indices/{os.path.basename(idx_file)}")
            step += 1
            if progress_cb:
                progress_cb("exporting", round(step / total_steps * 100, 1))

    if progress_cb:
        progress_cb("done", 100.0)

    return output_path


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def blocking_validate_archive(archive_path: str) -> Dict:
    """
    Open the 7z archive, read manifest.json, validate structure.
    Returns the parsed manifest dict.
    Raises ValueError with a descriptive message on any problem.
    """
    import py7zr

    if not os.path.isfile(archive_path):
        raise ValueError(f"Archive not found: {archive_path}")

    try:
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            names = archive.getnames()

            if "manifest.json" not in names:
                raise ValueError("Archive is missing manifest.json")
            if "input.fasta" not in names:
                raise ValueError("Archive is missing input.fasta")

            raw_dict = archive.read(["manifest.json"])
            raw = raw_dict["manifest.json"].read()
            manifest = json.loads(raw.decode("utf-8"))

            version = manifest.get("version")
            if version != ARCHIVE_FORMAT_VERSION:
                raise ValueError(
                    f"Unsupported archive version {version!r} "
                    f"(expected {ARCHIVE_FORMAT_VERSION})"
                )

            if "dataset" not in manifest or "files" not in manifest:
                raise ValueError("manifest.json missing 'dataset' or 'files' section")

            # Require at least one index file.
            declared_indices = manifest.get("files", {}).get("indices", [])
            if not declared_indices:
                raise ValueError(
                    "Archive contains no index files. "
                    "Only archives exported with index files can be imported."
                )

            # Verify every declared index file actually exists in the archive
            # and has a safe relative path.
            for idx_path in declared_indices:
                if not _safe_relative(idx_path):
                    raise ValueError(f"Unsafe path in manifest: {idx_path!r}")
                if idx_path not in names:
                    raise ValueError(
                        f"Declared index file missing from archive: {idx_path!r}"
                    )

    except py7zr.exceptions.Bad7zFile as exc:
        raise ValueError(f"Invalid 7z archive: {exc}") from exc

    return manifest


# ---------------------------------------------------------------------------
# Import with pre-built index
# ---------------------------------------------------------------------------

def blocking_import_with_index(
    archive_path: str,
    dataset_dir: str,
    progress_cb: Optional[Callable[[str, float], None]] = None,
) -> None:
    """
    Extract input.fasta and all indices/*.faiss files into *dataset_dir*.

    The archive structure mirrors the dataset directory layout, so
    extractall(path=dataset_dir) produces the correct file tree:
      dataset_dir/input.fasta
      dataset_dir/indices/shard_000.faiss
      ...

    Caller must have already validated the archive with blocking_validate_archive.
    """
    import py7zr

    if progress_cb:
        progress_cb("extracting", 10.0)

    os.makedirs(dataset_dir, exist_ok=True)
    index_dir = os.path.join(dataset_dir, "indices")
    os.makedirs(index_dir, exist_ok=True)

    with py7zr.SevenZipFile(archive_path, mode="r") as archive:
        names = archive.getnames()
        targets = [n for n in names if n == "input.fasta" or n.startswith("indices/")]
        archive.extractall(path=dataset_dir, targets=targets)

    if progress_cb:
        progress_cb("extracted", 80.0)
