"""Post-recording compression.

After a recording is finalized, its H.264 MP4 is re-encoded to AV1 (SVT-AV1)
with Opus audio and the result *replaces* the original file, so the smaller
file is what is stored and served. Benchmarks on Flirt4Free 1080p streams:
CRF 30 at preset 8 is ~75% smaller at VMAF ~93.5 (the unencoded ceiling on
that content was ~97.8), i.e. visually indistinguishable at normal viewing.

Safety rules:
* One job at a time, at low OS priority and with a capped SVT-AV1 core count
  so live captures and the web UI keep their CPU.
* The original is only replaced after the new file is verified (AV1 video
  stream present, duration within tolerance). Any failure keeps the original.
* A result that isn't meaningfully smaller is discarded ("skipped").
* The file keeps its name and timeline, so thumbnails, sprites, clips and
  links stay valid.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.core.media_utils import _probe_duration, recording_path
from app.core.notification_service import notification_service
from app.core.settings_store import settings_store
from app.db.database import get_session
from app.db.models import Recording

logger = logging.getLogger("camsuite.compression")

# quality key -> SVT-AV1 CRF. Measured on 1080p cam footage (GB per hour of
# recording, VMAF out of a ~97.8 ceiling): high 0.45 GB/h ~94.2,
# balanced 0.35 GB/h ~93.5, small 0.23 GB/h ~92.4. Source H.264: ~1.4 GB/h.
QUALITY_CRF = {"high": 26, "balanced": 30, "small": 35}
DEFAULT_QUALITY = "balanced"
SVT_PRESET = 8
AUDIO_BITRATE = "96k"
# Keep the result only if it saves at least this fraction.
MIN_SAVING = 0.10
# Allowed duration drift between source and result.
_DURATION_TOLERANCE_ABS = 2.0
_DURATION_TOLERANCE_REL = 0.01

_FINISHED = ("completed", "stopped")


def default_threads() -> int:
    """Cores for the encoder: all but two, so capture and the UI stay responsive."""
    return max(1, (os.cpu_count() or 2) - 2)


_encoder_checked: bool | None = None


def encoder_available() -> bool:
    """True if this ffmpeg build has libsvtav1 and libopus."""
    global _encoder_checked
    if _encoder_checked is None:
        try:
            out = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15
            ).stdout
            _encoder_checked = "libsvtav1" in out and "libopus" in out
        except Exception:
            _encoder_checked = False
        if not _encoder_checked:
            logger.warning("ffmpeg lacks libsvtav1/libopus: post-recording compression is disabled")
    return _encoder_checked


def get_config() -> dict:
    cfg = settings_store.get("compression", None) or {}
    quality = cfg.get("quality", DEFAULT_QUALITY)
    return {
        "enabled": bool(cfg.get("enabled", settings.DEFAULT_COMPRESSION_ENABLED)),
        "quality": quality if quality in QUALITY_CRF else DEFAULT_QUALITY,
    }


def _video_codec(path: Path) -> str | None:
    try:
        return subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip() or None
    except Exception:
        return None


def build_encode_cmd(src: Path, dst: Path, crf: int, threads: int) -> list[str]:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostats",
        "-progress", "pipe:1",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libsvtav1", "-preset", str(SVT_PRESET), "-crf", str(crf),
        "-g", "300", "-pix_fmt", "yuv420p",
        "-svtav1-params", f"lp={threads}",
        "-c:a", "libopus", "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(dst),
    ]
    # Lowest scheduling priority on Linux; Windows gets a priority class below.
    if sys.platform != "win32" and shutil.which("nice"):
        cmd = ["nice", "-n", "19", *cmd]
    return cmd


class CompressionService:
    def __init__(self) -> None:
        self._queue: "queue.Queue[int]" = queue.Queue()
        # Every recording queued or running (for de-duplication)...
        self._queued: set[int] = set()
        # ...and the waiting ones in the order they'll run.
        self._order: list[int] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._current: dict | None = None  # see process()
        # Media seconds encoded per wall-clock second on the last finished job,
        # used to estimate how long the queue will take.
        self._last_speed: float | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._reset_interrupted()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="compression")
        self._thread.start()
        # Resume anything that was waiting when the app last stopped.
        with get_session() as db:
            pending = [r.id for r in db.query(Recording).filter(Recording.compress_status == "pending").all()]
        for rid in pending:
            self.enqueue(rid)

    def shutdown(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        self._queue.put(-1)  # wake the worker

    def _reset_interrupted(self) -> None:
        """A job running when the app died left a temp file; requeue it."""
        with get_session() as db:
            for rec in db.query(Recording).filter(Recording.compress_status == "processing").all():
                rec.compress_status = "pending"
                recording_path(rec.filename).with_suffix(".av1.tmp.mp4").unlink(missing_ok=True)
            db.commit()

    # --------------------------------------------------------------- queue
    def enqueue(self, recording_id: int) -> bool:
        """Queue a recording if compression is enabled. Returns True if queued."""
        if not get_config()["enabled"] or not encoder_available():
            return False
        with self._lock:
            if recording_id in self._queued:
                return False
            self._queued.add(recording_id)
            self._order.append(recording_id)
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == recording_id).first()
            if rec and rec.compress_status not in ("done", "processing"):
                rec.compress_status = "pending"
                rec.compress_error = None
                db.commit()
        self._queue.put(recording_id)
        return True

    def enqueue_backlog(self) -> int:
        """Queue every finished recording that hasn't been compressed yet."""
        with get_session() as db:
            ids = [
                r.id for r in db.query(Recording)
                .filter(Recording.status.in_(_FINISHED))
                .filter((Recording.compress_status.is_(None)) | (Recording.compress_status.in_(("failed", "pending"))))
                .order_by(Recording.created_at.asc())
                .all()
            ]
        return sum(1 for rid in ids if self.enqueue(rid))

    def status(self, queue_limit: int = 100) -> dict:
        """Config, the running job (with speed/ETA) and the waiting queue in run order."""
        cfg = get_config()
        with self._lock:
            order = list(self._order)
        current = self._current_snapshot()
        speed = (current or {}).get("speed") or self._last_speed

        queue_items: list[dict] = []
        if order:
            with get_session() as db:
                rows = {
                    r.id: r for r in db.query(Recording).filter(Recording.id.in_(order[:queue_limit])).all()
                }
                for rid in order[:queue_limit]:
                    r = rows.get(rid)
                    if r is None:
                        continue
                    queue_items.append({
                        "recording_id": r.id,
                        "filename": r.filename,
                        "username": r.user.username if r.user else None,
                        "file_size": r.file_size,
                        "duration_seconds": r.duration_seconds,
                    })

        queue_media_seconds = sum(q["duration_seconds"] or 0 for q in queue_items)
        remaining = (current or {}).get("eta_seconds") or 0
        eta_all = (remaining + queue_media_seconds / speed) if speed else None
        return {
            **cfg,
            "available": encoder_available(),
            "threads": default_threads(),
            "queue_length": len(order),
            "queue": queue_items,
            "current": current,
            "speed": round(speed, 2) if speed else None,
            "eta_all_seconds": int(eta_all) if eta_all is not None else None,
        }

    def _current_snapshot(self) -> dict | None:
        cur = self._current
        if not cur:
            return None
        snap = {k: v for k, v in cur.items() if not k.startswith("_")}
        elapsed = time.monotonic() - cur["_started"]
        snap["elapsed_seconds"] = int(elapsed)
        duration = cur.get("duration_seconds")
        done = cur.get("progress", 0.0) * (duration or 0)
        # Speed is only meaningful after a few seconds of encoding.
        if duration and elapsed > 5 and done > 0:
            speed = done / elapsed
            snap["speed"] = round(speed, 2)
            snap["eta_seconds"] = int((duration - done) / speed)
        else:
            snap["speed"] = None
            snap["eta_seconds"] = None
        return snap

    # -------------------------------------------------------------- worker
    def _worker(self) -> None:
        while not self._stop.is_set():
            rid = self._queue.get()
            if rid < 0 or self._stop.is_set():
                break
            with self._lock:
                if rid in self._order:
                    self._order.remove(rid)
            try:
                self.process(rid)
            except Exception:
                logger.exception("Compression of recording %d crashed", rid)
                self._finish(rid, "failed", error="Internal error during compression")
            finally:
                with self._lock:
                    self._queued.discard(rid)
                self._current = None

    def _finish(self, rid: int, status: str, error: str | None = None, **fields) -> None:
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == rid).first()
            if not rec:
                return
            rec.compress_status = status
            rec.compress_error = error
            for k, v in fields.items():
                setattr(rec, k, v)
            db.commit()

    def process(self, rid: int) -> str:
        """Compress one recording synchronously. Returns the final compress_status."""
        with get_session() as db:
            rec = db.query(Recording).filter(Recording.id == rid).first()
            if not rec:
                return "missing"
            if rec.status not in _FINISHED:
                # Failed or still-running recordings are left alone.
                rec.compress_status = None
                db.commit()
                return "not_finished"
            filename = rec.filename
            username = rec.user.username if rec.user else None
            rec.compress_status = "processing"
            db.commit()

        src = recording_path(filename)
        if not src.exists():
            self._finish(rid, "failed", error="Recording file not found")
            return "failed"
        if _video_codec(src) == "av1":
            self._finish(rid, "done")
            return "done"

        src_size = src.stat().st_size
        src_duration = _probe_duration(src)
        tmp = src.with_suffix(".av1.tmp.mp4")
        crf = QUALITY_CRF[get_config()["quality"]]
        threads = default_threads()
        self._current = {
            "recording_id": rid,
            "filename": filename,
            "username": username,
            "file_size": src_size,
            "duration_seconds": src_duration,
            "progress": 0.0,
            "started_at": datetime.utcnow().isoformat(),
            "_started": time.monotonic(),
        }
        logger.info("Compressing recording %d (%s, %.1f MB) at CRF %d, %d cores",
                    rid, filename, src_size / 1e6, crf, threads)

        started = time.time()
        ok, err = self._encode(src, tmp, crf, threads, src_duration)
        if self._stop.is_set():
            tmp.unlink(missing_ok=True)
            self._finish(rid, "pending")
            return "pending"
        if not ok:
            tmp.unlink(missing_ok=True)
            self._finish(rid, "failed", error=err)
            return "failed"

        # --- verify before touching the original ---
        problem = self._verify(tmp, src_duration)
        if problem:
            tmp.unlink(missing_ok=True)
            logger.warning("Compressed output for recording %d rejected: %s", rid, problem)
            self._finish(rid, "failed", error=f"Verification failed: {problem}")
            return "failed"

        new_size = tmp.stat().st_size
        if new_size > src_size * (1 - MIN_SAVING):
            tmp.unlink(missing_ok=True)
            self._finish(rid, "skipped", error="Compressed file was not meaningfully smaller")
            return "skipped"

        # The recording may have been deleted while we were encoding.
        with get_session() as db:
            still_there = db.query(Recording).filter(Recording.id == rid).first() is not None
        if not still_there or not src.exists():
            tmp.unlink(missing_ok=True)
            return "missing"

        try:
            os.replace(tmp, src)
        except OSError as exc:
            # Windows refuses while the file is open (e.g. being streamed).
            tmp.unlink(missing_ok=True)
            self._finish(rid, "failed", error=f"Could not replace original: {exc}")
            return "failed"

        self._finish(rid, "done", original_size=src_size, file_size=new_size)
        elapsed = time.time() - started
        if src_duration and elapsed > 0:
            self._last_speed = src_duration / elapsed
        saved = src_size - new_size
        logger.info("Recording %d compressed: %.1f MB -> %.1f MB (%.0f%% saved) in %.0fs",
                    rid, src_size / 1e6, new_size / 1e6, 100 * saved / src_size, elapsed)
        try:
            notification_service.publish(
                type="recording_compressed",
                title="Recording compressed",
                message=f"{filename}: {src_size / 1e9:.2f} GB → {new_size / 1e9:.2f} GB",
                data={"recording_id": rid, "saved_bytes": saved},
            )
        except Exception:
            logger.debug("Failed to publish compression notification", exc_info=True)
        return "done"

    def _encode(self, src: Path, dst: Path, crf: int, threads: int, duration: float | None) -> tuple[bool, str | None]:
        cmd = build_encode_cmd(src, dst, crf, threads)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        try:
            self._proc = proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs
            )
        except Exception as exc:
            return False, f"Could not start ffmpeg: {exc}"

        # Collect stderr on a side thread so a chatty ffmpeg can't block on a full pipe.
        err_chunks: list[str] = []
        t = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
        t.start()
        for line in proc.stdout:
            if line.startswith("out_time_us=") and duration:
                try:
                    done = int(line.split("=", 1)[1]) / 1e6
                    if self._current:
                        self._current["progress"] = round(min(1.0, done / duration), 4)
                except ValueError:
                    pass
        proc.wait()
        t.join(timeout=5)
        self._proc = None
        if proc.returncode != 0:
            tail = "".join(err_chunks).strip()[-400:]
            return False, f"ffmpeg exited with {proc.returncode}: {tail}" if tail else f"ffmpeg exited with {proc.returncode}"
        if not dst.exists() or dst.stat().st_size == 0:
            return False, "ffmpeg produced no output"
        return True, None

    @staticmethod
    def _verify(path: Path, expected_duration: float | None) -> str | None:
        if _video_codec(path) != "av1":
            return "output has no AV1 video stream"
        if expected_duration:
            got = _probe_duration(path)
            if got is None:
                return "could not read output duration"
            tolerance = max(_DURATION_TOLERANCE_ABS, expected_duration * _DURATION_TOLERANCE_REL)
            if abs(got - expected_duration) > tolerance:
                return f"duration {got:.1f}s differs from source {expected_duration:.1f}s"
        return None


compression_service = CompressionService()
