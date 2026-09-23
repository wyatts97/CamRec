"""Shared media processing utilities for CamSuite.

Consolidates thumbnail generation, sprite sheet generation, video remuxing,
corruption repair, and health checks that were previously duplicated across
task_manager.py and recordings.py.

Every function takes an explicit ``video_path`` argument rather than a
recording ID, keeping this module free of route-layer concerns.
"""
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger("camsuite.media_utils")


# ----------------------------------------------------------------
# Clip helpers
# ----------------------------------------------------------------

def clip_directory() -> Path:
    """Return the directory for storing clip files."""
    return Path(settings.RECORDINGS_DIR) / "clips"


def create_clip(video_path: Path, start: int, end: int, output_path: Path) -> bool:
    """Extract a segment from *video_path* using ffmpeg.

    Tries stream-copy first (fast, lossless) and falls back to a
    full re-encode if the copy produces an empty or unreadable file.
    """
    if not video_path.exists():
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start

    # Strategy 1 — stream copy (fast, preserves quality)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-t", str(duration),
                "-i", str(video_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            check=True,
            timeout=180,
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            # Sanity-check the output is playable
            health = analyze_video_health(output_path)
            if not health.get("is_corrupt"):
                logger.info("Clip created (stream copy): %s", output_path.name)
                return True
    except Exception:
        logger.warning("Stream-copy clip failed for %s, trying re-encode", video_path)
    finally:
        if output_path.exists() and output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)

    # Strategy 2 — re-encode (slower but more robust)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-t", str(duration),
                "-i", str(video_path),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            check=True,
            timeout=300,
        )
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.info("Clip created (re-encode): %s", output_path.name)
            return True
    except Exception:
        logger.error("Re-encode clip also failed for %s", video_path)

    if output_path.exists():
        output_path.unlink(missing_ok=True)
    return False


class UnsafePathError(ValueError):
    """Raised when a stored filename would resolve outside its base directory."""


def resolve_within(base: Path, filename: str) -> Path:
    """Join ``filename`` onto ``base`` and prove the result stays inside it.

    Filenames are generated from model usernames and user-supplied clip
    titles.  Both are validated on the way in, but this is the last line of
    defence for rows written before those constraints existed -- a filename
    containing ``..`` or an absolute path must never escape the media root.
    """
    base_resolved = Path(base).resolve()
    candidate = (base_resolved / filename).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise UnsafePathError(f"Refusing to access {filename!r} outside {base_resolved}")
    return candidate


def recording_path(filename: str) -> Path:
    """Absolute path to a recording, guaranteed to sit inside RECORDINGS_DIR."""
    return resolve_within(settings.RECORDINGS_DIR, filename)


def generate_recording_filename(username: str, prefix: str = "F4F") -> str:
    """Build a standardised filename for a recorded live cam stream.

    Format: ``{PREFIX}_{username}_{YYYY.MM.DD_HH-MM-SS}.mp4`` (prefix per site, e.g. ``F4F``).
    """
    return f"{prefix}_{username}_{time.strftime('%Y.%m.%d_%H-%M-%S', time.localtime())}.mp4"


# ----------------------------------------------------------------
# Sprite generation — at most 2 concurrent invocations
# ----------------------------------------------------------------
_sprite_sem = threading.Semaphore(2)

# Thumbnail generation — at most 2 concurrent invocations. Without this,
# a Watch/Clips grid with many not-yet-ready thumbnails can fire a burst of
# concurrent ffmpeg processes (one per on-demand HTTP request), thrashing
# CPU and making every request in the burst slower than if they ran
# serially a few at a time.
_thumbnail_sem = threading.Semaphore(2)

# Cached probe for whether this ffmpeg build supports WebP encoding
# (libwebp). Debian's official `ffmpeg` apt package — used in the runtime
# image — is built with --enable-libwebp, but we still probe defensively
# and fall back to JPEG so this never hard-fails on a stripped-down build.
_webp_supported: bool | None = None
_webp_probe_lock = threading.Lock()


def _ffmpeg_supports_webp() -> bool:
    global _webp_supported
    if _webp_supported is not None:
        return _webp_supported
    with _webp_probe_lock:
        if _webp_supported is not None:
            return _webp_supported
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _webp_supported = "libwebp" in (result.stdout or "")
        except Exception:
            _webp_supported = False
    return _webp_supported


# ----------------------------------------------------------------
# Thumbnail helpers
# ----------------------------------------------------------------

def thumbnail_path(video_path: Path) -> Path:
    """Return the expected filesystem path for a video's thumbnail image.

    Prefers WebP (smaller, faster to decode over the wire) when the
    ffmpeg build supports it, falling back to JPEG otherwise. Existing
    ``_thumb.jpg`` files from before WebP support keep working (their
    ``thumbnail_ready`` DB flag is trusted as-is); they simply get replaced
    by a ``_thumb.webp`` the next time they need to be (re)generated.
    """
    ext = "webp" if _ffmpeg_supports_webp() else "jpg"
    return video_path.with_suffix("").with_name(f"{video_path.stem}_thumb.{ext}")


def thumbnail_media_type(thumb_path: Path) -> str:
    """Return the correct Content-Type for a thumbnail path's extension."""
    return "image/webp" if thumb_path.suffix.lower() == ".webp" else "image/jpeg"


def all_thumbnail_paths(video_path: Path) -> list[Path]:
    """Return every extension a thumbnail for *video_path* could exist under.

    Since :func:`thumbnail_path` picks WebP or JPEG based on the current
    ffmpeg build, a recording's on-disk thumbnail may be a leftover
    ``.jpg`` from before WebP support was added. Callers that need to find
    or delete "the" thumbnail regardless of which format produced it
    (e.g. cleanup on recording delete) should check all of these.
    """
    stem = video_path.stem
    return [
        video_path.with_name(f"{stem}_thumb.webp"),
        video_path.with_name(f"{stem}_thumb.jpg"),
    ]


def generate_thumbnail(
    video_path: Path,
    thumb_path: Path | None = None,
    recording_id: int | None = None,
    quick: bool = False,
) -> bool:
    """Extract a single thumbnail frame from *video_path* (WebP or JPEG).

    If *thumb_path* is not provided it is derived from *video_path* via
    :func:`thumbnail_path`.

    Tries several seek positions (1s, 0.5s, 2s, 0s) to handle very short
    or oddly-structured videos. Pass ``quick=True`` to only attempt the
    first seek position with a short timeout — intended for synchronous,
    request-blocking call sites (e.g. an on-demand HTTP fallback) where a
    slow multi-attempt retry would stall the response; callers should kick
    off a normal (non-quick) background retry separately in that case.

    Returns ``True`` when a non-empty image was written, ``False`` otherwise.
    """
    if not video_path.exists():
        return False

    thumb = thumb_path or thumbnail_path(video_path)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    is_webp = thumb.suffix.lower() == ".webp"

    seek_positions = ["1"] if quick else ["1", "0.5", "2", "0"]
    timeout = 8 if quick else 30
    success = False

    with _thumbnail_sem:
        for seek_time in seek_positions:
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", seek_time,
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-vf", "scale=480:-2",
                ]
                if is_webp:
                    cmd += ["-c:v", "libwebp", "-lossless", "0", "-quality", "80"]
                cmd.append(str(thumb))
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout,
                )
                if thumb.exists() and thumb.stat().st_size > 0:
                    success = True
                    break
            except Exception as exc:
                logger.warning("Thumbnail seek=%s failed for %s: %s",
                               seek_time, video_path, exc)
                continue

    if success and recording_id is not None:
        try:
            from app.db.database import get_session
            from app.db.models import Recording
            with get_session() as db:
                rec = db.query(Recording).filter(Recording.id == recording_id).first()
                if rec:
                    rec.thumbnail_ready = True
                    db.commit()
        except Exception as db_exc:
            logger.warning("Failed to persist thumbnail_ready for %s: %s",
                           video_path, db_exc)

    return success


def concat_ts_segments(segment_paths: list[Path], output_path: Path) -> bool:
    """Concatenate MPEG-TS segments into a single TS file.

    Uses ffmpeg's concat demuxer with stream copy so the result is a lossless
    join of the individual segments. The input list order is preserved.

    Returns ``True`` if the output file was created and non-empty.
    """
    if not segment_paths:
        return False
    segment_paths = [p for p in segment_paths if p.exists() and p.stat().st_size > 0]
    if not segment_paths:
        return False
    if len(segment_paths) == 1:
        try:
            import shutil
            shutil.copy2(segment_paths[0], output_path)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False

    concat_list = output_path.with_suffix(".concat.txt")
    try:
        concat_list.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in segment_paths),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                "-fflags", "+igndts+genpts",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                "-f", "mpegts",
                str(output_path),
            ],
            capture_output=True,
            check=True,
            timeout=300,
        )
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception as exc:
        logger.warning("Segment concat failed for %s: %s", output_path.name, exc)
        return False
    finally:
        concat_list.unlink(missing_ok=True)


# ----------------------------------------------------------------
# Sprite / hover-scrub helpers
# ----------------------------------------------------------------

def _fmt_vtt_time(seconds: float) -> str:
    """Format *seconds* as ``HH:MM:SS.mmm`` for WebVTT timestamps."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


SPRITE_THUMB_W = 160
SPRITE_THUMB_H = 90
SPRITE_COLS = 10
SPRITE_MAX_FRAMES = 300
SPRITE_MIN_INTERVAL = 2.0
SPRITE_MAX_INTERVAL = 30.0
SPRITE_GRAB_WORKERS = 4
# Bumped whenever the sprite/VTT format changes; older VTTs are regenerated
# lazily when a player asks for them (see sprite_vtt_version).
SPRITE_VERSION = 2
_SPRITE_VERSION_MARKER = "NOTE tikrec-sprite v"


def sprite_paths(video_path: Path) -> tuple[Path, Path]:
    """Return ``(sprite_jpg, sprite_vtt)`` paths for a video."""
    return (
        video_path.with_name(video_path.stem + "_sprite.jpg"),
        video_path.with_name(video_path.stem + "_sprite.vtt"),
    )


def sprite_vtt_version(vtt_path: Path) -> int:
    """Return the sprite format version recorded in a VTT (1 if unmarked, 0 if unreadable)."""
    try:
        with open(vtt_path, "r", encoding="utf-8") as fh:
            head = fh.read(200)
    except OSError:
        return 0
    idx = head.find(_SPRITE_VERSION_MARKER)
    if idx == -1:
        return 1
    digits = ""
    for ch in head[idx + len(_SPRITE_VERSION_MARKER):]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else 1


def render_sprite_vtt(video_path: Path, sprite_url: str) -> tuple[str, str] | None:
    """Return ``(vtt_content, etag)`` for serving a video's sprite map, or None.

    Sprite references become ``<sprite_url>?v=<sprite mtime>`` so the sheet can
    be cached as immutable: regenerating it changes the URL. The ETag covers
    both files, so a revalidating client picks up either changing.
    """
    sprite_path, vtt_path = sprite_paths(video_path)
    try:
        vtt_stat = vtt_path.stat()
        sprite_stat = sprite_path.stat()
        content = vtt_path.read_text(encoding="utf-8")
    except OSError:
        return None
    version = sprite_stat.st_mtime_ns
    content = content.replace("sprite#xywh=", f"{sprite_url}?v={version}#xywh=")
    etag = f'"{vtt_stat.st_mtime_ns}-{vtt_stat.st_size}-{version}"'
    return content, etag


def sprite_interval(duration: float) -> float:
    """Seconds between sprite frames: about 300 frames, clamped to 2-30 s."""
    return min(SPRITE_MAX_INTERVAL, max(SPRITE_MIN_INTERVAL, duration / SPRITE_MAX_FRAMES))


def build_sprite_vtt(
    timestamps: list[float],
    duration: float,
    cols: int = SPRITE_COLS,
    thumb_w: int = SPRITE_THUMB_W,
    thumb_h: int = SPRITE_THUMB_H,
) -> str:
    """Build the WebVTT map for a sprite sheet.

    *timestamps* are the real capture times of the tiles, in tile order. Each
    cue runs from its frame's time to the next frame's time (the last one to
    *duration*), so the cues cover the whole video with no gaps, and a frame
    that failed to extract can never shift later frames onto the wrong times.
    """
    lines = ["WEBVTT", "", f"{_SPRITE_VERSION_MARKER}{SPRITE_VERSION}", ""]
    for i, start in enumerate(timestamps):
        # The first cue starts at 0 so the very beginning always has a preview
        # even when the first successful grab landed later.
        start = 0.0 if i == 0 else start
        end = timestamps[i + 1] if i + 1 < len(timestamps) else max(duration, start + 0.001)
        col, row = i % cols, i // cols
        lines.append(f"{_fmt_vtt_time(start)} --> {_fmt_vtt_time(end)}")
        lines.append(f"sprite#xywh={col * thumb_w},{row * thumb_h},{thumb_w},{thumb_h}")
        lines.append("")
    return "\n".join(lines)


def _grab_sprite_frame(video_path: Path, timestamp: float, out_path: Path) -> bool:
    """Extract one scaled frame at *timestamp*. Returns True on success.

    ``-ss`` before ``-i`` seeks quickly to the preceding keyframe, then ffmpeg
    decodes forward to the exact time, so the frame matches its cue.
    """
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-nostdin", "-hide_banner", "-loglevel", "error",
                "-ss", f"{timestamp:.3f}",
                "-i", str(video_path),
                "-frames:v", "1",
                "-vf", f"scale={SPRITE_THUMB_W}:{SPRITE_THUMB_H}",
                "-an", "-sn", "-dn",
                str(out_path),
            ],
            capture_output=True,
            timeout=20,
            check=True,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def generate_sprite(video_path: Path) -> tuple[Path | None, Path | None]:
    """Generate a sprite sheet and WebVTT file for hover-scrub preview.

    Also persists ``sprite_ready = True`` on the corresponding
    ``Recording`` row so the API doesn't re-check the filesystem on
    every request.

    Returns ``(sprite_path, vtt_path)`` on success or ``(None, None)``
    on failure.

    **Locking:** a module-level semaphore limits concurrent sprite
    generation to 2 invocations; each runs a few frame grabs in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor

    sprite_path, vtt_path = sprite_paths(video_path)

    with _sprite_sem:
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True, text=True, timeout=15,
            )
            duration = float(probe.stdout.strip())

            interval = sprite_interval(duration)
            # Stop short of the very end: a seek to the last instant fails.
            targets: list[float] = []
            t = 0.0
            while t < duration - 0.25 and len(targets) < SPRITE_MAX_FRAMES:
                targets.append(round(t, 3))
                t += interval
            if not targets:
                targets = [0.0]

            temp_dir = tempfile.mkdtemp(prefix="sprite_frames_")
            try:
                raw = [Path(temp_dir) / f"raw_{i:04d}.jpg" for i in range(len(targets))]
                with ThreadPoolExecutor(max_workers=SPRITE_GRAB_WORKERS) as pool:
                    ok = list(pool.map(
                        lambda pair: _grab_sprite_frame(video_path, pair[0], pair[1]),
                        zip(targets, raw),
                    ))

                # Keep each surviving frame paired with the time it was taken,
                # so a failed grab leaves a longer cue instead of shifting
                # every later frame onto the wrong time.
                frames = [(ts, path) for ts, path, good in zip(targets, raw, ok) if good]
                if not frames:
                    return None, None

                for idx, (_, src) in enumerate(frames):
                    src.rename(Path(temp_dir) / f"frame_{idx:04d}.jpg")

                frame_count = len(frames)
                rows = (frame_count + SPRITE_COLS - 1) // SPRITE_COLS

                tile_result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-nostdin", "-hide_banner", "-loglevel", "error",
                        "-i", str(Path(temp_dir) / "frame_%04d.jpg"),
                        "-vf", f"tile={SPRITE_COLS}x{rows}",
                        "-q:v", "5",
                        str(sprite_path),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if tile_result.returncode != 0:
                    logger.warning(
                        "Sprite tiling failed for %s: %s",
                        video_path,
                        tile_result.stderr.decode("utf-8", errors="replace")[:200],
                    )
                    return None, None

                if not sprite_path.exists() or sprite_path.stat().st_size == 0:
                    return None, None

                vtt_path.write_text(
                    build_sprite_vtt([ts for ts, _ in frames], duration),
                    encoding="utf-8",
                )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            # Persist sprite_ready flag in DB
            try:
                from app.db.database import get_session
                from app.db.models import Recording
                with get_session() as db:
                    rec = db.query(Recording).filter(
                        Recording.filename == video_path.name
                    ).first()
                    if rec:
                        rec.sprite_ready = True
                        db.commit()
            except Exception as db_exc:
                logger.warning("Failed to persist sprite_ready for %s: %s",
                               video_path, db_exc)

            logger.info(
                "Sprite generated for %s: %d/%d frames (%dx%d) @ %.1fs interval",
                video_path.name, frame_count, len(targets), SPRITE_COLS, rows, interval,
            )
            return sprite_path, vtt_path

        except Exception as exc:
            logger.warning("Sprite generation failed for %s: %s", video_path, exc)
            return None, None


# ----------------------------------------------------------------
# Remuxing
# ----------------------------------------------------------------

def _probe_duration(video_path: Path) -> float | None:
    """Return the duration of *video_path* in seconds, or ``None``.

    First tries the container's ``format.duration``. If that is missing (common
    for MPEG-TS files before remux), it falls back to the last packet timestamp
    so callers still get a usable duration estimate without misclassifying a
    healthy stream as corrupt.
    """
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        value = probe.stdout.strip()
        if value:
            duration = float(value)
            if duration > 0:
                return duration
    except Exception:
        pass

    # Fallback: estimate duration from the last video packet timestamp.
    # This is slower but necessary for containers without a global duration.
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "packet=pts_time",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        timestamps = [float(line.strip()) for line in probe.stdout.splitlines() if line.strip()]
        if timestamps:
            max_ts = max(timestamps)
            if max_ts > 0:
                return max_ts
    except Exception:
        pass

    return None


def remux_to_mp4(
    input_path: Path,
    expected_duration: float | None = None,
    output_path: Path | None = None,
) -> tuple[bool, float | None]:
    """Remux a captured stream to a faststart MP4 for browser seeking.

    Uses error-tolerant ffmpeg flags to handle mid-stream codec switches
    common in live stream recordings. Falls back to a full re-encode if
    the stream-copy remux encounters corrupt frames or if the resulting
    duration diverges from *expected_duration* by >5 %% or >30 s.

    When *output_path* is given the remuxed MP4 is written there (the
    typical flow: ``.ts`` source → ``.mp4`` output); otherwise *input_path*
    is replaced in-place.

    Note: no explicit ``h264_mp4toannexb`` bitstream filter is used — when
    copying H.264 from MPEG-TS/FLV into MP4, ffmpeg automatically applies
    the correct AVCC conversion. Forcing Annex-B start codes into an MP4
    container produces files that ffprobe can read but real players reject.

    Returns ``(success, actual_duration)``.
    """
    if not input_path.exists():
        return False, None

    target = output_path or input_path

    # Strategy 1 — error-tolerant stream copy (fast, preserves quality)
    temp_path = target.with_suffix(".tmp.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-fflags", "+igndts+genpts",
                "-err_detect", "ignore_err",
                "-i", str(input_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(temp_path),
            ],
            capture_output=True,
            check=True,
            timeout=180,
        )
        if temp_path.exists() and temp_path.stat().st_size > 0:
            actual_duration = _probe_duration(temp_path)
            # Validate duration before replacing the original file
            if expected_duration is not None and actual_duration is not None:
                diff = abs(actual_duration - expected_duration)
                threshold = max(expected_duration * 0.05, 30.0)
                if diff > threshold:
                    logger.warning(
                        "Stream-copy remux duration mismatch for %s: "
                        "expected %.1fs, got %.1fs (diff %.1fs > threshold %.1fs). "
                        "Falling back to re-encode.",
                        input_path.name, expected_duration, actual_duration, diff, threshold,
                    )
                    temp_path.unlink(missing_ok=True)
                    # Fall through to Strategy 2
                else:
                    temp_path.replace(target)
                    return True, actual_duration
            else:
                temp_path.replace(target)
                return True, actual_duration
    except Exception:
        logger.warning("Stream-copy remux failed for %s, trying re-encode", input_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    # Strategy 2 — full re-encode (recovers corrupt frames and fixes timestamps)
    reencode_path = target.with_suffix(".tmp.reencode.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-fflags", "+igndts+genpts",
                "-err_detect", "ignore_err",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(reencode_path),
            ],
            capture_output=True,
            check=True,
            timeout=300,
        )
        if reencode_path.exists() and reencode_path.stat().st_size > 0:
            actual_duration = _probe_duration(reencode_path)
            reencode_path.replace(target)
            return True, actual_duration
    except Exception:
        logger.error("Re-encode remux also failed for %s", input_path)
    finally:
        if reencode_path.exists():
            reencode_path.unlink(missing_ok=True)

    return False, None


# ----------------------------------------------------------------
# Segment finalize — seamless jump-cut MP4 from resumable .ts parts
# ----------------------------------------------------------------

def _remux_part_to_mp4(ts_part: Path, out_mp4: Path) -> tuple[bool, float | None]:
    """Remux one captured ``.ts`` segment into a clean, zero-based MP4.

    Each resumable segment comes from a *separate* live session with its
    own timestamp base. To keep audio/video aligned within the part — and to
    make the later concat produce a seamless jump cut — we rebase timestamps to
    zero (``-avoid_negative_ts make_zero``) and regenerate presentation
    timestamps (``+genpts``). Stream-copy first (lossless, fast); full
    re-encode fallback for mid-stream codec/parameter quirks.

    Returns ``(success, duration)``.
    """
    if not ts_part.exists() or ts_part.stat().st_size == 0:
        return False, None

    # Strategy 1 — error-tolerant stream copy with rebased timestamps
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-fflags", "+genpts+igndts",
                "-err_detect", "ignore_err",
                "-i", str(ts_part),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(out_mp4),
            ],
            capture_output=True, check=True, timeout=300,
        )
        duration = _probe_duration(out_mp4)
        if out_mp4.exists() and out_mp4.stat().st_size > 0 and duration:
            return True, duration
    except Exception:
        logger.warning("Part stream-copy remux failed for %s, re-encoding", ts_part.name)
    finally:
        if out_mp4.exists() and out_mp4.stat().st_size == 0:
            out_mp4.unlink(missing_ok=True)

    # Strategy 2 — full re-encode (recovers corrupt frames, normalizes params)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-fflags", "+genpts+igndts",
                "-err_detect", "ignore_err",
                "-i", str(ts_part),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                str(out_mp4),
            ],
            capture_output=True, check=True, timeout=600,
        )
        duration = _probe_duration(out_mp4)
        if out_mp4.exists() and out_mp4.stat().st_size > 0 and duration:
            return True, duration
    except Exception:
        logger.error("Part re-encode remux also failed for %s", ts_part.name)
    finally:
        if out_mp4.exists() and out_mp4.stat().st_size == 0:
            out_mp4.unlink(missing_ok=True)

    return False, None


def finalize_segments_to_mp4(
    segments: list[Path],
    output_path: Path,
) -> tuple[bool, float | None]:
    """Build one seamless MP4 from resumable ``.ts`` capture segments.

    Strategy (avoids the cross-session A/V drift caused by raw-TS concat):

    1. Remux **each** ``.partNNN.ts`` into its own clean, zero-based MP4 so
       every part has a self-consistent timeline.
    2. Concatenate the clean MP4 parts with ffmpeg's concat demuxer using
       ``-c copy`` — the demuxer rebases timestamps per input file, producing a
       hard jump cut at each gap with no accumulated offset.

    The single-segment case takes the direct ``.ts → .mp4`` fast path.

    Returns ``(success, total_duration)`` where ``total_duration`` is the sum
    of the probed part durations (real content only — excludes offline gaps),
    or ``(False, None)`` on failure.
    """
    parts = [p for p in segments if p.exists() and p.stat().st_size > 0]
    if not parts:
        return False, None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Fast path — a single segment is just a normal remux.
    if len(parts) == 1:
        return remux_to_mp4(parts[0], output_path=output_path)

    clean_parts: list[Path] = []
    total_duration = 0.0
    try:
        for idx, part in enumerate(parts):
            clean_mp4 = output_path.with_suffix(f".clean{idx:03d}.mp4")
            ok, dur = _remux_part_to_mp4(part, clean_mp4)
            if not ok:
                logger.error(
                    "finalize: part %d (%s) could not be remuxed; aborting concat",
                    idx, part.name,
                )
                return False, None
            clean_parts.append(clean_mp4)
            total_duration += dur or 0.0

        # Concat the clean MP4 parts — demuxer rebases timestamps per file.
        concat_list = output_path.with_suffix(".concat.txt")
        try:
            concat_list.write_text(
                "\n".join(f"file '{p.as_posix()}'" for p in clean_parts),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(output_path),
                ],
                capture_output=True, check=True, timeout=600,
            )
        finally:
            concat_list.unlink(missing_ok=True)

        if output_path.exists() and output_path.stat().st_size > 0:
            actual = _probe_duration(output_path)
            return True, actual or (total_duration or None)
        return False, None
    finally:
        for cp in clean_parts:
            cp.unlink(missing_ok=True)


# ----------------------------------------------------------------
# Repair
# ----------------------------------------------------------------

def repair_video(input_path: Path, output_path: Path | None = None) -> tuple[bool, float | None]:
    """Attempt to repair a corrupted live recording.

    Uses two ffmpeg strategies in order:

    1. **Error-tolerant stream copy** — fast, preserves original quality.
       Adds ``-fflags +igndts+genpts`` and ``-err_detect ignore_err`` to work
       around corrupt headers/timestamps. No ``h264_mp4toannexb`` filter is
       used: forcing Annex-B start codes into MP4 yields files ffprobe can
       read but players reject. The output is validated: if ffprobe still
       cannot parse it or the duration is missing, we fall through to the
       re-encode strategy.

    2. **Full re-encode** — slower but can recover frames and rebuild
       correct duration metadata.  Uses ``libx264 veryfast crf 23``.

    If *output_path* is not provided, the repaired file replaces the
    original in-place.  Returns ``(True, duration)`` on success or
    ``(False, None)`` on failure.
    """
    if not input_path.exists():
        return False, None

    target = output_path or input_path
    target.parent.mkdir(parents=True, exist_ok=True)

    def _is_valid_repair(path: Path) -> tuple[bool, float | None]:
        health = analyze_video_health(path)
        duration = _probe_duration(path)
        valid = (
            path.exists()
            and path.stat().st_size > 0
            and not health.get("is_corrupt", True)
            and duration is not None
            and duration > 0
        )
        return valid, duration

    # Strategy 1 — error-tolerant stream copy
    temp_path = target.with_suffix(".tmp.repair.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-fflags", "+igndts+genpts",
                "-err_detect", "ignore_err",
                "-i", str(input_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(temp_path),
            ],
            capture_output=True,
            check=True,
            timeout=180,
        )
        valid, duration = _is_valid_repair(temp_path)
        if valid:
            temp_path.replace(target)
            logger.info("Repair (stream copy) succeeded for %s (%.1fs)", input_path, duration)
            return True, duration
        logger.warning(
            "Stream-copy repair for %s produced an invalid file (duration=%s); trying re-encode",
            input_path, duration,
        )
    except Exception:
        logger.warning("Stream-copy repair failed for %s, trying re-encode", input_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    # Strategy 2 — full re-encode
    reencode_path = target.with_suffix(".tmp.repair.reencode.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-fflags", "+igndts+genpts",
                "-err_detect", "ignore_err",
                "-i", str(input_path),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(reencode_path),
            ],
            capture_output=True,
            check=True,
            timeout=300,
        )
        valid, duration = _is_valid_repair(reencode_path)
        if valid:
            reencode_path.replace(target)
            logger.info("Repair (re-encode) succeeded for %s (%.1fs)", input_path, duration)
            return True, duration
        logger.warning("Re-encode repair for %s produced an invalid file (duration=%s)", input_path, duration)
    except Exception:
        logger.error("Re-encode repair also failed for %s", input_path)
    finally:
        if reencode_path.exists():
            reencode_path.unlink(missing_ok=True)

    return False, None


# ----------------------------------------------------------------
# Health check
# ----------------------------------------------------------------

def analyze_video_health(video_path: Path) -> dict:
    """Check a video file for structural integrity.

    Returns a dictionary with keys:

    * ``is_corrupt`` — ``True`` when ffprobe cannot parse the file
    * ``duration`` — detected duration in seconds (or ``None``)
    * ``has_video`` — at least one video stream present
    * ``has_audio`` — at least one audio stream present
    * ``error`` — error message if probing failed
    """
    result: dict = {
        "is_corrupt": True,
        "duration": None,
        "has_video": False,
        "has_audio": False,
        "error": None,
    }

    if not video_path.exists():
        result["error"] = "File not found"
        return result

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-show_entries", "stream=codec_type,codec_name",
                "-of", "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if probe.returncode != 0:
            result["error"] = (probe.stderr or "").strip() or "ffprobe returned non-zero"
            return result

        data = json.loads(probe.stdout)

        if "format" in data and "duration" in data.get("format", {}):
            try:
                result["duration"] = float(data["format"]["duration"])
            except (ValueError, TypeError):
                pass

        for stream in data.get("streams", []):
            ctype = stream.get("codec_type")
            if ctype == "video":
                result["has_video"] = True
            elif ctype == "audio":
                result["has_audio"] = True

        # A file ffprobe can parse but with no usable duration is still broken
        # for playback (bad duration metadata), so treat it as corrupt.
        if result["duration"] is None or result["duration"] <= 0:
            result["is_corrupt"] = True
            result["error"] = "No valid duration detected"
        else:
            result["is_corrupt"] = False

    except json.JSONDecodeError as exc:
        result["error"] = f"Failed to parse ffprobe output: {exc}"
    except FileNotFoundError:
        result["error"] = "ffprobe not found — is FFmpeg installed?"
    except Exception as exc:
        result["error"] = str(exc)

    return result
