import psycopg2
import os
import sys

# SOURCE: Render Database URL
RENDER_URL = "postgresql://shoeclinic_db_user:myOYLFN7JpYqvoHkFsoc0mbGcKaBz5li@dpg-d540aqjuibrs7385t1p0-a.oregon-postgres.render.com/shoeclinic_db"

# DESTINATION: Railway Database URL (From Environment)
RAILWAY_URL = os.environ.get('DATABASE_URL')

TABLES_IN_ORDER = [
    'user',
    'staff',
    'order',
    'order_item',
    'expense',
    'attendance',
    'announcement',
    'notification',
    'holiday',
    'login_attempt',
    'password_history',
    'payment_transaction'
]

def sync():
    if not RAILWAY_URL:
        print("\nERROR: RAILWAY_URL not found!")
        print("Please set it first in Powershell:")
        print('$env:DATABASE_URL = "your_railway_url_here"')
        return

    print("\n" + "="*50)
    print("      SHOE CLINIC: RENDER -> RAILWAY SYNC")
    print("="*50)

    try:
        print(f"[*] Connecting to Source (Render)...")
        src_conn = psycopg2.connect(RENDER_URL)
        src_cur = src_conn.cursor()

        print(f"[*] Connecting to Destination (Railway)...")
        dst_conn = psycopg2.connect(RAILWAY_URL)
        dst_cur = dst_conn.cursor()
    except Exception as e:
        print(f"[!] Connection Error: {e}")
        return

    for table in TABLES_IN_ORDER:
        print(f"\n[>] Table: {table}")
        
        try:
            # 1. Fetch data from Render
            print(f"    [*] Fetching from Render...")
            try:
                src_cur.execute(f'SELECT * FROM "{table}"')
                rows = src_cur.fetchall()
            except Exception as e:
                print(f"    [SOURCE ERROR] Failed to fetch '{table}': {e}")
                src_conn.rollback() # Important to reset source transaction too
                continue
                
            if not rows:
                print(f"    [INFO] No data in source. Skipping.")
                continue

            # 2. Get column names from BOTH and intersect
            src_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = 'public'")
            src_cols = set(c[0] for c in src_cur.fetchall())
            
            dst_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = 'public'")
            dst_cols = set(c[0] for c in dst_cur.fetchall())
            
            common_cols = sorted(list(src_cols.intersection(dst_cols)))
            col_str = '", "'.join(common_cols)
            placeholder = ', '.join(['%s'] * len(common_cols))

            # 3. Fetch ONLY common columns from Render
            src_cur.execute(f'SELECT "{col_str}" FROM "{table}"')
            rows = src_cur.fetchall()

            # 4. Insert into Railway
            print(f"    [*] Inserting {len(rows)} records into Railway (Common Columns: {len(common_cols)})...")
            
            try:
                # Prepare insert query
                insert_query = f'INSERT INTO "{table}" ("{col_str}") VALUES ({placeholder})'
                
                # Truncate existing data in Railway
                dst_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
                
                # Execute batch insert
                dst_cur.executemany(insert_query, rows)
                dst_conn.commit() # Commit each table to be safe
                print(f"    [SUCCESS] Table '{table}' synced.")
            except Exception as e:
                print(f"    [DEST ERROR] Failed to insert '{table}': {e}")
                dst_conn.rollback()
                continue
            
            # 4. Fix Sequences (SERIAL columns)
            try:
                dst_cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = '{table}' 
                    AND column_default LIKE 'nextval%'
                """)
                seq_cols = dst_cur.fetchall()
                for s_col in seq_cols:
                    c_name = s_col[0]
                    dst_cur.execute(f"""
                        SELECT setval(
                            pg_get_serial_sequence('"{table}"', '{c_name}'), 
                            COALESCE(MAX("{c_name}"), 1), 
                            MAX("{c_name}") IS NOT NULL
                        ) FROM "{table}"
                    """)
                dst_conn.commit()
            except Exception as e:
                print(f"    [SEQ ERROR] Failed to fix sequences for '{table}': {e}")
                dst_conn.rollback()

        except Exception as e:
            print(f"    [GENERAL ERROR] Table '{table}': {e}")
            continue

    # Final commit
    dst_conn.commit()
    
    src_cur.close()
    src_conn.close()
    dst_cur.close()
    dst_conn.close()
    
    print("\n" + "="*50)
    print("      DATABASE SYNC COMPLETED SUCCESSFULLY")
    print("="*50)

if __name__ == "__main__":
    sync()
