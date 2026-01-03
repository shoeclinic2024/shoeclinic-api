
import sqlite3
import os

db_path = os.path.join("instance", "shoeclinic.db")
if not os.path.exists(db_path):
    print("No SQLite DB found at instance/shoeclinic.db")
    exit()

print(f"Checking SQLite DB at {db_path}...")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check expenses for Jan 2026
c.execute("SELECT id, title, amount, real_amount, category, status FROM expense WHERE strftime('%Y-%m', expense_date) = '2026-01' AND status = 'approved'")
rows = c.fetchall()

print(f"{'ID':<5} {'Title':<15} {'Amount':<10} {'RealAmount':<10} {'Calculated'}")
print("-" * 60)

total = 0
for r in rows:
    id, title, amount, real_amount, category, status = r
    val = real_amount if real_amount else amount
    if not val: val = 0
    total += val
    print(f"{id:<5} {title[:15]:<15} {amount:<10} {real_amount:<10} {val}")

print("-" * 60)
print(f"TOTAL: {total}")

conn.close()
