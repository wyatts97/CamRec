"""Post-recording AV1 compression.

Uses a real ffmpeg encode of a short synthetic clip, so these are skipped when
the local ffmpeg has no libsvtav1.
"""
import subprocess

import pytest

from app.core import compression_service as cs


pytestmark = pytest.mark.skipif(not cs.encoder_available(), reason="ffmpeg without libsvtav1/libopus")


@pytest.fixture(scope="module")
def db():
    import app.db.database as database
    import app.db.models as models
    database.Base.metadata.create_all(bind=database.engine)
    return database, models


_n = iter(range(1, 10_000))


def _make_recording(db, seconds=4, status="completed"):
    """A real H.264/AAC MP4 on disk plus its Recording row."""
    database, models = db
    from app.core.media_utils import recording_path

    n = next(_n)
    filename = f"F4F_compress_{n}.mp4"
    path = recording_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         # Bloated on purpose so AV1 has something to save, like a live capture.
         "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "4M", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    with database.get_session() as s:
        user = models.User(site="flirt4free", username=f"compress-user-{n}")
        s.add(user)
        s.commit()
        rec = models.Recording(user_id=user.id, filename=filename, status=status, mode="manual",
                               file_size=path.stat().st_size)
        s.add(rec)
        s.commit()
        return rec.id, path


def _row(db, rid):
    database, models = db
    with database.get_session() as s:
        r = s.query(models.Recording).filter_by(id=rid).one()
        return r.compress_status, r.file_size, r.original_size, r.compress_error


def test_compresses_and_replaces_original(db):
    rid, path = _make_recording(db)
    before = path.stat().st_size

    assert cs.CompressionService().process(rid) == "done"

    status, size, original, err = _row(db, rid)
    assert status == "done" and err is None
    assert original == before
    assert size == path.stat().st_size < before
    assert cs._video_codec(path) == "av1"
    assert not path.with_suffix(".av1.tmp.mp4").exists()


def test_already_av1_is_left_alone(db):
    rid, path = _make_recording(db)
    svc = cs.CompressionService()
    svc.process(rid)
    size_after_first = path.stat().st_size
    assert svc.process(rid) == "done"
    assert path.stat().st_size == size_after_first


def test_failed_verification_keeps_original(db, monkeypatch):
    rid, path = _make_recording(db)
    original_bytes = path.read_bytes()
    monkeypatch.setattr(cs.CompressionService, "_verify", staticmethod(lambda p, d: "duration mismatch"))

    assert cs.CompressionService().process(rid) == "failed"

    status, _, original, err = _row(db, rid)
    assert status == "failed" and "duration mismatch" in err
    assert original is None
    assert path.read_bytes() == original_bytes
    assert not path.with_suffix(".av1.tmp.mp4").exists()


def test_result_not_smaller_is_skipped(db, monkeypatch):
    rid, path = _make_recording(db)
    original_bytes = path.read_bytes()
    monkeypatch.setattr(cs, "MIN_SAVING", 0.9999)

    assert cs.CompressionService().process(rid) == "skipped"
    assert _row(db, rid)[0] == "skipped"
    assert path.read_bytes() == original_bytes


def test_unfinished_recording_is_not_touched(db):
    rid, path = _make_recording(db, status="failed")
    original_bytes = path.read_bytes()
    assert cs.CompressionService().process(rid) == "not_finished"
    assert path.read_bytes() == original_bytes


def test_encode_command_caps_threads_and_uses_quality_crf():
    cmd = cs.build_encode_cmd(cs.Path("in.mp4"), cs.Path("out.mp4"), cs.QUALITY_CRF["balanced"], 6)
    assert "libsvtav1" in cmd and "libopus" in cmd
    assert cmd[cmd.index("-crf") + 1] == "30"
    assert cmd[cmd.index("-svtav1-params") + 1] == "lp=6"
