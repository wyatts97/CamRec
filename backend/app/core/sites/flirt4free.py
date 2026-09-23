"""Flirt4Free adapter.

Endpoints (verified against the live site):

* ``/?tpl=index2&model=json`` (XHR): every online model as JS-ish object
  literal ``window.__homePageData__ = {'models': [...], 'favorites': ...}``.
  Each entry has ``model_seo_name``, ``model_id``, ``display``,
  ``room_status_char`` (``O`` open/free chat, ``P``/``F`` private-type shows)
  and ``sample_long_id`` (profile image).
* ``ws.vs3.com/rooms/check-model-status.php?model_name=`` - single model:
  ``{"status": "online"|"offline", "model_id": ..., "DATA": {...}}`` or
  ``{"status": "failed", "message": "Model not found"|"Model is inactive"}``.
* ``/ws/rooms/chat-room-interface.php?a=login_room&model_id=`` -
  ``config.room.status`` is the authoritative room state letter.
* ``/ws/chat/get-stream-urls.php?model_id=`` - ``data.hls[0].url`` is a
  protocol-relative HLS master playlist with one variant per resolution.

The HLS CDN needs no cookies or Referer; ffmpeg can pull a variant directly.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import unquote, urljoin

from curl_cffi import requests as cffi_requests

from app.core.sites.base import ModelStatus, SiteAdapter, SiteBlockedError, SiteError

logger = logging.getLogger("camsuite.sites.flirt4free")

BASE = "https://www.flirt4free.com"
STATUS_URL = "https://ws.vs3.com/rooms/check-model-status.php"
ONLINE_LIST_URL = f"{BASE}/?tpl=index2&model=json"
LOGIN_ROOM_URL = f"{BASE}/ws/rooms/chat-room-interface.php"
STREAM_URLS_URL = f"{BASE}/ws/chat/get-stream-urls.php"
SCREENCAP_URL = "https://live-screencaps.vscdns.com/{model_id}-desktop.jpg"
AVATAR_URL = "https://cdn5.vscdns.com/images/models/webp/s/640x480/imgid/{sample_long_id}.webp"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")

# The online list is one ~300 KB request covering every open room; reusing it
# for this long lets one monitor cycle check the whole watchlist with it.
_ONLINE_LIST_TTL = 45

# Node shim that runs an anti-bot challenge script with a fake DOM and prints
# the cookies it sets. Only used if the site ever serves its
# "Checking Your Browser" (leastFactor) page instead of JSON.
_CHALLENGE_SHIM = r"""
const src = require('fs').readFileSync(0, 'utf8');
const cookies = [];
const location = { href: '', reload() {}, replace() {}, assign() {} };
const document = {
  set cookie(v) { cookies.push(String(v)); },
  get cookie() { return cookies.map(c => c.split(';')[0]).join('; '); },
  location, write() {}, getElementById() { return null; },
};
const window = { document, location, navigator: { userAgent: 'Mozilla/5.0' } };
window.window = window;
try { eval(src + '\n'); } catch (e) {}
setTimeout(() => process.stdout.write(JSON.stringify(cookies)), 100);
"""


def is_challenge_page(text: str) -> bool:
    return "Checking Your Browser" in text or "function leastFactor" in text


def parse_online_list(text: str) -> list[dict]:
    """Extract the ``models`` array from the home-page data blob."""
    key = text.find("'models':")
    if key < 0:
        key = text.find('"models":')
    if key < 0:
        raise SiteError("Online list: 'models' key not found")
    start = text.index("[", key)
    end = text.find("'favorites'", start)
    chunk = text[start:end] if end > 0 else text[start:]
    # The blob is a JS literal: strip the trailing comma(s) before the array
    # closes and anything after it.
    chunk = chunk.strip()
    chunk = re.sub(r",\s*$", "", chunk)
    chunk = re.sub(r",\s*\]$", "]", chunk)
    try:
        models, _ = json.JSONDecoder().raw_decode(chunk)
    except json.JSONDecodeError as exc:
        raise SiteError(f"Online list: could not parse models array ({exc})") from exc
    if not isinstance(models, list):
        raise SiteError("Online list: models is not a list")
    return models


def room_char_to_state(char: str | None) -> str:
    if char == "O":
        return "public"
    if char:
        return "private"
    return "offline"


def pick_variant(master_url: str, playlist: str, quality: str = "best") -> str:
    """Choose one variant from an HLS master playlist.

    ``quality`` is ``"best"`` or a maximum height such as ``"720"``. Falls
    back to the smallest variant when none fits under the cap.
    """
    variants: list[tuple[int, int, str]] = []  # (height, bandwidth, uri)
    lines = [l.strip() for l in playlist.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        uri = next((l for l in lines[i + 1:] if l and not l.startswith("#")), None)
        if not uri:
            continue
        res = re.search(r"RESOLUTION=\d+x(\d+)", line)
        bw = re.search(r"BANDWIDTH=(\d+)", line)
        variants.append((int(res.group(1)) if res else 0, int(bw.group(1)) if bw else 0, uri))
    if not variants:
        # Already a media playlist.
        return master_url
    variants.sort()
    chosen = variants[-1]
    if quality and quality != "best":
        try:
            cap = int(quality)
        except ValueError:
            cap = None
        if cap:
            fitting = [v for v in variants if v[0] <= cap]
            chosen = fitting[-1] if fitting else variants[0]
    return urljoin(master_url, chosen[2])


class Flirt4FreeAdapter(SiteAdapter):
    name = "flirt4free"
    label = "Flirt4Free"
    file_prefix = "F4F"

    def __init__(self, proxy: str | None = None):
        super().__init__(proxy)
        self._local = threading.local()
        self._list_lock = threading.Lock()
        self._list_cache: tuple[float, dict[str, dict]] | None = None
        # Cookies earned by solving a challenge, shared by every thread's session.
        self._challenge_cookies: dict[str, str] = {}
        self.last_blocked_at: float | None = None

    # ------------------------------------------------------------------ http
    def set_proxy(self, proxy: str | None) -> None:
        if proxy != self.proxy:
            super().set_proxy(proxy)
            self._local = threading.local()

    def _session(self) -> cffi_requests.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = cffi_requests.Session(impersonate="chrome")
            sess.headers.update({"Referer": f"{BASE}/", "Accept-Language": "en-US,en;q=0.9"})
            if self.proxy:
                sess.proxies = {"http": self.proxy, "https": self.proxy}
            self._local.session = sess
        for k, v in self._challenge_cookies.items():
            sess.cookies.set(k, v)
        return sess

    def _get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
             timeout: float = 20, _retry: bool = True):
        try:
            resp = self._session().get(url, params=params, headers=headers, timeout=timeout)
        except Exception as exc:
            raise SiteError(f"Request to {url.split('?')[0]} failed: {exc}") from exc
        ctype = resp.headers.get("content-type", "")
        if "html" in ctype and is_challenge_page(resp.text):
            self.last_blocked_at = time.time()
            if _retry and self._solve_challenge(resp.text):
                return self._get(url, params=params, headers=headers, timeout=timeout, _retry=False)
            raise SiteBlockedError("Flirt4Free served a browser-check page that could not be solved")
        if resp.status_code in (403, 429, 503):
            self.last_blocked_at = time.time()
            raise SiteBlockedError(f"Flirt4Free returned HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise SiteError(f"Flirt4Free returned HTTP {resp.status_code} for {url.split('?')[0]}")
        return resp

    def _get_json(self, url: str, **kw) -> dict:
        resp = self._get(url, headers={"Accept": "application/json, text/plain, */*"}, **kw)
        try:
            return resp.json()
        except Exception as exc:
            raise SiteError(f"Unexpected non-JSON response from {url.split('?')[0]}") from exc

    def _solve_challenge(self, html: str) -> bool:
        node = shutil.which("node")
        if not node:
            logger.warning("Challenge page received but node is not installed; cannot solve")
            return False
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)
        script = "\n".join(s for s in scripts if "cookie" in s)
        if not script:
            return False
        try:
            out = subprocess.run(
                [node, "-e", _CHALLENGE_SHIM], input=script, capture_output=True,
                text=True, timeout=10,
            ).stdout
            cookies = json.loads(out or "[]")
        except Exception as exc:
            logger.warning("Challenge solver failed: %s", exc)
            return False
        solved = {}
        for c in cookies:
            pair = c.split(";", 1)[0]
            if "=" in pair:
                k, v = pair.split("=", 1)
                solved[k.strip()] = v.strip()
        if not solved:
            return False
        logger.info("Solved Flirt4Free browser check (cookies: %s)", ", ".join(solved))
        self._challenge_cookies.update(solved)
        return True

    # ------------------------------------------------------------ discovery
    def normalize_username(self, raw: str) -> str:
        raw = (raw or "").strip()
        m = re.search(r"[?&]model=([^&#]+)", raw) or re.search(
            r"flirt4free\.com/(?:rooms|models?|videos|live)/([^/?#]+)", raw, re.I
        )
        name = unquote(m.group(1)) if m else raw
        name = name.strip().lstrip("@").lower()
        name = re.sub(r"[\s_]+", "-", name)
        name = re.sub(r"[^a-z0-9\-]", "", name).strip("-")
        if not USERNAME_RE.match(name):
            raise ValueError("Enter a Flirt4Free model name or profile URL")
        return name

    def online_models(self, force: bool = False) -> dict[str, dict]:
        """``{seo_name: entry}`` for every model currently online."""
        with self._list_lock:
            cached = self._list_cache
            if not force and cached and time.monotonic() - cached[0] < _ONLINE_LIST_TTL:
                return cached[1]
        resp = self._get(ONLINE_LIST_URL, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        models = parse_online_list(resp.text)
        by_name = {m["model_seo_name"].lower(): m for m in models if m.get("model_seo_name")}
        with self._list_lock:
            self._list_cache = (time.monotonic(), by_name)
        return by_name

    def _status_from_entry(self, username: str, entry: dict) -> ModelStatus:
        model_id = str(entry.get("model_id") or "") or None
        sample = entry.get("sample_long_id")
        return ModelStatus(
            username=username,
            state=room_char_to_state(entry.get("room_status_char")),
            model_id=model_id,
            display_name=entry.get("display") or None,
            thumbnail_url=SCREENCAP_URL.format(model_id=model_id) if model_id else None,
            avatar_url=AVATAR_URL.format(sample_long_id=sample) if sample else None,
        )

    def _room_char(self, model_id: str) -> str | None:
        data = self._get_json(LOGIN_ROOM_URL, params={"a": "login_room", "model_id": model_id})
        try:
            return data["config"]["room"]["status"] or None
        except (KeyError, TypeError):
            return None

    def _check_single(self, username: str, model_id: str | None = None) -> ModelStatus:
        data = self._get_json(STATUS_URL, params={"model_name": username})
        status = (data.get("status") or "").lower()
        if status == "failed":
            msg = (data.get("message") or "").lower()
            if "inactive" in msg:
                # Account exists but is dormant; keep it on the watchlist as offline.
                return ModelStatus(username=username, state="offline", model_id=model_id,
                                   error=data.get("message"))
            return ModelStatus(username=username, state="not_found", error=data.get("message"))
        mid = str(data.get("model_id") or model_id or "") or None
        extra = data.get("DATA") or {}
        display = extra.get("display_name") if isinstance(extra, dict) else None
        if status != "online" or not mid:
            return ModelStatus(username=username, state="offline", model_id=mid, display_name=display)
        # check-model-status lags behind show changes; the room itself is authoritative.
        state = room_char_to_state(self._room_char(mid))
        if state == "offline":
            state = "private"  # online per status API but no room letter: not recordable
        return ModelStatus(
            username=username, state=state, model_id=mid, display_name=display,
            thumbnail_url=SCREENCAP_URL.format(model_id=mid),
        )

    def check_status(self, username: str, model_id: str | None = None) -> ModelStatus:
        try:
            entry = self.online_models().get(username)
        except SiteError as exc:
            logger.debug("Online list unavailable, using per-model check: %s", exc)
            entry = None
        if entry is not None:
            return self._status_from_entry(username, entry)
        return self._check_single(username, model_id)

    def bulk_status(self, usernames: list[str]) -> dict[str, ModelStatus]:
        online = self.online_models(force=True)
        out: dict[str, ModelStatus] = {}
        for name in usernames:
            entry = online.get(name)
            if entry is not None:
                out[name] = self._status_from_entry(name, entry)
                continue
            # Not in the list: almost always offline, but the list can miss
            # categories, so confirm with the cheap per-model endpoint.
            try:
                out[name] = self._check_single(name)
            except SiteError as exc:
                out[name] = ModelStatus(username=name, state="offline", error=str(exc))
            time.sleep(0.3)
        return out

    def is_public(self, model_id: str) -> bool:
        return self._room_char(model_id) == "O"

    # --------------------------------------------------------------- stream
    def get_playback_url(self, model_id: str) -> str:
        data = self._get_json(STREAM_URLS_URL, params={"model_id": model_id})
        code = data.get("code")
        if code == 44:
            raise SiteError("Model does not exist")
        if code not in (0, "0"):
            raise SiteError(f"Stream lookup failed (code {code})")
        try:
            url = data["data"]["hls"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SiteError("No HLS stream offered for this room") from exc
        return "https:" + url if url.startswith("//") else url

    def get_stream_url(self, model_id: str, quality: str = "best") -> str:
        master = self.get_playback_url(model_id)
        resp = self._get(master)
        if "#EXTM3U" not in resp.text:
            raise SiteError("Stream playlist is not a valid HLS manifest")
        return pick_variant(master, resp.text, quality)

    # ----------------------------------------------------------------- misc
    def screencap_url(self, model_id: str) -> str:
        return SCREENCAP_URL.format(model_id=model_id)

    def profile_url(self, username: str) -> str:
        return f"{BASE}/?model={username}"

    def ffmpeg_headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Referer": f"{BASE}/"}

    def fetch_bytes(self, url: str) -> bytes | None:
        try:
            resp = self._session().get(url, timeout=20)
        except Exception:
            return None
        if resp.status_code != 200 or not resp.content:
            return None
        if not resp.headers.get("content-type", "").startswith("image/"):
            return None
        return resp.content

    def reachability(self) -> dict:
        try:
            self._get_json(STATUS_URL, params={"model_name": "camsuite-healthcheck"})
            return {"reachable": True, "blocked": False, "error": None}
        except SiteBlockedError as exc:
            return {"reachable": True, "blocked": True, "error": str(exc)}
        except SiteError as exc:
            return {"reachable": False, "blocked": False, "error": str(exc)}
