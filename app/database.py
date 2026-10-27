"""SQLAlchemy engine, session factory and base class."""
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

log = logging.getLogger("vibeguard.db")

# SQLite needs check_same_thread=False when used across FastAPI's threadpool.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,  # survive dropped connections on managed Postgres
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns() -> None:
    """Tiny auto-migration: add columns that exist in models but not in the DB.

    create_all() only creates missing *tables*; this covers new columns added in
    later versions so an existing Railway Postgres keeps working after updates.
    """
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=engine.dialect)}'
            if col.server_default is not None:
                ddl += f" DEFAULT '{col.server_default.arg}'"
            with engine.begin() as conn:
                conn.execute(text(ddl))
            log.info("migrated: %s", ddl)


def init_db() -> None:
    """Create tables and add new columns. Safe to call on every startup."""
    from . import models  # noqa: F401  (register models on Base)
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
