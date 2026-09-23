from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.user import USERNAME_PATTERN


class RecordingStart(BaseModel):
    username: str | None = Field(default=None, max_length=24, pattern=USERNAME_PATTERN)
    url: str | None = None
    room_id: str | None = None
    mode: str = Field(default="manual", pattern="^(manual|automatic)$")
    duration: int | None = Field(default=None, ge=1)
    bitrate: str | None = None


class RecordingResponse(BaseModel):
    id: int
    user_id: int
    username: str
    filename: str
    status: str
    mode: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    file_size: int | None = None
    error_message: str | None = None
    created_at: datetime
    thumbnail_ready: bool = False
    sprite_ready: bool = False
    transcript_status: str | None = None
    transcript_text: str | None = None
    is_favorite: bool = False
    is_corrupt: bool | None = None

    class Config:
        from_attributes = True


class RecordingListResponse(BaseModel):
    recordings: list[RecordingResponse]
    total: int
    page: int
    page_size: int


class ClipCreate(BaseModel):
    recording_id: int
    start_time: int = Field(..., ge=0, description="Start time in seconds")
    end_time: int = Field(..., ge=0, description="End time in seconds")
    title: str | None = Field(default=None, max_length=255)


class ClipResponse(BaseModel):
    id: int
    # None once the source recording has been deleted -- clips outlive it.
    recording_id: int | None = None
    username: str
    title: str | None = None
    filename: str
    start_time: int
    end_time: int
    duration_seconds: int | None = None
    file_size: int | None = None
    thumbnail_ready: bool = False
    sprite_ready: bool = False
    is_favorite: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ClipListResponse(BaseModel):
    clips: list[ClipResponse]
    total: int
    page: int
    page_size: int


class ActiveRecordingResponse(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    started_at: datetime | None = None
    duration_seconds: int | None = None
    room_id: str | None = None
    # Live chat capture state, so the UI can say "chat not captured" instead
    # of showing an empty timeline.
    chat_connected: bool = False
    chat_error: str | None = None
