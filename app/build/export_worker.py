"""
Standalone export/import worker subprocess.

Run as:
  python -m app.build.export_worker --config <path_to_config.json>

Config JSON must contain a "job_type" key:

  "export"
    dataset_id, output_path, include_index

  "import_with_index"
    dataset_id, archive_path, dataset_dir, index_dir, fasta_path,
    db_table, manifest

Progress is written to the PostgreSQL datasets table (for import jobs).
Export jobs write an output file; status is determined by the daemon.
"""
import argparse
import json
import os
import sys
import time


def _patch(dataset_id: str, step: str, pct: float, detail: str = "", **kwargs) -> None:
    from app.build.dataset_db import blocking_update_dataset
    patch = {
        "progress_step": step,
        "progress_pct": round(pct, 1),
        "progress_detail": (
            f"{step} {pct:.1f}%({detail})" if detail else f"{step} {pct:.1f}%"
        ),
    }
    patch.update(kwargs)
    blocking_update_dataset(dataset_id, patch)


# ---------------------------------------------------------------------------
# Export job
# ---------------------------------------------------------------------------

def run_export_job(config: dict) -> None:
    from app.build.dataset_db import blocking_get_dataset
    from app.build.export_import import blocking_export_dataset, blocking_fasta_from_db

    dataset_id = config["dataset_id"]
    output_path = config["output_path"]

    entry = blocking_get_dataset(dataset_id)
    if not entry:
        print(f"[export_worker] Dataset {dataset_id} not found", file=sys.stderr)
        sys.exit(1)

    fasta_path = entry["fasta_path"]
    tmp_fasta = None

    # Fallback: regenerate FASTA from the PostgreSQL protein table when the
    # original file is missing (e.g. it was deleted after indexing).
    if not fasta_path or not os.path.isfile(fasta_path):
        import tempfile
        db_table = entry.get("db_table")
        if not db_table:
            print(
                "[export_worker] input.fasta missing and no db_table — cannot export",
                file=sys.stderr,
            )
            sys.exit(1)

        print(
            f"[export_worker] input.fasta not found; rebuilding from DB table {db_table!r}",
            flush=True,
        )
        tmp_fd, tmp_fasta = tempfile.mkstemp(suffix=".fasta")
        os.close(tmp_fd)
        blocking_fasta_from_db(
            db_table=db_table,
            output_path=tmp_fasta,
            progress_cb=lambda step, pct: print(f"[export] {step} {pct:.1f}%", flush=True),
        )
        fasta_path = tmp_fasta

    _last_write = [0.0]

    def progress_cb(step: str, pct: float) -> None:
        now = time.monotonic()
        if step == "done" or (now - _last_write[0]) >= 2.0:
            print(f"[export] {step} {pct:.1f}%", flush=True)
            _last_write[0] = now

    try:
        blocking_export_dataset(
            fasta_path=fasta_path,
            dataset_id=dataset_id,
            manifest_data=entry,
            output_path=output_path,
            progress_cb=progress_cb,
        )
    finally:
        if tmp_fasta and os.path.isfile(tmp_fasta):
            try:
                os.remove(tmp_fasta)
            except OSError:
                pass

    print(f"[export_worker] Export complete: {output_path}")


# ---------------------------------------------------------------------------
# Import-with-index job
# ---------------------------------------------------------------------------

def run_import_with_index_job(config: dict) -> None:
    from app.build.dataset_db import blocking_update_dataset
    from app.build.export_import import blocking_import_with_index
    from app.build.index_builder import blocking_fasta_to_db

    dataset_id = config["dataset_id"]
    archive_path = config["archive_path"]
    dataset_dir = config["dataset_dir"]
    fasta_path = config["fasta_path"]
    db_table = config["db_table"]
    manifest = config["manifest"]

    _last_write = [0.0]

    def progress_cb(step: str, pct: float) -> None:
        now = time.monotonic()
        if step in ("done", "extracted") or (now - _last_write[0]) >= 2.0:
            _patch(dataset_id, step, pct)
            _last_write[0] = now

    try:
        _patch(dataset_id, "extracting", 0)

        blocking_import_with_index(
            archive_path=archive_path,
            dataset_dir=dataset_dir,
            progress_cb=progress_cb,
        )

        # Import sequences into the protein DB table
        _patch(dataset_id, "importing_db", 82)
        total_inserted = blocking_fasta_to_db(fasta_path, db_table, lambda *_: None)

        num_indexed = manifest.get("dataset", {}).get("num_indexed") or total_inserted
        blocking_update_dataset(dataset_id, {
            "status": "ready",
            "progress_step": "done",
            "progress_pct": 100,
            "progress_detail": "done 100.0%",
            "num_sequences": total_inserted,
            "num_indexed": num_indexed,
        })
        print(f"[export_worker] Import complete: {dataset_id} ({total_inserted} sequences)")

    except Exception as exc:
        print(f"[export_worker] Import failed: {exc}", file=sys.stderr)
        blocking_update_dataset(dataset_id, {
            "status": "error",
            "error_msg": str(exc),
            "progress_step": "error",
            "progress_detail": f"error: {exc}",
        })
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ProtFaiss export/import worker")
    parser.add_argument("--config", required=True, help="Path to job config JSON")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    job_type = config.get("job_type")
    print(f"[export_worker] Starting job_type={job_type!r}")

    from app.core.db import init_db_pool
    init_db_pool()

    if job_type == "export":
        run_export_job(config)
    elif job_type == "import_with_index":
        run_import_with_index_job(config)
    else:
        print(f"[export_worker] Unknown job_type: {job_type!r}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
