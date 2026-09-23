import shutil
from urllib.parse import urlparse

import psutil
from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.schemas.settings import (
    NotificationSinksConfig,
    NtfyConfig,
    DiscordConfig,
    TelegramBotConfig,
    AutoCleanupConfig,
    CompressionConfig,
    SettingsResponse,
    SettingsUpdate
)
from app.core.site_service import site_service
from app.core.sites import available_sites
from app.core.settings_store import settings_store
from app.core.cleanup_service import cleanup_service
from app.core import compression_service as compression_module
from app.core.compression_service import compression_service
from app.core.task_manager import monitor_service
from app.core import notification_sinks as sinks_module
from app.core.notification_sinks import notification_sinks

router = APIRouter(prefix="/settings", tags=["settings"])



# Secrets are shown to the client only as a short masked preview.  Any value
# the client sends back that still looks masked (or is blank) means "keep what
# is already stored" -- see _resolve_secret().
_MASK_CHAR = "•"


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return _MASK_CHAR * 8
    return _MASK_CHAR * 8 + value[-4:]


def _resolve_secret(submitted: str, current: str) -> str:
    """Return the value to persist for a secret field."""
    submitted = (submitted or "").strip()
    if not submitted or _MASK_CHAR in submitted:
        # Blank or still-masked -> the user did not edit this field.
        return current
    return submitted


def _validate_proxy(value: str | None) -> str | None:
    """Reject anything that is not a plain http(s) proxy URL.

    The proxy is handed to ffmpeg and httpx, so an unvalidated value lets a
    caller redirect all recorder traffic to a host of their choosing.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https", "socks5", "socks5h") or not parsed.hostname:
        raise HTTPException(
            status_code=422,
            detail="Proxy must be an http://, https://, socks5:// or socks5h:// URL",
        )
    return value


def _sink_response() -> NotificationSinksConfig:
    """Sink config for the client, with the two secret fields masked."""
    cfg = sinks_module.get_config()
    ntfy, discord, telegram = cfg["ntfy"], cfg["discord"], cfg["telegram"]
    return NotificationSinksConfig(
        enabled=cfg.get("enabled", False),
        events=cfg.get("events", []),
        ntfy=NtfyConfig(
            enabled=ntfy.get("enabled", False),
            server=ntfy.get("server", "https://ntfy.sh"),
            # Not a credential on its own, but an ntfy topic is a shared secret
            # in practice -- anyone who knows it can read your alerts.
            topic=_mask_secret(ntfy.get("topic", "")),
        ),
        discord=DiscordConfig(
            enabled=discord.get("enabled", False),
            webhook_url=_mask_secret(discord.get("webhook_url", "")),
            webhook_url_set=bool(discord.get("webhook_url")),
        ),
        telegram=TelegramBotConfig(
            enabled=telegram.get("enabled", False),
            bot_token=_mask_secret(telegram.get("bot_token", "")),
            chat_id=telegram.get("chat_id", ""),
            bot_token_set=bool(telegram.get("bot_token")),
        ),
    )


@router.get("", response_model=SettingsResponse)
def get_settings():
    auto_cleanup_data = settings_store.get("auto_cleanup", {
        "enabled": False,
        "days": 7,
        "action": "delete"
    })
    
    return SettingsResponse(
        proxy=settings_store.get("proxy", settings.DEFAULT_PROXY),
        output_dir=str(settings.RECORDINGS_DIR),
        automatic_interval=settings_store.get("automatic_interval", settings.DEFAULT_AUTOMATIC_INTERVAL),
        max_recording_hours=settings_store.get("max_recording_hours", settings.DEFAULT_MAX_RECORDING_HOURS),
        preferred_quality=str(settings_store.get("preferred_quality", settings.DEFAULT_PREFERRED_QUALITY)),
        auto_cleanup=AutoCleanupConfig(**auto_cleanup_data),
        compression=CompressionConfig(**compression_module.get_config()),
        notification_sinks=_sink_response(),
        available_notification_events=sinks_module.ALL_EVENTS,
        timezone=settings_store.get("timezone", "UTC")
    )


@router.put("", response_model=SettingsResponse)
def update_settings(update: SettingsUpdate):
    if update.proxy is not None:
        proxy = _validate_proxy(update.proxy)
        settings_store.set("proxy", proxy)

    if update.preferred_quality is not None:
        settings_store.set("preferred_quality", update.preferred_quality)

    if update.automatic_interval is not None:
        interval = max(1, int(update.automatic_interval))
        settings_store.set("automatic_interval", interval)

    if update.max_recording_hours is not None:
        max_hours = max(1, int(update.max_recording_hours))
        settings_store.set("max_recording_hours", max_hours)


    if update.auto_cleanup is not None:
        settings_store.set("auto_cleanup", {
            "enabled": update.auto_cleanup.enabled,
            "days": update.auto_cleanup.days,
            "action": update.auto_cleanup.action
        })

    if update.compression is not None:
        settings_store.set("compression", update.compression.model_dump())

    if update.notification_sinks is not None:
        current = sinks_module.get_config()
        incoming = update.notification_sinks
        settings_store.set("notification_sinks", {
            "enabled": incoming.enabled,
            "events": [e for e in incoming.events if e in sinks_module.ALL_EVENTS],
            "ntfy": {
                "enabled": incoming.ntfy.enabled,
                "server": incoming.ntfy.server.strip() or "https://ntfy.sh",
                "topic": _resolve_secret(incoming.ntfy.topic, current["ntfy"].get("topic", "")),
            },
            "discord": {
                "enabled": incoming.discord.enabled,
                "webhook_url": _resolve_secret(
                    incoming.discord.webhook_url, current["discord"].get("webhook_url", "")
                ),
            },
            "telegram": {
                "enabled": incoming.telegram.enabled,
                "bot_token": _resolve_secret(
                    incoming.telegram.bot_token, current["telegram"].get("bot_token", "")
                ),
                "chat_id": incoming.telegram.chat_id.strip(),
            },
        })

    if update.timezone is not None:
        settings_store.set("timezone", update.timezone.strip() or "UTC")

    return get_settings()


@router.post("/notifications/test/{sink}")
def test_notification_sink(sink: str):
    """Send a test notification through one sink and report the real error.

    Synchronous on purpose: the settings UI needs the outcome, and making the
    user go read the container logs to find out why a webhook failed is the
    thing this endpoint exists to avoid.
    """
    ok, message = notification_sinks.send_test(sink)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {"status": "ok", "message": message}


@router.get("/health")
def health_check():
    # Deliberately sync: this handler makes blocking HTTP calls to each site
    # and a blocking psutil sample. As `async def` those ran on the event loop
    # and stalled *every* other request. A plain `def` runs in the threadpool.
    sites = []
    for s in available_sites():
        probe = site_service.adapter(s["name"]).reachability()
        sites.append({**s, **probe})
    site_blocked = any(s["blocked"] for s in sites)
    site_reachable = all(s["reachable"] for s in sites)

    # Disk usage of the filesystem hosting the recordings directory
    disk_target = settings.RECORDINGS_DIR if settings.RECORDINGS_DIR.exists() else settings.RECORDINGS_DIR.parent
    try:
        du = shutil.disk_usage(disk_target)
        disk_usage = {
            "total": du.total,
            "used": du.used,
            "free": du.free,
            "percent": round(du.used / du.total * 100, 1),
        }
    except OSError:
        disk_usage = None

    # CPU and RAM usage
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        ram_percent = round(ram.percent, 1)
    except Exception:
        cpu_percent = None
        ram_percent = None

    return {
        "status": "healthy",
        "sites": sites,
        "site_reachable": site_reachable,
        "site_blocked": site_blocked,
        "monitor_error": monitor_service.last_error,
        "compression_available": compression_module.encoder_available(),
        "recordings_dir": str(settings.RECORDINGS_DIR),
        "recordings_dir_exists": settings.RECORDINGS_DIR.exists(),
        "disk_usage": disk_usage,
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
    }


@router.get("/compression/status")
def compression_status():
    """Queue length and progress of the post-recording AV1 compression worker."""
    return compression_service.status()


@router.post("/compression/run")
def compress_existing():
    """Queue every finished recording that has not been compressed yet."""
    if not compression_module.encoder_available():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This ffmpeg build has no AV1 (libsvtav1) encoder")
    if not compression_module.get_config()["enabled"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Compression is turned off in Settings")
    return {"queued": compression_service.enqueue_backlog()}


@router.get("/cleanup/stats")
def get_cleanup_stats():
    """Get statistics about recordings that would be cleaned up."""
    return cleanup_service.get_cleanup_stats()


@router.post("/cleanup/run")
def run_cleanup():
    """Manually trigger the cleanup process."""
    return cleanup_service.run_cleanup()


@router.get("/monitor-status")
async def get_monitor_status():
    """Return current monitor service timer state for the navbar countdown."""
    return monitor_service.get_status()


@router.post("/monitor-check")
def trigger_monitor_check():
    """Trigger an immediate live-status check and reset the interval timer."""
    monitor_service.trigger_check()
    return {"triggered": True}
