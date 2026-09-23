"""Outbound delivery of notifications to services outside the browser.

The in-app NotificationService is in-process and ephemeral: if the tab is
closed, a "user went live" or "recording failed" event is never seen. These
sinks forward the same events to somewhere durable.

All three sinks are plain HTTPS calls, so none of them add a dependency.
Telegram uses the Bot API (a bot token and a chat id) rather than telethon's
MTProto client -- telethon is declared in requirements.txt but has never been
imported, and a bot token needs no interactive login or session file.

Delivery runs on its own single worker thread. A slow or unreachable webhook
must never block the recording threads that call publish().
"""
import json
import logging
import queue
import threading
from typing import Any

import httpx

from app.core.settings_store import settings_store

logger = logging.getLogger("camsuite.notification_sinks")

# The full set of event types the app publishes, in the order the settings UI
# should list them. Kept in sync with the notification_service.publish() calls
# in task_manager.py and live_clip_service.py.
ALL_EVENTS = [
    "user_live",
    "recording_completed",
    "recording_stopped",
    "recording_failed",
    "clip_ready",
    "circuit_breaker_tripped",
    "mass_live_anomaly",
    "private_show",
    "site_blocked",
]

# On by default: the ones worth waking a phone for. "recording_stopped" is a
# user-initiated action and "clip_ready" is usually watched for in the UI, so
# both are opt-in.
DEFAULT_EVENTS = [
    "user_live",
    "recording_failed",
    "recording_completed",
    "circuit_breaker_tripped",
    "site_blocked",
]

_TIMEOUT = httpx.Timeout(10.0)
_MAX_QUEUE = 200


def default_config() -> dict:
    return {
        "enabled": False,
        "events": list(DEFAULT_EVENTS),
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": ""},
        "discord": {"enabled": False, "webhook_url": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    }


def get_config() -> dict:
    stored = settings_store.get("notification_sinks", {}) or {}
    config = default_config()
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


# --- Individual senders ------------------------------------------------
#
# Each returns the name it should be logged under, or raises.

def _send_ntfy(cfg: dict, notif: dict) -> None:
    topic = (cfg.get("topic") or "").strip()
    if not topic:
        raise ValueError("ntfy topic is not set")
    server = (cfg.get("server") or "https://ntfy.sh").rstrip("/")
    # ntfy takes the body as the message and metadata in headers. Headers must
    # be latin-1 safe, so non-ASCII titles are carried in the body instead.
    title = notif.get("title", "CamSuite")
    safe_title = title.encode("ascii", "ignore").decode("ascii") or "CamSuite"
    body = notif.get("message") or title
    if safe_title != title:
        body = f"{title}\n{body}"
    httpx.post(
        f"{server}/{topic}",
        content=body.encode("utf-8"),
        headers={"Title": safe_title, "Tags": notif.get("type", "bell")},
        timeout=_TIMEOUT,
    ).raise_for_status()


def _send_discord(cfg: dict, notif: dict) -> None:
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        raise ValueError("Discord webhook URL is not set")
    content = f"**{notif.get('title', 'CamSuite')}**"
    if notif.get("message"):
        content += f"\n{notif['message']}"
    httpx.post(url, json={"content": content[:2000]}, timeout=_TIMEOUT).raise_for_status()


def _send_telegram(cfg: dict, notif: dict) -> None:
    token = (cfg.get("bot_token") or "").strip()
    chat_id = (cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        raise ValueError("Telegram bot_token and chat_id are both required")
    text = f"*{notif.get('title', 'CamSuite')}*"
    if notif.get("message"):
        text += f"\n{notif['message']}"
    httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "Markdown"},
        timeout=_TIMEOUT,
    ).raise_for_status()


_SENDERS = {"ntfy": _send_ntfy, "discord": _send_discord, "telegram": _send_telegram}


class NotificationSinkDispatcher:
    """Fans notifications out to the configured sinks, off the caller's thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=_MAX_QUEUE)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="notif-sinks", daemon=True
            )
            self._thread.start()

    def enqueue(self, notif: dict) -> None:
        """Queue a notification for delivery. Never raises, never blocks."""
        try:
            config = get_config()
        except Exception:
            logger.exception("Could not read notification sink config")
            return

        if not config.get("enabled"):
            return
        if notif.get("type") not in config.get("events", DEFAULT_EVENTS):
            return
        if not any(config.get(name, {}).get("enabled") for name in _SENDERS):
            return

        self._ensure_worker()
        try:
            self._queue.put_nowait((notif, config))
        except queue.Full:
            # Dropping is correct here: these are transient alerts, and a
            # backlog means a sink is down. Never block a recording thread.
            logger.warning("Notification sink queue is full; dropping notification")

    def _run(self) -> None:
        while True:
            notif, config = self._queue.get()
            for name, send in _SENDERS.items():
                sink_cfg = config.get(name, {})
                if not sink_cfg.get("enabled"):
                    continue
                try:
                    send(sink_cfg, notif)
                    logger.info("Delivered notification to %s", name)
                except Exception as exc:
                    logger.warning("Notification delivery to %s failed: %s", name, exc)

    def send_test(self, name: str) -> tuple[bool, str]:
        """Send a test notification through one sink, synchronously.

        Returns (ok, message) so the settings UI can show the real error rather
        than making the user check the logs.
        """
        if name not in _SENDERS:
            return False, f"Unknown sink: {name}"
        cfg = get_config().get(name, {})
        notif = {
            "type": "test",
            "title": "CamSuite test notification",
            "message": "If you can read this, this sink is configured correctly.",
        }
        try:
            _SENDERS[name](cfg, notif)
            return True, "Test notification sent"
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = json.dumps(exc.response.json())[:200]
            except Exception:
                detail = exc.response.text[:200]
            return False, f"HTTP {exc.response.status_code}: {detail}"
        except Exception as exc:
            return False, str(exc)


notification_sinks = NotificationSinkDispatcher()
