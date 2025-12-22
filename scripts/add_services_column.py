import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'

if not DB_PATH.exists():
    print(f"Database file not found: {DB_PATH}")
    sys.exit(2)

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

# Check if services column exists
cur.execute("PRAGMA table_info('order_item')")
cols = [r[1] for r in cur.fetchall()]
if 'services' in cols:
    print("Column 'services' already exists on order_item.")
    conn.close()
    sys.exit(0)

# Add the column
try:
    cur.execute("ALTER TABLE order_item ADD COLUMN services TEXT")
    conn.commit()
    print("Added 'services' column to order_item table.")
except sqlite3.OperationalError as e:
    print("Failed to add column:", e)
    conn.rollback()
    conn.close()
    sys.exit(1)

conn.close()
sys.exit(0)
