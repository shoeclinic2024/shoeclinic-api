import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

cur.execute('SELECT id FROM "order"')
orders = [r[0] for r in cur.fetchall()]
for oid in orders:
    cur.execute('SELECT product_name FROM order_item WHERE order_id=? ORDER BY id LIMIT 1', (oid,))
    r = cur.fetchone()
    if r and r[0]:
        cur.execute('UPDATE "order" SET product_name=? WHERE id=?', (r[0], oid))
        print(f'Order {oid}: set product_name={r[0]}')

conn.commit()
conn.close()
print('Backfill done')
