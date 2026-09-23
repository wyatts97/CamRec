"""URL-expiry resumes must not accumulate backoff.

Regression test: TikTok stream URLs expire about every 30 minutes, so a long
live produces many segments that each end cleanly. The resume counter never
reset, so each expiry waited longer (3s, 5s, 10s, 15s, then 30s), and that
wait was missing from the recording.
"""
import pytest


@pytest.fixture(scope="module")
def db():
    import app.db.database as database
    import app.db.models as models
    database.Base.metadata.create_all(bind=database.engine)
    return database, models


def test_healthy_segments_resume_without_backoff(db, monkeypatch):
    database, models = db
    from app.core import task_manager as tm

    with database.get_session() as s:
        user = models.User(username="resume_user")
        s.add(user)
        s.commit()
        rec = models.Recording(user_id=user.id, filename="TK_resume.mp4", status="pending", mode="automatic")
        s.add(rec)
        s.commit()
        rec_id = rec.id

    class FakeApi:
        def __init__(self, **kwargs):
            pass

        def is_room_alive(self, room_id):
            return True

        def get_live_url(self, room_id, user=None):
            return "http://example.invalid/stream.flv"

    class FakeProc:
        """ffmpeg that writes some bytes and exits, like an expired URL."""
        stdin = None

        def __init__(self, cmd, **kwargs):
            with open(cmd[-1], "wb") as fh:
                fh.write(b"\x47" * 188)

        def poll(self):
            return 0

    segments_to_capture = 4
    resolved = {"n": 0}

    def fake_resolve(room_id, api, username=None):
        resolved["n"] += 1
        return "http://example.invalid/fresh.flv" if resolved["n"] < segments_to_capture else None

    sleeps = []
    monkeypatch.setattr(tm, "get_tiktok_api_class", lambda: FakeApi)
    monkeypatch.setattr(tm.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(tm, "_resolve_fresh_live_url", fake_resolve)
    monkeypatch.setattr(tm, "_check_live_with_backoff", lambda *a, **k: (False, None))
    monkeypatch.setattr(tm, "_HEALTHY_SEGMENT_SECONDS", 0)
    monkeypatch.setattr(tm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(tm.live_chat_service, "start_listening", lambda **k: True)
    monkeypatch.setattr(tm.live_chat_service, "is_listening", lambda rid: True)
    monkeypatch.setattr(tm.RecordingTask, "_finalize_recording", lambda self: None)

    task = tm.RecordingTask(recording_id=rec_id, username="resume_user", room_id="1")
    task._run()

    assert len(task._segments) == segments_to_capture
    # Only the final, genuine end of stream falls through to the backoff path.
    assert sleeps == [tm._RESUME_BACKOFF_SECONDS[0]], sleeps
