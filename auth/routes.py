"""
Auth routes – Flask version (no detached instance errors)
"""
from dotenv import load_dotenv
from flask import Blueprint, render_template, request, redirect, make_response, jsonify, abort, current_app
from datetime import datetime, timedelta
import hmac, hashlib, math, os, secrets, httpx

from auth.database import SessionLocal
from auth.models import User, UserStatus, SubscriptionType, PLAN_CDR_LIMIT, PLAN_LABELS, PLAN_DURATION_DAYS
from auth.utils import (
    hash_password, verify_password,
    validate_password_strength,
    generate_otp, otp_expiry, OTP_MAX_ATTEMPTS,
    create_access_token, decode_token,
    send_registration_otp, send_login_otp,
    send_approval_email, send_rejection_email,
    send_reset_otp, _now
)

load_dotenv()

# ── Admin alert (replaces unimplemented WhatsApp notifier) ────────────────
def _notify_admin(username: str, email: str, event: str) -> None:
    """
    Send an admin alert email when a user registers or submits a renewal.
    Falls back to a console log if SMTP is not configured.
    """
    from auth.utils import SMTP_USER, SMTP_PASS, _send_email
    import html as _html
    admin_email = os.getenv("ADMIN_EMAIL", SMTP_USER)
    if not admin_email:
        print(f"[ADMIN ALERT] {event} | user={username} | email={email}")
        return

    safe_event    = _html.escape(event)
    safe_username = _html.escape(username)
    safe_email    = _html.escape(email)
    from datetime import datetime as _dt
    timestamp = _dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    html_body = f"""
    <div style="font-family:monospace;background:#0d1a0f;color:#c9f0c9;padding:24px;border-radius:8px;max-width:480px;">
      <div style="border-left:4px solid #c9a84c;padding-left:14px;margin-bottom:16px;">
        <div style="font-size:11px;color:#c9a84c;letter-spacing:0.1em;text-transform:uppercase;">CDRInv.Online — Admin Alert</div>
        <div style="font-size:20px;font-weight:bold;margin-top:4px;">{safe_event}</div>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr><td style="color:#6a9a78;padding:4px 0;width:100px;">Username</td><td style="color:#e8f0eb;">{safe_username}</td></tr>
        <tr><td style="color:#6a9a78;padding:4px 0;">Email</td><td style="color:#e8f0eb;">{safe_email}</td></tr>
        <tr><td style="color:#6a9a78;padding:4px 0;">Time</td><td style="color:#e8f0eb;">{timestamp}</td></tr>
      </table>
      <div style="margin-top:16px;">
        <a href="https://cdrinv.online/auth/admin/pending"
           style="display:inline-block;padding:8px 18px;background:#c9a84c;color:#0d1a0f;
                  font-weight:bold;font-size:12px;border-radius:4px;text-decoration:none;
                  letter-spacing:0.06em;">
          OPEN ADMIN PANEL →
        </a>
      </div>
    </div>
    """
    try:
        _send_email(admin_email, f"[CDRInv] {event} — {username}", html_body)
    except Exception as e:
        print(f"[ADMIN ALERT EMAIL ERROR] {e}")
        print(f"[ADMIN ALERT] {event} | user={username} | email={email}")

# ── Blueprint ──────────────────────────────────────────────────────────────
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Standalone limiter for auth blueprint — initialised with the app in init_auth_routes()
_auth_limiter = Limiter(get_remote_address, default_limits=[], storage_uri="memory://")

def _limiter():
    return _auth_limiter

# ── Make `request` available in blueprint templates ───────────────────────
@auth_bp.context_processor
def inject_request():
    return dict(request=request)

ADMIN_SECRET = os.getenv("ADMIN_SECRET")
if not ADMIN_SECRET:
    raise RuntimeError("ADMIN_SECRET environment variable not set.")


def _admin_token():
    hour_bucket = str(math.floor(datetime.utcnow().timestamp() / 3600))
    return hmac.new(ADMIN_SECRET.encode(), hour_bucket.encode(), hashlib.sha256).hexdigest()

def _check_admin(admin_token):
    if not admin_token:
        return False
    return hmac.compare_digest(admin_token, _admin_token())

def _get_current_user():
    token = request.cookies.get("access_token")
    if not token:
        abort(401)
    payload = decode_token(token)
    if not payload:
        abort(401)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(payload.get("sub", 0))).first()
        if not user or user.status != UserStatus.ACTIVE:
            abort(401)
        if user.subscription_end and user.subscription_end < _now():
            # Persist the expired status so admin panel reflects it immediately
            if user.status == UserStatus.ACTIVE:
                user.status = UserStatus.EXPIRED
                db.commit()
            abort(401)
        # Keep the user attached until we return, so we must not close db here.
        # Instead, return the user and a flag that tells the caller not to close?
        # Better: return a copy of needed attributes. But for simplicity, we'll
        # return the user and let the route close the session after use.
        # To avoid detachment, we'll keep the session open and pass it along.
        # However, this is messy. Instead, we'll fetch all needed data now.
        # We'll create a simple data object.
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'subscription_type': user.subscription_type,
            'uploads_remaining': user.uploads_remaining,
            'status': user.status
        }
        db.close()
        return user_data
    except Exception:
        db.close()
        abort(401)

# ──────────────────────────────────────────────────────────────────────────
#  REGISTRATION
# ──────────────────────────────────────────────────────────────────────────


@auth_bp.route("/register", methods=['GET'])
def register_page():
    return render_template("register.html")

@auth_bp.route("/register", methods=['POST'])
@_limiter().limit("5 per minute")
def register():
    username = request.form.get("username")
    email = request.form.get("email").lower()
    password = request.form.get("password")
    confirm = request.form.get("confirm_password")
    transaction_id = request.form.get("transaction_id")
    subscription_type = request.form.get("subscription_type")

    errors = []
    if password != confirm:
        errors.append("Passwords do not match.")
    else:
        errors.extend(validate_password_strength(password))
    if subscription_type not in ("1_month", "6_months", "1_year"):
        errors.append("Invalid subscription type.")

    db = SessionLocal()
    try:
        existing_email = db.query(User).filter(User.email == email).first()
        existing_username = db.query(User).filter(User.username == username).first()

        if existing_email and existing_email.status != UserStatus.REJECTED:
            errors.append("Email already registered.")
        if existing_username and existing_username.status != UserStatus.REJECTED:
            errors.append("Username already taken.")
        if (existing_email and existing_email.status == UserStatus.REJECTED and
                existing_username and existing_username.status == UserStatus.REJECTED and
                existing_email.id != existing_username.id):
            errors.append("Username already taken by another account.")

        if errors:
            db.close()
            return render_template("register.html",
                                   errors=errors,
                                   form={"username": username, "email": email, "transaction_id": transaction_id}), 422

        otp = generate_otp()
        reapply_user = existing_email if (existing_email and existing_email.status == UserStatus.REJECTED) else None

        if reapply_user:
            reapply_user.username = username
            reapply_user.hashed_password = hash_password(password)
            reapply_user.transaction_id = transaction_id.strip()
            reapply_user.subscription_type = SubscriptionType(subscription_type)
            reapply_user.cdr_limit = PLAN_CDR_LIMIT.get(subscription_type)
            reapply_user.status = UserStatus.PENDING_EMAIL
            reapply_user.email_otp = otp
            reapply_user.email_otp_expires = otp_expiry()
            reapply_user.uploads_used = 0
            reapply_user.pending_request_type = None
            reapply_user.pending_plan = None
            db.commit()
            user = reapply_user
        else:
            user = User(
                username=username,
                email=email,
                hashed_password=hash_password(password),
                transaction_id=transaction_id.strip(),
                subscription_type=SubscriptionType(subscription_type),
                cdr_limit=PLAN_CDR_LIMIT.get(subscription_type),
                status=UserStatus.PENDING_EMAIL,
                email_otp=otp,
                email_otp_expires=otp_expiry(),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # Capture data before closing session
        user_id = user.id
        user_email = user.email
        user_username = user.username
        _notify_admin(username, email, f"NEW REG | {subscription_type}")
        db.close()

        send_registration_otp(user_email, user_username, otp)
        return redirect(f"/auth/verify-email?user_id={user_id}", code=303)

    except Exception as e:
        db.close()
        import traceback
        traceback.print_exc()
        return render_template("register.html",
                               errors=[str(e)],
                               form={"username": username, "email": email, "transaction_id": transaction_id}), 500


# ──────────────────────────────────────────────────────────────────────────
#  TRAIL
# ──────────────────────────────────────────────────────────────────────────
@auth_bp.route("/trial-register", methods=['GET'])
def trial_register_page():
    return render_template("trial_register.html")

@auth_bp.route("/register-trial", methods=['POST'])
@_limiter().limit("5 per minute")
def register_trial():
    username = request.form.get("username")
    email = request.form.get("email").lower()
    password = request.form.get("password")
    confirm = request.form.get("confirm_password")

    errors = []
    if password != confirm:
        errors.append("Passwords do not match.")
    else:
        errors.extend(validate_password_strength(password))

    db = SessionLocal()
    try:
        existing_email = db.query(User).filter(User.email == email).first()
        existing_username = db.query(User).filter(User.username == username).first()

        if existing_email and existing_email.status != UserStatus.REJECTED:
            errors.append("Email already registered.")
        if existing_username and existing_username.status != UserStatus.REJECTED:
            errors.append("Username already taken.")

        if errors:
            db.close()
            return render_template("trial_register.html",
                                   errors=errors,
                                   form={"username": username, "email": email}), 422

        trial_days = PLAN_DURATION_DAYS["trial"]
        now = _now()
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            transaction_id="TRIAL_" + generate_otp(8),
            subscription_type=SubscriptionType.TRIAL,
            cdr_limit=PLAN_CDR_LIMIT["trial"],
            status=UserStatus.ACTIVE,
            email_verified=True,
            subscription_start=now,
            subscription_end=now + timedelta(days=trial_days),
            approved_at=now,
            uploads_used=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        user_id = user.id
        user_username = user.username
        db.close()

        # Log the user in immediately
        token = create_access_token({"sub": user_id, "username": user_username})
        resp = make_response(redirect("/dashboard", code=303))
        resp.set_cookie(key="access_token", value=token, httponly=True, samesite="Lax", max_age=86400, path="/")
        return resp

    except Exception as e:
        db.close()
        import traceback
        traceback.print_exc()
        return render_template("trial_register.html",
                               errors=[str(e)],
                               form={"username": username, "email": email}), 500
    
# ── EMAIL OTP VERIFICATION ────────────────────────────────────────────────

@auth_bp.route("/verify-email", methods=['GET'])
def verify_email_page():
    user_id = request.args.get("user_id", type=int)
    return render_template("verify_email.html", user_id=user_id)

@auth_bp.route("/verify-email", methods=['POST'])
@_limiter().limit("5 per minute")
def verify_email():
    user_id = request.form.get("user_id", type=int)
    otp = request.form.get("otp")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            return render_template("verify_email.html", user_id=user_id, error="User not found."), 404
        if user.email_verified:
            db.close()
            return redirect(f"/auth/pending-approval?user_id={user.id}", code=303)

        now = _now()
        if not user.email_otp or user.email_otp != otp.strip():
            db.close()
            return render_template("verify_email.html", user_id=user_id, error="Invalid OTP."), 422
        if user.email_otp_expires and user.email_otp_expires < now:
            db.close()
            return render_template("verify_email.html", user_id=user_id, error="OTP expired."), 422

        user.email_verified = True
        user.email_otp = None
        user.email_otp_expires = None
        user.status = UserStatus.PENDING_PAYMENT
        db.commit()
        user_id = user.id
        db.close()
        return redirect(f"/auth/pending-approval?user_id={user_id}", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/resend-registration-otp", methods=['POST'])
@_limiter().limit("5 per minute")
def resend_registration_otp():
    user_id = request.form.get("user_id", type=int)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or user.email_verified:
            db.close()
            return jsonify({"error": "Cannot resend OTP"}), 400
        otp = generate_otp()
        user.email_otp = otp
        user.email_otp_expires = otp_expiry()
        db.commit()
        user_email = user.email
        user_username = user.username
        db.close()
        send_registration_otp(user_email, user_username, otp)
        return jsonify({"status": "sent"})
    except Exception:
        db.close()
        raise

# ── PENDING APPROVAL ──────────────────────────────────────────────────────

@auth_bp.route("/pending-approval", methods=['GET'])
def pending_approval():
    user_id = request.args.get("user_id", 0, type=int)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        submitted_plan = None
        request_type = None
        if user:
            plan_key = (user.pending_plan or user.subscription_type.value) if user else None
            submitted_plan = PLAN_LABELS.get(plan_key, plan_key)
            request_type = user.pending_request_type
        db.close()
        return render_template("pending_approval.html",
                               user_id=user_id,
                               submitted_plan=submitted_plan,
                               request_type=request_type)
    except Exception:
        db.close()
        raise

@auth_bp.route("/check-status/<int:user_id>")
def check_status(user_id):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
        if not user:
            return jsonify({"status": "not_found"})
        return jsonify({"status": user.status.value})
    except Exception:
        db.close()
        raise

# ── LOGIN ─────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=['GET'])
def login_page():
    return render_template("login.html")

@auth_bp.route("/login", methods=['POST'])
@_limiter().limit("5 per minute")
def login():
    email = request.form.get("email").lower()
    password = request.form.get("password")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.hashed_password):
            db.close()
            return render_template("login.html", error="Invalid email or password."), 401

        if user.status == UserStatus.ACTIVE and user.subscription_end and user.subscription_end < _now():
            user.status = UserStatus.EXPIRED
            db.commit()

        status_errors = {
            UserStatus.PENDING_EMAIL: "Please verify your email first.",
            UserStatus.PENDING_PAYMENT: "Your account is pending admin approval. Please wait.",
            UserStatus.REJECTED: "Your registration was not approved. Contact admin.",
            UserStatus.EXPIRED: "Your subscription has expired.",
        }
        if user.status in status_errors:
            is_expired = (user.status == UserStatus.EXPIRED)
            db.close()
            return render_template("login.html",
                                   error=status_errors[user.status],
                                   is_expired=is_expired,
                                   expired_email=email if is_expired else ""), 403
        if user.status != UserStatus.ACTIVE:
            db.close()
            return render_template("login.html", error="Account not active."), 403

        otp = generate_otp()
        user.login_otp = otp
        user.login_otp_expires = otp_expiry()
        user.login_otp_attempts = 0
        db.commit()

        # Extract needed data before closing
        user_id = user.id
        user_email = user.email
        user_username = user.username
        db.close()

        send_login_otp(user_email, user_username, otp)
        return redirect(f"/auth/login-otp?user_id={user_id}", code=303)

    except Exception:
        db.close()
        raise

# ── LOGIN OTP ─────────────────────────────────────────────────────────────

@auth_bp.route("/login-otp", methods=['GET'])
def login_otp_page():
    user_id = request.args.get("user_id", type=int)
    return render_template("login_otp.html", user_id=user_id)

@auth_bp.route("/login-otp", methods=['POST'])
@_limiter().limit("5 per minute")
def login_otp():
    user_id = request.form.get("user_id", type=int)
    otp = request.form.get("otp")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            abort(404)

        attempts = user.login_otp_attempts or 0
        if attempts >= OTP_MAX_ATTEMPTS:
            user.login_otp = None
            user.login_otp_expires = None
            user.login_otp_attempts = 0
            db.commit()
            db.close()
            return render_template("login_otp.html", user_id=user_id,
                                   error="Too many failed attempts. Please log in again."), 429

        now = _now()
        if not user.login_otp or user.login_otp != otp.strip():
            user.login_otp_attempts = attempts + 1
            db.commit()
            remaining = OTP_MAX_ATTEMPTS - user.login_otp_attempts
            db.close()
            return render_template("login_otp.html", user_id=user_id,
                                   error=f"Invalid OTP. {remaining} attempt(s) remaining."), 422
        if user.login_otp_expires and user.login_otp_expires < now:
            db.close()
            return render_template("login_otp.html", user_id=user_id, error="OTP expired. Please login again."), 422

        user.login_otp = None
        user.login_otp_expires = None
        user.login_otp_attempts = 0
        db.commit()

        # Extract needed data before closing
        user_id = user.id
        user_username = user.username
        db.close()

        token = create_access_token({"sub": user_id, "username": user_username})
        resp = make_response(redirect("/upload", code=303))
        resp.set_cookie(key="access_token", value=token, httponly=True, samesite="Lax", max_age=86400, path="/")
        return resp

    except Exception:
        db.close()
        raise

@auth_bp.route("/resend-login-otp", methods=['POST'])
@_limiter().limit("5 per minute")
def resend_login_otp():
    user_id = request.form.get("user_id", type=int)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or user.status != UserStatus.ACTIVE:
            db.close()
            return jsonify({"error": "Cannot resend OTP"}), 400
        otp = generate_otp()
        user.login_otp = otp
        user.login_otp_expires = otp_expiry()
        user.login_otp_attempts = 0
        db.commit()
        user_email = user.email
        user_username = user.username
        db.close()
        send_login_otp(user_email, user_username, otp)
        return jsonify({"status": "sent"})
    except Exception:
        db.close()
        raise

# ── LOGOUT ────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    resp = make_response(redirect("/auth/login", code=303))
    resp.delete_cookie("access_token", path="/")
    return resp

# ── ADMIN PANEL ───────────────────────────────────────────────────────────

@auth_bp.route("/admin/login", methods=['GET'])
def admin_login_page():
    return render_template("admin_login.html")

@auth_bp.route("/admin/login", methods=['POST'])
@_limiter().limit("5 per minute")
def admin_login():
    secret = request.form.get("secret")
    if secret != ADMIN_SECRET:
        return render_template("admin_login.html", error="Invalid admin secret key."), 403
    token = _admin_token()
    resp = make_response(redirect("/auth/admin/pending", code=303))
    resp.set_cookie("admin_token", token, httponly=True, samesite="Lax", max_age=3600, path="/")
    return resp

@auth_bp.route("/admin/pending", methods=['GET'])
def admin_pending():
    admin_token = request.cookies.get("admin_token")
    if not _check_admin(admin_token):
        return redirect("/auth/admin/login", code=303)
    db = SessionLocal()
    try:
        pending = db.query(User).filter(User.status == UserStatus.PENDING_PAYMENT).all()
        all_users = db.query(User).filter(User.status != UserStatus.PENDING_EMAIL).all()

        # ── Auto-expire users whose subscription_end has passed ──────────
        today = datetime.utcnow()
        changed = False
        for u in all_users:
            if u.status == UserStatus.ACTIVE and u.subscription_end:
                end = u.subscription_end
                if hasattr(end, 'tzinfo') and end.tzinfo is not None:
                    end = end.replace(tzinfo=None)
                if end < today:
                    u.status = UserStatus.EXPIRED
                    changed = True
        if changed:
            db.commit()
            # Refresh counts from updated list
            pending = [u for u in all_users if u.status == UserStatus.PENDING_PAYMENT]

        PLAN_PRICES = {"1_month": 1050, "6_months": 5600, "1_year": 11150}
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fiscal_year_start = today.replace(month=7, day=1, hour=0, minute=0, second=0, microsecond=0)
        if fiscal_year_start > today:
            fiscal_year_start = fiscal_year_start.replace(year=fiscal_year_start.year - 1)

        active_count = sum(1 for u in all_users if u.status == UserStatus.ACTIVE)
        pending_count = sum(1 for u in all_users if u.status == UserStatus.PENDING_PAYMENT)
        expired_count = sum(1 for u in all_users if u.status == UserStatus.EXPIRED)
        rejected_count = sum(1 for u in all_users if u.status == UserStatus.REJECTED)

        monthly_income = 0
        annual_income = 0
        for u in all_users:
            paid_on = u.subscription_start or u.approved_at
            if paid_on:
                if hasattr(paid_on, 'tzinfo') and paid_on.tzinfo:
                    paid_on = paid_on.replace(tzinfo=None)
                price = PLAN_PRICES.get(u.subscription_type.value, 0)
                if paid_on >= month_start:
                    monthly_income += price
                if paid_on >= fiscal_year_start:
                    annual_income += price

        db.close()
        return render_template("admin_panel.html",
                               pending=pending,
                               all_users=all_users,
                               PLAN_LABELS=PLAN_LABELS,
                               total_users=len(all_users),
                               active_count=active_count,
                               pending_count=pending_count,
                               expired_count=expired_count,
                               rejected_count=rejected_count,
                               monthly_income=monthly_income,
                               annual_income=annual_income,
                               now=today)
    except Exception:
        db.close()
        raise

@auth_bp.route("/admin/approve/<int:user_id>", methods=['POST'])
def admin_approve(user_id):
    admin_token = request.cookies.get("admin_token")
    if not _check_admin(admin_token):
        abort(403)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            abort(404)
        now = _now()
        if user.pending_plan:
            user.subscription_type = SubscriptionType(user.pending_plan)
            user.cdr_limit = PLAN_CDR_LIMIT.get(user.pending_plan)
        plan_value = user.subscription_type.value
        days = PLAN_DURATION_DAYS.get(plan_value, 30)
        label = PLAN_LABELS.get(plan_value, plan_value)
        user.status = UserStatus.ACTIVE
        user.subscription_start = now
        user.subscription_end = now + timedelta(days=days)
        user.approved_at = now
        if user.subscription_type == SubscriptionType.ONE_MONTH:
            user.uploads_used = 0
        action = "approved"
        if user.pending_request_type == "renewal":
            action = "renewed"
        elif user.pending_request_type == "upgrade":
            action = "upgraded"
        user.pending_request_type = None
        user.pending_plan = None
        db.commit()
        user_email = user.email
        user_username = user.username
        db.close()
        send_approval_email(user_email, user_username, label, action)
        return redirect("/auth/admin/pending", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/admin/reject/<int:user_id>", methods=['POST'])
def admin_reject(user_id):
    admin_token = request.cookies.get("admin_token")
    if not _check_admin(admin_token):
        abort(403)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            abort(404)
        if user.pending_plan:
            user.pending_plan = None
            user.pending_request_type = None
            if user.subscription_end and user.subscription_end > _now():
                user.status = UserStatus.ACTIVE
                db.commit()
                db.close()
                return redirect("/auth/admin/pending", code=303)
        user.status = UserStatus.REJECTED
        db.commit()
        user_email = user.email
        user_username = user.username
        db.close()
        send_rejection_email(user_email, user_username)
        return redirect("/auth/admin/pending", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/admin/change-status/<int:user_id>", methods=['POST'])
def admin_change_status(user_id):
    admin_token = request.cookies.get("admin_token")
    if not _check_admin(admin_token):
        abort(403)
    new_status = request.form.get("new_status")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            abort(404)
        try:
            status_enum = UserStatus(new_status)
        except ValueError:
            db.close()
            abort(400, "Invalid status")
        user.status = status_enum
        if status_enum == UserStatus.ACTIVE and (user.subscription_end is None or user.subscription_end < _now()):
            plan_value = user.subscription_type.value
            days = PLAN_DURATION_DAYS.get(plan_value, 30)
            user.subscription_start = _now()
            user.subscription_end = _now() + timedelta(days=days)
            if user.subscription_type == SubscriptionType.ONE_MONTH:
                user.uploads_used = 0
        db.commit()
        db.close()
        return redirect("/auth/admin/pending", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/admin/logout")
def admin_logout():
    resp = make_response(redirect("/auth/admin/login", code=303))
    resp.delete_cookie("admin_token", path="/")
    return resp

# ── RENEW / UPGRADE (authenticated) ──────────────────────────────────────

@auth_bp.route("/renew-plan", methods=['GET'])
def renew_plan_page():
    user = _get_current_user()  # returns dict with id, username, etc.
    db = SessionLocal()
    try:
        # Re-fetch the user to get full object for days_remaining etc.
        full_user = db.query(User).filter(User.id == user['id']).first()
        if not full_user:
            db.close()
            abort(401)
        plan_label = PLAN_LABELS.get(full_user.subscription_type.value, full_user.subscription_type.value)
        expiry_date = full_user.subscription_end.strftime("%d %b %Y") if full_user.subscription_end else "N/A"
        days_remaining = full_user.days_remaining
        current_plan_value = full_user.subscription_type.value
        db.close()
        return render_template("renew_plan.html",
                               plan_label=plan_label,
                               current_plan_value=current_plan_value,
                               days_remaining=days_remaining,
                               expiry_date=expiry_date,
                               success=False,
                               error=None)
    except Exception:
        db.close()
        raise

@auth_bp.route("/renew-plan", methods=['POST'])
@_limiter().limit("5 per minute")
def renew_plan_submit():
    user = _get_current_user()
    new_plan = request.form.get("new_plan")
    request_type = request.form.get("request_type")
    transaction_id = request.form.get("transaction_id")
    notes = request.form.get("notes", "")
    valid_plans = ("1_month", "6_months", "1_year")
    valid_types = ("renewal", "upgrade")
    error = None
    if new_plan not in valid_plans:
        error = "Invalid plan selected."
    elif request_type not in valid_types:
        error = "Invalid request type."
    elif not transaction_id.strip():
        error = "Transaction ID is required."

    if error:
        # Need to fetch user again to show form with error
        db = SessionLocal()
        try:
            full_user = db.query(User).filter(User.id == user['id']).first()
            plan_label = PLAN_LABELS.get(full_user.subscription_type.value, full_user.subscription_type.value)
            expiry_date = full_user.subscription_end.strftime("%d %b %Y") if full_user.subscription_end else "N/A"
            days_remaining = full_user.days_remaining
            current_plan_value = full_user.subscription_type.value
            db.close()
            return render_template("renew_plan.html",
                                   plan_label=plan_label,
                                   current_plan_value=current_plan_value,
                                   days_remaining=days_remaining,
                                   expiry_date=expiry_date,
                                   success=False,
                                   error=error), 422
        except Exception:
            db.close()
            raise

    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.id == user['id']).first()
        db_user.transaction_id = transaction_id.strip()
        db_user.pending_plan = new_plan
        db_user.pending_request_type = request_type
        db_user.status = UserStatus.PENDING_PAYMENT
        db.commit()
        user_username = db_user.username
        user_email = db_user.email
        db.close()
        _notify_admin(user_username, user_email, f"{request_type.upper()} → {new_plan}")
        resp = make_response(redirect(f"/auth/pending-approval?user_id={user['id']}", code=303))
        resp.delete_cookie("access_token", path="/")
        return resp
    except Exception:
        db.close()
        raise

# ── EXPIRED RENEWAL (unauthenticated) ────────────────────────────────────

@auth_bp.route("/expired-renew", methods=['GET'])
def expired_renew_page():
    email = request.args.get("email", "")
    return render_template("expired_renew.html", prefill_email=email)

@auth_bp.route("/expired-renew", methods=['POST'])
@_limiter().limit("5 per minute")
def expired_renew_submit():
    email = request.form.get("email").lower().strip()
    new_plan = request.form.get("new_plan")
    transaction_id = request.form.get("transaction_id")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        errors = []
        if not user:
            errors.append("No account found with that email address.")
        elif user.status not in (UserStatus.EXPIRED, UserStatus.ACTIVE, UserStatus.PENDING_PAYMENT):
            errors.append("This form is only for existing accounts. New users must register.")
        if new_plan not in ("1_month","6_months","1_year"):
            errors.append("Invalid plan selected.")
        if not transaction_id.strip():
            errors.append("Transaction ID is required.")
        if errors:
            db.close()
            return render_template("expired_renew.html", prefill_email=email, errors=errors), 422
        user.transaction_id = transaction_id.strip()
        user.pending_plan = new_plan
        user.pending_request_type = "renewal"
        user.status = UserStatus.PENDING_PAYMENT
        db.commit()
        user_id = user.id
        user_username = user.username
        user_email = user.email
        db.close()
        _notify_admin(user_username, user_email, f"EXPIRED RENEWAL → {new_plan}")
        return redirect(f"/auth/pending-approval?user_id={user_id}", code=303)
    except Exception:
        db.close()
        raise

# ── FORGOT PASSWORD ───────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=['GET'])
def forgot_password_page():
    return render_template("forgot_password.html")

@auth_bp.route("/forgot-password", methods=['POST'])
@_limiter().limit("5 per minute")
def forgot_password_submit():
    email = request.form.get("email").lower().strip()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user and user.status == UserStatus.ACTIVE:
            otp = generate_otp()
            user.reset_otp = otp
            user.reset_otp_expires = otp_expiry()
            db.commit()
            user_id = user.id
            user_email = user.email
            user_username = user.username
            db.close()
            send_reset_otp(user_email, user_username, otp)
            return redirect(f"/auth/reset-password-otp?user_id={user_id}", code=303)
        db.close()
        return render_template("forgot_password.html", sent=True)
    except Exception:
        db.close()
        raise

@auth_bp.route("/reset-password-otp", methods=['GET'])
def reset_otp_page():
    user_id = request.args.get("user_id", type=int)
    return render_template("reset_password_otp.html", user_id=user_id)

@auth_bp.route("/reset-password-otp", methods=['POST'])
@_limiter().limit("5 per minute")
def reset_otp_verify():
    user_id = request.form.get("user_id", type=int)
    otp = request.form.get("otp")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            abort(404)
        now = _now()
        if not user.reset_otp or user.reset_otp != otp.strip():
            db.close()
            return render_template("reset_password_otp.html", user_id=user_id, error="Invalid OTP."), 422
        if user.reset_otp_expires and user.reset_otp_expires < now:
            db.close()
            return render_template("reset_password_otp.html", user_id=user_id, error="OTP expired."), 422
        reset_token = secrets.token_urlsafe(32)
        user.reset_otp = f"tok:{reset_token}"
        user.reset_otp_expires = _now() + timedelta(minutes=15)
        db.commit()
        user_id = user.id
        db.close()
        return redirect(f"/auth/reset-password?user_id={user_id}&token={reset_token}", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/resend-reset-otp", methods=['POST'])
@_limiter().limit("5 per minute")
def resend_reset_otp():
    user_id = request.form.get("user_id", type=int)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            return jsonify({"error": "Cannot resend OTP"}), 400
        otp = generate_otp()
        user.reset_otp = otp
        user.reset_otp_expires = otp_expiry()
        db.commit()
        user_email = user.email
        user_username = user.username
        db.close()
        send_reset_otp(user_email, user_username, otp)
        return jsonify({"status": "sent"})
    except Exception:
        db.close()
        raise

@auth_bp.route("/reset-password", methods=['GET'])
def reset_password_page():
    user_id = request.args.get("user_id", type=int)
    token = request.args.get("token")
    return render_template("reset_password.html", user_id=user_id, token=token, errors=[])

@auth_bp.route("/reset-password", methods=['POST'])
@_limiter().limit("5 per minute")
def reset_password_submit():
    user_id = request.form.get("user_id", type=int)
    token = request.form.get("token")
    password = request.form.get("password")
    confirm = request.form.get("confirm_password")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.close()
            return render_template("reset_password.html", user_id=user_id, token=token, errors=["Invalid request."]), 422
        now = _now()
        expected = f"tok:{token}"
        if not user.reset_otp or user.reset_otp != expected:
            db.close()
            return render_template("reset_password.html", user_id=user_id, token=token, errors=["Invalid link."]), 422
        if user.reset_otp_expires and user.reset_otp_expires < now:
            db.close()
            return render_template("reset_password.html", user_id=user_id, token=token, errors=["Expired link."]), 422
        errors = []
        if password != confirm:
            errors.append("Passwords do not match.")
        else:
            errors.extend(validate_password_strength(password))
        if errors:
            db.close()
            return render_template("reset_password.html", user_id=user_id, token=token, errors=errors), 422
        user.hashed_password = hash_password(password)
        user.reset_otp = None
        user.reset_otp_expires = None
        db.commit()
        db.close()
        return redirect("/auth/login?reset=1", code=303)
    except Exception:
        db.close()
        raise

@auth_bp.route("/subscribe")
def subscribe_page():
    return render_template("subscribe.html")

# ── Helper to register blueprint ─────────────────────────────────────────
def init_auth_routes(app, limiter=None):
    _auth_limiter.init_app(app)
    app.register_blueprint(auth_bp)


@auth_bp.route("/blog")
def blog():
    return render_template("blog.html")