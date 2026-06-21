from auth.database import Base, engine
from auth.models import User  # noqa – registers model with Base
from sqlalchemy import text

# All columns that may be missing from an older database.
# Each entry: (column_name, SQLite_type, default_clause)
_MISSING_COLUMNS = [
    ("uploads_used",          "INTEGER",  "DEFAULT 0"),
    ("login_otp_attempts",    "INTEGER",  "DEFAULT 0"),
    ("reset_otp",             "TEXT",     "DEFAULT NULL"),
    ("reset_otp_expires",     "DATETIME", "DEFAULT NULL"),
    ("pending_request_type",  "TEXT",     "DEFAULT NULL"),
    ("pending_plan",          "TEXT",     "DEFAULT NULL"),
]

def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for col, dtype, default in _MISSING_COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {dtype} {default}"))
                conn.commit()
                print(f"[DB] Migrated: added column '{col}'")
            except Exception:
                # Column already exists — safe to skip
                pass
