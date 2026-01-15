import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from database import db
from sqlalchemy import inspect, text

def sync_db():
    with app.app_context():
        # 1. Create all missing tables
        db.create_all()
        print("Ensured all tables exist.")

        # 2. Add missing columns to existing tables
        inspector = inspect(db.engine)
        
        # Table: order_item
        oi_cols = [c['name'] for c in inspector.get_columns('order_item')]
        oi_to_add = {
            'service_assignments': 'TEXT',
            'service_statuses': 'TEXT',
            'service_prices': 'TEXT',
            'service_discounts': 'TEXT',
            'status': "VARCHAR(50) DEFAULT 'yts'",
            'defects': 'VARCHAR(255)',
            'vendor_amount': 'FLOAT DEFAULT 0.0',
            'is_vendor_paid': 'BOOLEAN DEFAULT FALSE',
            'vendor_paid_date': 'TIMESTAMP',
            'assigned_at': 'TIMESTAMP'
        }
        
        for col, col_type in oi_to_add.items():
            if col not in oi_cols:
                print(f"Adding column order_item.{col}...")
                try:
                    db.session.execute(text(f'ALTER TABLE order_item ADD COLUMN {col} {col_type}'))
                    db.session.commit()
                except Exception as e:
                    print(f"Error adding {col}: {e}")
                    db.session.rollback()

        # Table: order
        o_cols = [c['name'] for c in inspector.get_columns('order')]
        o_to_add = {
            'work_finish_date': 'TIMESTAMP',
            'actual_delivery_date': 'TIMESTAMP',
            'assignment_start_date': 'TIMESTAMP'
        }
        
        for col, col_type in o_to_add.items():
            if col not in o_cols:
                print(f"Adding column order.{col}...")
                try:
                    db.session.execute(text(f'ALTER TABLE "order" ADD COLUMN {col} {col_type}'))
                    db.session.commit()
                except Exception as e:
                    print(f"Error adding {col}: {e}")
                    db.session.rollback()

        print("Database sync complete!")

if __name__ == "__main__":
    sync_db()
