"""Flirt4Free adapter: parsing, status mapping and stream selection.

Fixtures mirror real responses captured from the site (trimmed).
"""
import pytest

from app.core.sites import flirt4free as f4f
from app.core.sites.base import SiteBlockedError

ONLINE_LIST = """

window.__homePageData__ = {
    'models': [
        {"room_status_char":"O","room_status":"In Open","model_id":"1463042","display":"Rita Grace","model_seo_name":"rita-grace","sample_long_id":"004/748/4748352/4748352"},
        {"room_status_char":"P","room_status":"In Private","model_id":"1463463","display":"Darya Sin","model_seo_name":"darya-sin","sample_long_id":"004/700/1/1"},
        {"room_status_char":"F","room_status":"In Private","model_id":"99","display":"Fan Only","model_seo_name":"fan-only","sample_long_id":""},
    ],
    'favorites': [],
    'promoMarkup': ''
};
"""

GUYS_LIST = """
window.__homePageData__ = {
    'models': [
        {"room_status_char":"O","room_status":"In Open","model_id":"777","display":"Guy Next Door","model_seo_name":"guy-next-door","sample_long_id":"001/2/3/4","service":"guys"},
    ],
    'favorites': [],
};
"""

MASTER = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=788000,CODECS="avc1.64001e,mp4a.40.2",RESOLUTION=640x360
chunklist_b728000.m3u8?key=nil&model_id=1463042&provider=cdn5
#EXT-X-STREAM-INF:BANDWIDTH=1448000,CODECS="avc1.64001f,mp4a.40.2",RESOLUTION=960x540
chunklist_b1328000.m3u8?key=nil&model_id=1463042&provider=cdn5
#EXT-X-STREAM-INF:BANDWIDTH=2548000,CODECS="avc1.64001f,mp4a.40.2",RESOLUTION=1280x720
chunklist_b2328000.m3u8?key=nil&model_id=1463042&provider=cdn5
#EXT-X-STREAM-INF:BANDWIDTH=3978000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1920x1080
chunklist_b3628000.m3u8?key=nil&model_id=1463042&provider=cdn5
"""
MASTER_URL = "https://hls.vscdns.com/manifest.m3u8?key=nil&provider=cdn5&model_id=1463042"


class FakeResp:
    def __init__(self, text="", status=200, ctype="text/html"):
        self.text = text
        self.status_code = status
        self.headers = {"content-type": ctype}


def test_parse_online_list_handles_js_literal():
    models = f4f.parse_online_list(ONLINE_LIST)
    assert [m["model_seo_name"] for m in models] == ["rita-grace", "darya-sin", "fan-only"]


@pytest.mark.parametrize("char,state", [("O", "public"), ("P", "private"), ("F", "private"), ("", "offline"), (None, "offline")])
def test_room_char_mapping(char, state):
    assert f4f.room_char_to_state(char) == state


@pytest.mark.parametrize("quality,expected", [
    ("best", "chunklist_b3628000"),
    ("720", "chunklist_b2328000"),
    ("540", "chunklist_b1328000"),
    ("240", "chunklist_b728000"),  # nothing fits: smallest
])
def test_pick_variant(quality, expected):
    url = f4f.pick_variant(MASTER_URL, MASTER, quality)
    assert url.startswith("https://hls.vscdns.com/" + expected)


def test_pick_variant_passes_through_media_playlist():
    assert f4f.pick_variant(MASTER_URL, "#EXTM3U\n#EXTINF:2.0,\nseg.ts\n") == MASTER_URL


@pytest.mark.parametrize("raw,expected", [
    ("rita-grace", "rita-grace"),
    ("Rita Grace", "rita-grace"),
    ("@Rita_Grace", "rita-grace"),
    ("https://www.flirt4free.com/?model=rita-grace", "rita-grace"),
    ("flirt4free.com/rooms/rita-grace/", "rita-grace"),
])
def test_normalize_username(raw, expected):
    assert f4f.Flirt4FreeAdapter().normalize_username(raw) == expected


def test_normalize_username_rejects_garbage():
    with pytest.raises(ValueError):
        f4f.Flirt4FreeAdapter().normalize_username("../../")


def test_challenge_detection():
    assert f4f.is_challenge_page("<html>Checking Your Browser...</html>")
    assert f4f.is_challenge_page("<script>function leastFactor(n){}</script>")
    assert not f4f.is_challenge_page(ONLINE_LIST)


@pytest.fixture
def adapter(monkeypatch):
    a = f4f.Flirt4FreeAdapter()
    status_calls = []

    def fake_get(url, *, params=None, headers=None, timeout=20, _retry=True):
        if url == f4f.ONLINE_LIST_URLS[0]:
            return FakeResp(ONLINE_LIST)
        if url == f4f.ONLINE_LIST_URLS[1]:
            if a.guys_list_down:
                raise f4f.SiteError("HTTP 500")
            return FakeResp(GUYS_LIST)
        if url == MASTER_URL:
            return FakeResp(MASTER, ctype="application/vnd.apple.mpegurl")
        raise AssertionError(f"unexpected GET {url}")

    def fake_json(url, params=None, **kw):
        if url == f4f.STATUS_URL:
            status_calls.append(params["model_name"])
            name = params["model_name"]
            if name == "sleepy":
                return {"status": "offline", "model_id": 5, "DATA": {"display_name": "Sleepy"}}
            if name == "dormant":
                return {"status": "failed", "message": "Model is inactive"}
            return {"status": "failed", "message": "Model not found"}
        if url == f4f.STREAM_URLS_URL:
            return {"code": 0, "data": {"hls": [{"url": "//hls.vscdns.com/manifest.m3u8?key=nil&provider=cdn5&model_id=1463042"}]}}
        if url == f4f.LOGIN_ROOM_URL:
            return {"config": {"room": {"status": "O"}}}
        raise AssertionError(f"unexpected JSON {url}")

    monkeypatch.setattr(a, "_get", fake_get)
    monkeypatch.setattr(a, "_get_json", fake_json)
    monkeypatch.setattr(f4f.time, "sleep", lambda s: None)
    a.status_calls = status_calls
    a.guys_list_down = False
    return a


def test_check_status_from_online_list(adapter):
    st = adapter.check_status("rita-grace")
    assert st.state == "public" and st.is_public
    assert st.model_id == "1463042"
    assert st.display_name == "Rita Grace"
    assert st.thumbnail_url.endswith("/1463042-desktop.jpg")
    assert st.avatar_url.endswith("4748352/4748352.webp")
    assert adapter.status_calls == []  # list hit: no per-model request


def test_check_status_private(adapter):
    assert adapter.check_status("darya-sin").state == "private"
    assert adapter.check_status("fan-only").state == "private"


def test_check_status_offline_and_missing(adapter):
    st = adapter.check_status("sleepy")
    assert st.state == "offline" and st.model_id == "5" and st.display_name == "Sleepy"
    assert adapter.check_status("dormant").state == "offline"
    assert adapter.check_status("nobody-here").state == "not_found"


def test_bulk_status_uses_one_list_fetch(adapter):
    out = adapter.bulk_status(["rita-grace", "darya-sin", "sleepy"])
    assert out["rita-grace"].is_public
    assert out["darya-sin"].state == "private"
    assert out["sleepy"].state == "offline"
    # Only the model missing from the list costs a per-model request.
    assert adapter.status_calls == ["sleepy"]


def test_mens_list_is_merged(adapter):
    st = adapter.check_status("guy-next-door")
    assert st.is_public and st.model_id == "777"
    assert adapter.status_calls == []


def test_offline_models_are_not_rechecked_every_cycle(adapter, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(f4f.time, "monotonic", lambda: clock[0])

    adapter.bulk_status(["rita-grace", "sleepy"])
    assert adapter.status_calls == ["sleepy"]  # first sighting: safety-net check

    clock[0] += 120  # next monitor cycle
    out = adapter.bulk_status(["rita-grace", "sleepy"])
    assert out["sleepy"].state == "offline"
    assert adapter.status_calls == ["sleepy"]  # lists alone were enough

    clock[0] += f4f._OFFLINE_RECHECK_SECONDS
    adapter.bulk_status(["rita-grace", "sleepy"])
    assert adapter.status_calls == ["sleepy", "sleepy"]  # periodic safety net


def test_failing_list_falls_back_to_per_model_checks(adapter, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(f4f.time, "monotonic", lambda: clock[0])
    adapter.guys_list_down = True

    adapter.bulk_status(["sleepy"])
    clock[0] += 120
    out = adapter.bulk_status(["rita-grace", "sleepy"])
    # The women's list still worked...
    assert out["rita-grace"].is_public
    # ...but with an incomplete picture, missing models are checked every cycle.
    assert adapter.status_calls == ["sleepy", "sleepy"]


def test_get_stream_url_picks_variant(adapter):
    assert adapter.get_playback_url("1463042") == MASTER_URL
    assert "chunklist_b3628000" in adapter.get_stream_url("1463042", "best")
    assert "chunklist_b2328000" in adapter.get_stream_url("1463042", "720")


def test_get_raises_blocked_on_unsolvable_challenge(monkeypatch):
    a = f4f.Flirt4FreeAdapter()

    class Sess:
        def get(self, *args, **kwargs):
            return FakeResp("<html>Checking Your Browser</html>")

    monkeypatch.setattr(a, "_session", lambda: Sess())
    monkeypatch.setattr(a, "_solve_challenge", lambda html: False)
    with pytest.raises(SiteBlockedError):
        a._get("https://www.flirt4free.com/")
