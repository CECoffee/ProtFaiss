import psycopg2
import pandas as pd

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "protein_db",
    "user": "postgres",
    "password": "0909"
}

conn = psycopg2.connect(**DB_CONFIG)
df = pd.read_sql("""SELECT sequence FROM "proteins_mock_10M" ORDER BY id""", conn)
df.to_csv("../proteins_mock_10m.csv", index=False)
conn.close()

print("✅ 已导出 proteins.csv，顺序与id一致")
