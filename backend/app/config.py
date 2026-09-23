import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "CamSuite"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite:///./data/camsuite.db"

    RECORDINGS_DIR: Path = Path("./recordings")
    DATA_DIR: Path = Path("./data")

    # Minutes between watchlist checks. Cam rooms flip public/private often,
    # so this is a short poll.
    DEFAULT_AUTOMATIC_INTERVAL: int = 2
    DEFAULT_PROXY: str | None = None
    # "best" or a max vertical resolution such as "720".
    DEFAULT_PREFERRED_QUALITY: str = "best"

    # Safety-net for automatic recordings: hard cap so a false "still live"
    # signal from the recorder library can't record forever.
    DEFAULT_MAX_RECORDING_HOURS: int = 8
    # Circuit breaker: consecutive bad automatic recordings for the same user
    # (within the lookback window) before we pause auto-recording for them.
    DEFAULT_MAX_CONSECUTIVE_BAD_RECORDINGS: int = 3
    DEFAULT_CIRCUIT_BREAKER_LOOKBACK_MINUTES: int = 120

    # Hard ceiling on simultaneous recordings.  Each one costs a thread, an
    # ffmpeg process, a network stream and sustained disk writes, so without a
    # cap a watchlist that all goes live at once exhausts the host.
    MAX_CONCURRENT_RECORDINGS: int = 10
    # Upper bound on any client-supplied page size, so `?page_size=1000000`
    # cannot materialise an entire library in one request.
    MAX_PAGE_SIZE: int = 200

    # --- Security -------------------------------------------------------
    # This app is designed to be internet-reachable, so auth is on by default.
    # Only turn it off for local development behind a trusted network.
    AUTH_ENABLED: bool = True
    # Set to choose your own login password; otherwise one is generated on
    # first boot and logged once.  Never read directly — see core/auth.py.
    APP_PASSWORD: str | None = None
    # Send the session cookie only over HTTPS.  Leave False if you terminate
    # TLS elsewhere and reach the app over plain HTTP on a private network.
    COOKIE_SECURE: bool = False
    # Browsers may only call the API from these origins.  The default covers
    # the bundled nginx frontend and the Vite dev server.  "*" is rejected.
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    # Expose the interactive API docs.  Off by default now that the app is
    # internet-facing; they leak the full endpoint surface.
    ENABLE_DOCS: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

os.makedirs(settings.RECORDINGS_DIR, exist_ok=True)
os.makedirs(settings.DATA_DIR, exist_ok=True)
