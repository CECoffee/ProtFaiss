"""
tools/insert_fasta_to_db.py — 将 FASTA 文件批量导入 PostgreSQL

从 app.core.config 读取数据库配置，避免重复维护连接信息。

用法：
  python tools/insert_fasta_to_db.py --fasta ../src/KEGG_test.fasta --table proteins
  python tools/insert_fasta_to_db.py --fasta ../src/KEGG_test.fasta --table proteins --batch-size 500
"""
import argparse
import sys
import os

import psycopg2
from psycopg2.extras import execute_values
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import get_db_config

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Import FASTA sequences into PostgreSQL")
parser.add_argument("--fasta", required=True, help="Path to FASTA file")
parser.add_argument("--table", default="proteins", help="Target table name")
parser.add_argument("--batch-size", type=int, default=1000, help="Rows per DB insert batch")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# FASTA parsing
# ---------------------------------------------------------------------------

from app.build.index_builder import fasta_data_iterator


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

INSERT_QUERY = """
INSERT INTO {table} (
    id, original_header, accession, ko_number, ec_number,
    sequence, sequence_length, ph_processed
) VALUES %s
"""


def main():
    _db = get_db_config()
    print(f"Connecting to database {_db['dbname']} ...")
    conn = psycopg2.connect(**_db)
    cursor = conn.cursor()
    print("Connected.")

    current_id = 0
    batch = []
    query = INSERT_QUERY.format(table=args.table)

    try:
        with tqdm(desc="Inserting", unit="seq") as pbar:
            for record in fasta_data_iterator(args.fasta):
                original_header, accession, ko, ec, sequence, seq_len, ph_val = record
                batch.append((current_id, original_header, accession, ko, ec, sequence, seq_len, ph_val))
                current_id += 1

                if len(batch) >= args.batch_size:
                    execute_values(cursor, query, batch)
                    conn.commit()
                    pbar.update(len(batch))
                    pbar.set_postfix({"total": current_id})
                    batch = []

            if batch:
                execute_values(cursor, query, batch)
                conn.commit()
                pbar.update(len(batch))

        print(f"Done. Inserted {current_id} sequences into table '{args.table}'.")

    except psycopg2.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        conn.rollback()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
