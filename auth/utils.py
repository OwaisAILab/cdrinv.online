"""
Auth Utilities: password hashing, OTP generation, JWT, email sending
"""
import os, random, smtplib, string, time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from passlib.context import CryptContext
from jose import jwt

# At the top of auth/utils.py, after imports
def _now():
    return datetime.utcnow()

# ── Config ────────────────────────────────────────────────────────────────────
JWT_SECRET      = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM   = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HRS  = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "muhammadmeethani@gmail.com")
SMTP_PASS       = os.getenv("SMTP_PASS", "dnzrvpzlnqdudrtv")
FROM_EMAIL      = os.getenv("FROM_EMAIL", "CDRIO Portal")

OTP_EXPIRE_MINS  = 10
OTP_MAX_ATTEMPTS = 5   # lock after this many wrong guesses

pwd_ctx = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

# ── Password ──────────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(plain, hashed)
    except Exception:
        return False

_SPECIAL = set("!@#$%^&*()_+-=[]{}|;':\",./<>?`~\\")

def validate_password_strength(password: str) -> list:
    """Returns list of error strings. Empty list means password is valid."""
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not any(c.isupper() for c in password):
        errors.append("Must contain at least one uppercase letter (A-Z).")
    if not any(c.islower() for c in password):
        errors.append("Must contain at least one lowercase letter (a-z).")
    if not any(c.isdigit() for c in password):
        errors.append("Must contain at least one number (0-9).")
    if not any(c in _SPECIAL for c in password):
        errors.append("Must contain at least one special character (!@#$%^&* etc.).")
    return errors

# ── OTP ───────────────────────────────────────────────────────────────────────
def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))

def otp_expiry() -> datetime:
    # Naive UTC — matches SQLite datetime storage
    return datetime.utcnow() + timedelta(minutes=OTP_EXPIRE_MINS)

# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(data: dict) -> str:
    payload = data.copy()
    if "sub" in payload:
        payload["sub"] = str(payload["sub"])
    payload["exp"] = int(time.time()) + (JWT_EXPIRE_HRS * 3600)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception as e:
        print(f"[JWT] decode failed: {e}")
        return None

# ── Email ─────────────────────────────────────────────────────────────────────
def _send_email(to: str, subject: str, html_body: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        print(f"\n{'='*60}")
        print(f"[DEV EMAIL] To: {to}")
        print(f"[DEV EMAIL] Subject: {subject}")
        import re
        otp_match = re.search(r'letter-spacing:8px[^>]*>(\d{6})<', html_body)
        if otp_match:
            print(f"[DEV EMAIL] *** OTP CODE: {otp_match.group(1)} ***")
        print(f"{'='*60}\n")
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = FROM_EMAIL
        msg["To"]      = to
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(FROM_EMAIL, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def send_registration_otp(email: str, username: str, otp: str) -> bool:
    subject = "CDR Intelligence Portal — Email Verification"
    body = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:32px;max-width:500px">
      <h2 style="color:#c9a84c;letter-spacing:2px">CDR INTELLIGENCE PORTAL</h2>
      <p style="color:#6a9a78;margin:8px 0 24px">Email Verification Required</p>
      <p>Hello <strong>{username}</strong>,</p>
      <p style="margin-top:12px">Your one-time verification code is:</p>
      <div style="font-size:2.5rem;font-weight:bold;color:#c9a84c;letter-spacing:8px;
                  background:#0d2218;padding:20px;text-align:center;margin:20px 0;
                  border:1px solid #1e4030">{otp}</div>
      <p style="color:#6a9a78;font-size:0.85rem">Expires in <strong style="color:#e8f0eb">10 minutes</strong>.</p>
      <p style="color:#6a9a78;font-size:0.85rem;margin-top:16px">
        After verification your account will be reviewed by an administrator.
      </p>
    </div>
    """
    return _send_email(email, subject, body)


def send_approval_email(email: str, username: str, subscription: str, action: str = "approved") -> bool:
    """
    action: "approved" | "renewed" | "upgraded"
    """
    action_map = {
        "approved": ("Account Approved", "Your account has been approved.", "#4aad72"),
        "renewed":  ("Subscription Renewed", "Your subscription has been renewed.", "#00d68f"),
        "upgraded": ("Plan Upgraded", "Your plan has been upgraded.", "#00bfff"),
    }
    title, msg_text, color = action_map.get(action, action_map["approved"])
    subject = f"CDR Intelligence Portal — {title}"
    body = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:32px;max-width:500px">
      <h2 style="color:#c9a84c;letter-spacing:2px">CDR INTELLIGENCE PORTAL</h2>
      <p style="color:{color};font-size:1.1rem;margin:8px 0 24px">{title}</p>
      <p>Hello <strong>{username}</strong>,</p>
      <p style="margin-top:12px">
        {msg_text} Your active plan is now
        <strong style="color:#c9a84c">{subscription}</strong>.
        Every login requires a one-time code sent to this email.
      </p>
    </div>
    """
    return _send_email(email, subject, body)


def send_rejection_email(email: str, username: str) -> bool:
    subject = "CDR Intelligence Portal — Registration Update"
    body = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:32px;max-width:500px">
      <h2 style="color:#c9a84c;letter-spacing:2px">CDR INTELLIGENCE PORTAL</h2>
      <p style="color:#c0392b;font-size:1.1rem;margin:8px 0 24px">Registration Not Approved</p>
      <p>Hello <strong>{username}</strong>,</p>
      <p style="margin-top:12px">We were unable to verify your payment. Please contact the administrator.</p>
    </div>
    """
    return _send_email(email, subject, body)


def send_login_otp(email: str, username: str, otp: str) -> bool:
    subject = "CDR Intelligence Portal — Login Verification"
    body = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:32px;max-width:500px">
      <h2 style="color:#c9a84c;letter-spacing:2px">CDR INTELLIGENCE PORTAL</h2>
      <p style="color:#6a9a78;margin:8px 0 24px">Login OTP</p>
      <p>Hello <strong>{username}</strong>,</p>
      <p style="margin-top:12px">Your login verification code is:</p>
      <div style="font-size:2.5rem;font-weight:bold;color:#c9a84c;letter-spacing:8px;
                  background:#0d2218;padding:20px;text-align:center;margin:20px 0;
                  border:1px solid #1e4030">{otp}</div>
      <p style="color:#6a9a78;font-size:0.85rem">Expires in <strong style="color:#e8f0eb">10 minutes</strong>. Do not share this code.</p>
    </div>
    """
    return _send_email(email, subject, body)


def send_reset_otp(email: str, username: str, otp: str) -> bool:
    subject = "CDR Intelligence Portal — Password Reset"
    body = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:32px;max-width:500px">
      <h2 style="color:#c9a84c;letter-spacing:2px">CDR INTELLIGENCE PORTAL</h2>
      <p style="color:#6a9a78;margin:8px 0 24px">Password Reset Request</p>
      <p>Hello <strong>{username}</strong>,</p>
      <p style="margin-top:12px">Your one-time reset code is:</p>
      <div style="font-size:2.5rem;font-weight:bold;color:#c9a84c;letter-spacing:8px;
                  background:#0d2218;padding:20px;text-align:center;margin:20px 0;
                  border:1px solid #1e4030">{otp}</div>
      <p style="color:#6a9a78;font-size:0.85rem">Expires in <strong style="color:#e8f0eb">10 minutes</strong>. Do not share this code.</p>
      <p style="color:#6a9a78;font-size:0.85rem;margin-top:16px">
        If you did not request a password reset, please ignore this email.
      </p>
    </div>
    """
    return _send_email(email, subject, body)