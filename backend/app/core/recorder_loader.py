"""Safe loader for the bundled TikTok recorder package.

The recorder source lives at ``settings.TIKTOK_RECORDER_PATH`` (added to the
build image via ``git clone``). This module makes importing it resilient: if the
path is missing or the import fails, the rest of the API keeps running and
surfaces a clear error instead of crash-looping the whole app.
"""
import sys
import threading
from pathlib import Path

from app.config import settings

_lock = threading.Lock()
_path_added = False
_import_error: str | None = None


def _ensure_path() -> None:
    global _path_added
    if _path_added:
        return
    recorder_path = Path(settings.TIKTOK_RECORDER_PATH)
    if recorder_path.exists():
        path_str = str(recorder_path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    _path_added = True


def recorder_available() -> bool:
    """Return True if the recorder package can be imported."""
    try:
        get_tiktok_api_class()
        return True
    except Exception:
        return False


def recorder_error() -> str | None:
    """Return the last import error message, if any."""
    return _import_error


def get_tiktok_api_class():
    """Lazily import and return the ``TikTokAPI`` class.

    Raises RuntimeError with a helpful message if the recorder is unavailable.
    """
    global _import_error
    with _lock:
        _ensure_path()
        recorder_path = Path(settings.TIKTOK_RECORDER_PATH)
        if not recorder_path.exists():
            _import_error = (
                f"TikTok recorder not found at {recorder_path}. "
                "Ensure the backend image was built with the recorder bundled."
            )
            raise RuntimeError(_import_error)
        try:
            from core.tiktok_api import TikTokAPI  # type: ignore
        except Exception as exc:  # pragma: no cover - defensive
            _import_error = f"Failed to import TikTok recorder: {exc}"
            raise RuntimeError(_import_error) from exc
        _import_error = None
        return TikTokAPI
