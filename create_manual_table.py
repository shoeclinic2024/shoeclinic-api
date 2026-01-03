from app import app, db
from models import ManualTask

if __name__ == "__main__":
    with app.app_context():
        # This will create the manual_task table if it doesn't exist
        # It won't overwrite existing tables
        db.create_all()
        print("Database schema updated: ManualTask table ensured.")
