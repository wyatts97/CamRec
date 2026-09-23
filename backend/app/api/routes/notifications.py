"""Notification endpoints: history list, read-state, and a live SSE stream."""
import asyncio
import json
import logging
import queue as _queue

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.notification_service import notification_service

logger = logging.getLogger("tikrec.notifications")

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(limit: int = 50):
    """Return recent notifications plus the current unread count."""
    return {
        "notifications": notification_service.get_recent(limit),
        "unread": notification_service.unread_count(),
    }


@router.post("/read")
def mark_all_read():
    """Mark every notification in history as read."""
    notification_service.mark_all_read()
    return {"unread": 0}


@router.post("/{notif_id}/read")
def mark_one_read(notif_id: int):
    notification_service.mark_read(notif_id)
    return {"unread": notification_service.unread_count()}


@router.get("/stream")
async def notifications_stream(request: Request):
    """Server-Sent Events stream of notifications.

    Sends a comment heartbeat every ~15s so proxies keep the connection
    open, and terminates cleanly when the client disconnects.
    """

    async def event_generator():
        q = notification_service.subscribe()
        # Initial event so the client knows the stream is established.
        yield f"event: ready\ndata: {json.dumps({'unread': notification_service.unread_count()})}\n\n"
        heartbeat = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    notif = q.get_nowait()
                    yield f"data: {json.dumps(notif)}\n\n"
                    heartbeat = 0
                    continue
                except _queue.Empty:
                    pass
                await asyncio.sleep(1)
                heartbeat += 1
                if heartbeat >= 15:
                    heartbeat = 0
                    yield ": ping\n\n"
        finally:
            notification_service.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )
