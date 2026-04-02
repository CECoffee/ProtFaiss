"""\\history command — list and view past search results."""
from app.cli.ipc_client import get_client, IpcError


def run(args: list[str]) -> None:
    if args and not args[0].startswith("-"):
        _detail(args[0])
    else:
        _list(args)


def _list(args: list[str]) -> None:
    limit = 20
    offset = 0
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--offset" and i + 1 < len(args):
            offset = int(args[i + 1]); i += 2
        else:
            i += 1

    client = get_client()
    try:
        data = client.call("search.history_list", {"limit": limit, "offset": offset})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
        return

    tasks = data.get("tasks", [])
    total = data.get("total", 0)
    if not tasks:
        print("No search history found.")
        return

    print(f"\nSearch History ({offset + 1}–{offset + len(tasks)} of {total})")
    print(f"  {'Task ID':<12} {'Dataset':<24} {'Submitted':<22} {'Hits':<6} {'GPU(s)'}")
    print("  " + "-" * 80)
    for t in tasks:
        tid = (t.get("search_task_id") or "")[:10]
        ds = str(t.get("dataset_name") or "—")[:22]
        sub = str(t.get("submitted_at") or "")[:19].replace("T", " ")
        hits = t.get("hit_count", 0)
        gpu = t.get("gpu_seconds") or 0
        print(f"  {tid:<12} {ds:<24} {sub:<22} {hits:<6} {gpu:.2f}")
    print()


def _detail(task_id: str) -> None:
    client = get_client()
    try:
        data = client.call("search.history_detail", {"search_task_id": task_id})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
        return

    ds = data.get("dataset_name") or "—"
    sub = str(data.get("submitted_at") or "")[:19].replace("T", " ")
    gpu = data.get("gpu_seconds") or 0
    hits = data.get("hits", [])

    print(f"\nTask:    {task_id}")
    print(f"Dataset: {ds}  |  Submitted: {sub}  |  GPU: {gpu:.2f}s")

    if data.get("legacy"):
        print("(No saved hits — search predates history feature)")
        return

    if not hits:
        print("No hits.")
        return

    print(f"\n  {'#':<4} {'ID':<8} {'Dist':<10} {'Header':<40} {'KO':<12} {'EC'}")
    print("  " + "-" * 90)
    for h in hits:
        print(
            f"  {h.get('rank', ''):<4} {str(h.get('protein_row_id', '')):<8} "
            f"{h.get('faiss_distance', 0):<10.4f} "
            f"{str(h.get('original_header', ''))[:38]:<40} "
            f"{str(h.get('ko_number', '')):<12} {h.get('ec_number', '')}"
        )
    print()
