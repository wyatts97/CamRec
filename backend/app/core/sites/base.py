"""Site adapter contract.

Everything that knows how a particular cam site works lives behind this
interface. The recording engine, monitor and routes only ever talk to a
``SiteAdapter``, so adding a new site means writing one adapter module and
registering it in ``registry.py``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Literal

RoomState = Literal["public", "private", "offline", "not_found"]


class SiteError(RuntimeError):
    """A site request failed (network, unexpected payload, ...)."""


class SiteBlockedError(SiteError):
    """The site answered with an anti-bot / access-denied page we could not pass."""


@dataclass
class ModelStatus:
    username: str
    state: RoomState
    model_id: str | None = None
    display_name: str | None = None
    # Live screencap of the room (only meaningful while online).
    thumbnail_url: str | None = None
    # Profile / sample image usable as an avatar.
    avatar_url: str | None = None
    error: str | None = None

    @property
    def is_public(self) -> bool:
        return self.state == "public"

    @property
    def is_online(self) -> bool:
        return self.state in ("public", "private")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_live"] = self.is_public
        d["is_public"] = self.is_public
        return d


class SiteAdapter(ABC):
    #: Registry key stored in ``users.site``.
    name: str
    #: Human-readable site name for the UI.
    label: str
    #: Prefix for recording filenames, e.g. ``F4F``.
    file_prefix: str

    def __init__(self, proxy: str | None = None):
        self.proxy = proxy

    def set_proxy(self, proxy: str | None) -> None:
        self.proxy = proxy

    @abstractmethod
    def normalize_username(self, raw: str) -> str:
        """Turn a username, display name or profile URL into the canonical name."""

    @abstractmethod
    def check_status(self, username: str, model_id: str | None = None) -> ModelStatus:
        """Return the current room state for one model."""

    def bulk_status(self, usernames: list[str]) -> dict[str, ModelStatus]:
        """Status for many models at once. Sites with a cheap online list override this."""
        return {u: self.check_status(u) for u in usernames}

    @abstractmethod
    def is_public(self, model_id: str) -> bool:
        """Cheap re-check used while a recording is running."""

    @abstractmethod
    def get_stream_url(self, model_id: str, quality: str = "best") -> str:
        """Return a URL ffmpeg can record (a single HLS variant playlist)."""

    @abstractmethod
    def get_playback_url(self, model_id: str) -> str:
        """Return a URL the browser can play (usually the HLS master playlist)."""

    @abstractmethod
    def profile_url(self, username: str) -> str:
        """Public page for the model on the site."""

    def screencap_url(self, model_id: str) -> str | None:
        """Still image of the live room, if the site publishes one."""
        return None

    def ffmpeg_headers(self) -> dict[str, str]:
        """Extra HTTP headers ffmpeg must send when pulling the stream."""
        return {}

    def fetch_bytes(self, url: str) -> bytes | None:
        """Download a small asset (avatar/screencap) through the site's session."""
        return None

    def reachability(self) -> dict:
        """Health probe for the settings page: ``{reachable, blocked, error}``."""
        return {"reachable": True, "blocked": False, "error": None}
