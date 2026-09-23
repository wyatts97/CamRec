"""What survives when a recording is deleted.

Live events go with it -- they are only meaningful alongside the stream. Clips
deliberately do NOT: deleting a recording frees the large source file while
keeping the clips cut from it, so their recording_id is nulled instead.

Regression test. Enabling `PRAGMA foreign_keys=ON` (part of the SQLite
concurrency tuning) surfaced that Recording had no `clips` relationship at all:
the delete began failing outright with FOREIGN KEY constraint failed. Before
the pragma it had silently succeeded and left clip rows pointing at a recording
that no longer existed.
"""
from datetime import datetime

import pytest


# The database is configured by tests/conftest.py before any app import, so
# nothing here needs to reload modules -- doing so re-declared the ORM tables
# on an already-populated MetaData.
@pytest.fixture(scope="module")
def db():
    import app.db.database as database
    import app.db.models as models
    database.Base.metadata.create_all(bind=database.engine)
    return database, models


_seed_counter = iter(range(1, 10_000))


def _seed(database, models, n_clips=2, n_events=3):
    with database.get_session() as s:
        # Unique per call: username is a unique column and the fixture's
        # database is shared across the tests in this module.
        user = models.User(username=f"cascade_user_{next(_seed_counter)}")
        s.add(user)
        s.commit()
        rec = models.Recording(
            user_id=user.id, filename="TK_cascade.mp4", status="completed", mode="manual"
        )
        s.add(rec)
        s.commit()
        for i in range(n_clips):
            s.add(models.Clip(
                recording_id=rec.id,
                username=user.username,
                filename=f"clip{i}.mp4",
                start_time=0,
                end_time=10,
            ))
        for i in range(n_events):
            s.add(models.LiveEvent(
                recording_id=rec.id, offset_seconds=float(i),
                event_type="chat", user_nickname="bob", created_at=datetime.utcnow(),
            ))
        s.commit()
        return user.id, rec.id


def test_foreign_keys_are_enforced(db):
    """Guards the pragma itself -- without it this whole class of bug is silent."""
    database, _ = db
    from sqlalchemy import text
    with database.engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_deleting_a_recording_keeps_its_clips_but_detaches_them(db):
    database, models = db
    _, rec_id = _seed(database, models, n_clips=2)

    with database.get_session() as s:
        clip_ids = [c.id for c in s.query(models.Clip).filter_by(recording_id=rec_id)]
        s.delete(s.query(models.Recording).filter_by(id=rec_id).one())
        s.commit()

    with database.get_session() as s:
        assert s.query(models.Recording).filter_by(id=rec_id).count() == 0
        # The clips survive, detached rather than deleted.
        surviving = s.query(models.Clip).filter(models.Clip.id.in_(clip_ids)).all()
        assert len(surviving) == 2
        assert all(c.recording_id is None for c in surviving)
        # ...and still know who they are of, which is only possible because
        # the username is stored on the clip itself.
        assert all(c.username and c.username.startswith("cascade_user") for c in surviving)


def test_deleting_a_recording_removes_its_live_events(db):
    database, models = db
    _, rec_id = _seed(database, models, n_events=3)

    with database.get_session() as s:
        s.delete(s.query(models.Recording).filter_by(id=rec_id).one())
        s.commit()

    with database.get_session() as s:
        assert s.query(models.LiveEvent).filter_by(recording_id=rec_id).count() == 0


def test_deleting_a_user_removes_their_recordings_but_keeps_clips(db):
    database, models = db
    user_id, rec_id = _seed(database, models, n_clips=2)

    with database.get_session() as s:
        clip_ids = [c.id for c in s.query(models.Clip).filter_by(recording_id=rec_id)]
        s.delete(s.query(models.User).filter_by(id=user_id).one())
        s.commit()

    with database.get_session() as s:
        assert s.query(models.Recording).filter_by(id=rec_id).count() == 0
        surviving = s.query(models.Clip).filter(models.Clip.id.in_(clip_ids)).all()
        assert len(surviving) == 2
        assert all(c.recording_id is None for c in surviving)


def test_deleting_a_clip_leaves_its_recording_alone(db):
    database, models = db
    _, rec_id = _seed(database, models)

    with database.get_session() as s:
        clip = s.query(models.Clip).filter_by(recording_id=rec_id).first()
        s.delete(clip)
        s.commit()

    with database.get_session() as s:
        assert s.query(models.Recording).filter_by(id=rec_id).count() == 1
        assert s.query(models.Clip).filter_by(recording_id=rec_id).count() == 1
