from contextlib import contextmanager, asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

# ---------------------------------------------------------------------------
# Sync engine (legacy, used by background threads & sync routes)
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

# ---------------------------------------------------------------------------
# SQLite tuning
#
# This app runs many concurrent writers against one SQLite file: a thread per
# active recording, the monitor loop, the transcription dispatcher, live-chat
# listeners and the shared background pool.  Without these PRAGMAs the default
# rollback journal serialises readers against writers and any contention
# surfaces immediately as "database is locked".
#
#   journal_mode=WAL  -- readers no longer block the writer (and vice versa)
#   busy_timeout      -- wait for a held lock instead of failing instantly
#   synchronous=NORMAL-- safe under WAL, far fewer fsyncs
#   foreign_keys=ON   -- SQLite leaves FK enforcement off by default
# ---------------------------------------------------------------------------

def _is_sqlite(dbapi_connection) -> bool:
    return type(dbapi_connection).__module__.startswith("sqlite3")


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    if not _is_sqlite(dbapi_connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# Async engine (hot-path routes)
# ---------------------------------------------------------------------------

ASYNC_DATABASE_URL = settings.DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------

Base = declarative_base()

# -- Shared thread pool for fire-and-forget background tasks ----------
#
# Short work only: thumbnails, sprite sheets, avatar fetches.  Anything that
# runs for minutes belongs on its own pool -- see recovery_executor.
background_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="bg",
)

# -- Dedicated pool for long-running recovery work --------------------
#
# Orphan recovery runs a full ffmpeg finalize, which can take minutes.  It used
# to share the 2-worker pool above, so two orphans at startup blocked every
# thumbnail and avatar fetch until they finished.  One worker, because these
# are ffmpeg-bound and running several at once only thrashes the disk.
recovery_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="recovery",
)


def run_background(fn, *args, **kwargs):
    """Submit a short fire-and-forget callable to the shared background pool."""
    return background_executor.submit(fn, *args, **kwargs)


def run_recovery(fn, *args, **kwargs):
    """Submit long-running recovery work to its own pool."""
    return recovery_executor.submit(fn, *args, **kwargs)


# -- DB session management --------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def async_get_db():
    """Async context / FastAPI dependency for hot-path endpoints.

    Usage in route files::

        async def list_users(db: AsyncSession = Depends(async_get_db)):
            ...
    """
    async with AsyncSessionLocal() as db:
        yield db


@contextmanager
def get_session():
    """Context manager for short-lived background DB sessions.

    Usage::

        with get_session() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from pathlib import Path
    from alembic.config import Config as AlembicConfig
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    alembic_cfg = AlembicConfig(
        str(Path(__file__).resolve().parent.parent.parent / "alembic.ini")
    )

    inspector = inspect(engine)

    if "alembic_version" not in inspector.get_table_names():
        # Completely fresh database — create all tables from models,
        # then stamp at head so Alembic knows the schema is current.
        # Running command.upgrade() afterwards would attempt to
        # CREATE TABLE for new models (e.g. live_events) that already
        # exist from create_all() → crash on SQLite.
        from app.db import models
        Base.metadata.create_all(bind=engine)
        command.stamp(alembic_cfg, "head")
        return

    # If alembic_version references a revision whose migration file no longer
    # exists (e.g. after replacing an initial "create all tables" migration
    # with an empty baseline), clear the stale entry so Alembic can start fresh.
    if "alembic_version" in inspector.get_table_names():
        with engine.begin() as conn:
            stored = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        if stored is not None:
            try:
                ScriptDirectory.from_config(alembic_cfg).get_revision(stored)
            except KeyError:
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM alembic_version"))

    command.upgrade(alembic_cfg, "head")
