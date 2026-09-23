import subprocess
import time
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from app.db.database import get_session, run_background
from app.db.models import Recording, User
from app.core.media_utils import (
    generate_recording_filename,
    generate_sprite,
    generate_thumbnail,
    remux_to_mp4,
    repair_video,
    analyze_video_health,
    concat_ts_segments,
    finalize_segments_to_mp4,
    recording_path,
)
from app.core.notification_service import notification_service
from app.core.site_service import site_service


def _update_recording_status(recording_id: int, status: str, error_message: str | None = None) -> None:
    with get_session() as db:
        recording = db.query(Recording).filter(Recording.id == recording_id).first()
        if recording:
            recording.status = status
            if error_message is not None:
                recording.error_message = error_message
            if status in ("failed", "completed", "stopped"):
                recording.ended_at = datetime.utcnow()
            if status == "failed":
                recording.is_corrupt = True
            db.commit()


logger = logging.getLogger("camsuite.task_manager")

# Capture is treated as stalled if the .ts output file does not grow for this
# many seconds while ffmpeg is still running (dead socket with no reconnect).
# A cam room going private freezes the playlist, so this also ends the segment
# when a public show turns into a private one.
_STALL_TIMEOUT_SECONDS = 45

# Resumable live capture settings — when the stream drops (URL expiry, a short
# private show, a model's connection blip) ffmpeg exits and we re-check the room
# and resume with a fresh URL instead of finalizing the recording.
_MAX_RESUME_ATTEMPTS = 30
_RESUME_BACKOFF_SECONDS = (3, 5, 10, 15, 30)
_OFFLINE_CONFIRMATION_SECONDS = 90
_SEGMENT_CHECK_INTERVAL = 0.5
# A segment that captured cleanly for at least this long is treated as a
# healthy session whose URL expired: the resume counter resets and the next
# segment starts without backoff.
_HEALTHY_SEGMENT_SECONDS = 60

# Independent re-confirmation of liveness while a segment is actively
# capturing. The stall detector only catches a *dead* stream (no bytes); it
# can't catch a stream that keeps producing bytes (e.g. a stale/looping CDN
# placeholder) after the room actually went offline. Re-checking room status
# periodically closes that gap so a false "still live" signal can't keep a
# recording running indefinitely.
_LIVE_RECONFIRM_SECONDS = 120


def _read_log_tail(log_path: Path | None, max_chars: int = 600) -> str | None:
    """Return the last *max_chars* of an ffmpeg log file, if it exists."""
    if log_path is None or not log_path.exists():
        return None
    try:
        data = log_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if not data:
        return None
    return data[-max_chars:]


def _check_live_with_backoff(
    username: str,
    site: str,
    model_id: str | None,
    max_retries: int = 3,
    backoff_seconds: tuple[int, ...] = (5, 10, 15),
) -> tuple[bool, str | None]:
    """Confirm whether *username*'s room is currently public (recordable).

    Performs up to *max_retries* checks with backoff to tolerate transient
    site blips and short private shows. Returns ``(is_public, model_id)``.
    """
    for attempt in range(max_retries):
        try:
            status = site_service.check_status(username, site, model_id)
            model_id = status.model_id or model_id
            if status.is_public and model_id:
                return True, model_id
            if status.state == "not_found":
                return False, model_id
        except Exception as exc:
            logger.debug("Live check attempt %d failed for %s: %s", attempt + 1, username, exc)
        if attempt < max_retries - 1:
            delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(delay)
    return False, model_id


def _resolve_fresh_live_url(model_id: str, site: str) -> str | None:
    """Resolve a fresh recordable stream URL if the room is still public."""
    try:
        if not site_service.is_public(model_id, site):
            return None
        return site_service.get_live_url(model_id, site)
    except Exception as exc:
        logger.debug("Failed to resolve fresh URL for model %s: %s", model_id, exc)
        return None


def _build_capture_cmd(
    live_url: str,
    ts_path: Path,
    duration: int | None,
    proxy: str | None,
    headers: dict[str, str] | None,
) -> list[str]:
    """Build the ffmpeg capture command, wiring proxy/headers when present.

    ffmpeg consumes the HLS variant playlist directly and writes a single
    continuous MPEG-TS. The proxy is passed so a stream reachable only through
    the same proxy as URL discovery still works.
    """
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        # Reconnect on transient network drops, but NOT at EOF: a live EOF means
        # the broadcast/session ended. Reconnecting at EOF makes ffmpeg pull the
        # dead URL's slate/junk (the "black tail" bug) instead of exiting so the
        # resume loop can re-resolve a fresh URL.
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        # Exit promptly when the socket dies instead of hanging until the 90s
        # stall detector fires (15s in microseconds).
        "-rw_timeout", "15000000",
    ]
    if proxy:
        cmd += ["-http_proxy", proxy]
    headers = dict(headers or {})
    user_agent = headers.pop("User-Agent", None)
    if user_agent:
        cmd += ["-user_agent", user_agent]
    if headers:
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    cmd += [
        # Record the stream verbatim — keep the original timestamps. Do NOT add
        # +igndts+genpts here: regenerating timestamps during a live capture lets
        # audio and video drift apart. Timestamp repair happens once, at remux.
        "-i", live_url,
        "-c", "copy",
        "-f", "mpegts",
    ]
    if duration:
        cmd += ["-t", str(duration)]
    cmd.append(str(ts_path))
    return cmd


def _notify_recording_finished(recording_id: int, username: str, status: str, duration_seconds: int) -> None:
    """Publish a notification when a recording reaches a terminal state."""
    if status == "completed":
        title = f"Recording completed: {username}"
        message = f"Recorded {duration_seconds // 60} min"
    elif status == "stopped":
        title = f"Recording stopped: {username}"
        message = f"Recorded {duration_seconds // 60} min"
    else:  # failed
        title = f"Recording failed: {username}"
        message = "The recording ended unexpectedly."
    notification_service.publish(
        type=f"recording_{status}",
        title=title,
        message=message,
        data={"recording_id": recording_id, "username": username, "status": status},
    )


class RecordingTask:
    def __init__(
        self,
        recording_id: int,
        username: str,
        model_id: str,
        site: str,
        duration: int | None = None,
        proxy: str | None = None
    ):
        self.recording_id = recording_id
        self.username = username
        self.model_id = model_id
        self.site = site
        self.duration = duration
        self.proxy = proxy
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_path: Path | None = None
        self._ts_path: Path | None = None
        self._log_path: Path | None = None
        self._proc: subprocess.Popen | None = None
        self._start_time: float | None = None
        self._capture_error: str | None = None
        self._segments: list[Path] = []
        self._finalized = False
        self._segment_index = 0
        self._total_elapsed_seconds: float | None = None
    
    def start(self):
        self._thread = threading.Thread(target=self._run_with_error_handling, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._stop_event.set()
        # Ask the capture ffmpeg to finish gracefully so the final GOP and
        # the MPEG-TS trailer are flushed before we remux.
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
            self._thread.join(timeout=15)
    
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
    
    def _run(self):
        # --- Phase 1: mark as recording (short-lived session) ---
        with get_session() as db:
            recording = db.query(Recording).filter(Recording.id == self.recording_id).first()
            if not recording:
                return
            filename = recording.filename
            recording.status = "recording"
            recording.started_at = datetime.utcnow()
            db.commit()

        # --- Phase 2: validate room and get initial stream URL (no DB) ---
        try:
            is_public = site_service.is_public(self.model_id, self.site)
        except Exception:
            is_public = True  # status blip: let the stream lookup decide
        if not is_public:
            _update_recording_status(self.recording_id, "failed", "Room is not in a public show")
            return

        try:
            live_url = site_service.get_live_url(self.model_id, self.site)
        except Exception as exc:
            _update_recording_status(self.recording_id, "failed", str(exc))
            return
        headers = site_service.adapter(self.site).ffmpeg_headers()

        # --- Phase 3: resumable capture into sequential segments ---
        # A public show is interrupted by private shows and connection blips.
        # Instead of finalizing the recording when ffmpeg exits, we re-check
        # the room, re-resolve a fresh URL and start a new segment, then
        # concatenate all segments into one file at finalize time. This keeps
        # one broadcast session as one recording.
        output_path = recording_path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path = output_path
        self._ts_path = output_path.with_suffix(".ts")
        self._log_path = output_path.with_suffix(".ffmpeg.log")
        self._start_time = time.time()

        model_id = self.model_id
        resumed = False
        resume_attempts = 0
        session_done = False
        self._capture_error = None

        while not session_done:
            # Manual stop or duration cap ends the session immediately.
            if self._stop_event.is_set():
                break

            elapsed = time.time() - self._start_time
            if self.duration is not None and elapsed >= self.duration:
                logger.info("Recording %d: duration cap reached (%d s)", self.recording_id, self.duration)
                break

            segment_remaining = None
            if self.duration is not None:
                segment_remaining = max(1, int(self.duration - elapsed))

            segment_index = len(self._segments) + 1
            segment_path = output_path.with_suffix(f".part{segment_index:03d}.ts")

            cmd = _build_capture_cmd(live_url, segment_path, segment_remaining, self.proxy, headers)
            log_fh = None
            proc = None
            try:
                log_fh = open(self._log_path, "ab")
            except Exception:
                log_fh = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=(log_fh or subprocess.DEVNULL),
                )
            except Exception as e:
                logger.error("Failed to start ffmpeg capture for recording %d: %s", self.recording_id, e)
                if log_fh:
                    log_fh.close()
                self._capture_error = f"Capture failed to start: {e}"
                break

            self._proc = proc
            segment_started = time.time()
            logger.info(
                "Recording %d: started segment %d%s",
                self.recording_id, segment_index, " (resumed)" if resumed else "",
            )

            # Monitor this segment until it ends, stalls, is confirmed offline,
            # or is manually stopped.
            last_size = -1
            last_growth = time.time()
            last_live_reconfirm = time.time()
            segment_failed = False
            while not self._stop_event.is_set():
                if proc.poll() is not None:
                    break
                try:
                    cur_size = segment_path.stat().st_size if segment_path.exists() else 0
                except OSError:
                    cur_size = 0
                now = time.time()
                if cur_size > last_size:
                    last_size = cur_size
                    last_growth = now
                elif now - last_growth > _STALL_TIMEOUT_SECONDS:
                    logger.warning(
                        "Recording %d: segment %d stalled (no growth for %ds)",
                        self.recording_id, segment_index, _STALL_TIMEOUT_SECONDS,
                    )
                    self._capture_error = (
                        f"Segment {segment_index} stalled — no data for {_STALL_TIMEOUT_SECONDS}s"
                    )
                    segment_failed = True
                    break

                # Independent public-room re-check: catches a stream that keeps
                # producing bytes (e.g. a placeholder loop) after the show went
                # private or offline — the stall detector above can't see this
                # since the file is still growing.
                if now - last_live_reconfirm > _LIVE_RECONFIRM_SECONDS:
                    last_live_reconfirm = now
                    try:
                        still_public = site_service.is_public(model_id, self.site)
                    except Exception:
                        still_public = True  # network blip — don't kill a good recording
                    if not still_public:
                        logger.info(
                            "Recording %d: model %s no longer public on re-check; pausing capture",
                            self.recording_id, model_id,
                        )
                        self._capture_error = "Room left the public show during periodic re-check"
                        segment_failed = True
                        break
                time.sleep(_SEGMENT_CHECK_INTERVAL)

            # Ensure the segment ffmpeg exits cleanly.
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
            if log_fh:
                try:
                    log_fh.close()
                except Exception:
                    pass
            self._proc = None

            # Record the segment if it produced any data.
            segment_healthy = False
            if segment_path.exists() and segment_path.stat().st_size > 0:
                self._segments.append(segment_path)
                self._capture_error = None  # a good segment clears prior transient errors
                segment_healthy = (
                    not segment_failed
                    and time.time() - segment_started >= _HEALTHY_SEGMENT_SECONDS
                )
            elif not self._stop_event.is_set():
                logger.warning(
                    "Recording %d: segment %d produced no data; treating as end-of-stream",
                    self.recording_id, segment_index,
                )
                segment_failed = True

            # Manual stop or duration cap ends the session.
            if self._stop_event.is_set():
                break
            elapsed = time.time() - self._start_time
            if self.duration is not None and elapsed >= self.duration:
                break

            # Otherwise, decide whether the session really ended or just needs a fresh URL.
            if segment_failed or proc.poll() is not None:
                if segment_healthy:
                    # A long, clean segment ending is usually a stream hiccup,
                    # not the broadcast ending. Reset the counter so backoff
                    # doesn't grow across a long session, and try a fresh URL
                    # straight away: every second spent here is a second
                    # missing from the recording.
                    resume_attempts = 0
                    fresh_url = _resolve_fresh_live_url(model_id, self.site)
                    if fresh_url:
                        live_url = fresh_url
                        resumed = True
                        logger.info(
                            "Recording %d: segment ended after %ds; fast-resuming with fresh URL (model %s)",
                            self.recording_id, int(time.time() - segment_started), model_id,
                        )
                        continue

                resume_attempts += 1
                if resume_attempts > _MAX_RESUME_ATTEMPTS:
                    logger.warning(
                        "Recording %d: exceeded max resume attempts (%d), finalizing",
                        self.recording_id, _MAX_RESUME_ATTEMPTS,
                    )
                    break

                backoff = _RESUME_BACKOFF_SECONDS[
                    min(resume_attempts - 1, len(_RESUME_BACKOFF_SECONDS) - 1)
                ]
                logger.info(
                    "Recording %d: ffmpeg exited/segment failed; waiting %ds before re-checking live status",
                    self.recording_id, backoff,
                )
                time.sleep(backoff)

                is_public, fresh_model_id = _check_live_with_backoff(
                    self.username,
                    self.site,
                    model_id,
                    max_retries=3,
                    backoff_seconds=(10, 20, _OFFLINE_CONFIRMATION_SECONDS // 3),
                )
                if not is_public or not fresh_model_id:
                    logger.info(
                        "Recording %d: %s no longer in a public show, finalizing session",
                        self.recording_id, self.username,
                    )
                    break

                # Room is public again — refresh the URL and resume.
                fresh_url = _resolve_fresh_live_url(fresh_model_id, self.site)
                if not fresh_url:
                    logger.warning(
                        "Recording %d: room public but could not resolve fresh URL; retrying",
                        self.recording_id,
                    )
                    continue
                model_id = fresh_model_id
                live_url = fresh_url
                resumed = True
                logger.info(
                    "Recording %d: resuming session with fresh URL (model %s)",
                    self.recording_id, model_id,
                )
            else:
                # This path should be unreachable; treat as session end to be safe.
                break

        self._total_elapsed_seconds = time.time() - self._start_time
        self._finalize_recording()

    def _finalize_recording(self) -> None:
        """Finalize a recording: flush file, update DB, remux, thumbnails.
        Called from _run() on normal exit and from _run_with_error_handling()
        in finally to guarantee it always runs even on unexpected thread death.
        """
        if self._finalized:
            return
        self._finalized = True

        output_path = self._output_path
        start_time = self._start_time

        if output_path is None or start_time is None:
            # Recording never reached Phase 3 (no file created)
            return

        ts_path = self._ts_path
        ended_at = datetime.utcnow()
        # Wall-clock elapsed — used only for notifications. The authoritative
        # duration comes from probing the finalized MP4 (real content only,
        # excluding offline gaps and resume backoff waits).
        wall_clock_seconds = int(self._total_elapsed_seconds or (time.time() - start_time))

        # Gather the captured sources. Normally these are the resumable
        # ``.partNNN.ts`` segments; a lone ``.ts`` may exist from a legacy or
        # single-segment capture path.
        segments = [p for p in self._segments if p.exists() and p.stat().st_size > 0]
        if not segments and ts_path is not None and ts_path.exists() and ts_path.stat().st_size > 0:
            segments = [ts_path]

        captured = bool(segments)

        # Move the row to "processing" while we remux/concat. Setting a terminal
        # status here (as the old code did) made a healthy recording flash the
        # "needs repair" UI during the remux window, and a repair click would
        # 404 because the .mp4 didn't exist yet.
        with get_session() as db:
            recording = db.query(Recording).filter(Recording.id == self.recording_id).first()
            if not recording:
                return
            if recording.status in ("recording", "pending"):
                recording.ended_at = ended_at
                if captured:
                    recording.status = "processing"
                    recording.duration_seconds = wall_clock_seconds
                else:
                    recording.status = "failed"
                    recording.is_corrupt = True
                    log_tail = _read_log_tail(self._log_path)
                    detail = self._capture_error or "Output file not created"
                    if log_tail:
                        detail = f"{detail} | ffmpeg: {log_tail}"
                    recording.error_message = recording.error_message or detail
                db.commit()

        if not captured:
            try:
                _notify_recording_finished(self.recording_id, self.username, "failed", wall_clock_seconds)
            except Exception:
                logger.debug("Failed to publish recording-finished notification", exc_info=True)
            return

        # --- Finalize: build one seamless MP4 from the captured segment(s) ---
        logger.info(
            "Recording %d: finalizing %d segment(s) into %s",
            self.recording_id, len(segments), output_path.name,
        )
        remux_ok, actual_duration = finalize_segments_to_mp4(segments, output_path)

        # Last-ditch fallback: concat the raw .ts parts and run a full repair.
        if not remux_ok:
            logger.info(
                "Recording %d: segment finalize failed, attempting concat+repair fallback",
                self.recording_id,
            )
            if ts_path is not None and concat_ts_segments(segments, ts_path):
                remux_ok, actual_duration = repair_video(ts_path, output_path=output_path)

        stopped = self._stop_event.is_set()
        final_status: str | None = None

        if remux_ok and output_path.exists() and output_path.stat().st_size > 0:
            # Playable MP4 is in place — clean up all intermediate .ts sources.
            for part in self._segments:
                part.unlink(missing_ok=True)
            self._segments = []
            if ts_path is not None:
                ts_path.unlink(missing_ok=True)

            duration_int = (
                int(round(actual_duration)) if actual_duration else wall_clock_seconds
            )
            with get_session() as db:
                recording = db.query(Recording).filter(Recording.id == self.recording_id).first()
                if recording:
                    recording.file_size = output_path.stat().st_size
                    recording.duration_seconds = duration_int
                    recording.is_corrupt = False
                    recording.status = "stopped" if stopped else "completed"
                    recording.error_message = None
                    db.commit()
                    final_status = recording.status

            # Diagnostic log no longer needed on success.
            if self._log_path is not None:
                self._log_path.unlink(missing_ok=True)

            run_background(generate_thumbnail, output_path, None, self.recording_id)
            run_background(generate_sprite, output_path)
        else:
            # Finalize + repair both failed — keep the .ts/parts so the user can
            # retry via the repair button, and surface a diagnosable failure.
            logger.error(
                "Recording %d: finalize and repair both failed; keeping %d source segment(s)",
                self.recording_id, len(segments),
            )
            log_tail = _read_log_tail(self._log_path)
            detail = "Remux failed — captured stream could not be converted"
            if log_tail:
                detail = f"{detail} | ffmpeg: {log_tail}"
            with get_session() as db:
                recording = db.query(Recording).filter(Recording.id == self.recording_id).first()
                if recording:
                    recording.status = "failed"
                    recording.is_corrupt = True
                    recording.error_message = detail
                    db.commit()
                    final_status = recording.status

        if final_status:
            try:
                _notify_recording_finished(
                    self.recording_id, self.username, final_status,
                    int(actual_duration) if actual_duration else wall_clock_seconds,
                )
            except Exception:
                logger.debug("Failed to publish recording-finished notification", exc_info=True)

    def _run_with_error_handling(self):
        try:
            self._run()
        except Exception as e:
            logger.error(f"Recording error: {e}", exc_info=True)
            _update_recording_status(self.recording_id, "failed", str(e))
        finally:
            self._finalize_recording()


class TaskManager:
    def __init__(self):
        self._tasks: dict[int, RecordingTask] = {}
        self._lock = threading.Lock()
        # Users for whom a recording is being set up right now.
        #
        # The monitor snapshots "who is already recording" once per cycle, then
        # sleeps and makes several network calls per user before inserting the
        # Recording row.  A manual POST /recordings/start landing in that window
        # produced two simultaneous recordings of the same room.  A claim is
        # held across the whole decide-and-insert sequence to close that gap.
        self._starting_users: set[int] = set()

    @contextmanager
    def claim_user(self, user_id: int):
        """Reserve a user for recording setup.

        Yields True if the claim was acquired, False if another caller is
        already starting a recording for this user.  Always releases.
        """
        with self._lock:
            if user_id in self._starting_users:
                acquired = False
            else:
                self._starting_users.add(user_id)
                acquired = True
        try:
            yield acquired
        finally:
            if acquired:
                with self._lock:
                    self._starting_users.discard(user_id)

    
    def start_recording(
        self,
        recording_id: int,
        username: str,
        model_id: str,
        site: str,
        duration: int | None = None,
        proxy: str | None = None
    ) -> bool:
        with self._lock:
            if recording_id in self._tasks:
                return False

            if len(self._tasks) >= settings.MAX_CONCURRENT_RECORDINGS:
                logger.warning(
                    "Refusing to start recording %s for %s: at the concurrency "
                    "limit of %s. Raise MAX_CONCURRENT_RECORDINGS if the host "
                    "can carry more.",
                    recording_id, username, settings.MAX_CONCURRENT_RECORDINGS,
                )
                return False

            task = RecordingTask(
                recording_id=recording_id,
                username=username,
                model_id=model_id,
                site=site,
                duration=duration,
                proxy=proxy
            )
            task.start()
            self._tasks[recording_id] = task
            return True
    
    def stop_recording(self, recording_id: int) -> bool:
        # task.stop() blocks for up to ~25s (ffmpeg drain + thread join), so it
        # must run OUTSIDE the lock.  Holding it here stalled every other
        # caller -- notably get_active_recordings(), which the UI polls every
        # 5 seconds -- for the whole duration of a stop.
        with self._lock:
            task = self._tasks.pop(recording_id, None)
        if task is None:
            return False
        task.stop()
        return True
    
    def is_recording(self, recording_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(recording_id)
            return task is not None and task.is_running()
    
    def get_active_recordings(self) -> list[int]:
        with self._lock:
            return [rid for rid, task in self._tasks.items() if task.is_running()]
    
    def cleanup_finished(self):
        with self._lock:
            finished = [rid for rid, task in self._tasks.items() if not task.is_running()]
            for rid in finished:
                del self._tasks[rid]
    
    def shutdown(self):
        # Same reasoning as stop_recording: drain the registry under the lock,
        # then do the blocking stops without holding it.
        with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            try:
                task.stop()
            except Exception:
                logger.exception("Error stopping task during shutdown")


task_manager = TaskManager()


class MonitorService:
    """Background loop that tracks watchlist room states and auto-records.

    Every ``automatic_interval`` minutes it fetches each site's online list
    once (``bulk_status``), updates every watchlist model's room state, and
    starts a recording for monitored models whose room is in a public show.

    Consecutive status errors for a model trigger exponential backoff before
    its next confirmation (2×, 4×, … up to 60 s).
    """

    # Delay between recording starts / per-model confirmations (seconds)
    _INTER_USER_DELAY = 1.0
    # Exponential-backoff limits
    _BACKOFF_BASE = 2          # first retry waits 2 s
    _BACKOFF_MAX = 60          # never wait more than 60 s per user
    # Brief delay before re-confirming a "public" signal so a single stale
    # list entry can't start a recording on its own.
    _LIVE_CONFIRM_DELAY = 2
    # Circuit breaker: if a user's last N automatic recordings all ended up
    # failed/corrupt within the lookback window, auto-recording is paused for
    # them instead of retrying forever every check interval.
    _CIRCUIT_BREAKER_THRESHOLD = 3
    _CIRCUIT_BREAKER_LOOKBACK_MINUTES = 120
    # Mass-simultaneous-live anomaly guard: if more monitored models than this
    # flip to public in one cycle, treat it as a likely site glitch and use a
    # slower confirmation for the rest of the cycle.
    _MASS_LIVE_ANOMALY_MIN_ABSOLUTE = 5
    _MASS_LIVE_ANOMALY_FRACTION = 0.5

    def __init__(self):
        self._stop_event = threading.Event()
        self._force_check = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_check_at: datetime | None = None
        self._next_check_at: datetime | None = None
        # Per-user consecutive failure count for backoff
        self._check_failures: dict[int, int] = {}
        # Users whose circuit breaker has tripped — only notify once per trip
        self._circuit_notified: set[int] = set()
        # Users already notified about the current private show; cleared when
        # they go offline or back to public.
        self._private_notified: set[int] = set()
        # Last time retention cleanup ran, so it fires about once a day.
        self._last_cleanup_at: datetime | None = None
        # Whether the last cycle hit a site block, for the health endpoint.
        self.last_error: str | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Monitor service started")

    def stop(self):
        self._stop_event.set()
        self._force_check.set()  # Wake the wait immediately
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def trigger_check(self):
        """Request an immediate status check, bypassing the normal interval."""
        self._force_check.set()

    def get_status(self) -> dict:
        now = datetime.utcnow()
        next_check_in: int | None = None
        if self._next_check_at is not None:
            delta = (self._next_check_at - now).total_seconds()
            next_check_in = max(0, int(delta))
        return {
            "is_running": self._thread is not None and self._thread.is_alive(),
            "last_check_at": self._last_check_at.isoformat() if self._last_check_at else None,
            "next_check_in_seconds": next_check_in,
            "interval_minutes": self._interval_seconds() // 60,
            "check_interval": self._interval_seconds(),
            "last_error": self.last_error,
        }

    def _notify_private(self, user) -> None:
        """Tell the user a monitored model is online but in a private show, once per show."""
        if user.id in self._private_notified:
            return
        self._private_notified.add(user.id)
        logger.info("%s is online in a private/non-public show; not recording", user.username)
        try:
            notification_service.publish(
                type="private_show",
                title=f"{user.username} is in a private show",
                message="Only public (free chat) shows are recorded. Recording starts when the room goes public.",
                data={"user_id": user.id, "username": user.username},
            )
        except Exception:
            logger.debug("Failed to publish private-show notification", exc_info=True)

    def _circuit_tripped(self, user_id: int) -> bool:
        """Return True if auto-recording should be paused for *user_id*.

        Trips when the user's last ``_CIRCUIT_BREAKER_THRESHOLD`` automatic
        recordings are all terminal-bad (failed or corrupt) and fall within
        the lookback window — i.e. a rapid-fire loop of bogus recordings
        rather than occasional unlucky failures spread over time.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=self._CIRCUIT_BREAKER_LOOKBACK_MINUTES)
        with get_session() as db:
            recent = (
                db.query(Recording)
                .filter(Recording.user_id == user_id, Recording.mode == "automatic")
                .order_by(Recording.created_at.desc())
                .limit(self._CIRCUIT_BREAKER_THRESHOLD)
                .all()
            )
            if len(recent) < self._CIRCUIT_BREAKER_THRESHOLD:
                return False
            if any(rec.created_at < cutoff for rec in recent):
                return False
            return all(rec.status == "failed" or rec.is_corrupt for rec in recent)

    def _interval_seconds(self) -> int:
        from app.core.settings_store import settings_store
        minutes = settings_store.get("automatic_interval", settings.DEFAULT_AUTOMATIC_INTERVAL)
        try:
            return max(60, int(minutes) * 60)
        except (TypeError, ValueError):
            return settings.DEFAULT_AUTOMATIC_INTERVAL * 60

    def _maybe_run_auto_cleanup(self):
        """Run retention cleanup at most once a day, if it is enabled."""
        from app.core.cleanup_service import cleanup_service

        if not cleanup_service.get_config().get("enabled"):
            return

        now = datetime.utcnow()
        if self._last_cleanup_at is not None and (now - self._last_cleanup_at) < timedelta(days=1):
            return

        # Stamp before running: a failure should not retry every cycle.
        self._last_cleanup_at = now
        try:
            result = cleanup_service.run_cleanup()
            if result.get("deleted") or result.get("compressed"):
                logger.info(
                    "Auto-cleanup: deleted %d, compressed %d",
                    result.get("deleted", 0), result.get("compressed", 0),
                )
        except Exception:
            logger.exception("Auto-cleanup failed")

    def _run(self):
        # Initial short delay so the app finishes starting up.
        if self._stop_event.wait(15):
            return
        while not self._stop_event.is_set():
            self._last_check_at = datetime.utcnow()
            try:
                self._check_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(f"Monitor loop error: {exc}", exc_info=True)
            try:
                self._maybe_run_auto_cleanup()
            except Exception:
                logger.exception("Auto-cleanup scheduling failed")
            interval = self._interval_seconds()
            self._next_check_at = datetime.utcnow() + timedelta(seconds=interval)
            self._force_check.clear()
            # Wait for the interval or a forced check; _stop_event wakes via trigger_check in stop()
            self._force_check.wait(timeout=interval)
            self._force_check.clear()
            if self._stop_event.is_set():
                break

    def _check_once(self):
        from types import SimpleNamespace

        from app.core.settings_store import settings_store
        from app.core.sites import SiteBlockedError
        from app.core.unified_avatar_service import unified_avatar_service

        # --- Phase 0: retry failed avatar fetches ---
        for site, username in unified_avatar_service.get_retryable():
            if self._stop_event.is_set():
                return
            unified_avatar_service.fetch_and_cache(site, username)

        # --- Phase 1: snapshot the watchlist (short session) ---
        with get_session() as db:
            rows = db.query(User).filter(User.is_on_watchlist == True).all()  # noqa: E712
            if not rows:
                return
            users = [
                SimpleNamespace(
                    id=u.id, site=u.site, username=u.username, model_id=u.model_id,
                    display_name=u.display_name, is_live=u.is_live,
                    is_monitoring=u.is_monitoring,
                )
                for u in rows
            ]
            recording_user_ids = {
                rec.user_id
                for rec in db.query(Recording).filter(
                    Recording.status.in_(["pending", "recording"])
                ).all()
            }

        # --- Phase 2: one bulk status call per site (no DB session held) ---
        statuses = {}
        self.last_error = None
        by_site: dict[str, list] = {}
        for u in users:
            by_site.setdefault(u.site, []).append(u)
        for site, site_users in by_site.items():
            try:
                result = site_service.adapter(site).bulk_status([u.username for u in site_users])
            except SiteBlockedError as exc:
                self.last_error = str(exc)
                logger.warning("Site %s blocked the status check: %s", site, exc)
                try:
                    notification_service.publish(
                        type="site_blocked",
                        title=f"{site} is blocking status checks",
                        message=str(exc),
                        data={"site": site},
                    )
                except Exception:
                    pass
                continue
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("Bulk status for %s failed: %s", site, exc)
                continue
            for u in site_users:
                statuses[u.id] = result.get(u.username)

        # --- Phase 3: persist room states ---
        now = datetime.utcnow()
        with get_session() as db:
            for u in users:
                st = statuses.get(u.id)
                if st is None:
                    continue
                row = db.query(User).filter(User.id == u.id).first()
                if not row:
                    continue
                row.room_state = st.state
                row.is_live = st.is_public
                row.last_checked = now
                if st.model_id:
                    row.model_id = st.model_id
                    u.model_id = st.model_id
                if st.display_name and not row.display_name:
                    row.display_name = st.display_name
            db.commit()

        # --- Phase 4: avatars, notifications, recordings ---
        proxy = settings_store.get("proxy", settings.DEFAULT_PROXY)
        max_recording_seconds = max(
            60,
            int(settings_store.get("max_recording_hours", settings.DEFAULT_MAX_RECORDING_HOURS)) * 3600,
        )
        monitored_count = sum(1 for u in users if u.is_monitoring)
        mass_live_anomaly_threshold = max(
            self._MASS_LIVE_ANOMALY_MIN_ABSOLUTE,
            int(monitored_count * self._MASS_LIVE_ANOMALY_FRACTION) + 1,
        )
        confirmed_live_count = 0
        mass_live_anomaly_notified = False

        for user in users:
            if self._stop_event.is_set():
                break
            st = statuses.get(user.id)
            if st is None:
                continue

            if st.error:
                self._check_failures[user.id] = self._check_failures.get(user.id, 0) + 1
            else:
                self._check_failures.pop(user.id, None)

            if (st.avatar_url or st.thumbnail_url) and not unified_avatar_service.has_cached_avatar(user.site, user.username):
                run_background(
                    unified_avatar_service.fetch_and_cache,
                    user.site, user.username, st.avatar_url, st.thumbnail_url,
                )

            if st.state != "private":
                self._private_notified.discard(user.id)

            if not user.is_monitoring or user.id in recording_user_ids:
                continue
            if st.state == "private":
                self._notify_private(user)
                continue
            if not st.is_public or not st.model_id:
                continue

            # --- Circuit breaker ---
            if self._circuit_tripped(user.id):
                if user.id not in self._circuit_notified:
                    self._circuit_notified.add(user.id)
                    logger.warning(
                        "Circuit breaker tripped for %s — pausing auto-recording "
                        "after %d consecutive bad automatic recordings",
                        user.username, self._CIRCUIT_BREAKER_THRESHOLD,
                    )
                    try:
                        notification_service.publish(
                            type="circuit_breaker_tripped",
                            title=f"Auto-recording paused for {user.username}",
                            message=(
                                f"The last {self._CIRCUIT_BREAKER_THRESHOLD} automatic recordings "
                                "failed or came out corrupt. Auto-recording is paused for this model "
                                "until you investigate."
                            ),
                            data={"user_id": user.id, "username": user.username},
                        )
                    except Exception:
                        logger.debug("Failed to publish circuit-breaker notification", exc_info=True)
                continue
            self._circuit_notified.discard(user.id)

            # --- Exponential backoff for users with recent failures ---
            failures = self._check_failures.get(user.id, 0)
            if failures > 0:
                backoff = min(self._BACKOFF_BASE ** failures, self._BACKOFF_MAX)
                if self._stop_event.wait(timeout=backoff):
                    return

            # --- Mass-live anomaly guard ---
            mass_live_anomaly = confirmed_live_count >= mass_live_anomaly_threshold
            if mass_live_anomaly and not mass_live_anomaly_notified:
                mass_live_anomaly_notified = True
                logger.warning(
                    "Mass-live anomaly: %d/%d monitored models reported public in one cycle",
                    confirmed_live_count, monitored_count,
                )
                try:
                    notification_service.publish(
                        type="mass_live_anomaly",
                        title="Unusual number of models went public at once",
                        message=(
                            f"{confirmed_live_count} monitored models came back public in the same "
                            "check cycle. Extra confirmation is being applied."
                        ),
                        data={"confirmed_live_count": confirmed_live_count, "total_monitored": monitored_count},
                    )
                except Exception:
                    logger.debug("Failed to publish mass-live-anomaly notification", exc_info=True)

            # --- Double-confirm against the room itself, then resolve the stream ---
            confirm_delay = self._LIVE_CONFIRM_DELAY * (3 if mass_live_anomaly else 1)
            if self._stop_event.wait(timeout=confirm_delay):
                return
            try:
                confirmed_live = site_service.is_public(st.model_id, user.site)
                if confirmed_live:
                    confirmed_live = bool(site_service.get_live_url(st.model_id, user.site))
            except Exception as e:
                logger.info("Public-room confirmation failed for %s: %s", user.username, e)
                confirmed_live = False

            if not confirmed_live:
                logger.info("Public signal for %s did not hold up on re-check; skipping this cycle", user.username)
                continue

            confirmed_live_count += 1

            # --- Notify on transition, then record ---
            if not user.is_live:
                try:
                    notification_service.publish(
                        type="user_live",
                        title=f"{user.username} is live",
                        message="A monitored model started a public show — recording is starting.",
                        data={"user_id": user.id, "username": user.username},
                    )
                except Exception:
                    logger.debug("Failed to publish user-live notification", exc_info=True)

            # The claim closes the window between the once-per-cycle
            # "already recording" snapshot above and this insert.
            with task_manager.claim_user(user.id) as claimed:
                if not claimed:
                    logger.info("Skipping auto-record for %s: another start is already in flight", user.username)
                    continue

                with get_session() as db:
                    already = (
                        db.query(Recording)
                        .filter(
                            Recording.user_id == user.id,
                            Recording.status.in_(["pending", "recording"]),
                        )
                        .first()
                    )
                    if already is not None:
                        logger.info(
                            "Skipping auto-record for %s: recording %d already active",
                            user.username, already.id,
                        )
                        continue

                    prefix = site_service.adapter(user.site).file_prefix
                    recording = Recording(
                        user_id=user.id,
                        filename=generate_recording_filename(user.username, prefix),
                        status="pending",
                        mode="automatic",
                    )
                    db.add(recording)
                    db.commit()
                    db.refresh(recording)
                    recording_id = recording.id

            started = task_manager.start_recording(
                recording_id=recording_id,
                username=user.username,
                model_id=st.model_id,
                site=user.site,
                duration=max_recording_seconds,
                proxy=proxy,
            )
            if started:
                logger.info("Auto-started recording for %s", user.username)
            else:
                with get_session() as db:
                    rec = db.query(Recording).filter(Recording.id == recording_id).first()
                    if rec:
                        rec.status = "failed"
                        rec.error_message = "Failed to start automatic recording (concurrency limit?)"
                        db.commit()

            if self._stop_event.wait(timeout=self._INTER_USER_DELAY):
                return


monitor_service = MonitorService()
