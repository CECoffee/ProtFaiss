"""\\build and \\build-status commands."""
import os
import time

from app.cli.ipc_client import get_client, IpcError


def cmd_build(args: list[str]) -> None:
    if not args:
        print("Usage: build <fasta_path> [--name NAME] [--algorithm flat|ivfpq|hnsw]")
        return

    name = None
    algorithm = "flat"
    positional = []

    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]; i += 2
        elif args[i] == "--algorithm" and i + 1 < len(args):
            algorithm = args[i + 1]; i += 2
        else:
            positional.append(args[i]); i += 1

    if not positional:
        print("Usage: build <fasta_path> [--name NAME] [--algorithm flat|ivfpq|hnsw]")
        return
    fasta_path = positional[0]
    if not os.path.isfile(fasta_path):
        print(f"File not found: {fasta_path}"); return

    if name is None:
        name = os.path.basename(fasta_path)

    client = get_client()
    try:
        result = client.call("build.submit", {
            "fasta_tmp_path": fasta_path,
            "name": name,
            "algorithm": algorithm,
        })
        dataset_id = result["dataset_id"]
        print(f"Build started: {dataset_id[:8]} ({name}, {algorithm})")
        print("Polling progress (Ctrl+C to stop polling, build continues in background)…")

        while True:
            try:
                status = client.call("build.status", {"dataset_id": dataset_id})
                step = status.get("progress_step", "")
                pct = status.get("progress_pct") or 0
                detail = status.get("progress_detail", "")
                s = status.get("status", "")
                print(f"  [{s}] {step} {pct:.1f}% {detail}\x1b[K", end="\r", flush=True)
                if s in ("ready", "error"):
                    print()
                    if s == "ready":
                        print(f"Build complete: {status.get('num_indexed')} sequences indexed.")
                    else:
                        print(f"Build failed: {status.get('error_msg')}")
                    return
                time.sleep(2)
            except KeyboardInterrupt:
                print(f"\nStopped polling. Dataset ID: {dataset_id}")
                return
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_build_status(args: list[str]) -> None:
    if not args:
        print("Usage: build-status <dataset_id>"); return
    client = get_client()
    try:
        status = client.call("build.status", {"dataset_id": args[0]})
        for k, v in status.items():
            print(f"  {k}: {v}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
