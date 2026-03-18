"""
Standalone build worker for FaaIndex dataset builder.

Run as a subprocess:
  python -m app.build.worker --config <path_to_build_config.json>

Progress is written directly to the PostgreSQL datasets table.
This process is terminated by the main FastAPI server on shutdown.
"""
import argparse
import json
import sys
import time


def _patch(dataset_id: str, step: str, pct: float, detail: str = "", **kwargs) -> None:
    from app.build.dataset_db import blocking_update_dataset
    patch = {
        "progress_step": step,
        "progress_pct": round(pct, 1),
        "progress_detail": f"{step} {pct:.1f}%({detail})" if detail else f"{step} {pct:.1f}%",
    }
    patch.update(kwargs)
    blocking_update_dataset(dataset_id, patch)


def run_build_job(config: dict) -> None:
    from app.build.dataset_db import blocking_update_dataset
    from app.build.index_builder import (
        blocking_fasta_to_db, blocking_build_flat, blocking_build_ivfpq,
        blocking_build_hnsw, fasta_data_iterator,
    )
    from app.core import encoder as _encoder

    dataset_id = config["dataset_id"]
    fasta_path = config["fasta_path"]
    db_table = config["db_table"]
    index_dir = config["index_dir"]
    algorithm = config["algorithm"]
    nlist = config["nlist"]
    pq_m = config["pq_m"]
    nbits = config["nbits"]
    hnsw_m = config["hnsw_m"]
    ef_construction = config["ef_construction"]

    _last_write = [0.0]

    def throttled_patch(step, pct, detail="", force=False, **kwargs):
        now = time.monotonic()
        if force or (now - _last_write[0]) >= 2.0:
            _patch(dataset_id, step, pct, detail, **kwargs)
            _last_write[0] = now

    try:
        _patch(dataset_id, "importing", 0)

        num_sequences = sum(1 for _ in fasta_data_iterator(fasta_path))
        blocking_update_dataset(dataset_id, {"num_sequences": num_sequences})

        def db_progress(step, pct):
            if step == "importing_done":
                blocking_update_dataset(dataset_id, {
                    "progress_step": "importing",
                    "progress_pct": 40,
                    "progress_detail": "importing 40.0%",
                    "num_sequences": pct,
                })

        total_inserted = blocking_fasta_to_db(fasta_path, db_table, db_progress)
        _patch(dataset_id, "importing", 40, num_sequences=total_inserted)

        _patch(dataset_id, "building", 40)
        sequences = [record[4] for record in fasta_data_iterator(fasta_path)]

        model = _encoder.ESM2_MODEL
        tokenizer = _encoder.ESM2_TOKENIZER

        def scaled_cb(step, pct, detail=""):
            scaled = round(40.0 + pct * 0.6, 1)
            throttled_patch(step, scaled, detail)

        if algorithm == "flat":
            num_indexed = blocking_build_flat(sequences, model, tokenizer, index_dir, scaled_cb)
        elif algorithm == "ivfpq":
            num_indexed = blocking_build_ivfpq(
                sequences, model, tokenizer, index_dir, nlist, pq_m, nbits, scaled_cb
            )
        elif algorithm == "hnsw":
            num_indexed = blocking_build_hnsw(
                sequences, model, tokenizer, index_dir, hnsw_m, ef_construction, scaled_cb
            )
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        blocking_update_dataset(dataset_id, {
            "status": "ready",
            "progress_step": "done",
            "progress_pct": 100,
            "progress_detail": "done 100.0%",
            "num_indexed": num_indexed,
        })
        print(f"Build job {dataset_id} completed: {num_indexed} vectors indexed.")

    except Exception as e:
        print(f"Build job {dataset_id} failed: {e}", file=sys.stderr)
        from app.build.dataset_db import blocking_update_dataset as _upd
        _upd(dataset_id, {
            "status": "error",
            "error_msg": str(e),
            "progress_step": "error",
            "progress_detail": f"error: {e}",
        })
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ProtFaiss build worker")
    parser.add_argument("--config", required=True, help="Path to build_config.json")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    from app.core.encoder import init_model
    from app.core.db import init_db_pool
    from app.core.config import ESM2_MODEL_DIR
    from app.core.gpu import log_gpu_status

    print(f"Build worker starting for dataset {config['dataset_id']} ...")
    log_gpu_status()
    init_model(ESM2_MODEL_DIR)
    init_db_pool()

    run_build_job(config)


if __name__ == "__main__":
    main()
