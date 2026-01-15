import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from database import db
from models import AppConfig, DailyCapacity

with app.app_context():
    db.create_all()
    print("Database tables created successfully!")
    
    # Initialize default capacity if not exists
    if not AppConfig.query.filter_by(key="default_daily_capacity").first():
        default_cap = AppConfig(key="default_daily_capacity", value="20")
        db.session.add(default_cap)
        db.session.commit()
        print("Initialized default_daily_capacity to 20")
