# -*- coding: utf-8 -*-
# admin.py
from flask import Blueprint, render_template, flash, request, redirect, url_for, jsonify, send_file
from flask_login import login_required, current_user
from database import db
from models import User, Expense, Notification, Staff, Attendance, Order, OrderItem, ManualTask
import io
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import extract, func
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from functools import wraps
import json
import base64

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'super_admin']:
            flash("Access denied. Authorized personnel only.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash("Access denied. Super Admin privileges required.", "danger")
            return redirect(request.referrer or url_for('home'))
        return f(*args, **kwargs)
    return decorated_function



# Define Blueprint
admin_bp = Blueprint("admin", __name__, template_folder="templates")

# Admin Panel Home
@admin_bp.route("/panel", endpoint="admin_panel")
@login_required
@admin_required
def panel():
    data = {}
    if current_user.role == 'super_admin':
        # Get counts for the Superior Control badge
        data['pending_users'] = User.query.filter_by(is_active=False).count()
        data['pending_expenses'] = Expense.query.filter_by(status='pending').count()
        data['pending_access'] = User.query.filter_by(customer_view_requested=True).count()
        data['modification_requests'] = Expense.query.filter(Expense.request_type != 'none').count()
        data['total_pending'] = data['pending_users'] + data['pending_expenses'] + data['pending_access'] + data['modification_requests']
    
    # Detect Database Engine
    from flask import current_app
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'postgresql' in db_uri or 'postgres' in db_uri:
        data['db_engine'] = 'PostgreSQL (Production)'
    else:
        data['db_engine'] = 'SQLite (Local)'
    
    return render_template("admin_panel.html", now=datetime.utcnow(), **data)

# Manage Users
@admin_bp.route("/manage_users")
@login_required
@admin_required
def manage_users():
    try:
        users = User.query.order_by(User.username).all()
        return render_template("admin/manage_users.html", users=users)
    except Exception as e:
        print(f"ERROR: {str(e)}")
        flash(f"Error loading users: {str(e)}", "danger")
        return render_template("admin/manage_users.html", users=[])

@admin_bp.route("/add_user", methods=["GET", "POST"])
@login_required
@admin_required
def add_user():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        is_active = request.form.get("is_active") == "on"

        # Check existing
        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for("admin.add_user"))
        
        # Validate Password
        from security_service import security_service
        is_valid, msg = security_service.validate_password_strength(password)
        if not is_valid:
            flash(f"Password Error: {msg}", "danger")
            return redirect(url_for("admin.add_user"))

        # Hash
        from flask_bcrypt import Bcrypt
        bcrypt = Bcrypt()
        hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
        
        new_user = User(
            username=username, 
            password=hashed_pw, 
            role=role, 
            is_active=is_active
        )
        
        db.session.add(new_user)
        db.session.commit() # Commit first to generate ID
        
        # Add to history
        security_service.save_password_history(new_user, hashed_pw)
        db.session.commit()
        
        flash(f"User {username} created successfully!", "success")
        return redirect(url_for("admin.manage_users"))
        
    return render_template("admin/add_user.html")


@admin_bp.route("/reset_user_password/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def reset_user_password(user_id):
    """Admin resets a user's password"""
    if current_user.role != 'super_admin':
        flash("Only Super Admin can reset passwords.", "danger")
        return redirect(url_for('admin.manage_users'))

    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password")
    
    if not new_password or len(new_password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for('admin.manage_users'))

    from security_service import security_service
    is_valid, msg = security_service.validate_password_strength(new_password, user)
    if not is_valid:
        flash(f"Error: {msg}", "danger")
        return redirect(url_for('admin.manage_users'))

    from flask_bcrypt import Bcrypt
    bcrypt = Bcrypt()
    pw_hash = bcrypt.generate_password_hash(new_password).decode("utf-8")
    user.password = pw_hash
    
    # Save to history
    security_service.save_password_history(user, pw_hash)
    
    # Reset lockouts
    user.failed_login_attempts = 0
    user.account_locked_until = None
    
    db.session.commit()
    flash(f"Password for {user.username} has been reset.", "success")
    return redirect(url_for('admin.manage_users'))

@admin_bp.route("/reset_user_2fa/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def reset_user_2fa(user_id):
    """Admin resets a user's 2FA (disables it)"""
    if current_user.role != 'super_admin':
        flash("Only Super Admin can reset 2FA.", "danger")
        return redirect(url_for('admin.manage_users'))

    user = User.query.get_or_404(user_id)
    user.two_factor_enabled = False
    user.two_factor_secret = None
    db.session.commit()
    
    flash(f"2FA has been disabled for {user.username}. They must set it up again.", "warning")
    return redirect(url_for('admin.manage_users'))

# --- Staff Management ---
@admin_bp.route("/manage_staff")
@login_required
@admin_required
def manage_staff():
    staff_list = Staff.query.order_by(Staff.name).all()
    # Fetch active users for linking
    users = User.query.filter_by(is_active=True).order_by(User.username).all()
    return render_template("admin/manage_staff.html", staff_list=staff_list, users=users)

@admin_bp.route("/add_staff", methods=["POST"])
@login_required
@admin_required
def add_staff():
    name = request.form.get("name")
    mobile = request.form.get("mobile")
    place = request.form.get("place")
    salary_type = request.form.get("salary_type", "monthly")
    base_salary = float(request.form.get("base_salary", 0))
    user_id = request.form.get("user_id")

    if not name:
        flash("Name is required.", "danger")
        return redirect(url_for("admin.manage_staff"))

    if Staff.query.filter_by(name=name).first():
        flash("Staff member already exists.", "danger")
    else:
        new_staff = Staff(
            name=name, 
            mobile=mobile, 
            place=place, 
            salary_type=salary_type, 
            base_salary=base_salary,
            user_id=int(user_id) if user_id and user_id != "" else None
        )
        db.session.add(new_staff)
        db.session.commit()
        flash(f"Staff {name} added successfully.", "success")
    
    return redirect(url_for("admin.manage_staff"))

@admin_bp.route("/edit_staff/<int:id>", methods=["POST"])
@login_required
@admin_required
def edit_staff(id):
    staff = Staff.query.get_or_404(id)
    staff.mobile = request.form.get("mobile")
    staff.place = request.form.get("place")
    staff.salary_type = request.form.get("salary_type")
    staff.base_salary = float(request.form.get("base_salary", 0))
    user_id = request.form.get("user_id")
    staff.user_id = int(user_id) if user_id and user_id != "" else None
    
    db.session.commit()
    flash(f"Updated record for {staff.name}.", "success")
    return redirect(url_for("admin.manage_staff"))

@admin_bp.route("/delete_staff/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_staff(id):
    staff = Staff.query.get_or_404(id)
    db.session.delete(staff)
    db.session.commit()
    flash(f"Staff {staff.name} removed.", "warning")
    return redirect(url_for("admin.manage_staff"))

# Analytics Dashboard
@admin_bp.route("/analytics")
@login_required
@admin_required
def analytics():
    try:
        from datetime import datetime, timedelta
        from models import Order
        
        # Get all orders
        all_orders = Order.query.all()
        all_expenses = Expense.query.filter_by(status="approved").all()
        today = datetime.utcnow().date()
        
        # Generate list of available months and years for dropdowns if needed
        available_months = []
        available_years = []
        for order in all_orders:
            if order.pickup_date:
                m_key, y_key = order.pickup_date.strftime('%Y-%m'), str(order.pickup_date.year)
                if m_key not in available_months: available_months.append(m_key)
                if y_key not in available_years: available_years.append(y_key)
        
        available_months.sort(reverse=True)
        available_years.sort(reverse=True)
        
        # Week range
        this_week_start = today - timedelta(days=today.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)
        
        
        
        def filter_expenses(exp_list, start, end):
            return [e for e in exp_list if start <= e.expense_date <= end]

        def get_place_analysis(orders):
            stats = {}
            for order in orders:
                p = order.place or "Unknown"
                if p not in stats: stats[p] = {'name': p, 'count': 0, 'revenue': 0}
                stats[p]['count'] += 1
                stats[p]['revenue'] += float(order.price or 0)
            return sorted(stats.values(), key=lambda x: x['revenue'], reverse=True)

        def get_customer_analysis(orders):
            stats = {}
            for order in orders:
                c = order.mobile or "N/A"
                if c not in stats: stats[c] = {'mobile': c, 'name': order.customer_name or "Unknown", 'count': 0, 'revenue': 0}
                stats[c]['count'] += 1
                stats[c]['revenue'] += float(order.price or 0)
            return sorted(stats.values(), key=lambda x: x['revenue'], reverse=True)

        def get_service_analysis(orders):
            stats = {}
            for order in orders:
                for item in order.items:
                    if item.services:
                        for svc in item.services.split(','):
                            svc = svc.strip()
                            if svc:
                                if svc not in stats: stats[svc] = {'name': svc, 'count': 0, 'revenue': 0}
                                stats[svc]['count'] += 1
                                stats[svc]['revenue'] += float(item.price or 0)
            
            sorted_stats = sorted(stats.values(), key=lambda x: x['revenue'], reverse=True)
            total_svcs = sum(s['count'] for s in sorted_stats)
            top_svc = sorted_stats[0]['name'] if sorted_stats else "N/A"
            return sorted_stats, total_svcs, top_svc

        def get_metrics(orders, expenses=[]):
            total_rev = sum([float(o.price or 0) for o in orders])
            total_discount = sum([float(o.discount or 0) if o.discount else 0 for o in orders])
            
            # Billed Revenue: Sum of price for orders with specific payment status or tracked status
            billed_rev = sum([float(o.price or 0) for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])])
            
            # Status Analysis
            total = len(orders)
            done = len([o for o in orders if o.status and 'done' in o.status.lower()])
            wip = len([o for o in orders if o.status and 'wip' in o.status.lower()])
            yts = len([o for o in orders if o.status and ('yts' in o.status.lower() or 'yet' in o.status.lower())])
            
            # Billing Logic
            billed_count = len([o for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])])
            unbilled_count = total - billed_count
            
            # Service sub-analysis
            _, total_svcs, top_svc = get_service_analysis(orders)
            

            # Vendor Cost calculation to prevent double-counting
            total_vendor_cost = 0.0
            processed_v_ids = set()
            for o in orders:
                if o.vendor_amount and o.vendor_amount > 0 and o.id not in processed_v_ids:
                    total_vendor_cost += float(o.vendor_amount)
                    processed_v_ids.add(o.id)

            total_exp = sum([float(e.amount or 0) for e in expenses]) + total_vendor_cost
            margin = total_rev - total_exp
            margin_p = (margin / total_rev * 100) if total_rev > 0 else 0
            exp_p = (total_exp / total_rev * 100) if total_rev > 0 else 0
            return {
                'revenue': total_rev,
                'billed_revenue': billed_rev,
                'discount': total_discount,
                'net': total_rev - total_discount,
                'orders': total,
                'completed': done,
                'wip': wip,
                'yts': yts,
                'billed': billed_count,
                'unbilled': unbilled_count,
                'pending': total - done,
                'completion_rate': (done / total * 100) if total > 0 else 0,
                'billing_rate': (billed_count / total * 100) if total > 0 else 0,
                'avg_order_value': (total_rev / total) if total > 0 else 0,
                'total_services': total_svcs,
                'top_service': top_svc,
                'svcs_per_order': (total_svcs / total) if total > 0 else 0,
                'total_vendor_cost': total_vendor_cost,
                'total_expense': total_exp,
                'profit_margin': margin,
                'margin_percentage': margin_p,
                'expense_percentage': exp_p
            }
        
        this_week_orders = [o for o in all_orders if o.pickup_date and this_week_start <= o.pickup_date.date() <= today]
        last_week_orders = [o for o in all_orders if o.pickup_date and last_week_start <= o.pickup_date.date() <= last_week_end]
        
        this_week = get_metrics(this_week_orders, filter_expenses(all_expenses, this_week_start, today))
        last_week = get_metrics(last_week_orders, filter_expenses(all_expenses, last_week_start, last_week_end))
        
        def calc_growth(current, previous):
            if previous == 0:
                return 0 if current == 0 else 100
            return ((current - previous) / previous * 100)
        
        week_growth = calc_growth(this_week['revenue'], last_week['revenue'])
        
        # Simplified Filter Logic
        filter_type = request.args.get('filter_type', 'month')  # daily, month, year
        filter_date = request.args.get('filter_date', today.strftime('%Y-%m-%d'))
        filter_month = request.args.get('filter_month', today.strftime('%Y-%m'))
        filter_year = request.args.get('filter_year', str(today.year))

        # Main Analysis Period
        if filter_type == 'daily':
            try:
                d1_start = datetime.strptime(filter_date, '%Y-%m-%d').date()
                d1_end = d1_start
            except:
                d1_start = d1_end = today
            month1_label = d1_start.strftime('%d %B %Y')
            # Compare to previous day
            d2_start = d2_end = d1_start - timedelta(days=1)
            month2_label = d2_start.strftime('%d %B %Y')
        elif filter_type == 'year':
            try:
                y_val = int(filter_year)
                d1_start = datetime(year=y_val, month=1, day=1).date()
                d1_end = datetime(year=y_val, month=12, day=31).date()
            except:
                d1_start = datetime(year=today.year, month=1, day=1).date()
                d1_end = datetime(year=today.year, month=12, day=31).date()
            month1_label = f"Year {d1_start.year}"
            # Compare to previous year
            d2_start = d1_start.replace(year=d1_start.year - 1)
            d2_end = d1_end.replace(year=d1_end.year - 1)
            month2_label = f"Year {d2_start.year}"
        else: # monthly (default)
            try:
                d1_start = datetime.strptime(filter_month, '%Y-%m').date()
            except:
                d1_start = today.replace(day=1)
            
            if d1_start.month == 12:
                d1_end = d1_start.replace(year=d1_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                d1_end = d1_start.replace(month=d1_start.month + 1, day=1) - timedelta(days=1)
            month1_label = d1_start.strftime('%B %Y')
            
            # Compare to previous month
            d2_start = (d1_start - timedelta(days=1)).replace(day=1)
            if d2_start.month == 12:
                d2_end = d2_start.replace(year=d2_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                d2_end = d2_start.replace(month=d2_start.month + 1, day=1) - timedelta(days=1)
            month2_label = d2_start.strftime('%B %Y')

        # Filter Orders for selected periods
        month1_orders = [o for o in all_orders if o.pickup_date and d1_start <= o.pickup_date.date() <= d1_end]
        month2_orders = [o for o in all_orders if o.pickup_date and d2_start <= o.pickup_date.date() <= d2_end]
        
        month1 = get_metrics(month1_orders, filter_expenses(all_expenses, d1_start, d1_end))
        month2 = get_metrics(month2_orders, filter_expenses(all_expenses, d2_start, d2_end))
        month_growth = calc_growth(month1['revenue'], month2['revenue'])
        
        # Service Analysis for filtered period
        service_list, _, _ = get_service_analysis(month1_orders)
        place_list = get_place_analysis(month1_orders)
        customer_list = get_customer_analysis(month1_orders)
        
        # Yearly defaults (for template backwards compatibility if needed)
        year1 = month1 if filter_type == 'year' else get_metrics([o for o in all_orders if o.pickup_date and o.pickup_date.year == today.year])
        year2 = month2 if filter_type == 'year' else get_metrics([o for o in all_orders if o.pickup_date and o.pickup_date.year == today.year - 1])
        year_growth = calc_growth(year1['revenue'], year2['revenue'])
        year1_label = str(today.year)
        year2_label = str(today.year - 1)
        
        # ===== TECHNICIAN PERFORMANCE (Filtered by Selected Period) =====
        technician_stats = {}
        for order in month1_orders:
            if order.technician and order.technician != 'None':
                if order.technician not in technician_stats:
                    technician_stats[order.technician] = {
                        'name': order.technician,
                        'orders': 0,
                        'revenue': 0,
                        'completed': 0,
                        'pending': 0
                    }
                tech = technician_stats[order.technician]
                tech['orders'] += 1
                tech['revenue'] += float(order.price or 0)
                if order.status and 'done' in order.status.lower():
                    tech['completed'] += 1
                else:
                    tech['pending'] += 1
        
        technician_list = sorted(technician_stats.values(), key=lambda x: x['revenue'], reverse=True)
        for tech in technician_list:
            tech['completion_rate'] = (tech['completed'] / tech['orders'] * 100) if tech['orders'] > 0 else 0
            tech['avg_per_order'] = (tech['revenue'] / tech['orders']) if tech['orders'] > 0 else 0
        
        # ===== MONTHLY TREND =====
        monthly_trend = {}
        for i in range(12, -1, -1):
            month_date = today - timedelta(days=30*i)
            month_key = month_date.strftime('%b %Y')
            month_start = month_date.replace(day=1)
            if month_date.month == 12:
                month_end = month_date.replace(year=month_date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
            
            month_orders = [o for o in all_orders if o.pickup_date and month_start <= o.pickup_date.date() <= month_end]
            m_metrics = get_metrics(month_orders, filter_expenses(all_expenses, month_start, month_end))

            monthly_trend[month_key] = {
                'revenue': m_metrics['revenue'],
                'billed_revenue': m_metrics['billed_revenue'],
                'orders': m_metrics['orders'],
                'services': m_metrics['total_services'],
                'expense': m_metrics['total_expense'],
                'profit': m_metrics['profit_margin']
            }
        
        return render_template("admin/analytics.html",
                             filter_type=filter_type,
                             filter_date=filter_date,
                             filter_month=filter_month,
                             filter_year=filter_year,
                             this_week=this_week,
                             last_week=last_week,
                             week_growth=week_growth,
                             month1=month1,
                             month2=month2,
                             month1_label=month1_label,
                             month2_label=month2_label,
                             month_growth=month_growth,
                             year1=year1,
                             year2=year2,
                             year_growth=year_growth,
                             technician_list=technician_list,
                             service_list=service_list,
                             place_list=place_list,
                             customer_list=customer_list,
                             monthly_trend=monthly_trend)
    
    except Exception as e:
        print(f"ERROR in analytics: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading analytics: {str(e)}", "danger")
        return redirect(url_for('admin.admin_panel'))

@admin_bp.route("/export_analytics_excel")
@login_required
@super_admin_required
def export_analytics_excel():
    from models import Order, Expense
    import pandas as pd
    import io

    filter_type = request.args.get('filter_type', 'month')
    filter_date = request.args.get('filter_date', datetime.utcnow().strftime('%Y-%m-%d'))
    filter_month = request.args.get('filter_month', datetime.utcnow().strftime('%Y-%m'))
    filter_year = request.args.get('filter_year', str(datetime.utcnow().year))
    
    today = datetime.utcnow().date()
    all_orders = Order.query.all()
    all_expenses = Expense.query.filter_by(status="approved").all()
    
    # Replicate filter logic
    if filter_type == 'daily':
        try: d1_start = datetime.strptime(filter_date, '%Y-%m-%d').date()
        except: d1_start = today
        d1_end = d1_start
        label = d1_start.strftime('%d_%b_%Y')
    elif filter_type == 'year':
        try: y_val = int(filter_year)
        except: y_val = today.year
        d1_start = datetime(year=y_val, month=1, day=1).date()
        d1_end = datetime(year=y_val, month=12, day=31).date()
        label = f"Year_{y_val}"
    else:
        try: d1_start = datetime.strptime(filter_month, '%Y-%m').date()
        except: d1_start = today.replace(day=1)
        if d1_start.month == 12: d1_end = d1_start.replace(year=d1_start.year + 1, month=1, day=1) - timedelta(days=1)
        else: d1_end = d1_start.replace(month=d1_start.month + 1, day=1) - timedelta(days=1)
        label = d1_start.strftime('%b_%Y')

    orders = [o for o in all_orders if o.pickup_date and d1_start <= o.pickup_date.date() <= d1_end]
    expenses = [e for e in all_expenses if d1_start <= e.expense_date <= d1_end]

    # Calculate summaries
    total_rev = sum([float(o.price or 0) for o in orders])
    
    total_vendor_cost = 0.0
    processed_v_ids = set()
    for o in orders:
        if o.vendor_amount and o.vendor_amount > 0 and o.id not in processed_v_ids:
            total_vendor_cost += float(o.vendor_amount)
            processed_v_ids.add(o.id)

    total_exp = sum([float(e.amount or 0) for e in expenses]) + total_vendor_cost
    billed_rev = sum([float(o.price or 0) for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])])
    
    # 1. Summary Data
    summary_data = [
        {'Metric': 'Total Revenue (Gross)', 'Value': total_rev},
        {'Metric': 'Billed Revenue (Actual)', 'Value': billed_rev},
        {'Metric': 'Operational Expenses', 'Value': total_exp - total_vendor_cost},
        {'Metric': 'Vendor Costs', 'Value': total_vendor_cost},
        {'Metric': 'Total Expenses', 'Value': total_exp},
        {'Metric': 'Net Profit', 'Value': total_rev - total_exp},
        {'Metric': 'Profit Margin (%)', 'Value': ((total_rev-total_exp)/total_rev*100) if total_rev > 0 else 0},
        {'Metric': 'Total Orders', 'Value': len(orders)}
    ]
    
    # 2. Detailed Orders Data
    orders_data = []
    for o in orders:
        svcs = []
        for it in o.items:
            if it.services: svcs.extend([s.strip() for s in it.services.split(',') if s.strip()])
        orders_data.append({
            'ID': o.id, 'Customer': o.customer_name, 'Mobile': o.mobile, 'Place': o.place,
            'Date': o.pickup_date.strftime('%d-%b-%Y') if o.pickup_date else '-',
            'Status': o.status, 'Technician': o.technician or 'None',
            'Services': ', '.join(svcs), 'Amount': float(o.price or 0)
        })

    # 3. Geo & Service Ranking Data
    places = {}
    svcs_stats = {}
    for o in orders:
        p = o.place or "Unknown"
        places[p] = places.get(p, 0) + float(o.price or 0)
        for it in o.items:
            if it.services:
                for s in it.services.split(','):
                    s = s.strip()
                    if s: svcs_stats[s] = svcs_stats.get(s, 0) + float(it.price or 0)
    
    places_data = [{'Location': k, 'Revenue': v} for k, v in sorted(places.items(), key=lambda x: x[1], reverse=True)]
    svcs_data = [{'Service': k, 'Revenue': v} for k, v in sorted(svcs_stats.items(), key=lambda x: x[1], reverse=True)]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame(summary_data).to_excel(writer, index=False, sheet_name='Executive Summary')
        pd.DataFrame(orders_data).to_excel(writer, index=False, sheet_name='Detailed Orders')
        pd.DataFrame(places_data).to_excel(writer, index=False, sheet_name='Geography Analysis')
        pd.DataFrame(svcs_data).to_excel(writer, index=False, sheet_name='Service Rankings')
    
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"Advanced_Analytics_{label}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def add_watermark(canvas, doc):
    """Add watermark to PDF pages"""
    canvas.saveState()
    canvas.setFont('Helvetica-Bold', 55)
    canvas.setFillGray(0.9)
    canvas.translate(300, 400)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "The Shoe Clinic")
    canvas.restoreState()

@admin_bp.route("/export_analytics_pdf")
@login_required
@super_admin_required
def export_analytics_pdf():
    from models import Order, Expense
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    
    filter_type = request.args.get('filter_type', 'month')
    filter_date = request.args.get('filter_date', datetime.utcnow().strftime('%Y-%m-%d'))
    filter_month = request.args.get('filter_month', datetime.utcnow().strftime('%Y-%m'))
    filter_year = request.args.get('filter_year', str(datetime.utcnow().year))
    
    today = datetime.utcnow().date()
    all_orders = Order.query.all()
    all_expenses = Expense.query.filter_by(status="approved").all()
    
    def filter_expenses(exp_list, start, end):
        return [e for e in exp_list if start <= e.expense_date <= end]

    # Replicate filter logic from analytics()
    if filter_type == 'daily':
        try: d1_start = datetime.strptime(filter_date, '%Y-%m-%d').date()
        except: d1_start = today
        d1_end = d1_start
        label = d1_start.strftime('%d %B %Y')
        d2_start = d2_end = d1_start - timedelta(days=1)
    elif filter_type == 'year':
        try: y_val = int(filter_year)
        except: y_val = today.year
        d1_start = datetime(year=y_val, month=1, day=1).date()
        d1_end = datetime(year=y_val, month=12, day=31).date()
        label = f"Year {y_val}"
        d2_start = d1_start.replace(year=d1_start.year - 1)
        d2_end = d1_end.replace(year=d1_end.year - 1)
    else:
        try: d1_start = datetime.strptime(filter_month, '%Y-%m').date()
        except: d1_start = today.replace(day=1)
        if d1_start.month == 12: d1_end = d1_start.replace(year=d1_start.year + 1, month=1, day=1) - timedelta(days=1)
        else: d1_end = d1_start.replace(month=d1_start.month + 1, day=1) - timedelta(days=1)
        label = d1_start.strftime('%B %Y')
        d2_start = (d1_start - timedelta(days=1)).replace(day=1)
        if d2_start.month == 12: d2_end = d2_start.replace(year=d2_start.year + 1, month=1, day=1) - timedelta(days=1)
        else: d2_end = d2_start.replace(month=d2_start.month + 1, day=1) - timedelta(days=1)

    period_orders = [o for o in all_orders if o.pickup_date and d1_start <= o.pickup_date.date() <= d1_end]
    prev_orders = [o for o in all_orders if o.pickup_date and d2_start <= o.pickup_date.date() <= d2_end]
    period_expenses = filter_expenses(all_expenses, d1_start, d1_end)
    prev_expenses = filter_expenses(all_expenses, d2_start, d2_end)

    def get_metrics(orders, expenses):
        rev = sum([float(o.price or 0) for o in orders])
        
        v_cost = 0.0
        p_ids = set()
        for o in orders:
            if o.vendor_amount and o.vendor_amount > 0 and o.id not in p_ids:
                v_cost += float(o.vendor_amount)
                p_ids.add(o.id)

        exp = sum([float(e.amount or 0) for e in expenses]) + v_cost
        billed = sum([float(o.price or 0) for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])])
        return {'rev': rev, 'exp': exp, 'billed': billed, 'profit': rev - exp, 'margin': ((rev-exp)/rev*100) if rev > 0 else 0, 'orders': len(orders)}

    m1 = get_metrics(period_orders, period_expenses)
    m2 = get_metrics(prev_orders, prev_expenses)
    growth = ((m1['rev'] - m2['rev']) / m2['rev'] * 100) if m2['rev'] > 0 else (100 if m1['rev'] > 0 else 0)

    # ReportLab Generation
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor("#4f46e5"), alignment=1, spaceAfter=20)
    section_style = ParagraphStyle('SectionStyle', parent=styles['Heading2'], fontSize=14, textColor=colors.black, spaceBefore=15, spaceAfter=10)
    kpi_val_style = ParagraphStyle('KPIVal', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', alignment=1)
    kpi_lab_style = ParagraphStyle('KPILab', parent=styles['Normal'], fontSize=9, textColor=colors.grey, alignment=1)
    
    elements = []
    
    # Title
    elements.append(Paragraph(f"The Shoe Clinic - Executive Analytics", header_style))
    elements.append(Paragraph(f"Period: {label} ({filter_type.capitalize()} Analysis)", styles['Normal']))
    elements.append(Spacer(1, 15))

    # KPI Summary Table
    kpi_data = [
        [Paragraph("Gross Revenue", kpi_lab_style), Paragraph("Billed Revenue", kpi_lab_style), Paragraph("Total Expenses", kpi_lab_style), Paragraph("Net Profit", kpi_lab_style)],
        [Paragraph(f"INR {m1['rev']:,.2f}", kpi_val_style), Paragraph(f"INR {m1['billed']:,.2f}", kpi_val_style), Paragraph(f"INR {m1['exp']:,.2f}", kpi_val_style), Paragraph(f"INR {m1['profit']:,.2f}", kpi_val_style)]
    ]
    kpi_table = Table(kpi_data, colWidths=[1.3*inch, 1.3*inch, 1.3*inch, 1.3*inch])
    kpi_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.lightgrey),
        ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 20))

    # Growth & Health Section
    elements.append(Paragraph("Business Growth & Financial Health", section_style))
    
    # Growth Bar "Visual"
    growth_color = colors.green if growth >= 0 else colors.red
    health_data = [
        ["Revenue Velocity:", f"{growth:+.1f}% vs Previous Period"],
        ["Profit Margin:", f"{m1['margin']:.1f}% Efficiency"],
        ["Total Orders:", f"{m1['orders']} Jobs Processed"]
    ]
    health_table = Table(health_data, colWidths=[200, 300])
    health_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1,0), (1,0), growth_color),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#dcfce7') if growth >= 0 else colors.HexColor('#fee2e2')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    ]))
    elements.append(health_table)
    elements.append(Spacer(1, 15))

    # --- Trend Chart for PDF ---
    elements.append(Paragraph("Revenue vs Expense Trend (Last 6 Months)", section_style))
    
    # Calculate Trend
    rev_vals = []
    exp_vals = []
    trend_lbls = []
    for i in range(5, -1, -1):
        t_date = today - timedelta(days=30*i)
        t_start = t_date.replace(day=1)
        if t_start.month == 12: t_end = t_start.replace(year=t_start.year+1, month=1, day=1) - timedelta(days=1)
        else: t_end = t_start.replace(month=t_start.month+1, day=1) - timedelta(days=1)
        
        t_orders = [o for o in all_orders if o.pickup_date and t_start <= o.pickup_date.date() <= t_end]
        t_rev = sum([float(o.price or 0) for o in t_orders])
        
        t_exps = [e for e in all_expenses if t_start <= e.expense_date <= t_end]
        t_exp_total = sum([float(e.amount or 0) for e in t_exps])
        
        rev_vals.append(t_rev)
        exp_vals.append(t_exp_total)
        trend_lbls.append(t_start.strftime('%b'))

    # Build Chart
    drawing = Drawing(450, 180)
    bc = VerticalBarChart()
    bc.x = 50
    bc.y = 40
    bc.height = 110
    bc.width = 350
    bc.data = [rev_vals, exp_vals]
    bc.strokeColor = colors.grey
    bc.valueAxis.valueMin = 0
    max_val = max(rev_vals + exp_vals + [1000])
    bc.valueAxis.valueMax = max_val * 1.2
    bc.valueAxis.valueStep = bc.valueAxis.valueMax / 4
    bc.categoryAxis.labels.boxAnchor = 'ne'
    bc.categoryAxis.labels.dx = 8
    bc.categoryAxis.labels.dy = -2
    bc.categoryAxis.categoryNames = trend_lbls
    bc.bars[0].fillColor = colors.HexColor("#4f46e5") # Revenue
    bc.bars[1].fillColor = colors.HexColor("#ef4444") # Expense
    bc.barWidth = 10
    bc.groupSpacing = 10
    
    # Add simple legend-like text manually to Drawing Since Legend class is complex
    from reportlab.graphics.shapes import String, Rect
    drawing.add(Rect(50, 10, 8, 8, fillColor=colors.HexColor("#4f46e5")))
    drawing.add(String(65, 10, "Gross Revenue", fontSize=8))
    drawing.add(Rect(140, 10, 8, 8, fillColor=colors.HexColor("#ef4444")))
    drawing.add(String(155, 10, "Total Expenses", fontSize=8))
    
    drawing.add(bc)
    elements.append(drawing)
    elements.append(Spacer(1, 15))

    # Ranking Sections
    def get_rankings():
        places = {}
        services = {}
        customers = {}
        techs = {}
        for o in period_orders:
            p = o.place or "Unknown"
            places[p] = places.get(p, 0) + float(o.price or 0)
            c = o.mobile or "N/A"
            if c not in customers: customers[c] = {'name': o.customer_name or "Unknown", 'rev': 0}
            customers[c]['rev'] += float(o.price or 0)
            t = o.technician or "None"
            techs[t] = techs.get(t, 0) + float(o.price or 0)
            for item in o.items:
                if item.services:
                    for s in item.services.split(','):
                        s = s.strip()
                        if s: services[s] = services.get(s, 0) + float(item.price or 0)
        return (sorted(places.items(), key=lambda x:x[1], reverse=True), 
                sorted(services.items(), key=lambda x:x[1], reverse=True),
                sorted(customers.values(), key=lambda x:x['rev'], reverse=True),
                sorted(techs.items(), key=lambda x:x[1], reverse=True))

    # Shared style for mini tables
    mini_style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4f46e5")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
    ])

    r_places, r_svcs, r_custs, r_techs = get_rankings()

    # Two columns for Rank tables
    col1_table = Table([["Top Services", "Revenue"]] + [[s[:20], f"INR {v:,.0f}"] for s,v in r_svcs[:5]], colWidths=[1.8*inch, 0.9*inch])
    col1_table.setStyle(mini_style)
    
    col2_table = Table([["Top Locations", "Revenue"]] + [[p[:20], f"INR {v:,.0f}"] for p,v in r_places[:5]], colWidths=[1.8*inch, 0.9*inch])
    col2_table.setStyle(mini_style)
    
    t_rank = Table([[col1_table, Spacer(0.2*inch, 0), col2_table]])
    t_rank.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    
    elements.append(t_rank)
    elements.append(Spacer(1, 20))

    # Engagement Section
    elements.append(Paragraph("Frequent Customer & Technician Standings", section_style))
    
    col3_table = Table([["Top Customers", "Visits/Spend"]] + [[c['name'][:20], f"INR {c['rev']:,.0f}"] for c in r_custs[:5]], colWidths=[1.8*inch, 0.9*inch])
    col3_table.setStyle(mini_style)
    
    col4_table = Table([["Technician Rankings", "Revenue Share"]] + [[t[:20], f"INR {v:,.0f}"] for t,v in r_techs[:5]], colWidths=[1.8*inch, 0.9*inch])
    col4_table.setStyle(mini_style)

    t_rank2 = Table([[col3_table, Spacer(0.2*inch, 0), col4_table]])
    t_rank2.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elements.append(t_rank2)

    # Order details on next page
    elements.append(PageBreak())
    elements.append(Paragraph("Detailed Order List", section_style))
    detailed_data = [['ID', 'Customer', 'Date', 'Amount', 'Status']]
    for o in period_orders[:50]: # Cap to 50 for performance and clarity
        detailed_data.append([o.id, o.customer_name[:15], o.pickup_date.strftime('%d-%b') if o.pickup_date else '-', f"{float(o.price or 0):,.2f}", o.status])
    
    t_det = Table(detailed_data, colWidths=[0.6*inch, 1.8*inch, 1*inch, 1.2*inch, 1*inch])
    t_det.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
        ('BOX', (0,0), (-1,-1), 0.25, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    elements.append(t_det)
    if len(period_orders) > 50:
        elements.append(Paragraph(f"... and {len(period_orders) - 50} more orders", styles['Italic']))

    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"Advanced_Analytics_{label.replace(' ', '_')}.pdf", mimetype='application/pdf')


@admin_bp.route("/reports")
@login_required
@admin_required
def reports():
    return redirect(url_for('report_daily'))




# Work Assign

@admin_bp.route("/work_assign")
@login_required
@super_admin_required
def work_assign():
    from models import Order, OrderItem, User, ManualTask
    from sqlalchemy import func
    from datetime import datetime
    
    from sqlalchemy import or_
    # Fetch all items and filter in Python to ensure maximum reliability across DB types
    all_items = OrderItem.query.all()
    
    # Clean up orphaned items (items whose order was deleted previously)
    orphans = [item for item in all_items if item.order is None]
    if orphans:
        for o in orphans:
            db.session.delete(o)
        db.session.commit()
        all_items = OrderItem.query.all() # Refresh list

    active_items = [
        item for item in all_items 
        if item.order and (item.status is None or str(item.status).lower() not in ['done', 'completed', 'delivered', 'cancelled', 'ready to deliver', 'ready', 'billed'])
        and (item.order.status is None or str(item.order.status).lower() not in ['cancelled', 'delivered', 'billed', 'ready to deliver', 'ready', 'completed'])
    ]
    
    # Sort by drop date
    active_items.sort(key=lambda x: (x.order.drop_date if x.order and x.order.drop_date else datetime.max))
    
    # Fetch active staff for the availability sidebar and assignment options
    staff = User.query.filter_by(is_active=True).all()
    
    # Detailed Workload
    today = datetime.now().date()
    # Detailed Workload calculation counting individual services (tasks)
    workload = {p.username: {'items': 0, 'tasks': 0} for p in staff}
    
    for item in all_items:
        # Check if item is active (Consistency with active_items filter)
        if not item.order \
           or str(item.status).lower() in ['done', 'completed', 'delivered', 'cancelled', 'ready to deliver', 'ready', 'billed'] \
           or str(item.order.status).lower() in ['cancelled', 'delivered', 'billed', 'ready to deliver', 'ready', 'completed']:
            continue
            
        import json
        try:
            assignments = json.loads(item.service_assignments) if item.service_assignments else {}
            item_techs = set()
            
            # Count individual tasks assigned to staff
            for s_name, tech_name in assignments.items():
                if tech_name and tech_name in workload:
                    workload[tech_name]['tasks'] += 1
                    item_techs.add(tech_name)
            
            # If a Main Lead is assigned, they are involved with the item
            if item.technician and item.technician in workload:
                item_techs.add(item.technician)
                # If they are Main Lead but have no specific tasks assigned yet, 
                # we still count the item involvement.
            
            # Increment item count for everyone involved in this specific item
            for tech_name in item_techs:
                workload[tech_name]['items'] += 1
        except:
            pass

    # Fetch manual tasks
    manual_tasks = ManualTask.query.filter(ManualTask.status.notin_(['done', 'completed'])).all()
    
    # Include manual tasks in workload
    for task in manual_tasks:
        if task.assigned_to and task.assigned_to in workload:
            workload[task.assigned_to]['tasks'] += 1
            workload[task.assigned_to]['items'] += 1

    return render_template("admin/work_assign.html", 
                           items=active_items, 
                           staff=staff, 
                           workload=workload,
                           manual_tasks=manual_tasks,
                           today_date=today)

@admin_bp.route("/add_manual_task", methods=["POST"])
@login_required
@super_admin_required
def add_manual_task():
    try:
        title = request.form.get("title")
        task_type = request.form.get("task_type", "Pickup")
        customer = request.form.get("customer_name")
        mobile = request.form.get("mobile")
        due_date_str = request.form.get("due_date")
        assigned_to = request.form.get("assigned_to")
        description = request.form.get("description")
        
        due_date = None
        if due_date_str:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            
        new_task = ManualTask(
            title=title,
            task_type=task_type,
            customer_name=customer,
            mobile=mobile,
            due_date=due_date,
            assigned_to=assigned_to,
            description=description,
            status='yts'
        )
        db.session.add(new_task)
        db.session.commit()
        flash("Manual task added and assigned successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding manual task: {str(e)}", "danger")
        
    return redirect(url_for('admin.work_assign'))

@admin_bp.route("/delete_manual_task/<int:task_id>", methods=["POST"])
@login_required
@super_admin_required
def delete_manual_task(task_id):
    task = ManualTask.query.get_or_404(task_id)
    try:
        db.session.delete(task)
        db.session.commit()
        flash("Manual task deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting task: {str(e)}", "danger")
    return redirect(url_for('admin.work_assign'))

@admin_bp.route("/assign_task", methods=["POST"])
@login_required
@super_admin_required
def assign_task():
    from models import Order, OrderItem
    import json
    
    order_id = request.form.get("order_id")
    item_id = request.form.get("item_id")
    service_name = request.form.get("service_name")
    technician_name = request.form.get("technician")
    
    try:
        if item_id:
            item = OrderItem.query.get(item_id)
            if item:
                if service_name:
                    assignments = json.loads(item.service_assignments) if item.service_assignments else {}
                    statuses = json.loads(item.service_statuses) if item.service_statuses else {}
                    
                    if not technician_name or technician_name == 'UNASSIGN':
                        # Unassign Logic
                        services_to_clear = [service_name]
                        if service_name.lower() == 'deep clean':
                            services_to_clear.extend(['wash', 're wash', 'packing'])
                        
                        for s in services_to_clear:
                            if s in assignments:
                                del assignments[s]
                            if s in statuses:
                                del statuses[s]
                        flash(f"Service(s) cleared \u2705", "info")
                    else:
                        # Assign Logic
                        services_to_assign = [service_name]
                        if service_name.lower() == 'deep clean':
                            services_to_assign.extend(['wash', 're wash', 'packing'])
                        
                        for s in services_to_assign:
                            assignments[s] = technician_name
                            if s not in statuses:
                                statuses[s] = 'yts'
                        flash(f"Assigned to {technician_name} \u2705", "success")
                        
                    item.service_assignments = json.dumps(assignments)
                    item.service_statuses = json.dumps(statuses)
                    
                    # Set service_date on the order if not already set
                    if item.order and not item.order.service_date:
                        from datetime import datetime
                        item.order.service_date = datetime.now()
                else:
                    # Assign whole item (Main Lead)
                    # We ONLY update the item-level technician now.
                    # We do NOT automatically assign this person to every individual service anymore.
                    item.technician = technician_name
                    flash(f"Main Lead updated to {technician_name} \u2705", "success")
                    
                    # Ensure order service_date is set
                    if item.order and not item.order.service_date:
                        from datetime import datetime
                        item.order.service_date = datetime.now()
                db.session.commit()
        elif order_id:
            order = Order.query.get(order_id)
            if order:
                order.technician = technician_name
                
                # Set service_date if not already set
                if not order.service_date:
                    from datetime import datetime
                    order.service_date = datetime.now()
                
                # Also auto-assign to all items
                for item in order.items:
                    item.technician = technician_name
                    assignments = {}
                    statuses = json.loads(item.service_statuses) if item.service_statuses else {}
                    if item.services:
                        for s in item.services.split(','):
                            name = s.strip()
                            assignments[name] = technician_name
                            if name not in statuses:
                                statuses[name] = 'yts'
                    item.service_assignments = json.dumps(assignments)
                    item.service_statuses = json.dumps(statuses)
                db.session.commit()
                flash(f"Whole Order {order.job_id} assigned to {technician_name} \u2705", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error assigning task: {str(e)}", "danger")
            
    return redirect(url_for("admin.work_assign"))

@admin_bp.route("/assign_task_bundle", methods=["POST"])
@login_required
@super_admin_required
def assign_task_bundle():
    from models import OrderItem
    import json
    
    item_id = request.form.get("item_id")
    technician_name = request.form.get("technician")
    bundle_name = request.form.get("bundle_name")
    
    if not item_id or not technician_name or not bundle_name:
        flash("Missing data for bundle assignment", "danger")
        return redirect(url_for("admin.work_assign"))
        
    try:
        item = OrderItem.query.get(item_id)
        if item:
            current_services = [s.strip() for s in item.services.split(',')] if item.services else []
            assignments = json.loads(item.service_assignments) if item.service_assignments else {}
            statuses = json.loads(item.service_statuses) if item.service_statuses else {}
            
            services_to_add = []
            if bundle_name == 'standard_process':
                 services_to_add = ['deep clean', 'wash', 're wash', 'packing']
            elif bundle_name == 'cleaning_full':
                 services_to_add = ['deep clean', 'wash', 're wash', 'packing']
            
            # 1. Update Services List
            for s in services_to_add:
                if technician_name == 'UNASSIGN':
                    # REMOVE Logic: Remove service from list and assignments
                    # Remove from text list
                    temp_services = []
                    for existing in current_services:
                        if existing.lower() != s.lower():
                            temp_services.append(existing)
                    current_services = temp_services
                    
                    # Remove assignment
                    if s in assignments:
                        del assignments[s]
                    
                    # Remove status (optional, keeps data cleaner)
                    if s in statuses:
                        del statuses[s]

                else:
                    # ADD Logic: Add service if missing, assign tech
                    # Add to text list if not present
                    is_present = False
                    for existing in current_services:
                        if existing.lower() == s.lower():
                            is_present = True
                            break
                    if not is_present:
                        current_services.append(s)
                    
                    # Assign to Tech
                    assignments[s] = technician_name
                    
                    # Init Status
                    if s not in statuses:
                        statuses[s] = 'yts'
            
            item.services = ",".join(current_services)
            item.service_assignments = json.dumps(assignments)
            item.service_statuses = json.dumps(statuses)
            
            # Ensure order service_date is set
            if item.order and not item.order.service_date:
                from datetime import datetime
                item.order.service_date = datetime.now()
            
            db.session.commit()
            
            if technician_name == 'UNASSIGN':
                flash(f"Process unassigned (cleared) \u2705", "info")
            else:
                flash(f"Process assigned to {technician_name} \u2705", "success")
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
        
    return redirect(url_for("admin.work_assign"))

@admin_bp.route("/set_assignment_date", methods=["POST"])
@login_required
@super_admin_required
def set_assignment_date():
    from models import Order
    from datetime import datetime
    
    order_id = request.form.get("order_id")
    assignment_start_date_str = request.form.get("assignment_start_date")
    
    try:
        order = Order.query.get(order_id)
        if order:
            if assignment_start_date_str:
                # Parse the date string to datetime
                assignment_start_date = datetime.strptime(assignment_start_date_str, "%Y-%m-%d")
                order.assignment_start_date = assignment_start_date
                
                # Calculate days until start
                from datetime import date
                today = date.today()
                start_date = assignment_start_date.date()
                days_diff = (start_date - today).days
                
                if days_diff > 0:
                    flash(f"Assignment scheduled to start in {days_diff} day{'s' if days_diff != 1 else ''} Γ£ô", "info")
                elif days_diff == 0:
                    flash(f"Assignment set to start today Γ£ô", "success")
                else:
                    flash(f"Assignment is now active Γ£ô", "success")
            else:
                # Clear the assignment start date
                order.assignment_start_date = None
                flash("Assignment start date cleared - task is now immediately visible Γ£ô", "info")
            
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Error setting assignment date: {str(e)}", "danger")
    
    return redirect(url_for("admin.work_assign"))



def _get_customer_data():
    from models import Order
    from sqlalchemy import func
    
    # Determine if we should group by mobile or name if mobile is missing
    # Since mobile is primary key for customer uniqueness as per request
    
    # We filter out records with no mobile to avoid grouping them all into one 'None' customer
    # If mobile is missing, we might (optionally) fall back to name, but user insisted on mobile.
    
    results = db.session.query(
        func.trim(Order.mobile).label('mobile'),
        func.max(Order.customer_name).label('name'),
        func.max(Order.place).label('place'),
        func.count(Order.id).label('order_count'),
        func.sum(Order.price).label('total_spent'),
        func.max(Order.pickup_date).label('last_visit')
    ).filter(
        Order.mobile.isnot(None), 
        Order.mobile != '',
        Order.mobile != '-'
    ).group_by(func.trim(Order.mobile)).order_by(func.max(Order.pickup_date).desc()).all()
    
    customers = []
    for r in results:
        customers.append({
            'mobile': r.mobile,
            'name': r.name,
            'place': r.place,
            'order_count': r[3],
            'total_spent': r[4] or 0,
            'last_visit': r[5]
        })
    return customers

# Customer Database
@admin_bp.route("/customers")
@login_required
def customer_database():
    # Helper to revoke and redirect
    def revoke_access(msg):
        current_user.can_view_customers = False
        current_user.can_export_customers = False
        current_user.customer_access_expiry = None
        current_user.customer_view_requested = False
        db.session.commit()
        flash(msg, "warning")
        return redirect(url_for('admin.admin_panel'))

    # Permission Check
    if current_user.role != 'super_admin':
        if not current_user.can_view_customers:
            flash("Access to Customer Database is restricted.", "danger")
            return redirect(url_for('admin.admin_panel'))
        
        # Check Expiry
        if current_user.customer_access_expiry:
            if datetime.utcnow() > current_user.customer_access_expiry:
                return revoke_access("Your temporary access to the Customer Database has expired.")
        
    customers = _get_customer_data()
    return render_template("admin/customer_database.html", customers=customers)

    return redirect(url_for("admin.admin_panel"))

@admin_bp.route("/request_customer_access")
@login_required
def request_customer_access():
    if current_user.role == 'super_admin':
        flash("You are Super Admin, you already have access!", "info")
        return redirect(url_for("admin.admin_panel"))
        
    # Check if access is currently active and not expired
    is_active = current_user.can_view_customers
    is_expired = current_user.customer_access_expiry and datetime.utcnow() > current_user.customer_access_expiry
    
    if is_active and not is_expired:
        flash("You already have access to the database.", "info")
    else:
        # Reset everything and set request flag
        current_user.can_view_customers = False
        current_user.can_export_customers = False
        current_user.customer_access_expiry = None
        current_user.customer_view_requested = True
        db.session.commit()
        flash("Access request sent to Super Admin.", "success")
        
    return redirect(url_for("admin.admin_panel"))

@admin_bp.route("/request_performance_access")
@login_required
def request_performance_access():
    if current_user.role == 'super_admin':
        flash("You are Super Admin, you already have access!", "info")
        return redirect(url_for("admin.admin_panel"))
        
    # Check if access is currently active and not expired
    is_active = current_user.can_view_performance
    is_expired = current_user.performance_access_expiry and datetime.utcnow() > current_user.performance_access_expiry
    
    if is_active and not is_expired:
        flash("You already have access to the Performance Monitor.", "info")
    else:
        # Reset everything and set request flag
        current_user.can_view_performance = False
        current_user.performance_access_expiry = None
        current_user.performance_view_requested = True
        db.session.commit()
        
        # Notify Super Admin? (Automated via pending counts)
        flash("Performance Monitor access request sent to Super Admin.", "success")
        
    return redirect(url_for("admin.admin_panel"))


@admin_bp.route("/export_customers_excel")
@login_required
def export_customers_excel():
    # Permission Check
    if current_user.role != 'super_admin' and not current_user.can_export_customers:
        flash("Export access denied.", "danger")
        return redirect(url_for('admin.customer_database'))

    customers = _get_customer_data()
    
    data = []
    for c in customers:
        data.append({
            'Customer Name': c['name'],
            'Mobile': c['mobile'],
            'Place': c['place'] or '-',
            'Total Orders': c['order_count'],
            'Total Spent': c['total_spent'],
            'Last Visit': c['last_visit'].strftime('%d-%b-%Y') if c['last_visit'] else '-'
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Customers')
    output.seek(0)
    
    filename = f"Customer_Database_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@admin_bp.route("/export_customers_pdf")
@login_required
def export_customers_pdf():
    # Permission Check
    if current_user.role != 'super_admin' and not current_user.can_export_customers:
        flash("Export access denied.", "danger")
        return redirect(url_for('admin.customer_database'))

    customers = _get_customer_data()
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    elements.append(Paragraph("Customer Database Report", styles['Title']))
    elements.append(Paragraph(f"Generated on: {datetime.utcnow().strftime('%d-%b-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    data = [['Name', 'Mobile', 'Place', 'Orders', 'Spent', 'Last Visit']]
    
    for c in customers:
        data.append([
            c['name'][:15] if c['name'] else '-',
            c['mobile'],
            c['place'][:10] if c['place'] else '-',
            str(c['order_count']),
            f"{c['total_spent']:.0f}",
            c['last_visit'].strftime('%d-%b') if c['last_visit'] else '-'
        ])
        
    t = Table(data, colWidths=[100, 80, 80, 50, 60, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    
    filename = f"Customer_Database_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

    


@admin_bp.route("/toggle_customer_view/<int:user_id>")
@login_required
@super_admin_required
def toggle_customer_view(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'super_admin':
        flash("Cannot modify permissions for Super Admin.", "warning")
    else:
        user.can_view_customers = not user.can_view_customers
        # Reset request flag if access is granted
        if user.can_view_customers:
            user.customer_view_requested = False
            
        db.session.commit()
        status = "enabled" if user.can_view_customers else "disabled"
        flash(f"Customer View {status} for {user.username}.", "success")
        
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

# Add Expense Form (Action)

@admin_bp.route("/add_expense", methods=["GET", "POST"])
@login_required
@admin_required
def add_expense():
    from datetime import datetime
    
    if request.method == "POST":
        try:
            title = request.form.get("title")
            amount = float(request.form.get("amount") or 0)
            real_amount = float(request.form.get("real_amount") or amount)
            category = request.form.get("category")
            description = request.form.get("description")
            date_str = request.form.get("expense_date")
            expense_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            # Determine status based on role
            status = 'approved' if current_user.role == 'super_admin' else 'pending'
            
            new_expense = Expense(
                title=title,
                amount=amount,
                real_amount=real_amount,
                category=category,
                description=description,
                expense_date=expense_date,
                status=status,
                added_by=current_user.id
            )
            
            db.session.add(new_expense)
            db.session.commit()
            
            if status == 'approved':
                flash("Expense added and approved! \u2705", "success")
            else:
                flash("Expense submitted for Super Admin approval. ΓÅ│", "info")
            
            return redirect(url_for('home')) 
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding expense: {str(e)}", "danger")
    
    today_date = datetime.utcnow().strftime("%Y-%m-%d")
    staff_members = Staff.query.all()
    return render_template("admin/add_expense.html", today_date=today_date, staff_members=staff_members)

@admin_bp.route("/get_staff_balance/<string:name>")
@login_required
@admin_required
def get_staff_balance(name):
    from sqlalchemy import func
    staff = Staff.query.filter(func.lower(Staff.name) == func.lower(name.strip())).first()
    if not staff:
        return jsonify({'error': 'Staff not found'}), 404
        
    # Calculate Total Earned (Lifetime)
    total_earned = 0.0
    
    # 1. Attendance-based earnings
    if staff.user_id:
        atts = Attendance.query.filter_by(user_id=staff.user_id).all()
        for a in atts:
            if staff.salary_type == 'per_day':
                if a.status == 'Present': total_earned += float(staff.base_salary or 0)
                elif a.status == 'Half-Day': total_earned += float(staff.base_salary or 0) * 0.5
            elif staff.salary_type == 'per_hour':
                if a.check_in and a.check_out:
                    h = min((a.check_out - a.check_in).total_seconds() / 3600, 12.0)
                    total_earned += int(h) * float(staff.base_salary or 0)
    
    # 2. Fixed monthly earnings (Count months since created)
    # 2. Monthly earnings (Strictly Attendance Based)
    if staff.salary_type == 'monthly':
        if staff.user_id:
            import calendar
            # Reset earn count to strict attendance if user is linked
            # (Note: This overwrites any per_day calculation above, but per_day/per_hour types enter previous block)
            # Actually, per_day enters block 1, monthly enters block 2. Only "monthly" executes here.
            
            # Efficiently fetch attendance again if needed, or iterate existing 'atts' if we had them
            # The previous block (lines 1386-1396) fetches 'atts' ONLY if salary_type is per_day/per_hour ?
            # No, line 1386 fetches for ALL linked users, but the inner loop only acts on per_day/per_hour.
            # So 'atts' variable IS available here if we move logic or reuse it.
            
            # Let's verify scope. 'atts' is defined inside "if staff.user_id:".
            # We should reuse that logic block structure or fetch again.
            
            # To be safe and clean, let's restructure to use variable 'atts' if available.
            # But since 'atts' scope is inside if, let's just re-query or assume previous block ran.
            # Best to just re-query or check scope. The previous code structure had them separate.
            
            atts = Attendance.query.filter_by(user_id=staff.user_id).all()
            monthly_earned = 0.0
            
            for a in atts:
                # Determine that month's total days
                # a.date is a date object
                _, days_in_month = calendar.monthrange(a.date.year, a.date.month)
                daily_rate = float(staff.base_salary or 0) / days_in_month
                
                if a.status == 'Present':
                    monthly_earned += daily_rate
                elif a.status == 'Half-Day':
                    monthly_earned += (daily_rate * 0.5)
            
            total_earned = monthly_earned
        else:
            # Fallback for Unlinked Accounts: Pro-rata based on days existed
            now = datetime.now().date()
            start = staff.created_at.date()
            days_passed = (now - start).days + 1
            # Average 30 days? Or calculate rough months? 
            # User wants strictness, but unlinked accounts can't be strict.
            # Let'sstick to strict "days existing" pro-rata for unlinked.
            # Daily rate approx = Base / 30.44
            daily_rate = float(staff.base_salary or 0) / 30.44
            total_earned = days_passed * daily_rate

    # 3. Total Paid
    total_paid = db.session.query(func.sum(Expense.real_amount)).filter(
        Expense.category.in_(['Salary', 'Salary Advance']),
        Expense.title.ilike(f"%{staff.name.strip()}%"),
        Expense.status == 'approved'
    ).scalar() or 0.0
    
    balance = max(0, total_earned - float(total_paid))
    return jsonify({
        'balance': balance,
        'earned': total_earned,
        'paid': total_paid,
        'salary_type': staff.salary_type,
        'rate': staff.base_salary
    })

# Day to Day Expense (View)
def _get_filtered_expenses(args):
    from sqlalchemy import extract
    
    filter_type = args.get('filter_type', 'month')
    selected_date_str = args.get('date_{}'.format(filter_type)) or args.get('date')
    selected_category = args.get('category', '')

    query = Expense.query.filter_by(status='approved')
    today = datetime.utcnow().date()
    selected_date = today 
    display_date = today.strftime('%Y-%m')

    if filter_type == 'month':
        if selected_date_str:
            try:
                year, month = map(int, selected_date_str.split('-'))
                query = query.filter(extract('year', Expense.expense_date) == year,
                                     extract('month', Expense.expense_date) == month)
                display_date = selected_date_str
                selected_date = datetime(year, month, 1).date()
            except ValueError:
                selected_date_str = None
        
        if not selected_date_str:
            query = query.filter(extract('year', Expense.expense_date) == today.year,
                                 extract('month', Expense.expense_date) == today.month)
            display_date = today.strftime('%Y-%m')

    elif filter_type == 'date':
        if selected_date_str:
            try:
                selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
                display_date = selected_date.strftime('%Y-%m-%d')
            except ValueError:
                selected_date = today
        else:
            display_date = today.strftime('%Y-%m-%d')
        query = query.filter(Expense.expense_date == selected_date)

    elif filter_type == 'year':
        if selected_date_str:
            try:
                year = int(selected_date_str)
                query = query.filter(extract('year', Expense.expense_date) == year)
                display_date = str(year)
                selected_date = datetime(year, 1, 1).date()
            except ValueError:
                selected_date_str = None
        
        if not selected_date_str:
            year = today.year
            query = query.filter(extract('year', Expense.expense_date) == year)
            display_date = str(year)

    elif filter_type == 'range':
        start_date_str = args.get('start_date')
        end_date_str = args.get('end_date')
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(Expense.expense_date >= start_date, Expense.expense_date <= end_date)
                display_date = f"{start_date_str} to {end_date_str}"
                selected_date = start_date
            except ValueError:
                pass
        else:
            # Fallback to last 7 days if no range provided
            start_date = today - timedelta(days=7)
            query = query.filter(Expense.expense_date >= start_date, Expense.expense_date <= today)
            display_date = f"{start_date} to {today}"

    if selected_category:
        query = query.filter(Expense.category == selected_category)

    expenses = query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    return expenses, filter_type, display_date, selected_date, selected_category

# Day to Day Expense (View)
@admin_bp.route("/day_to_day_expense")
@login_required
@admin_required
def day_to_day_expense():
    expenses, filter_type, display_date, selected_date, selected_category = _get_filtered_expenses(request.args)
    
    total_amount = sum(float(e.real_amount or e.amount or 0) for e in expenses)
    transaction_count = len(expenses)
    
    categories = ["Rent", "Utilities", "Salary", "Salary Advance", "Supplies", "Marketing", "Petrol", "Maintenance", "Electricity", "Other"]

    return render_template("admin/day_to_day_expense.html", 
                         expenses=expenses, 
                         total_amount=total_amount,
                         transaction_count=transaction_count,
                         timedelta=timedelta,
                         datetime=datetime,
                         now=datetime.utcnow(),
                         filter_type=filter_type,
                         display_date=display_date,
                         selected_date=selected_date,
                         selected_category=selected_category,
                         categories=categories)

@admin_bp.route("/export_expenses_excel", methods=["GET", "POST"])
@login_required
@super_admin_required
def export_expenses_excel():
    expenses, filter_type, display_date, _, _ = _get_filtered_expenses(request.values)
    
    data = []
    for e in expenses:
        data.append({
            'Date': e.expense_date.strftime('%d-%b-%Y'),
            'Title': e.title,
            'Category': e.category,
            'Description': e.description or '-',
            'Amount': e.real_amount or e.amount,
            'Added At': e.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Expenses')
        workbook = writer.book
        worksheet = writer.sheets['Expenses']
        
        # Insert Chart if provided
        time_chart = request.form.get('time_chart')
        
        if time_chart:
            header, encoded = time_chart.split(",", 1)
            img_data = base64.b64decode(encoded)
            worksheet.write(2, 7, 'Spending Trend')
            worksheet.insert_image(3, 7, 'time_chart.png', {'image_data': io.BytesIO(img_data), 'x_scale': 0.6, 'y_scale': 0.6})
        
    output.seek(0)
    
    filename = f"Expenses_Report_{display_date}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@admin_bp.route("/export_expenses_pdf", methods=["GET", "POST"])
@login_required
@super_admin_required
def export_expenses_pdf():
    expenses, filter_type, display_date, _, _ = _get_filtered_expenses(request.values)
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    elements.append(Paragraph(f"Expense Report - {display_date}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Table Header
    data = [['Date', 'Title', 'Category', 'Description', 'Amount']]
    
    total = 0
    for e in expenses:
        data.append([
            e.expense_date.strftime('%d-%b-%Y'),
            e.title,
            e.category,
            e.description or '-',
            f"INR {(e.real_amount or e.amount):.2f}"
        ])
        total += (e.real_amount or e.amount)
    
    # Add Total Row
    data.append(['', '', '', 'TOTAL', f"INR {total:.2f}"])
    
    # Create Table
    t = Table(data, colWidths=[80, 120, 80, 150, 70])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(t)
    
    # Add Chart to PDF
    time_chart = request.form.get('time_chart')
    
    if time_chart:
        elements.append(Spacer(1, 24))
        elements.append(Paragraph("Visual Analytics", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        try:
            header, encoded = time_chart.split(",", 1)
            img_data = base64.b64decode(encoded)
            elements.append(Paragraph("Spending Trend", styles['Heading3']))
            elements.append(Image(io.BytesIO(img_data), width=450, height=220))
            elements.append(Spacer(1, 12))
        except: pass

    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    
    output.seek(0)
    filename = f"Expenses_Report_{display_date}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

@admin_bp.route("/expense_chart_data")
@login_required
@admin_required
def expense_chart_data():
    from datetime import datetime
    from sqlalchemy import extract
    
    filter_type = request.args.get('filter_type', 'month')
    date_str = request.args.get('date')
    selected_cat = request.args.get('category', '')
    
    try:
        if date_str:
            ref_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            ref_date = datetime.utcnow().date()
    except ValueError:
        ref_date = datetime.utcnow().date()
        
    query = Expense.query.filter_by(status='approved')
    
    # Apply Time Filter
    if filter_type == 'month':
        query = query.filter(extract('year', Expense.expense_date) == ref_date.year,
                             extract('month', Expense.expense_date) == ref_date.month)
    elif filter_type == 'year':
        query = query.filter(extract('year', Expense.expense_date) == ref_date.year)
    elif filter_type == 'range':
        s_date = request.args.get('start_date')
        e_date = request.args.get('end_date')
        if s_date and e_date:
            try:
                start = datetime.strptime(s_date, '%Y-%m-%d').date()
                end = datetime.strptime(e_date, '%Y-%m-%d').date()
                query = query.filter(Expense.expense_date >= start, Expense.expense_date <= end)
            except ValueError:
                pass

    # Apply Category Filter (Optional) - only for trend line
    trend_query = query
    if selected_cat:
        trend_query = trend_query.filter(Expense.category == selected_cat)

    # Fetch all matching expenses for this period
    all_expenses = query.all()
    trend_expenses = trend_query.all()
    
    # 1. Calculate Summary (from ALL categories in this period)
    # 1. Calculate Summary (from ALL categories in this period)
    total_amount = sum((e.real_amount or e.amount or 0) for e in all_expenses)
    
    cat_summary = {}
    for e in all_expenses:
        val = e.real_amount or e.amount or 0
        cat_summary[e.category] = cat_summary.get(e.category, 0) + val
    
    largest_cat_name = "N/A"
    largest_cat_amount = 0
    if cat_summary:
        largest_cat_name = max(cat_summary, key=cat_summary.get)
        largest_cat_amount = cat_summary[largest_cat_name]

    # 2. Time Trend Data (from TREND query)
    time_groups = {}
    labels = []
    
    if filter_type == 'month':
        for e in trend_expenses:
            day = e.expense_date.day
            val = e.real_amount or e.amount or 0
            time_groups[day] = time_groups.get(day, 0) + val
        labels = sorted(time_groups.keys())
    elif filter_type == 'year':
        for e in trend_expenses:
            month = e.expense_date.month
            val = e.real_amount or e.amount or 0
            time_groups[month] = time_groups.get(month, 0) + val
        labels = sorted(time_groups.keys())
    elif filter_type == 'range':
        s_date = request.args.get('start_date')
        e_date = request.args.get('end_date')
        try:
            start = datetime.strptime(s_date, '%Y-%m-%d').date()
            end = datetime.strptime(e_date, '%Y-%m-%d').date()
            diff = (end - start).days
            
            if diff <= 62: # Up to 2 months, show daily
                for e in trend_expenses:
                    d_key = e.expense_date.strftime('%d %b')
                    val = e.real_amount or e.amount or 0
                    time_groups[d_key] = time_groups.get(d_key, 0) + val
                # Sort by date properly
                labels = sorted(time_groups.keys(), key=lambda x: datetime.strptime(x, '%d %b'))
            else: # Larger range, show monthly
                for e in trend_expenses:
                    m_key = e.expense_date.strftime('%b %Y')
                    val = e.real_amount or e.amount or 0
                    time_groups[m_key] = time_groups.get(m_key, 0) + val
                labels = sorted(time_groups.keys(), key=lambda x: datetime.strptime(x, '%b %Y'))
        except (ValueError, TypeError):
            # Fallback
            for e in trend_expenses:
                day = e.expense_date.day
                val = e.real_amount or e.amount or 0
                time_groups[day] = time_groups.get(day, 0) + val
            labels = sorted(time_groups.keys())

    time_data = [time_groups[l] for l in labels]

    # 3. Category Distribution (from ALL categories in this period)
    cat_labels = list(cat_summary.keys())
    cat_data = [cat_summary[l] for l in cat_labels]
        
    return jsonify({
        'by_category': {
            'labels': cat_labels,
            'data': [float(d) for d in cat_data]
        },
        'by_time': {
            'labels': labels,
            'data': [float(d) for d in time_data]
        },
        'summary': {
            'total': total_amount,
            'top_cat_name': largest_cat_name,
            'top_cat_amount': largest_cat_amount
        }
    })

@admin_bp.route("/financial_report")
@login_required
@admin_required
def financial_report():
    try:
        from app import get_monthly_report_legacy, get_yearly_report_legacy
        from datetime import datetime

        # Get timeframe arguments
        selected_year = request.args.get('year', datetime.now().year, type=int)
        selected_month = request.args.get('month', datetime.now().month, type=int)
        
        monthly_report = get_monthly_report_legacy(selected_year, selected_month)
        yearly_report = get_yearly_report_legacy(selected_year)
        
        if 'error' in monthly_report:
            flash(f"Error generating monthly report: {monthly_report['error']}", "danger")
        if 'error' in yearly_report:
            flash(f"Error generating yearly report: {yearly_report['error']}", "danger")

        # Trend data for chart
        trend_period = request.args.get('trend_period', 6, type=int)
        financial_trend = []
        import calendar
        for i in range(trend_period - 1, -1, -1):
            m = selected_month - i
            y = selected_year
            while m <= 0:
                m += 12
                y -= 1
            try:
                rep = get_monthly_report_legacy(y, m)
                if 'error' not in rep:
                    financial_trend.append({
                        'label': f"{calendar.month_name[m][:3]} {y}",
                        'revenue': float(rep.get('income', 0)),
                        'expense': float(rep.get('total_expenses_actual', 0)),
                        'vendor': float(rep.get('total_vendor_cost', 0))
                    })
            except:
                continue

        return render_template(
            "admin/reports/financial.html", 
            monthly=monthly_report, 
            yearly=yearly_report,
            years=range(2023, datetime.now().year + 2),
            selected_year=selected_year,
            selected_month=selected_month,
            financial_trend=financial_trend,
            trend_period=trend_period
        )
        
    except Exception as e:
        print(f"Error generating financial report: {e}")
        flash(f"Error: {e}", "danger")
        return redirect(url_for('report_daily'))

# Payouts
@admin_bp.route("/payouts")
@login_required
@admin_required
def payouts():
    try:
        from sqlalchemy import extract
        from datetime import datetime
        
        filter_type = request.args.get('filter_type', 'month')
        selected_date_str = request.args.get('date_{}'.format(filter_type)) or request.args.get('date')
        
        query = Expense.query.filter(Expense.category.in_(['Salaries', 'Salary']))
        today = datetime.utcnow().date()
        selected_date = today 
        display_date = today.strftime('%Y-%m')

        if filter_type == 'month':
            if selected_date_str:
                try:
                    year, month = map(int, selected_date_str.split('-'))
                    query = query.filter(extract('year', Expense.expense_date) == year,
                                         extract('month', Expense.expense_date) == month)
                    display_date = selected_date_str
                    selected_date = datetime(year, month, 1).date()
                except ValueError:
                    selected_date_str = None
            
            if not selected_date_str:
                query = query.filter(extract('year', Expense.expense_date) == today.year,
                                     extract('month', Expense.expense_date) == today.month)
                display_date = today.strftime('%Y-%m')

        elif filter_type == 'year':
            if selected_date_str:
                try:
                    year = int(selected_date_str)
                    query = query.filter(extract('year', Expense.expense_date) == year)
                    display_date = str(year)
                    selected_date = datetime(year, 1, 1).date()
                except ValueError:
                    selected_date_str = None
            
            if not selected_date_str:
                year = today.year
                query = query.filter(extract('year', Expense.expense_date) == year)
                display_date = str(year)

        expenses = query.order_by(Expense.expense_date.desc()).all()
        total_payout = sum(float(e.real_amount or e.amount or 0) for e in expenses)
        
        return render_template("admin/payouts.html", 
                             expenses=expenses, 
                             total_payout=total_payout,
                             filter_type=filter_type,
                             display_date=display_date,
                             selected_date=selected_date)
    except Exception as e:
        flash(f"Error loading payouts: {str(e)}", "danger")
        return redirect(url_for('admin.admin_panel'))

# Technician Status
@admin_bp.route("/performance_monitor")
@login_required
@admin_required
def performance_monitor():
    from models import User, OrderItem, db
    # Permission Check
    if current_user.role != 'super_admin':
        if not current_user.can_view_performance:
            flash("Access to Performance Monitor is restricted.", "danger")
            return redirect(url_for('admin.admin_panel'))
        
        # Check Expiry
        if current_user.performance_access_expiry:
            if datetime.utcnow() > current_user.performance_access_expiry:
                current_user.can_view_performance = False
                current_user.performance_access_expiry = None
                current_user.performance_view_requested = False
                db.session.commit()
                flash("Your temporary access to the Performance Monitor has expired.", "warning")
                return redirect(url_for('admin.admin_panel'))
    
    # Logic to calculate performance
    # 1. Total tasks completed by each technician
    # 2. Revenue generated
    # 3. Efficiency (if we have timestamps)
    
    # Get all users with roles that can do work (technician/employee)
    technicians = User.query.filter(User.role.in_(['employee', 'admin', 'super_admin'])).all()
    
    # Filter by date range (default to current month)
    # TODO: Add date picker
    
    perf_data = []
    for tech in technicians:
        # Completed items
        items = OrderItem.query.filter_by(technician=tech.username, status='done').all()
        # Revenue: We might need to handle per-service price if granular
        # For now, let's use the item price
        revenue = sum(item.price or 0 for item in items)
        
        perf_data.append({
            'username': tech.username,
            'role': tech.role,
            'completed_count': len(items),
            'revenue': revenue
        })
        
    return render_template("admin/performance_monitor.html", perf_data=perf_data)

@admin_bp.route("/approve_performance_access/<int:user_id>")
@login_required
@super_admin_required
def approve_performance_access(user_id):
    user = User.query.get_or_404(user_id)
    duration_hours = request.args.get('duration', type=int) 
    
    user.can_view_performance = True
    user.performance_view_requested = False
    
    if duration_hours:
        user.performance_access_expiry = datetime.utcnow() + timedelta(hours=duration_hours)
    else:
        user.performance_access_expiry = None
        
    db.session.commit()
    
    expiry_msg = f"Expires in {duration_hours}h" if duration_hours else "Permanent"
    
    # Create notification
    notif = Notification(
        user_id=user.id,
        title="Performance Monitor Access Granted \ud83d\udcca",
        message=f"Admin has granted you {expiry_msg} access to the Performance Monitor.",
        link=url_for('admin.performance_monitor')
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(f"Access granted to {user.username} ({expiry_msg}).", "success")
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/reject_performance_access/<int:user_id>")
@login_required
@super_admin_required
def reject_performance_access(user_id):
    user = User.query.get_or_404(user_id)
    user.performance_view_requested = False
    
    # Create notification
    notif = Notification(
        user_id=user.id,
        title="Performance Access Rejected \u274c",
        message="Your request for Performance Monitor access was rejected by Super Admin.",
        link=url_for('admin_panel')
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(f"Performance access request for {user.username} rejected.", "info")
    return redirect(url_for('admin.notifications'))

# --- SUPER ADMIN (OWNER) ACTIONS ---

@admin_bp.route("/pending_approvals")
@login_required
@super_admin_required
def pending_approvals():
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/approve_customer_access/<int:user_id>")
@login_required
@super_admin_required
def approve_customer_access(user_id):
    user = User.query.get_or_404(user_id)
    export_perm = request.args.get('export', 'false') == 'true'
    duration_hours = request.args.get('duration', type=int) # If None, it's permanent
    
    user.can_view_customers = True
    user.customer_view_requested = False
    user.can_export_customers = export_perm
    
    if duration_hours:
        user.customer_access_expiry = datetime.utcnow() + timedelta(hours=duration_hours)
    else:
        user.customer_access_expiry = None # Permanent until revoked manually
        
    db.session.commit()
    
    expiry_msg = f"Expires in {duration_hours}h" if duration_hours else "Permanent"
    msg = f"Access granted to {user.username} (Export: {'Yes' if export_perm else 'No'}, {expiry_msg})."
    
    # Create notification
    notif = Notification(
        user_id=user.id,
        title="Database Access Granted \ud83d\uddd2\ufe0f",
        message=f"Admin has granted you {expiry_msg} access to the Customer Database (Export: {'Enabled' if export_perm else 'Disabled'}).",
        link=url_for('admin.customer_database')
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(msg, "success")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/reject_customer_access/<int:user_id>")
@login_required
@super_admin_required
def reject_customer_access(user_id):
    user = User.query.get_or_404(user_id)
    user.customer_view_requested = False
    
    # Create notification
    notif = Notification(
        user_id=user.id,
        title="Database Access Rejected \u274c",
        message="Your request for Customer Database access was rejected by Super Admin.",
        link=url_for('admin_panel')
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(f"Access request for {user.username} rejected.", "info")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/toggle_customer_export/<int:user_id>")
@login_required
@super_admin_required
def toggle_customer_export(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'super_admin':
        flash("Cannot modify Super Admin.", "warning")
    else:
        user.can_export_customers = not user.can_export_customers
        db.session.commit()
        status = "enabled" if user.can_export_customers else "disabled"
        flash(f"Customer Export {status} for {user.username}.", "success")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/approve_user/<int:user_id>")
@login_required
@super_admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    
    # Create notification
    notif = Notification(
        user_id=user.id,
        title="Account Approved \u2705",
        message="Your account has been approved by Super Admin. You can now use all features.",
        link=url_for('home')
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(f"User {user.username} approved successfully! \u2705", "success")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/reject_user/<int:user_id>")
@login_required
@super_admin_required
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    username = user.username
    # We delete rejected users as they don't have active accounts anyway
    # But if we want them to see a notification, we can't delete yet.
    # For now, let's just delete to keep DB clean, or just keep them inactive.
    # Handle Foreign Key Constraints before deletion
    from models import Staff, LoginAttempt
    Staff.query.filter_by(user_id=user.id).update({Staff.user_id: None})
    LoginAttempt.query.filter_by(user_id=user.id).delete()
    
    db.session.delete(user)
    db.session.commit()
    flash(f"User {username} registration rejected and removed.", "warning")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/approve_expense/<int:expense_id>")
@login_required
@super_admin_required
def approve_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    expense.status = 'approved'
    
    # Create notification
    if expense.added_by:
        notif = Notification(
            user_id=expense.added_by,
            title="Expense Approved \u2705",
            message=f"Your expense '{expense.title}' for Γé╣{expense.amount:,.2f} has been approved.",
            link=url_for('admin.day_to_day_expense')
        )
        db.session.add(notif)
        
    db.session.commit()
    flash(f"Expense '{expense.title}' approved and reflected in reports! \u2705", "success")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/reject_expense/<int:expense_id>")
@login_required
@super_admin_required
def reject_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    title = expense.title
    amount = expense.amount
    recipient_id = expense.added_by
    
    db.session.delete(expense)
    
    # Create notification
    if recipient_id:
        notif = Notification(
            user_id=recipient_id,
            title="Expense Rejected \u274c",
            message=f"Your expense '{title}' for Γé╣{amount:,.2f} has been rejected and removed.",
            link=url_for('admin.day_to_day_expense')
        )
        db.session.add(notif)
        
    db.session.commit()
    flash(f"Expense rejected and deleted. \u274c", "warning")
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/request_delete_expense/<int:expense_id>", methods=["POST"])
@login_required
def request_delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    reason = request.form.get('reason')
    
    if current_user.role == 'super_admin':
        # Direct Delete
        db.session.delete(expense)
        db.session.commit()
        flash("Expense deleted successfully.", "success")
    else:
        # Check 24 hour limit
        if expense.created_at and (datetime.utcnow() - expense.created_at) > timedelta(hours=24):
            flash("Modification request failed: Original entry is more than 24 hours old.", "danger")
            return redirect(url_for('admin.day_to_day_expense'))
            
        # Request Delete
        expense.request_type = 'delete'
        expense.request_reason = reason
        db.session.commit()
        flash("Deletion request submitted to Super Admin.", "info")
    
    return redirect(url_for('admin.day_to_day_expense'))

@admin_bp.route("/request_edit_expense/<int:expense_id>", methods=["POST"])
@login_required
def request_edit_expense(expense_id):
    import json
    from datetime import datetime
    expense = Expense.query.get_or_404(expense_id)
    
    # Get form data
    title = request.form.get("title")
    amount = request.form.get("amount")
    real_amount = request.form.get("real_amount")
    category = request.form.get("category")
    expense_date_str = request.form.get("expense_date")
    description = request.form.get("description")
    reason = request.form.get("reason")
    
    if not category:
        flash("Registration failed: Category is required.", "danger")
        return redirect(url_for('admin.day_to_day_expense'))

    if current_user.role == 'super_admin':
        # Direct Edit
        expense.title = title
        expense.amount = float(amount or 0)
        expense.real_amount = float(real_amount or amount or 0)
        expense.category = category
        expense.expense_date = datetime.strptime(expense_date_str, "%Y-%m-%d").date()
        expense.description = description
        db.session.commit()
        flash("Expense updated successfully.", "success")
    else:
        # Check 24 hour limit
        if expense.created_at and (datetime.utcnow() - expense.created_at) > timedelta(hours=24):
            flash("Modification request failed: Original entry is more than 24 hours old.", "danger")
            return redirect(url_for('admin.day_to_day_expense'))
            
        # Request Edit
        proposed_changes = {
            'title': title,
            'amount': amount,
            'real_amount': real_amount or amount,
            'category': category,
            'expense_date': expense_date_str,
            'description': description
        }
        expense.request_type = 'edit'
        expense.request_reason = reason
        expense.request_data = json.dumps(proposed_changes)
        db.session.commit()
        flash("Edit request submitted for approval.", "info")
        
    return redirect(url_for('admin.day_to_day_expense'))

@admin_bp.route("/process_expense_request/<int:expense_id>/<action>")
@login_required
@super_admin_required
def process_expense_request(expense_id, action):
    # action: approve or reject
    import json
    from datetime import datetime
    expense = Expense.query.get_or_404(expense_id)
    recipient_id = expense.added_by
    req_type = expense.request_type
    
    if action == 'reject':
        # Store title before clearing record if necessary, but here we keep the record
        expense.request_type = 'none'
        expense.request_reason = None
        expense.request_data = None
        flash("Request rejected.", "info")
        
        # Create notification
        if recipient_id:
            notif = Notification(
                user_id=recipient_id,
                title="Expense Request Rejected \u274c",
                message=f"Your request to {req_type} expense '{expense.title}' was rejected by Super Admin.",
                link=url_for('admin.day_to_day_expense')
            )
            db.session.add(notif)
        
    elif action == 'approve':
        if req_type == 'delete':
            title_deleted = expense.title
            db.session.delete(expense)
            flash("Expense deletion approved.", "success")
            # Create notification
            if recipient_id:
                notif = Notification(
                    user_id=recipient_id,
                    title="Expense Deletion Approved \u2705",
                    message=f"Your request to delete expense '{title_deleted}' was approved.",
                    link=url_for('admin.day_to_day_expense')
                )
                db.session.add(notif)
        elif req_type == 'edit':
            if expense.request_data:
                data = json.loads(expense.request_data)
                expense.title = data['title']
                expense.amount = float(data['amount'])
                expense.real_amount = float(data.get('real_amount') or data['amount'])
                expense.category = data['category']
                expense.expense_date = datetime.strptime(data['expense_date'], "%Y-%m-%d").date()
                expense.description = data['description']
                
                # Clear request
                expense.request_type = 'none'
                expense.request_reason = None
                expense.request_data = None
                flash("Expense edit approved and applied.", "success")
                
                # Create notification
                if recipient_id:
                    notif = Notification(
                        user_id=recipient_id,
                        title="Expense Edit Approved \u2705",
                        message=f"Your request to edit expense '{expense.title}' was approved.",
                        link=url_for('admin.day_to_day_expense')
                    )
                    db.session.add(notif)
    
    db.session.commit()
    if 'manage_users' in (request.referrer or ''):
        return redirect(url_for('admin.manage_users'))
    return redirect(url_for('admin.notifications'))

@admin_bp.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    pending_leaves = []
    pending_users = []
    pending_expenses = []
    access_requests = []
    performance_requests = []
    expense_requests = []
    active_access_users = []
    active_performance_users = []

    if current_user.role == 'super_admin':
        pending_leaves = Attendance.query.filter_by(status='Leave Pending').all()
        pending_users = User.query.filter_by(is_active=False).all()
        pending_expenses = Expense.query.filter_by(status='pending').all()
        access_requests = User.query.filter_by(customer_view_requested=True).all()
        performance_requests = User.query.filter_by(performance_view_requested=True).all()
        expense_requests = Expense.query.filter(Expense.request_type != 'none').all()
        # Fetch users with active access (excluding super admin)
        active_access_users = User.query.filter(User.can_view_customers == True, User.role != 'super_admin').all()
        active_performance_users = User.query.filter(User.can_view_performance == True, User.role != 'super_admin').all()
        
    return render_template("admin/notifications.html", 
                         notifications=notifs, 
                         pending_leaves=pending_leaves,
                         pending_users=pending_users,
                         pending_expenses=pending_expenses,
                         access_requests=access_requests,
                         performance_requests=performance_requests,
                         expense_requests=expense_requests,
                         active_access_users=active_access_users,
                         active_performance_users=active_performance_users)

@admin_bp.route("/mark_notification_read/<int:notif_id>")
@login_required
def mark_notification_read(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    return redirect(request.referrer or url_for('admin.notifications'))

@admin_bp.route("/clear_all_notifications")
@login_required
def clear_all_notifications():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({Notification.is_read: True})
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for('admin.notifications'))


@admin_bp.route("/staff_ledger/<int:id>")
@login_required
@admin_required
def staff_ledger(id):
    staff = Staff.query.get_or_404(id)
    
    # Get all attendance records
    atts = []
    if staff.user_id:
        atts = Attendance.query.filter_by(user_id=staff.user_id).order_by(Attendance.date.desc()).all()
    
    # Get all salary payments/advances
    payments = Expense.query.filter(
        Expense.category.in_(['Salary', 'Salary Advance']),
        Expense.title.ilike(f"%{staff.name.strip()}%"),
        Expense.status == 'approved'
    ).order_by(Expense.expense_date.desc()).all()

    # Calculate Total Earned (Total Lifetime)
    total_earned = 0.0
    for a in atts:
        if staff.salary_type == 'per_day':
            if a.status == 'Present': total_earned += float(staff.base_salary or 0)
            elif a.status == 'Half-Day': total_earned += float(staff.base_salary or 0) * 0.5
        elif staff.salary_type == 'per_hour':
            if a.check_in and a.check_out:
                h = min((a.check_out - a.check_in).total_seconds() / 3600, 12.0)
                total_earned += int(h) * float(staff.base_salary or 0)
    
    if staff.salary_type == 'monthly':
        now = datetime.now().date()
        months = (now.year - staff.created_at.year) * 12 + now.month - staff.created_at.month + 1
        total_earned = months * float(staff.base_salary or 0)

    total_paid = sum([float(p.real_amount or p.amount or 0) for p in payments])
    
    return render_template("admin/staff_ledger.html", 
                           staff=staff, 
                           atts=atts, 
                           payments=payments,
                           total_earned=total_earned,
                           total_paid=total_paid,
                           balance=total_earned - total_paid)

# --- Cash Management & Manual Payment Routes ---

@admin_bp.route("/cash_management")
@login_required
@admin_required
def cash_management():
    from models import Order, CashDeposit, User
    from sqlalchemy import func
    from datetime import datetime
    
    # Calculate Total Cash Collected (Payment Mode = Cash, Payment Status = Paid)
    # Note: Case-insensitive check for robustness
    cash_orders = Order.query.filter(
        func.lower(Order.payment_status) == 'paid',
        func.lower(Order.payment_mode) == 'cash'
    ).all()
    total_collected = sum([float(o.price or 0) for o in cash_orders])
    
    # Total Deposited
    deposits = CashDeposit.query.order_by(CashDeposit.deposit_date.desc()).all()
    total_deposited = sum([d.amount for d in deposits])
    
    cash_in_hand = total_collected - total_deposited
    
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template("admin/cash_management.html",
                           total_collected=total_collected,
                           total_deposited=total_deposited,
                           cash_in_hand=cash_in_hand,
                           deposits=deposits,
                           today_date=today_date)

@admin_bp.route("/add_cash_deposit", methods=['POST'])
@login_required
@admin_required
def add_cash_deposit():
    from models import CashDeposit
    from datetime import datetime
    try:
        amount = float(request.form.get('amount'))
        date_str = request.form.get('deposit_date')
        reference = request.form.get('reference')
        notes = request.form.get('notes')
        
        deposit_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        new_deposit = CashDeposit(
            amount=amount,
            deposit_date=deposit_date,
            reference=reference,
            notes=notes,
            added_by=current_user.id
        )
        db.session.add(new_deposit)
        db.session.commit()
        flash("Cash deposit recorded successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error recording deposit: {str(e)}", "danger")
        
    return redirect(url_for('admin.cash_management'))

@admin_bp.route("/mark_order_paid_manual", methods=['POST'])
@login_required
def mark_order_paid_manual():
    from models import Order
    
    order_id = request.form.get('order_id')
    amount = request.form.get('amount')
    mode = request.form.get('payment_mode')
    note = request.form.get('note') # Currently unused in DB but could be added later
    
    try:
        order = Order.query.get(order_id)
        if order:
            order.payment_status = 'Paid'
            order.payment_mode = mode
            # Could update price if different, but usually stick to order price
            
            db.session.commit()
            flash(f"Order {order.job_id} marked as PAID via {mode}", "success")
        else:
             flash("Order not found", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating order: {str(e)}", "danger")
        
    # specific redirection based on role or referrer could be better
    return redirect(url_for('tsc_dashboard'))


@admin_bp.route("/vendor_management")
@login_required
@admin_required
def vendor_management():
    # --- VENDOR TRACKING ---
    vendor_active = []
    vendor_history = []
    total_vendor_paid = 0.0
    
    # Find all items where any task is assigned to "VENDOR"
    v_search = '%"VENDOR"%'
    all_vendor_items = OrderItem.query.filter(
        (OrderItem.technician == 'VENDOR') | 
        (OrderItem.service_assignments.ilike(v_search))
    ).order_by(OrderItem.created_at.desc()).all()
    
    processed_orders = set()
    for v_item in all_vendor_items:
        if not v_item.order: continue
        
        # Extract only vendor tasks
        try:
            v_assigns = json.loads(v_item.service_assignments or '{}')
            v_stats = json.loads(v_item.service_statuses or '{}')
        except:
            v_assigns = {}
            v_stats = {}
        
        # Tasks assigned to VENDOR
        v_tasks = []
        core_v = [s.strip() for s in (v_item.services or '').split(',')] if v_item.services else []
        for s_name in core_v:
            if v_assigns.get(s_name) == 'VENDOR' or (not v_assigns.get(s_name) and v_item.technician == 'VENDOR'):
                v_tasks.append({'name': s_name, 'status': v_stats.get(s_name, 'yts')})
        
        for t_name, t_user in v_assigns.items():
            if t_user == 'VENDOR' and t_name not in core_v:
                v_tasks.append({'name': t_name, 'status': v_stats.get(t_name, 'yts')})
        
        if v_tasks:
            entry = {
                'item': v_item,
                'tasks': v_tasks,
                'vendor_amount': v_item.order.vendor_amount or 0.0
            }
            # If all vendor tasks are done, it's history
            is_v_done = all(t['status'].lower() in ['done', 'ready to deliver', 'billed'] for t in v_tasks)
            if is_v_done:
                vendor_history.append(entry)
                if v_item.order.id not in processed_orders:
                    total_vendor_paid += (v_item.order.vendor_amount or 0.0)
                    processed_orders.add(v_item.order.id)
            else:
                vendor_active.append(entry)
                
    return render_template("admin/vendor_management.html", 
                           vendor_active=vendor_active, 
                           vendor_history=vendor_history, 
                           total_vendor_paid=total_vendor_paid)

@admin_bp.route("/edit_manual_task/<int:task_id>", methods=["POST"])
@login_required
@super_admin_required
def edit_manual_task(task_id):
    from models import ManualTask
    task = ManualTask.query.get_or_404(task_id)
    try:
        task.title = request.form.get("title")
        task.task_type = request.form.get("task_type")
        task.customer_name = request.form.get("customer_name")
        task.mobile = request.form.get("mobile")
        
        due_date_str = request.form.get("due_date")
        if due_date_str:
            task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            
        task.assigned_to = request.form.get("assigned_to")
        task.description = request.form.get("description")
        
        db.session.commit()
        flash("Manual task updated successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating manual task: {str(e)}", "danger")
        
    return redirect(url_for('admin.work_assign'))

@admin_bp.route("/emergency_db_fix")
@login_required
@super_admin_required
def emergency_db_fix():
    from sqlalchemy import text, inspect
    logs = []
    def log(msg):
        logs.append(str(msg))
    try:
        engine = db.engine
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        with engine.begin() as conn:
            log("--- Starting Schema Repair ---")
            
            # --- USER ---
            u_cols = [c['name'] for c in inspector.get_columns('user')]
            if 'first_login_seen' not in u_cols:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN first_login_seen BOOLEAN DEFAULT FALSE'))
                log("Added user.first_login_seen")

            # --- ORDER ---
            o_cols = [c['name'] for c in inspector.get_columns('order')]
            if 'vendor_amount' not in o_cols:
                conn.execute(text('ALTER TABLE "order" ADD COLUMN vendor_amount FLOAT'))
                log("Added order.vendor_amount")

            # --- EXPENSE ---
            e_cols = [c['name'] for c in inspector.get_columns('expense')]
            if 'request_type' not in e_cols:
                conn.execute(text("ALTER TABLE expense ADD COLUMN request_type VARCHAR(20) DEFAULT 'none'"))
            if 'request_reason' not in e_cols:
                conn.execute(text("ALTER TABLE expense ADD COLUMN request_reason VARCHAR(255)"))
            if 'request_data' not in e_cols:
                conn.execute(text("ALTER TABLE expense ADD COLUMN request_data TEXT"))
            log("Ensured expense request columns")

            # --- MANUAL TASK (Table or Columns) ---
            if 'manual_task' not in tables:
                log("Creating manual_task table...")
                conn.execute(text("""
                    CREATE TABLE manual_task (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(100) NOT NULL,
                        description TEXT,
                        assigned_to VARCHAR(100),
                        status VARCHAR(20) DEFAULT 'yts',
                        due_date TIMESTAMP,
                        task_type VARCHAR(50) DEFAULT 'Pickup',
                        customer_name VARCHAR(100),
                        mobile VARCHAR(20),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """))
            else:
                m_cols = [c['name'] for c in inspector.get_columns('manual_task')]
                # List of all expected columns and their types
                expected = {
                    'description': 'TEXT',
                    'assigned_to': 'VARCHAR(100)',
                    'status': "VARCHAR(20) DEFAULT 'yts'",
                    'due_date': 'TIMESTAMP',
                    'task_type': "VARCHAR(50) DEFAULT 'Pickup'",
                    'customer_name': 'VARCHAR(100)',
                    'mobile': 'VARCHAR(20)',
                    'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                    'completed_at': 'TIMESTAMP'
                }
                for col, col_type in expected.items():
                    if col not in m_cols:
                        conn.execute(text(f'ALTER TABLE manual_task ADD COLUMN {col} {col_type}'))
                        log(f"Added manual_task.{col}")

            # --- CASH DEPOSIT ---
            if 'cash_deposit' not in tables:
                log("Creating cash_deposit table...")
                conn.execute(text("""
                    CREATE TABLE cash_deposit (
                        id SERIAL PRIMARY KEY,
                        amount FLOAT NOT NULL,
                        deposit_date DATE NOT NULL,
                        reference VARCHAR(100),
                        notes VARCHAR(255),
                        added_by INTEGER REFERENCES "user"(id),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        request_type VARCHAR(20) DEFAULT 'none',
                        request_reason VARCHAR(255),
                        request_data TEXT
                    )
                """))
            else:
                # Add request columns if missing
                c_cols = [c['name'] for c in inspector.get_columns('cash_deposit')]
                if 'request_type' not in c_cols:
                    conn.execute(text("ALTER TABLE cash_deposit ADD COLUMN request_type VARCHAR(20) DEFAULT 'none'"))
                    conn.execute(text("ALTER TABLE cash_deposit ADD COLUMN request_reason VARCHAR(255)"))
                    conn.execute(text("ALTER TABLE cash_deposit ADD COLUMN request_data TEXT"))

            log("--- COMPLETE ---")
    except Exception as e:
        log(f"ERROR: {str(e)}")
    return "<br>".join(logs)
