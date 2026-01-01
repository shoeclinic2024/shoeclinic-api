import os
import psycopg2

# Railway Public Connection String
RAILWAY_URL = "postgresql://postgres:QvWlkCypHfDYJPQQYTQUjlNYcxvrhTXf@trolley.proxy.rlwy.net:40006/railway"

def repair_user_table():
    print(f"Attempting to repair user table at {RAILWAY_URL}")
    try:
        conn = psycopg2.connect(RAILWAY_URL)
        cursor = conn.cursor()
        
        # 1. Integers
        int_fields = ['failed_login_attempts', 'otp_attempts']
        for field in int_fields:
            cursor.execute(f'UPDATE "user" SET {field} = 0 WHERE {field} IS NULL')
            print(f"Fixed NULLs in {field}")
            
        # 2. Booleans
        bool_fields = [
            'is_active', 'can_view_customers', 'customer_view_requested', 
            'can_export_customers', 'can_view_performance', 'performance_view_requested', 
            'two_factor_enabled'
        ]
        for field in bool_fields:
            cursor.execute(f'UPDATE "user" SET {field} = false WHERE {field} IS NULL')
            print(f"Fixed NULLs in {field}")
            
        conn.commit()
        print("\nRepair complete! All NULL security fields have been set to defaults.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    repair_user_table()
