from datetime import datetime
from pydantic import BaseModel, Field


class RecordingStart(BaseModel):
    # A model name or profile URL; normalized by the site adapter.
    username: str | None = Field(default=None, max_length=300)
    user_id: int | None = None
    site: str = "flirt4free"
    mode: str = Field(default="manual", pattern="^(manual|automatic)$")
    duration: int | None = Field(default=None, ge=1)


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
    site: str = "flirt4free"
    model_id: str | None = None
