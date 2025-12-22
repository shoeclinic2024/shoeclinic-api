# scripts/backup_manager.py
import os
import io
import smtplib
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# Load environment variables from .env if it exists (for local testing)
load_dotenv()

def send_backup_email(file_path):
    """
    Sends the backup Excel file via email using SMTP settings from environment variables.
    """
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    receiver_email = os.getenv("BACKUP_RECEIVER")

    if not all([smtp_server, smtp_user, smtp_password, receiver_email]):
        print(f"[{datetime.now()}] Email skip: SMTP settings missing in environment variables.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = receiver_email
        msg['Subject'] = f"TSC Daily Data Backup - {datetime.now().strftime('%d %b %Y')}"

        body = f"Attached is the daily core data backup for The Shoe Clinic.\nGenerated at: {datetime.now()}"
        msg.attach(MIMEText(body, 'plain'))

        # Attach the file
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename= {filename}",
            )
            msg.attach(part)

        # Connect and send
        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        print(f"[{datetime.now()}] Email sent successfully to {receiver_email}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] Email FAILED: {str(e)}")
        return False

def run_backup():
    """
    Connects to the database and exports the dashboard data to an Excel file.
    Then attempts to email the file if SMTP settings are present.
    """
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        # Check both root and instance folder for default SQLite
        if os.path.exists("instance/shoeclinic.db"):
            database_url = "sqlite:///instance/shoeclinic.db"
        else:
            database_url = "sqlite:///shoeclinic.db"
    
    # Handle PostgreSQL URL compatibility
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        
    print(f"[{datetime.now()}] Starting backup from {database_url.split('@')[-1] if '@' in database_url else 'local SQLite'}...")
    
    try:
        engine = create_engine(database_url)
        
        # Query Order and OrderItem data
        orders_query = 'SELECT * FROM "order"'  
        items_query = "SELECT * FROM order_item"
        
        df_orders = pd.read_sql(orders_query, engine)
        df_items = pd.read_sql(items_query, engine)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        filename = f"{backup_dir}/TSC_Full_Backup_{timestamp}.xlsx"
        
        with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
            df_orders.to_excel(writer, index=False, sheet_name='Orders')
            df_items.to_excel(writer, index=False, sheet_name='OrderItems')
            
        print(f"[{datetime.now()}] Backup file created: {filename}")
        
        # Attempt to email the backup
        send_backup_email(filename)
        
        return filename
        
    except Exception as e:
        print(f"[{datetime.now()}] Backup execution FAILED: {str(e)}")
        return None

if __name__ == "__main__":
    run_backup()
