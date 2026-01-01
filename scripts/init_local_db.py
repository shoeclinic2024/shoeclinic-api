import sys
import os

# Add parent directory to sys.path to find app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db

def init_db():
    print("Attempting to initialize local PostgreSQL database...")
    try:
        with app.app_context():
            db.create_all()
        print("\nSUCCESS: Tables created successfully in the 'shoeclinic' database!")
    except Exception as e:
        print(f"\nERROR: Could not connect to the database.")
        print(f"Details: {e}")
        print("\nPlease check your .env file and ensure: ")
        print("1. The password is correct.")
        print("2. PostgreSQL is currently running.")
        print("3. You created the 'shoeclinic' database in pgAdmin.")

if __name__ == "__main__":
    init_db()
