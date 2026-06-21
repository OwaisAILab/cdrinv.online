"""
Standalone migration script — run ONCE if you are upgrading from an older
version that is missing columns.

    python migrate_db.py

Safe to re-run; existing columns are skipped automatically.
"""
import sqlite3, os

# Locate the database file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "cdr_portal.db")

if not os.path.exists(DB_PATH):
    for name in ("app.db", "database.db", "cdrinv.db"):
        candidate = os.path.join(BASE_DIR, name)
        if os.path.exists(candidate):
            DB_PATH = candidate
            break
    else:
        print("ERROR: Cannot find .db file. Edit DB_PATH at the top of this script.")
        raise SystemExit(1)

print(f"Using: {DB_PATH}")

COLUMNS = [
    ("uploads_used",          "INTEGER",  "DEFAULT 0"),
    ("login_otp_attempts",    "INTEGER",  "DEFAULT 0"),
    ("reset_otp",             "TEXT",     "DEFAULT NULL"),
    ("reset_otp_expires",     "DATETIME", "DEFAULT NULL"),
    ("pending_request_type",  "TEXT",     "DEFAULT NULL"),
    ("pending_plan",          "TEXT",     "DEFAULT NULL"),
]

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()
cur.execute("PRAGMA table_info(users)")
existing = {row[1] for row in cur.fetchall()}
print(f"Existing columns: {sorted(existing)}")

added = []
for col, dtype, default in COLUMNS:
    if col not in existing:
        cur.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype} {default}")
        added.append(col)
        print(f"  + Added: {col}")
    else:
        print(f"  ✓ OK:    {col}")

conn.commit()
conn.close()
print(f"\nDone. {len(added)} column(s) added: {added if added else 'none'}")
