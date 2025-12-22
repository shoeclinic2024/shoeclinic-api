import sqlite3
from pathlib import Path
import sys

DB_PATH = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
if not DB_PATH.exists():
    print(f"DB not found: {DB_PATH}")
    sys.exit(2)

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

# Get existing columns
cur.execute("PRAGMA table_info('order_item')")
cols = [r[1] for r in cur.fetchall()]
adds = []
if 'price' not in cols:
    adds.append("ALTER TABLE order_item ADD COLUMN price REAL")
if 'discount' not in cols:
    adds.append("ALTER TABLE order_item ADD COLUMN discount REAL")
if 'technician' not in cols:
    adds.append("ALTER TABLE order_item ADD COLUMN technician TEXT")
if 'status' not in cols:
    adds.append("ALTER TABLE order_item ADD COLUMN status TEXT")
if 'created_at' not in cols:
    adds.append("ALTER TABLE order_item ADD COLUMN created_at DATETIME")

for sql in adds:
    try:
        cur.execute(sql)
        print("Executed:", sql)
    except sqlite3.OperationalError as e:
        print("Failed:", sql, e)

conn.commit()
conn.close()
print('Done')
