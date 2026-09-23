"""Tests for outbound notification delivery filtering."""
import os
import tempfile

import pytest


@pytest.fixture
def sinks(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("RECORDINGS_DIR", os.path.join(tmp, "rec"))
    import importlib
    import app.config
    importlib.reload(app.config)
    import app.core.settings_store as store
    importlib.reload(store)
    import app.core.notification_sinks as m
    importlib.reload(m)
    return m


def _configure(sinks, **overrides):
    cfg = sinks.default_config()
    cfg.update(overrides)
    from app.core.settings_store import settings_store
    settings_store.set("notification_sinks", cfg)


def test_nothing_is_sent_when_disabled(sinks):
    sent = []
    sinks._SENDERS["discord"] = lambda c, n: sent.append(n)
    _configure(sinks, enabled=False, discord={"enabled": True, "webhook_url": "http://x"})
    sinks.notification_sinks.enqueue({"type": "user_live", "title": "t"})
    assert sent == []


def test_events_outside_the_filter_are_dropped(sinks):
    sent = []
    sinks._SENDERS["discord"] = lambda c, n: sent.append(n)
    _configure(sinks, enabled=True, events=["user_live"],
               discord={"enabled": True, "webhook_url": "http://x"})
    sinks.notification_sinks.enqueue({"type": "clip_ready", "title": "t"})
    assert sent == [], "clip_ready is not in the configured event list"


def test_nothing_is_sent_when_no_sink_is_enabled(sinks):
    sent = []
    sinks._SENDERS["discord"] = lambda c, n: sent.append(n)
    _configure(sinks, enabled=True, events=["user_live"],
               discord={"enabled": False, "webhook_url": "http://x"})
    sinks.notification_sinks.enqueue({"type": "user_live", "title": "t"})
    assert sent == []


def test_matching_event_is_delivered(sinks):
    import threading
    got = threading.Event()
    sinks._SENDERS["discord"] = lambda c, n: got.set()
    _configure(sinks, enabled=True, events=["user_live"],
               discord={"enabled": True, "webhook_url": "http://x"})
    sinks.notification_sinks.enqueue({"type": "user_live", "title": "t"})
    assert got.wait(5), "a matching event should reach the sender"


def test_a_failing_sink_does_not_raise_into_the_caller(sinks):
    def boom(c, n):
        raise RuntimeError("webhook down")
    sinks._SENDERS["discord"] = boom
    _configure(sinks, enabled=True, events=["user_live"],
               discord={"enabled": True, "webhook_url": "http://x"})
    # enqueue must never propagate: it is called from recording threads.
    sinks.notification_sinks.enqueue({"type": "user_live", "title": "t"})


def test_default_events_are_all_real_event_types(sinks):
    assert set(sinks.DEFAULT_EVENTS) <= set(sinks.ALL_EVENTS)


def test_send_test_reports_config_errors(sinks):
    _configure(sinks, telegram={"enabled": True, "bot_token": "", "chat_id": ""})
    ok, msg = sinks.notification_sinks.send_test("telegram")
    assert ok is False and "required" in msg


def test_send_test_rejects_unknown_sink(sinks):
    ok, msg = sinks.notification_sinks.send_test("carrier-pigeon")
    assert ok is False and "Unknown sink" in msg
