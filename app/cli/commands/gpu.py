"""\\gpu and \\cancel commands."""
from app.cli.ipc_client import get_client, IpcError


def cmd_gpu(args: list[str]) -> None:
    client = get_client()
    try:
        data = client.call("gpu.queue", {})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}"); return

    pool = data.get("pool", {})
    tasks = data.get("tasks", [])
    used = pool.get("used_slots", 0)
    total = pool.get("total_slots", 0)
    print(f"\nGPU Pool: {used}/{total} slots used")

    if not tasks:
        print("  No tasks in queue.")
        return

    print(f"\n  {'Task ID':<12} {'Type':<8} {'Status':<10} {'User':<12} {'Age'}")
    print("  " + "-" * 60)
    import time
    now = time.time()
    for t in tasks:
        age = now - (t.get("created_at") or now)
        print(
            f"  {str(t.get('id',''))[:10]:<12} {t.get('task_type',''):<8} "
            f"{t.get('status',''):<10} {str(t.get('user_id',''))[:10]:<12} {age:.0f}s"
        )


def cmd_cancel(args: list[str]) -> None:
    if not args:
        print("Usage: cancel <task_id>"); return
    client = get_client()
    try:
        result = client.call("gpu.cancel", {"task_id": args[0]})
        print(f"Cancelled: {result['cancelled']}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_gpu_status(args: list[str]) -> None:
    client = get_client()
    try:
        data = client.call("gpu.status", {})
        for k, v in data.items():
            print(f"  {k}: {v}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_gpu_history(args: list[str]) -> None:
    client = get_client()
    params = {"limit": 50, "offset": 0}

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            params["limit"] = int(args[i + 1])
            i += 2
        elif args[i] == "--offset" and i + 1 < len(args):
            params["offset"] = int(args[i + 1])
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            params["status_filter"] = args[i + 1].split(",")
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            params["task_type_filter"] = args[i + 1]
            i += 2
        elif args[i] == "--user" and i + 1 < len(args):
            params["user_id_filter"] = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        data = client.call("gpu.admin_history", params)
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
        return

    tasks = data.get("tasks", [])
    total = data.get("total", 0)
    has_more = data.get("has_more", False)

    if not tasks:
        print("  No historical tasks found.")
        return

    print(f"\nGPU Task History (showing {len(tasks)} of {total} total)")
    print(f"  {'ID':<10} {'User':<12} {'Type':<8} {'Status':<10} {'GPU(s)':<8} {'Completed'}")
    print("  " + "-" * 70)

    for t in tasks:
        task_id = str(t.get("id", ""))[:8]
        username = t.get("username", "")[:10]
        task_type = t.get("task_type", "")[:7]
        status = t.get("status", "")
        gpu_sec = t.get("gpu_seconds", 0) or 0
        completed = t.get("completed_at", "")[:19] if t.get("completed_at") else "N/A"

        print(f"  {task_id:<10} {username:<12} {task_type:<8} {status:<10} {gpu_sec:<8.1f} {completed}")

    if has_more:
        print(f"\n  (Use --offset {params['offset'] + params['limit']} to see more)")
