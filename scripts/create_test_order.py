import sqlite3
from pathlib import Path
from datetime import datetime
DB = Path(__file__).resolve().parents[1] / 'instance' / 'shoeclinic.db'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

# Insert order
cur.execute("INSERT INTO 'order' (job_id, customer_name, drop_date, pickup_date, place, mobile, status, created_at, price, item_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ('TSC99999', 'Test User', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'testplace', '9999999999', 'yts', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 150.0, 1))
order_id = cur.lastrowid

# Insert item with price
cur.execute("INSERT INTO order_item (order_id, product_name, services, price, discount, technician, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (order_id, 'Test Shoe', 'wash,repair', 150.0, 0.0, 'Tech1', 'wip', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

conn.commit()
print('Inserted test order id:', order_id)
conn.close()
