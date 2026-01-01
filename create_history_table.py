from app import app, db
from models import PasswordHistory

with app.app_context():
    # This will create the table if it implies based on the model
    # Since we are using SQLAlchemy, create_all usually skips existing tables
    # and creates new ones.
    db.create_all()
    print("Database tables updated (PasswordHistory created if missing).")
