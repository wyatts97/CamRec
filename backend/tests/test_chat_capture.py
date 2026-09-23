"""Chat capture retry decisions.

Regression tests for the VPS failure where every chat attempt raised
TikTokLive's AuthenticatedWebSocketConnectionError: a configured session ID
made the library refuse to connect, and the listener burned all 10 retries
(~7 minutes) on an error that could never succeed.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from TikTokLive.client.errors import (
    AuthenticatedWebSocketConnectionError,
    UserOfflineError,
)

from app.core import live_chat_service as lcs


def _listener(**kwargs):
    defaults = dict(
        recording_id=1,
        username="someone",
        room_id="123",
        started_at=datetime.utcnow(),
        cookies={"sessionid_ss": "secret", "tt-target-idc": "useast2a"},
    )
    defaults.update(kwargs)
    return lcs.LiveChatListener(**defaults)


def test_classify_auth_block_fatal_and_transient():
    listener = _listener()
    assert listener._classify(AuthenticatedWebSocketConnectionError("blocked"), False) == lcs._AUTH_BLOCKED
    assert listener._classify(UserOfflineError("gone"), False) == lcs._FATAL
    assert listener._classify(RuntimeError("HTTP 400"), False) == lcs._FAILED
    assert listener._classify(RuntimeError("dropped"), True) == lcs._CONNECTED
    assert listener.last_error.startswith("RuntimeError")


def test_session_not_sent_unless_opted_in(monkeypatch):
    monkeypatch.delenv("WHITELIST_AUTHENTICATED_SESSION_ID_HOST", raising=False)
    calls = []
    client = SimpleNamespace(web=SimpleNamespace(set_session=lambda *a: calls.append(a)))

    assert _listener(authenticated=False)._apply_session_cookies(client) is False
    assert calls == []

    assert _listener(authenticated=True)._apply_session_cookies(client) is True
    assert calls == [("secret", "useast2a")]
    import os
    assert os.environ["WHITELIST_AUTHENTICATED_SESSION_ID_HOST"] == lcs._sign_server_host()


def test_auth_block_falls_back_to_anonymous_without_counting_a_failure(monkeypatch):
    listener = _listener(authenticated=True)
    outcomes = iter([lcs._AUTH_BLOCKED, lcs._FATAL])
    seen_auth = []

    async def fake_connect(attempt):
        seen_auth.append(listener._use_auth)
        return next(outcomes)

    async def no_sleep(seconds):
        raise AssertionError("an auth block must retry immediately, not back off")

    monkeypatch.setattr(listener, "_connect_once", fake_connect)
    monkeypatch.setattr(listener, "_sleep_unless_stopped", no_sleep)
    asyncio.run(listener._run_async())

    # First attempt authenticated, second anonymous; the fatal outcome ends
    # the loop without another retry.
    assert seen_auth == [True, False]


def test_service_restarts_a_dead_listener(monkeypatch):
    service = lcs.LiveChatService()
    started = []

    class FakeListener:
        def __init__(self, **kwargs):
            self.alive = True
            started.append(self)

        def start(self):
            pass

        def is_running(self):
            return self.alive

    monkeypatch.setattr(lcs, "LiveChatListener", FakeListener)
    args = dict(recording_id=7, username="u", room_id="1", started_at=datetime.utcnow(), authenticated=False)

    assert service.start_listening(**args) is True
    assert service.start_listening(**args) is False, "a running listener must not be duplicated"

    started[0].alive = False
    assert service.start_listening(**args) is True, "a listener that gave up must not block a restart"
    assert len(started) == 2
