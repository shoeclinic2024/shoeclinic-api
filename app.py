from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from datetime import datetime, timedelta
from database import db
from admin import admin_bp
from flask_migrate import Migrate
from otp_service import otp_service
import os
import io
import pandas as pd
from reportlab.lib.pagesizes import A4
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
from models import User, Order, OrderItem, Announcement, Attendance, Holiday, Expense, LoginAttempt

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
    elif s in ["done", "completed", "finished"]:
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
        pending_access = User.query.filter_by(customer_view_requested=True).count()
        pending_attendance = Attendance.query.filter_by(reg_requested=True).count()
        return dict(pending_approvals_count=pending_users + pending_expenses + pending_access + pending_attendance)
    return dict(pending_approvals_count=0)

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
            flash("Access denied. Owner privileges required.", "danger")
            return redirect(request.referrer or url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- Report Helper Functions ---
def get_daily_report(date=None):
    """Get report for a specific date"""
    try:
        if date is None:
            date = datetime.now().date()
        
        start_of_day = datetime.combine(date, datetime.min.time())
        end_of_day = datetime.combine(date, datetime.max.time())

        # Revenue from Orders (Direct filter in SQL)
        orders = Order.query.filter(Order.pickup_date >= start_of_day, Order.pickup_date <= end_of_day).all()
        
        # Only counting APPROVED expenses (Direct filter in SQL)
        expenses = Expense.query.filter(Expense.status == 'approved', Expense.expense_date == date).all()
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        completed = Order.query.filter(Order.pickup_date >= start_of_day, Order.pickup_date <= end_of_day, Order.status.ilike('%done%')).count()
        
        return {
            'date': date,
            'title': date.strftime('%d %B, %Y'),
            'type': 'Daily',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': completed,
            'pending': len(orders) - completed,
            'orders': orders,
            'expenses': expenses
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
        
        all_orders = Order.query.all()
        orders = [o for o in all_orders if o.pickup_date and week_start <= o.pickup_date.date() <= week_end]
        
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if week_start <= e.expense_date <= week_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        completed = len([o for o in orders if o.status and 'done' in o.status.lower()])
        
        return {
            'week_start': week_start,
            'week_end': week_end,
            'title': f"{week_start.strftime('%d %b')} - {week_end.strftime('%d %b, %Y')}",
            'type': 'Weekly',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': completed,
            'pending': len(orders) - completed,
            'orders': orders,
            'expenses': expenses
        }
    except Exception as e:
        return {'error': str(e)}

def get_monthly_report(year=None, month=None):
    """Get report for a specific month"""
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
        
        all_orders = Order.query.all()
        orders = [o for o in all_orders if o.pickup_date and month_start <= o.pickup_date.date() <= month_end]
        
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if month_start <= e.expense_date <= month_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        completed = len([o for o in orders if o.status and 'done' in o.status.lower()])
        
        return {
            'month': month,
            'year': year,
            'title': datetime(year, month, 1).strftime('%B %Y'),
            'type': 'Monthly',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': completed,
            'pending': len(orders) - completed,
            'orders': orders,
            'expenses': expenses
        }
    except Exception as e:
        return {'error': str(e)}

def get_yearly_report(year=None):
    """Get report for a specific year"""
    try:
        from models import Order, Expense
        if year is None:
            year = datetime.now().year
        
        year_start = datetime(year, 1, 1).date()
        year_end = datetime(year, 12, 31).date()
        
        all_orders = Order.query.all()
        orders = [o for o in all_orders if o.pickup_date and year_start <= o.pickup_date.date() <= year_end]
        
        all_expenses = Expense.query.filter_by(status='approved').all()
        expenses = [e for e in all_expenses if year_start <= e.expense_date <= year_end]
        
        total_revenue = sum([float(o.price or 0) for o in orders])
        total_expenses = sum([float(e.amount or 0) for e in expenses])
        completed = len([o for o in orders if o.status and 'done' in o.status.lower()])
        
        return {
            'year': year,
            'title': str(year),
            'type': 'Yearly',
            'total_orders': len(orders),
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_profit': total_revenue - total_expenses,
            'completed': completed,
            'pending': len(orders) - completed,
            'orders': orders,
            'expenses': expenses
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
    
    # 6. Check if 2FA is enabled
    if user.two_factor_enabled:
        # Store user ID in session for 2FA verification
        session['pending_2fa_user_id'] = user.id
        session['pending_2fa_ip'] = ip_address
        flash("🔐 Enter code from Google Authenticator", "info")
        return redirect(url_for("verify_2fa_login"))
    
    # 7. Login successful!
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
    """Step 1: Request password reset with phone number"""
    if request.method == "POST":
        username = request.form.get("username")
        phone_number = request.form.get("phone_number")
        
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash("Username not found.", "danger")
            return redirect(url_for("forgot_password"))
        
        # Generate OTP
        otp_code = otp_service.generate_otp()
        otp_expiry = otp_service.get_otp_expiry_time()
        
        # Save OTP to user
        user.otp_code = otp_code
        user.otp_expiry = otp_expiry
        user.otp_attempts = 0
        user.phone_number = phone_number
        db.session.commit()
        
        # Send OTP via SMS
        success, message = otp_service.send_otp_sms(phone_number, otp_code)
        
        if success:
            session['reset_username'] = username
            flash("OTP sent to your phone number.", "success")
            return redirect(url_for("verify_otp"))
        else:
            flash(f"Failed to send OTP: {message}", "danger")
            return redirect(url_for("forgot_password"))
    
    return render_template("forgot_password.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    """Step 2: Verify OTP sent to phone"""
    if 'reset_username' not in session:
        flash("Invalid request. Please start password reset again.", "warning")
        return redirect(url_for("forgot_password"))
    
    username = session.get('reset_username')
    user = User.query.filter_by(username=username).first()
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        otp_input = request.form.get("otp_code")
        
        # Check if OTP attempts exceeded
        if not otp_service.can_attempt_otp(user.otp_attempts):
            flash("Too many OTP attempts. Please try again later.", "danger")
            return redirect(url_for("forgot_password"))
        
        # Check if OTP expired
        if not otp_service.is_otp_valid(user.otp_expiry):
            flash("OTP has expired. Please request a new one.", "danger")
            return redirect(url_for("forgot_password"))
        
        # Verify OTP
        if user.otp_code == otp_input:
            session['otp_verified'] = True
            flash("OTP verified! Now set your new password.", "success")
            return redirect(url_for("reset_password_otp"))
        else:
            user.otp_attempts += 1
            db.session.commit()
            attempts_left = 3 - user.otp_attempts
            flash(f"Invalid OTP. {attempts_left} attempts left.", "danger")
            return redirect(url_for("verify_otp"))
    
    return render_template("verify_otp.html", username=username)

@app.route("/reset-password-otp", methods=["GET", "POST"])
def reset_password_otp():
    """Step 3: Reset password after OTP verification"""
    if not session.get('otp_verified'):
        flash("Please verify OTP first.", "warning")
        return redirect(url_for("verify_otp"))
    
    username = session.get('reset_username')
    user = User.query.filter_by(username=username).first()
    
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        if not new_password or not confirm_password:
            flash("Please fill in all fields.", "warning")
            return redirect(url_for("reset_password_otp"))
        
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("reset_password_otp"))
        
        if len(new_password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return redirect(url_for("reset_password_otp"))
        
        # Update password
        user.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
        user.otp_code = None
        user.otp_expiry = None
        user.otp_attempts = 0
        db.session.commit()
        
        # Clear session
        session.pop('reset_username', None)
        session.pop('otp_verified', None)
        
        flash("Password reset successful! Please login with your new password.", "success")
        return redirect(url_for("login_page"))
    
    return render_template("reset_password_otp.html", username=username)

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
    todays_delivery_count = Order.query.filter(
        db.func.date(Order.drop_date) == today
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
                         todays_delivery_count=todays_delivery_count,
                         announcements=announcements,
                         upcoming_holidays=upcoming_holidays,
                         user=current_user)

# --- Dashboard Route ---
@app.route("/tsc_dashboard")
@login_required
@admin_required
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
                pickup_date=datetime.strptime(request.form["pickup_date"], "%Y-%m-%d"),
                service_note=request.form.get("service_note"),
                technician=request.form.get("technician"),
                created_at=datetime.now()
            )
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
        order.technician = request.form.get("technician")
        order.job_id = request.form.get("job_id")
        order.customer_name = request.form.get("customer_name")
        order.pickup_date = datetime.strptime(request.form.get("pickup_date"), "%Y-%m-%d") if request.form.get("pickup_date") else None
        order.service_date = datetime.strptime(request.form.get("service_date"), "%Y-%m-%d") if request.form.get("service_date") else None
        order.drop_date = datetime.strptime(request.form.get("drop_date"), "%Y-%m-%d") if request.form.get("drop_date") else None
        order.place = request.form.get("place")
        order.service_note = request.form.get("service_note")
        order.status = request.form.get("status")

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
            
            # Simple Logic: If all services are 'done', set item status to 'done'
            all_done = True
            if item.services:
                for s in item.services.split(','):
                    name = s.strip()
                    if statuses.get(name) != 'done':
                        all_done = False
                        break
            
            if all_done:
                item.status = 'done'
                # Check parent order: if all items are done, set order status to 'done' or 'ready to deliver'
                order = item.order
                order_done = True
                for itm in order.items:
                    if itm.status != 'done':
                        order_done = False
                        break
                if order_done:
                    order.status = 'ready to deliver'
            else:
                item.status = 'wip'
                item.order.status = 'wip'
                
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
    # Fetch individual tasks (OrderItem) assigned to current user (either as lead or for specific services)
    search_term = f'%"{current_user.username}"%'
    assigned_items = OrderItem.query.filter(
        (OrderItem.technician == current_user.username) | 
        (OrderItem.service_assignments.ilike(search_term))
    ).order_by(OrderItem.created_at.desc()).all()
    
    # Fetch whole orders assigned to current user
    assigned_orders = Order.query.filter_by(technician=current_user.username).all()
    
    # Filter out orders that are already done
    active_assigned_orders = [o for o in assigned_orders if o.status != 'done']
    
    return render_template("my_works.html", items=assigned_items, orders=active_assigned_orders)

# Reports
@app.route("/report_daily")
@login_required
@admin_required
def report_daily():
    data = get_daily_report()
    return render_template("reports.html", **data)

@app.route("/report_weekly")
@login_required
@admin_required
def report_weekly():
    data = get_weekly_report()
    return render_template("reports.html", **data)

@app.route("/report_monthly")
@login_required
@admin_required
def report_monthly():
    data = get_monthly_report()
    return render_template("reports.html", **data)

@app.route("/report_yearly")
@login_required
@admin_required
def report_yearly():
    data = get_yearly_report()
    return render_template("reports.html", **data)

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
    order = Order.query.get_or_404(order_id)
    return render_template("view_order_bill.html", order=order)

@app.route("/pickup_confirmation/<int:order_id>")
@login_required
@admin_required
def pickup_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Pre-generate share message
    msg = f"--- PICKUP CONFIRMATION ---\n"
    msg += f"Job ID: {order.job_id}\n"
    msg += f"Expected Delivery: {order.drop_date.strftime('%d-%m-%Y') if order.drop_date else 'TBA'}\n\n"
    
    # Add Itemized details
    for i, item in enumerate(order.items, 1):
        services_str = f" ({item.services})" if item.services else ""
        msg += f"{i}. {item.product_name or 'Item'}{services_str}\n"
        if item.defects:
            msg += f"   - Condition: {item.defects}\n"
            
    msg += f"\nCustomer: {order.customer_name}\n"
    msg += f"Total Items: {order.item_count}\n"
    msg += f"Estimate Total: ₹{order.price}\n"
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
            if not today_attendance:
                today_attendance = Attendance(user_id=current_user.id, date=today, status="Holiday", note=request.form.get("note"))
                db.session.add(today_attendance)
                flash("Holiday status marked for today.", "info")
            else:
                flash("Attendance already recorded for today.", "warning")
        
        elif action == "request_reg":
            att_id = request.form.get("attendance_id")
            att = Attendance.query.get_or_404(att_id)
            if att.user_id != current_user.id:
                flash("Unauthorized request.", "danger")
            else:
                att.reg_requested = True
                att.reg_status = request.form.get("reg_status")
                att.reg_reason = request.form.get("reg_reason")
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
        att_id = request.form.get("attendance_id")
        action = request.form.get("action") # approve or manual
        
        att = Attendance.query.get_or_404(att_id)
        
        if action == "approve":
            att.status = att.reg_status
            att.note = f"Approved: {att.reg_reason}"
            att.reg_requested = False
            att.is_regularized = True
        else:
            # Manual regularization
            att.status = request.form.get("status")
            att.note = request.form.get("note")
            att.reg_requested = False
            att.is_regularized = True
            
        att.regularized_by = current_user.id
        db.session.commit()
        flash(f"Attendance for {att.user.username} has been regularized.", "success")
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
    all_users = User.query.filter_by(is_active=True).all()
    
    return render_template("admin/attendance_manage.html", 
                         all_attendance=all_attendance, 
                         pending_reg=pending_reg,
                         all_users=all_users,
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
@admin_required
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
        services = []
        for item in order.items:
            if item.services:
                for s in item.services.split(','):
                    svc = s.strip()
                    if svc and svc not in services:
                        services.append(svc)
        
        data.append({
            'Job ID': order.job_id,
            'Customer Name': order.customer_name,
            'Pickup Date': order.pickup_date.strftime('%d-%b-%Y') if order.pickup_date else '-',
            'Service Date': order.service_date.strftime('%d-%b-%Y') if order.service_date else '-',
            'Drop Date': order.drop_date.strftime('%d-%b-%Y') if order.drop_date else '-',
            'Place': order.place or '-',
            'Services': ', '.join(services),
            'Service Note': order.service_note or '-',
            'Status': order.status or '-',
            'Mobile': order.mobile or '-',
            'Product': order.product_name or '-',
            'Token': order.token or '-',
            'Price': float(order.price or 0),
            'Payment Mode': order.payment_mode or '-',
            'Payment Status': order.payment_status or '-',
            'Discount': order.discount or '0',
            'Outsource': order.outsource or '-',
            'Item Count': order.item_count or 0,
            'Dispatch': getattr(order, 'dispatch', '-') or '-',
            'Technician': technician
        })

    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dashboard')
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

    doc = SimpleDocTemplate(output, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    elements.append(Paragraph("TSC Dashboard Report", styles['Title']))
    elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Table Header
    data = [['Job ID', 'Customer', 'Mobile', 'Pickup', 'Drop', 'Status', 'Technician', 'Price']]
    
    total_price = 0
    for order in orders:
        # Get technician info
        if order.technician:
            technician = order.technician[:15]
        else:
            tech_list = []
            for item in order.items:
                if item.technician and item.technician not in tech_list:
                    tech_list.append(item.technician)
            technician = (', '.join(tech_list)[:15]) if tech_list else '-'
        
        price = float(order.price or 0)
        data.append([
            order.job_id or '-',
            (order.customer_name[:15]) if order.customer_name else '-',
            (order.mobile or '-')[:12],
            order.pickup_date.strftime('%d-%b') if order.pickup_date else '-',
            order.drop_date.strftime('%d-%b') if order.drop_date else '-',
            (order.status[:10]) if order.status else '-',
            technician,
            f"₹{price:.2f}"
        ])
        total_price += price
    
    # Add Total Row
    data.append(['', '', '', '', '', '', 'TOTAL', f"₹{total_price:.2f}"])
    
    # Create Table
    t = Table(data, colWidths=[60, 80, 70, 50, 50, 60, 80, 60])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(t)
    doc.build(elements, onFirstPage=add_watermark, onLaterPages=add_watermark)
    output.seek(0)
    
    filename = f"TSC_Dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/pdf')


# --- Run App ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    # Use PORT from environment (default to 5000 for local)
    port = int(os.environ.get("PORT", 5000))
    # In production, debug should be False
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(debug=debug, host='0.0.0.0', port=port)
