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
            f"  {str(t.get('task_id',''))[:10]:<12} {t.get('task_type',''):<8} "
            f"{t.get('status',''):<10} {str(t.get('user_id',''))[:10]:<12} {age:.0f}s"
        )


def cmd_cancel(args: list[str]) -> None:
    if not args:
        print("Usage: \\cancel <task_id>"); return
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
