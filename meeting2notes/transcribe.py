"""
Transcription using faster-whisper.

This module mirrors the logic from the original script, including a simple
cache for loaded models and chunking behavior.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
from typing import List

from .timing import step, status
from .audio import reencode_to_wav_16k_mono, split_audio_wav, audio_duration_seconds
from .config import DEFAULT_WHISPER_MODEL, DEFAULT_CHUNK_SECONDS, AUTO_CHUNK_IF_LONGER_THAN_S

_FASTER_WHISPER_CACHE: dict[tuple[str, str, str], object] = {}


def _pick_faster_whisper_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def load_faster_whisper_model(model_name: str, device: str | None = None, compute_type: str = "int8"):
    """
    Load and cache faster-whisper WhisperModel.
    """
    from faster_whisper import WhisperModel

    dev = device or _pick_faster_whisper_device()
    key = (model_name, dev, compute_type)
    if key in _FASTER_WHISPER_CACHE:
        return _FASTER_WHISPER_CACHE[key]

    status(f"Loading faster-whisper model '{model_name}' on {dev} (compute_type={compute_type})…")
    t0 = time.perf_counter()
    m = WhisperModel(model_name, device=dev, compute_type=compute_type)
    status(f"faster-whisper model ready ({time.perf_counter() - t0:.1f}s).")
    _FASTER_WHISPER_CACHE[key] = m
    return m


def _transcribe_one_file_fw(model, wav_path: Path, *, language: str = "en") -> str:
    segments, _info = model.transcribe(
        str(wav_path),
        language=language,
        task="transcribe",
        beam_size=1,
        best_of=1,
        temperature=0.0,
        vad_filter=True,
    )
    parts: List[str] = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            parts.append(t)
    return " ".join(parts).strip()


def transcribe_audio_local(
    audio_path: Path,
    *,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
    keep_intermediate: bool = False,
    device: str | None = None,
    compute_type: str = "int8",
) -> str:
    """
    Local faster-whisper transcription.
    - Re-encodes to a clean WAV (16k mono)
    - If duration > AUTO_CHUNK_IF_LONGER_THAN_S the splits audio into chunks and transcribes each chunk
    """
    model = load_faster_whisper_model(whisper_model, device=device, compute_type=compute_type)

    if keep_intermediate:
        tmp_root_ctx = None
        tmp_dir = audio_path.parent / "_meeting2notes_intermediate"
        tmp_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_root_ctx = tempfile.TemporaryDirectory(prefix="meeting2notes_")
        tmp_dir = Path(tmp_root_ctx.name)

    try:
        wav_path = tmp_dir / "speech_16k_mono.wav"
        with step("Re-encoding audio to 16kHz mono WAV"):
            reencode_to_wav_16k_mono(audio_path, wav_path)

        dur_s = audio_duration_seconds(wav_path)
        if dur_s and status:  # status already checks DEBUG_TIMING internally
            status(f"Audio duration: {dur_s/60.0:.1f} minutes")

        should_chunk = bool(dur_s and dur_s > AUTO_CHUNK_IF_LONGER_THAN_S)

        if should_chunk:
            with step(f"Splitting into {chunk_seconds//60} minute chunks"):
                chunks_dir = tmp_dir / "chunks"
                chunks = split_audio_wav(wav_path, chunks_dir, chunk_seconds=chunk_seconds)

            if not status:
                # keep old behavior's prints when timing disabled
                print(f"Transcribing in {len(chunks)} chunks…", flush=True)
            else:
                status(f"Starting faster-whisper transcription across {len(chunks)} chunks…")

            parts: List[str] = []
            for i, ch in enumerate(chunks, start=1):
                t0 = time.perf_counter()
                if not status:
                    print(f"  chunk {i}/{len(chunks)}", flush=True)
                else:
                    status(f"faster-whisper: transcribing chunk {i}/{len(chunks)}")

                txt = _transcribe_one_file_fw(model, ch, language="en")
                if txt:
                    parts.append(txt)

                if status:
                    status(f"Chunk {i}/{len(chunks)} done ({time.perf_counter() - t0:.1f}s)")

            with step("Joining chunk transcripts"):
                return "\n\n".join(parts).strip()

        # Single file
        if not status:
            print("Transcribing (single pass)…", flush=True)
        else:
            status("Starting faster-whisper transcription (single pass)…")

        t0 = time.perf_counter()
        txt = _transcribe_one_file_fw(model, wav_path, language="en")
        if status:
            status(f"Transcription finished ({time.perf_counter() - t0:.1f}s)")
        return txt

    finally:
        if tmp_root_ctx is not None:
            tmp_root_ctx.cleanup()
