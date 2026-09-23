"""Tests for background ZIP export jobs."""
import os
import tempfile
import time
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def svc(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("RECORDINGS_DIR", os.path.join(tmp, "rec"))
    import importlib, app.config
    importlib.reload(app.config)
    import app.core.export_service as m
    importlib.reload(m)
    return m


def _make_files(n=3, size=2048):
    d = Path(tempfile.mkdtemp())
    out = []
    for i in range(n):
        p = d / f"file{i}.mp4"
        p.write_bytes(b"x" * size)
        out.append((p, p.name))
    return out


def _wait(job, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline and job.status in ("pending", "running"):
        time.sleep(0.05)
    return job


def test_export_completes_and_contains_every_file(svc):
    files = _make_files(4)
    job = _wait(svc.export_service.create(files, "test.zip"))
    assert job.status == "ready", job.error
    assert job.path and Path(job.path).exists()
    with zipfile.ZipFile(job.path) as zf:
        assert sorted(zf.namelist()) == sorted(n for _, n in files)


def test_progress_reaches_100_and_counts_bytes(svc):
    files = _make_files(3, size=1024)
    job = _wait(svc.export_service.create(files, "t.zip"))
    assert job.as_dict()["percent"] == 100.0
    assert job.bytes_done == 3 * 1024
    assert job.files_done == 3


def test_percent_never_reports_100_before_ready(svc):
    job = svc.ExportJob(id="x", total_files=10, total_bytes=1000, status="running")
    job.bytes_done = 1000
    # A byte count that has reached the total must still not claim completion
    # while the archive is being finalised.
    assert job.as_dict()["percent"] == 99.9


def test_missing_files_are_rejected_not_silently_empty(svc):
    with pytest.raises(ValueError, match="exist"):
        svc.export_service.create([(Path("/nope/missing.mp4"), "missing.mp4")], "t.zip")


def test_unreadable_file_does_not_lose_the_archive(svc):
    files = _make_files(3)
    # Delete one after the size check, simulating a file removed mid-export.
    files[1][0].unlink()
    job = _wait(svc.export_service.create(files, "t.zip"))
    assert job.status == "ready"
    with zipfile.ZipFile(job.path) as zf:
        assert len(zf.namelist()) == 2


def test_discard_removes_the_archive(svc):
    job = _wait(svc.export_service.create(_make_files(2), "t.zip"))
    path = job.path
    assert Path(path).exists()
    svc.export_service.discard(job.id)
    assert not Path(path).exists()
    assert svc.export_service.get(job.id) is None


def test_refuses_export_larger_than_free_disk(svc, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(
        svc.shutil, "disk_usage",
        lambda _p: sh._ntuple_diskusage(total=100, used=100, free=0),
    )
    with pytest.raises(ValueError, match="disk space"):
        svc.export_service.create(_make_files(1), "t.zip")
