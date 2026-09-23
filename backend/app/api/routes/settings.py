import json
import shutil
from urllib.parse import urlparse

import psutil
from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.schemas.settings import (
    CookiesConfig,
    NotificationSinksConfig,
    NtfyConfig,
    DiscordConfig,
    TelegramBotConfig,
    TelegramConfig,
    AutoCleanupConfig,
    SettingsResponse,
    SettingsUpdate
)
from app.core.recorder_service import recorder_service
from app.core.settings_store import settings_store
from app.core.cleanup_service import cleanup_service
from app.core.task_manager import monitor_service
from app.core import notification_sinks as sinks_module
from app.core.notification_sinks import notification_sinks

router = APIRouter(prefix="/settings", tags=["settings"])


def _read_json_file(path, default: dict) -> dict:
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default


def _write_json_file(path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


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
    cookies_data = _read_json_file(
        settings.COOKIES_FILE,
        {"sessionid_ss": "", "tt-target-idc": "useast2a"}
    )
    
    telegram_data = _read_json_file(
        settings.TELEGRAM_CONFIG_FILE,
        {"api_id": "", "api_hash": "", "chat_id": "me"}
    )
    
    auto_cleanup_data = settings_store.get("auto_cleanup", {
        "enabled": False,
        "days": 7,
        "action": "delete"
    })
    
    return SettingsResponse(
        cookies=CookiesConfig(
            sessionid_ss=_mask_secret(cookies_data.get("sessionid_ss", "")),
            tt_target_idc=cookies_data.get("tt-target-idc", "useast2a"),
            sessionid_ss_set=bool(cookies_data.get("sessionid_ss")),
        ),
        telegram=TelegramConfig(
            api_id=telegram_data.get("api_id", ""),
            api_hash=_mask_secret(telegram_data.get("api_hash", "")),
            chat_id=telegram_data.get("chat_id", "me"),
            api_hash_set=bool(telegram_data.get("api_hash")),
        ),
        proxy=settings_store.get("proxy", settings.DEFAULT_PROXY),
        output_dir=str(settings.RECORDINGS_DIR),
        default_bitrate=settings_store.get("default_bitrate", settings.DEFAULT_BITRATE),
        automatic_interval=settings_store.get("automatic_interval", settings.DEFAULT_AUTOMATIC_INTERVAL),
        max_recording_hours=settings_store.get("max_recording_hours", settings.DEFAULT_MAX_RECORDING_HOURS),
        chat_authenticated=bool(settings_store.get("chat_authenticated", False)),
        auto_cleanup=AutoCleanupConfig(**auto_cleanup_data),
        notification_sinks=_sink_response(),
        available_notification_events=sinks_module.ALL_EVENTS,
        timezone=settings_store.get("timezone", "UTC")
    )


@router.put("", response_model=SettingsResponse)
def update_settings(update: SettingsUpdate):
    if update.cookies:
        existing = _read_json_file(settings.COOKIES_FILE, {})
        cookies_data = {
            "sessionid_ss": _resolve_secret(
                update.cookies.sessionid_ss, existing.get("sessionid_ss", "")
            ),
            "tt-target-idc": update.cookies.tt_target_idc,
        }
        _write_json_file(settings.COOKIES_FILE, cookies_data)
        recorder_service.reload_cookies()

    if update.telegram:
        existing = _read_json_file(settings.TELEGRAM_CONFIG_FILE, {})
        telegram_data = {
            "api_id": update.telegram.api_id,
            "api_hash": _resolve_secret(
                update.telegram.api_hash, existing.get("api_hash", "")
            ),
            "chat_id": update.telegram.chat_id,
        }
        _write_json_file(settings.TELEGRAM_CONFIG_FILE, telegram_data)

    if update.proxy is not None:
        proxy = _validate_proxy(update.proxy)
        settings_store.set("proxy", proxy)
        recorder_service.set_proxy(proxy)

    if update.default_bitrate is not None:
        bitrate = update.default_bitrate.strip() or None
        settings_store.set("default_bitrate", bitrate)

    if update.automatic_interval is not None:
        interval = max(1, int(update.automatic_interval))
        settings_store.set("automatic_interval", interval)

    if update.max_recording_hours is not None:
        max_hours = max(1, int(update.max_recording_hours))
        settings_store.set("max_recording_hours", max_hours)

    if update.chat_authenticated is not None:
        settings_store.set("chat_authenticated", bool(update.chat_authenticated))

    if update.auto_cleanup is not None:
        settings_store.set("auto_cleanup", {
            "enabled": update.auto_cleanup.enabled,
            "days": update.auto_cleanup.days,
            "action": update.auto_cleanup.action
        })

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
    # Deliberately sync: this handler makes a blocking HTTP call to TikTok
    # (is_country_blacklisted) and a blocking psutil sample. As `async def`
    # those ran on the event loop and stalled *every* other request for the
    # duration. A plain `def` lets Starlette run it in the threadpool.
    cookies_data = _read_json_file(settings.COOKIES_FILE, {})
    has_cookies = bool(cookies_data.get("sessionid_ss"))

    recorder_ready = recorder_service.is_available()
    is_blacklisted = recorder_service.is_country_blacklisted() if recorder_ready else False

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
        "recorder_available": recorder_ready,
        "country_blacklisted": is_blacklisted,
        "cookies_configured": has_cookies,
        "recordings_dir": str(settings.RECORDINGS_DIR),
        "recordings_dir_exists": settings.RECORDINGS_DIR.exists(),
        "disk_usage": disk_usage,
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
    }


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
