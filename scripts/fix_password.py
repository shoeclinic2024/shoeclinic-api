
import os
import psycopg2
from urllib.parse import urlparse

# The OLD credentials (currently active on the server, visible in your screenshot)
# We use this to get in one last time.
OLD_DB_URL = "postgresql://postgres:ChamundiHillskarnataka123@trolley.proxy.rlwy.net:40006/railway"

# The NEW password you want to set (to match your local .env)
NEW_PASSWORD = "K4rn4takaShoeClinicSecure9988"

def fix_password():
    print(f"[*] Attempting to connect with OLD credentials...")
    try:
        conn = psycopg2.connect(OLD_DB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("[*] Connection successful! Updating password now...")
        
        # The SQL command to force the update
        cur.execute(f"ALTER USER postgres WITH PASSWORD '{NEW_PASSWORD}';")
        
        print(f"[+] SUCCESS! Password updated to: {NEW_PASSWORD}")
        print("[*] You can now run the sync script.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"[-] Failed: {e}")
        print("    (This might mean the old password we guessed is wrong, or the update already happened.)")

if __name__ == "__main__":
    fix_password()
