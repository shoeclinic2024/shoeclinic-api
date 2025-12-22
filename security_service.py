"""
Security Service - Login Security Features
Handles rate limiting, login tracking, 2FA, and security monitoring
"""
from datetime import datetime, timedelta
from flask import request, session
import pyotp
import qrcode
import io
import base64
from models import LoginAttempt, User
from database import db

# In-memory rate limiting storage (simple implementation)
# For production, consider using Redis
login_attempts_cache = {}

class SecurityService:
    """Centralized security service for authentication"""
    
    # Configuration
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 30
    RATE_LIMIT_WINDOW_MINUTES = 15
    SESSION_TIMEOUT_MINUTES = 30
    
    @staticmethod
    def is_rate_limited(ip_address):
        """Check if IP is rate limited"""
        if ip_address not in login_attempts_cache:
            return False
        
        attempts = login_attempts_cache[ip_address]
        cutoff_time = datetime.utcnow() - timedelta(minutes=SecurityService.RATE_LIMIT_WINDOW_MINUTES)
        
        # Filter recent attempts
        recent_attempts = [t for t in attempts if t > cutoff_time]
        login_attempts_cache[ip_address] = recent_attempts
        
        return len(recent_attempts) >= SecurityService.MAX_LOGIN_ATTEMPTS
    
    @staticmethod
    def track_rate_limit(ip_address):
        """Track failed login attempt for rate limiting"""
        if ip_address not in login_attempts_cache:
            login_attempts_cache[ip_address] = []
        
        login_attempts_cache[ip_address].append(datetime.utcnow())
    
    @staticmethod
    def reset_rate_limit(ip_address):
        """Clear rate limit on successful login"""
        if ip_address in login_attempts_cache:
            del login_attempts_cache[ip_address]
    
    @staticmethod
    def get_rate_limit_time_remaining(ip_address):
        """Get time remaining for rate limit in minutes"""
        if ip_address not in login_attempts_cache:
            return 0
        
        attempts = login_attempts_cache[ip_address]
        if not attempts:
            return 0
        
        oldest_attempt = min(attempts)
        elapsed = (datetime.utcnow() - oldest_attempt).total_seconds() / 60
        remaining = max(0, SecurityService.RATE_LIMIT_WINDOW_MINUTES - elapsed)
        
        return int(remaining)
    
    @staticmethod
    def is_account_locked(user):
        """Check if user account is locked"""
        if not user or not user.account_locked_until:
            return False
        
        if datetime.utcnow() < user.account_locked_until:
            return True
        
        # Auto-unlock if lockout period expired
        user.account_locked_until = None
        user.failed_login_attempts = 0
        db.session.commit()
        return False
    
    @staticmethod
    def get_lockout_time_remaining(user):
        """Get remaining lockout time in minutes"""
        if not user or not user.account_locked_until:
            return 0
        
        if datetime.utcnow() >= user.account_locked_until:
            return 0
        
        remaining = (user.account_locked_until - datetime.utcnow()).total_seconds() / 60
        return int(remaining)
    
    @staticmethod
    def handle_failed_login(user):
        """Handle failed login attempt and potential account lockout"""
        if not user:
            return
        
        user.failed_login_attempts += 1
        user.last_failed_login = datetime.utcnow()
        
        if user.failed_login_attempts >= SecurityService.MAX_LOGIN_ATTEMPTS:
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=SecurityService.LOCKOUT_DURATION_MINUTES)
            db.session.commit()
            return True  # Account locked
        
        db.session.commit()
        return False  # Not locked yet
    
    @staticmethod
    def handle_successful_login(user, ip_address):
        """Handle successful login"""
        user.failed_login_attempts = 0
        user.last_failed_login = None
        user.account_locked_until = None
        user.last_login_at = datetime.utcnow()
        user.last_login_ip = ip_address
        user.last_activity = datetime.utcnow()
        db.session.commit()
    
    @staticmethod
    def log_login_attempt(username, ip_address, success, failure_reason=None, user_id=None):
        """Log login attempt to database"""
        try:
            attempt = LoginAttempt(
                username=username,
                ip_address=ip_address,
                user_agent=request.headers.get('User-Agent', '')[:255],
                success=success,
                failure_reason=failure_reason,
                user_id=user_id
            )
            db.session.add(attempt)
            db.session.commit()
        except Exception as e:
            print(f"Error logging login attempt: {e}")
            db.session.rollback()
    
    @staticmethod
    def check_session_timeout():
        """Check if user session has timed out"""
        from flask_login import current_user
        
        if not current_user.is_authenticated:
            return False
        
        last_activity = session.get('last_activity')
        if not last_activity:
            session['last_activity'] = datetime.utcnow().isoformat()
            return False
        
        try:
            last_activity_time = datetime.fromisoformat(last_activity)
            idle_time = datetime.utcnow() - last_activity_time
            
            if idle_time > timedelta(minutes=SecurityService.SESSION_TIMEOUT_MINUTES):
                return True  # Timed out
            
            # Update last activity
            session['last_activity'] = datetime.utcnow().isoformat()
            
            # Also update in database
            current_user.last_activity = datetime.utcnow()
            db.session.commit()
            
            return False
        except:
            session['last_activity'] = datetime.utcnow().isoformat()
            return False
    
    # --- Two-Factor Authentication (Google Authenticator) ---
    
    @staticmethod
    def generate_totp_secret():
        """Generate a new TOTP secret for Google Authenticator"""
        return pyotp.random_base32()
    
    @staticmethod
    def get_totp_uri(user, secret):
        """Get TOTP provisioning URI for QR code"""
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.username,
            issuer_name='Shoe Clinic'
        )
    
    @staticmethod
    def generate_qr_code(uri):
        """Generate QR code image for Google Authenticator setup"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64 for embedding in HTML
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    
    @staticmethod
    def verify_totp(secret, code):
        """Verify TOTP code from Google Authenticator"""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # Allow 30 seconds before/after
    
    @staticmethod
    def enable_2fa(user):
        """Enable 2FA for user"""
        if not user.two_factor_secret:
            user.two_factor_secret = SecurityService.generate_totp_secret()
        
        user.two_factor_enabled = True
        db.session.commit()
        
        return user.two_factor_secret
    
    @staticmethod
    def disable_2fa(user):
        """Disable 2FA for user"""
        user.two_factor_enabled = False
        user.two_factor_secret = None
        db.session.commit()
    
    # --- Password Strength Validation ---
    
    @staticmethod
    def validate_password_strength(password):
        """
        Validate password strength
        Returns (is_valid, error_message)
        """
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        
        if not any(c.isupper() for c in password):
            return False, "Password must contain at least one uppercase letter"
        
        if not any(c.islower() for c in password):
            return False, "Password must contain at least one lowercase letter"
        
        if not any(c.isdigit() for c in password):
            return False, "Password must contain at least one number"
        
        # Check for common weak passwords
        weak_passwords = ['password', 'password123', '12345678', 'qwerty123']
        if password.lower() in weak_passwords:
            return False, "Password is too common, please choose a stronger one"
        
        return True, ""
    
    @staticmethod
    def get_password_strength_score(password):
        """
        Get password strength score (0-4)
        0 = Very Weak, 1 = Weak, 2 = Fair, 3 = Good, 4 = Strong
        """
        score = 0
        
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if any(c.isupper() for c in password) and any(c.islower() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
            score += 1
        
        return min(score, 4)

# Create singleton instance
security_service = SecurityService()
