"""Data layer (SQLAlchemy 2.0, sync) for SQLite (default, single host) or
Postgres (`REFRACT_DATABASE_URL=postgresql+psycopg://…`).

Why Postgres at all: SQLite allows one writer at a time. With several workers
heartbeating job progress, a render and an upload all writing, writers queue
behind `busy_timeout`. Postgres removes that ceiling and lets workers live on
other machines (they no longer need the SQLite file on a shared disk).

Schema changes stay additive and tool-free: `create_all` builds new tables and
`_ensure_columns` adds new nullable/defaulted columns to existing ones. It reads
columns through SQLAlchemy's inspector, so it works on both dialects.
Copy an existing SQLite database into Postgres with `python -m app.dbcopy`.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
DATABASE_URL = _settings.resolved_database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, future=True)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
        """WAL + busy_timeout so the API and Celery worker can share the SQLite file."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
else:
    # pre_ping: survive Postgres restarts / idle connection drops between jobs.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10,
                           pool_recycle=1800, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables, then additively add any new columns to existing tables
    (all schema changes so far are additive — this preserves data without a
    migration tool on either dialect)."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                default = getattr(col.default, "arg", None)
                if default is not None and not callable(default):
                    if isinstance(default, bool):
                        ddl += f" DEFAULT {'TRUE' if default else 'FALSE'}" if not IS_SQLITE else f" DEFAULT {int(default)}"
                    elif isinstance(default, str):
                        ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                    else:
                        ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
