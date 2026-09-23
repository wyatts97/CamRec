from datetime import datetime
from pydantic import BaseModel, Field


# TikTok's own username charset.  Constrained here because the value ends up
# in on-disk filenames (see media_utils.generate_recording_filename), so path
# separators and traversal sequences must never reach it.
USERNAME_PATTERN = r"^[A-Za-z0-9._]{1,24}$"


class UserBase(BaseModel):
    username: str = Field(..., min_length=1, max_length=24, pattern=USERNAME_PATTERN)


class UserCreate(UserBase):
    is_monitoring: bool = False


class UserUpdate(BaseModel):
    is_monitoring: bool | None = None
    is_on_watchlist: bool | None = None
    room_id: str | None = None


class UserResponse(BaseModel):
    # Deliberately NOT inheriting UserBase: the pattern there guards *input*.
    # Rows already in the database predate that constraint, and a response
    # model must never fail validation on data we already stored.
    username: str
    id: int
    display_name: str | None = None
    bio: str | None = None
    follower_count: int | None = None
    room_id: str | None = None
    profile_pic_url: str | None = None
    is_monitoring: bool
    is_live: bool
    is_on_watchlist: bool
    last_checked: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserStatusResponse(BaseModel):
    username: str
    is_live: bool
    room_id: str | None = None
    last_checked: datetime
