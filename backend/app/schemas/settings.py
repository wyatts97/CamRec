from pydantic import BaseModel, Field


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
    proxy: str | None = None
    output_dir: str
    automatic_interval: int = 2
    max_recording_hours: int = 8
    preferred_quality: str = "best"
    auto_cleanup: AutoCleanupConfig = AutoCleanupConfig()
    notification_sinks: NotificationSinksConfig = NotificationSinksConfig()
    available_notification_events: list[str] = []
    timezone: str = "UTC"


class SettingsUpdate(BaseModel):
    proxy: str | None = None
    automatic_interval: int | None = None
    max_recording_hours: int | None = None
    preferred_quality: str | None = Field(default=None, pattern="^(best|1080|720|540|480|360)$")
    auto_cleanup: AutoCleanupConfig | None = None
    notification_sinks: NotificationSinksConfig | None = None
    timezone: str | None = None
