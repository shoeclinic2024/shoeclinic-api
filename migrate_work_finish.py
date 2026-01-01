from app import app, db
import sqlite3
import os

def migrate():
    # Attempting to add the column via raw SQL for SQLite
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'shoeclinic.db')
    if not os.path.exists(db_path):
        db_path = os.path.join(os.path.dirname(__file__), 'shoeclinic.db')
        
    print(f"Connecting to database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("Adding 'work_finish_date' column to 'order' table...")
        cursor.execute('ALTER TABLE "order" ADD COLUMN work_finish_date DATETIME')
        conn.commit()
        print("Successfully added column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column already exists.")
        else:
            print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
