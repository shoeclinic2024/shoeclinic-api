
import psycopg2
import sys

# Candidates to try
PASSWORDS_TO_TRY = [
    "ChamundiHillskarnataka123",       # The one in your screenshot
    "ChamundiHills@karnataka123",      # The original one (with @)
    "K4rn4takaShoeClinicSecure9988"    # The one you tried to set
]

TARGET_PASSWORD = "ShoeClinic2025"    # The simple, safe password we want

HOST = "trolley.proxy.rlwy.net"
PORT = "40006"
DB = "railway"
USER = "postgres"

def try_fix():
    print("[*] Magic Fixer Starting...")
    
    for password in PASSWORDS_TO_TRY:
        print(f"[*] Trying password: {password} ...")
        try:
            conn = psycopg2.connect(
                host=HOST,
                port=PORT,
                database=DB,
                user=USER,
                password=password
            )
            conn.autocommit = True
            cur = conn.cursor()
            print(f"[+] SUCCESS! We got in with: {password}")
            
            print(f"[*] Force-updating password to: {TARGET_PASSWORD} ...")
            cur.execute(f"ALTER USER postgres WITH PASSWORD '{TARGET_PASSWORD}';")
            print("[+] PASSWORD UPDATED SUCCESSFULLY!")
            
            cur.close()
            conn.close()
            return True
            
        except psycopg2.OperationalError:
            print("[-] No luck with this one.")
        except Exception as e:
            print(f"[-] Error: {e}")

    print("[x] All guesses failed. The password is something else entirely.")
    return False

if __name__ == "__main__":
    if try_fix():
        print("\n[+] SUCCESS! Now update your .env file to use password: ShoeClinic2025")
    else:
        print("\n[x] FAILED. We need to use the Railway Terminal manually.")
