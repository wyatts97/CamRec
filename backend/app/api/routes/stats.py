"""Analytics & storage statistics endpoints.

Aggregates data already captured in the Recording / Clip / LiveEvent / User
tables to power the Stats (analytics) and Storage-management pages.
All queries are read-only and use lightweight SQL aggregates.
"""
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import Recording, Clip, LiveEvent, User

router = APIRouter(prefix="/stats", tags=["stats"])

# Statuses that represent a recording with an on-disk file worth counting.
_FINISHED = ("completed", "stopped", "failed")
_PLAYABLE = ("completed", "stopped")


@router.get("/overview")
def stats_overview(db: Session = Depends(get_db)):
    """High-level totals for the analytics dashboard headline cards."""
    total_recordings = (
        db.query(func.count(Recording.id))
        .filter(Recording.status.in_(_PLAYABLE))
        .scalar()
        or 0
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
    clip_storage = (
        db.query(func.coalesce(func.sum(Clip.file_size), 0)).scalar() or 0
    )
    total_clips = db.query(func.count(Clip.id)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    monitored_users = (
        db.query(func.count(User.id)).filter(User.is_monitoring == True).scalar() or 0  # noqa: E712
    )
    total_chat = (
        db.query(func.count(LiveEvent.id))
        .filter(LiveEvent.event_type == "chat")
        .scalar()
        or 0
    )
    total_gifts = (
        db.query(func.count(LiveEvent.id))
        .filter(LiveEvent.event_type == "gift")
        .scalar()
        or 0
    )
    total_diamonds = (
        db.query(
            func.coalesce(
                func.sum(LiveEvent.gift_diamond_count * LiveEvent.gift_repeat_count), 0
            )
        )
        .filter(LiveEvent.event_type == "gift")
        .scalar()
        or 0
    )

    return {
        "total_recordings": int(total_recordings),
        "total_hours": round(int(total_seconds) / 3600, 1),
        "total_seconds": int(total_seconds),
        "total_storage": int(total_storage),
        "clip_storage": int(clip_storage),
        "total_clips": int(total_clips),
        "total_users": int(total_users),
        "monitored_users": int(monitored_users),
        "total_chat_messages": int(total_chat),
        "total_gifts": int(total_gifts),
        "total_diamonds": int(total_diamonds),
    }


@router.get("/recordings-per-day")
def recordings_per_day(days: int = 30, db: Session = Depends(get_db)):
    """Count of recordings created per day over the trailing *days* window."""
    days = max(1, min(days, 365))
    cutoff = datetime.utcnow() - timedelta(days=days - 1)
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        db.query(
            func.date(Recording.created_at).label("day"),
            func.count(Recording.id).label("count"),
            func.coalesce(func.sum(Recording.duration_seconds), 0).label("seconds"),
        )
        .filter(Recording.created_at >= cutoff)
        .group_by(func.date(Recording.created_at))
        .all()
    )
    by_day = {str(r.day): {"count": int(r.count), "seconds": int(r.seconds)} for r in rows}

    # Fill gaps so the chart has a continuous x-axis.
    out = []
    for i in range(days):
        d = (cutoff + timedelta(days=i)).date().isoformat()
        entry = by_day.get(d, {"count": 0, "seconds": 0})
        out.append({
            "date": d,
            "count": entry["count"],
            "hours": round(entry["seconds"] / 3600, 2),
        })
    return out


@router.get("/top-streamers")
def top_streamers(limit: int = 10, db: Session = Depends(get_db)):
    """Most-recorded users by recording count and total recorded time."""
    limit = max(1, min(limit, 50))
    rows = (
        db.query(
            User.id.label("user_id"),
            User.username.label("username"),
            func.count(Recording.id).label("count"),
            func.coalesce(func.sum(Recording.duration_seconds), 0).label("seconds"),
        )
        .join(Recording, Recording.user_id == User.id)
        .filter(Recording.status.in_(_PLAYABLE))
        .group_by(User.id)
        .order_by(func.count(Recording.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "user_id": r.user_id,
            "username": r.username,
            "count": int(r.count),
            "hours": round(int(r.seconds) / 3600, 2),
        }
        for r in rows
    ]


@router.get("/storage-by-user")
def storage_by_user(limit: int = 20, db: Session = Depends(get_db)):
    """Total on-disk storage and recording count grouped by user."""
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
        {
            "user_id": r.user_id,
            "username": r.username,
            "count": int(r.count),
            "bytes": int(r.bytes),
        }
        for r in rows
    ]


@router.get("/gift-chat-volume")
def gift_chat_volume(limit: int = 10, db: Session = Depends(get_db)):
    """Per-stream chat-message and gift-diamond volume (top streams by activity)."""
    limit = max(1, min(limit, 50))
    rows = (
        db.query(
            LiveEvent.recording_id.label("recording_id"),
            func.sum(
                case((LiveEvent.event_type == "chat", 1), else_=0)
            ).label("chat_count"),
            func.sum(
                case((LiveEvent.event_type == "gift", 1), else_=0)
            ).label("gift_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            LiveEvent.event_type == "gift",
                            LiveEvent.gift_diamond_count * LiveEvent.gift_repeat_count,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("diamonds"),
        )
        .group_by(LiveEvent.recording_id)
        .order_by(func.count(LiveEvent.id).desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return []

    rec_ids = [r.recording_id for r in rows]
    recs = (
        db.query(Recording.id, User.username)
        .join(User, Recording.user_id == User.id)
        .filter(Recording.id.in_(rec_ids))
        .all()
    )
    name_map = {rid: uname for rid, uname in recs}

    return [
        {
            "recording_id": r.recording_id,
            "username": name_map.get(r.recording_id, "unknown"),
            "chat_count": int(r.chat_count or 0),
            "gift_count": int(r.gift_count or 0),
            "diamonds": int(r.diamonds or 0),
        }
        for r in rows
    ]


@router.get("/largest-recordings")
def largest_recordings(limit: int = 20, db: Session = Depends(get_db)):
    """Largest recordings on disk — powers the storage-management view."""
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


@router.get("/storage")
def storage_stats(db: Session = Depends(get_db)):
    """Category-level storage breakdown and disk usage for the Storage page."""
    recording_storage = (
        db.query(func.coalesce(func.sum(Recording.file_size), 0))
        .filter(Recording.status.in_(_FINISHED))
        .scalar()
        or 0
    )
    clip_storage = (
        db.query(func.coalesce(func.sum(Clip.file_size), 0)).scalar() or 0
    )
    total_recordings = db.query(func.count(Recording.id)).filter(Recording.status.in_(_FINISHED)).scalar() or 0
    total_clips = db.query(func.count(Clip.id)).scalar() or 0

    # Backup ZIPs in the data/backups directory
    backup_storage = 0
    backup_count = 0
    backups_dir = Path(settings.DATA_DIR) / "backups"
    if backups_dir.exists():
        for p in backups_dir.iterdir():
            if p.is_file() and p.suffix == ".zip":
                backup_storage += p.stat().st_size
                backup_count += 1

    # Disk usage of the filesystem hosting recordings
    disk_target = settings.RECORDINGS_DIR if settings.RECORDINGS_DIR.exists() else settings.RECORDINGS_DIR.parent
    try:
        du = shutil.disk_usage(disk_target)
        disk_usage = {
            "total": du.total,
            "used": du.used,
            "free": du.free,
            "percent": round(du.used / du.total * 100, 1),
        }
    except OSError:
        disk_usage = None

    return {
        "total_storage": int(recording_storage) + int(clip_storage) + int(backup_storage),
        "recording_storage": int(recording_storage),
        "clip_storage": int(clip_storage),
        "backup_storage": int(backup_storage),
        "backup_count": int(backup_count),
        "total_recordings": int(total_recordings),
        "total_clips": int(total_clips),
        "disk_usage": disk_usage,
    }
