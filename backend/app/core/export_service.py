"""Background ZIP export jobs with progress reporting.

The batch-download endpoints used to build the whole archive inside the
request: the browser sat on a dead connection for as long as it took (minutes,
for a library of multi-GB recordings) with no indication anything was
happening, and the temp file was deliberately never cleaned up -- an
unbounded disk-exhaustion path.

Jobs run on their own single-worker pool and report byte-level progress, so
the UI can show a real progress bar. Finished archives are deleted once
downloaded, and swept after a TTL if they never are.
"""
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("tikrec.exports")

# How long a finished archive is kept if nobody downloads it.
_EXPORT_TTL = timedelta(hours=6)
# Refuse to start an export that obviously cannot fit on disk.
_DISK_HEADROOM_BYTES = 512 * 1024 * 1024


@dataclass
class ExportJob:
    id: str
    total_files: int
    total_bytes: int
    status: str = "pending"          # pending | running | ready | failed | cancelled
    files_done: int = 0
    bytes_done: int = 0
    error: str | None = None
    path: str | None = None
    filename: str = "export.zip"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def as_dict(self) -> dict:
        # Progress is byte-weighted: file counts jump misleadingly when sizes
        # differ by orders of magnitude, which they always do here.
        percent = 0.0
        if self.status == "ready":
            percent = 100.0
        elif self.total_bytes:
            percent = min(99.9, round(self.bytes_done / self.total_bytes * 100, 1))
        return {
            "id": self.id,
            "status": self.status,
            "files_done": self.files_done,
            "total_files": self.total_files,
            "bytes_done": self.bytes_done,
            "total_bytes": self.total_bytes,
            "percent": percent,
            "error": self.error,
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
        }


class ExportService:
    def __init__(self) -> None:
        self._jobs: dict[str, ExportJob] = {}
        self._lock = threading.Lock()
        # One at a time: these are disk-bound, and running several in parallel
        # only makes each slower while multiplying peak disk use.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")

    # -- Job lifecycle -------------------------------------------------

    def create(self, files: list[tuple[Path, str]], filename: str) -> ExportJob:
        """Queue an export. `files` is a list of (source path, name in archive)."""
        existing = [(p, arc) for p, arc in files if p.exists()]
        if not existing:
            raise ValueError("None of the selected files exist on disk")

        total_bytes = sum(p.stat().st_size for p, _ in existing)

        free = shutil.disk_usage(tempfile.gettempdir()).free
        if total_bytes + _DISK_HEADROOM_BYTES > free:
            raise ValueError(
                f"Not enough free disk space for this export "
                f"({total_bytes / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free)"
            )

        job = ExportJob(
            id=uuid.uuid4().hex,
            total_files=len(existing),
            total_bytes=total_bytes,
            filename=filename,
        )
        with self._lock:
            self._sweep_locked()
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, existing)
        return job

    def get(self, job_id: str) -> ExportJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in ("ready", "failed", "cancelled"):
            return False
        job._cancel.set()
        return True

    def discard(self, job_id: str) -> None:
        """Drop a job and delete its archive. Called after a successful download."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job and job.path:
            Path(job.path).unlink(missing_ok=True)

    # -- Worker --------------------------------------------------------

    def _run(self, job: ExportJob, files: list[tuple[Path, str]]) -> None:
        job.status = "running"
        fd, temp_path = tempfile.mkstemp(suffix=".zip", prefix="tikrec-export-")
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for source, arcname in files:
                    if job._cancel.is_set():
                        job.status = "cancelled"
                        Path(temp_path).unlink(missing_ok=True)
                        return
                    try:
                        zf.write(source, arcname)
                        job.bytes_done += source.stat().st_size
                    except OSError:
                        # One unreadable file should not lose the whole archive.
                        logger.warning("Skipping unreadable file in export: %s", source)
                    job.files_done += 1

            job.path = temp_path
            job.status = "ready"
            logger.info("Export %s ready: %d files", job.id, job.files_done)
        except Exception as exc:
            logger.exception("Export %s failed", job.id)
            job.status = "failed"
            job.error = str(exc)
            Path(temp_path).unlink(missing_ok=True)

    # -- Housekeeping --------------------------------------------------

    def _sweep_locked(self) -> None:
        """Drop expired jobs. Caller must hold the lock."""
        now = datetime.now(timezone.utc)
        for job_id, job in list(self._jobs.items()):
            if now - job.created_at <= _EXPORT_TTL:
                continue
            if job.path:
                Path(job.path).unlink(missing_ok=True)
            del self._jobs[job_id]
            logger.info("Swept expired export %s", job_id)

    def shutdown(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                job._cancel.set()
                if job.path:
                    Path(job.path).unlink(missing_ok=True)
            self._jobs.clear()
        self._executor.shutdown(wait=False)


export_service = ExportService()
