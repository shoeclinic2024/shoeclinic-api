import psycopg2
import os
from dotenv import load_dotenv

# Load local .env
load_dotenv()

# SOURCE: Railway Database (Live)
# SOURCE: Railway Database (Live)
RAILWAY_URL = os.getenv("RAILWAY_DATABASE_URL")


# DESTINATION: Local Database (from .env)
LOCAL_URL = os.getenv("DATABASE_URL")

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

def sync_to_local():
    if not LOCAL_URL:
        print("ERROR: LOCAL_URL not found in .env!")
        return

    print("\n" + "="*50)
    print("      SHOE CLINIC: RAILWAY -> LOCAL SYNC")
    print("="*50)

    try:
        print(f"[*] Connecting to Live Source (Railway)...")
        src_conn = psycopg2.connect(RAILWAY_URL)
        src_cur = src_conn.cursor()

        print(f"[*] Connecting to Destination (Local)...")
        dst_conn = psycopg2.connect(LOCAL_URL)
        dst_cur = dst_conn.cursor()
    except Exception as e:
        print(f"[!] Connection Error: {e}")
        return

    for table in TABLES_IN_ORDER:
        print(f"\n[>] Table: {table}")
        
        try:
            # 1. Get column names from BOTH and intersect
            src_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = 'public'")
            src_cols = set(c[0] for c in src_cur.fetchall())
            
            dst_cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = 'public'")
            dst_cols = set(c[0] for c in dst_cur.fetchall())
            
            common_cols = sorted(list(src_cols.intersection(dst_cols)))
            if not common_cols:
                print(f"    [SKIP] No matching columns found for '{table}'.")
                continue

            col_str = '", "'.join(common_cols)
            placeholder = ', '.join(['%s'] * len(common_cols))

            # 2. Fetch data from Railway
            print(f"    [*] Fetching data from Railway...")
            src_cur.execute(f'SELECT "{col_str}" FROM "{table}"')
            rows = src_cur.fetchall()
            
            if not rows:
                print(f"    [INFO] No data in live database for '{table}'. Skipping.")
                continue

            # 3. Insert into Local
            print(f"    [*] Syncing {len(rows)} records to Local...")
            
            try:
                # Prepare insert query
                insert_query = f'INSERT INTO "{table}" ("{col_str}") VALUES ({placeholder})'
                
                # Truncate existing data locally
                dst_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
                
                # Execute batch insert
                dst_cur.executemany(insert_query, rows)
                dst_conn.commit() 
                print(f"    [SUCCESS] Table '{table}' synced.")
            except Exception as e:
                print(f"    [ERROR] Failed to insert '{table}': {e}")
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

    dst_conn.commit()
    src_conn.close()
    dst_conn.close()
    
    print("\n" + "="*50)
    print("      DATABASE SYNC COMPLETED SUCCESSFULLY")
    print("="*50)

if __name__ == "__main__":
    sync_to_local()
