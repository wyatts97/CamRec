"""Storage statistics endpoints for the Storage page and dashboard counters."""
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import Recording, Clip, User

router = APIRouter(prefix="/storage", tags=["storage"])

# Statuses that represent a recording with an on-disk file worth counting.
_FINISHED = ("completed", "stopped", "failed")
_PLAYABLE = ("completed", "stopped")


def _disk_usage() -> dict | None:
    disk_target = settings.RECORDINGS_DIR if settings.RECORDINGS_DIR.exists() else settings.RECORDINGS_DIR.parent
    try:
        du = shutil.disk_usage(disk_target)
    except OSError:
        return None
    return {
        "total": du.total,
        "used": du.used,
        "free": du.free,
        "percent": round(du.used / du.total * 100, 1),
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Headline counters for the dashboard."""
    total_recordings = (
        db.query(func.count(Recording.id)).filter(Recording.status.in_(_PLAYABLE)).scalar() or 0
    )
    total_seconds = (
        db.query(func.coalesce(func.sum(Recording.duration_seconds), 0))
        .filter(Recording.status.in_(_PLAYABLE))
        .scalar()
        or 0
    )
    total_storage = (
        db.query(func.coalesce(func.sum(Recording.file_size), 0))
        .filter(Recording.status.in_(_FINISHED))
        .scalar()
        or 0
    )
    watchlist = db.query(func.count(User.id)).filter(User.is_on_watchlist == True).scalar() or 0  # noqa: E712
    monitored = (
        db.query(func.count(User.id))
        .filter(User.is_on_watchlist == True, User.is_monitoring == True)  # noqa: E712
        .scalar()
        or 0
    )
    return {
        "total_recordings": int(total_recordings),
        "total_hours": round(int(total_seconds) / 3600, 1),
        "total_storage": int(total_storage),
        "clip_storage": int(db.query(func.coalesce(func.sum(Clip.file_size), 0)).scalar() or 0),
        "total_clips": int(db.query(func.count(Clip.id)).scalar() or 0),
        "total_users": int(watchlist),
        "monitored_users": int(monitored),
    }


@router.get("")
def storage_stats(db: Session = Depends(get_db)):
    """Category-level storage breakdown and disk usage."""
    recording_storage = (
        db.query(func.coalesce(func.sum(Recording.file_size), 0))
        .filter(Recording.status.in_(_FINISHED))
        .scalar()
        or 0
    )
    clip_storage = db.query(func.coalesce(func.sum(Clip.file_size), 0)).scalar() or 0
    total_recordings = db.query(func.count(Recording.id)).filter(Recording.status.in_(_FINISHED)).scalar() or 0
    total_clips = db.query(func.count(Clip.id)).scalar() or 0

    # Backup ZIPs written by auto-cleanup / compress.
    backup_storage = 0
    backup_count = 0
    backups_dir = Path(settings.DATA_DIR) / "backups"
    if backups_dir.exists():
        for p in backups_dir.iterdir():
            if p.is_file() and p.suffix == ".zip":
                backup_storage += p.stat().st_size
                backup_count += 1

    return {
        "total_storage": int(recording_storage) + int(clip_storage) + int(backup_storage),
        "recording_storage": int(recording_storage),
        "clip_storage": int(clip_storage),
        "backup_storage": int(backup_storage),
        "backup_count": int(backup_count),
        "total_recordings": int(total_recordings),
        "total_clips": int(total_clips),
        "disk_usage": _disk_usage(),
    }


@router.get("/by-user")
def storage_by_user(limit: int = 20, db: Session = Depends(get_db)):
    """Total on-disk storage and recording count grouped by model."""
    limit = max(1, min(limit, 100))
    rows = (
        db.query(
            User.id.label("user_id"),
            User.username.label("username"),
            func.count(Recording.id).label("count"),
            func.coalesce(func.sum(Recording.file_size), 0).label("bytes"),
        )
        .join(Recording, Recording.user_id == User.id)
        .filter(Recording.status.in_(_FINISHED))
        .group_by(User.id)
        .order_by(func.coalesce(func.sum(Recording.file_size), 0).desc())
        .limit(limit)
        .all()
    )
    return [
        {"user_id": r.user_id, "username": r.username, "count": int(r.count), "bytes": int(r.bytes)}
        for r in rows
    ]


@router.get("/largest")
def largest_recordings(limit: int = 20, db: Session = Depends(get_db)):
    """Largest recordings on disk."""
    limit = max(1, min(limit, 100))
    rows = (
        db.query(Recording, User.username)
        .join(User, Recording.user_id == User.id)
        .filter(Recording.status.in_(_FINISHED))
        .filter(Recording.file_size.isnot(None))
        .order_by(Recording.file_size.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": rec.id,
            "username": uname,
            "filename": rec.filename,
            "file_size": int(rec.file_size or 0),
            "duration_seconds": rec.duration_seconds,
            "status": rec.status,
            "created_at": rec.created_at,
        }
        for rec, uname in rows
    ]
