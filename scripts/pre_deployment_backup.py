"""
Pre-Deployment Backup Script
Creates a backup of the database before deployment to ensure data safety
"""
import os
import sys
from datetime import datetime
import subprocess
import shutil

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def create_backup_directory():
    """Create backups directory if it doesn't exist"""
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        print(f"[INFO] Created backup directory: {backup_dir}")
    return backup_dir

def backup_sqlite(db_path, backup_dir):
    """Backup SQLite database"""
    if not os.path.exists(db_path):
        print(f"[ERROR] Database file not found: {db_path}")
        return False
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"shoeclinic_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        shutil.copy2(db_path, backup_path)
        file_size = os.path.getsize(backup_path) / (1024 * 1024)  # Convert to MB
        print(f"[SUCCESS] SQLite backup created successfully!")
        print(f"   File: {backup_filename}")
        print(f"   Size: {file_size:.2f} MB")
        print(f"   Path: {backup_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Error creating SQLite backup: {e}")
        return False

def backup_postgresql(database_url, backup_dir):
    """Backup PostgreSQL database using pg_dump"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"shoeclinic_backup_{timestamp}.sql"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        print("[INFO] Starting PostgreSQL backup...")
        
        # Use pg_dump to create backup
        cmd = f'pg_dump {database_url} > "{backup_path}"'
        
        # For Windows, use PowerShell
        if os.name == 'nt':
            subprocess.run(["powershell", "-Command", cmd], check=True, capture_output=True)
        else:
            subprocess.run(cmd, shell=True, check=True)
        
        if os.path.exists(backup_path):
            file_size = os.path.getsize(backup_path) / (1024 * 1024)  # Convert to MB
            print(f"[SUCCESS] PostgreSQL backup created successfully!")
            print(f"   File: {backup_filename}")
            print(f"   Size: {file_size:.2f} MB")
            print(f"   Path: {backup_path}")
            return True
        else:
            print("[ERROR] Backup file was not created")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Error creating PostgreSQL backup: {e}")
        print(f"   Note: Make sure pg_dump is installed and in your PATH")
        return False
    except Exception as e:
        print(f"[ERROR] Error creating PostgreSQL backup: {e}")
        return False

def cleanup_old_backups(backup_dir, keep_count=10):
    """Keep only the most recent backups"""
    try:
        # Get all backup files
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith('shoeclinic_backup_')]
        
        if len(backup_files) > keep_count:
            # Sort by modification time
            backup_files.sort(key=lambda x: os.path.getmtime(os.path.join(backup_dir, x)))
            
            # Remove oldest backups
            files_to_remove = backup_files[:-keep_count]
            for file in files_to_remove:
                file_path = os.path.join(backup_dir, file)
                os.remove(file_path)
                print(f"[INFO] Removed old backup: {file}")
            
            print(f"[INFO] Kept {keep_count} most recent backups")
    except Exception as e:
        print(f"[WARN] Error cleaning up old backups: {e}")

def main():
    print("========================================")
    print("  Pre-Deployment Backup Script")
    print("  Shoe Clinic API")
    print("========================================")
    print()
    
    # Create backup directory
    backup_dir = create_backup_directory()
    
    # Get database URL from environment
    from dotenv import load_dotenv
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL', 'sqlite:///shoeclinic.db')
    
    print(f"[DB] Database: {database_url.split('@')[0] if '@' in database_url else database_url}")
    print()
    
    # Determine database type and create backup
    success = False
    if database_url.startswith('sqlite'):
        # Extract database path from sqlite URL
        db_path = database_url.replace('sqlite:///', '')
        
        # If relative path, make it absolute
        if not os.path.isabs(db_path):
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), db_path)
        
        success = backup_sqlite(db_path, backup_dir)
    
    elif database_url.startswith('postgresql') or database_url.startswith('postgres'):
        success = backup_postgresql(database_url, backup_dir)
    
    else:
        print(f"[ERROR] Unsupported database type: {database_url.split(':')[0]}")
        return
    
    if success:
        print()
        print("[INFO] Cleaning up old backups...")
        cleanup_old_backups(backup_dir, keep_count=10)
        print()
        print("========================================")
        print("  [SUCCESS] Backup completed successfully!")
        print("  You can now safely deploy updates.")
        print("========================================")
    else:
        print()
        print("========================================")
        print("  [ERROR] Backup failed!")
        print("  Do NOT deploy until backup succeeds.")
        print("========================================")
        sys.exit(1)

if __name__ == '__main__':
    main()
