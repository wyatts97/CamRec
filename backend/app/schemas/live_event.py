from datetime import datetime
from pydantic import BaseModel


class LiveEventResponse(BaseModel):
    id: int
    recording_id: int
    offset_seconds: float
    event_type: str  # "chat" or "gift"
    user_nickname: str
    user_unique_id: str | None = None
    content: str | None = None
    gift_name: str | None = None
    gift_diamond_count: int | None = None
    gift_repeat_count: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class LiveEventListResponse(BaseModel):
    events: list[LiveEventResponse]
    total: int
