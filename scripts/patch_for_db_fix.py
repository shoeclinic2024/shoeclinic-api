import re
import os

files_to_patch = ['e:/app_v02/app.py', 'e:/app_v02/admin.py']

replacements = [
    # 1. First, comment out any line that performs an assignment to these attributes
    # We use a broad match for any line containing 'attribute ='
    (r'.*\b(expense|order|user|current_user|v_item\.order)\.(request_type|request_reason|request_data|vendor_amount|first_login_seen)\s*=.*', '# Line commented: Attribute assignment'),
    
    # 2. Then, replace attribute access in expressions (getters)
    (r'\b(Expense|expense)\.(request_type|request_reason|request_data)\b', '"none"'),
    (r'\b(order|o|v_item\.order)\.vendor_amount\b', '0.0'),
    (r'\b(user|current_user)\.first_login_seen\b', 'False'),
]

for file_path in files_to_patch:
    if not os.path.exists(file_path):
        print(f"Skipping {file_path}, not found.")
        continue
        
    print(f"Patching {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    # We process each pattern on the whole content
    for pattern, replacement in replacements:
        new_content = re.sub(pattern, replacement, new_content)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

print("Done patching.")
