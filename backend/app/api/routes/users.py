from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db, get_session, run_background
from app.db.models import User, Recording
from app.schemas.user import UserCreate, UserUpdate, UserResponse, UserStatusResponse
from app.core.recorder_service import recorder_service
from app.core.user_info_service import user_info_service
from app.core.unified_avatar_service import unified_avatar_service
from app.core.task_manager import task_manager

router = APIRouter(prefix="/users", tags=["users"])


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
        query = query.filter(User.is_monitoring == True)
    if watchlist_only:
        query = query.filter(User.is_on_watchlist == True)
    users = query.offset(skip).limit(limit).all()
    # Backfill profile_pic_url for users with cached avatars
    for user in users:
        if not user.profile_pic_url:
            if unified_avatar_service.get_avatar_path(user.username):
                user.profile_pic_url = f"/api/users/{user.id}/avatar"
    db.commit()
    return users


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    username = user.username.lstrip("@").strip()

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        if existing.is_on_watchlist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User '{username}' already exists"
            )
        # User was previously removed from the watchlist — re-activate them
        status_info = recorder_service.check_user_live(username)
        existing.is_on_watchlist = True
        existing.is_monitoring = user.is_monitoring
        existing.is_live = status_info.get("is_live", False)
        existing.room_id = status_info.get("room_id")
        existing.last_checked = datetime.utcnow()
        db.commit()
        db.refresh(existing)

        user_info_service.update_user_profile_async(existing.id)
        run_background(unified_avatar_service.fetch_and_cache, existing.username, existing.room_id)
        return existing

    status_info = recorder_service.check_user_live(username)

    db_user = User(
        username=username,
        room_id=status_info.get("room_id"),
        is_monitoring=user.is_monitoring,
        is_live=status_info.get("is_live", False),
        is_on_watchlist=True,
        last_checked=datetime.utcnow()
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    user_info_service.update_user_profile_async(db_user.id)

    # Also fetch avatar asynchronously using the new unified service
    def _fetch_avatar():
        fetched = unified_avatar_service.fetch_and_cache(db_user.username, db_user.room_id)
        if fetched:
            with get_session() as db:
                u = db.query(User).filter(User.id == db_user.id).first()
                if u:
                    u.profile_pic_url = f"/api/users/{u.id}/avatar"
                    db.commit()
    run_background(_fetch_avatar)

    return db_user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    # Backfill profile_pic_url like list_users does
    if not user.profile_pic_url and unified_avatar_service.get_avatar_path(user.username):
        user.profile_pic_url = f"/api/users/{user.id}/avatar"
        db.commit()
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, user_update: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

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
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    db.delete(user)
    db.commit()
    return None


@router.get("/{user_id}/status", response_model=UserStatusResponse)
def check_user_status(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    status_info = recorder_service.check_user_live(user.username)
    
    user.is_live = status_info.get("is_live", False)
    user.room_id = status_info.get("room_id")
    user.last_checked = datetime.utcnow()
    db.commit()
    
    if status_info.get("error"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=status_info["error"]
        )
    
    return UserStatusResponse(
        username=user.username,
        is_live=user.is_live,
        room_id=user.room_id,
        last_checked=user.last_checked
    )


@router.post("/{user_id}/refresh", response_model=UserResponse)
def refresh_user_status(
    user_id: int,
    refresh_profile: bool = False,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    status_info = recorder_service.check_user_live(user.username)
    
    user.is_live = status_info.get("is_live", False)
    user.room_id = status_info.get("room_id")
    user.last_checked = datetime.utcnow()
    db.commit()
    db.refresh(user)

    if refresh_profile:
        user_info_service.update_user_profile_async(user.id)
        run_background(unified_avatar_service.fetch_and_cache, user.username, user.room_id, force=True)

    return user


@router.get("/{user_id}/avatar")
def get_user_avatar(user_id: int, refresh: bool = False, db: Session = Depends(get_db)):
    """Get the avatar image for a user. Fetches from TikTok if not cached."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Try to fetch (or re-fetch if refresh=true) using the unified service
    if refresh or not unified_avatar_service.get_avatar_path(user.username):
        fetched = unified_avatar_service.fetch_and_cache(
            user.username, user.room_id, force=refresh
        )
        if fetched and not user.profile_pic_url:
            # Persist the fact that we have an avatar so the frontend knows
            user.profile_pic_url = f"/api/users/{user.id}/avatar"
            db.commit()

    cached = unified_avatar_service.get_avatar_path(user.username)
    if cached:
        return FileResponse(
            path=cached,
            media_type="image/jpeg",
            content_disposition_type="inline",
            headers={
                "Cache-Control": "no-cache, no-store" if refresh else "public, max-age=31536000, immutable"
            },
        )

    from fastapi.responses import Response as _Response
    return _Response(status_code=204)
