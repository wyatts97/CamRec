from datetime import datetime
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db, get_session, run_background, run_recovery
from app.db.models import Recording
from app.core.media_utils import (
    analyze_video_health,
    finalize_segments_to_mp4,
    generate_thumbnail,
    generate_sprite,
    thumbnail_path,
    recording_path,
)
from app.core.auth import require_auth
from app.api.routes import (
    auth as auth_routes,
    users,
    recordings,
    clips,
    settings as settings_routes,
    storage as storage_routes,
    notifications as notifications_routes,
)
from app.core.task_manager import task_manager, monitor_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class _HealthCheckFilter(logging.Filter):
    """Drop access-log lines for /api/health (the Docker healthcheck fires
    every 30s and was most of the backend log)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/health " not in record.getMessage()


def _quiet_noisy_loggers() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HealthCheckFilter) for f in access.filters):
        access.addFilter(_HealthCheckFilter())
    # httpx logs every request at INFO with the full URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)


_quiet_noisy_loggers()


def _find_orphan_sources(video_path: Path) -> list[Path]:
    """Return any leftover capture segments for a recording whose task died."""
    stem_path = video_path.with_suffix("")
    parts = sorted(
        p for p in video_path.parent.glob(f"{stem_path.name}.part*.ts")
        if p.exists() and p.stat().st_size > 0
    )
    if parts:
        return parts
    lone_ts = video_path.with_suffix(".ts")
    if lone_ts.exists() and lone_ts.stat().st_size > 0:
        return [lone_ts]
    return []


def _recover_orphaned_recording(recording_id: int, filename: str) -> None:
    """Background finalize for a recording left in 'recording'/'processing' after a crash."""
    video_path = recording_path(filename)
    sources = _find_orphan_sources(video_path)
    if not sources:
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == recording_id).first()
            if rec and rec.status in ("recording", "processing"):
                rec.status = "failed"
                rec.is_corrupt = True
                rec.ended_at = datetime.utcnow()
                rec.error_message = rec.error_message or "Recording orphaned after restart — no capture files found"
                db.commit()
                logger.warning("No capture files for orphan recording %d; marked failed", recording_id)
        return

    logger.info("Recovering orphan recording %d from %d source(s)", recording_id, len(sources))
    try:
        ok, actual_duration = finalize_segments_to_mp4(sources, video_path)
    except Exception:
        logger.exception("Orphan recovery finalize raised for recording %d", recording_id)
        ok = False

    if ok and video_path.exists() and video_path.stat().st_size > 0:
        for src in sources:
            src.unlink(missing_ok=True)
        health = analyze_video_health(video_path)
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == recording_id).first()
            if rec:
                rec.status = "stopped" if rec.status == "stopped" else "completed"
                rec.is_corrupt = health.get("is_corrupt", False)
                rec.ended_at = datetime.utcnow()
                rec.file_size = video_path.stat().st_size
                rec.duration_seconds = int(round(actual_duration)) if actual_duration else rec.duration_seconds
                rec.error_message = None
                db.commit()
        run_background(generate_thumbnail, video_path, thumbnail_path(video_path), recording_id)
        run_background(generate_sprite, video_path)
        logger.info("Orphan recording %d recovered successfully", recording_id)
    else:
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == recording_id).first()
            if rec and rec.status in ("recording", "processing"):
                rec.status = "failed"
                rec.is_corrupt = True
                rec.ended_at = datetime.utcnow()
                rec.error_message = rec.error_message or "Orphan recovery failed — could not finalize capture"
                db.commit()
        logger.error("Orphan recovery failed for recording %d; sources kept for manual repair", recording_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Alembic's env.py calls fileConfig() which resets root logger to
    # WARNING (from alembic.ini).  Restore to INFO so app logs are visible.
    logging.getLogger().setLevel(logging.INFO)
    _quiet_noisy_loggers()
    monitor_service.start()

    # Reconcile orphaned recordings from previous container restarts.
    # Rows stuck in 'recording'/'processing' with no running task are either
    # failed or recoverable from the leftover .ts/.part files on disk.
    with get_session() as db:
        orphaned = (
            db.query(Recording)
            .filter(Recording.status.in_(("recording", "processing")))
            .all()
        )
        for rec in orphaned:
            if task_manager.is_recording(rec.id):
                continue
            sources = _find_orphan_sources(recording_path(rec.filename))
            if sources:
                run_recovery(_recover_orphaned_recording, rec.id, rec.filename)
            else:
                rec.status = "failed"
                rec.is_corrupt = True
                rec.ended_at = datetime.utcnow()
                rec.error_message = rec.error_message or "Recording orphaned after app restart"
                db.commit()
                logger.warning(
                    "Reconciled orphaned recording %d for %s (%s)",
                    rec.id, rec.user.username, rec.filename,
                )

    yield
    monitor_service.stop()
    task_manager.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    description="Live cam recorder",
    version="1.0.0",
    lifespan=lifespan,
    # The docs enumerate every endpoint; keep them off on an internet-facing
    # deployment unless explicitly enabled.
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# An explicit origin list is required: "*" together with allow_credentials
# makes Starlette echo back any Origin, which would let any site the user
# visits drive this API with their session cookie.
_allowed_origins = [o for o in settings.ALLOWED_ORIGINS if o != "*"]
if len(_allowed_origins) != len(settings.ALLOWED_ORIGINS):
    logger.error('ALLOWED_ORIGINS contained "*"; ignoring it (unsafe with credentials)')

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Login/logout must stay reachable without a session.
app.include_router(auth_routes.router, prefix="/api")

# Auth is applied at include time rather than per-endpoint so a newly added
# route cannot accidentally ship unprotected.
_protected = Depends(require_auth)
for _router in (
    users.router,
    recordings.router,
    clips.router,
    settings_routes.router,
    storage_routes.router,
    notifications_routes.router,
):
    app.include_router(_router, prefix="/api", dependencies=[_protected])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/")
def root():
    return {
        "message": "CamSuite API",
        "docs": "/docs",
        "health": "/api/health"
    }
