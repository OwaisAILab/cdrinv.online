"""
Auth Database - SQLite via SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Absolute path — always the same file regardless of where uvicorn is launched from
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = "sqlite:///" + os.path.join(_BASE_DIR, "cdr_portal.db")

DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_DB)

print(f"[DB] Using database: {DATABASE_URL}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
