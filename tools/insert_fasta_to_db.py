"""
tools/insert_fasta_to_db.py — 将 FASTA 文件批量导入 PostgreSQL

从 app.core.config 读取数据库配置，避免重复维护连接信息。

用法：
  python tools/insert_fasta_to_db.py --fasta ../src/KEGG_test.fasta --table proteins
  python tools/insert_fasta_to_db.py --fasta ../src/KEGG_test.fasta --table proteins --batch-size 500
"""
import argparse
import re
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

def parse_fasta_header(header_string: str):
    accession = header_string
    ko = None
    ec = None

    ko_match = re.search(r'KO:(K\d{5})', header_string)
    if ko_match:
        ko = ko_match.group(1)

    ec_match = re.search(r'EC:([\d\.\-n]+)', header_string)
    if ec_match:
        ec = ec_match.group(1)

    split_pos = -1
    ko_pos = header_string.find('_KO:')
    ec_pos = header_string.find('_EC:')

    if ko_pos != -1 and ec_pos != -1:
        split_pos = min(ko_pos, ec_pos)
    elif ko_pos != -1:
        split_pos = ko_pos
    elif ec_pos != -1:
        split_pos = ec_pos

    if split_pos != -1:
        accession = header_string[:split_pos]

    return accession, ko, ec


def fasta_data_iterator(fasta_file_path: str):
    header = None
    sequence_parts = []

    with open(fasta_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if header:
                    full_sequence = "".join(sequence_parts)
                    original_header = header.lstrip('>')
                    accession, ko, ec = parse_fasta_header(original_header)
                    yield (original_header, accession, ko, ec, full_sequence, len(full_sequence), None)
                header = line
                sequence_parts = []
            else:
                sequence_parts.append(line)

        if header:
            full_sequence = "".join(sequence_parts)
            original_header = header.lstrip('>')
            accession, ko, ec = parse_fasta_header(original_header)
            yield (original_header, accession, ko, ec, full_sequence, len(full_sequence), None)


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
