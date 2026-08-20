"""Conexión a base de datos — patrón de backend_gal.

Env-driven: si DATABASE_URL apunta a PostgreSQL (Neon), se usa Postgres.
Sin DATABASE_URL se usa SQLite local para desarrollo.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./local_test.db"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

IS_POSTGRES = engine.dialect.name == "postgresql"

API_KEY = os.getenv("WASI_API_KEY")
ADMIN_PASSWORD = os.getenv("WASI_ADMIN_PASSWORD")
TALLER_PASSWORD = os.getenv("WASI_TALLER_PASSWORD")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()