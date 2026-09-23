"""Persistent key/value store for runtime-configurable settings.

Backed by a JSON file (``data/settings.json``) so changes made in the WebUI
(proxy, default bitrate, automatic interval) survive restarts. Static defaults
come from ``app.config.settings``.
"""
import json
import os
import threading
from typing import Any

from app.config import settings


class SettingsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._path = settings.DATA_DIR / "settings.json"
        self._data: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {
            "proxy": settings.DEFAULT_PROXY,
            "default_bitrate": settings.DEFAULT_BITRATE,
            "automatic_interval": settings.DEFAULT_AUTOMATIC_INTERVAL,
            "max_recording_hours": settings.DEFAULT_MAX_RECORDING_HOURS,
            # Off by default: authenticated chat sends the TikTok session ID to
            # a third-party sign server (Euler Stream).
            "chat_authenticated": False,
        }
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def _save(self) -> None:
        # Atomic write. A truncated file here is silently swallowed by _load()
        # and resets every runtime setting to defaults -- wiping the user's
        # proxy, notification sinks and retention policy. Same tmp+replace
        # dance core/auth.py uses for the credential file.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
            if key in self._defaults:
                return self._defaults[key]
            return default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._data.update(values)
            self._save()

    def all(self) -> dict[str, Any]:
        with self._lock:
            merged = dict(self._defaults)
            merged.update(self._data)
            return merged


settings_store = SettingsStore()
