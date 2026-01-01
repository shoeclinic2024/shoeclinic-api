import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def upgrade_schema():
    # Railway usually provides the DATABASE_URL environment variable
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not found.")
        print("Please set it: export DATABASE_URL=postgres://user:pass@host:port/db")
        return

    print(f"Connecting to Railway Database...")
    try:
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # 1. Define missing columns for v02 upgrade
    # Format: (table_name, column_name, column_type, default_value)
    missing_columns = [
        # User Table Security Upgrades
        ('user', 'can_view_performance', 'BOOLEAN', 'FALSE'),
        ('user', 'performance_view_requested', 'BOOLEAN', 'FALSE'),
        ('user', 'performance_access_expiry', 'TIMESTAMP', 'NULL'),
        ('user', 'failed_login_attempts', 'INTEGER', '0'),
        ('user', 'last_failed_login', 'TIMESTAMP', 'NULL'),
        ('user', 'account_locked_until', 'TIMESTAMP', 'NULL'),
        ('user', 'last_login_at', 'TIMESTAMP', 'NULL'),
        ('user', 'last_login_ip', 'VARCHAR(45)', 'NULL'),
        ('user', 'two_factor_enabled', 'BOOLEAN', 'FALSE'),
        ('user', 'two_factor_secret', 'VARCHAR(32)', 'NULL'),
        ('user', 'session_token', 'VARCHAR(100)', 'NULL'),
        ('user', 'last_activity', 'TIMESTAMP', 'NULL'),
        
        # Order Table Tracking Upgrades
        ('order', 'work_finish_date', 'TIMESTAMP', 'NULL'),
        ('order', 'actual_delivery_date', 'TIMESTAMP', 'NULL'),
        ('order', 'assignment_start_date', 'TIMESTAMP', 'NULL'),
        
        # Expense Table Request Tracking
        ('expense', 'real_amount', 'DOUBLE PRECISION', '0.0'),
        ('expense', 'request_type', 'VARCHAR(20)', "'none'"),
        ('expense', 'request_reason', 'VARCHAR(255)', 'NULL'),
        ('expense', 'request_data', 'TEXT', 'NULL')
    ]

    print("Checking for missing columns...")
    for table, col, col_type, default in missing_columns:
        # Check if column exists
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM information_schema.columns 
            WHERE table_name='{table}' AND column_name='{col}';
        """)
        if cursor.fetchone()[0] == 0:
            print(f"Adding column '{col}' to table '{table}'...")
            try:
                cursor.execute(f"ALTER TABLE \"{table}\" ADD COLUMN {col} {col_type} DEFAULT {default};")
                print(f"  [SUCCESS]")
            except Exception as e:
                print(f"  [FAILED] {e}")
        else:
            print(f"Column '{col}' already exists in '{table}'.")

    # 2. Create New v02 Tables
    new_tables = {
        'login_attempt': """
            CREATE TABLE IF NOT EXISTS login_attempt (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                ip_address VARCHAR(45) NOT NULL,
                user_agent VARCHAR(255),
                success BOOLEAN DEFAULT FALSE,
                failure_reason VARCHAR(100),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES \"user\"(id)
            );
        """,
        'password_history': """
            CREATE TABLE IF NOT EXISTS password_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES \"user\"(id),
                password_hash VARCHAR(200) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """,
        'payment_transaction': """
            CREATE TABLE IF NOT EXISTS payment_transaction (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES \"order\"(id),
                razorpay_order_id VARCHAR(50) UNIQUE,
                razorpay_payment_id VARCHAR(50) UNIQUE,
                razorpay_signature VARCHAR(255),
                razorpay_plink_id VARCHAR(50) UNIQUE,
                short_url VARCHAR(255),
                amount DOUBLE PRECISION NOT NULL,
                currency VARCHAR(10) DEFAULT 'INR',
                status VARCHAR(20) DEFAULT 'created',
                method VARCHAR(20),
                error_code VARCHAR(50),
                error_description VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
    }

    for table_name, create_sql in new_tables.items():
        print(f"Verifying table '{table_name}'...")
        cursor.execute(create_sql)
        print(f"  [OK]")

    cursor.close()
    conn.close()
    print("\n--- Migration Complete ---")
    print("Your v01 data has been successfully patched to support v02 features.")

if __name__ == "__main__":
    upgrade_schema()
