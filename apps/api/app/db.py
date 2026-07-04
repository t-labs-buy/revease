"""Tiny SQLite data layer (SQLAlchemy 2.0, sync). No migration ceremony for V1 —
`create_all` builds the schema; V2 can swap in Alembic without touching callers."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(
    _settings.resolved_database_url(),
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
    """WAL + busy_timeout so the API and Celery worker can share the SQLite file."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables, then additively add any new columns to existing tables
    (V1 has no migration tool; all schema changes so far are additive, and SQLite
    supports ADD COLUMN — this preserves local data without a `make clean`)."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            existing = {
                row[1] for row in conn.execute(text(f'PRAGMA table_info("{table.name}")'))
            }
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                default = getattr(col.default, "arg", None)
                if default is not None and not callable(default):
                    ddl += f" DEFAULT {default!r}" if isinstance(default, str) else f" DEFAULT {default}"
                conn.execute(text(ddl))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
