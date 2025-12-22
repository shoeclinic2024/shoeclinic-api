import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

print('Last 5 orders:')
cur.execute('SELECT id, job_id, customer_name, price, item_count FROM "order" ORDER BY id DESC LIMIT 5')
orders = cur.fetchall()
for o in orders:
    oid, job, name, price, count = o
    print(f'Order {oid} {job} {name} price={price} items={count}')
    cur.execute('SELECT id, product_name, services, price, discount FROM order_item WHERE order_id=?', (oid,))
    items = cur.fetchall()
    for it in items:
        print('  item:', it)

conn.close()
