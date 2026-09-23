import json
import logging
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from app.config import settings
from app.core.media_utils import recording_path

logger = logging.getLogger(__name__)

# Model cache; the first job downloads the model here and later jobs reuse it.
_WHISPER_CACHE_DIR = Path(settings.DATA_DIR) / "whisper_cache"

# Directory that contains the ``app`` package, so ``python -m app.core...``
# resolves no matter what the API process's working directory is.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Generous cap so a wedged worker can't block the queue forever; CPU Whisper
# "tiny" runs well under real time, so twice the recording length is ample.
_MIN_TIMEOUT_SECONDS = 600


class TranscriptionFailed(Exception):
    """The worker process could not produce a transcript."""


def _run_worker(video_path: Path, duration_seconds: int | None, on_start=None) -> dict:
    """Transcribe *video_path* in a child process and return its JSON result.

    Whisper runs out-of-process so its model, runtimes and audio buffers are
    returned to the OS when the job ends, instead of staying resident in the
    API process (see ``app/core/transcribe_worker.py``).
    """
    _WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    timeout = max(_MIN_TIMEOUT_SECONDS, 2 * (duration_seconds or 0))
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "app.core.transcribe_worker",
            str(video_path), "--cache-dir", str(_WHISPER_CACHE_DIR),
        ],
        cwd=str(_BACKEND_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if on_start is not None:
        on_start(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise TranscriptionFailed(f"worker timed out after {timeout}s")
    stderr_tail = stderr.decode(errors="replace")[-2000:]
    if proc.returncode != 0:
        raise TranscriptionFailed(f"worker exited {proc.returncode}: {stderr_tail}")
    try:
        result = json.loads(stdout)
        lines = result["lines"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TranscriptionFailed(f"worker returned invalid output ({exc}): {stderr_tail}")
    if not isinstance(lines, list):
        raise TranscriptionFailed("worker returned non-list lines")
    return result


def _reset_stuck_processing(db) -> None:
    """Reset any recordings stuck in 'processing' to 'failed'.

    Called once at startup so records orphaned by a previous container
    restart are not left in a permanent 'processing' state.
    """
    from app.db.models import Recording
    try:
        stuck = db.query(Recording).filter(Recording.transcript_status == "processing").all()
        for rec in stuck:
            rec.transcript_status = "failed"
            logger.warning(
                "Reset stuck transcription for recording %d (%s) to 'failed'",
                rec.id, rec.filename,
            )
        if stuck:
            db.commit()
    except Exception as exc:
        logger.error("Failed to reset stuck transcriptions: %s", exc)


class TranscriptionService:
    """Transcribe completed recordings using faster-whisper.

    Up to ``MAX_WORKERS`` transcriptions run concurrently. Additional
    requests are queued and dispatched in FIFO order as workers become
    available.

    The DB session is intentionally kept open only for short reads/writes
    and is always closed before the long-running Whisper inference starts,
    so SQLite is never locked for the duration of a transcription job.
    """

    MAX_WORKERS = 1

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._shutting_down = False
        self._queue: list[int] = []
        self._queue_cond = threading.Condition()
        self._executor = ThreadPoolExecutor(
            max_workers=self.MAX_WORKERS,
            thread_name_prefix="transcribe",
        )
        self._dispatcher = threading.Thread(target=self._dispatcher_loop, daemon=True)
        self._dispatcher.start()
        self._reset_stuck_on_startup()

    def _reset_stuck_on_startup(self) -> None:
        """Reset any 'processing' records left over from a previous crash."""
        try:
            from app.db.database import get_session
            with get_session() as db:
                _reset_stuck_processing(db)
        except Exception as exc:
            logger.error("Startup stuck-transcription reset failed: %s", exc)

    def enqueue(self, recording_id: int) -> None:
        """Add a recording to the transcription queue."""
        with self._queue_cond:
            if recording_id not in self._queue:
                self._queue.append(recording_id)
                logger.info(
                    "Enqueued recording %d for transcription (queue len=%d)",
                    recording_id, len(self._queue),
                )
                self._queue_cond.notify()

    def shutdown(self) -> None:
        """Kill a running worker so it doesn't outlive the API process."""
        with self._proc_lock:
            self._shutting_down = True
            proc = self._proc
        if proc is not None and proc.poll() is None:
            logger.info("Stopping transcription worker (pid %d)", proc.pid)
            proc.kill()

    def _set_proc(self, proc: subprocess.Popen | None) -> None:
        with self._proc_lock:
            self._proc = proc
            if proc is not None and self._shutting_down:
                proc.kill()

    def get_queue(self) -> list[int]:
        """Return a copy of the current queue (for status/debug)."""
        with self._queue_cond:
            return list(self._queue)

    def _dispatcher_loop(self) -> None:
        """Background dispatcher: pulls from queue, submits to thread pool."""
        while True:
            recording_id: int | None = None
            with self._queue_cond:
                while not self._queue:
                    self._queue_cond.wait()
                recording_id = self._queue.pop(0)

            logger.info(
                "Dispatching transcription for recording %d (queue len=%d)",
                recording_id, len(self._queue),
            )
            self._executor.submit(self._run, recording_id)

    def _run(self, recording_id: int) -> None:
        from app.db.database import get_session
        from app.db.models import Recording

        # --- Phase 1: short DB read — validate and mark as processing ---
        video_path: Path | None = None
        duration_seconds: int | None = None
        try:
            with get_session() as db:
                recording = db.query(Recording).filter(Recording.id == recording_id).first()
                if not recording:
                    return
                if recording.status not in ("completed", "stopped"):
                    return
                video_path = recording_path(recording.filename)
                if not video_path.exists():
                    recording.transcript_status = "failed"
                    db.commit()
                    logger.warning("Transcription skipped for recording %d: file not found", recording_id)
                    return
                duration_seconds = recording.duration_seconds
                recording.transcript_status = "processing"
                db.commit()
        except Exception as exc:
            logger.error("Transcription pre-check failed for recording %d: %s", recording_id, exc)
            return

        # --- Phase 2-3: run Whisper in a child process (no DB session held) ---
        try:
            logger.info("Starting Whisper inference for recording %d (%s)", recording_id, video_path.name)
            try:
                result = _run_worker(video_path, duration_seconds, on_start=self._set_proc)
            finally:
                self._set_proc(None)
            parts = result["lines"]
            transcript_text = "\n".join(parts)
            logger.info(
                "Whisper inference done for recording %d — %d segments, lang=%s (%.0f%%)",
                recording_id, len(parts), result.get("language"),
                (result.get("language_probability") or 0) * 100,
            )
        except Exception as exc:
            logger.error("Whisper inference failed for recording %d: %s", recording_id, exc)
            try:
                with get_session() as db:
                    rec = db.query(Recording).filter(Recording.id == recording_id).first()
                    if rec:
                        rec.transcript_status = "failed"
                        db.commit()
            except Exception:
                pass
            return

        # --- Phase 4: short DB write — persist results ---
        try:
            with get_session() as db:
                rec = db.query(Recording).filter(Recording.id == recording_id).first()
                if rec:
                    rec.transcript_text = transcript_text
                    rec.transcript_status = "done"
                    db.commit()
                    logger.info("Transcription saved for recording %d", recording_id)
        except Exception as exc:
            logger.error("Failed to save transcription for recording %d: %s", recording_id, exc)

    def search(self, query: str, db) -> list[dict]:
        """Return recording IDs and snippet matches for a transcript text search."""
        from app.db.models import Recording
        from sqlalchemy import func

        results = (
            db.query(Recording)
            .filter(
                Recording.transcript_status == "done",
                func.lower(Recording.transcript_text).contains(query.lower()),
            )
            .all()
        )
        out = []
        for rec in results:
            snippet = _extract_snippet(rec.transcript_text or "", query)
            out.append({
                "recording_id": rec.id,
                # Recording has no username column; it lives on the related User.
                "username": rec.user.username if rec.user else None,
                "snippet": snippet,
            })
        return out


def _extract_snippet(text: str, query: str, context: int = 80) -> str:
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:160]
    start = max(0, idx - context)
    end = min(len(text), idx + len(query) + context)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


transcription_service = TranscriptionService()
