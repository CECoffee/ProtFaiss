"""export and import CLI commands."""
import os
import time

from app.cli.ipc_client import get_client, IpcError


def cmd_export(args: list) -> None:
    """
    Usage: export <dataset_id> [--output <path>]

    Export a dataset (FASTA + FAISS index) to a .7z archive.
    """
    if not args:
        print("Usage: export <dataset_id> [--output <path>]")
        return

    output_path = None
    positional = []

    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        else:
            positional.append(args[i]); i += 1

    if not positional:
        print("Usage: export <dataset_id> [--output <path>]")
        return
    dataset_id = positional[0]

    client = get_client()
    try:
        client.call("dataset.export", {"dataset_id": dataset_id})
        print(f"Export started: {dataset_id[:8]}")
        print("Polling progress (Ctrl+C to stop polling, export continues in background)…")

        while True:
            try:
                status = client.call("dataset.export_status", {"dataset_id": dataset_id})
                s = status.get("status", "")
                if s == "done":
                    print()
                    src = status.get("export_path", "")
                    size_mb = (status.get("file_size") or 0) / 1024 / 1024
                    print(f"Export complete: {src} ({size_mb:.1f} MB)")
                    if output_path and src and os.path.isfile(src):
                        import shutil
                        shutil.copy2(src, output_path)
                        print(f"Copied to: {output_path}")
                    return
                elif s == "error":
                    print()
                    print("Export failed.")
                    return
                else:
                    print(f"  [{s}] …\x1b[K", end="\r", flush=True)
                time.sleep(2)
            except KeyboardInterrupt:
                print(f"\nStopped polling. Export continues in background.")
                print(f"Check status with: export-status {dataset_id}")
                return

    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_export_status(args: list) -> None:
    """Usage: export-status <dataset_id>"""
    if not args:
        print("Usage: export-status <dataset_id>")
        return
    client = get_client()
    try:
        status = client.call("dataset.export_status", {"dataset_id": args[0]})
        s = status.get("status", "unknown")
        print(f"  Status: {s}")
        if s == "done":
            export_path = status.get("export_path", "")
            size_mb = (status.get("file_size") or 0) / 1024 / 1024
            print(f"  File:   {export_path} ({size_mb:.1f} MB)")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_import(args: list) -> None:
    """
    Usage: import <archive_path> [--name NAME]

    Import a dataset from a .7z archive exported by ProtFaiss.
    The archive must contain FAISS index files; the dataset will be
    ready immediately without any GPU rebuild.
    """
    if not args:
        print("Usage: import <archive_path> [--name NAME]")
        return

    name = ""
    positional = []

    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]
            i += 2
        else:
            positional.append(args[i]); i += 1

    if not positional:
        print("Usage: import <archive_path> [--name NAME]")
        return
    archive_path = positional[0]
    if not os.path.isfile(archive_path):
        print(f"File not found: {archive_path}")
        return

    client = get_client()
    try:
        result = client.call("dataset.import", {
            "archive_tmp_path": archive_path,
            "name": name,
        })
        dataset_id = result.get("dataset_id", "")
        print(f"Import started: {dataset_id[:8]}")
        print("Polling progress (Ctrl+C to stop polling)…")

        while True:
            try:
                status = client.call("build.status", {"dataset_id": dataset_id})
                step = status.get("progress_step", "")
                pct = status.get("progress_pct") or 0
                s = status.get("status", "")
                print(f"  [{s}] {step} {pct:.1f}%\x1b[K", end="\r", flush=True)
                if s == "ready":
                    print()
                    print(f"Import complete: {status.get('num_indexed') or status.get('num_sequences')} sequences ready.")
                    return
                elif s == "error":
                    print()
                    print(f"Import failed: {status.get('error_msg')}")
                    return
                time.sleep(2)
            except KeyboardInterrupt:
                print(f"\nStopped polling. Dataset ID: {dataset_id}")
                return

    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
