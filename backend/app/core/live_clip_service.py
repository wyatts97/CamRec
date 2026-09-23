"""Clip-from-live service.

Lets a user capture a clip *while* a stream is still being recorded, without
touching the main recording. It does this by spawning a **separate** ffmpeg
process that reads the same public live URL and writes to its own MPEG-TS file
(truncation-safe — needs no moov atom), then remuxes that to a faststart MP4
when the user stops the clip. The main recording's file and thread are never
touched.

At most one live clip per recording is allowed at a time.
"""
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from app.db.database import get_session, run_background
from app.db.models import Recording, Clip
from app.core.media_utils import clip_directory, generate_thumbnail, generate_sprite, thumbnail_path
from app.core.site_service import site_service
from app.core.notification_service import notification_service

logger = logging.getLogger("camsuite.live_clip")


class LiveClipTask:
    """Runs one ffmpeg capture of a live stream into a .ts file."""

    def __init__(self, recording_id: int, username: str, site: str, model_id: str, ts_path: Path, start_offset: int):
        self.recording_id = recording_id
        self.username = username
        self.site = site
        self.model_id = model_id
        self.ts_path = ts_path
        self.start_offset = start_offset
        self.started_wall = time.time()
        self.error: str | None = None
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            live_url = site_service.get_live_url(self.model_id, self.site)
        except Exception as exc:
            self.error = str(exc) or "Could not resolve live stream URL"
            self._ready.set()
            logger.warning("Live clip for recording %d: no live URL (%s)", self.recording_id, exc)
            return
        user_agent = site_service.adapter(self.site).ffmpeg_headers().get("User-Agent")
        try:
            self._proc = subprocess.Popen(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    *(["-user_agent", user_agent] if user_agent else []),
                    "-fflags", "+igndts+genpts",
                    "-i", live_url,
                    "-c", "copy",
                    "-f", "mpegts",
                    str(self.ts_path),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.error = f"Failed to start ffmpeg: {exc}"
            self._ready.set()
            return

        self._ready.set()
        # Hold until asked to stop or the stream ends on its own.
        while not self._stop.is_set():
            if self._proc.poll() is not None:
                break
            time.sleep(0.5)

    def wait_ready(self, timeout: float = 8.0) -> bool:
        return self._ready.wait(timeout)

    def elapsed(self) -> int:
        return int(time.time() - self.started_wall)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop_capture(self) -> None:
        """Ask ffmpeg to finish writing, falling back to terminate."""
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)


def _remux_ts_to_mp4(ts_path: Path, mp4_path: Path) -> bool:
    """Remux a captured .ts into a faststart .mp4 (copy, re-encode fallback)."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-fflags", "+igndts+genpts", "-err_detect", "ignore_err",
                "-i", str(ts_path),
                "-c", "copy", "-movflags", "+faststart",
                str(mp4_path),
            ],
            capture_output=True, check=True, timeout=180,
        )
        if mp4_path.exists() and mp4_path.stat().st_size > 0:
            return True
    except Exception:
        logger.warning("Live clip stream-copy remux failed for %s, re-encoding", ts_path)

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-fflags", "+igndts+genpts", "-err_detect", "ignore_err",
                "-i", str(ts_path),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                str(mp4_path),
            ],
            capture_output=True, check=True, timeout=300,
        )
        return mp4_path.exists() and mp4_path.stat().st_size > 0
    except Exception:
        logger.error("Live clip re-encode remux failed for %s", ts_path)
        return False


class LiveClipService:
    def __init__(self) -> None:
        self._tasks: dict[int, LiveClipTask] = {}
        self._lock = threading.Lock()

    def is_active(self, recording_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(recording_id)
            return task is not None

    def status(self, recording_id: int) -> dict:
        with self._lock:
            task = self._tasks.get(recording_id)
            if not task:
                return {"active": False, "elapsed": 0}
            return {"active": True, "elapsed": task.elapsed(), "error": task.error}

    def start(self, recording_id: int) -> dict:
        """Begin a live clip for an active recording. Returns status dict."""
        with self._lock:
            if recording_id in self._tasks:
                return {"active": True, "elapsed": self._tasks[recording_id].elapsed()}

        # Validate the recording is currently active and resolve metadata.
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == recording_id).first()
            if not rec:
                raise ValueError("Recording not found")
            if rec.status not in ("pending", "recording"):
                raise ValueError("Recording is not active")
            model_id = rec.user.model_id
            site = rec.user.site
            username = rec.user.username
            started_at = rec.started_at
            if not model_id:
                raise ValueError("No model id known for this recording")

        start_offset = 0
        if started_at:
            start_offset = max(0, int((datetime.utcnow() - started_at).total_seconds()))

        stem = f"liveclip_{recording_id}_{time.strftime('%Y%m%d_%H%M%S')}"
        ts_path = clip_directory() / f"{stem}.ts"
        ts_path.parent.mkdir(parents=True, exist_ok=True)

        task = LiveClipTask(recording_id, username, site, model_id, ts_path, start_offset)
        task.start()
        task.wait_ready(timeout=8)
        if task.error:
            raise RuntimeError(task.error)

        with self._lock:
            self._tasks[recording_id] = task
        logger.info("Started live clip for recording %d (%s)", recording_id, username)
        return {"active": True, "elapsed": 0}

    def stop(self, recording_id: int) -> dict:
        """Stop the live clip, remux to MP4, and create a Clip row."""
        with self._lock:
            task = self._tasks.pop(recording_id, None)
        if not task:
            raise ValueError("No active live clip for this recording")

        task.stop_capture()

        ts_path = task.ts_path
        if not ts_path.exists() or ts_path.stat().st_size == 0:
            ts_path.unlink(missing_ok=True)
            raise RuntimeError("Live clip produced no data")

        mp4_path = ts_path.with_suffix(".mp4")
        ok = _remux_ts_to_mp4(ts_path, mp4_path)
        ts_path.unlink(missing_ok=True)
        if not ok:
            mp4_path.unlink(missing_ok=True)
            raise RuntimeError("Failed to finalize live clip")

        end_offset = task.start_offset + task.elapsed()
        duration = max(1, end_offset - task.start_offset)
        file_size = mp4_path.stat().st_size if mp4_path.exists() else None

        with get_session() as db:
            clip = Clip(
                recording_id=recording_id,
                # Stored on the clip so it survives deletion of the recording.
                username=task.username,
                title=f"Live clip — {task.username}",
                filename=mp4_path.name,
                start_time=task.start_offset,
                end_time=end_offset,
                duration_seconds=duration,
                file_size=file_size,
            )
            db.add(clip)
            db.commit()
            db.refresh(clip)
            clip_id = clip.id

        run_background(generate_thumbnail, mp4_path, thumbnail_path(mp4_path))
        run_background(generate_sprite, mp4_path)

        try:
            notification_service.publish(
                type="clip_ready",
                title=f"Live clip saved: {task.username}",
                message=f"A {duration}s clip was captured from the live stream.",
                data={"clip_id": clip_id, "recording_id": recording_id, "username": task.username},
            )
        except Exception:
            logger.debug("Failed to publish clip-ready notification", exc_info=True)

        logger.info("Saved live clip %d for recording %d (%ds)", clip_id, recording_id, duration)
        return {"active": False, "clip_id": clip_id, "duration_seconds": duration}


live_clip_service = LiveClipService()
