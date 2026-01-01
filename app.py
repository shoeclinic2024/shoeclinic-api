from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, session, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
import razorpay
import json
from datetime import datetime, timedelta
from database import db
from admin import admin_bp
from flask_migrate import Migrate

import os
import io
import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import calendar as py_calendar

# --- Flask App ---
app = Flask(__name__)
app.secret_key = "supersecretkey"
# --- Version Information ---
APP_VERSION = "v02"
VERSION_DATE = "2025-12-22"
VERSION_STATUS = "development"

def mask_ip(ip):
    """Mask the middle parts of an IP address for privacy"""
    if not ip or ip == "Unknown":
        return "Unknown"
    parts = ip.split('.')
    if len(parts) == 4:
        # Mask middle octets for IPv4: 122.***.***.45
        return f"{parts[0]}.***.***.{parts[3]}"
    parts = ip.split(':')
    if len(parts) > 1:
        # Mask middle parts for IPv6
        return f"{parts[0]}:****:****:{parts[-1]}"
    return "Masked"

app.jinja_env.filters['mask_ip'] = mask_ip


# --- Database Config ---
import os
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///shoeclinic.db")
# Fix for Render/Heroku postgres:// URLs
if app.config["SQLALCHEMY_DATABASE_URI"] and app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}} if "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"] else {}
db.init_app(app)
bcrypt = Bcrypt(app)

# --- Import Models (after db initialization) ---
from models import User, Order, OrderItem, Announcement, Attendance, Holiday, Expense, LoginAttempt, Notification

# --- Flask-Migrate ---
migrate = Migrate(app, db)

# --- Login Manager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login_page"

# --- Register Blueprints ---
app.register_blueprint(admin_bp, url_prefix="/admin")

# --- Global alias for admin panel endpoint ---
@app.route("/admin/panel", endpoint="admin_panel")
@login_required
def admin_panel_alias():
    return redirect(url_for("admin.admin_panel"))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Custom Jinja2 Filters ---
@app.template_filter('format_date')
def format_date(value, format="%d-%m-%Y"):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(format)

@app.template_filter('status_color')
def status_color(status):
    if not status:
        return "secondary"
    s = str(status).lower()
    if s in ["pending", "in progress", "wip", "started", "yts"]:
        return "warning"
    elif s in ["done", "completed", "finished", "billed"]:
        return "success"
    elif s in ["cancelled", "rejected", "failed"]:
        return "danger"
    elif s in ["pack pend", "ready to deliver", "re wash"]:
        return "info"
    else:
        return "secondary"

@app.template_filter('from_json')
def from_json_filter(value):
    import json
    try:
        return json.loads(value or '{}')
    except:
        return {}

# --- Database Initialization Route ---
@app.route('/init-db')
def init_db():
    """Initialize database tables (run once on first deployment)"""
    try:
        # Use Flask-Migrate to create tables properly
        from flask_migrate import upgrade
        with app.app_context():
            # First, create all tables
            db.create_all()
            # Then run any pending migrations
            try:
                upgrade()
            except:
                pass  # Migrations might not exist yet
        return "✅ Database tables created successfully! You can now use the application."
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"❌ Error creating tables:<br><pre>{error_details}</pre>", 500

from functools import wraps

@app.context_processor
def inject_pending_counts():
    if current_user.is_authenticated and current_user.role == 'super_admin':
        pending_users = User.query.filter_by(is_active=False).count()
        pending_expenses = Expense.query.filter_by(status='pending').count()
        pending_customer_access = User.query.filter_by(customer_view_requested=True).count()
        pending_performance_access = User.query.filter_by(performance_view_requested=True).count()
        pending_attendance = Attendance.query.filter(
            db.or_(Attendance.reg_requested == True, Attendance.status == 'Leave Pending')
        ).count()
        # Modification requests (Edit/Delete) on approved expenses
        modification_requests = Expense.query.filter(Expense.request_type != 'none').count()
        
        return dict(pending_approvals_count=pending_users + pending_expenses + pending_customer_access + pending_performance_access + pending_attendance + modification_requests)
    return dict(pending_approvals_count=0)

@app.template_filter('ist')
def ist_filter(dt):
    """Convert UTC datetime to IST for display"""
    if not dt:
        return ""
    from datetime import timedelta
    # Basic conversion: UTC + 5:30
    return dt + timedelta(hours=5, minutes=30)

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        # Standard Notifications
        unread_db_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        unread_notifs = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(5).all()
        
        # System Actions (Pending Approvals) - Only for Super Admin
        action_count = 0
        if current_user.role == 'super_admin':
            p_users = User.query.filter_by(is_active=False).count()
            p_expenses = Expense.query.filter_by(status='pending').count()
            p_customer_access = User.query.filter_by(customer_view_requested=True).count()
            p_performance_access = User.query.filter_by(performance_view_requested=True).count()
            # Only count LEAVE requests here for notifications page, regularization is still in attendance? 
            # User said "pending approvals tab is not needed... all request when rise it should show in notification page"
            # So we count everything.
            p_attendance = Attendance.query.filter(
                db.or_(Attendance.reg_requested == True, Attendance.status == 'Leave Pending')
            ).count()
            p_mod_req = Expense.query.filter(Expense.request_type != 'none').count()
            
            action_count = p_users + p_expenses + p_customer_access + p_performance_access + p_attendance + p_mod_req

        return dict(
            unread_notifications=unread_notifs, 
            unread_count=unread_db_count + action_count,
            pending_action_count=action_count # Expose this separately if needed for logic
        )
    return dict(unread_notifications=[], unread_count=0, pending_action_count=0)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin', 'super_admin']:
            from flask import flash, redirect, url_for
            flash("Access denied. Authorized personnel only.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            from flask import flash, redirect, url_for
            flash("Access denied. Super Admin privileges required.", "danger")
            return redirect(request.referrer or url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- Report Helper Functions ---
import json

def calculate_ops_metrics(start_date, end_date, orders=None):
    """Calculate operational metrics for a given date range or order list"""
    try:
        from models import Order, OrderItem, Attendance, db
        from datetime import datetime, date
        
        # 1. Workers Worked
        start = start_date if isinstance(start_date, (datetime, date)) else datetime.strptime(str(start_date), '%Y-%m-%d').date()
        end = end_date if isinstance(end_date, (datetime, date)) else datetime.strptime(str(end_date), '%Y-%m-%d').date()
        
        if isinstance(start, datetime): start = start.date()
        if isinstance(end, datetime): end = end.date()

        workers_count = db.session.query(db.func.count(db.distinct(Attendance.user_id))).filter(
            Attendance.date >= start,
            Attendance.date <= end,
            db.or_(
                Attendance.check_in != None,
                Attendance.status.in_(['Present', 'Half-Day'])
            )
        ).scalar()
        
        # 2. Ops based on Orders
        # If orders list passed explicitly, use it (e.g. for Daily Report filtered by drop_date)
        if orders is None:
            orders = Order.query.filter(db.func.date(Order.drop_date) >= start, db.func.date(Order.drop_date) <= end).all()
            
        order_ids = [o.id for o in orders]
        
        # Order Counts
        # Update: Delivered should include 'billed', 'delivered', 'completed'
        delivered_count = len([o for o in orders if o.status and o.status.lower() in ['billed', 'delivered', 'completed']])
        ready_count = len([o for o in orders if o.status and 'ready' in o.status.lower()])
        expected_delivery_count = len(orders) 
        
        # Item/Task Counts (Granular Status)
        g_yts = 0
        g_wip = 0
        g_done = 0
        g_ready = 0
        g_billed = 0
        
        if orders:
            for order in orders:
                # Force Billed status if Order is finalized
                is_order_billed = (order.status or '').lower() in ['billed', 'delivered', 'completed']
                
                for item in order.items:
                    svc_list = []
                    if item.services:
                        svc_list = [s.strip() for s in item.services.split(',') if s.strip()]
                    
                    if not svc_list:
                        # Treat item as single task
                        if is_order_billed:
                            g_billed += 1
                        else:
                            st = (item.status or 'yts').lower()
                            if st in ['done', 'completed']: g_done += 1
                            elif st in ['billed', 'delivered']: g_billed += 1
                            elif st in ['ready', 'ready to deliver']: g_ready += 1
                            elif st in ['wip', 'work in progress']: g_wip += 1
                            else: g_yts += 1
                    else:
                        # Granular Services
                        try: statuses = json.loads(item.service_statuses or '{}')
                        except: statuses = {}
                        
                        for svc in svc_list:
                            if is_order_billed:
                                g_billed += 1
                            else:
                                # Default to item status if specific service stat not found
                                # This ensures if Item is 'WIP', 'Ready', or 'Done', we don't count it as 'YTS'
                                item_stat_default = (item.status or 'yts').lower()
                                s_stat = statuses.get(svc, item_stat_default).lower()
                                     
                                if s_stat in ['done', 'completed']: g_done += 1
                                elif s_stat in ['billed', 'delivered']: g_billed += 1
                                elif s_stat in ['ready', 'ready to deliver']: g_ready += 1 
                                elif s_stat in ['wip', 'work in progress']: g_wip += 1
                                else: g_yts += 1

        total_granular_tasks = g_yts + g_wip + g_done + g_ready + g_billed
        
        return {
            'workers_worked': workers_count or 0,
            'target_assigned': total_granular_tasks,
            'yts_count': g_yts,
            'wip_count': g_wip,
            'done_count': g_done,
            'ready_count': g_ready, 
            'billed_granular_count': g_billed, # New distinct granular count
            'delivered_count': delivered_count, # Order level count
            'expected_delivery_count': expected_delivery_count
        }
    except Exception as e:
        print(f"Error calculating ops metrics: {e}")
        return {
            'workers_worked': 0, 'target_assigned': 0, 'yts_count': 0, 
            'wip_count': 0, 'done_count': 0, 'ready_count': 0, 
            'billed_granular_count': 0,
            'delivered_count': 0, 'expected_delivery_count': 0
        }

def calculate_tech_performance(orders):
    """Claculate technician efficiency based on list of orders"""
    tech_performance = {}
    try:
        for order in orders:
            for item in order.items:
                # 1. Check Granular Service Assignments first
                has_granular = False
                if item.service_assignments:
                    try:
                        assignments = json.loads(item.service_assignments)
                        statuses = json.loads(item.service_statuses or '{}')
                        for svc_name, tech_name in assignments.items():
                            if tech_name:
                                has_granular = True
                                if tech_name not in tech_performance:
                                    tech_performance[tech_name] = {'assigned': 0, 'completed': 0}
                                tech_performance[tech_name]['assigned'] += 1
                                
                                # Check status of this specific service
                                s_status = statuses.get(svc_name, 'yts').lower()
                                if s_status in ['done', 'completed', 'ready to deliver']:
                                    tech_performance[tech_name]['completed'] += 1
                    except:
                        pass # Valid JSON check failed
                
                # 2. Fallback to Item Level Technician if no granular services assigned
                if not has_granular and item.technician:
                    t_name = item.technician
                    if t_name not in tech_performance:
                        tech_performance[t_name] = {'assigned': 0, 'completed': 0}
                    tech_performance[t_name]['assigned'] += 1
                    
                    if item.status and item.status.lower() in ['done', 'completed', 'ready to deliver']:
                        tech_performance[t_name]['completed'] += 1
    except Exception as e:
        print(f"Error calculating tech performance: {e}")
    return tech_performance

def get_daily_report(date=None):
    """Get report for a specific date"""
    try:
        if date is None:
            date = datetime.now().date()
        
        start_of_day = datetime.combine(date, datetime.min.time())
        end_of_day = datetime.combine(date, datetime.max.time())

        # Revenue from Orders (Delivery View)
        orders = Order.query.filter(Order.drop_date >= start_of_day, Order.drop_date <= end_of_day).all()
        
        # Only counting APPROVED expenses (Direct filter in SQL)
        expenses = Expense.query.filter(Expense.status == 'approved', Expense.expense_date == date).all()
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        
        # Calculate Billed Revenue from Sales View (Orders TAKEN today that are billed)
        sales_orders = Order.query.filter(Order.pickup_date >= start_of_day, Order.pickup_date <= end_of_day).all()
        billed_orders = [o for o in sales_orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'received', 'settled']) or (o.status and o.status.lower() in ['billed', 'delivered', 'completed'])]
        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_revenue = sum([float(o.price or 0) for o in paid_orders])
        billed_revenue = sum([float(o.price or 0) for o in billed_orders])
        
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        completed = Order.query.filter(Order.drop_date >= start_of_day, Order.drop_date <= end_of_day, Order.status.ilike('%done%')).count()
        
        # Calculate Technician Performance
        tech_performance = calculate_tech_performance(orders)

        ops = calculate_ops_metrics(date, date, orders=orders)

        return {
            'date': date,
            'title': date.strftime('%d %B, %Y'),
            'type': 'Daily',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'billed_revenue': billed_revenue,
            'billed_count': len(billed_orders),
            'paid_revenue': paid_revenue,
            'paid_count': paid_count,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': completed,
            'pending': len(orders) - completed,
            'orders': orders,
            'expenses': expenses,
            'ops': ops,
            'ready_today_count': ops['ready_count'],
            'tech_performance': tech_performance
        }
    except Exception as e:
        return {'error': str(e)}

def get_weekly_report(week_start=None):
    """Get report for a specific week"""
    try:
        from models import Order, Expense
        if week_start is None:
            today = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())
        
        week_end = week_start + timedelta(days=6)
        
        start_dt = datetime.combine(week_start, datetime.min.time())
        end_dt = datetime.combine(week_end, datetime.max.time())
        
        # 1. Target Orders (Delivery View - Drop Date)
        orders = Order.query.filter(Order.drop_date >= start_dt, Order.drop_date <= end_dt).all()
        
        # 2. Sales Orders (Billing View - Pickup Date)
        sales_orders = Order.query.filter(Order.pickup_date >= start_dt, Order.pickup_date <= end_dt).all()
        billed_orders = [o for o in sales_orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'received', 'settled']) or (o.status and o.status.lower() in ['billed', 'delivered', 'completed'])]
        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_revenue = sum([float(o.price or 0) for o in paid_orders])
        
        # Expenses
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if week_start <= e.expense_date <= week_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        billed_revenue = sum([float(o.price or 0) for o in billed_orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        
        # Tech Perf
        tech_performance = calculate_tech_performance(orders)
        
        ops = calculate_ops_metrics(week_start, week_end, orders=orders)

        return {
            'week_start': week_start,
            'week_end': week_end,
            'title': f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b, %Y')}",
            'type': 'Weekly',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'billed_revenue': billed_revenue,
            'billed_count': len(billed_orders),
            'paid_revenue': paid_revenue,
            'paid_count': paid_count,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': 0,
            'pending': 0,
            'orders': orders,
            'expenses': expenses,
            'ops': ops,
            'tech_performance': tech_performance
        }
    except Exception as e:
        return {'error': str(e)}

def get_monthly_report(year=None, month=None):
    """Get report for a specific month (Operational View)"""
    try:
        from models import Order, Expense
        if year is None or month is None:
            today = datetime.now().date()
            year = today.year
            month = today.month
        
        month_start = datetime(year, month, 1).date()
        if month == 12:
            next_month = datetime(year + 1, 1, 1).date()
        else:
            next_month = datetime(year, month + 1, 1).date()
        month_end = next_month - timedelta(days=1)
        
        start_dt = datetime.combine(month_start, datetime.min.time())
        end_dt = datetime.combine(month_end, datetime.max.time())
        
        # 1. Target Orders (Delivery View - Drop Date)
        orders = Order.query.filter(Order.drop_date >= start_dt, Order.drop_date <= end_dt).all()
        
        # 2. Sales Orders (Billing View - Pickup Date)
        sales_orders = Order.query.filter(Order.pickup_date >= start_dt, Order.pickup_date <= end_dt).all()
        billed_orders = [o for o in sales_orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'received', 'settled']) or (o.status and o.status.lower() in ['billed', 'delivered', 'completed'])]
        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_revenue = sum([float(o.price or 0) for o in paid_orders])
        
        # Expenses
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if month_start <= e.expense_date <= month_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        billed_revenue = sum([float(o.price or 0) for o in billed_orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        
        # Tech Perf
        tech_performance = calculate_tech_performance(orders)
        
        ops = calculate_ops_metrics(month_start, month_end, orders=orders)
        
        return {
            'month': month,
            'year': year,
            'title': datetime(year, month, 1).strftime('%B %Y'),
            'type': 'Monthly',
            'month_start': month_start,
            'month_end': month_end,
            'total_orders': len(orders),
            'total_revenue': total_revenue, 
            'billed_revenue': billed_revenue,
            'billed_count': len(billed_orders),
            'paid_revenue': paid_revenue,
            'paid_count': paid_count,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': 0,
            'pending': 0,
            'orders': orders,
            'expenses': expenses,
            'ops': ops,
            'tech_performance': tech_performance
        }
    except Exception as e:
        return {'error': str(e)}

def get_monthly_report_legacy(year=None, month=None):
    """Get report for a specific month with detailed financial breakdown"""
    try:
        from models import Order, Expense, Staff, Attendance
        if year is None or month is None:
            today = datetime.now().date()
            year = today.year
            month = today.month
        
        month_start = datetime(year, month, 1).date()
        if month == 12:
            next_month = datetime(year + 1, 1, 1).date()
        else:
            next_month = datetime(year, month + 1, 1).date()
        month_end = next_month - timedelta(days=1)
        
        all_orders = Order.query.all()
        orders = [o for o in all_orders if o.pickup_date and month_start <= o.pickup_date.date() <= month_end]
        
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if month_start <= e.expense_date <= month_end]
        
        # Financial Breakdown
        total_orders = len(orders)
        billed_orders = [o for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])]
        billed_count = len(billed_orders)

        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_amount = sum([float(o.price or 0) for o in paid_orders])
        
        total_discount = sum([float(o.discount or 0) if o.discount else 0 for o in orders])
        billed_amount = sum([float(o.price or 0) for o in billed_orders])
        total_revenue = sum([float(o.price or 0) for o in orders])
        
        income = billed_amount - total_discount
        
        # Categorized Expenses (Actual vs Real/AP)
        cat_list = ["Rent", "Petrol", "Utilities", "Salary", "Supplies", "Marketing", "Maintenance", "Electricity", "Other"]
        cat_expenses = {cat: {'actual': 0.0, 'real': 0.0} for cat in cat_list}
        
        # Initialize breakdown with all staff members
        staff_members = Staff.query.all()
        salary_breakdown = {}
        for s in staff_members:
            # --- Calculation for THIS Month ---
            base_sal_this_month = 0.0
            working_days = 0
            total_hours = 0
            
            if s.salary_type == 'monthly':
                base_sal_this_month = float(s.base_salary or 0)
            elif s.salary_type == 'per_day' and s.user_id:
                d_p = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date>=month_start, Attendance.date<=month_end, Attendance.status=='Present').count()
                d_h = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date>=month_start, Attendance.date<=month_end, Attendance.status=='Half-Day').count()
                working_days = d_p + (d_h * 0.5)
                base_sal_this_month = working_days * float(s.base_salary or 0)
            elif s.salary_type == 'per_hour' and s.user_id:
                atts = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date>=month_start, Attendance.date<=month_end).all()
                for a in atts:
                    if a.check_in and a.check_out:
                        h = min((a.check_out - a.check_in).total_seconds() / 3600, 12.0)
                        total_hours += int(h)
                base_sal_this_month = total_hours * float(s.base_salary or 0)

            # --- Calculation for PREVIOUS Balance (Carry Forward) ---
            # Total Earned before this month
            earned_before = 0.0
            if s.salary_type == 'monthly':
                # Months between start and now
                months = (month_start.year - s.created_at.year) * 12 + month_start.month - s.created_at.month
                earned_before = months * float(s.base_salary or 0)
            elif s.salary_type == 'per_day' and s.user_id:
                eb_p = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date < month_start, Attendance.status=='Present').count()
                eb_h = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date < month_start, Attendance.status=='Half-Day').count()
                earned_before = (eb_p + (eb_h * 0.5)) * float(s.base_salary or 0)
            elif s.salary_type == 'per_hour' and s.user_id:
                eb_atts = Attendance.query.filter(Attendance.user_id==s.user_id, Attendance.date < month_start).all()
                eb_h_total = 0
                for a in eb_atts:
                    if a.check_in and a.check_out:
                        h = min((a.check_out - a.check_in).total_seconds() / 3600, 12.0)
                        eb_h_total += int(h)
                earned_before = eb_h_total * float(s.base_salary or 0)

            # Total Paid before this month
            paid_before = db.session.query(db.func.sum(Expense.real_amount)).filter(
                Expense.category.in_(['Salary', 'Salary Advance']),
                Expense.title.ilike(f"%{s.name.strip()}%"),
                Expense.expense_date < month_start,
                Expense.status == 'approved'
            ).scalar() or 0.0
            
            opening_balance = earned_before - float(paid_before)

            salary_breakdown[s.name] = {
                'actual': 0.0, 
                'real': 0.0, 
                'base_salary': base_sal_this_month,
                'salary_type': s.salary_type,
                'days': working_days,
                'hours': total_hours,
                'rate': float(s.base_salary or 0),
                'opening_balance': opening_balance,
                'staff_id': s.id
            }
        
        for e in expenses:
            cat = e.category
            # Merge 'Salary' and 'Salary Advance' for breakdown
            if cat in ["Salary", "Salary Advance"]:
                emp_name = e.title.strip()
                if emp_name not in salary_breakdown:
                    salary_breakdown[emp_name] = {'actual': 0.0, 'real': 0.0, 'base_salary': 0.0}
                salary_breakdown[emp_name]['actual'] += float(e.amount or 0)
                salary_breakdown[emp_name]['real'] += float(e.real_amount or e.amount or 0)
                cat = "Salary"
            
            target_cat = cat if cat in cat_expenses else "Other"
            cat_expenses[target_cat]['actual'] += float(e.amount or 0)
            cat_expenses[target_cat]['real'] += float(e.real_amount or e.amount or 0)
        
        total_expenses_actual = sum(c['actual'] for c in cat_expenses.values())
        total_expenses_real = sum(c['real'] for c in cat_expenses.values())
        completed = len([o for o in orders if o.status and 'done' in o.status.lower()])
        
        ops = calculate_ops_metrics(month_start, month_end)

        # --- Payment Mode Breakdown (v02) ---
        payment_breakdown = {}
        for o in billed_orders:
            mode = o.payment_mode or 'Default'
            payment_breakdown[mode] = payment_breakdown.get(mode, 0.0) + float(o.price or 0)

        return {
            'month': month,
            'year': year,
            'title': datetime(year, month, 1).strftime('%B %Y'),
            'type': 'Monthly',
            'total_orders': total_orders,
            'billed_count': billed_count,
            'total_discount': total_discount,
            'billed_amount': billed_amount,
            'total_revenue': total_revenue,
            'income': income,
            'cat_expenses': cat_expenses,
            'salary_breakdown': salary_breakdown,
            'total_expenses_actual': total_expenses_actual,
            'total_expenses_real': total_expenses_real,
            'total_expenses': total_expenses_actual,  # Compatibility with reports.html
            'profit_loss_actual': income - total_expenses_actual,
            'profit_loss_real': income - total_expenses_real,
            'net_profit': income - total_expenses_actual,  # Compatibility with reports.html
            'completed': completed,
            'pending': total_orders - completed,
            'orders': orders,
            'month_start': month_start,
            'month_end': month_end,
            'ops': ops,
            'payment_breakdown': payment_breakdown,
            'paid_count': paid_count,
            'paid_amount': paid_amount
        }
    except Exception as e:
        return {'error': str(e)}

def get_yearly_report(year=None):
    """Get report for a specific year (Operational View)"""
    try:
        from models import Order, Expense
        if year is None:
            year = datetime.now().year
        
        year_start = datetime(year, 1, 1).date()
        year_end = datetime(year, 12, 31).date()
        
        start_dt = datetime.combine(year_start, datetime.min.time())
        end_dt = datetime.combine(year_end, datetime.max.time())
        
        # 1. Target Orders (Delivery View - Drop Date)
        orders = Order.query.filter(Order.drop_date >= start_dt, Order.drop_date <= end_dt).all()
        
        # 2. Sales Orders (Billing View - Pickup Date)
        sales_orders = Order.query.filter(Order.pickup_date >= start_dt, Order.pickup_date <= end_dt).all()
        billed_orders = [o for o in sales_orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'received', 'settled']) or (o.status and o.status.lower() in ['billed', 'delivered', 'completed'])]
        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_revenue = sum([float(o.price or 0) for o in paid_orders])
        
        # Expenses
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if year_start <= e.expense_date <= year_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        billed_revenue = sum([float(o.price or 0) for o in billed_orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        
        # Tech Perf
        tech_performance = calculate_tech_performance(orders)
        
        # Production Stats
        ops = calculate_ops_metrics(year_start, year_end, orders=orders)
        
        return {
            'year': year,
            'title': str(year),
            'type': 'Yearly',
            'year_start': year_start,
            'year_end': year_end,
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'billed_revenue': billed_revenue,
            'billed_count': len(billed_orders),
            'paid_revenue': paid_revenue,
            'paid_count': paid_count,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': 0,
            'pending': 0,
            'orders': orders,
            'expenses': expenses,
            'ops': ops,
            'tech_performance': tech_performance
        }
    except Exception as e:
        return {'error': str(e)}

def get_yearly_report_legacy(year=None):
    """Get report for a specific year with detailed financial breakdown"""
    try:
        from models import Order, Expense, Staff, Attendance
        if year is None:
            year = datetime.now().year
        
        year_start = datetime(year, 1, 1).date()
        year_end = datetime(year, 12, 31).date()
        
        all_orders = Order.query.all()
        orders = [o for o in all_orders if o.pickup_date and year_start <= o.pickup_date.date() <= year_end]
        
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if year_start <= e.expense_date <= year_end]
        
        # Financial Breakdown
        total_orders = len(orders)
        billed_orders = [o for o in orders if (o.payment_status and o.payment_status.lower() in ['paid', 'billed', 'done', 'completed']) or (o.status and o.status.lower() in ['billed', 'completed', 'delivered'])]
        billed_count = len(billed_orders)

        # --- Paid Orders Tracking (v02) ---
        paid_orders = [o for o in billed_orders if o.payment_status and o.payment_status.lower() == 'paid']
        paid_count = len(paid_orders)
        paid_amount = sum([float(o.price or 0) for o in paid_orders])
        
        total_discount = sum([float(o.discount or 0) if o.discount else 0 for o in orders])
        billed_amount = sum([float(o.price or 0) for o in billed_orders])
        total_revenue = sum([float(o.price or 0) for o in orders])
        
        income = billed_amount - total_discount
        
        # Categorized Expenses (Actual vs Real/AP)
        cat_list = ["Rent", "Petrol", "Utilities", "Salary", "Supplies", "Marketing", "Maintenance", "Electricity", "Other"]
        cat_expenses = {cat: {'actual': 0.0, 'real': 0.0} for cat in cat_list}
        
        staff_members = Staff.query.all()
        salary_breakdown = {}
        for s in staff_members:
            base_sal = float(s.base_salary or 0)
            working_days = 0
            total_hours = 0
            if s.salary_type == 'per_day' and s.user_id:
                # Calculate working days for the whole year
                days_present = Attendance.query.filter(
                    Attendance.user_id == s.user_id,
                    Attendance.date >= year_start,
                    Attendance.date <= year_end,
                    Attendance.status == 'Present'
                ).count()
                days_half = Attendance.query.filter(
                    Attendance.user_id == s.user_id,
                    Attendance.date >= year_start,
                    Attendance.date <= year_end,
                    Attendance.status == 'Half-Day'
                ).count()
                working_days = days_present + (days_half * 0.5)
                base_sal = working_days * float(s.base_salary or 0)
            elif s.salary_type == 'per_hour' and s.user_id:
                # Calculate total hours from attendance
                attendances = Attendance.query.filter(
                    Attendance.user_id == s.user_id,
                    Attendance.date >= year_start,
                    Attendance.date <= year_end
                ).all()
                total_hours = 0
                for a in attendances:
                    if a.check_in and a.check_out:
                        diff = a.check_out - a.check_in
                        # Cap at 12 hours and round down to nearest whole hour
                        shift_hours = min(diff.total_seconds() / 3600, 12.0)
                        total_hours += int(shift_hours)
                base_sal = total_hours * float(s.base_salary or 0)
            else:
                base_sal = base_sal * 12 # Annualize monthly salary
            
            salary_breakdown[s.name] = {
                'actual': 0.0, 
                'real': 0.0, 
                'base_salary': base_sal if s.user_id or s.salary_type == 'monthly' else 0.0,
                'salary_type': s.salary_type,
                'days': working_days,
                'hours': total_hours,
                'rate': float(s.base_salary or 0)
            }
        
        for e in expenses:
            cat = e.category
            if cat in ["Salary", "Salary Advance"]:
                emp_name = e.title.strip()
                if emp_name not in salary_breakdown:
                    salary_breakdown[emp_name] = {'actual': 0.0, 'real': 0.0, 'base_salary': 0.0}
                salary_breakdown[emp_name]['actual'] += float(e.amount or 0)
                salary_breakdown[emp_name]['real'] += float(e.real_amount or e.amount or 0)
                cat = "Salary"
            
            target_cat = cat if cat in cat_expenses else "Other"
            cat_expenses[target_cat]['actual'] += float(e.amount or 0)
            cat_expenses[target_cat]['real'] += float(e.real_amount or e.amount or 0)
        
        total_expenses_actual = sum(c['actual'] for c in cat_expenses.values())
        total_expenses_real = sum(c['real'] for c in cat_expenses.values())
        completed = len([o for o in orders if o.status and 'done' in o.status.lower()])
        
        ops = calculate_ops_metrics(year_start, year_end)

        # --- Payment Mode Breakdown (v02) ---
        payment_breakdown = {}
        for o in billed_orders:
            mode = o.payment_mode or 'Default'
            payment_breakdown[mode] = payment_breakdown.get(mode, 0.0) + float(o.price or 0)

        return {
            'year': year,
            'title': str(year),
            'type': 'Yearly',
            'total_orders': total_orders,
            'billed_count': billed_count,
            'total_discount': total_discount,
            'billed_amount': billed_amount,
            'total_revenue': total_revenue,
            'income': income,
            'cat_expenses': cat_expenses,
            'salary_breakdown': salary_breakdown,
            'total_expenses_actual': total_expenses_actual,
            'total_expenses_real': total_expenses_real,
            'total_expenses': total_expenses_actual,  # Compatibility with reports.html
            'profit_loss_actual': income - total_expenses_actual,
            'profit_loss_real': income - total_expenses_real,
            'net_profit': income - total_expenses_actual,  # Compatibility with reports.html
            'completed': completed,
            'pending': total_orders - completed,
            'orders': orders,
            'year_start': year_start,
            'ops': ops,
            'payment_breakdown': payment_breakdown,
            'paid_count': paid_count,
            'paid_amount': paid_amount
        }
    except Exception as e:
        return {'error': str(e)}


# --- Version Endpoint ---
@app.route("/version")
def version_info():
    return jsonify({
        "version": APP_VERSION,
        "release_date": VERSION_DATE,
        "status": VERSION_STATUS,
        "api_name": "Shoe Clinic API"
    })
# --- Auth Routes ---
@app.route("/")
def login_page():
    return render_template("auth.html")

@app.route("/login", methods=["POST"])
def login():
    """Enhanced secure login with rate limiting, account lockout, and 2FA"""
    from security_service import security_service
    from models import LoginAttempt
    
    username = request.form.get("username")
    password = request.form.get("password")
    ip_address = request.remote_addr
    
    # 1. Check IP-based rate limiting
    if security_service.is_rate_limited(ip_address):
        minutes_remaining = security_service.get_rate_limit_time_remaining(ip_address)
        flash(f"🛡️ Too many login attempts. Please try again in {minutes_remaining} minutes.", "danger")
        security_service.log_login_attempt(username or "unknown", ip_address, False, "rate_limited")
        return redirect(url_for("login_page"))
    
    # 2. Find user
    user = User.query.filter_by(username=username).first()
    
    if not user:
        # User doesn't exist - still track rate limit to prevent username enumeration
        security_service.track_rate_limit(ip_address)
        security_service.log_login_attempt(username, ip_address, False, "user_not_found")
        flash("Invalid username or password", "danger")
        return redirect(url_for("login_page"))
    
    # 3. Check if account is locked
    if security_service.is_account_locked(user):
        minutes_remaining = security_service.get_lockout_time_remaining(user)
        flash(f"🔒 Account locked due to multiple failed attempts. Try again in {minutes_remaining} minutes.", "danger")
        security_service.log_login_attempt(username, ip_address, False, "account_locked", user.id)
        return redirect(url_for("login_page"))
    
    # 4. Verify password
    if not bcrypt.check_password_hash(user.password, password):
        # Failed login
        is_locked = security_service.handle_failed_login(user)
        security_service.track_rate_limit(ip_address)
        
        if is_locked:
            flash(f"🔒 Account locked after {security_service.MAX_LOGIN_ATTEMPTS} failed attempts. Locked for {security_service.LOCKOUT_DURATION_MINUTES} minutes.", "danger")
            security_service.log_login_attempt(username, ip_address, False, "locked_now", user.id)
        else:
            attempts_remaining = security_service.MAX_LOGIN_ATTEMPTS - user.failed_login_attempts
            flash(f"❌ Invalid password. {attempts_remaining} attempts remaining.", "danger")
            security_service.log_login_attempt(username, ip_address, False, "wrong_password", user.id)
        
        return redirect(url_for("login_page"))
    
    # 5. Password correct - check account status
    if not user.is_active:
        flash("⏳ Account pending approval. Please contact the Owner.", "warning")
        security_service.log_login_attempt(username, ip_address, False, "account_inactive", user.id)
        return redirect(url_for("login_page"))
    
    # 6. Login successful (2FA removed from login flow as per request)
    security_service.handle_successful_login(user, ip_address)
    security_service.reset_rate_limit(ip_address)
    security_service.log_login_attempt(username, ip_address, True, None, user.id)
    
    login_user(user)
    session['last_activity'] = datetime.utcnow().isoformat()
    
    flash("✅ Login successful!", "success")
    return redirect(url_for("home"))

@app.route("/register", methods=["POST"])
def register():
    """Enhanced registration with password strength validation"""
    from security_service import security_service
    
    username = request.form.get("username")
    password = request.form.get("password")
    role = request.form.get("role")

    if User.query.filter_by(username=username).first():
        flash("Username already taken.", "danger")
        return redirect(url_for("login_page"))
    
    # Validate password strength
    is_valid, error_message = security_service.validate_password_strength(password)
    if not is_valid:
        flash(f"❌ {error_message}", "danger")
        return redirect(url_for("login_page"))

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    
    # If this is the first user, make them active Super Admin
    user_count = User.query.count()
    if user_count == 0:
        new_user = User(username=username, password=hashed_pw, role='super_admin', is_active=True)
        flash("Registration successful. You are the Owner.", "success")
    else:
        new_user = User(username=username, password=hashed_pw, role=role, is_active=False)
        flash("Registration successful. Waiting for Owner approval.", "info")
        
    db.session.add(new_user)
    db.session.commit()
    return redirect(url_for("login_page"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login_page"))

# --- Forgot Password Routes ---
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Step 1: Request password reset via 2FA"""
    if request.method == "POST":
        username = request.form.get("username")
        user = User.query.filter_by(username=username).first()
        
        if not user:
            # Security: Don't reveal if user exists (though for internal app this is less critical)
            flash("If the user exists, you will be redirected.", "info")
            return redirect(url_for("forgot_password"))
            
        if not user.two_factor_enabled:
            flash("❌ 2FA is not enabled for this account. Please contact the Admin.", "danger")
            return redirect(url_for("forgot_password"))
            
        # User exists and has 2FA -> Proceed to verification
        session['reset_username'] = username
        return redirect(url_for("reset_password_2fa"))
    
    return render_template("forgot_password.html")

@app.route("/reset-password/verify-2fa", methods=["GET", "POST"])
def reset_password_2fa():
    """Step 2: Verify 2FA for password reset"""
    if 'reset_username' not in session:
        return redirect(url_for("forgot_password"))
        
    username = session.get('reset_username')
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return redirect(url_for("forgot_password"))
        
    if request.method == "POST":
        from security_service import security_service
        code = request.form.get("otp")
        
        if security_service.verify_totp(user.two_factor_secret, code):
            session['reset_verified'] = True
            return redirect(url_for("reset_password_new"))
        else:
            flash("❌ Invalid code. Please try again.", "danger")
            
    return render_template("reset_password_2fa.html")

@app.route("/reset-password/new", methods=["GET", "POST"])
def reset_password_new():
    """Step 3: Set new password"""
    if 'reset_username' not in session or not session.get('reset_verified'):
        return redirect(url_for("forgot_password"))
        
    if request.method == "POST":
        new_pw = request.form.get("new_password")
        confirm_pw = request.form.get("confirm_password")
        
        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("reset_password_new"))
        
        user = User.query.filter_by(username=session['reset_username']).first()
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("forgot_password"))

        # Validate strength
        from security_service import security_service
        is_valid, msg = security_service.validate_password_strength(new_pw, user)
        if not is_valid:
            flash(f"❌ {msg}", "danger")
            return redirect(url_for("reset_password_new"))
            
        # Check for reuse
        if security_service.check_password_reuse(user, new_pw):
            flash("❌ You cannot reuse a recent password. Please choose a new one.", "danger")
            return redirect(url_for("reset_password_new"))
            
        # Update
        pw_hash = bcrypt.generate_password_hash(new_pw).decode("utf-8")
        user.password = pw_hash
        security_service.save_password_history(user, pw_hash)
        
        # Reset security flags if necessary (like lockout)
        user.failed_login_attempts = 0
        user.account_locked_until = None
        db.session.commit()
            
        flash("✅ Password updated successfully! Please login.", "success")
        session.pop('reset_username', None)
        session.pop('reset_verified', None)
        return redirect(url_for("login_page"))
            
    return render_template("reset_password_form.html")

# Removed SMS/OTP routes per user request


# --- Two-Factor Authentication (Google Authenticator) ---
@app.route("/verify-2fa-login", methods=["GET", "POST"])
def verify_2fa_login():
    """Verify Google Authenticator code during login"""
    from security_service import security_service
    
    if 'pending_2fa_user_id' not in session:
        flash("Invalid request. Please login again.", "warning")
        return redirect(url_for("login_page"))
    
    user_id = session.get('pending_2fa_user_id')
    user = User.query.get(user_id)
    
    if not user:
        session.pop('pending_2fa_user_id', None)
        flash("User not found.", "danger")
        return redirect(url_for("login_page"))
    
    if request.method == "POST":
        code = request.form.get("code")
        
        if security_service.verify_totp(user.two_factor_secret, code):
            # 2FA successful
            ip_address = session.get('pending_2fa_ip', request.remote_addr)
            
            security_service.handle_successful_login(user, ip_address)
            security_service.reset_rate_limit(ip_address)
            security_service.log_login_attempt(user.username, ip_address, True, "2fa_success", user.id)
            
            login_user(user)
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_2fa_ip', None)
            session['last_activity'] = datetime.utcnow().isoformat()
            
            flash("✅ Login successful!", "success")
            return redirect(url_for("home"))
        else:
            flash("❌ Invalid code. Please try again.", "danger")
    
    return render_template("verify_2fa_login.html", username=user.username)

# --- Security Settings & 2FA Management ---
@app.route("/security/settings")
@login_required
def security_settings():
    """Security management dashboard"""
    from models import LoginAttempt
    
    recent_activity = []
    if current_user.role == 'super_admin':
        # 1. Differential Cleanup (Privacy Hardening)
        try:
            # Delete attacker/unknown logs older than 24 hours
            one_day_ago = datetime.utcnow() - timedelta(hours=24)
            LoginAttempt.query.filter(
                LoginAttempt.user_id == None, 
                LoginAttempt.timestamp < one_day_ago
            ).delete()
            
            # Delete registered user logs older than 30 days
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            LoginAttempt.query.filter(
                LoginAttempt.user_id != None, 
                LoginAttempt.timestamp < thirty_days_ago
            ).delete()
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Cleanup error: {e}")

        # 2. Fetch 50 most recent login attempts across all users
        recent_activity = LoginAttempt.query.order_by(LoginAttempt.timestamp.desc()).limit(50).all()
        
    return render_template("security_settings.html", recent_activity=recent_activity)

@app.route("/security/2fa/setup")
@login_required
def setup_2fa():
    """Start 2FA setup process"""
    from security_service import security_service
    
    if current_user.two_factor_enabled:
        flash("2FA is already enabled.", "info")
        return redirect(url_for('security_settings'))
    
    # Generate temporary secret
    secret = security_service.generate_totp_secret()
    uri = security_service.get_totp_uri(current_user, secret)
    qr_code = security_service.generate_qr_code(uri)
    
    return render_template("setup_2fa.html", qr_code=qr_code, secret=secret)

@app.route("/security/2fa/verify-setup", methods=["POST"])
@login_required
def verify_2fa_setup():
    """Verify and enable 2FA"""
    from security_service import security_service
    
    secret = request.form.get("secret")
    code = request.form.get("otp")
    
    if security_service.verify_totp(secret, code):
        # Save secret to user model and enable
        current_user.two_factor_secret = secret
        current_user.two_factor_enabled = True
        db.session.commit()
        
        flash("✅ Two-Factor Authentication enabled successfully!", "success")
        return redirect(url_for('security_settings'))
    else:
        flash("❌ Invalid code. Please try again.", "danger")
        # Regenerate to prevent replay/stale issues (optional, but flow redirects back)
        uri = security_service.get_totp_uri(current_user, secret)
        qr_code = security_service.generate_qr_code(uri)
        return render_template("setup_2fa.html", qr_code=qr_code, secret=secret)

@app.route("/security/2fa/disable/confirm")
@login_required
def disable_2fa_confirm():
    """Confirm 2FA disable"""
    return render_template_string("""
    {% extends "base.html" %}
    {% block content %}
    <div class="container mt-5 text-center">
        <div class="card mx-auto shadow-sm border-0" style="max-width: 500px; border-radius: 15px;">
            <div class="card-body py-5">
                <div class="mb-4">
                    <i class="bi bi-exclamation-triangle-fill text-warning" style="font-size: 4rem;"></i>
                </div>
                <h3 class="fw-bold">Disable 2FA?</h3>
                <p class="text-muted mb-4">You are about to turn off Two-Factor Authentication. Your account will be less secure.</p>
                <div class="d-flex justify-content-center gap-3">
                    <a href="/security/settings" class="btn btn-light px-4">Cancel</a>
                    <form action="/security/2fa/disable" method="POST">
                        <button type="submit" class="btn btn-danger px-4">Disable 2FA</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """)

@app.route("/security/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    """Disable 2FA"""
    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    db.session.commit()
    
    flash("Two-Factor Authentication disabled.", "warning")
    return redirect(url_for('security_settings'))

@app.route("/security/change-password", methods=["POST"])
@login_required
def change_password():
    """Change user password"""
    current_pw = request.form.get("current_password")
    new_pw = request.form.get("new_password")
    confirm_pw = request.form.get("confirm_password")
    
    if new_pw != confirm_pw:
        flash("New passwords do not match.", "danger")
        return redirect(url_for('security_settings'))
        
    if not bcrypt.check_password_hash(current_user.password, current_pw):
        flash("Incorrect current password.", "danger")
        return redirect(url_for('security_settings'))

    from security_service import security_service
    is_valid, msg = security_service.validate_password_strength(new_pw, current_user)
    if not is_valid:
        flash(f"Error: {msg}", "danger")
        return redirect(url_for('security_settings'))
        
    if security_service.check_password_reuse(current_user, new_pw):
        flash("You cannot reuse a recent password.", "danger")
        return redirect(url_for('security_settings'))
        
    pw_hash = bcrypt.generate_password_hash(new_pw).decode("utf-8")
    current_user.password = pw_hash
    security_service.save_password_history(current_user, pw_hash)
    
    # Reset security flags
    current_user.failed_login_attempts = 0
    db.session.commit()
    
    flash("Password changed successfully.", "success")
    return redirect(url_for('security_settings'))

# --- Session Timeout Middleware ---
@app.before_request
def check_session_timeout():
    """Check for session timeout and enforce automatic logout"""
    from security_service import security_service
    
    # Skip for login/logout/static routes
    if request.endpoint in ['login', 'login_page', 'register', 'logout', 'static', 'version_info']:
        return
    
    if current_user.is_authenticated:
        if security_service.check_session_timeout():
            logout_user()
            session.clear()
            flash("⏱️ Session expired due to inactivity. Please login again.", "info")
            return redirect(url_for("login_page"))

# --- Admin: Unlock Account ---
@app.route("/admin/unlock-account/<int:user_id>", methods=["POST"])
@login_required
@super_admin_required
def unlock_account(user_id):
    """Admin can manually unlock a locked account"""
    user = User.query.get_or_404(user_id)
    
    user.account_locked_until = None
    user.failed_login_attempts = 0
    db.session.commit()
    
    flash(f"✅ Account unlocked for {user.username}", "success")
    return redirect(request.referrer or url_for("admin.manage_users"))


# --- Home Route ---
@app.route("/home")
@login_required
def home():
    today = datetime.now().date()
    todays_pickup_count = Order.query.filter(
        db.func.date(Order.pickup_date) == today
    ).count()
    expected_delivery_count = Order.query.filter(
        db.func.date(Order.drop_date) == today
    ).count()
    actually_delivered_count = Order.query.filter(
        Order.status.in_(['billed', 'delivered']),
        db.func.date(Order.actual_delivery_date) == today
    ).count()
    # Fetch announcements based on user role and ID, and expiry date
    now = datetime.now()
    announcements = Announcement.query.filter(
        Announcement.is_active == True
    ).filter(
        (Announcement.expiry_date == None) | (Announcement.expiry_date >= now)
    ).filter(
        (Announcement.target_role == 'all') |
        (Announcement.target_role == current_user.role) |
        (Announcement.target_user_id == current_user.id)
    ).order_by(Announcement.created_at.desc()).all()

    # Fetch upcoming holidays (next 30 days)
    upcoming_holidays = Holiday.query.filter(
        Holiday.date >= today
    ).order_by(Holiday.date.asc()).limit(10).all()

    return render_template("home.html", 
                         todays_pickup_count=todays_pickup_count,
                         expected_delivery_count=expected_delivery_count,
                         actually_delivered_count=actually_delivered_count,
                         announcements=announcements,
                         upcoming_holidays=upcoming_holidays,
                         user=current_user)

# --- Dashboard Route ---
@app.route("/tsc_dashboard")
@login_required
def tsc_dashboard():
    search = request.args.get("search", "")
    pickup_date_filter = request.args.get("pickup_date_filter", "")
    drop_date_filter = request.args.get("drop_date_filter", "")
    status_filter = request.args.get("status_filter", "")
    technician_filter = request.args.get("technician_filter", "")
    discount_filter = request.args.get("discount_filter", "")
    outsource_filter = request.args.get("outsource_filter", "")

    query = Order.query.options(db.joinedload(Order.items))

    if search:
        query = query.filter(
            (Order.customer_name.ilike(f"%{search}%")) |
            (Order.mobile.ilike(f"%{search}%")) |
            (Order.job_id.ilike(f"%{search}%"))
        )
    if pickup_date_filter:
        query = query.filter(db.func.date(Order.pickup_date) == pickup_date_filter)
    if drop_date_filter:
        query = query.filter(db.func.date(Order.drop_date) == drop_date_filter)
    if status_filter:
        query = query.filter(Order.status == status_filter)
    if technician_filter:
        query = query.join(Order.items).filter(
            (Order.technician.ilike(f"%{technician_filter}%")) |
            (OrderItem.technician.ilike(f"%{technician_filter}%"))
        ).distinct()
    if discount_filter:
        query = query.filter(Order.discount.ilike(f"%{discount_filter}%"))
    if outsource_filter:
        query = query.filter(Order.outsource == outsource_filter)

    # Filter by Job ID ascending (oldest orders first) and then by pickup_date descending
    orders = query.order_by(Order.job_id.asc(), Order.pickup_date.desc()).all()
    
    # Fetch active staff for the filter dropdown
    staff = User.query.filter_by(is_active=True).all()
    
    return render_template("dashboard.html", orders=orders, request=request, staff=staff)

# --- Add Order ---
@app.route("/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_order():
    last_order = Order.query.order_by(Order.id.desc()).first()
    if last_order and last_order.job_id:
        last_id = int(last_order.job_id.replace("TSC", ""))
        new_job_id = f"TSC{last_id+1:05d}"
    else:
        new_job_id = "TSC00001"

    today = datetime.today().strftime("%Y-%m-%d")

    if request.method == "POST":
        try:
            order = Order(
                job_id=request.form["job_id"],
                customer_name=request.form["name"],
                drop_date=datetime.strptime(request.form["drop_date"], "%Y-%m-%d"),
                place=request.form["place"],
                mobile=request.form["mobile"],
                status=request.form["status"],
                token=request.form.get("token"),
                pickup_date=datetime.strptime(request.form["pickup_date"], "%Y-%m-%d"),
                service_note=request.form.get("service_note"),
                technician=request.form.get("technician"),
                created_at=datetime.now()
            )
            if order.technician:
                order.service_date = datetime.now()
            db.session.add(order)
            db.session.flush()

            total_order_price = 0.0
            total_item_count = 0
            total_order_discount = 0.0
            first_product_name = None

            for i in range(1, 50):
                product_name = request.form.get(f"items[{i}][product_name]")
                if not product_name:
                    continue

                if not first_product_name:
                    first_product_name = product_name

                services = request.form.getlist(f"items[{i}][services][]")
                prices = request.form.getlist(f"items[{i}][service_prices][]")
                discounts = request.form.getlist(f"items[{i}][service_discounts][]")

                # compute totals for this item
                try:
                    service_prices = [float(p) if p else 0.0 for p in prices]
                except ValueError:
                    service_prices = [float(p) if p else 0.0 for p in prices if p is not None]
                try:
                    service_discounts = [float(d) if d else 0.0 for d in discounts]
                except ValueError:
                    service_discounts = [float(d) if d else 0.0 for d in discounts if d is not None]

                item_price = sum(service_prices) if service_prices else 0.0
                item_discount = sum(service_discounts) if service_discounts else 0.0

                item = OrderItem(
                    order_id=order.id,
                    product_name=product_name,
                    services=','.join(services) if services else None,
                    price=item_price,
                    discount=item_discount,
                    status='yts',
                    defects=request.form.get(f"items[{i}][defects]")
                )
                db.session.add(item)
                db.session.flush()

                total_order_price += (item_price - item_discount)
                total_item_count += 1
                total_order_discount += item_discount

            # update order totals
            order.price = total_order_price
            order.item_count = total_item_count
            # store total discount as string to preserve existing schema type
            order.discount = str(total_order_discount) if total_order_discount else None
            # set order.product_name from first item (if available)
            if first_product_name:
                order.product_name = first_product_name

            db.session.commit()
            flash("Order added successfully ✅", "success")
            return redirect(url_for("pickup_confirmation", order_id=order.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding order: {e}", "danger")

    # Fetch active staff for the technician dropdown
    staff = User.query.filter_by(is_active=True).all()
    
    return render_template("add.html", job_id=new_job_id, today=today, staff=staff)

@app.route("/edit_order/<int:order_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_order(order_id):
    order = Order.query.get_or_404(order_id)

    if request.method == "POST":
        # Basic Info
        new_technician = request.form.get("technician")
        if new_technician and not order.service_date:
            order.service_date = datetime.now()
        order.technician = new_technician

        order.job_id = request.form.get("job_id")
        order.customer_name = request.form.get("customer_name")
        order.pickup_date = datetime.strptime(request.form.get("pickup_date"), "%Y-%m-%d") if request.form.get("pickup_date") else None
        
        # Only update service_date manually if provided, otherwise keep the automated one
        form_service_date = request.form.get("service_date")
        if form_service_date:
            order.service_date = datetime.strptime(form_service_date, "%Y-%m-%d")
        
        # Allow manual update of work_finish_date
        form_work_finish_date = request.form.get("work_finish_date")
        if form_work_finish_date:
            order.work_finish_date = datetime.strptime(form_work_finish_date, "%Y-%m-%d")
            
        order.drop_date = datetime.strptime(request.form.get("drop_date"), "%Y-%m-%d") if request.form.get("drop_date") else None
        order.place = request.form.get("place")
        order.service_note = request.form.get("service_note")
        
        new_status = request.form.get("status")
        if new_status in ['done', 'ready to deliver', 'billed'] and not order.work_finish_date:
            order.work_finish_date = datetime.now()
        
        # Only update if status actually changed to avoid unnecessary overwrites
        if order.status != new_status:
            order.status = new_status
            
            # Cascade status change to all items and their services to keep them in sync
            # This fixes the issue where dashboard expanded view shows old/stale status
            for item in order.items:
                # If main order is Billed, items should also show valid completed status (billed)
                item.status = new_status
                
                if item.services:
                    # Update granular service statuses
                    import json
                    try:
                        statuses = json.loads(item.service_statuses or '{}')
                        
                        # Initialize if empty based on services string
                        if not statuses and item.services:
                            statuses = {s.strip(): new_status for s in item.services.split(',')}
                        else:
                            # Update existing keys
                            for k in statuses:
                                # Force update all service statuses to match Order status
                                statuses[k] = new_status
                                
                        item.service_statuses = json.dumps(statuses)
                    except:
                        pass

        # Other Info
        order.mobile = request.form.get("mobile")
        order.product_name = request.form.get("product_name")
        order.token = request.form.get("token")
        order.price = float(request.form.get("price")) if request.form.get("price") else None
        order.payment_mode = request.form.get("payment_mode")
        order.payment_status = request.form.get("payment_status")
        order.discount = request.form.get("discount")
        order.outsource = request.form.get("outsource")
        order.item_count = int(request.form.get("item_count")) if request.form.get("item_count") else None

        try:
            db.session.commit()
            flash("Order updated successfully!", "success")
            return redirect(url_for("tsc_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating order: {str(e)}", "danger")
            # Fetch active staff in case of error too
            staff = User.query.filter_by(is_active=True).all()
            return render_template("edit.html", order=order, staff=staff)

    # Fetch active staff for the dropdown
    staff = User.query.filter_by(is_active=True).all()
    return render_template("edit.html", order=order, staff=staff)


# --- User Management ---
@app.route("/manage_users")
@login_required
def manage_users():
    if current_user.role != "admin":
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("home"))
    users = User.query.order_by(User.username).all()
    return render_template("manage_users.html", users=users)

@app.route("/activate-user/<int:user_id>")
@login_required
def activate_user(user_id):
    if current_user.role not in ["admin", "super_admin"]:
        flash("Access denied.", "danger")
        return redirect(url_for("home"))
    
    user = User.query.get_or_404(user_id)
    
    # Hierarchy Check: Admin cannot manage Admin or Super Admin
    if current_user.role == 'admin' and user.role in ['admin', 'super_admin']:
        flash("Restriction: Admins cannot manage other Admin or Owner accounts.", "warning")
        return redirect(url_for("admin.manage_users"))

    user.is_active = True
    db.session.commit()
    flash(f"Activated {user.username}", "success")
    return redirect(url_for("admin.manage_users"))

@app.route("/deactivate-user/<int:user_id>")
@login_required
def deactivate_user(user_id):
    if current_user.role not in ["admin", "super_admin"]:
        flash("Access denied.", "danger")
        return redirect(url_for("home"))
    
    user = User.query.get_or_404(user_id)
    
    # Hierarchy Check: Admin cannot manage Admin or Super Admin
    if current_user.role == 'admin' and user.role in ['admin', 'super_admin']:
        flash("Restriction: Admins cannot manage other Admin or Owner accounts.", "warning")
        return redirect(url_for("admin.manage_users"))

    user.is_active = False
    db.session.commit()
    flash(f"Deactivated {user.username}", "warning")
    return redirect(url_for("admin.manage_users"))

@app.route("/delete-user/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    if current_user.role not in ["admin", "super_admin"]:
        flash("Access denied.", "danger")
        return redirect(url_for("home"))
    
    user = User.query.get_or_404(user_id)
    
    # Hierarchy Check: Admin cannot manage Admin or Super Admin
    if current_user.role == 'admin' and user.role in ['admin', 'super_admin']:
        flash("Restriction: Admins cannot manage other Admin or Owner accounts.", "warning")
        return redirect(url_for("admin.manage_users"))
    
    # Safety: Cannot delete self
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin.manage_users"))

    db.session.delete(user)
    db.session.commit()
    flash(f"Deleted {user.username}", "danger")
    return redirect(url_for("admin.manage_users"))

@app.route("/update_task_status", methods=["POST"])
@login_required
def update_task_status():
    from models import OrderItem, Order
    import json
    
    item_id = request.form.get("item_id")
    service_name = request.form.get("service_name")
    new_status = request.form.get("new_status")
    
    try:
        item = OrderItem.query.get(item_id)
        if item:
            statuses = json.loads(item.service_statuses) if item.service_statuses else {}
            statuses[service_name] = new_status
            item.service_statuses = json.dumps(statuses)
            
            # --- Improved Status Logic ---
            
            # 1. Determine Item Status based on its Services
            service_statuses = []
            if item.services:
                for s in item.services.split(','):
                    name = s.strip()
                    service_statuses.append(statuses.get(name, 'yts'))
            
            if not service_statuses: 
                pass 
            elif all(s == 'yts' for s in service_statuses):
                item.status = 'yts'
            elif all(s == 'done' for s in service_statuses):
                item.status = 'done'
            elif all(s == 'ready to deliver' for s in service_statuses):
                item.status = 'ready to deliver'
            # Check for mixed completed states (e.g. some done, some ready)
            elif all(s in ['done', 'ready to deliver'] for s in service_statuses):
                # If mixed 'done' and 'ready', treat as 'done' to be safe, or 'ready'?
                # User specifically asked for DONE -> DONE.
                item.status = 'done'
            else:
                item.status = 'wip'
                
            # 2. Determine Order Status based on all Items
            order = item.order
            item_statuses = [i.status for i in order.items if i.id != item.id] 
            item_statuses.append(item.status) 
            
            if all(s == 'yts' for s in item_statuses):
                order.status = 'yts'
            elif all(s == 'done' for s in item_statuses):
                order.status = 'done'
            elif all(s == 'ready to deliver' for s in item_statuses):
                order.status = 'ready to deliver'
                if not order.work_finish_date:
                    order.work_finish_date = datetime.now()
            elif all(s in ['done', 'ready to deliver'] for s in item_statuses):
                 # Mixed Done/Ready -> Done
                 order.status = 'done'
                 # Note: we don't set work_finish_date here unless we consider 'done' as finished work?
                 # Usually 'done' means work is finished. 'ready to deliver' means ready for customer.
                 if not order.work_finish_date:
                    order.work_finish_date = datetime.now()
            else:
                order.status = 'wip'
                
            db.session.commit()
            flash(f"Status updated to {new_status} ✅", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating status: {str(e)}", "danger")
        
    return redirect(url_for("my_works"))

@app.route("/my_works")
@login_required
def my_works():
    from models import Order, OrderItem
    from datetime import datetime, date
    import json
    
    today = date.today()
    
    # Fetch individual tasks (OrderItem) assigned to current user (either as lead or for specific services)
    search_term = f'%"{current_user.username}"%'
    assigned_items = OrderItem.query.filter(
        (OrderItem.technician == current_user.username) | 
        (OrderItem.service_assignments.ilike(search_term))
    ).order_by(OrderItem.created_at.desc()).all()
    
    # Filter items based on assignment_start_date AND completion status
    filtered_items = []
    completed_items = []
    
    for item in assigned_items:
        if item.order:
            if item.order.assignment_start_date and item.order.assignment_start_date.date() > today:
                continue
            
            # Split into Active vs Completed based on Item Status
            # Note: Granular status might differ, but list is Item-based. 
            # If Item is Ready/Billed, it goes to Completed History.
            # If Done/WIP/YTS, it stays in Active (Active Table).
            st = (item.status or '').lower()
            if st in ['ready to deliver', 'billed', 'delivered', 'completed']:
                 # Check if 'completed' should be in active or history? 
                 # User previously differentiated 'Done' (Work Finished) vs 'Ready' (Packed).
                 # Usually 'Ready' and 'Billed' are the finalized states. 'Done' might still need review/packing.
                 # Let's keep 'Done' in Active for now, and 'Ready/Billed' in History.
                 if st in ['done', 'completed']:
                     filtered_items.append(item)
                 else:
                     completed_items.append(item)
            else:
                filtered_items.append(item)
    
    # Calculate Granular Task Counts
    import json
    yts_count = 0
    wip_count = 0
    done_count = 0
    ready_count = 0
    
    for item in assigned_items: 
        try:
            assignments = json.loads(item.service_assignments or '{}')
            statuses = json.loads(item.service_statuses or '{}')
        except:
            assignments = {}
            statuses = {}

        is_item_technician = (item.technician == current_user.username)
        
        # Determine services for this user
        user_services = []
        if item.services:
            for s in item.services.split(','):
                s_name = s.strip()
                if assignments.get(s_name) == current_user.username or (not assignments.get(s_name) and is_item_technician):
                    user_services.append(s_name)
        
        # If no specific services but user is item technician, count the item itself
        if not user_services and is_item_technician:
             st = (item.status or 'yts').lower()
             if st in ['ready to deliver', 'billed', 'delivered']:
                 ready_count += 1
             elif st in ['done', 'completed']:
                 done_count += 1
             elif st in ['wip', 'work in progress']:
                 wip_count += 1
             else: 
                 yts_count += 1
        else:
            # Count based on services
            for s_name in user_services:
                st = statuses.get(s_name, 'yts').lower()
                if st in ['ready to deliver', 'billed', 'delivered']:
                    ready_count += 1
                elif st in ['done', 'completed']:
                    done_count += 1
                elif st in ['wip', 'work in progress']:
                    wip_count += 1
                else:
                    yts_count += 1

    return render_template("my_works.html", items=filtered_items, completed_items=completed_items, 
                           task_stats={'yts': yts_count, 'wip': wip_count, 'done': done_count, 'ready': ready_count, 'total': yts_count + wip_count + done_count + ready_count})

# Reports
@app.route("/report_daily")
@login_required
@admin_required
def report_daily():
    date_str = request.args.get('date')
    selected_date = None
    if date_str:
        try: selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except: pass
    
    data = get_daily_report(selected_date)
    return render_template("admin/reports/daily.html", daily=data, selected_date=data.get('date'))

@app.route("/report_weekly")
@login_required
@admin_required
def report_weekly():
    date_str = request.args.get('date')
    week_start = None
    if date_str:
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            week_start = d - timedelta(days=d.weekday())
        except: pass
    
    data = get_weekly_report(week_start)
    return render_template("admin/reports/weekly.html", weekly=data, selected_date=date_str)

@app.route("/report_monthly")
@login_required
@admin_required
def report_monthly():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    data = get_monthly_report(year, month)
    return render_template("admin/reports/monthly.html", monthly=data, years=range(2024, 2030), selected_year=data.get('year'), selected_month=data.get('month'))

@app.route("/report_yearly")
@login_required
@admin_required
def report_yearly():
    year = request.args.get('year', type=int)
    data = get_yearly_report(year)
    return render_template("admin/reports/yearly.html", yearly=data, years=range(2024, 2030), selected_year=data.get('year'))

# Expenses
@app.route("/day_to_day_expense")
@login_required
@admin_required
def day_to_day_expense():
    return redirect(url_for('admin.day_to_day_expense', filter_type='date'))

@app.route("/monthly_expense")
@login_required
@admin_required
def monthly_expense():
    return redirect(url_for('admin.day_to_day_expense', filter_type='month'))

@app.route("/expense_dashboard")
@login_required
@admin_required
def expense_dashboard():
    return redirect(url_for('admin.day_to_day_expense', filter_type='year'))

# Misc Pages
@app.route("/payouts")
@login_required
@admin_required
def payouts():
    return redirect(url_for('admin.payouts'))

@app.route("/todays_delivery")
@login_required
@admin_required
def todays_delivery():
    from datetime import datetime
    today = datetime.now().date()
    orders = Order.query.filter(db.func.date(Order.drop_date) == today).all()
    return render_template("todays_delivery.html", orders=orders, today=today)

@app.route("/print_bill", methods=["GET", "POST"])
@login_required
@admin_required
def print_bill():
    from datetime import datetime
    today_date = datetime.now().date()
    
    if request.method == "POST":
        order_id = request.form.get("order_id")
        order = Order.query.get(order_id)
        if order:
            from datetime import datetime
            order.status = "billed"
            if not order.actual_delivery_date:
                order.actual_delivery_date = datetime.now()
            if not order.work_finish_date:
                order.work_finish_date = datetime.now()
            db.session.commit()
        return redirect(url_for('view_bill', order_id=order_id))

    # GET parameters for search and filter
    search = request.args.get('search', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    status_filter = request.args.get('status_filter', '')

    query = Order.query

    if search:
        query = query.filter(
            (Order.customer_name.ilike(f"%{search}%")) |
            (Order.job_id.ilike(f"%{search}%")) |
            (Order.mobile.ilike(f"%{search}%"))
        )

    if status_filter:
        query = query.filter(Order.status == status_filter)

    if start_date:
        try:
            s_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Order.pickup_date) >= s_dt)
        except ValueError: pass
    
    if end_date:
        try:
            e_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Order.pickup_date) <= e_dt)
        except ValueError: pass

    # Sort by pickup date descending
    query = query.order_by(Order.pickup_date.desc())

    # If no search, status, or date filter, default to today's orders
    if not (search or start_date or end_date or status_filter):
        orders = query.filter(db.func.date(Order.pickup_date) == today_date).all()
        # Fallback to recent 20 if today is empty
        if not orders:
            orders = query.limit(20).all()
    else:
        orders = query.all()
        
    return render_template("print_bill.html", orders=orders, today=today_date.strftime('%d-%b-%Y'), 
                           search=search, start_date=start_date, end_date=end_date, status_filter=status_filter)

@app.route("/view_bill/<int:order_id>")
@login_required
@admin_required
def view_bill(order_id):
    from models import Order, PaymentTransaction
    order = Order.query.get_or_404(order_id)
    
    # Try to find an existing payment link for this order
    tx = PaymentTransaction.query.filter_by(order_id=order.id, status='created').filter(PaymentTransaction.short_url != None).first()
    
    payment_link = tx.short_url if tx else None
    
    # Generate new link if it doesn't exist and price is valid
    if not payment_link and order.price and order.price > 0:
        try:
            # Create Razorpay Payment Link
            link_data = {
                "amount": int(float(order.price) * 100),
                "currency": "INR",
                "accept_partial": False,
                "description": f"Payment for Job ID: {order.job_id}",
                "customer": {
                    "name": order.customer_name,
                    "contact": order.mobile,
                },
                "notify": {"sms": False, "email": False},
                "reminder_enable": True,
                "notes": {"order_id": order.id, "job_id": order.job_id},
                "callback_url": url_for('dashboard', _external=True), # Redirect back to dashboard after payment
                "callback_method": "get"
            }
            
            plink = razorpay_client.payment_link.create(data=link_data)
            payment_link = plink.get('short_url')
            
            # Save transaction info
            new_tx = PaymentTransaction(
                order_id=order.id,
                razorpay_plink_id=plink.get('id'),
                short_url=payment_link,
                amount=float(order.price),
                status='created'
            )
            db.session.add(new_tx)
            db.session.commit()
            
        except Exception as e:
            print(f"Error generating payment link: {e}")
            # Silently fail, bill will still show without link

    return render_template("view_order_bill.html", order=order, payment_link=payment_link)

@app.route("/pickup_confirmation/<int:order_id>")
@login_required
@admin_required
def pickup_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Pre-generate share message (WhatsApp formatted)
    msg = f"*SHOECLINIC - PICKUP CONFIRMATION*\n\n"
    msg += f"Job ID: {order.job_id}\n"
    msg += f"Expected Delivery: {order.drop_date.strftime('%d-%m-%Y') if order.drop_date else 'TBA'}\n"
    msg += f"--------------------------------\n"
    
    # Add Itemized details
    for i, item in enumerate(order.items, 1):
        services_str = f" ({item.services})" if item.services else ""
        msg += f"{i}. {item.product_name or 'Item'}{services_str}\n"
        if item.defects:
            msg += f"   ⚠ Condition: {item.defects}\n"
            
    msg += f"\nCustomer: {order.customer_name}\n"
    msg += f"Total Items: {order.item_count}\n"
    msg += f"Total Amount: ₹{order.price}\n"
    msg += f"--------------------------------\n"
    msg += f"Thank you for choosing ShoeClinic!"
    
    import urllib.parse
    encoded_msg = urllib.parse.quote(msg)
    
    return render_template("pickup_confirmation.html", order=order, msg=msg, encoded_msg=encoded_msg)

@app.route("/announcement", methods=["GET", "POST"])
@login_required
@admin_required
def announcement():
    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        target_role = request.form.get("target_role", "all")
        target_user_id = request.form.get("target_user_id")
        duration = request.form.get("duration") # days
        
        if target_user_id == "":
            target_user_id = None
            
        expiry_date = None
        if duration and duration.isdigit():
            expiry_date = datetime.now() + timedelta(days=int(duration))
            
        new_ann = Announcement(
            title=title,
            content=content,
            target_role=target_role,
            target_user_id=target_user_id,
            expiry_date=expiry_date,
            created_by=current_user.id
        )
        db.session.add(new_ann)
        db.session.commit()
        flash("Announcement posted successfully!", "success")
        return redirect(url_for("announcement"))

    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    users = User.query.filter_by(is_active=True).all()
    return render_template("add_announcement.html", 
                         announcements=announcements, 
                         users=users)

@app.route("/delete_announcement/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_announcement(id):
    ann = Announcement.query.get_or_404(id)
    db.session.delete(ann)
    db.session.commit()
    flash("Announcement deleted.", "info")
    return redirect(url_for("announcement"))

@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    from datetime import datetime
    today = datetime.now().date()
    
    # Get current user's attendance for today
    today_attendance = Attendance.query.filter_by(user_id=current_user.id, date=today).first()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "mark_in":
            if not today_attendance:
                today_attendance = Attendance(user_id=current_user.id, date=today, check_in=datetime.now())
                db.session.add(today_attendance)
                flash("Good morning! Mark-in recorded.", "success")
            else:
                flash("You have already marked in for today.", "warning")
                
        elif action == "mark_out":
            if today_attendance and not today_attendance.check_out:
                today_attendance.check_out = datetime.now()
                flash("Evening mark-out recorded. Have a great evening!", "success")
            else:
                flash("Mark-in required first or already marked out.", "warning")
                
        elif action == "holiday":
            leave_date_str = request.form.get("leave_date")
            target_date = datetime.strptime(leave_date_str, "%Y-%m-%d").date() if leave_date_str else today
            
            existing_attendance = Attendance.query.filter_by(user_id=current_user.id, date=target_date).first()
            
            if not existing_attendance:
                # Create as Leave Pending
                new_leave = Attendance(user_id=current_user.id, date=target_date, status="Leave Pending", note=request.form.get("note"))
                db.session.add(new_leave)
                
                # Notify Super Admin
                super_admin = User.query.filter_by(role='super_admin').first()
                if super_admin:
                    notif = Notification(
                        user_id=super_admin.id,
                        title="New Leave Request 📅",
                        message=f"{current_user.username} has applied for leave on {target_date.strftime('%d %b')}.",
                        link=url_for('attendance_manage')
                    )
                    db.session.add(notif)
                    
                flash(f"Leave request for {target_date.strftime('%d %b, %Y')} submitted for approval.", "info")
            else:
                if existing_attendance.status == 'Leave Pending':
                     flash(f"Leave request for {target_date.strftime('%d %b, %Y')} is already pending approval.", "warning")
                else:
                     flash(f"Attendance/Leave record already exists for {target_date.strftime('%d %b, %Y')}."
                     , "warning")
        
        elif action == "request_reg":
            att_id = request.form.get("attendance_id")
            att = Attendance.query.get_or_404(att_id)
            if att.user_id != current_user.id:
                flash("Unauthorized request.", "danger")
            else:
                att.reg_requested = True
                att.reg_status = request.form.get("reg_status")
                att.reg_reason = request.form.get("reg_reason")
                
                # Notify Super Admin
                super_admin = User.query.filter_by(role='super_admin').first()
                if super_admin:
                    notif = Notification(
                        user_id=super_admin.id,
                        title="Regularization Request 🔧",
                        message=f"{current_user.username} requested update for {att.date.strftime('%d %b')}.",
                        link=url_for('attendance_manage')
                    )
                    db.session.add(notif)
                    
                flash("Regularization request sent to Super Admin.", "info")
        
        db.session.commit()
        return redirect(url_for('attendance'))

    # Visibility Check: Employees only see their own. Admins see all.
    if current_user.role == 'super_admin':
        all_attendance = Attendance.query.order_by(Attendance.date.desc(), Attendance.created_at.desc()).limit(100).all()
    else:
        all_attendance = Attendance.query.filter_by(user_id=current_user.id).order_by(Attendance.date.desc()).all()
    
    return render_template("attendance.html", 
                         today_attendance=today_attendance, 
                         all_attendance=all_attendance,
                         today=today)

def get_kerala_holidays(year, month):
    # Public Holidays based on Kerala Govt. Calendar
    all_holidays = {
        2025: {
            1: [(1, "New Year's Day"), (26, "Republic Day")],
            2: [(26, "Maha Shivaratri")],
            3: [(31, "Id-ul-Fitr (Ramzan)")],
            4: [(14, "Vishu / Ambedkar Jayanthi"), (18, "Good Friday")],
            5: [(1, "May Day")],
            6: [(6, "Id-ul-Ad'ha (Bakrid)")],
            7: [(6, "Muharram")],
            8: [(15, "Independence Day")],
            9: [(5, "First Onam"), (6, "Thiruvonam"), (21, "Sree Narayana Guru Samadhi")],
            10: [(1, "Mahanavami"), (2, "Vijayadasami / Gandhi Jayanthi"), (20, "Deepavali")],
            12: [(25, "Christmas")]
        },
        2026: {
            1: [(2, "Mannam Jayanthi"), (26, "Republic Day")],
            3: [(20, "Id-Ul-Fitr (Ramzan)")],
            4: [(2, "Maundy Thursday"), (3, "Good Friday"), (14, "Ambedkar Jayanthi"), (15, "Vishu")],
            5: [(1, "May Day"), (27, "Id-Ul-Adha (Bakrid)")],
            6: [(25, "Muharram")],
            8: [(12, "Karkkadaka Vaavu"), (15, "Independence Day"), (25, "First Onam"), (26, "Thiruvonam"), (28, "Sree Narayana Guru Jayanthi")],
            9: [(4, "Sreekrishna Jayanthi"), (21, "Sree Narayana Guru Samadhi")],
            10: [(2, "Gandhi Jayanthi"), (20, "Maha Navami"), (21, "Vijayadasami")],
            11: [(8, "Deepavali")],
            12: [(25, "Christmas")]
        }
    }
    return all_holidays.get(year, {}).get(month, [])

@app.route("/calendar", methods=["GET", "POST"])
@login_required
@super_admin_required
def calendar():
    today = datetime.now()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    if request.method == "POST":
        date_str = request.form.get("date")
        name = request.form.get("name")
        desc = request.form.get("description")
        
        holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Check if holiday already exists
        existing = Holiday.query.filter_by(date=holiday_date).first()
        if existing:
            existing.name = name
            existing.description = desc
            flash(f"Holiday '{name}' updated.", "success")
        else:
            new_holiday = Holiday(date=holiday_date, name=name, description=desc)
            db.session.add(new_holiday)
            flash(f"Holiday '{name}' marked.", "success")
            
        db.session.commit()
        return redirect(url_for('calendar', year=year, month=month))

    # Calendar logic
    cal = py_calendar.Calendar(firstweekday=6) # Sunday first
    month_days = cal.monthdayscalendar(year, month)
    month_name = py_calendar.month_name[month]
    
    # Get holidays for this month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)
        
    holidays = Holiday.query.filter(Holiday.date >= start_date, Holiday.date < end_date).all()
    holiday_map = {h.date.day: h for h in holidays}

    # Prev/Next Month logic
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    kerala_suggestions = get_kerala_holidays(year, month)

    return render_template("calendar.html", 
                         month_days=month_days, 
                         month_name=month_name,
                         year=year,
                         month=month,
                         holiday_map=holiday_map,
                         prev_month=prev_month,
                         prev_year=prev_year,
                         next_month=next_month,
                         next_year=next_year,
                         today_day=today.day if today.year == year and today.month == month else None,
                         kerala_suggestions=kerala_suggestions)

@app.route("/admin/attendance_manage", methods=["GET", "POST"])
@login_required
@super_admin_required
def attendance_manage():
    if request.method == "POST":
        action = request.form.get("action") # approve, manual, or add
        
        if action == "add":
            # Add or Update manual attendance
            user_id = request.form.get("user_id", type=int)
            date_str = request.form.get("date")
            status = request.form.get("status")
            note = request.form.get("note")
            ci_time = request.form.get("check_in")
            co_time = request.form.get("check_out")
            
            try:
                p_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except Exception as e:
                flash(f"Invalid date format: {date_str}", "danger")
                return redirect(url_for('attendance_manage'))
            
            # Use existing if it exists, else create new
            att = Attendance.query.filter_by(user_id=user_id, date=p_date).first()
            if not att:
                att = Attendance(user_id=user_id, date=p_date)
                db.session.add(att)
            
            # Update values
            att.status = status
            att.note = note
            att.is_regularized = True
            att.regularized_by = current_user.id
            att.reg_requested = False # Resolve any pending request
            
            if ci_time:
                try:
                    h, m = map(int, ci_time.split(':'))
                    att.check_in = datetime.combine(p_date, datetime.min.time().replace(hour=h, minute=m))
                except: pass
            else:
                att.check_in = None
                
            if co_time:
                try:
                    h, m = map(int, co_time.split(':'))
                    att.check_out = datetime.combine(p_date, datetime.min.time().replace(hour=h, minute=m))
                except: pass
            else:
                att.check_out = None
                
            db.session.commit()
            flash(f"Attendance for {att.user.username} on {p_date} has been updated/added.", "success")
            return redirect(url_for('attendance_manage'))

        att_id = request.form.get("attendance_id")
        att = Attendance.query.get_or_404(att_id)
        
        if action == "approve":
            att.status = att.reg_status
            att.note = f"Approved: {att.reg_reason}"
            att.reg_requested = False
            att.is_regularized = True
            
            # Create notification
            notif = Notification(
                user_id=att.user_id,
                title="Attendance Regularized ✅",
                message=f"Your regularization request for {att.date.strftime('%d %b')} was approved as '{att.status}'.",
                link=url_for('attendance')
            )
            db.session.add(notif)
            flash(f"Attendance for {att.user.username} approved.", "success")

        elif action == "approve_leave":
            att.status = "Holiday"
            att.note = att.note or "Leave Approved"
            
            # Create notification
            notif = Notification(
                user_id=att.user_id,
                title="Leave Approved ✅",
                message=f"Your leave request for {att.date.strftime('%d %b')} has been APPROVED.",
                link=url_for('attendance')
            )
            db.session.add(notif)
            flash(f"Leave request for {att.user.username} approved.", "success")
            
        elif action == "reject_leave":
            att.status = "Leave Rejected"
            
            # Create notification
            notif = Notification(
                user_id=att.user_id,
                title="Leave Rejected ❌",
                message=f"Your leave request for {att.date.strftime('%d %b')} has been REJECTED by Admin.",
                link=url_for('attendance')
            )
            db.session.add(notif)
            flash(f"Leave request for {att.user.username} rejected.", "warning")

        elif action == "reject_reg":
            att.reg_requested = False
            # Create notification
            notif = Notification(
                user_id=att.user_id,
                title="Regularization Rejected ❌",
                message=f"Your regularization request for {att.date.strftime('%d %b')} was rejected by Super Admin.",
                link=url_for('attendance')
            )
            db.session.add(notif)
            flash(f"Regularization request for {att.user.username} rejected.", "info")

        elif action == "manual":
            # Manual regularization
            att.status = request.form.get("status")
            att.note = request.form.get("note")
            
            # Update times if provided
            ci_time = request.form.get("check_in")
            co_time = request.form.get("check_out")
            
            if ci_time:
                h, m = map(int, ci_time.split(':'))
                att.check_in = datetime.combine(att.date, datetime.min.time().replace(hour=h, minute=m))
            else:
                att.check_in = None
                
            if co_time:
                h, m = map(int, co_time.split(':'))
                att.check_out = datetime.combine(att.date, datetime.min.time().replace(hour=h, minute=m))
            else:
                att.check_out = None

            att.reg_requested = False
            att.is_regularized = True
            
            # Create notification
            notif = Notification(
                user_id=att.user_id,
                title="Attendance Updated 📝",
                message=f"Admin manually updated your attendance for {att.date.strftime('%d %b')} to '{att.status}'.",
                link=url_for('attendance')
            )
            db.session.add(notif)
            flash(f"Attendance for {att.user.username} manually updated.", "success")
            
        elif action == "delete":
            username = att.user.username
            date_str = att.date.strftime('%d %b %Y')
            db.session.delete(att)
            db.session.commit()
            flash(f"Attendance record for {username} on {date_str} has been permanently deleted.", "warning")
            return redirect(url_for('attendance_manage'))
            
        att.regularized_by = current_user.id
        db.session.commit()
        if 'notifications' in (request.referrer or ''):
            return redirect(url_for('admin.notifications'))
        return redirect(url_for('attendance_manage'))

    # Advanced Filters
    user_id = request.args.get('user_id', type=int)
    date_str = request.args.get('date')
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)

    query = Attendance.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    if date_str:
        try:
            filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            query = query.filter(Attendance.date == filter_date)
        except:
            pass
    if month:
        query = query.filter(db.extract('month', Attendance.date) == month)
    if year:
        query = query.filter(db.extract('year', Attendance.date) == year)

    all_attendance = query.order_by(Attendance.date.desc()).all()
    pending_reg = Attendance.query.filter_by(reg_requested=True).all()
    pending_leaves = Attendance.query.filter_by(status='Leave Pending').all()
    all_users = User.query.filter_by(is_active=True).all()
    
    return render_template("admin/attendance_manage.html", 
                         all_attendance=all_attendance, 
                         pending_reg=pending_reg,
                         pending_leaves=pending_leaves,
                         all_users=all_users,
                         now=datetime.now(),
                         filters={
                             'user_id': user_id,
                             'date': date_str,
                             'month': month,
                             'year': year
                         })

# --- TSC Assist API ---
@app.route("/api/tsc-assist/query", methods=["POST"])
@login_required
def tsc_assist_query():
    data = request.json
    query_type = data.get("type")
    
    if current_user.role in ['admin', 'super_admin']:
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        if query_type == "stats_pending":
            count = Order.query.filter(Order.status.notin_(['Ready to Deliver', 'Delivered', 'Cancelled'])).count()
            return jsonify({"status": "success", "message": f"There are currently **{count}** pending orders in the system."})
        
        elif query_type == "stats_billed":
            # Sum of prices for orders picked up today (range-based for speed)
            revenue = db.session.query(db.func.sum(OrderItem.price - OrderItem.discount))\
                .join(Order).filter(Order.pickup_date >= today_start, Order.pickup_date <= today_end).scalar() or 0.0
            return jsonify({"status": "success", "message": f"Today's total billed amount is **₹{revenue:,.2f}**."})
            
        elif query_type == "stats_today_pending":
            count = Order.query.filter(Order.pickup_date >= today_start, Order.pickup_date <= today_end, 
                                     Order.status.notin_(['Ready to Deliver', 'Delivered'])).count()
            return jsonify({"status": "success", "message": f"You have **{count}** orders created today that are still pending."})

    # Search logic for everyone
    if query_type == "search":
        term = data.get("term")
        results = Order.query.filter(
            (Order.customer_name.ilike(f"%{term}%")) | 
            (Order.job_id.ilike(f"%{term}%")) | 
            (Order.mobile.ilike(f"%{term}%"))
        ).limit(5).all()
        
        if not results:
            return jsonify({"status": "success", "message": "No orders found matching that name or token."})
        
        msg = "I found these matching orders:\n"
        for o in results:
            msg += f"• **{o.job_id}**: {o.customer_name} ({o.status})\n"
        return jsonify({"status": "success", "message": msg})

    return jsonify({"status": "error", "message": "I'm sorry, I couldn't process that request."})

@app.route("/api/tsc-assist/submit-order", methods=["POST"])
@login_required
def tsc_assist_submit_order():
    # Simplified order creation from bot
    data = request.json
    try:
        last_order = Order.query.order_by(Order.id.desc()).first()
        if last_order and last_order.job_id:
            last_id = int(last_order.job_id.replace("TSC", ""))
            new_job_id = f"TSC{last_id+1:05d}"
        else:
            new_job_id = "TSC00001"

        today = datetime.now().date()
        drop_date = today + timedelta(days=3) # Default 3 days for chat-added orders

        order = Order(
            job_id=new_job_id,
            customer_name=data.get("name"),
            mobile=data.get("mobile"),
            place=data.get("place", "-"),
            pickup_date=today,
            drop_date=drop_date,
            status="Pending",
            created_at=datetime.now()
        )
        db.session.add(order)
        db.session.flush()

        item = OrderItem(
            order_id=order.id,
            product_name=data.get("product"),
            services=data.get("service"),
            price=float(data.get("price", 0)),
            discount=0,
            status="yts" # Yet To Start
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"status": "success", "job_id": new_job_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/api/tsc-assist/submit-expense", methods=["POST"])
@login_required
def tsc_assist_submit_expense():
    data = request.json
    try:
        expense = Expense(
            title=data.get("title") or data.get("category") or "Unspecified Expense",
            category=data.get("category") or "General",
            amount=float(data.get("amount") or 0),
            description=data.get("description", "Chatbot Entry"),
            added_by=current_user.id,
            status="pending"
        )
        db.session.add(expense)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/delete_holiday/<int:id>", methods=["POST"])
@login_required
@super_admin_required
def delete_holiday(id):
    holiday = Holiday.query.get_or_404(id)
    db.session.delete(holiday)
    db.session.commit()
    flash("Holiday removed from calendar.", "info")
    return redirect(url_for('calendar'))

@app.route("/delete-order/<int:order_id>", methods=["POST"])
@login_required
@super_admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    try:
        db.session.delete(order)
        db.session.commit()
        flash("Order deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting order: {str(e)}", "danger")
    return redirect(url_for("tsc_dashboard"))

@app.route("/bulk_delete_orders", methods=["POST"])
@login_required
@super_admin_required
def bulk_delete_orders():
    order_ids = request.form.getlist('order_ids')
    if not order_ids:
        flash("No orders selected for deletion.", "warning")
        return redirect(url_for("tsc_dashboard"))
    
    try:
        # Get orders to delete
        orders = Order.query.filter(Order.id.in_(order_ids)).all()
        count = len(orders)
        
        for order in orders:
            db.session.delete(order)
            
        db.session.commit()
        flash(f"Successfully deleted {count} orders.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error during bulk deletion: {str(e)}", "danger")
    
    return redirect(url_for("tsc_dashboard"))

# --- Dashboard Export Routes ---
@app.route("/export_dashboard_excel")
@login_required
@super_admin_required
def export_dashboard_excel():
    """Export TSC Dashboard data to Excel"""
    # Get all filter parameters from request args
    search = request.args.get("search", "")
    pickup_date_filter = request.args.get("pickup_date_filter", "")
    drop_date_filter = request.args.get("drop_date_filter", "")
    status_filter = request.args.get("status_filter", "")
    technician_filter = request.args.get("technician_filter", "")
    discount_filter = request.args.get("discount_filter", "")
    outsource_filter = request.args.get("outsource_filter", "")

    # Apply same filters as dashboard
    query = Order.query.options(db.joinedload(Order.items))

    if search:
        query = query.filter(
            (Order.customer_name.ilike(f"%{search}%")) |
            (Order.mobile.ilike(f"%{search}%")) |
            (Order.job_id.ilike(f"%{search}%"))
        )
    if pickup_date_filter:
        query = query.filter(db.func.date(Order.pickup_date) == pickup_date_filter)
    if drop_date_filter:
        query = query.filter(db.func.date(Order.drop_date) == drop_date_filter)
    if status_filter:
        query = query.filter(Order.status == status_filter)
    if technician_filter:
        query = query.join(Order.items).filter(
            (Order.technician.ilike(f"%{technician_filter}%")) |
            (OrderItem.technician.ilike(f"%{technician_filter}%"))
        ).distinct()
    if discount_filter:
        query = query.filter(Order.discount.ilike(f"%{discount_filter}%"))
    if outsource_filter:
        query = query.filter(Order.outsource == outsource_filter)

    orders = query.order_by(Order.job_id.asc(), Order.pickup_date.desc()).all()

    # Prepare data for Excel
    data = []
    for order in orders:
        # Get technician info
        if order.technician:
            technician = order.technician
        else:
            tech_list = []
            for item in order.items:
                if item.technician and item.technician not in tech_list:
                    tech_list.append(item.technician)
            technician = ', '.join(tech_list) if tech_list else '-'
        
        # Get services
        services_list = []
        for item in order.items:
            if item.services:
                for s in item.services.split(','):
                    svc = s.strip()
                    if svc and svc not in services_list:
                        services_list.append(svc)
        
        # Service Date Range for cleaner Excel
        start_date = order.service_date.strftime('%d-%m-%Y') if order.service_date else '-'
        finish_date = order.work_finish_date.strftime('%d-%m-%Y') if order.work_finish_date else '-'
        service_date = f"{start_date} -> {finish_date}" if order.service_date else '-'

        data.append({
            'Sl. No': len(data) + 1,
            'Job ID': order.job_id,
            'Token': order.token or '-',
            'Name': order.customer_name,
            'Pickup': order.pickup_date.strftime('%d-%m-%Y') if order.pickup_date else '-',
            'Service': ', '.join(services_list),
            'Service Date': service_date,
            'Drop': order.drop_date.strftime('%d-%m-%Y') if order.drop_date else '-',
            'Place': order.place or '-',
            'Status': order.status or '-',
            'Mobile': order.mobile or '-',
            'Product': order.product_name or '-',
            'Price': float(order.price or 0),
            'Payment Status': order.payment_status or '-',
            'Discount': order.discount or '0',
            'Outsource': order.outsource or '-',
            'Count': order.item_count or 0
        })

    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dashboard')
        workbook = writer.book
        worksheet = writer.sheets['Dashboard']
        
        # Get dimensions of the dataframe
        (max_row, max_col) = df.shape
        
        # Create a list of column headers
        column_settings = [{'header': column} for column in df.columns]
        
        # Add the Excel table with styling
        worksheet.add_table(0, 0, max_row, max_col - 1, {
            'columns': column_settings,
            'style': 'Table Style Medium 9'
        })
        
        # Format for centering content
        center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
        
        # Auto-adjust column widths based on content
        for i, col in enumerate(df.columns):
            # Calculate the max length of the column content
            column_len = df[col].astype(str).str.len().max()
            # Compare with header length
            column_len = max(column_len, len(col)) + 2
            # Limit reasonable max width
            column_len = min(column_len, 50)
            
            # Apply width and center formatting to the column
            worksheet.set_column(i, i, column_len, center_format)

    output.seek(0)
    
    filename = f"TSC_Dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route("/export_dashboard_pdf")
@login_required
@super_admin_required
def export_dashboard_pdf():
    """Export TSC Dashboard data to PDF"""
    # Get all filter parameters from request args
    search = request.args.get("search", "")
    pickup_date_filter = request.args.get("pickup_date_filter", "")
    drop_date_filter = request.args.get("drop_date_filter", "")
    status_filter = request.args.get("status_filter", "")
    technician_filter = request.args.get("technician_filter", "")
    discount_filter = request.args.get("discount_filter", "")
    outsource_filter = request.args.get("outsource_filter", "")

    # Apply same filters as dashboard
    query = Order.query.options(db.joinedload(Order.items))

    if search:
        query = query.filter(
            (Order.customer_name.ilike(f"%{search}%")) |
            (Order.mobile.ilike(f"%{search}%")) |
            (Order.job_id.ilike(f"%{search}%"))
        )
    if pickup_date_filter:
        query = query.filter(db.func.date(Order.pickup_date) == pickup_date_filter)
    if drop_date_filter:
        query = query.filter(db.func.date(Order.drop_date) == drop_date_filter)
    if status_filter:
        query = query.filter(Order.status == status_filter)
    if technician_filter:
        query = query.join(Order.items).filter(
            (Order.technician.ilike(f"%{technician_filter}%")) |
            (OrderItem.technician.ilike(f"%{technician_filter}%"))
        ).distinct()
    if discount_filter:
        query = query.filter(Order.discount.ilike(f"%{discount_filter}%"))
    if outsource_filter:
        query = query.filter(Order.outsource == outsource_filter)

    orders = query.order_by(Order.job_id.asc(), Order.pickup_date.desc()).all()

    output = io.BytesIO()

    def add_watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 55)
        canvas.setFillGray(0.85)
        canvas.translate(300, 400)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "The Shoe Clinic")
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    
    # Define a custom style for all table content to ensure 100% font uniformity
    table_cell_style = styles['Normal'].clone('TableCell')
    table_cell_style.fontName = 'Helvetica'
    table_cell_style.fontSize = 6
    table_cell_style.leading = 7
    table_cell_style.alignment = 1 # Center
    
    elements = []
    
    # Title (Using uniform font style)
    title_style = styles['Normal'].clone('ReportTitle')
    title_style.fontName = 'Helvetica'
    title_style.fontSize = 11
    elements.append(Paragraph("TSC Dashboard Report", title_style))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}", title_style))
    elements.append(Spacer(1, 10))
    
    # Table Header (17 Columns exactly per user request)
    data = [['Sl. No', 'Job ID', 'Token', 'Name', 'Pickup', 'Service', 'Service Date', 'Drop', 'Place', 'Status', 'Mobile', 'Product', 'Price', 'Payment Status', 'Discount', 'Outsource', 'Count']]
    
    total_price = 0
    for i, order in enumerate(orders, 1):
        # Technician info for Name column (No formatting as per user request for 'same fond')
        tech_names = []
        if order.technician: tech_names.append(order.technician)
        for itm in order.items:
            if itm.technician and itm.technician not in tech_names: tech_names.append(itm.technician)
            if itm.service_assignments:
                try: 
                    import json
                    assignments = json.loads(itm.service_assignments)
                    for _, t in assignments.items():
                        if t and t not in tech_names: tech_names.append(t)
                except: pass
        technician = ', '.join(tech_names) if tech_names else '-'
        
        # Services
        services_list = []
        for item in order.items:
            if item.services:
                for s in item.services.split(','):
                    svc = s.strip()
                    if svc and svc not in services_list: services_list.append(svc)
        service_str = ', '.join(services_list)

        # Service Date Range
        start = order.service_date.strftime('%d-%m') if order.service_date else '-'
        finish = order.work_finish_date.strftime('%d-%m') if order.work_finish_date else '-'
        service_date = f"{start}->{finish}" if order.service_date else '-'

        price = float(order.price or 0)
        
        # Name cell content with Technician integrated but NO bold/red/separate size
        name_content = f"{order.customer_name or '-'}<br/>TECH: {technician}"

        data.append([
            str(i),
            order.job_id or '-',
            order.token or '-',
            Paragraph(name_content, table_cell_style),
            order.pickup_date.strftime('%d-%m') if order.pickup_date else '-',
            Paragraph(service_str[:100], table_cell_style),
            service_date,
            order.drop_date.strftime('%d-%m') if order.drop_date else '-',
            Paragraph(order.place or '-', table_cell_style),
            (order.status or '-')[:12],
            (order.mobile or '-')[-10:],
            Paragraph(order.product_name or '-', table_cell_style),
            f"{price:.0f}",
            Paragraph(order.payment_status or '-', table_cell_style),
            str(order.discount or '0'),
            (order.outsource or '-')[:3],
            str(order.item_count or 0)
        ])
        total_price += price
    
    # Add Total Row
    data.append(['', '', '', '', '', '', '', '', '', '', '', '', f"{total_price:.0f}", '', '', '', ''])
    
    # Adjusted column widths for landscape A4 (approx 800 width)
    # Increased 'Place' width to prevent kuttichal truncation/wrapping issues
    widths = [25, 45, 30, 85, 40, 90, 70, 40, 50, 40, 50, 45, 40, 60, 35, 30, 25] 
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    
    filename = f"TSC_Dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')


# --- Report Export Routes ---

@app.route("/export_report/<report_type>/<report_format>")
@login_required
@super_admin_required
def export_report(report_type, report_format):
    """Generic route to export any report to Excel or PDF"""
    try:
        data = None
        filename_prefix = f"TSC_{report_type.capitalize()}_Report"
        
        # 1. Fetch Report Data
        if report_type == 'daily':
            date_str = request.args.get('date')
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
            data = get_daily_report(selected_date)
            filename_prefix += f"_{selected_date.strftime('%Y%m%d')}"
            
        elif report_type == 'weekly':
            date_str = request.args.get('date')
            week_start = None
            if date_str:
                d = datetime.strptime(date_str, '%Y-%m-%d').date()
                week_start = d - timedelta(days=d.weekday())
            data = get_weekly_report(week_start)
            filename_prefix += f"_{data.get('week_start').strftime('%Y%m%d') if data.get('week_start') else 'W'}_to_{data.get('week_end').strftime('%Y%m%d') if data.get('week_end') else 'E'}"
            
        elif report_type == 'monthly':
            year = request.args.get('year', datetime.now().year, type=int)
            month = request.args.get('month', datetime.now().month, type=int)
            data = get_monthly_report(year, month)
            filename_prefix += f"_{year}{month:02d}"
            
        elif report_type == 'yearly':
            year = request.args.get('year', datetime.now().year, type=int)
            data = get_yearly_report(year)
            filename_prefix += f"_{year}"
            
        elif report_type in ['financial_monthly', 'financial_yearly']:
            year = request.args.get('year', datetime.now().year, type=int)
            month = request.args.get('month', datetime.now().month, type=int)
            if 'monthly' in report_type:
                data = get_monthly_report_legacy(year, month)
                filename_prefix = f"TSC_Financial_Monthly_{year}{month:02d}"
            else:
                data = get_yearly_report_legacy(year)
                filename_prefix = f"TSC_Financial_Yearly_{year}"

        if not data or 'error' in data:
            flash("Error fetching report data for export.", "danger")
            return redirect(request.referrer or url_for('home'))

        # 2. Export to Requested Format
        if report_format == 'excel':
            return export_report_excel(data, report_type, filename_prefix)
        elif report_format == 'pdf':
            return export_report_pdf(data, report_type, filename_prefix)
        else:
            flash("Invalid export format requested.", "danger")
            return redirect(request.referrer or url_for('home'))

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        flash(f"Export failed: {str(e)}", "danger")
        return redirect(request.referrer or url_for('home'))

def export_report_excel(data, report_type, filename_prefix):
    """Internal helper to generate Excel for reports"""
    orders = data.get('orders', [])
    export_data = []
    
    for i, order in enumerate(orders, 1):
        # Extract services
        services = []
        for item in order.items:
            if item.services:
                services.extend([s.strip() for s in item.services.split(',') if s.strip()])
        
        export_data.append({
            'Sl. No': i,
            'Job ID': order.job_id,
            'Customer': order.customer_name,
            'Pickup': order.pickup_date.strftime('%d-%m-%Y') if order.pickup_date else '-',
            'Drop': order.drop_date.strftime('%d-%m-%Y') if order.drop_date else '-',
            'Services': ', '.join(list(set(services))),
            'Status': order.status or '-',
            'Mobile': order.mobile or '-',
            'Amount': float(order.price or 0),
            'Discount': order.discount or '0'
        })

    df = pd.DataFrame(export_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        sheet_name = report_type[:31] # Excel limit
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = writer.book
        worksheet = writer.sheets[sheet_name]
        
        # Style the header and columns
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 15)

    output.seek(0)
    filename = f"{filename_prefix}_{datetime.now().strftime('%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

def export_report_pdf(data, report_type, filename_prefix):
    """Internal helper to generate PDF for reports with Summary"""
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_text = f"{data.get('type', report_type.capitalize())} Report: {data.get('title', '')}"
    elements.append(Paragraph(f"<b>{title_text}</b>", styles['Title']))
    elements.append(Spacer(1, 12))

    # Executive Summary Table
    summary_data = [
        ['Metric', 'Value', 'Metric', 'Value'],
        ['Total Orders', str(data.get('total_orders', 0)), 'Billed Orders', str(data.get('billed_count', 0))],
        ['Expected Revenue', f"INR {data.get('total_revenue', 0):.2f}", 'Billed Revenue', f"INR {data.get('billed_revenue', 0):.2f}"],
        ['Total Expenses', f"INR {data.get('total_expenses', 0):.2f}", 'Net Profit', f"INR {data.get('net_profit', 0):.2f}"]
    ]
    
    s_table = Table(summary_data, colWidths=[150, 150, 150, 150])
    s_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('BACKGROUND', (2,0), (2,-1), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(s_table)
    elements.append(Spacer(1, 20))

    # Orders Table
    orders = data.get('orders', [])
    if orders:
        elements.append(Paragraph("<b>Order Details</b>", styles['Heading3']))
        order_header = ['Job ID', 'Customer', 'Pickup', 'Drop', 'Mobile', 'Status', 'Amount']
        order_rows = [order_header]
        
        for o in orders:
            order_rows.append([
                o.job_id,
                o.customer_name[:20] if o.customer_name else '-',
                o.pickup_date.strftime('%d-%b') if o.pickup_date else '-',
                o.drop_date.strftime('%d-%b') if o.drop_date else '-',
                o.mobile or '-',
                o.status or '-',
                f"{float(o.price or 0):.2f}"
            ])
            
        o_table = Table(order_rows, repeatRows=1)
        o_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.darkgrey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ]))
        elements.append(o_table)
    
    def watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 60)
        canvas.setFillGray(0.9)
        canvas.translate(400, 300)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "The Shoe Clinic")
        canvas.restoreState()

    doc.build(elements, onFirstPage=watermark, onLaterPages=watermark)
    output.seek(0)
    filename = f"{filename_prefix}_{datetime.now().strftime('%H%M%S')}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route("/request_report_export", methods=["POST"])
@login_required
@admin_required
def request_report_export():
    """Admin users can request an export from Super Admin"""
    req_data = request.json
    report_name = req_data.get("report_name")
    report_format = req_data.get("format")
    details = req_data.get("details", "")
    
    super_admin = User.query.filter_by(role='super_admin').first()
    if super_admin:
        notif = Notification(
            user_id=super_admin.id,
            title="Export Request 📥",
            message=f"<b>{current_user.username}</b> requested {report_format} export for: {report_name}. {details}",
            link=url_for('report_daily')
        )
        db.session.add(notif)
        db.session.commit()
        return jsonify({"status": "success", "message": "📥 Export request sent to Super Admin."})
    
    return jsonify({"status": "error", "message": "Super Admin not found."})

# Razorpay Client
RAZORPAY_KEY_ID = "rzp_test_YourKeyID" # Replace with user provided key
RAZORPAY_KEY_SECRET = "YourKeySecret" # Replace with user provided secret
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# --- Utils ---
if __name__ == "__main__":
    print("\n" + "="*50)
    print("DEBUG: Server is starting from E:\\app_v02")
    print("DEBUG: Auto-Reload (Debug Mode) is ENABLED")
    print("="*50 + "\n")
    with app.app_context():
        db.create_all()
    # Use PORT from environment (default to 5000 for local)
    port = int(os.environ.get("PORT", 5000))
    # Enable Debug Mode for automatic reloading
    app.run(debug=True, host='0.0.0.0', port=port)
# --- Payment Gateway Routes (v02) ---

@app.route("/create_payment/<int:order_id>", methods=["POST"])
@login_required
def create_payment(order_id):
    from models import Order, PaymentTransaction
    order = Order.query.get_or_4_4(order_id)
    
    if not order.price or order.price <= 0:
        return jsonify({"status": "error", "message": "Invalid order price"}), 400

    amount = int(float(order.price) * 100)  # Razorpay expects amount in paise
    
    try:
        data = {
            "amount": amount,
            "currency": "INR",
            "receipt": f"receipt_{order.job_id}",
            "payment_capture": 1 # Auto capture
        }
        
        razorpay_order = razorpay_client.order.create(data=data)
        
        # Log transaction
        tx = PaymentTransaction(
            order_id=order.id,
            razorpay_order_id=razorpay_order['id'],
            amount=float(order.price),
            status='created'
        )
        db.session.add(tx)
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "razorpay_order_id": razorpay_order['id'],
            "razorpay_key_id": RAZORPAY_KEY_ID,
            "amount": amount,
            "currency": "INR",
            "order_name": "The Shoe Clinic",
            "order_description": f"Payment for Job ID: {order.job_id}",
            "prefill_name": order.customer_name,
            "prefill_contact": order.mobile
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    from models import Order, PaymentTransaction
    data = request.json
    
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")
    
    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }
    
    try:
        # Verify the signature
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        # Update transaction
        tx = PaymentTransaction.query.filter_by(razorpay_order_id=razorpay_order_id).first()
        if tx:
            tx.razorpay_payment_id = razorpay_payment_id
            tx.razorpay_signature = razorpay_signature
            tx.status = 'captured'
            
            # Update Order
            order = Order.query.get(tx.order_id)
            if order:
                order.payment_status = 'Paid'
                order.payment_mode = 'Online'
                
            db.session.commit()
            return jsonify({"status": "success", "message": "Payment verified successfully"})
        else:
            return jsonify({"status": "error", "message": "Transaction record not found"}), 404
            
    except Exception as e:
        # Signature verification failed or other error
        tx = PaymentTransaction.query.filter_by(razorpay_order_id=razorpay_order_id).first()
        if tx:
            tx.status = 'failed'
            tx.error_description = str(e)
            db.session.commit()
            
        return jsonify({"status": "error", "message": "Payment verification failed"}), 400
