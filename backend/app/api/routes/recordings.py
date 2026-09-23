import os
import re
import json
import time
import threading
import logging
import shutil

from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db.database import get_db, get_session, run_background
from app.db.models import Recording, User
from app.schemas.recording import (
    RecordingStart,
    RecordingResponse,
    RecordingListResponse,
    ActiveRecordingResponse
)
from app.schemas.user import USERNAME_PATTERN
from app.core.site_service import site_service
from app.core.task_manager import task_manager
from app.core.live_clip_service import live_clip_service
from app.core.media_utils import (
    generate_recording_filename,
    generate_sprite,
    generate_thumbnail,
    thumbnail_path,
    thumbnail_media_type,
    all_thumbnail_paths,
    analyze_video_health,
    repair_video,
    finalize_segments_to_mp4,
    recording_path,
    render_sprite_vtt,
    sprite_paths,
    sprite_vtt_version,
    SPRITE_VERSION,
)
from app.core.settings_store import settings_store

logger = logging.getLogger("camsuite.recordings")


router = APIRouter(prefix="/recordings", tags=["recordings"])


# Debounce registry for background thumbnail/sprite regeneration.
#
# These are touched from request threads, so they need a lock.  They are also
# time-bounded: an earlier implementation used plain sets that were only ever
# added to, which permanently blocked a recording from ever retrying after one
# failed attempt and leaked an entry per recording for the process lifetime.
_RETRY_COOLDOWN_SECONDS = 300

_retry_lock = threading.Lock()
_thumb_retry_at: dict[int, float] = {}
_sprite_retry_at: dict[int, float] = {}


def _claim_retry(registry: dict[int, float], recording_id: int) -> bool:
    """Reserve a background retry slot, or return False if one is still cooling down."""
    now = time.monotonic()
    with _retry_lock:
        # Opportunistically drop expired entries so the dict cannot grow without bound.
        for rec_id, started in list(registry.items()):
            if now - started > _RETRY_COOLDOWN_SECONDS:
                del registry[rec_id]
        if recording_id in registry:
            return False
        registry[recording_id] = now
        return True


def _delete_recording_files(recording: Recording) -> list[str]:
    """Delete all on-disk assets for a recording.

    Removes the main video file, thumbnail, sprite sheet, and sprite VTT.
    Returns a list of error messages (empty iff all deletions succeeded).
    """
    errors: list[str] = []
    video_path = recording_path(recording.filename)

    assets = [
        ("video", video_path),
        *[("thumbnail", p) for p in all_thumbnail_paths(video_path)],
        ("sprite", video_path.with_name(video_path.stem + "_sprite.jpg")),
        ("sprite VTT", video_path.with_name(video_path.stem + "_sprite.vtt")),
    ]

    for label, path in assets:
        if path.exists():
            try:
                os.remove(path)
                logger.info("Deleted %s file: %s", label, path)
            except OSError as e:
                msg = f"Failed to delete {label} for recording {recording.id} ({path.name}): {e}"
                errors.append(msg)
                logger.warning(msg)

    return errors


def _find_capture_sources(video_path: Path) -> list[Path]:
    """Return the raw capture sources for a recording whose ``.mp4`` is missing.

    A finalize/remux failure keeps the intermediate MPEG-TS on disk: either the
    resumable ``.partNNN.ts`` segments or a single legacy ``.ts``. This lets the
    repair endpoint recover a recording even when the final ``.mp4`` was never
    produced (the "needs repair" → "no recording found" bug).
    """
    stem_path = video_path.with_suffix("")  # strip .mp4
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


def _is_thumbnail_ready(recording: Recording, db: Session | None = None) -> bool:
    # Fast path: trust the cached DB flag and avoid a filesystem stat.
    if recording.thumbnail_ready:
        return True

    video_path = recording_path(recording.filename)
    thumb_path = thumbnail_path(video_path)
    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        # Files exist but DB is out of sync — fix it.
        if db is not None:
            recording.thumbnail_ready = True
            db.commit()
        return True

    # Kick off a background retry for finished recordings that lost their thumbnail
    if (
        recording.status in ("completed", "stopped", "failed")
        and video_path.exists()
        and _claim_retry(_thumb_retry_at, recording.id)
    ):
        run_background(generate_thumbnail, video_path, thumb_path, recording.id)
    return False


def _is_sprite_ready(recording: Recording, db: Session | None = None) -> bool:
    # Fast path: trust the cached DB flag and avoid a filesystem stat.
    if recording.sprite_ready:
        return True

    video_path = recording_path(recording.filename)
    sprite_path = video_path.with_name(video_path.stem + "_sprite.jpg")
    vtt_path = video_path.with_name(video_path.stem + "_sprite.vtt")
    if sprite_path.exists() and sprite_path.stat().st_size > 0 and vtt_path.exists() and vtt_path.stat().st_size > 0:
        # Files exist but DB is out of sync — fix it.
        if db is not None:
            recording.sprite_ready = True
            db.commit()
        return True

    # Kick off a background retry for finished recordings missing sprites
    if (
        recording.status in ("completed", "stopped", "failed")
        and video_path.exists()
        and _claim_retry(_sprite_retry_at, recording.id)
    ):
        run_background(generate_sprite, video_path)
    return False


def _build_response(rec: Recording, db: Session | None = None) -> RecordingResponse:
    # Corruption state is cached on the row (set at finalize/repair time) so
    # list endpoints never shell out to ffprobe. Legacy rows have a NULL flag;
    # probe those once lazily and backfill so it's fast on subsequent loads.
    is_corrupt: bool | None = rec.is_corrupt
    if (
        is_corrupt is None
        and rec.status in ("completed", "stopped", "failed")
    ):
        video_path = recording_path(rec.filename)
        if video_path.exists():
            health = analyze_video_health(video_path)
            is_corrupt = health.get("is_corrupt", True)
        else:
            is_corrupt = True
        if db is not None:
            rec.is_corrupt = is_corrupt
            db.commit()

    return RecordingResponse(
        id=rec.id,
        user_id=rec.user_id,
        username=rec.user.username,
        filename=rec.filename,
        status=rec.status,
        mode=rec.mode,
        started_at=rec.started_at,
        ended_at=rec.ended_at,
        duration_seconds=rec.duration_seconds,
        file_size=rec.file_size,
        error_message=rec.error_message,
        created_at=rec.created_at,
        thumbnail_ready=_is_thumbnail_ready(rec, db),
        sprite_ready=_is_sprite_ready(rec, db),
        is_favorite=rec.is_favorite or False,
        is_corrupt=is_corrupt,
    )


@router.get("", response_model=RecordingListResponse)
def list_recordings(
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    user_id: int | None = None,
    sort_by: str = "date",
    sort_order: str = "desc",
    username_filter: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    favorites_only: bool = False,
    db: Session = Depends(get_db)
):
    # Clamp: an unbounded page_size lets one request materialise the whole
    # table (and, on the recordings list, fan out into an ffprobe per row).
    page = max(1, page)
    page_size = max(1, min(page_size, settings.MAX_PAGE_SIZE))
    query = db.query(Recording).join(User).options(joinedload(Recording.user))
    count_query = db.query(func.count()).select_from(Recording).join(User)

    if status_filter:
        if "," in status_filter:
            statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
            query = query.filter(Recording.status.in_(statuses))
            count_query = count_query.filter(Recording.status.in_(statuses))
        else:
            query = query.filter(Recording.status == status_filter)
            count_query = count_query.filter(Recording.status == status_filter)
    if user_id:
        query = query.filter(Recording.user_id == user_id)
        count_query = count_query.filter(Recording.user_id == user_id)
    if username_filter:
        like_pat = f"%{username_filter}%"
        query = query.filter(User.username.ilike(like_pat))
        count_query = count_query.filter(User.username.ilike(like_pat))
    if min_size is not None:
        query = query.filter(Recording.file_size >= min_size)
        count_query = count_query.filter(Recording.file_size >= min_size)
    if max_size is not None:
        query = query.filter(Recording.file_size <= max_size)
        count_query = count_query.filter(Recording.file_size <= max_size)
    if date_from:
        try:
            dt = datetime.fromisoformat(date_from)
            query = query.filter(Recording.created_at >= dt)
            count_query = count_query.filter(Recording.created_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to)
            query = query.filter(Recording.created_at <= dt)
            count_query = count_query.filter(Recording.created_at <= dt)
        except ValueError:
            pass
    if favorites_only:
        query = query.filter(Recording.is_favorite == True)
        count_query = count_query.filter(Recording.is_favorite == True)

    total = count_query.scalar() or 0

    sort_col_map = {
        "size": Recording.file_size,
        "duration": Recording.duration_seconds,
        "username": User.username,
    }
    if sort_by == "favorites":
        # Favorites float to the top without excluding non-favorites.
        order = (Recording.is_favorite.desc(), Recording.created_at.desc())
    else:
        sort_col = sort_col_map.get(sort_by, Recording.created_at)
        order = (sort_col.asc() if sort_order == "asc" else sort_col.desc(),)
    recordings = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()

    return RecordingListResponse(
        recordings=[_build_response(rec) for rec in recordings],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/start", response_model=RecordingResponse, status_code=status.HTTP_201_CREATED)
def start_recording(request: RecordingStart, db: Session = Depends(get_db)):
    site = request.site
    if request.user_id:
        user = db.query(User).filter(User.id == request.user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
        username, site = user.username, user.site
    elif request.username:
        try:
            username = site_service.normalize_username(request.username, site)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        if not re.match(USERNAME_PATTERN, username):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model name")
        user = db.query(User).filter(User.site == site, User.username == username).first()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a model name, profile URL or user_id"
        )

    st = site_service.check_status(username, site, user.model_id if user else None)
    if st.state == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No model named '{username}' was found")
    if st.error and not st.is_online:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=st.error)
    if st.state == "private":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{username} is in a private show — only public shows can be recorded",
        )
    if not st.is_public or not st.model_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{username} is not currently live")
    model_id = st.model_id

    if not user:
        # Recording someone who isn't on the watchlist yet: keep a hidden row
        # so the recording has an owner.
        user = User(site=site, username=username, is_on_watchlist=False)
        db.add(user)
    user.model_id = model_id
    user.room_state = st.state
    user.is_live = True
    user.last_checked = datetime.utcnow()
    if st.display_name and not user.display_name:
        user.display_name = st.display_name
    db.commit()
    db.refresh(user)

    # Hold a claim across the duplicate check and the insert so this cannot
    # race the monitor loop, which may be mid-cycle deciding to auto-record
    # the same user.  See TaskManager.claim_user.
    with task_manager.claim_user(user.id) as claimed:
        if not claimed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A recording for {username} is already being started",
            )

        existing = (
            db.query(Recording)
            .filter(
                Recording.user_id == user.id,
                Recording.status.in_(["pending", "recording"]),
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{username} is already being recorded",
            )

        filename = generate_recording_filename(username, site_service.adapter(site).file_prefix)

        recording = Recording(
            user_id=user.id,
            filename=filename,
            status="pending",
            mode=request.mode
        )
        db.add(recording)
        db.commit()
        db.refresh(recording)

    max_seconds = max(
        60, int(settings_store.get("max_recording_hours", settings.DEFAULT_MAX_RECORDING_HOURS)) * 3600
    )
    success = task_manager.start_recording(
        recording_id=recording.id,
        username=username,
        model_id=model_id,
        site=site,
        duration=request.duration or max_seconds,
        proxy=settings_store.get("proxy", settings.DEFAULT_PROXY)
    )
    
    if not success:
        recording.status = "failed"
        recording.error_message = "Failed to start recording task"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start recording"
        )
    
    db.refresh(recording)
    
    return _build_response(recording, db)


@router.get("/active", response_model=list[ActiveRecordingResponse])
def get_active_recordings(db: Session = Depends(get_db)):
    """Return all active recordings.

    Merges the in-memory task manager IDs with any DB rows whose status is
    still ``recording`` or ``pending``. This prevents active recordings from
    disappearing after a backend restart, when the in-memory task map is empty.
    """
    task_manager.cleanup_finished()
    in_memory_ids = set(task_manager.get_active_recordings())

    recent_threshold = datetime.utcnow() - timedelta(hours=24)
    db_active = db.query(Recording).filter(
        Recording.status.in_(["recording", "pending"]),
        or_(
            Recording.started_at >= recent_threshold,
            Recording.started_at.is_(None),
        ),
    ).all()

    # Warn about orphaned recordings (DB says active, but no task is running)
    for rec in db_active:
        if rec.id not in in_memory_ids:
            logger.warning(
                "Recording %d is active in DB but has no in-memory task manager entry; "
                "it may be an orphaned recording from a previous process restart.",
                rec.id,
            )

    active_ids = in_memory_ids | {rec.id for rec in db_active}
    if not active_ids:
        return []

    recordings = db.query(Recording).filter(Recording.id.in_(active_ids)).all()

    now = datetime.utcnow()
    out = []
    for rec in recordings:
        duration = None
        if rec.started_at:
            duration = int((now - rec.started_at).total_seconds())
        out.append(ActiveRecordingResponse(
            id=rec.id,
            user_id=rec.user_id,
            username=rec.user.username,
            status=rec.status,
            started_at=rec.started_at,
            duration_seconds=duration,
            site=rec.user.site,
            model_id=rec.user.model_id,
        ))

    return out


@router.get("/{recording_id}/live-url")
def get_recording_live_url(recording_id: int, db: Session = Depends(get_db)):
    """Fetch a fresh HLS master playlist URL for watching an active recording in the browser."""
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording or recording.status not in ("pending", "recording"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not active"
        )
    model_id = recording.user.model_id
    if not model_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model id known for this recording"
        )

    try:
        live_url = site_service.get_playback_url(model_id, recording.user.site)
    except RuntimeError as e:
        logger.warning("Live URL resolution failed for recording %d: %s", recording_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("Unexpected error resolving live URL for recording %d", recording_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not resolve live stream URL: {e}"
        )

    return {"live_url": live_url, "type": "hls"}


@router.get("/{recording_id}/live-clip/status")
def live_clip_status(recording_id: int):
    """Return whether a live clip is currently being captured for this recording."""
    return live_clip_service.status(recording_id)


@router.post("/{recording_id}/live-clip/start")
def live_clip_start(recording_id: int):
    """Begin capturing a clip from the live stream (does not affect recording)."""
    try:
        return live_clip_service.start(recording_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.post("/{recording_id}/live-clip/stop")
def live_clip_stop(recording_id: int):
    """Stop the live clip, finalize the MP4, and create the clip."""
    try:
        return live_clip_service.stop(recording_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{recording_id}", response_model=RecordingResponse)
def get_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )

    return _build_response(recording)


@router.post("/{recording_id}/stop", response_model=RecordingResponse)
def stop_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )
    
    if recording.status not in ["pending", "recording"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Recording is not active (status: {recording.status})"
        )
    
    stopped = task_manager.stop_recording(recording_id)
    if not stopped and recording.status == "recording":
        # Orphan recording — task no longer in memory (e.g. container restart)
        recording.status = "stopped"
        recording.ended_at = datetime.utcnow()
        db.commit()
    
    db.refresh(recording)
    
    return _build_response(recording, db)


@router.post("/{recording_id}/favorite", response_model=RecordingResponse)
def toggle_favorite_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )
    recording.is_favorite = not recording.is_favorite
    db.commit()
    db.refresh(recording)
    return _build_response(recording, db)


@router.delete("/{recording_id}")
def delete_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )
    
    was_recording = task_manager.is_recording(recording_id)
    if was_recording:
        task_manager.stop_recording(recording_id)
        time.sleep(2)
    
    errors = _delete_recording_files(recording)
    
    db.delete(recording)
    db.commit()
    
    if errors:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"deleted": True, "errors": errors},
        )
    
    return {"deleted": True, "errors": []}


@router.get("/{recording_id}/download")
def download_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )

    file_path = recording_path(recording.filename)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording file not found"
        )

    return FileResponse(
        path=str(file_path),
        filename=recording.filename,
        media_type="video/mp4"
    )


@router.api_route("/{recording_id}/stream", methods=["GET", "HEAD"])
def stream_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )

    file_path = recording_path(recording.filename)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording file not found"
        )

    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        content_disposition_type="inline",
    )


@router.get("/{recording_id}/thumbnail")
def thumbnail_recording(recording_id: int, db: Session = Depends(get_db)):
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found"
        )

    video_path = recording_path(recording.filename)
    thumb_path = thumbnail_path(video_path)

    if not thumb_path.exists():
        # Try a single fast attempt inline first — covers the common case
        # (e.g. a stale thumbnail_ready flag pointing at a since-deleted
        # file) without the caller waiting through a full multi-attempt
        # retry. Concurrent thumbnail generation is capped by a semaphore
        # inside generate_thumbnail(), so a burst of these across many
        # recordings at once (e.g. right after import) can't thrash the
        # CPU the way an unbounded number of full retries would.
        if not generate_thumbnail(video_path, thumb_path, recording.id, quick=True):
            # Fall back to the full multi-attempt retry so this endpoint
            # still eventually succeeds for harder cases (e.g. an odd
            # keyframe layout) rather than surfacing a permanent failure.
            if not generate_thumbnail(video_path, thumb_path, recording.id):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Could not generate thumbnail for this recording",
                )

    if not recording.thumbnail_ready:
        recording.thumbnail_ready = True
        db.commit()

    # Revalidatable cache: no `immutable` flag, so the browser will refetch when
    # the URL changes (cache-buster) or when the ETag/Last-Modified differs. This
    # prevents stale thumbnails from being shown for reused recording IDs or after
    # a thumbnail is regenerated (e.g., repair).
    stat = thumb_path.stat()
    etag = f'"{stat.st_mtime_ns}-{stat.st_size}"'
    last_modified = datetime.utcfromtimestamp(stat.st_mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")

    return FileResponse(
        path=str(thumb_path),
        media_type=thumbnail_media_type(thumb_path),
        content_disposition_type="inline",
        headers={
            "Cache-Control": "public, max-age=86400, must-revalidate",
            "ETag": etag,
            "Last-Modified": last_modified,
        },
    )


@router.post("/stop-all", status_code=status.HTTP_200_OK)
def stop_all_recordings(db: Session = Depends(get_db)):
    """Stop all currently active (status=recording) recordings."""
    active = db.query(Recording).filter(Recording.status == "recording").all()
    stopped = 0
    for rec in active:
        try:
            task_manager.stop_recording(rec.id)
            stopped += 1
        except Exception:
            pass
    return {"stopped": stopped}


@router.post("/batch/delete", status_code=status.HTTP_200_OK)
def batch_delete_recordings(
    recording_ids: List[int] = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Delete multiple recordings at once."""
    if not recording_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recording IDs provided"
        )
    
    deleted_count = 0
    errors = []
    
    for recording_id in recording_ids:
        recording = db.query(Recording).filter(Recording.id == recording_id).first()
        if not recording:
            errors.append(f"Recording {recording_id} not found")
            continue
        
        was_recording = task_manager.is_recording(recording_id)
        if was_recording:
            task_manager.stop_recording(recording_id)
            time.sleep(2)
        
        errors.extend(_delete_recording_files(recording))
        
        db.delete(recording)
        deleted_count += 1
    
    db.commit()
    
    return {
        "deleted": deleted_count,
        "errors": errors
    }


@router.post("/batch/compress", status_code=status.HTTP_200_OK)
def batch_compress_recordings(
    recording_ids: List[int] = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Compress selected recordings into a backup ZIP and delete the originals.

    Used by the storage-management view to reclaim space while keeping an
    archived copy in the backups folder.
    """
    from app.core.cleanup_service import cleanup_service

    if not recording_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recording IDs provided"
        )

    recordings = (
        db.query(Recording)
        .filter(Recording.id.in_(recording_ids))
        .filter(Recording.status.in_(("completed", "stopped", "failed")))
        .all()
    )
    if not recordings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No eligible recordings found"
        )

    backup_file = cleanup_service.compress_recordings(recordings)
    if not backup_file:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create backup archive"
        )

    deleted = 0
    for rec in recordings:
        _delete_recording_files(rec)
        db.delete(rec)
        deleted += 1
    db.commit()

    return {"compressed": deleted, "deleted": deleted, "backup_file": backup_file}


@router.get("/{recording_id}/sprite")
def get_sprite(recording_id: int, db: Session = Depends(get_db)):
    """Return the sprite sheet JPEG for hover-scrub preview.

    Cached as immutable: the VTT references it as ``?v=<mtime>``, so a
    regenerated sheet is fetched under a new URL.
    """
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    sprite_path, _ = sprite_paths(recording_path(recording.filename))
    if not sprite_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprite not yet generated")
    return FileResponse(
        path=str(sprite_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/{recording_id}/thumbnails.vtt")
def get_sprite_vtt(recording_id: int, request: Request, db: Session = Depends(get_db)):
    """Return the WebVTT sprite map for Vidstack and the card hover-scrub.

    Revalidated on every use (``no-cache`` + ETag) so a regenerated sprite is
    picked up immediately. Maps written by an older generator (which could
    misalign frames) are served as-is while a background job rebuilds them.
    """
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    video_path = recording_path(recording.filename)
    rendered = render_sprite_vtt(video_path, f"/api/recordings/{recording_id}/sprite")
    if rendered is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VTT not yet generated")

    _, vtt_path = sprite_paths(video_path)
    if (
        sprite_vtt_version(vtt_path) < SPRITE_VERSION
        and video_path.exists()
        and _claim_retry(_sprite_retry_at, recording.id)
    ):
        run_background(generate_sprite, video_path)

    content, etag = rendered
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=content, media_type="text/vtt", headers=headers)


@router.post("/sprites/regenerate")
def regenerate_missing_sprites(db: Session = Depends(get_db)):
    """Trigger sprite generation for all completed/stopped recordings missing sprites."""
    recordings = (
        db.query(Recording)
        .filter(Recording.status.in_(("completed", "stopped")))
        .filter(or_(Recording.sprite_ready.is_(False), Recording.sprite_ready.is_(None)))
        .all()
    )
    triggered = 0
    for rec in recordings:
        video_path = recording_path(rec.filename)
        if video_path.exists() and _claim_retry(_sprite_retry_at, rec.id):
            run_background(generate_sprite, video_path)
            triggered += 1
    return {"total_missing": len(recordings), "triggered": triggered}


@router.get("/{recording_id}/health")
def get_recording_health(recording_id: int, db: Session = Depends(get_db)):
    """Check the structural integrity of a recording file.

    Returns ``ffprobe`` diagnostics so the frontend can display a warning
    when a recording is corrupt and offer the repair action.
    """
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    video_path = recording_path(recording.filename)
    if video_path.exists():
        return analyze_video_health(video_path)

    # No .mp4 yet — a finalize/remux failure left the raw capture on disk.
    # Report it as recoverable so the UI still offers the repair action
    # instead of a dead "no recording found" state.
    sources = _find_capture_sources(video_path)
    if sources:
        return {
            "is_corrupt": True,
            "duration": None,
            "has_video": False,
            "has_audio": False,
            "error": "Final MP4 missing — raw capture is present and can be repaired",
            "recoverable": True,
        }
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file not found")


@router.post("/{recording_id}/repair", response_model=RecordingResponse)
def repair_recording(recording_id: int, db: Session = Depends(get_db)):
    """Attempt to repair a corrupted recording.

    Runs error-tolerant ffmpeg commands (stream-copy first, full re-encode
    as fallback) to recover playback from recordings damaged by the stream's
    mid-stream codec/resolution switches.

    The repaired file **replaces** the original in-place. On success the
    recording duration is updated, its status is moved to ``completed`` if
    it was ``failed``, and visual assets are regenerated.
    """
    recording = db.query(Recording).filter(Recording.id == recording_id).first()
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    if recording.status not in ("completed", "stopped", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only finished recordings can be repaired",
        )

    video_path = recording_path(recording.filename)

    # Case A — the .mp4 was never produced (finalize/remux failure). Rebuild it
    # from the raw capture sources still on disk instead of 404-ing. This is the
    # exact scenario the repair button is shown for after a failed finalize.
    if not video_path.exists():
        sources = _find_capture_sources(video_path)
        if not sources:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recording file not found — no MP4 or raw capture on disk",
            )
        try:
            rebuilt_ok, actual_duration = finalize_segments_to_mp4(sources, video_path)
        except Exception:
            logger.exception("Rebuild-from-sources raised for recording %d", recording_id)
            rebuilt_ok = False

        if rebuilt_ok and video_path.exists():
            for src in sources:
                src.unlink(missing_ok=True)
            recording.file_size = video_path.stat().st_size
            if actual_duration is not None:
                recording.duration_seconds = int(round(actual_duration))
            recording.status = "stopped" if recording.status == "stopped" else "completed"
            recording.is_corrupt = False
            recording.error_message = "Recording rebuilt from raw capture"
            db.commit()
            db.refresh(recording)
            run_background(generate_thumbnail, video_path, thumbnail_path(video_path), recording.id)
            run_background(generate_sprite, video_path)
            return _build_response(recording, db)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Repair failed — raw capture could not be converted to MP4",
        )

    # Case B — the .mp4 exists but is corrupt. Non-destructive in-place repair:
    # keep a backup while we attempt to fix it; restore it if repair fails.
    backup_path = video_path.with_suffix(video_path.suffix + ".backup")
    try:
        shutil.copy2(video_path, backup_path)
    except Exception as exc:
        logger.warning("Failed to create backup before repair for %s: %s", video_path, exc)
        backup_path = None

    try:
        repair_ok, actual_duration = repair_video(video_path)
    except Exception as exc:
        logger.exception("Repair raised an exception for recording %d", recording_id)
        repair_ok = False

    if repair_ok:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
        recording.file_size = video_path.stat().st_size
        if actual_duration is not None:
            recording.duration_seconds = int(round(actual_duration))
        if recording.status == "failed":
            recording.status = "completed"
        recording.is_corrupt = False
        recording.error_message = "Recording was repaired"
        db.commit()
        db.refresh(recording)

        # Regenerate visual assets now that the file is healthy
        run_background(generate_thumbnail, video_path, thumbnail_path(video_path), recording.id)
        run_background(generate_sprite, video_path)

        return _build_response(recording, db)

    # Repair failed: restore the original from the backup if we made one.
    if backup_path is not None and backup_path.exists():
        try:
            backup_path.replace(video_path)
            logger.info("Restored original file for recording %d from %s", recording_id, backup_path)
        except Exception as exc:
            logger.error("Failed to restore backup for recording %d: %s", recording_id, exc)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Repair failed — recording may be beyond recovery",
    )
