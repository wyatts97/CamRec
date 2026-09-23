"""Sprite sheet / VTT generation for hover-scrub previews.

Regression tests: frames used to be written to the VTT by position
(`start = i * interval`), so one failed frame grab shifted every later preview
onto the wrong time. The player looks thumbnails up by time and showed the
wrong frame, while the cards (which stepped by index) looked fine.
"""
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import media_utils as mu

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed"
)

CUE = re.compile(r"(\d\d):(\d\d):(\d\d\.\d{3}) --> (\d\d):(\d\d):(\d\d\.\d{3})\n(.+)")


def _seconds(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_cues(vtt: str):
    return [
        (_seconds(*m.group(1, 2, 3)), _seconds(*m.group(4, 5, 6)), m.group(7))
        for m in CUE.finditer(vtt)
    ]


def test_interval_is_clamped():
    assert mu.sprite_interval(30) == 2.0          # short clip: dense
    assert mu.sprite_interval(4588) == pytest.approx(4588 / 300)  # 76 min: ~15 s
    assert mu.sprite_interval(100_000) == 30.0    # very long: capped


def test_vtt_cues_are_contiguous_and_keep_real_times():
    # Frame at 20 s is missing: the 10 s cue must stretch to 30 s rather than
    # the 30 s frame being relabelled as 20 s.
    vtt = mu.build_sprite_vtt([0.0, 10.0, 30.0], duration=41.5)
    assert "NOTE tikrec-sprite v2" in vtt
    cues = parse_cues(vtt)
    assert [(s, e) for s, e, _ in cues] == [(0.0, 10.0), (10.0, 30.0), (30.0, 41.5)]
    assert cues[2][2] == "sprite#xywh=320,0,160,90"


def test_version_detection(tmp_path):
    old = tmp_path / "old.vtt"
    old.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:10.000\nsprite#xywh=0,0,160,90\n")
    new = tmp_path / "new.vtt"
    new.write_text(mu.build_sprite_vtt([0.0], 5))
    assert mu.sprite_vtt_version(old) == 1
    assert mu.sprite_vtt_version(new) == mu.SPRITE_VERSION
    assert mu.sprite_vtt_version(tmp_path / "missing.vtt") == 0


@needs_ffmpeg
def test_failed_grab_does_not_shift_later_frames(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=21",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "20", str(video)],
        check=True,
    )

    real_grab = mu._grab_sprite_frame
    attempted = []

    def flaky_grab(path, timestamp, out_path):
        attempted.append(timestamp)
        if timestamp == 6.0:  # simulate a seek that fails mid-file
            return False
        return real_grab(path, timestamp, out_path)

    monkeypatch.setattr(mu, "_grab_sprite_frame", flaky_grab)
    sprite, vtt = mu.generate_sprite(video)
    assert sprite and vtt and sprite.exists()

    cues = parse_cues(vtt.read_text())
    starts = [s for s, _, _ in cues]
    expected = [t for t in sorted(attempted) if t != 6.0]
    assert starts == expected, "cue start times must be the real capture times"
    # Contiguous, starting at 0 and ending at the video's duration.
    assert starts[0] == 0.0
    for (_, end, _), (next_start, _, _) in zip(cues, cues[1:]):
        assert end == next_start
    assert cues[-1][1] == pytest.approx(21.0, abs=0.1)
    # 2 s interval on a 21 s clip.
    assert attempted[:3] == [0.0, 2.0, 4.0]


def test_render_adds_version_and_etag(tmp_path):
    video = tmp_path / "rec.mp4"
    sprite, vtt = mu.sprite_paths(video)
    sprite.write_bytes(b"\xff\xd8jpeg")
    vtt.write_text(mu.build_sprite_vtt([0.0, 2.0], 4))

    content, etag = mu.render_sprite_vtt(video, "/api/recordings/7/sprite")
    assert re.search(r"/api/recordings/7/sprite\?v=\d+#xywh=0,0,160,90", content)
    assert etag.startswith('"') and etag.endswith('"')
    assert mu.render_sprite_vtt(tmp_path / "none.mp4", "/x") is None


def test_vtt_route_revalidates_and_upgrades_old_maps(tmp_path, monkeypatch):
    import app.db.database as database
    import app.db.models as models
    from app.api.routes import recordings as routes

    database.Base.metadata.create_all(bind=database.engine)
    with database.get_session() as s:
        user = models.User(username="sprite_route_user")
        s.add(user)
        s.commit()
        rec = models.Recording(user_id=user.id, filename="TK_sprite_route.mp4", status="completed", mode="manual")
        s.add(rec)
        s.commit()
        rec_id = rec.id

    video = tmp_path / "TK_sprite_route.mp4"
    video.write_bytes(b"video")
    sprite, vtt = mu.sprite_paths(video)
    sprite.write_bytes(b"\xff\xd8jpeg")
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:10.000\nsprite#xywh=0,0,160,90\n")  # v1

    monkeypatch.setattr(routes, "recording_path", lambda name: video)
    queued = []
    monkeypatch.setattr(routes, "run_background", lambda fn, *a: queued.append((fn, a)))
    routes._sprite_retry_at.clear()

    request = SimpleNamespace(headers={})
    with database.get_session() as s:
        resp = routes.get_sprite_vtt(rec_id, request, s)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"
    assert "?v=" in resp.body.decode()
    assert queued and queued[0][0] is routes.generate_sprite, "old-format map must be rebuilt"

    etag = resp.headers["etag"]
    with database.get_session() as s:
        cached = routes.get_sprite_vtt(rec_id, SimpleNamespace(headers={"if-none-match": etag}), s)
    assert cached.status_code == 304
    assert len(queued) == 1, "rebuild is throttled"
