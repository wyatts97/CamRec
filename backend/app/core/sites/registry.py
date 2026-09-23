"""Site adapter registry. Add new cam sites here."""
from __future__ import annotations

import threading

from app.core.sites.base import SiteAdapter
from app.core.sites.flirt4free import Flirt4FreeAdapter

DEFAULT_SITE = "flirt4free"

_ADAPTER_CLASSES: dict[str, type[SiteAdapter]] = {
    Flirt4FreeAdapter.name: Flirt4FreeAdapter,
}

_instances: dict[str, SiteAdapter] = {}
_lock = threading.Lock()


def available_sites() -> list[dict]:
    return [{"name": cls.name, "label": cls.label} for cls in _ADAPTER_CLASSES.values()]


def get_adapter(site: str | None = None) -> SiteAdapter:
    """Shared adapter instance for *site*, configured with the current proxy."""
    from app.config import settings
    from app.core.settings_store import settings_store

    site = site or DEFAULT_SITE
    cls = _ADAPTER_CLASSES.get(site)
    if cls is None:
        raise ValueError(f"Unsupported site: {site}")
    proxy = settings_store.get("proxy", settings.DEFAULT_PROXY) or None
    with _lock:
        adapter = _instances.get(site)
        if adapter is None:
            adapter = cls(proxy=proxy)
            _instances[site] = adapter
    adapter.set_proxy(proxy)
    return adapter
