import re
import os

files_to_patch = ['e:/app_v02/app.py', 'e:/app_v02/admin.py', 'e:/app_v02/models.py']

# (pattern, replacement, is_line_replacement)
replacements = [
    # Models.py definitions
    (r'^\s*(first_login_seen|vendor_amount|request_type|request_reason|request_data)\s*=\s*db\.Column.*$', r'    # \1 removed temporarily'),
    
    # Assignments (MUST keep indentation and provide a valid statement like 'pass' to avoid IndentationError)
    (r'^(\s*).*?\b(expense|order|user|current_user|v_item\.order)\.(request_type|request_reason|request_data|vendor_amount|first_login_seen)\s*=.*$', r'\1pass # Attribute assignment removed'),
    
    # Expressions / Getters
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
        lines = f.readlines()
    
    new_lines = []
    for line in lines:
        new_line = line
        for pattern, replacement in replacements:
            # We use MULTILINE-like behavior by processing line-by-line
            new_line = re.sub(pattern, replacement, new_line)
        new_lines.append(new_line)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

print("Done patching.")
