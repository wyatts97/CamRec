import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db, get_session, run_background
from app.db.models import User, Recording
from app.schemas.user import USERNAME_PATTERN, UserCreate, UserUpdate, UserResponse, UserStatusResponse
from app.core.site_service import site_service
from app.core.sites import ModelStatus, available_sites
from app.core.unified_avatar_service import unified_avatar_service
from app.core.task_manager import task_manager

router = APIRouter(prefix="/users", tags=["users"])

_USERNAME_RE = re.compile(USERNAME_PATTERN)


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return user


def _apply_status(user: User, st: ModelStatus) -> None:
    user.room_state = st.state
    user.is_live = st.is_public
    user.last_checked = datetime.utcnow()
    if st.model_id:
        user.model_id = st.model_id
    if st.display_name:
        user.display_name = st.display_name


def _fetch_avatar_async(user_id: int, site: str, username: str, st: ModelStatus | None, force: bool = False) -> None:
    def _job():
        fetched = unified_avatar_service.fetch_and_cache(
            site, username,
            st.avatar_url if st else None,
            st.thumbnail_url if st else None,
            force=force,
        )
        if fetched:
            with get_session() as db:
                u = db.query(User).filter(User.id == user_id).first()
                if u and not u.profile_pic_url:
                    u.profile_pic_url = f"/api/users/{u.id}/avatar"
                    db.commit()
    run_background(_job)


@router.get("/sites")
def list_sites():
    return available_sites()


@router.get("", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    monitoring_only: bool = False,
    watchlist_only: bool = True,
    db: Session = Depends(get_db)
):
    # Clamp: `?limit=` was unbounded.
    skip = max(0, skip)
    limit = max(1, min(limit, settings.MAX_PAGE_SIZE))
    query = db.query(User)
    if monitoring_only:
        query = query.filter(User.is_monitoring == True)  # noqa: E712
    if watchlist_only:
        query = query.filter(User.is_on_watchlist == True)  # noqa: E712
    users = query.offset(skip).limit(limit).all()
    # Backfill profile_pic_url for users with cached avatars
    changed = False
    for user in users:
        if not user.profile_pic_url and unified_avatar_service.get_avatar_path(user.site, user.username):
            user.profile_pic_url = f"/api/users/{user.id}/avatar"
            changed = True
    if changed:
        db.commit()
    return users


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    try:
        username = site_service.normalize_username(payload.username, payload.site)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid model name")

    existing = db.query(User).filter(User.site == payload.site, User.username == username).first()
    if existing and existing.is_on_watchlist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{username}' is already on the watchlist",
        )

    st = site_service.check_status(username, payload.site)
    if st.state == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No model named '{username}' was found on {site_service.adapter(payload.site).label}",
        )

    if existing:
        # Previously removed from the watchlist — re-activate.
        user = existing
        user.is_on_watchlist = True
        user.is_monitoring = payload.is_monitoring
    else:
        user = User(
            site=payload.site,
            username=username,
            is_monitoring=payload.is_monitoring,
            is_on_watchlist=True,
        )
        db.add(user)
    _apply_status(user, st)
    db.commit()
    db.refresh(user)

    _fetch_avatar_async(user.id, user.site, user.username, st)
    return user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    if not user.profile_pic_url and unified_avatar_service.get_avatar_path(user.site, user.username):
        user.profile_pic_url = f"/api/users/{user.id}/avatar"
        db.commit()
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, user_update: UserUpdate, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    update_data = user_update.model_dump(exclude_unset=True)

    # When removing from watchlist, also disable monitoring and stop active recordings
    if update_data.get("is_on_watchlist") is False:
        update_data["is_monitoring"] = False
        active_recordings = (
            db.query(Recording)
            .filter(Recording.user_id == user.id, Recording.status == "recording")
            .all()
        )
        for rec in active_recordings:
            task_manager.stop_recording(rec.id)
            rec.status = "stopped"
        if active_recordings:
            db.commit()

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    db.delete(user)
    db.commit()
    return None


@router.get("/{user_id}/status", response_model=UserStatusResponse)
def check_user_status(user_id: int, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    st = site_service.check_status(user.username, user.site, user.model_id)
    _apply_status(user, st)
    db.commit()
    if st.error and st.state != "offline":
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=st.error)
    return UserStatusResponse(
        username=user.username,
        is_live=user.is_live,
        room_state=user.room_state,
        model_id=user.model_id,
        last_checked=user.last_checked,
    )


@router.post("/{user_id}/refresh", response_model=UserResponse)
def refresh_user_status(
    user_id: int,
    refresh_profile: bool = False,
    db: Session = Depends(get_db)
):
    user = _get_user_or_404(db, user_id)
    st = site_service.check_status(user.username, user.site, user.model_id)
    _apply_status(user, st)
    db.commit()
    db.refresh(user)
    if refresh_profile:
        _fetch_avatar_async(user.id, user.site, user.username, st, force=True)
    return user


def _image_response(path: str, cache: str) -> FileResponse:
    media = "image/webp" if path.endswith(".webp") else "image/png" if path.endswith(".png") else "image/jpeg"
    return FileResponse(path=path, media_type=media, content_disposition_type="inline",
                        headers={"Cache-Control": cache})


@router.get("/{user_id}/avatar")
def get_user_avatar(user_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    """Cached avatar image for a model (fetched from the site if missing)."""
    user = _get_user_or_404(db, user_id)
    if refresh or not unified_avatar_service.get_avatar_path(user.site, user.username):
        fetched = unified_avatar_service.fetch_and_cache(user.site, user.username, force=refresh)
        if fetched and not user.profile_pic_url:
            user.profile_pic_url = f"/api/users/{user.id}/avatar"
            db.commit()

    cached = unified_avatar_service.get_avatar_path(user.site, user.username)
    if cached:
        return _image_response(cached, "no-cache" if refresh else "public, max-age=3600")
    return Response(status_code=204)


@router.get("/{user_id}/screencap")
def get_user_screencap(user_id: int, db: Session = Depends(get_db)):
    """Current live screencap of the room, proxied so the browser never hot-links the site."""
    user = _get_user_or_404(db, user_id)
    if not user.model_id or user.room_state not in ("public", "private"):
        return Response(status_code=204)
    adapter = site_service.adapter(user.site)
    url = adapter.screencap_url(user.model_id)
    data = adapter.fetch_bytes(url) if url else None
    if not data:
        return Response(status_code=204)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=30"})
