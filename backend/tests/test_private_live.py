"""A private live is reported once per room, not on every monitor cycle."""
from types import SimpleNamespace


def test_private_live_notifies_once_per_room(monkeypatch):
    from app.core import task_manager as tm_module

    published = []
    monkeypatch.setattr(
        tm_module.notification_service, "publish", lambda **kw: published.append(kw)
    )
    monitor = tm_module.MonitorService.__new__(tm_module.MonitorService)
    monitor._private_rooms = {}
    user = SimpleNamespace(id=5, username="lermaguy")

    monitor._mark_private_live(user, "room-a")
    monitor._mark_private_live(user, "room-a")
    assert len(published) == 1
    assert published[0]["type"] == "private_live"
    assert monitor._private_rooms[5][0] == "room-a"

    # A new broadcast (different room) is worth telling the user about again.
    monitor._mark_private_live(user, "room-b")
    assert len(published) == 2
