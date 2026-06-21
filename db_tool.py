"""
CDR Portal — Database Management Tool
Run from the same folder as main.py:
    python db_tool.py

Commands available in the menu.
"""
import sys, os
# Make sure we run relative to the project root
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from auth.database import SessionLocal, engine
from auth.models import User, UserStatus, SubscriptionType, Base
from auth.utils import hash_password
from datetime import datetime, timedelta

Base.metadata.create_all(engine)
db = SessionLocal()

def divider(title=""):
    print("\n" + "─" * 55)
    if title:
        print(f"  {title}")
        print("─" * 55)

def list_users():
    divider("ALL USERS")
    users = db.query(User).all()
    if not users:
        print("  No users found.")
        return
    for u in users:
        print(f"\n  ID       : {u.id}")
        print(f"  Username : {u.username}")
        print(f"  Email    : {u.email}")
        print(f"  Status   : {u.status.value}")
        print(f"  Email OK : {u.email_verified}")
        print(f"  Sub Type : {u.subscription_type.value if u.subscription_type else '—'}")
        print(f"  Sub End  : {u.subscription_end}")
        print(f"  Txn ID   : {u.transaction_id}")
        print(f"  Created  : {u.created_at}")
        print(f"  Approved : {u.approved_at}")
        print(f"  {'─'*40}")

def approve_user():
    divider("APPROVE USER")
    uid = input("  Enter User ID to approve: ").strip()
    user = db.query(User).filter(User.id == int(uid)).first()
    if not user:
        print("  ✗ User not found.")
        return
    sub = input("  Subscription (6m / 1y) [1y]: ").strip() or "1y"
    now = datetime.now(timezone.utc)
    days = 183 if sub == "6m" else 365
    user.status             = UserStatus.ACTIVE
    user.email_verified     = True
    user.email_otp          = None
    user.email_otp_expires  = None
    user.subscription_start = now
    user.subscription_end   = now + timedelta(days=days)
    user.approved_at        = now
    db.commit()
    print(f"  ✓ User '{user.username}' approved. Expires: {user.subscription_end.date()}")

def force_status():
    divider("FORCE STATUS")
    uid = input("  Enter User ID: ").strip()
    user = db.query(User).filter(User.id == int(uid)).first()
    if not user:
        print("  ✗ User not found.")
        return
    print("  Statuses: pending_email / pending_payment / active / expired / rejected")
    new_status = input("  New status: ").strip()
    try:
        user.status = UserStatus(new_status)
        db.commit()
        print(f"  ✓ Status updated to '{new_status}'")
    except Exception as e:
        print(f"  ✗ Error: {e}")

def delete_user():
    divider("DELETE USER")
    uid = input("  Enter User ID to delete: ").strip()
    user = db.query(User).filter(User.id == int(uid)).first()
    if not user:
        print("  ✗ User not found.")
        return
    confirm = input(f"  Delete '{user.username}' ({user.email})? (yes/no): ").strip()
    if confirm.lower() == "yes":
        db.delete(user)
        db.commit()
        print(f"  ✓ User deleted.")
    else:
        print("  Cancelled.")

def delete_by_email():
    divider("DELETE USER BY EMAIL")
    email = input("  Enter email to delete: ").strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        print(f"  ✗ No user with email '{email}'.")
        return
    confirm = input(f"  Delete '{user.username}'? (yes/no): ").strip()
    if confirm.lower() == "yes":
        db.delete(user)
        db.commit()
        print("  ✓ User deleted.")
    else:
        print("  Cancelled.")

def reset_password():
    divider("RESET PASSWORD")
    uid = input("  Enter User ID: ").strip()
    user = db.query(User).filter(User.id == int(uid)).first()
    if not user:
        print("  ✗ User not found.")
        return
    new_pw = input("  New password: ").strip()
    user.hashed_password = hash_password(new_pw)
    db.commit()
    print(f"  ✓ Password updated for '{user.username}'")

def show_db_path():
    divider("DATABASE PATH")
    from auth.database import DATABASE_URL
    print(f"  URL : {DATABASE_URL}")
    import sqlite3, os
    db_path = DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
    abs_path = os.path.abspath(db_path)
    print(f"  File: {abs_path}")
    print(f"  Exists: {os.path.exists(abs_path)}")

def menu():
    while True:
        divider("CDR PORTAL — DB TOOL")
        print("  1. List all users")
        print("  2. Approve a user (force active)")
        print("  3. Force set user status")
        print("  4. Delete user by ID")
        print("  5. Delete user by email")
        print("  6. Reset user password")
        print("  7. Show database file path")
        print("  0. Exit")
        divider()
        choice = input("  Choice: ").strip()
        if   choice == "1": list_users()
        elif choice == "2": approve_user()
        elif choice == "3": force_status()
        elif choice == "4": delete_user()
        elif choice == "5": delete_by_email()
        elif choice == "6": reset_password()
        elif choice == "7": show_db_path()
        elif choice == "0": break
        else: print("  Invalid choice.")

if __name__ == "__main__":
    menu()
    db.close()
