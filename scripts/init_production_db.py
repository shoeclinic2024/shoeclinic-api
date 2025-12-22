"""
One-time script to initialize the production database schema on Render.
This creates all the tables defined in models.py.
"""
import os
from app import app, db

# Ensure we're using the production database
database_url = os.getenv("DATABASE_URL")
if not database_url or not database_url.startswith("postgresql"):
    print("ERROR: DATABASE_URL must be set to a PostgreSQL connection string")
    exit(1)

print(f"Connecting to: {database_url.split('@')[1] if '@' in database_url else 'database'}...")

with app.app_context():
    print("Creating all tables...")
    db.create_all()
    print("✅ Database schema created successfully!")
    print("\nTables created:")
    print("  - user")
    print("  - order")
    print("  - order_item")
    print("  - expense")
    print("  - announcement")
    print("  - attendance")
    print("  - holiday")
