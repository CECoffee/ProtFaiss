import psycopg2
import random
import string

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909"
}

def random_protein_sequence(length):
    return ''.join(random.choices("ACDEFGHIKLMNPQRSTVWY", k=length))

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # cur.execute("""
    #     CREATE TABLE IF NOT EXISTS proteins_mock (
    #         id SERIAL PRIMARY KEY,
    #         original_header TEXT,
    #         accession TEXT,
    #         ko_number TEXT,
    #         ec_number TEXT,
    #         sequence TEXT,
    #         sequence_length INT,
    #         ph_processed FLOAT
    #     );
    # """)
    # conn.commit()

    batch_size = 1000
    total = 10000000

    for i in range(0, total, batch_size):
        data_batch = []
        for j in range(batch_size):
            idx = i + j
            ko = f"K{random.randint(10000, 99999)}"
            ec = f"{random.randint(1, 6)}.{random.randint(1, 9)}.{random.randint(1, 9)}.{random.randint(1, 999)}"
            seq_len = random.randint(80, 500)
            seq = random_protein_sequence(seq_len)
            header_base = f"mock_protein_{idx}_region001_{random.randint(1,100)}_1_{seq_len}"
            header = f"{header_base}_KO:{ko}_EC:{ec}"
            accession = header_base
            ph_processed = 7.0
            data_batch.append((idx, header, accession, ko, ec, seq, seq_len, ph_processed))

        cur.executemany("""
            INSERT INTO "proteins_mock_10M"
            (id, original_header, accession, ko_number, ec_number, sequence, sequence_length, ph_processed)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, data_batch)
        conn.commit()
        print(f"Inserted {i + batch_size} / {total}")

    cur.close()
    conn.close()
    print("✅ mock 数据已写入 proteins_mock 表。")

if __name__ == "__main__":
    main()
