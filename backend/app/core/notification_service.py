"""In-app notification service with a thread-safe pub/sub broker.

Background threads (monitor service, recording tasks, live-clip tasks) call
:meth:`NotificationService.publish` to broadcast events. The FastAPI SSE
endpoint subscribes to receive them in real time, while a bounded history
buffer backs the notification-center list/unread-count endpoints.

The broker is deliberately simple and in-process: notifications are ephemeral
(not persisted) and reset on restart, which is appropriate for transient
"went live / recording finished" alerts.
"""
import logging
import threading
import queue as _queue
from collections import deque
from datetime import datetime, timezone
from itertools import count
from typing import Any

logger = logging.getLogger("tikrec.notifications")

_MAX_HISTORY = 100
_MAX_QUEUE = 100


class NotificationService:
    def __init__(self) -> None:
        self._history: deque[dict] = deque(maxlen=_MAX_HISTORY)
        self._subscribers: set[_queue.Queue] = set()
        self._lock = threading.Lock()
        self._ids = count(1)
        self._read_ids: set[int] = set()

    # -- Publishing ---------------------------------------------------

    def publish(
        self,
        type: str,
        title: str,
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict:
        """Create a notification, store it in history, and fan it out to
        all current SSE subscribers. Safe to call from any thread."""
        notif = {
            "id": next(self._ids),
            "type": type,
            "title": title,
            "message": message,
            "data": data or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        with self._lock:
            self._history.appendleft(notif)
            dead: list[_queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(notif)
                except _queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.discard(q)
        logger.info("Notification: [%s] %s", type, title)

        # Fan out to any configured external sinks (ntfy / Discord / Telegram).
        # Imported lazily and guarded: an outbound delivery problem must never
        # affect the in-app notification, which is the primary path.
        try:
            from app.core.notification_sinks import notification_sinks
            notification_sinks.enqueue(notif)
        except Exception:
            logger.exception("Failed to enqueue notification for external delivery")

        return notif

    # -- Subscription (SSE) -------------------------------------------

    def subscribe(self) -> _queue.Queue:
        q: _queue.Queue = _queue.Queue(maxsize=_MAX_QUEUE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: _queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    # -- History / read-state -----------------------------------------

    def get_recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = list(self._history)[:limit]
        return [{**n, "read": n["id"] in self._read_ids} for n in items]

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for n in self._history if n["id"] not in self._read_ids)

    def mark_all_read(self) -> None:
        with self._lock:
            self._read_ids.update(n["id"] for n in self._history)

    def mark_read(self, notif_id: int) -> None:
        with self._lock:
            self._read_ids.add(notif_id)


notification_service = NotificationService()
