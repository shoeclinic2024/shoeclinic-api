from app import app, db
from sqlalchemy import text

def add_assigned_at_column():
    with app.app_context():
        try:
            # Check if column already exists (sqlite specific)
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE order_item ADD COLUMN assigned_at TIMESTAMP"))
                conn.commit()
            print("Successfully added assigned_at column to order_item table.")
        except Exception as e:
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("Column assigned_at already exists.")
            else:
                print(f"Error adding column: {e}")

if __name__ == "__main__":
    add_assigned_at_column()
