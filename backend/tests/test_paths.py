"""Tests for the media path containment guard (core/media_utils.resolve_within)."""
import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def media():
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["RECORDINGS_DIR"] = os.path.join(tmp, "recordings")
    import importlib
    import app.config
    importlib.reload(app.config)
    import app.core.media_utils as m
    importlib.reload(m)
    return m


def test_normal_filename_resolves_inside_base(media):
    p = media.recording_path("TK_someuser_2024.01.01_00-00-00.mp4")
    assert str(p).startswith(str(media.settings.RECORDINGS_DIR.resolve()))


@pytest.mark.parametrize("evil", [
    "../secrets.txt",
    "../../etc/passwd",
    "sub/../../escape.mp4",
    r"..\..\windows\system32\config",
])
def test_traversal_is_rejected(media, evil):
    with pytest.raises(media.UnsafePathError):
        media.recording_path(evil)


def test_absolute_path_is_rejected(media):
    absolute = r"C:\Windows\System32\drivers\etc\hosts" if os.name == "nt" else "/etc/passwd"
    with pytest.raises(media.UnsafePathError):
        media.recording_path(absolute)


def test_nested_subdirectory_is_allowed(media):
    # Clips legitimately live in a subdirectory of the recordings root.
    p = media.resolve_within(media.settings.RECORDINGS_DIR, "clips/my-clip.mp4")
    assert "clips" in str(p)
