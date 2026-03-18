"""\\users, \\user, \\useradd, \\userdel commands."""
from app.cli.ipc_client import get_client, IpcError


def cmd_users(args: list[str]) -> None:
    client = get_client()
    try:
        data = client.call("user.list", {"limit": 50, "offset": 0})
    except IpcError as e:
        print(f"Error {e.code}: {e.message}"); return

    users = data.get("users", [])
    if not users:
        print("No users found."); return

    print(f"\n  {'ID':<10} {'Username':<20} {'Role':<8} {'Quota':<6} {'Active'}")
    print("  " + "-" * 60)
    for u in users:
        print(
            f"  {str(u['id'])[:8]:<10} {u['username']:<20} {u['role']:<8} "
            f"{u.get('gpu_quota',''):<6} {u.get('is_active','')}"
        )


def cmd_user(args: list[str]) -> None:
    if not args:
        print("Usage: user <user_id>"); return
    client = get_client()
    try:
        user = client.call("user.get", {"user_id": args[0]})
        for k, v in user.items():
            print(f"  {k}: {v}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_useradd(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: useradd <username> <password> [email]"); return
    params = {"username": args[0], "password": args[1]}
    if len(args) >= 3:
        params["email"] = args[2]
    client = get_client()
    try:
        user = client.call("auth.register", params)
        print(f"Created user: {user['username']} (id={str(user['id'])[:8]}, role={user['role']})")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")


def cmd_userdel(args: list[str]) -> None:
    if not args:
        print("Usage: userdel <user_id>"); return
    confirm = input(f"Delete user {args[0][:8]}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Cancelled."); return
    client = get_client()
    try:
        result = client.call("user.delete", {"user_id": args[0]})
        print(f"Deleted: {result['deleted']}")
    except IpcError as e:
        print(f"Error {e.code}: {e.message}")
