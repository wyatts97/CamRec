"""Out-of-process transcription.

Whisper used to run inside the API process, which kept the model, its runtimes
and the peak audio buffers resident forever (~1.3 GB idle after a single
transcription). These tests cover the pieces that replaced it: windowed audio
streaming in the worker, and the service's handling of the worker process.
"""
import io
import json
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from app.core import transcribe_worker as tw


def _pcm(samples: np.ndarray) -> io.BytesIO:
    return io.BytesIO(samples.astype(np.int16).tobytes())


def test_quiet_cut_lands_in_the_silent_second():
    sr = 100  # small "sample rate" keeps the arrays tiny
    loud = np.full(sr * 30, 10_000, dtype=np.int16)
    loud[sr * 17 : sr * 18] = 0  # one silent second, 3 s after the target
    cut = tw.find_quiet_cut(loud, target=sr * 20, search=sr * 5, frame=sr)
    assert sr * 17 <= cut < sr * 18


def test_windows_cover_the_stream_exactly_once():
    sr = 100
    audio = (np.random.default_rng(0).standard_normal(sr * 95) * 5000).astype(np.int16)
    windows = list(tw.iter_windows(_pcm(audio), window_samples=sr * 20, snap_samples=sr * 3))

    assert len(windows) >= 4
    # Offsets are contiguous and the concatenation reproduces the input.
    expected_offset = 0
    for offset, window in windows:
        assert offset == expected_offset
        expected_offset += len(window)
    assert np.array_equal(np.concatenate([w for _, w in windows]), audio)
    # No window strays further from its nominal size than the snap margin.
    for _, window in windows[:-1]:
        assert abs(len(window) - sr * 20) <= sr * 3


def test_segment_timestamps_are_shifted_by_window_offset(monkeypatch):
    sr = tw.SAMPLE_RATE
    windows = [(0, np.zeros(sr, np.int16)), (sr * 600, np.zeros(sr, np.int16))]

    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **kwargs):
            seg = SimpleNamespace(start=1.0, end=2.5, text=" hi ")
            return iter([seg]), SimpleNamespace(language="en", language_probability=0.9)

    class FakeFFmpeg:
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        def __init__(self, *a, **k):
            pass

        def wait(self):
            return 0

    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(tw.subprocess, "Popen", FakeFFmpeg)
    monkeypatch.setattr(tw, "iter_windows", lambda stream: iter(windows))

    result = tw.transcribe("video.mp4", "cache")
    assert result["lines"] == [
        "[00:00:01 --> 00:00:02] hi",
        "[00:10:01 --> 00:10:02] hi",
    ]
    assert result["language"] == "en"


# --- Service side -----------------------------------------------------------

@pytest.fixture
def run_worker(monkeypatch, tmp_path):
    from app.core import transcription_service as ts
    monkeypatch.setattr(ts, "_WHISPER_CACHE_DIR", tmp_path / "cache")

    def configure(returncode=0, stdout=b"", stderr=b"", timeout=False):
        class FakeProc:
            pid = 1234

            def __init__(self, *a, **k):
                self.returncode = None
                self.killed = False

            def communicate(self, timeout=None):
                if timeout_flag["armed"]:
                    timeout_flag["armed"] = False
                    raise subprocess.TimeoutExpired("worker", timeout)
                self.returncode = returncode
                return stdout, stderr

            def kill(self):
                self.killed = True

            def poll(self):
                return self.returncode

        timeout_flag = {"armed": timeout}
        monkeypatch.setattr(ts.subprocess, "Popen", FakeProc)
        return ts

    return configure


def test_worker_success_returns_lines(run_worker, tmp_path):
    ts = run_worker(stdout=json.dumps({"lines": ["[00:00:00 --> 00:00:01] a"], "language": "en"}).encode())
    result = ts._run_worker(tmp_path / "v.mp4", 60)
    assert result["lines"] == ["[00:00:00 --> 00:00:01] a"]


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(returncode=1, stderr=b"Traceback: boom"),
        dict(stdout=b"not json"),
        dict(stdout=b'{"language": "en"}'),
        dict(timeout=True),
    ],
    ids=["nonzero-exit", "bad-json", "missing-lines", "timeout"],
)
def test_worker_failures_raise(run_worker, tmp_path, kwargs):
    ts = run_worker(**kwargs)
    with pytest.raises(ts.TranscriptionFailed):
        ts._run_worker(tmp_path / "v.mp4", 60)


def test_failed_worker_marks_recording_failed(monkeypatch):
    import app.db.database as database
    import app.db.models as models
    from app.core import transcription_service as ts

    database.Base.metadata.create_all(bind=database.engine)
    with database.get_session() as s:
        user = models.User(username="transcribe_fail_user")
        s.add(user)
        s.commit()
        rec = models.Recording(user_id=user.id, filename="TK_tx.mp4", status="completed", mode="manual")
        s.add(rec)
        s.commit()
        rec_id = rec.id

    monkeypatch.setattr(ts, "recording_path", lambda name: SimpleNamespace(exists=lambda: True, name=name))

    def boom(*a, **k):
        raise ts.TranscriptionFailed("worker exited 1")

    monkeypatch.setattr(ts, "_run_worker", boom)
    service = ts.TranscriptionService.__new__(ts.TranscriptionService)
    service._proc = None
    service._proc_lock = __import__("threading").Lock()
    service._shutting_down = False
    service._run(rec_id)

    with database.get_session() as s:
        assert s.get(models.Recording, rec_id).transcript_status == "failed"
