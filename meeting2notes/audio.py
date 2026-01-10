"""
Audio utilities: ffmpeg/ffprobe wrappers, recording (macOS), re-encoding and splitting.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .timing import status
from typing import List


def require_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found. Install it (e.g. `brew install ffmpeg`).")


def audio_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        return 0.0
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def transcription_cost_gbp(audio_path: Path) -> tuple[float, float]:
    dur_s = audio_duration_seconds(audio_path)
    dur_min = dur_s / 60.0 if dur_s else 0.0
    # import here to avoid cycle at package import time
    from .config import TRANSCRIPTION_GBP_PER_MIN
    return dur_min, dur_min * TRANSCRIPTION_GBP_PER_MIN


def list_macos_audio_devices() -> None:
    cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print("ffmpeg not found")


def record_audio_macos(output_path: Path, device: str) -> None:
    require_ffmpeg()
    status(f"Recording to: {output_path}")
    status("Press Enter to stop recording…")

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f", "avfoundation",
        "-i", device,
        "-ac", "1",
        "-ar", "16000",
        str(output_path),
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        input()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    status("Recording stopped.")
    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("Recording failed or produced an empty file")


def reencode_to_wav_16k_mono(src: Path, dst: Path) -> None:
    require_ffmpeg()
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(dst),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1024:
        raise RuntimeError(f"ffmpeg wav encode failed:\n{r.stderr[-1200:]}")


def split_audio_wav(src: Path, out_dir: Path, chunk_seconds: int) -> List[Path]:
    require_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "chunk_%03d.wav"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-reset_timestamps", "1",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(pattern),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg split failed:\n{r.stderr[-1200:]}")
    chunks = sorted(out_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("ffmpeg split produced no chunks.")
    return chunks
