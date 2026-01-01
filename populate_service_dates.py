from app import app, db
from models import Order
from datetime import datetime
import sqlite3
import os

def populate_service_dates():
    """
    Populate service_date for existing orders that have a technician assigned
    but no service_date yet. This is a one-time migration.
    """
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'shoeclinic.db')
    if not os.path.exists(db_path):
        db_path = os.path.join(os.path.dirname(__file__), 'shoeclinic.db')
        
    print(f"Connecting to database at: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get all orders that have a technician but no service_date
        cursor.execute('''
            SELECT id, job_id, technician, pickup_date, created_at 
            FROM "order" 
            WHERE technician IS NOT NULL 
            AND technician != '' 
            AND service_date IS NULL
        ''')
        
        orders = cursor.fetchall()
        print(f"\nFound {len(orders)} orders with technicians but no service_date")
        
        updated_count = 0
        for order in orders:
            order_id, job_id, technician, pickup_date, created_at = order
            
            # Use pickup_date as service_date (since that's when they likely started)
            # If pickup_date is not available, use created_at
            service_date = pickup_date if pickup_date else created_at
            
            cursor.execute('''
                UPDATE "order" 
                SET service_date = ? 
                WHERE id = ?
            ''', (service_date, order_id))
            
            updated_count += 1
            print(f"  Updated {job_id} - Technician: {technician}, Service Date: {service_date}")
        
        conn.commit()
        print(f"\nSuccessfully updated {updated_count} orders with service dates")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    populate_service_dates()
