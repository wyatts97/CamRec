from pydantic import BaseModel


class CookiesConfig(BaseModel):
    """Cookie config as sent to the client.

    ``sessionid_ss`` is a live TikTok session token, so it is never returned in
    full -- only a masked preview plus a flag saying whether one is stored.
    """
    sessionid_ss: str = ""
    tt_target_idc: str = "useast2a"
    sessionid_ss_set: bool = False


class TelegramConfig(BaseModel):
    api_id: str = ""
    api_hash: str = ""
    chat_id: str = "me"
    api_hash_set: bool = False


class NtfyConfig(BaseModel):
    enabled: bool = False
    server: str = "https://ntfy.sh"
    topic: str = ""


class DiscordConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    webhook_url_set: bool = False


class TelegramBotConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    bot_token_set: bool = False


class NotificationSinksConfig(BaseModel):
    """Delivery of notifications to services outside the browser."""
    enabled: bool = False
    events: list[str] = []
    ntfy: NtfyConfig = NtfyConfig()
    discord: DiscordConfig = DiscordConfig()
    telegram: TelegramBotConfig = TelegramBotConfig()


class AutoCleanupConfig(BaseModel):
    enabled: bool = False
    days: int = 7  # 1, 3, 7, 14, 30
    action: str = "delete"  # "delete" or "compress"


class SettingsResponse(BaseModel):
    cookies: CookiesConfig
    telegram: TelegramConfig
    proxy: str | None = None
    output_dir: str
    default_bitrate: str | None = None
    automatic_interval: int = 5
    max_recording_hours: int = 8
    chat_authenticated: bool = False
    auto_cleanup: AutoCleanupConfig = AutoCleanupConfig()
    notification_sinks: NotificationSinksConfig = NotificationSinksConfig()
    available_notification_events: list[str] = []
    timezone: str = "UTC"


class SettingsUpdate(BaseModel):
    cookies: CookiesConfig | None = None
    telegram: TelegramConfig | None = None
    proxy: str | None = None
    default_bitrate: str | None = None
    automatic_interval: int | None = None
    max_recording_hours: int | None = None
    chat_authenticated: bool | None = None
    auto_cleanup: AutoCleanupConfig | None = None
    notification_sinks: NotificationSinksConfig | None = None
    timezone: str | None = None
