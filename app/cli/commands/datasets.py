"""\\datasets, \\switch, \\delete commands."""
from app.cli.ipc_client import get_client, IpcError


def cmd_datasets(args: list[str]) -> None:
    client = get_client()
    try:
        data = client.call("dataset.list", {})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}"); return

    active_id = data.get("active_dataset_id")
    datasets = data.get("datasets", [])
    if not datasets:
        print("No datasets found.")
        return

    print(f"\n  {'*':<2} {'ID':<10} {'Name':<24} {'Algo':<8} {'Status':<10} {'Seqs':<10} {'Vis'}")
    print("  " + "-" * 80)
    for d in datasets:
        marker = "*" if d["id"] == active_id else " "
        print(
            f"  {marker:<2} {d['id'][:8]:<10} {d['name'][:22]:<24} {d['algorithm']:<8} "
            f"{d['status']:<10} {str(d.get('num_sequences') or ''):<10} {d.get('visibility','')}"
        )
    if active_id:
        print(f"\n  Active: {active_id[:8]}")


def cmd_switch(args: list[str]) -> None:
    if not args:
        print("Usage: \\switch <dataset_id>"); return
    client = get_client()
    try:
        result = client.call("dataset.switch", {"dataset_id": args[0]})
        print(f"Switched active dataset to {result['active_dataset_id'][:8]}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_delete(args: list[str]) -> None:
    if not args:
        print("Usage: \\delete <dataset_id>"); return
    dataset_id = args[0]
    confirm = input(f"Delete dataset {dataset_id[:8]}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled."); return
    client = get_client()
    try:
        result = client.call("dataset.delete", {"dataset_id": dataset_id})
        print(f"Deleted: {result['deleted'][:8]}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_visibility(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: \\visibility <dataset_id> <public|private>"); return
    client = get_client()
    try:
        result = client.call("dataset.visibility", {"dataset_id": args[0], "visibility": args[1]})
        print(f"Dataset {args[0][:8]} visibility set to {result.get('visibility')}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
