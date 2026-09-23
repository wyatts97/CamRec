"""Facade over the site adapters used by routes, the monitor and recording tasks."""
from __future__ import annotations

import logging

from app.config import settings
from app.core.settings_store import settings_store
from app.core.sites import DEFAULT_SITE, ModelStatus, SiteError, get_adapter

logger = logging.getLogger("camsuite.site_service")


class SiteService:
    def adapter(self, site: str | None = None):
        return get_adapter(site or DEFAULT_SITE)

    def preferred_quality(self) -> str:
        return str(settings_store.get("preferred_quality", settings.DEFAULT_PREFERRED_QUALITY) or "best")

    def normalize_username(self, raw: str, site: str | None = None) -> str:
        return self.adapter(site).normalize_username(raw)

    def check_status(self, username: str, site: str | None = None, model_id: str | None = None) -> ModelStatus:
        """Never raises: network/site errors come back as ``state=offline`` with ``error`` set."""
        try:
            return self.adapter(site).check_status(username, model_id)
        except SiteError as exc:
            logger.info("Status check failed for %s/%s: %s", site or DEFAULT_SITE, username, exc)
            return ModelStatus(username=username, state="offline", model_id=model_id, error=str(exc))

    def bulk_status(self, usernames: list[str], site: str | None = None) -> dict[str, ModelStatus]:
        try:
            return self.adapter(site).bulk_status(usernames)
        except SiteError as exc:
            logger.warning("Bulk status failed for %s: %s", site or DEFAULT_SITE, exc)
            return {u: self.check_status(u, site) for u in usernames}

    def is_public(self, model_id: str, site: str | None = None) -> bool:
        return self.adapter(site).is_public(model_id)

    def get_live_url(self, model_id: str, site: str | None = None) -> str:
        """Recordable variant URL. Raises ``RuntimeError`` with a readable reason."""
        try:
            return self.adapter(site).get_stream_url(model_id, self.preferred_quality())
        except SiteError as exc:
            raise RuntimeError(f"Failed to resolve stream URL: {exc}") from exc

    def get_playback_url(self, model_id: str, site: str | None = None) -> str:
        try:
            return self.adapter(site).get_playback_url(model_id)
        except SiteError as exc:
            raise RuntimeError(f"Failed to resolve stream URL: {exc}") from exc


site_service = SiteService()
