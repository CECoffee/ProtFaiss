"""
Migrate existing datasets/registry.json into the PostgreSQL datasets table.
Run once after applying 001_auth_tables.sql.

Usage:
    python -m app.migrations.migrate_registry
"""
import json
import os
import sys
import uuid


def run():
    from app.core.db import init_db_pool, get_pool

    REGISTRY_PATH = "datasets/registry.json"
    init_db_pool()
    pool = get_pool()

    # Check if registry.json exists
    if not os.path.exists(REGISTRY_PATH):
        print("No registry.json found — nothing to migrate.")
        return

    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        data = {"active": None, "datasets": data}

    datasets = data.get("datasets", [])
    if not datasets:
        print("registry.json is empty — nothing to migrate.")
        return

    # Find or create the admin user to own migrated datasets
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            row = cur.fetchone()
            if not row:
                print("ERROR: No admin user found. Run the server first to create the admin user.")
                return
            admin_id = str(row[0])

        migrated = 0
        skipped = 0
        with conn.cursor() as cur:
            for entry in datasets:
                dataset_id = entry.get("id") or str(uuid.uuid4())
                # Skip if already in DB
                cur.execute("SELECT id FROM datasets WHERE id = %s", (dataset_id,))
                if cur.fetchone():
                    skipped += 1
                    continue

                cur.execute(
                    "INSERT INTO datasets "
                    "(id, owner_id, name, algorithm, status, visibility, error_msg, "
                    "fasta_path, db_table, num_sequences, num_indexed, "
                    "progress_step, progress_pct) "
                    "VALUES (%s, %s, %s, %s, %s, 'public', %s, %s, %s, %s, %s, %s, %s)",
                    (
                        dataset_id,
                        admin_id,
                        entry.get("name", "Migrated Dataset"),
                        entry.get("algorithm", "flat"),
                        entry.get("status", "ready"),
                        entry.get("error_msg"),
                        entry.get("fasta_path"),
                        entry.get("db_table"),
                        entry.get("num_sequences", 0),
                        entry.get("num_indexed", 0),
                        entry.get("progress_step", "done"),
                        entry.get("progress_pct", 100),
                    ),
                )
                migrated += 1

            # Migrate active pointer for admin
            active_id = data.get("active")
            if active_id:
                cur.execute(
                    "INSERT INTO user_active_datasets (user_id, dataset_id) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET dataset_id = EXCLUDED.dataset_id",
                    (admin_id, active_id),
                )

        conn.commit()
        print(f"Migration complete: {migrated} datasets inserted, {skipped} skipped (already exist).")

        # Rename registry.json to mark as migrated
        migrated_path = REGISTRY_PATH + ".migrated"
        os.rename(REGISTRY_PATH, migrated_path)
        print(f"Renamed registry.json → {migrated_path}")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        pool.putconn(conn)


if __name__ == "__main__":
    run()
