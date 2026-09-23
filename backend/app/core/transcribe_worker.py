"""Standalone Whisper transcription worker.

Run as ``python -m app.core.transcribe_worker <video> --cache-dir <dir>``.
It prints one JSON object to stdout and exits; logs go to stderr.

This runs in a short-lived child process on purpose. Loading faster-whisper
inside the API process pinned the model, the CTranslate2/onnxruntime
runtimes and the job's peak audio buffers there forever: after one
transcription the backend idled at ~1.3 GB instead of ~150 MB. When a child
process exits, the OS gets all of that memory back.

It deliberately imports nothing else from ``app``, so the child stays small.

Audio is streamed from ffmpeg and transcribed in ~10-minute windows instead
of decoding the whole recording at once (76 min of float32 audio is ~290 MB,
briefly doubled during decoding). Each cut is snapped to the quietest second
near the boundary so no word is split across windows.
"""
import argparse
import json
import logging
import subprocess
import sys
from typing import Iterator

import numpy as np

logger = logging.getLogger("tikrec.transcribe_worker")

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # s16le
WINDOW_SECONDS = 600
SNAP_SECONDS = 15
MODEL_SIZE = "tiny"


def fmt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def find_quiet_cut(samples: np.ndarray, target: int, search: int, frame: int = SAMPLE_RATE) -> int:
    """Return a cut index near *target* at the centre of the quietest *frame*.

    Only frames that lie wholly within ``[target - search, target + search]``
    are considered, so the cut never moves further than *search* samples.
    """
    lo = max(0, target - search)
    hi = min(len(samples), target + search)
    if hi - lo < frame:
        return min(target, len(samples))
    region = samples[lo:hi].astype(np.float32)
    n_frames = len(region) // frame
    energies = (region[: n_frames * frame].reshape(n_frames, frame) ** 2).mean(axis=1)
    quietest = int(np.argmin(energies))
    return lo + quietest * frame + frame // 2


def iter_windows(
    stream,
    window_samples: int = WINDOW_SECONDS * SAMPLE_RATE,
    snap_samples: int = SNAP_SECONDS * SAMPLE_RATE,
) -> Iterator[tuple[int, np.ndarray]]:
    """Yield ``(offset_samples, int16 window)`` pairs from a raw s16le stream.

    Holds at most one window plus the snap margin in memory.
    """
    raw = bytearray()
    offset = 0
    needed_bytes = (window_samples + snap_samples) * BYTES_PER_SAMPLE
    while True:
        eof = False
        while len(raw) < needed_bytes:
            chunk = stream.read(needed_bytes - len(raw))
            if not chunk:
                eof = True
                break
            raw += chunk
        usable = len(raw) - (len(raw) % BYTES_PER_SAMPLE)
        samples = np.frombuffer(bytes(raw[:usable]), dtype=np.int16)
        if eof:
            if len(samples):
                yield offset, samples
            return
        cut = find_quiet_cut(samples, window_samples, snap_samples)
        yield offset, samples[:cut]
        del raw[: cut * BYTES_PER_SAMPLE]
        offset += cut


def transcribe(video_path: str, cache_dir: str, model_size: str = MODEL_SIZE) -> dict:
    from faster_whisper import WhisperModel

    logger.info("Loading Whisper model '%s' from %s", model_size, cache_dir)
    model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=cache_dir)

    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", video_path,
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    lines: list[str] = []
    language, language_probability, best_speech = None, 0.0, -1
    total_samples = 0
    try:
        for offset, window in iter_windows(ffmpeg.stdout):
            total_samples += len(window)
            offset_s = offset / SAMPLE_RATE
            audio = window.astype(np.float32) / 32768.0
            segments, info = model.transcribe(audio, beam_size=1, vad_filter=True)
            n = 0
            for seg in segments:
                n += 1
                lines.append(
                    f"[{fmt_timestamp(seg.start + offset_s)} --> "
                    f"{fmt_timestamp(seg.end + offset_s)}] {seg.text.strip()}"
                )
            # Report the language of the window with the most speech.
            if n > best_speech:
                best_speech = n
                language, language_probability = info.language, info.language_probability
            logger.info(
                "Window at %s: %d segments (%s)", fmt_timestamp(offset_s), n, info.language
            )
    finally:
        ffmpeg.stdout.close()
        stderr = ffmpeg.stderr.read().decode(errors="replace")
        returncode = ffmpeg.wait()

    if total_samples == 0:
        raise RuntimeError(f"ffmpeg produced no audio (exit {returncode}): {stderr[-500:]}")
    if returncode != 0:
        logger.warning("ffmpeg exited %d after %d s of audio: %s",
                       returncode, total_samples // SAMPLE_RATE, stderr[-500:])

    return {
        "language": language,
        "language_probability": language_probability,
        "lines": lines,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--model", default=MODEL_SIZE)
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        result = transcribe(args.video, args.cache_dir, args.model)
    except Exception:
        logger.exception("Transcription failed for %s", args.video)
        return 1
    json.dump(result, sys.stdout)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
