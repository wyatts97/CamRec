"""Avatar cache.

Avatars come from the site adapter (profile sample image, or the live
screencap as a fallback) and are cached at ``data/avatars/{site}_{name}.{ext}``
so the UI never hot-links the cam site.
"""
import logging
import os
import threading
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger("camsuite.avatars")

_EXTS = (".webp", ".jpg", ".png")


def _ext_for(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ".jpg"


class UnifiedAvatarService:
    AVATARS_DIR = Path(settings.DATA_DIR) / "avatars"

    # Exponential backoff for failed fetches (seconds)
    _BACKOFF_BASE = 60      # 1 min
    _BACKOFF_MAX = 3600     # 1 hour
    _MAX_RETRIES = 5

    def __init__(self):
        self.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()
        # key -> {last_attempt: ts, attempts: int}
        self._failure_tracker: dict[str, dict] = {}

    @staticmethod
    def key(site: str, username: str) -> str:
        return f"{site}_{username}"

    def get_avatar_path(self, site: str, username: str) -> str | None:
        key = self.key(site, username)
        cached = self._cache.get(key)
        if cached and os.path.exists(cached):
            return cached
        for ext in _EXTS:
            path = self.AVATARS_DIR / f"{key}{ext}"
            if path.exists() and path.stat().st_size > 0:
                self._cache[key] = str(path)
                return str(path)
        return None

    def has_cached_avatar(self, site: str, username: str) -> bool:
        return self.get_avatar_path(site, username) is not None

    def _should_retry(self, key: str) -> bool:
        entry = self._failure_tracker.get(key)
        if not entry:
            return True
        attempts = entry.get("attempts", 0)
        if attempts >= self._MAX_RETRIES:
            return False
        backoff = min(self._BACKOFF_BASE * (2 ** attempts), self._BACKOFF_MAX)
        return (time.time() - entry.get("last_attempt", 0)) >= backoff

    def _record_failure(self, key: str) -> None:
        entry = self._failure_tracker.get(key, {"attempts": 0})
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_attempt"] = time.time()
        self._failure_tracker[key] = entry
        logger.info("Avatar fetch failed for %s (attempt %d)", key, entry["attempts"])

    def get_retryable(self) -> list[tuple[str, str]]:
        """``(site, username)`` pairs whose backoff has expired."""
        out = []
        for key, entry in list(self._failure_tracker.items()):
            if entry.get("attempts", 0) < self._MAX_RETRIES and self._should_retry(key):
                site, _, username = key.partition("_")
                out.append((site, username))
        return out

    def _save(self, site: str, username: str, data: bytes) -> str:
        key = self.key(site, username)
        for ext in _EXTS:
            (self.AVATARS_DIR / f"{key}{ext}").unlink(missing_ok=True)
        path = self.AVATARS_DIR / f"{key}{_ext_for(data)}"
        path.write_bytes(data)
        self._cache[key] = str(path)
        return str(path)

    def fetch_and_cache(
        self,
        site: str,
        username: str,
        avatar_url: str | None = None,
        fallback_url: str | None = None,
        force: bool = False,
    ) -> str | None:
        """Download and cache an avatar.

        Without URLs, asks the site adapter for the model's current status to
        find one. Offline models often have no image available; that counts as
        a failure so it is retried later with backoff.
        """
        from app.core.site_service import site_service

        key = self.key(site, username)
        if not force and self.has_cached_avatar(site, username):
            return self.get_avatar_path(site, username)
        if force:
            self._failure_tracker.pop(key, None)
        if not self._should_retry(key):
            return None
        with self._lock:
            if key in self._in_flight:
                return None
            self._in_flight.add(key)
        try:
            if not avatar_url and not fallback_url:
                status = site_service.check_status(username, site)
                avatar_url, fallback_url = status.avatar_url, status.thumbnail_url
            adapter = site_service.adapter(site)
            for url in (avatar_url, fallback_url):
                if not url:
                    continue
                data = adapter.fetch_bytes(url)
                if data and len(data) > 500:
                    path = self._save(site, username, data)
                    self._failure_tracker.pop(key, None)
                    logger.info("Cached avatar for %s (%d bytes)", key, len(data))
                    return path
            self._record_failure(key)
            return None
        finally:
            with self._lock:
                self._in_flight.discard(key)

    def delete_avatar(self, site: str, username: str) -> bool:
        key = self.key(site, username)
        self._cache.pop(key, None)
        deleted = False
        for ext in _EXTS:
            path = self.AVATARS_DIR / f"{key}{ext}"
            if path.exists():
                try:
                    os.remove(path)
                    deleted = True
                except OSError:
                    pass
        return deleted


unified_avatar_service = UnifiedAvatarService()
