from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE user ADD COLUMN can_view_performance BOOLEAN DEFAULT 0"))
        db.session.execute(text("ALTER TABLE user ADD COLUMN performance_view_requested BOOLEAN DEFAULT 0"))
        db.session.execute(text("ALTER TABLE user ADD COLUMN performance_access_expiry DATETIME"))
        db.session.commit()
        print("Columns added successfully.")
    except Exception as e:
        db.session.rollback()
        print("Error or already exists: " + str(e))
