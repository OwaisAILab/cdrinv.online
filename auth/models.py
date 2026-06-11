"""
ORM Models for CDR Portal Auth
"""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.sql import func
import enum
from auth.database import Base
from typing import Dict, List

class SubscriptionType(str, enum.Enum):
    ONE_MONTH  = "1_month"
    SIX_MONTHS = "6_months"
    ONE_YEAR   = "1_year"


# Max CDRs allowed per plan (None = unlimited).
PLAN_CDR_LIMIT: Dict[str, int | None] = {
    "1_month":  30,
    "6_months": None,
    "1_year":   None
}

# Subscription duration in days per plan.
PLAN_DURATION_DAYS: Dict[str, int] = {
    "1_month":  30,
    "6_months": 180,
    "1_year":   365,
}

# Human-readable plan labels
PLAN_LABELS: Dict[str, str] = {
    "1_month":  "Basic (1 Month)",
    "6_months": "Standard (6 Months)",
    "1_year":   "Extended (1 Year)",
}


class UserStatus(str, enum.Enum):
    PENDING_EMAIL   = "pending_email"    # OTP not yet verified
    PENDING_PAYMENT = "pending_payment"  # OTP ok, awaiting admin approval
    ACTIVE          = "active"           # Admin approved
    EXPIRED         = "expired"          # Subscription lapsed
    REJECTED        = "rejected"         # Admin rejected


class User(Base):
    __tablename__ = "users"

    id                    = Column(Integer, primary_key=True, index=True)
    username              = Column(String(100), unique=True, index=True, nullable=False)
    email                 = Column(String(200), unique=True, index=True, nullable=False)
    hashed_password       = Column(String(255), nullable=False)
    transaction_id        = Column(String(100), nullable=False)
    subscription_type     = Column(SAEnum(SubscriptionType), nullable=False)
    cdr_limit             = Column(Integer, nullable=True)   # NULL = unlimited
    status                = Column(SAEnum(UserStatus), default=UserStatus.PENDING_EMAIL)
    email_otp             = Column(String(10), nullable=True)
    email_otp_expires     = Column(DateTime, nullable=True)
    email_verified        = Column(Boolean, default=False)
    login_otp             = Column(String(10), nullable=True)
    login_otp_expires     = Column(DateTime, nullable=True)
    login_otp_attempts    = Column(Integer, default=0, nullable=False)  # brute-force guard
    reset_otp             = Column(String(10), nullable=True)
    reset_otp_expires     = Column(DateTime, nullable=True)
    subscription_start    = Column(DateTime, nullable=True)
    subscription_end      = Column(DateTime, nullable=True)
    created_at            = Column(DateTime, server_default=func.now())
    approved_at           = Column(DateTime, nullable=True)
    uploads_used          = Column(Integer, default=0, nullable=False)

    # Tracks what kind of pending request is in the queue so admin can distinguish
    # None  = new registration
    # "renewal" = same-or-any plan renewal by existing user
    # "upgrade" = plan upgrade by existing user
    pending_request_type  = Column(String(20), nullable=True)

    # Stores the plan the user *requested* (upgrade/renewal) before admin approves.
    # The live subscription_type is NOT changed until admin approves.
    pending_plan          = Column(String(20), nullable=True)

    @property
    def uploads_remaining(self):
        """Number of remaining single CDR uploads for Basic users."""
        if self.subscription_type == SubscriptionType.ONE_MONTH:
            limit = self.cdr_limit or 30
            remaining = limit - (self.uploads_used or 0)
            return remaining if remaining > 0 else 0
        return None   # unlimited for Standard / Extended

    @property
    def days_remaining(self) -> int:
        if self.subscription_end:
            now = datetime.utcnow()
            end = self.subscription_end
            # Normalise: strip tzinfo if present (SQLite stores naive UTC)
            if hasattr(end, 'tzinfo') and end.tzinfo is not None:
                end = end.replace(tzinfo=None)
            if end > now:
                return (end - now).days
        return 0