"""\\search command — submit a search and poll until done."""
import time

from app.cli.ipc_client import get_client, IpcError


def run(args: list[str]) -> None:
    if not args:
        print("Usage: \\search <sequence> [--top_k N] [--pooling mean|max]")
        return

    sequence = args[0]
    top_k = 5
    pooling = "mean"

    i = 1
    while i < len(args):
        if args[i] == "--top_k" and i + 1 < len(args):
            top_k = int(args[i + 1]); i += 2
        elif args[i] == "--pooling" and i + 1 < len(args):
            pooling = args[i + 1]; i += 2
        else:
            i += 1

    client = get_client()
    try:
        result = client.call("search.submit", {"sequence": sequence, "top_k": top_k, "pooling": pooling})
        task_id = result["task_id"]
        print(f"Task {task_id[:8]}… submitted, waiting…")

        # Poll until done
        while True:
            task = client.call("search.result", {"task_id": task_id})
            status = task.get("status")
            if status == "done":
                _print_results(task)
                return
            elif status == "error":
                print(f"Error: {task.get('error')}")
                return
            else:
                idx_status = task.get("index_status", "")
                print(f"  [{status}] index:{idx_status}", end="\r", flush=True)
                time.sleep(0.5)
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def _print_results(task: dict) -> None:
    results = task.get("result", [])
    times = task.get("times", {})
    print(f"\nResults ({times.get('total_time', 0):.2f}s):")
    print(f"  {'#':<4} {'ID':<8} {'Dist':<10} {'Header':<40} {'KO':<12} {'EC'}")
    print("  " + "-" * 90)
    for i, r in enumerate(results, 1):
        print(
            f"  {i:<4} {str(r.get('id','')):<8} {r.get('faiss_distance', 0):<10.4f} "
            f"{str(r.get('header',''))[:38]:<40} {str(r.get('ko','')):<12} {r.get('ec','')}"
        )
