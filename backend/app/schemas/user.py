from datetime import datetime
from pydantic import BaseModel, Field


# Canonical (normalized) model name charset. Constrained because the value
# ends up in on-disk filenames (see media_utils.generate_recording_filename),
# so path separators and traversal sequences must never reach it.
USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$"


class UserCreate(BaseModel):
    # Free-form: a model name, display name or profile URL. The site adapter
    # normalizes it, and the normalized form is validated against
    # USERNAME_PATTERN before it is stored.
    username: str = Field(..., min_length=1, max_length=300)
    site: str = "flirt4free"
    is_monitoring: bool = False


class UserUpdate(BaseModel):
    is_monitoring: bool | None = None
    is_on_watchlist: bool | None = None


class UserResponse(BaseModel):
    # Deliberately loose: a response model must never fail validation on
    # data we already stored.
    id: int
    site: str
    username: str
    display_name: str | None = None
    model_id: str | None = None
    room_state: str | None = None
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
    room_state: str | None = None
    model_id: str | None = None
    last_checked: datetime
