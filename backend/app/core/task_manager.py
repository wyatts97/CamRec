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
from app.core.recorder_loader import get_tiktok_api_class
from app.core.transcription_service import transcription_service
from app.core.live_chat_service import live_chat_service
from app.core.notification_service import notification_service


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


logger = logging.getLogger("tikrec.task_manager")

# Capture is treated as stalled if the .ts output file does not grow for this
# many seconds while ffmpeg is still running (dead socket with no reconnect).
_STALL_TIMEOUT_SECONDS = 90

# Resumable live capture settings — when a TikTok live URL expires, ffmpeg exits
# and we re-resolve a fresh URL instead of finalizing the recording.
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
_LIVE_RECONFIRM_SECONDS = 300


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
    api: object,
    recorder_service: object,
    max_retries: int = 3,
    backoff_seconds: tuple[int, ...] = (5, 10, 15),
) -> tuple[bool, str | None]:
    """Confirm whether *username* is currently live.

    Performs up to *max_retries* room-alive checks with backoff to tolerate
    transient TikTok API blips. Returns ``(is_live, room_id)``; room_id may be
    updated even if the user is not live.
    """
    for attempt in range(max_retries):
        try:
            status = recorder_service.check_user_live(username)
            is_live = status.get("is_live", False)
            room_id = status.get("room_id")
            if is_live and room_id:
                return True, room_id
            if not is_live and room_id:
                # User not live but we got a room_id — try the room directly
                try:
                    if api.is_room_alive(room_id):
                        return True, room_id
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Live check attempt %d failed for @%s: %s", attempt + 1, username, exc)
        if attempt < max_retries - 1:
            delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            time.sleep(delay)
    return False, None


def _resolve_fresh_live_url(room_id: str, api: object, username: str | None = None) -> str | None:
    """Resolve a fresh live URL for an active room_id.

    TikTok live URLs expire quickly; this re-fetches a brand new URL that can be
    used to start the next segment. Passing *username* lets the recorder fall
    back to scraping the live page directly when TikTok's webcast API returns
    a restricted-access response (status 4003110).
    """
    try:
        if not api.is_room_alive(room_id):
            return None
        url = api.get_live_url(room_id, user=username)
        return url
    except Exception as exc:
        logger.debug("Failed to resolve fresh URL for room %s: %s", room_id, exc)
        return None


def _build_capture_cmd(
    live_url: str,
    ts_path: Path,
    duration: int | None,
    proxy: str | None,
    cookies: dict | None,
) -> list[str]:
    """Build the ffmpeg capture command, wiring proxy/cookies when present.

    ffmpeg consumes the live URL directly (HLS m3u8 or FLV) and writes a single
    continuous MPEG-TS. Proxy and cookies are passed so a geo-restricted stream
    reachable only through the same proxy/session as URL discovery still works.
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
    if cookies:
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items() if k)
        if cookie_header:
            cmd += ["-headers", f"Cookie: {cookie_header}\r\n"]
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
        title = f"Recording completed: @{username}"
        message = f"Recorded {duration_seconds // 60} min"
    elif status == "stopped":
        title = f"Recording stopped: @{username}"
        message = f"Recorded {duration_seconds // 60} min"
    else:  # failed
        title = f"Recording failed: @{username}"
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
        room_id: str,
        duration: int | None = None,
        bitrate: str | None = None,
        cookies: dict | None = None,
        proxy: str | None = None
    ):
        self.recording_id = recording_id
        self.username = username
        self.room_id = room_id
        self.duration = duration
        self.bitrate = bitrate
        self.cookies = cookies
        self.proxy = proxy
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_path: Path | None = None
        self._ts_path: Path | None = None
        self._log_path: Path | None = None
        self._proc: subprocess.Popen | None = None
        self._chat_started_at: datetime = datetime.utcnow()
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
        api_cls = get_tiktok_api_class()
        api = api_cls(proxy=self.proxy, cookies=self.cookies)
        from app.core.recorder_service import recorder_service

        if not api.is_room_alive(self.room_id):
            _update_recording_status(self.recording_id, "failed", "User is not live")
            return

        live_url = api.get_live_url(self.room_id, user=self.username)
        if not live_url:
            _update_recording_status(self.recording_id, "failed", "Could not get live stream URL")
            return

        # Start live chat/gift capture after stream URL is confirmed so that
        # offset_seconds values align with the video start time rather than the
        # earlier status-change time (Phase 1 can precede Phase 3 by 5-30 s).
        self._chat_started_at = datetime.utcnow()
        self._start_chat(self.room_id)

        # --- Phase 3: resumable capture into sequential segments ---
        # TikTok live URLs expire every few minutes. Instead of finalizing the
        # recording when ffmpeg exits, we re-resolve a fresh URL and start a new
        # segment, then concatenate all segments into one continuous file at
        # finalize time. This keeps one live session as one recording.
        output_path = recording_path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path = output_path
        self._ts_path = output_path.with_suffix(".ts")
        self._log_path = output_path.with_suffix(".ffmpeg.log")
        self._start_time = time.time()

        room_id = self.room_id
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

            cmd = _build_capture_cmd(live_url, segment_path, segment_remaining, self.proxy, self.cookies)
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

                # Independent liveness re-check: catches a stream that keeps
                # producing bytes (e.g. stale/looping placeholder) even though
                # the room has actually gone offline — the stall detector above
                # can't see this since the file is still growing.
                if now - last_live_reconfirm > _LIVE_RECONFIRM_SECONDS:
                    last_live_reconfirm = now
                    try:
                        still_alive = api.is_room_alive(room_id)
                    except Exception:
                        still_alive = True  # network blip — don't kill a good recording
                    if not still_alive:
                        logger.warning(
                            "Recording %d: room %s no longer alive on re-check; ending session",
                            self.recording_id, room_id,
                        )
                        self._capture_error = "Room confirmed offline during periodic re-check"
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
                    # A long, clean segment ending is almost always the signed
                    # URL expiring (~every 30 min), not the broadcast ending.
                    # Reset the counter so backoff doesn't grow across a long
                    # session, and try a fresh URL straight away: every second
                    # spent here is a second missing from the recording.
                    resume_attempts = 0
                    fresh_url = _resolve_fresh_live_url(room_id, api, self.username)
                    if fresh_url:
                        live_url = fresh_url
                        resumed = True
                        logger.info(
                            "Recording %d: segment ended after %ds; fast-resuming with fresh URL (room %s)",
                            self.recording_id, int(time.time() - segment_started), room_id,
                        )
                        self._start_chat(room_id, resumed=True)
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

                is_live, fresh_room_id = _check_live_with_backoff(
                    self.username,
                    api,
                    recorder_service,
                    max_retries=3,
                    backoff_seconds=(10, 20, _OFFLINE_CONFIRMATION_SECONDS // 3),
                )
                if not is_live or not fresh_room_id:
                    logger.info(
                        "Recording %d: user @%s confirmed offline, finalizing session",
                        self.recording_id, self.username,
                    )
                    break

                # User is still live — refresh the URL and resume.
                fresh_url = _resolve_fresh_live_url(fresh_room_id, api, self.username)
                if not fresh_url:
                    logger.warning(
                        "Recording %d: user still live but could not resolve fresh URL; retrying",
                        self.recording_id,
                    )
                    continue
                room_id = fresh_room_id
                live_url = fresh_url
                resumed = True
                logger.info(
                    "Recording %d: resuming session with fresh URL (room %s)",
                    self.recording_id, room_id,
                )
                self._start_chat(room_id, resumed=True)
            else:
                # This path should be unreachable; treat as session end to be safe.
                break

        self._total_elapsed_seconds = time.time() - self._start_time
        self._finalize_recording()

    def _start_chat(self, room_id: str, resumed: bool = False) -> None:
        """Start chat capture, or restart it if the previous listener died.

        Offsets stay relative to the original ``_chat_started_at`` so events
        captured after a resume still line up with the stitched video.
        """
        if resumed and live_chat_service.is_listening(self.recording_id):
            return
        try:
            started = live_chat_service.start_listening(
                recording_id=self.recording_id,
                username=self.username,
                room_id=room_id,
                started_at=self._chat_started_at,
                proxy=self.proxy,
                cookies=self.cookies,
            )
        except Exception as e:
            logger.warning("Failed to start chat capture for recording %d: %s", self.recording_id, e)
            return
        if started and resumed:
            logger.info("Recording %d: restarted chat capture after resume", self.recording_id)
        elif not started and not resumed:
            # Refused (the MAX_WORKERS cap). The recording proceeds either
            # way, but say so loudly: otherwise the missing chat only shows
            # up as an empty timeline later.
            logger.warning(
                "Chat capture NOT started for recording %d (@%s) - no chat or "
                "gift events will be captured for this recording",
                self.recording_id,
                self.username,
            )

    def _finalize_recording(self) -> None:
        """Finalize a recording: flush file, update DB, stop chat, remux, thumbnails.
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
            try:
                live_chat_service.stop_listening(self.recording_id)
            except Exception:
                pass
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

        # Stop live chat/gift capture regardless of outcome.
        try:
            live_chat_service.stop_listening(self.recording_id)
        except Exception:
            pass

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
                    if recording.transcript_status is None:
                        recording.transcript_status = "pending"
                    db.commit()
                    final_status = recording.status

            # Diagnostic log no longer needed on success.
            if self._log_path is not None:
                self._log_path.unlink(missing_ok=True)

            run_background(generate_thumbnail, output_path, None, self.recording_id)
            run_background(generate_sprite, output_path)
            transcription_service.enqueue(self.recording_id)
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
        room_id: str,
        duration: int | None = None,
        bitrate: str | None = None,
        cookies: dict | None = None,
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
                room_id=room_id,
                duration=duration,
                bitrate=bitrate,
                cookies=cookies,
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
    """Background loop that auto-records watched users when they go live.

    Every ``automatic_interval`` minutes it checks each user flagged with
    ``is_monitoring`` and, if live and not already recording, starts a recording.

    Rate-limiting: a 1.5 s delay is inserted between each user check to
    avoid triggering TikTok's rate limiter.  Consecutive failures for a user
    trigger exponential backoff (2×, 4×, … up to 60 s).
    """

    # Delay between individual user checks (seconds)
    _INTER_USER_DELAY = 1.5
    # How long to skip re-checking a room that TikTok says is private.
    _PRIVATE_LIVE_BACKOFF = 900
    # Exponential-backoff limits
    _BACKOFF_BASE = 2          # first retry waits 2 s
    _BACKOFF_MAX = 60          # never wait more than 60 s per user
    # Brief delay before re-confirming a "live" signal so a single flickering
    # API response can't start a recording on its own.
    _LIVE_CONFIRM_DELAY = 3
    # Circuit breaker: if a user's last N automatic recordings all ended up
    # failed/corrupt within the lookback window, auto-recording is paused for
    # them instead of retrying forever every check interval.
    _CIRCUIT_BREAKER_THRESHOLD = 3
    _CIRCUIT_BREAKER_LOOKBACK_MINUTES = 120
    # Mass-simultaneous-live anomaly guard: a real TikTok event where many
    # watched creators go live in the same check cycle is possible but rare.
    # If more users than this trip "live" in one cycle, treat it as a likely
    # systemic API glitch and require a stricter, slower confirmation for the
    # rest of the cycle instead of blindly trusting the signal.
    _MASS_LIVE_ANOMALY_MIN_ABSOLUTE = 3
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
        # user_id -> (room_id, monotonic deadline). A live that needs a login
        # fails the stream-URL check identically every cycle, so after the
        # first failure the same room is not re-probed until the deadline.
        self._private_rooms: dict[int, tuple[str, float]] = {}
        # Last time retention cleanup ran, so it fires about once a day.
        self._last_cleanup_at: datetime | None = None

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
        }

    def _mark_private_live(self, user, room_id: str) -> None:
        """Record that *user*'s live in *room_id* needs a login, notifying once per room."""
        previous = self._private_rooms.get(user.id)
        self._private_rooms[user.id] = (room_id, time.monotonic() + self._PRIVATE_LIVE_BACKOFF)
        if previous is not None and previous[0] == room_id:
            return
        logger.warning(
            "@%s is live in a private room (%s) that requires login cookies; "
            "re-checking in %d min",
            user.username, room_id, self._PRIVATE_LIVE_BACKOFF // 60,
        )
        try:
            notification_service.publish(
                type="private_live",
                title=f"@{user.username} is live, but the stream is private",
                message=(
                    "TikTok only lets logged-in viewers with access watch this live, so it "
                    "can't be recorded. If it's followers- or subscribers-only, the account "
                    "in your Settings cookies needs that access."
                ),
                data={"user_id": user.id, "username": user.username, "room_id": room_id},
            )
        except Exception:
            logger.debug("Failed to publish private-live notification", exc_info=True)

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
        """Run retention cleanup at most once a day, if it is enabled.

        The auto-cleanup toggle has always been surfaced in the UI and honoured
        by CleanupService, but nothing ever called it outside the manual
        "Run now" button -- so enabling it silently did nothing.
        """
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
        from app.core.recorder_service import recorder_service
        from app.core.settings_store import settings_store
        from app.core.unified_avatar_service import unified_avatar_service

        if not recorder_service.is_available():
            return

        # --- Phase 0: retry failed avatar fetches ---
        retryable = unified_avatar_service.get_retryable_usernames()
        if retryable:
            logger.info(f"Retrying avatar fetch for {len(retryable)} users")
            for username in retryable:
                if self._stop_event.is_set():
                    return
                unified_avatar_service.fetch_and_cache(username)
                if self._stop_event.wait(timeout=1.5):
                    return

        # --- Phase 1: fetch monitored users and active recordings (short session) ---
        with get_session() as db:
            monitored = db.query(User).filter(
                User.is_monitoring == True,  # noqa: E712
                User.is_on_watchlist == True,  # noqa: E712
            ).all()
            if not monitored:
                return

            recording_user_ids = {
                rec.user_id
                for rec in db.query(Recording).filter(
                    Recording.status.in_(["pending", "recording"])
                ).all()
            }

        cookies = recorder_service.load_cookies()
        proxy = settings_store.get("proxy", settings.DEFAULT_PROXY)
        bitrate = settings_store.get("default_bitrate", settings.DEFAULT_BITRATE)
        max_recording_seconds = max(
            60,
            int(settings_store.get("max_recording_hours", settings.DEFAULT_MAX_RECORDING_HOURS)) * 3600,
        )
        mass_live_anomaly_threshold = max(
            self._MASS_LIVE_ANOMALY_MIN_ABSOLUTE,
            (len(monitored) + 1) // 2,
        )
        confirmed_live_count = 0
        mass_live_anomaly_notified = False

        for user in monitored:
            if self._stop_event.is_set():
                break
            if user.id in recording_user_ids:
                continue

            # --- Circuit breaker: stop hammering a user whose last several
            # automatic recordings all came back bad in a short window ---
            if self._circuit_tripped(user.id):
                if user.id not in self._circuit_notified:
                    self._circuit_notified.add(user.id)
                    logger.warning(
                        "Circuit breaker tripped for @%s — pausing auto-recording "
                        "after %d consecutive bad automatic recordings",
                        user.username, self._CIRCUIT_BREAKER_THRESHOLD,
                    )
                    try:
                        notification_service.publish(
                            type="circuit_breaker_tripped",
                            title=f"Auto-recording paused for @{user.username}",
                            message=(
                                f"The last {self._CIRCUIT_BREAKER_THRESHOLD} automatic recordings "
                                "failed or came out corrupt. Auto-recording is paused for this user "
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
                logger.debug("Backoff %d s for @%s (%d consecutive failures)",
                             backoff, user.username, failures)
                if self._stop_event.wait(timeout=backoff):
                    return

            # --- Network calls happen with NO DB session held ---
            status_info = recorder_service.check_user_live(user.username)
            is_live = status_info.get("is_live", False)
            room_id = status_info.get("room_id")
            last_checked = datetime.utcnow()

            # --- Update failure counter / log success ---
            if status_info.get("error"):
                self._check_failures[user.id] = failures + 1
            else:
                self._check_failures.pop(user.id, None)

            if not is_live or not room_id:
                self._private_rooms.pop(user.id, None)
                # --- Update user status (short session) ---
                with get_session() as db:
                    u = db.query(User).filter(User.id == user.id).first()
                    if u:
                        u.is_live = is_live
                        u.room_id = room_id
                        u.last_checked = last_checked
                        db.commit()
                # Rate-limiting delay between users
                if self._stop_event.wait(timeout=self._INTER_USER_DELAY):
                    return
                continue

            # --- Known private live in the same room: skip the confirmation
            # round-trips until the backoff expires or the room changes. ---
            private = self._private_rooms.get(user.id)
            if private is not None:
                if private[0] == room_id and time.monotonic() < private[1]:
                    if self._stop_event.wait(timeout=self._INTER_USER_DELAY):
                        return
                    continue
                if private[0] != room_id:
                    self._private_rooms.pop(user.id, None)

            # --- Mass-simultaneous-live anomaly guard: if an unusually large
            # share of the watchlist has already come back "live" this cycle,
            # a systemic API glitch is more likely than a real coincidence —
            # slow down and demand stricter confirmation for the rest of the
            # cycle instead of trusting the signal outright. ---
            mass_live_anomaly = confirmed_live_count >= mass_live_anomaly_threshold
            if mass_live_anomaly and not mass_live_anomaly_notified:
                mass_live_anomaly_notified = True
                logger.warning(
                    "Mass-live anomaly: %d/%d monitored users reported live in one "
                    "check cycle — treating remaining live signals with extra scrutiny",
                    confirmed_live_count, len(monitored),
                )
                try:
                    notification_service.publish(
                        type="mass_live_anomaly",
                        title="Unusual number of users reported live at once",
                        message=(
                            f"{confirmed_live_count} monitored users came back live in the same "
                            "check cycle. This is more likely a false-positive from the TikTok "
                            "API than a real coincidence — extra confirmation is being applied."
                        ),
                        data={"confirmed_live_count": confirmed_live_count, "total_monitored": len(monitored)},
                    )
                except Exception:
                    logger.debug("Failed to publish mass-live-anomaly notification", exc_info=True)

            # --- Double-confirm before starting a recording: a brief pause and
            # a second independent check filters out a single flickering/stale
            # "live" response from the recorder API so it can't spawn a bogus
            # recording on its own. During a mass-live anomaly, wait longer to
            # give a transient API glitch more time to clear. ---
            confirm_delay = self._LIVE_CONFIRM_DELAY * (3 if mass_live_anomaly else 1)
            if self._stop_event.wait(timeout=confirm_delay):
                return
            try:
                confirmed_live = recorder_service.get_api().is_room_alive(room_id)
            except Exception:
                confirmed_live = False

            # --- Independent verification: hit a *different* upstream code
            # path (webcast/room/info stream extraction) than check_alive, so
            # a bug in one check is unlikely to also be wrong in the other.
            # This is required outright during a mass-live anomaly, and used
            # as a normal second opinion otherwise. ---
            if confirmed_live:
                try:
                    live_url = recorder_service.get_live_url(room_id, username=user.username)
                    confirmed_live = bool(live_url)
                except Exception as e:
                    confirmed_live = False
                    if "private" in str(e).lower():
                        self._mark_private_live(user, room_id)
                    else:
                        logger.info(
                            "Independent stream-URL check failed for @%s: %s", user.username, e,
                        )

            if not confirmed_live:
                logger.info(
                    "Live signal for @%s did not hold up on re-check; skipping this cycle",
                    user.username,
                )
                with get_session() as db:
                    u = db.query(User).filter(User.id == user.id).first()
                    if u:
                        u.is_live = False
                        u.room_id = room_id
                        u.last_checked = last_checked
                        db.commit()
                if self._stop_event.wait(timeout=self._INTER_USER_DELAY):
                    return
                continue

            confirmed_live_count += 1

            # --- User is live: notify on transition, then record ---
            if not user.is_live:
                try:
                    notification_service.publish(
                        type="user_live",
                        title=f"@{user.username} is live",
                        message="A monitored user just went live — recording is starting.",
                        data={"user_id": user.id, "username": user.username},
                    )
                except Exception:
                    logger.debug("Failed to publish user-live notification", exc_info=True)

            # --- update user and create recording (short session) ---
            # The claim closes the window between the once-per-cycle
            # "already recording" snapshot above and this insert.
            with task_manager.claim_user(user.id) as claimed:
                if not claimed:
                    logger.info(
                        "Skipping auto-record for @%s: another start is already in flight",
                        user.username,
                    )
                    continue

                # Re-check under the claim -- the snapshot is now stale by
                # several seconds of network calls and sleeps.
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
                        "Skipping auto-record for @%s: recording %d already active",
                        user.username, already.id,
                    )
                    continue

                filename = generate_recording_filename(user.username)
                with get_session() as db:
                    u = db.query(User).filter(User.id == user.id).first()
                    if u:
                        u.is_live = True
                        u.room_id = room_id
                        u.last_checked = last_checked
                    recording = Recording(
                        user_id=user.id,
                        filename=filename,
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
                room_id=room_id,
                duration=max_recording_seconds,
                cookies=cookies,
                proxy=proxy,
                bitrate=bitrate,
            )
            if started:
                logger.info(f"Auto-started recording for @{user.username}")
            else:
                # --- Mark recording as failed (short session) ---
                with get_session() as db:
                    rec = db.query(Recording).filter(Recording.id == recording_id).first()
                    if rec:
                        rec.status = "failed"
                        rec.error_message = "Failed to start automatic recording"
                        db.commit()

            # Rate-limiting delay between users
            if self._stop_event.wait(timeout=self._INTER_USER_DELAY):
                return


monitor_service = MonitorService()
