
import os
from app import app, db
from models import Expense
from sqlalchemy import func

# Force absolute path if needed, but app.py seems to use relative.
# Let's check where the file actually is.
print(f"CWD: {os.getcwd()}")
print(f"DB URI: {app.config['SQLALCHEMY_DATABASE_URI']}")

with app.app_context():
    # Filter for Jan 2026
    expenses = Expense.query.filter(
        func.strftime('%Y-%m', Expense.expense_date) == '2026-01',
        Expense.status == 'approved'
    ).all()
    
    print(f"\n{'ID':<5} {'Date':<12} {'Category':<15} {'Amount':<10} {'RealAmount':<10} {'Calculated':<10} {'Title'}")
    print("-" * 90)
    
    total_val = 0
    for e in expenses:
        # Replicate admin.py logic exactly
        val = e.real_amount or e.amount or 0
        total_val += val
        
        print(f"{e.id:<5} {str(e.expense_date):<12} {e.category[:15]:<15} {str(e.amount):<10} {str(e.real_amount):<10} {val:<10.2f} {e.title}")
        
    print("-" * 90)
    print(f"TOTAL: {total_val}")
