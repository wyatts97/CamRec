"""List endpoints must not carry full transcripts.

Regression test: every row of GET /api/recordings included transcript_text,
so a 12-row page of hour-long streams was ~900 KB while the list UIs only read
transcript_status.
"""
import pytest


@pytest.fixture(scope="module")
def db():
    import app.db.database as database
    import app.db.models as models
    database.Base.metadata.create_all(bind=database.engine)
    return database, models


def test_list_omits_transcript_but_detail_keeps_it(db):
    database, models = db
    from app.api.routes.recordings import _build_response, list_recordings

    transcript = "[00:00:01] hello\n" * 5000
    with database.get_session() as s:
        user = models.User(username="payload_user")
        s.add(user)
        s.commit()
        rec = models.Recording(
            user_id=user.id,
            filename="TK_payload.mp4",
            status="completed",
            mode="manual",
            transcript_status="done",
            transcript_text=transcript,
            is_corrupt=False,  # skip the lazy ffprobe backfill
        )
        s.add(rec)
        s.commit()
        rec_id = rec.id

        listed = list_recordings(page=1, page_size=10, db=s)
        row = next(r for r in listed.recordings if r.id == rec_id)
        assert row.transcript_status == "done"
        assert row.transcript_text is None

        detail = _build_response(s.get(models.Recording, rec_id))
        assert detail.transcript_text == transcript
