"""Unified avatar fetching service.

Uses the bundled TikTok recorder API (webcast room/info) to get avatar URLs.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path


from curl_cffi import requests

from app.config import settings

logger = logging.getLogger(__name__)


class UnifiedAvatarService:
    AVATARS_DIR = Path(settings.DATA_DIR) / "avatars"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # Exponential backoff for failed fetches (seconds)
    _BACKOFF_BASE = 60      # 1 min
    _BACKOFF_MAX = 3600     # 1 hour
    _MAX_RETRIES = 5

    def __init__(self):
        self.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        # In-memory cache: username -> path. Avoids filesystem stat on every
        # GET /users call. Populated lazily by get_avatar_path / has_cached_avatar.
        self._cache: dict[str, str] = {}
        # Prevent concurrent fetches for the same username
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        # Track failures for retry: username -> {last_attempt: ts, attempts: int}
        self._failure_tracker: dict[str, dict] = {}

    def _avatar_path(self, username: str) -> Path:
        return self.AVATARS_DIR / f"{username}.jpg"

    def _save_debug(self, username: str, content: str, suffix: str = "html") -> None:
        """Save raw response content for debugging blocked pages."""
        try:
            debug_dir = Path(settings.DATA_DIR) / "avatar-debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            path = debug_dir / f"{username}_{int(time.time())}.{suffix}"
            path.write_text(content, encoding="utf-8")
            logger.info(f"Saved debug snapshot for @{username} -> {path}")
        except Exception:
            pass

    def has_cached_avatar(self, username: str) -> bool:
        """Check if we have a cached avatar for this user."""
        if username in self._cache:
            return True
        path = self._avatar_path(username)
        if path.exists() and path.stat().st_size > 0:
            self._cache[username] = str(path)
            return True
        return False

    def _download_and_cache(self, username: str, url: str) -> str | None:
        """Download avatar image and save locally. Returns local path or None."""
        try:
            headers = {"User-Agent": self.USER_AGENT}

            # Add cookies for authenticated access
            cookie_str = self._load_cookies_string()
            if cookie_str:
                headers["Cookie"] = cookie_str

            # Load proxy if configured
            proxy = self._load_proxy()
            proxies = {"https": proxy, "http": proxy} if proxy else None

            with requests.Session() as client:
                response = client.get(
                    url,
                    headers=headers,
                    timeout=15,
                    impersonate="chrome120",
                    proxies=proxies,
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if content_type.startswith("image/") or len(response.content) > 1000:
                    path = self._avatar_path(username)
                    path.write_bytes(response.content)
                    self._cache[username] = str(path)
                    logger.info(f"Cached avatar for @{username} -> {path} ({len(response.content)} bytes)")
                    return str(path)
                else:
                    logger.warning(f"Avatar response for @{username} not an image: content-type={content_type}, size={len(response.content)}")
        except Exception as exc:
            logger.warning(f"Failed to download avatar for @{username}: {exc}")
        return None

    def download_and_cache(self, username: str, url: str) -> str | None:
        """Public wrapper to download and cache an avatar from a known URL."""
        return self._download_and_cache(username, url)

    def _should_retry(self, username: str) -> bool:
        """Check if enough time has passed since the last failed attempt."""
        entry = self._failure_tracker.get(username)
        if not entry:
            return True
        attempts = entry.get("attempts", 0)
        if attempts >= self._MAX_RETRIES:
            return False
        last_attempt = entry.get("last_attempt", 0)
        backoff = min(self._BACKOFF_BASE * (2 ** attempts), self._BACKOFF_MAX)
        return (time.time() - last_attempt) >= backoff

    def _record_failure(self, username: str) -> None:
        entry = self._failure_tracker.get(username, {"attempts": 0})
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_attempt"] = time.time()
        self._failure_tracker[username] = entry
        logger.warning(f"Avatar fetch failed for @{username} (attempt {entry['attempts']})")

    def _record_success(self, username: str) -> None:
        self._failure_tracker.pop(username, None)

    def reset_failure(self, username: str) -> None:
        """Clear failure tracker for a user (e.g., manual refresh)."""
        self._failure_tracker.pop(username, None)

    def get_retryable_usernames(self) -> list[str]:
        """Return usernames whose backoff has expired and are eligible for retry."""
        return [
            u for u, entry in self._failure_tracker.items()
            if entry.get("attempts", 0) < self._MAX_RETRIES
            and self._should_retry(u)
        ]

    def _fetch_via_recorder(self, room_id: str) -> str | None:
        """Use the bundled TikTokAPI to get avatar URL from room info.

        Calls the webcast room/info endpoint (which TikTok does not block
        as aggressively as the profile page) and extracts avatar URLs from
        the owner field.
        """
        try:
            from app.core.recorder_loader import get_tiktok_api_class
            from app.core.settings_store import settings_store
            from app.config import settings as app_settings

            proxy = settings_store.get("proxy", app_settings.DEFAULT_PROXY)
            cookies = None
            if app_settings.COOKIES_FILE.exists():
                import json as _json
                with open(app_settings.COOKIES_FILE, "r") as f:
                    cookies = _json.load(f)

            api_cls = get_tiktok_api_class()
            api = api_cls(proxy=proxy, cookies=cookies)

            data = api.http_client.get(
                f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}"
            ).json()

            owner = data.get("data", {}).get("owner", {})
            avatar_url = (
                owner.get("avatar_large", {}).get("url_list", [None])[0]
                or owner.get("avatar_medium", {}).get("url_list", [None])[0]
                or owner.get("avatar_thumb", {}).get("url_list", [None])[0]
            )
            if avatar_url:
                logger.info(f"Got avatar URL via recorder API (room_id={room_id})")
                return avatar_url
        except Exception as exc:
            logger.warning(f"Recorder avatar fetch failed: {exc}")
        return None

    def _load_cookies_string(self) -> str:
        """Load TikTok cookies from settings and return as Cookie header string."""
        try:
            from app.config import settings as app_settings
            if app_settings.COOKIES_FILE.exists():
                import json as _json
                with open(app_settings.COOKIES_FILE, "r") as f:
                    cookies = _json.load(f)
                if cookies.get("sessionid_ss"):
                    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
        except Exception:
            pass
        return ""

    def _load_proxy(self) -> str | None:
        """Load proxy from settings store."""
        try:
            from app.core.settings_store import settings_store
            from app.config import settings as app_settings
            return settings_store.get("proxy", app_settings.DEFAULT_PROXY)
        except Exception:
            return None

    def fetch_and_cache(self, username: str, room_id: str | None = None, force: bool = False) -> str | None:
        """
        Fetch avatar for a user and cache it locally.

        Args:
            username: TikTok username.
            room_id: Optional room_id to use the recorder API (preferred).
            force: If True, re-fetch even if cached.

        Returns:
            Local filesystem path to the cached avatar, or None.
        """
        if not force and self.has_cached_avatar(username):
            return str(self._avatar_path(username))

        # Clear failure tracker on manual force-refresh
        if force:
            self.reset_failure(username)

        # Retry backoff gate
        if not self._should_retry(username):
            logger.info(f"Avatar fetch for @{username} skipped: backoff active")
            return None

        # Deduplication: prevent concurrent fetches for the same username
        with self._lock:
            if username in self._in_flight:
                logger.info(f"Avatar fetch for @{username} already in flight")
                return None
            self._in_flight.add(username)

        try:
            # Primary: recorder API via webcast room/info (works reliably)
            avatar_url: str | None = None
            if not room_id:
                try:
                    from app.core.recorder_service import recorder_service
                    room_id = recorder_service.get_room_id(username)
                except Exception:
                    pass
            if room_id:
                avatar_url = self._fetch_via_recorder(room_id)

            if avatar_url:
                result = self._download_and_cache(username, avatar_url)
                if result:
                    self._record_success(username)
                    return result
                else:
                    self._record_failure(username)
                    return None

            self._record_failure(username)
            logger.warning(f"All avatar fetch methods failed for @{username}")
            return None
        finally:
            with self._lock:
                self._in_flight.discard(username)

    def get_avatar_path(self, username: str) -> str | None:
        """Return cached avatar path if it exists, else None."""
        cached = self._cache.get(username)
        if cached:
            return cached
        path = self._avatar_path(username)
        if path.exists() and path.stat().st_size > 0:
            self._cache[username] = str(path)
            return str(path)
        return None

    def delete_avatar(self, username: str) -> bool:
        """Delete a cached avatar. Returns True if deleted, False otherwise."""
        self._cache.pop(username, None)
        path = self._avatar_path(username)
        if path.exists():
            try:
                os.remove(path)
                return True
            except OSError:
                pass
        return False


unified_avatar_service = UnifiedAvatarService()
