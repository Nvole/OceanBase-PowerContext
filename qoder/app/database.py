"""Database configuration.

Reads connection parameters from environment variables.
Supports seekdb (MySQL protocol) via PyMySQL, with SQLite fallback for local dev.
"""
import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base

# Environment variables for seekdb (MySQL protocol compatible)
SEEKDB_HOST = os.getenv("SEEKDB_HOST", "")
SEEKDB_PORT = os.getenv("SEEKDB_PORT", "2881")
SEEKDB_USER = os.getenv("SEEKDB_USER", "")
SEEKDB_PASSWORD = os.getenv("SEEKDB_PASSWORD", "")
SEEKDB_DATABASE = os.getenv("SEEKDB_DATABASE", "qoder_research")

# Use SQLite fallback when no seekdb host is configured
USE_SQLITE = not SEEKDB_HOST

if USE_SQLITE:
    sqlite_path = Path(os.getenv("QODER_SQLITE_PATH", "data/research.db")).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = URL.create("sqlite", database=str(sqlite_path))
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    
    # Enable WAL mode for better concurrent access
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
else:
    # seekdb uses MySQL protocol; PyMySQL driver
    DATABASE_URL = URL.create(
        "mysql+pymysql", username=SEEKDB_USER, password=SEEKDB_PASSWORD,
        host=SEEKDB_HOST, port=int(SEEKDB_PORT), database=SEEKDB_DATABASE,
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        pool_recycle=3600,
        pool_pre_ping=True,
        echo=False,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)
