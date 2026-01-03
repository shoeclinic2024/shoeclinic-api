import re
import os

files_to_patch = ['e:/app_v02/app.py', 'e:/app_v02/admin.py']

replacements = [
    (r'\bExpense\.request_type\b', '"none"'),
    (r'\bExpense\.request_reason\b', '"none"'),
    (r'\bExpense\.request_data\b', '"none"'),
    (r'\bexpense\.request_type\b', '"none"'),
    (r'\bexpense\.request_reason\b', '"none"'),
    (r'\bexpense\.request_data\b', '"none"'),
    (r'\bv_item\.order\.vendor_amount\b', '0.0'),
    (r'\border\.vendor_amount\b', '0.0'),
    (r'\bo\.vendor_amount\b', '0.0'),
    (r'\bcurrent_user\.first_login_seen\b', 'False'),
    (r'\buser\.first_login_seen\b', 'False'),
    # Assignments (Greedy matching to comment out whole line)
    (r'.*expense\.request_type\s*=.*', '# Attribute assignment removed'),
    (r'.*expense\.request_reason\s*=.*', '# Attribute assignment removed'),
    (r'.*expense\.request_data\s*=.*', '# Attribute assignment removed'),
    (r'.*order\.vendor_amount\s*=.*', '# Attribute assignment removed'),
]

for file_path in files_to_patch:
    if not os.path.exists(file_path):
        print(f"Skipping {file_path}, not found.")
        continue
        
    print(f"Patching {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for pattern, replacement in replacements:
        new_content = re.sub(pattern, replacement, new_content)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

print("Done patching.")
