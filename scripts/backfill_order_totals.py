import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

cur.execute('SELECT id FROM "order"')
orders = [r[0] for r in cur.fetchall()]
for oid in orders:
    cur.execute('SELECT COALESCE(SUM(COALESCE(price,0) - COALESCE(discount,0)),0), COUNT(*) FROM order_item WHERE order_id=?', (oid,))
    total, count = cur.fetchone()
    # store total discount as string if not zero
    cur.execute('SELECT COALESCE(SUM(COALESCE(discount,0)),0) FROM order_item WHERE order_id=?', (oid,))
    total_discount = cur.fetchone()[0]
    cur.execute('UPDATE "order" SET price=?, item_count=?, discount=? WHERE id=?', (total, count if count>0 else None, str(total_discount) if total_discount else None, oid))
    print(f'Order {oid}: price={total} items={count} discount={total_discount}')

conn.commit()
conn.close()
print('Backfill complete')
