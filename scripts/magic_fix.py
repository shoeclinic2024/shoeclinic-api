
import os
import sys
import sqlalchemy as sa
from sqlalchemy import create_engine, text, inspect

# Add parent directory to path so we can import app/models if needed (though we'll use raw SQL primarily)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("CRITICAL: DATABASE_URL not found.")
    sys.exit(1)

# Fix for Railway/Render postgres:// deprecated scheme
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def fix_schema():
    inspector = inspect(engine)
    
    with engine.connect() as conn:
        print("--- Starting Schema Repair ---")
        
        # 1. Check User table for 'first_login_seen'
        columns = [c['name'] for c in inspector.get_columns('user')]
        if 'first_login_seen' not in columns:
            print("Fixing: Adding 'first_login_seen' to user table...")
            conn.execute(text('ALTER TABLE "user" ADD COLUMN first_login_seen BOOLEAN DEFAULT FALSE'))
        else:
            print("OK: 'first_login_seen' exists.")

        # 2. Check Order table for 'vendor_amount'
        columns = [c['name'] for c in inspector.get_columns('order')]
        if 'vendor_amount' not in columns:
            print("Fixing: Adding 'vendor_amount' to order table...")
            conn.execute(text('ALTER TABLE "order" ADD COLUMN vendor_amount FLOAT'))
        else:
            print("OK: 'vendor_amount' exists.")

        # 3. Check Expense table for 'request_type' etc.
        columns = [c['name'] for c in inspector.get_columns('expense')]
        if 'request_type' not in columns:
            print("Fixing: Adding 'request_type' to expense table...")
            conn.execute(text("ALTER TABLE expense ADD COLUMN request_type VARCHAR(20) DEFAULT 'none'"))
        if 'request_reason' not in columns:
            conn.execute(text("ALTER TABLE expense ADD COLUMN request_reason VARCHAR(255)"))
        if 'request_data' not in columns:
            conn.execute(text("ALTER TABLE expense ADD COLUMN request_data TEXT"))
        print("OK: Expense columns checked.")

        # 4. Check for 'manual_task' table
        if not inspector.has_table('manual_task'):
            print("Fixing: Creating 'manual_task' table...")
            conn.execute(text("""
                CREATE TABLE manual_task (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(100) NOT NULL,
                    description TEXT,
                    assigned_to VARCHAR(100),
                    status VARCHAR(20) DEFAULT 'yts',
                    due_date TIMESTAMP,
                    task_type VARCHAR(50) DEFAULT 'Pickup',
                    customer_name VARCHAR(100),
                    mobile VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            """))
        else:
            print("OK: 'manual_task' table exists.")

        # 5. Check for 'cash_deposit' table
        if not inspector.has_table('cash_deposit'):
            print("Fixing: Creating 'cash_deposit' table...")
            conn.execute(text("""
                CREATE TABLE cash_deposit (
                    id SERIAL PRIMARY KEY,
                    amount FLOAT NOT NULL,
                    deposit_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    reference VARCHAR(100),
                    notes VARCHAR(255),
                    added_by INTEGER REFERENCES "user"(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    request_type VARCHAR(20) DEFAULT 'none',
                    request_reason VARCHAR(255)
                )
            """))
        else:
            print("OK: 'cash_deposit' table exists.")
            
        print("--- Schema Repair Complete ---")
        conn.commit()

if __name__ == "__main__":
    try:
        fix_schema()
    except Exception as e:
        print(f"Error during schema repair: {e}")
        # We don't exit 1 because we want the app to TRY starting anyway
