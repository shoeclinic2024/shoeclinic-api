import random
import string
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

class OTPService:
    """Handle OTP generation and SMS delivery"""
    
    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID', '')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
        self.twilio_phone = os.getenv('TWILIO_PHONE_NUMBER', '+1234567890')
        self.otp_validity_minutes = 5  # OTP valid for 5 minutes
        
        # Determine if we should use test mode
        self.use_test_mode = not (self.account_sid.strip() and self.auth_token.strip())
        self.client = None
        
        # Only try to import Twilio if credentials are provided
        if not self.use_test_mode:
            try:
                from twilio.rest import Client
                self.client = Client(self.account_sid, self.auth_token)
            except Exception as e:
                print(f"Twilio initialization failed: {e}")
                self.use_test_mode = True
                self.client = None
    
    def generate_otp(self, length=6):
        """Generate a random OTP code"""
        return ''.join(random.choices(string.digits, k=length))
    
    def send_otp_sms(self, phone_number, otp_code):
        """Send OTP via SMS using Twilio or test mode"""
        
        # Test Mode - Print OTP for testing
        if self.use_test_mode:
            print(f"\n{'='*60}")
            print(f"TEST MODE - OTP SENT (Not using Twilio)")
            print(f"{'='*60}")
            print(f"Phone: {phone_number}")
            print(f"OTP Code: {otp_code}")
            print(f"Valid for: {self.otp_validity_minutes} minutes")
            print(f"{'='*60}\n")
            return True, "OTP sent successfully (TEST MODE)"
        
        # Production Mode - Send via Twilio
        if not self.client:
            return False, "Twilio not configured. Add credentials to .env file."
        
        try:
            # Format phone number (ensure it starts with +)
            if not phone_number.startswith('+'):
                phone_number = '+' + phone_number
            
            message = self.client.messages.create(
                body=f"Your password reset OTP is: {otp_code}. Valid for 5 minutes.",
                from_=self.twilio_phone,
                to=phone_number
            )
            return True, "OTP sent successfully"
        except Exception as e:
            return False, str(e)
    
    def get_otp_expiry_time(self):
        """Get the expiry time for OTP"""
        return datetime.utcnow() + timedelta(minutes=self.otp_validity_minutes)
    
    def is_otp_valid(self, otp_expiry):
        """Check if OTP is still valid (not expired)"""
        if not otp_expiry:
            return False
        return datetime.utcnow() < otp_expiry
    
    def can_attempt_otp(self, otp_attempts, max_attempts=3):
        """Check if user can attempt OTP verification"""
        return otp_attempts < max_attempts

otp_service = OTPService()
