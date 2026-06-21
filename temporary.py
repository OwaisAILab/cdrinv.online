import sqlite3

conn = sqlite3.connect("cdr_portal.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN uploads_used INTEGER DEFAULT 0")
    conn.commit()
    print("✓ Column 'uploads_used' added successfully.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Column already exists.")
    else:
        print(f"Error: {e}")

conn.close()