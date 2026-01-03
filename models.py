from database import db
from flask_login import UserMixin
from datetime import datetime

# --- User Model ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="employee")  # roles: super_admin, admin, employee
    is_active = db.Column(db.Boolean, nullable=False, default=False)  # requires approval
    otp_code = db.Column(db.String(10), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    otp_attempts = db.Column(db.Integer, default=0)
    can_view_customers = db.Column(db.Boolean, default=False)
    customer_view_requested = db.Column(db.Boolean, default=False)
    can_export_customers = db.Column(db.Boolean, default=False)
    customer_access_expiry = db.Column(db.DateTime, nullable=True)
    
    # --- Performance Monitor Access (v02) ---
    can_view_performance = db.Column(db.Boolean, default=False)
    performance_view_requested = db.Column(db.Boolean, default=False)
    performance_access_expiry = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # --- Security Fields (v02) ---
    # Login tracking
    failed_login_attempts = db.Column(db.Integer, default=0)
    last_failed_login = db.Column(db.DateTime, nullable=True)
    account_locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)
    
    # Two-Factor Authentication (Google Authenticator)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)  # TOTP secret for Google Authenticator
    
    # Session management
    session_token = db.Column(db.String(100), nullable=True)
    last_activity = db.Column(db.DateTime, nullable=True)
    
    # UI Flags
    # first_login_seen = db.Column(db.Boolean, default=False)

# --- Order Model ---
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(20), unique=True)
    customer_name = db.Column(db.String(100))
    technician = db.Column(db.String(100))
    drop_date = db.Column(db.DateTime)
    pickup_date = db.Column(db.DateTime, default=datetime.now)
    service_date = db.Column(db.DateTime, nullable=True)
    place = db.Column(db.String(100))
    service_note = db.Column(db.String(200))
    status = db.Column(db.String(50))
    mobile = db.Column(db.String(20))
    product_name = db.Column(db.String(100))
    token = db.Column(db.String(50))
    price = db.Column(db.Float)
    payment_mode = db.Column(db.String(50))
    payment_status = db.Column(db.String(50))
    discount = db.Column(db.String(50))
    outsource = db.Column(db.String(100))
    # vendor_amount = db.Column(db.Float)
    item_count = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.now)
    work_finish_date = db.Column(db.DateTime, nullable=True) # New column
    actual_delivery_date = db.Column(db.DateTime, nullable=True)
    assignment_start_date = db.Column(db.DateTime, nullable=True) # When assignment becomes active

    items = db.relationship('OrderItem', backref='order', lazy='joined', cascade='all, delete-orphan')

# --- OrderItem Model ---
class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    product_name = db.Column(db.String(100))
    services = db.Column(db.String(200))
    price = db.Column(db.Float)
    discount = db.Column(db.Float)
    technician = db.Column(db.String(100))
    # Stores a JSON mapping of service name to technician name
    service_assignments = db.Column(db.Text) 
    # Stores a JSON mapping of service name to status (yts, wip, done, etc.)
    service_statuses = db.Column(db.Text)
    status = db.Column(db.String(50), default='yts')
    defects = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now)

# --- Expense Model ---
class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    real_amount = db.Column(db.Float, nullable=True, default=0.0)
    category = db.Column(db.String(50), nullable=False)
    expense_date = db.Column(db.Date, nullable=False, default=datetime.now)
    description = db.Column(db.String(255))
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending, approved
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Request tracking for non-super admins
    #     request_type = db.Column(db.String(20), default='none') # none, delete, edit
    #     request_reason = db.Column(db.String(255), nullable=True)
    #     request_data = db.Column(db.Text, nullable=True) # JSON literal for proposed edits
    
    @property
    def get_request_data(self):
        import json
        if self.request_data:
            try:
                return json.loads(self.request_data)
            except:
                return {}
        return {}

# --- Cash Deposit Model ---
class CashDeposit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    deposit_date = db.Column(db.Date, nullable=False, default=datetime.now)
    reference = db.Column(db.String(100)) # e.g. Bank Ref ID or "Handover"
    notes = db.Column(db.String(255))
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Request tracking for non-super admins
    #     request_type = db.Column(db.String(20), default='none') # none, delete, edit
    #     request_reason = db.Column(db.String(255), nullable=True)
    #     request_data = db.Column(db.Text, nullable=True) # JSON literal for proposed edits
    
    @property
    def get_request_data(self):
        import json
        if self.request_data:
            try:
                return json.loads(self.request_data)
            except:
                return {}
        return {}
    
    creator = db.relationship('User', foreign_keys=[added_by])

# --- Announcement Model ---
class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    target_role = db.Column(db.String(20), default="all")  # all, admin, employee
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    expiry_date = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    creator = db.relationship('User', foreign_keys=[created_by])
    target_user = db.relationship('User', foreign_keys=[target_user_id])

# --- Attendance Model ---
class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.now)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="Present")  # Present, Absent, Half-Day, Holiday
    note = db.Column(db.String(200), nullable=True)
    
    # Regularization Fields
    reg_requested = db.Column(db.Boolean, default=False)
    reg_status = db.Column(db.String(20)) # The status they want (e.g. Present)
    reg_reason = db.Column(db.String(200)) # Why they are requesting it
    
    is_regularized = db.Column(db.Boolean, default=False)
    regularized_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('attendances', cascade='all, delete-orphan'))
    regularizer = db.relationship('User', foreign_keys=[regularized_by])

# --- Holiday Model ---
class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    link = db.Column(db.String(200), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', cascade='all, delete-orphan'))

# --- Login Attempt Model (v02 - Security) ---
class LoginAttempt(db.Model):
    """Track all login attempts for security monitoring"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(255))
    success = db.Column(db.Boolean, default=False, index=True)
    failure_reason = db.Column(db.String(100))  # wrong_password, account_locked, user_not_found, rate_limited
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    user = db.relationship('User', backref='login_attempts')

# --- Password History Model (v02 - Security) ---
class PasswordHistory(db.Model):
    """Track previous passwords to prevent reuse"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('password_history', cascade='all, delete-orphan'))

# --- Staff Model ---
class Staff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    mobile = db.Column(db.String(20), nullable=True)
    place = db.Column(db.String(100), nullable=True)
    salary_type = db.Column(db.String(20), default="monthly")  # monthly, per_day
    base_salary = db.Column(db.Float, default=0.0)  # monthly amount or daily rate
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])
# --- Payment Transaction Model (v02) ---
class PaymentTransaction(db.Model):
    """Track Razorpay payment transactions"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    razorpay_order_id = db.Column(db.String(50), nullable=True, unique=True)
    razorpay_payment_id = db.Column(db.String(50), nullable=True, unique=True)
    razorpay_signature = db.Column(db.String(255), nullable=True)
    razorpay_plink_id = db.Column(db.String(50), nullable=True, unique=True)
    short_url = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='INR')
    status = db.Column(db.String(20), default='created') # created, authorized, captured, failed
    method = db.Column(db.String(20), nullable=True) # card, netbanking, upi
    error_code = db.Column(db.String(50), nullable=True)
    error_description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    order = db.relationship('Order', backref=db.backref('transactions', cascade='all, delete-orphan'))

# --- Manual Task Model (v02) ---
class ManualTask(db.Model):
    """Tasks not directly linked to an order like Pickup/Delivery"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False) # e.g. Pickup from XYZ
    description = db.Column(db.Text, nullable=True)
    assigned_to = db.Column(db.String(100), nullable=True) # Staff Username
    status = db.Column(db.String(20), default="yts") # yts, wip, done
    due_date = db.Column(db.DateTime, nullable=True)
    task_type = db.Column(db.String(50), default="Pickup") # Pickup, Delivery, Other
    customer_name = db.Column(db.String(100), nullable=True)
    mobile = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Optional relationship if needed
    # user = db.relationship('User', primaryjoin="ManualTask.assigned_to == User.username", foreign_keys="User.username")

