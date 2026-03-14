"""
Run the DB migration and create the initial admin user on first startup.
Called from main.py startup().
"""
import secrets
import string

from .config import ADMIN_USERNAME, ADMIN_PASSWORD
from .db_operations import blocking_count_users, blocking_create_user


def ensure_admin():
    """Create the admin user if no users exist yet."""
    count = blocking_count_users()
    if count > 0:
        return

    password = ADMIN_PASSWORD
    if not password:
        # Generate a random password and print it once
        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(16))
        print(f"\n[auth] *** No users found. Creating admin account ***")
        print(f"[auth]   Username : {ADMIN_USERNAME}")
        print(f"[auth]   Password : {password}")
        print(f"[auth] Set ADMIN_PASSWORD env var to use a fixed password.\n")
    else:
        print(f"[auth] Creating admin user '{ADMIN_USERNAME}' from environment.")

    blocking_create_user(ADMIN_USERNAME, password, role="admin")
