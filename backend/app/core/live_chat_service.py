from __future__ import annotations

import functools
import logging
import os
import threading
import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

import httpx

from app.db.database import get_session
from app.db.models import LiveEvent

if TYPE_CHECKING:
    from TikTokLive import TikTokLiveClient

logger = logging.getLogger("tikrec.live_chat")

# Outcomes of a single connection attempt.
_CONNECTED = "connected"      # socket came up (and later dropped)
_FAILED = "failed"            # transient refusal; worth retrying with backoff
_AUTH_BLOCKED = "auth_blocked"  # library refused to send the session ID
_FATAL = "fatal"              # retrying cannot help (room gone, user missing)


@functools.cache
def _ttl() -> SimpleNamespace:
    """Import TikTokLive on first use.

    Its generated protobuf models add ~30 MB of resident memory, which an idle
    backend with nothing recording has no use for.
    """
    from TikTokLive import TikTokLiveClient
    from TikTokLive.client.errors import (
        AuthenticatedWebSocketConnectionError,
        UserNotFoundError,
        UserOfflineError,
    )
    from TikTokLive.client.web.web_settings import WebDefaults
    from TikTokLive.events import CommentEvent, ConnectEvent, GiftEvent

    return SimpleNamespace(
        TikTokLiveClient=TikTokLiveClient,
        AuthenticatedWebSocketConnectionError=AuthenticatedWebSocketConnectionError,
        # Errors that no amount of retrying will fix for this room.
        FATAL_ERRORS=(UserNotFoundError, UserOfflineError),
        WebDefaults=WebDefaults,
        CommentEvent=CommentEvent,
        ConnectEvent=ConnectEvent,
        GiftEvent=GiftEvent,
    )


def _sign_server_host() -> str:
    """Host of the sign server this TikTokLive release talks to.

    TikTokLive only accepts a session ID when WHITELIST_AUTHENTICATED_SESSION_ID_HOST
    equals this host exactly, and the host has changed between releases
    (api.eulerstream.com -> tiktok.eulerstream.com), so it is read from the
    library rather than hardcoded.
    """
    return _ttl().WebDefaults.tiktok_sign_url.split("://", 1)[-1]


class LiveChatListener:
    """Per-recording WebSocket listener for TikTok live chat/gift events.

    Runs in a dedicated daemon thread with its own asyncio event loop.
    Fire-and-forget: failure does not affect the recording.

    TikTok's webcast edge rejects the WebSocket handshake intermittently
    (Cloudflare answers the upgrade with HTTP 400), especially for anonymous
    connections from datacenter IPs.  A single attempt therefore loses chat
    for a whole session at random, so the listener keeps reconnecting with
    exponential backoff for as long as the recording is running.
    """

    # Reconnect backoff, in seconds.
    INITIAL_BACKOFF = 5
    MAX_BACKOFF = 60
    # Give up after this many consecutive failures with no successful
    # connection in between, so an ended room stops hammering the sign server.
    MAX_CONSECUTIVE_FAILURES = 10
    # How long to wait for a connection task to wind down after a disconnect
    # before cancelling it, so a stuck socket cannot wedge the listener thread.
    SHUTDOWN_TIMEOUT = 10

    def __init__(
        self,
        recording_id: int,
        username: str,
        room_id: str,
        started_at: datetime,
        proxy: Optional[str] = None,
        cookies: Optional[dict] = None,
        authenticated: bool = False,
    ):
        self.recording_id = recording_id
        self.username = username
        self.room_id = room_id
        self.started_at = started_at
        self.proxy = proxy
        self.cookies = cookies
        # Whether to send the TikTok session ID to the sign server. Flipped to
        # False for the rest of the session if the library refuses it.
        self._use_auth = authenticated
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Live state for the UI: whether the socket is up right now, and why
        # the last attempt failed.
        self.connected = False
        self.last_error: Optional[str] = None
        # Capture tallies, reported when the listener exits so that "no chat
        # events because the room was quiet" can be told apart from "never
        # connected".
        self._connect_count = 0
        self._chat_count = 0
        self._gift_count = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as exc:
            logger.warning(
                "LiveChatListener for recording %d ended: %s",
                self.recording_id,
                exc,
                exc_info=True,
            )
        finally:
            loop.close()

    def _make_proxy_objects(self) -> tuple:
        """Convert proxy string to httpx.Proxy objects for web and WS."""
        if not self.proxy:
            return None, None
        try:
            proxy_obj = httpx.Proxy(url=self.proxy)
            return proxy_obj, proxy_obj
        except Exception as exc:
            logger.warning(
                "Invalid proxy '%s' for chat listener: %s", self.proxy, exc
            )
            return None, None

    def _apply_session_cookies(self, client: TikTokLiveClient) -> bool:
        """Authenticate the webcast client with the configured TikTok session.

        Opt-in only (the ``chat_authenticated`` setting): it sends the session
        ID to the Euler Stream sign server, which TikTokLive refuses to do
        unless that host is whitelisted. Signed-in handshakes are refused less
        often from datacenter IPs. Returns True if a session was set.
        """
        if not self._use_auth or not self.cookies:
            return False
        session_id = self.cookies.get("sessionid_ss") or self.cookies.get("sessionid")
        if not session_id:
            return False
        tt_target_idc = (
            self.cookies.get("tt-target-idc")
            or self.cookies.get("tt_target_idc")
            or None
        )
        if not tt_target_idc:
            # TikTokLive raises ValueError on a session ID without a target IDC.
            return False
        os.environ["WHITELIST_AUTHENTICATED_SESSION_ID_HOST"] = _sign_server_host()
        try:
            client.web.set_session(session_id, tt_target_idc)
            return True
        except Exception as exc:
            logger.warning(
                "Could not apply session cookies to chat client for recording %d: %s",
                self.recording_id,
                exc,
            )
            return False

    async def _sleep_unless_stopped(self, seconds: float):
        """Sleep in 1 s slices so a stop request is acted on promptly."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while not self._stop_event.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(1.0, remaining))

    async def _run_async(self):
        backoff = self.INITIAL_BACKOFF
        consecutive_failures = 0
        attempt = 0

        try:
            while not self._stop_event.is_set():
                attempt += 1
                outcome = await self._connect_once(attempt)

                if self._stop_event.is_set():
                    break

                if outcome == _AUTH_BLOCKED:
                    # Deterministic: the library will refuse the session ID on
                    # every attempt. Drop to anonymous and retry immediately,
                    # without counting it as a failure.
                    logger.warning(
                        "Authenticated chat was blocked by TikTokLive for recording %d; "
                        "continuing anonymously",
                        self.recording_id,
                    )
                    self._use_auth = False
                    continue

                if outcome == _FATAL:
                    logger.warning(
                        "Chat capture for recording %d stopped: %s",
                        self.recording_id,
                        self.last_error,
                    )
                    break

                if outcome == _CONNECTED:
                    # A working session dropped mid-stream: reset the backoff
                    # so we get back onto the socket promptly.
                    consecutive_failures = 0
                    backoff = self.INITIAL_BACKOFF
                    logger.info(
                        "Chat capture for recording %d dropped after connecting; "
                        "reconnecting in %ds",
                        self.recording_id,
                        backoff,
                    )
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "Giving up on chat capture for recording %d after %d "
                            "consecutive failed connection attempts",
                            self.recording_id,
                            consecutive_failures,
                        )
                        break
                    logger.warning(
                        "Chat capture attempt %d for recording %d did not connect; "
                        "retrying in %ds (failure %d/%d)",
                        attempt,
                        self.recording_id,
                        backoff,
                        consecutive_failures,
                        self.MAX_CONSECUTIVE_FAILURES,
                    )

                await self._sleep_unless_stopped(backoff)
                backoff = min(backoff * 2, self.MAX_BACKOFF)
        finally:
            if self._connect_count == 0:
                logger.error(
                    "Chat capture for recording %d (@%s) NEVER connected after %d "
                    "attempt(s) - this recording has no chat or gift events",
                    self.recording_id,
                    self.username,
                    attempt,
                )
            else:
                logger.info(
                    "Chat capture for recording %d finished: %d chat + %d gift "
                    "events over %d connection(s)",
                    self.recording_id,
                    self._chat_count,
                    self._gift_count,
                    self._connect_count,
                )

    def _classify(self, exc: BaseException, connected: bool) -> str:
        """Map a connection failure to a retry decision, recording why."""
        self.last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}".strip()
        ttl = _ttl()
        if isinstance(exc, ttl.AuthenticatedWebSocketConnectionError):
            return _AUTH_BLOCKED
        if isinstance(exc, ttl.FATAL_ERRORS):
            return _FATAL
        return _CONNECTED if connected else _FAILED

    async def _connect_once(self, attempt: int) -> str:
        """Run one connection attempt to exhaustion.

        Returns one of the ``_CONNECTED`` / ``_FAILED`` / ``_AUTH_BLOCKED`` /
        ``_FATAL`` outcomes, so the caller can tell a dropped session apart
        from a refused handshake, and a retryable refusal from one that will
        fail identically every time.
        """
        ttl = _ttl()
        web_proxy, ws_proxy = self._make_proxy_objects()
        client = ttl.TikTokLiveClient(
            unique_id=f"@{self.username}",
            web_proxy=web_proxy,
            ws_proxy=ws_proxy,
        )
        authed = self._apply_session_cookies(client)

        connected = False

        # --- Event handlers ---

        @client.on(ttl.ConnectEvent)
        async def on_connect(event):
            nonlocal connected
            connected = True
            self.connected = True
            self.last_error = None
            self._connect_count += 1
            logger.info(
                "Chat capture connected for @%s (recording %d, room=%s, "
                "attempt %d, authenticated=%s)",
                self.username,
                self.recording_id,
                client.room_id,
                attempt,
                authed,
            )

        @client.on(ttl.CommentEvent)
        async def on_comment(event):
            if self._stop_event.is_set():
                await client.disconnect()
                return
            offset = (datetime.utcnow() - self.started_at).total_seconds()
            try:
                with get_session() as db:
                    db.add(
                        LiveEvent(
                            recording_id=self.recording_id,
                            offset_seconds=offset,
                            event_type="chat",
                            user_nickname=event.user.nickname,
                            user_unique_id=event.user.unique_id,
                            content=event.comment,
                        )
                    )
                    db.commit()
                self._chat_count += 1
                logger.debug(
                    "Chat event saved for recording %d: @%s: %s",
                    self.recording_id,
                    event.user.nickname,
                    event.comment[:60] if event.comment else "",
                )
            except Exception as e:
                logger.warning("Failed to save chat event: %s", e)

        @client.on(ttl.GiftEvent)
        async def on_gift(event):
            if self._stop_event.is_set():
                await client.disconnect()
                return
            # Skip intermediate streak ticks — only save when the streak is complete
            # (or for non-streakable gifts which are always final).
            if event.gift.streakable and event.streaking:
                return
            offset = (datetime.utcnow() - self.started_at).total_seconds()
            repeat_count = event.repeat_count
            diamond_count = getattr(event.gift, 'diamond_count', None)
            try:
                with get_session() as db:
                    db.add(
                        LiveEvent(
                            recording_id=self.recording_id,
                            offset_seconds=offset,
                            event_type="gift",
                            user_nickname=event.user.nickname,
                            user_unique_id=event.user.unique_id,
                            gift_name=event.gift.name,
                            gift_diamond_count=diamond_count,
                            gift_repeat_count=repeat_count,
                        )
                    )
                    db.commit()
                self._gift_count += 1
                logger.debug(
                    "Gift event saved for recording %d: @%s sent %s x%d",
                    self.recording_id,
                    event.user.nickname,
                    event.gift.name,
                    repeat_count,
                )
            except Exception as e:
                logger.warning("Failed to save gift event: %s", e)

        # --- Connect and poll ---

        connection_task = None
        try:
            # Start non-blocking so we can poll the stop event.
            # Pass room_id directly to skip HTML scraping (often blocked on servers).
            # fetch_live_check=False because Phase 2 already confirmed the stream is live.
            # fetch_gift_info=True enables gift name/metadata resolution.
            connection_task = await client.start(
                room_id=int(self.room_id),
                fetch_live_check=False,
                fetch_gift_info=True,
            )
        except Exception as exc:
            outcome = self._classify(exc, connected)
            self._log_failure(exc, outcome, attempt, "failed to start")
            await self._shutdown_client(client)
            return outcome

        try:
            # Poll until recording stops or the connection drops
            while not self._stop_event.is_set() and not connection_task.done():
                await asyncio.sleep(1)

            # If we were asked to stop, disconnect cleanly
            if self._stop_event.is_set() and client.connected:
                logger.info(
                    "Stopping chat capture for recording %d",
                    self.recording_id,
                )
                await client.disconnect()

            # Let the connection task finish cleanly, but never block the
            # listener thread forever if the socket refuses to wind down.
            # asyncio.wait() is used rather than awaiting the task directly:
            # it observes the task without re-raising its outcome, so a
            # cancelled connection task cannot kill the retry loop with a
            # CancelledError (which `except Exception` would not catch).
            if not connection_task.done():
                finished, _pending = await asyncio.wait(
                    {connection_task}, timeout=self.SHUTDOWN_TIMEOUT
                )
                if not finished:
                    logger.warning(
                        "Chat capture task for recording %d did not finish within "
                        "%ds; cancelling it",
                        self.recording_id,
                        self.SHUTDOWN_TIMEOUT,
                    )
                    connection_task.cancel()

        except Exception:
            logger.warning(
                "LiveChat client for recording %d error",
                self.recording_id,
                exc_info=True,
            )
        finally:
            self.connected = False
            # The WebSocket handshake runs inside the task returned by start(),
            # so a rejected handshake surfaces ONLY as that task's exception.
            # Without retrieving it here the failure is invisible apart from
            # asyncio's late "Task exception was never retrieved" warning at
            # garbage-collection time.
            outcome = self._task_outcome(connection_task, connected, attempt)
            await self._shutdown_client(client)

        return outcome

    def _task_outcome(self, task, connected: bool, attempt: int) -> str:
        """Classify a finished connection task by the exception it holds."""
        default = _CONNECTED if connected else _FAILED
        if task is None or not task.done():
            return default
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return default
        if exc is None:
            return default
        outcome = self._classify(exc, connected)
        self._log_failure(exc, outcome, attempt, "ended")
        return outcome

    def _log_failure(self, exc: BaseException, outcome: str, attempt: int, what: str):
        # Known, deterministic failures get one line; TikTokLive's auth block
        # message alone is ~20 lines and would otherwise repeat every retry.
        known = outcome in (_AUTH_BLOCKED, _FATAL)
        logger.warning(
            "Chat capture attempt %d for recording %d (@%s) %s: %s",
            attempt,
            self.recording_id,
            self.username,
            what,
            self.last_error,
            exc_info=None if known else exc,
        )

    async def _shutdown_client(self, client: TikTokLiveClient):
        """Tear a client down without letting cleanup errors escape.

        ``disconnect()`` is only meaningful once a socket exists; calling it
        after ``start()`` failed left a half-built coroutine behind ("coroutine
        'TikTokLiveClient.disconnect' was never awaited"). When nothing
        connected, just close the HTTP sessions.
        """
        try:
            if client.connected:
                await asyncio.wait_for(
                    client.disconnect(close_client=True), timeout=self.SHUTDOWN_TIMEOUT
                )
            else:
                await asyncio.wait_for(client.close(), timeout=self.SHUTDOWN_TIMEOUT)
        except Exception:
            logger.debug(
                "Chat client cleanup for recording %d failed",
                self.recording_id,
                exc_info=True,
            )


class LiveChatService:
    """Singleton service managing multiple LiveChatListener instances.

    Each recording gets its own listener thread.  Max 3 concurrent listeners.
    """

    MAX_WORKERS = 3

    def __init__(self):
        self._listeners: dict[int, LiveChatListener] = {}
        self._lock = threading.Lock()

    def start_listening(
        self,
        recording_id: int,
        username: str,
        room_id: str,
        started_at: datetime,
        proxy: Optional[str] = None,
        cookies: Optional[dict] = None,
        authenticated: Optional[bool] = None,
    ) -> bool:
        if authenticated is None:
            from app.core.settings_store import settings_store
            authenticated = bool(settings_store.get("chat_authenticated", False))
        with self._lock:
            existing = self._listeners.get(recording_id)
            if existing is not None:
                if existing.is_running():
                    logger.warning("Already listening for recording %d", recording_id)
                    return False
                # A listener that gave up (or crashed) must not block a
                # restart, e.g. when the recording resumes on a fresh URL.
                del self._listeners[recording_id]
            running = sum(1 for l in self._listeners.values() if l.is_running())
            if running >= self.MAX_WORKERS:
                logger.warning("Max listeners reached (%d)", self.MAX_WORKERS)
                return False

            listener = LiveChatListener(
                recording_id=recording_id,
                username=username,
                room_id=room_id,
                started_at=started_at,
                proxy=proxy,
                cookies=cookies,
                authenticated=authenticated,
            )
            listener.start()
            self._listeners[recording_id] = listener
            logger.info("Started chat capture for recording %d", recording_id)
            return True

    def stop_listening(self, recording_id: int) -> bool:
        with self._lock:
            listener = self._listeners.pop(recording_id, None)
            if listener:
                was_running = listener.is_running()
                listener.stop()
                if was_running:
                    logger.info("Stopped chat capture for recording %d", recording_id)
                else:
                    logger.warning(
                        "Chat capture for recording %d had already died before the "
                        "recording ended",
                        recording_id,
                    )
                return True
            return False

    def is_listening(self, recording_id: int) -> bool:
        with self._lock:
            listener = self._listeners.get(recording_id)
            return listener is not None and listener.is_running()

    def get_status(self, recording_id: int) -> tuple[bool, Optional[str]]:
        """Return ``(connected, last_error)`` for a recording's chat capture.

        ``last_error`` is a short reason when chat is not connected, e.g. the
        listener gave up or was never started.
        """
        with self._lock:
            listener = self._listeners.get(recording_id)
        if listener is None:
            return False, "not running"
        if listener.connected:
            return True, None
        if not listener.is_running():
            return False, listener.last_error or "stopped"
        return False, listener.last_error or "connecting…"

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._listeners)

    def cleanup_finished(self):
        with self._lock:
            finished = [
                rid
                for rid, listener in self._listeners.items()
                if not listener.is_running()
            ]
            for rid in finished:
                del self._listeners[rid]


live_chat_service = LiveChatService()
