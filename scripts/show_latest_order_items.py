import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute('SELECT id FROM "order" ORDER BY id DESC LIMIT 1')
row = cur.fetchone()
if not row:
    print('No orders found')
else:
    oid = row[0]
    cur.execute('SELECT id, product_name, services, price, discount FROM order_item WHERE order_id=?', (oid,))
    for r in cur.fetchall():
        print(r)
conn.close()
