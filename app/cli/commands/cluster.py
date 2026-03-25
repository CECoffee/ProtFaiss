"""cluster and cluster-set commands — list/manage worker nodes."""
import time

from app.cli.ipc_client import get_client, IpcError

_STATUS_LABELS = {
    "online": "online",
    "dead": "DEAD",
    "available": "available",
    "unavailable": "DRAINED",
    "hidden": "hidden",
}


def _rel(ts: float) -> str:
    if not ts:
        return "—"
    diff = int(time.time() - ts)
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    return f"{diff // 3600}h ago"


def _bar(pct: float, width: int = 10) -> str:
    if pct < 0:
        return "N/A       "[:width]
    filled = round(pct / 100 * width)
    return f"[{'#' * filled}{'.' * (width - filled)}] {pct:5.1f}%"


def cmd_cluster(args: list[str]) -> None:
    """List all registered cluster workers with status and metrics."""
    client = get_client()
    try:
        data = client.call("cluster.list", {})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
        return

    workers = data.get("workers", [])
    if not workers:
        print("No workers registered.")
        return

    print()
    header = f"  {'Node ID':<24} {'Address':<20} {'Liveness':<8} {'Admin Status':<12} {'Slots':<6} {'Last Seen':<12} {'CPU':<17} {'Memory':<17}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for w in workers:
        metrics = w.get("metrics", {})
        cpu = metrics.get("cpu_percent", -1)
        mem_pct = metrics.get("memory_percent", -1)
        liveness = _STATUS_LABELS.get(w.get("status", ""), w.get("status", ""))
        admin_st = _STATUS_LABELS.get(w.get("admin_status", ""), w.get("admin_status", ""))
        print(
            f"  {w['node_id'][:22]:<24} {w.get('address','')[:18]:<20} "
            f"{liveness:<8} {admin_st:<12} "
            f"{w.get('gpu_slots', 0):<6} {_rel(w.get('last_seen', 0)):<12} "
            f"{_bar(cpu):<17} {_bar(mem_pct):<17}"
        )
        # Per-GPU line
        gpus = metrics.get("gpus", [])
        for g in gpus:
            util = g.get("utilization_percent", -1)
            vram_used = g.get("vram_used_mb", -1)
            vram_total = g.get("vram_total_mb", -1)
            temp = g.get("temperature_c", -1)
            vram_pct = g.get("vram_percent", -1)
            vram_str = f"{vram_used}/{vram_total} MB" if vram_used >= 0 else "N/A"
            temp_str = f"{temp}°C" if temp >= 0 else ""
            print(
                f"    GPU{g['id']} {g.get('name','')[:20]:<22} "
                f"util: {_bar(util):<17} vram: {_bar(vram_pct):<17} {vram_str}  {temp_str}"
            )
    print()


def cmd_cluster_set(args: list[str]) -> None:
    """Set worker admin status.

    Usage: cluster-set <node_id> <available|unavailable|hidden>
    """
    if len(args) < 2:
        print("Usage: cluster-set <node_id> <available|unavailable|hidden>")
        return

    node_id = args[0]
    new_status = args[1].lower()
    client = get_client()

    try:
        if new_status == "hidden":
            result = client.call("cluster.set_hidden", {"node_id": node_id, "hidden": True})
        elif new_status in ("available", "unavailable"):
            result = client.call("cluster.set_status", {"node_id": node_id, "status": new_status})
        else:
            print(f"Unknown status '{new_status}'. Use: available, unavailable, hidden")
            return
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
        return

    if result.get("error"):
        print(f"Error: {result['error']}")
    else:
        print(f"Worker '{node_id}' admin_status set to '{result.get('admin_status', new_status)}'")
