import os
import sys
import psycopg2
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import get_db_config

conn = psycopg2.connect(**get_db_config())
df = pd.read_sql("""SELECT sequence FROM "proteins_mock_10M" ORDER BY id""", conn)
df.to_csv("../proteins_mock_10m.csv", index=False)
conn.close()

print("✅ 已导出 proteins.csv，顺序与id一致")
