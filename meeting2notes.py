#!/usr/bin/env python3
"""
Legacy shim for meeting2notes CLI.

This file used to contain the entire application. It has been refactored
into the `meeting2notes` package. The shim simply calls the new CLI entrypoint.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import requests

OPENAI_BASE_URL = "https://api.openai.com/v1"
CHAT_MODEL = "gpt-4.1-mini"

DEFAULT_WHISPER_MODEL = "small"
DEFAULT_CHUNK_SECONDS = 600          # chunk size in seconds (10 minutes)
AUTO_CHUNK_IF_LONGER_THAN_S = 600    # if meeting > 10 minutes, chunk it
TRANSCRIPTION_GBP_PER_MIN = 0.0      # local => £0.00

# Pricing for chat calls (GBP)
PRICING_GBP = {
    "gpt-4.1-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.00060},
    "gpt-4.1": {"input_per_1k": 0.0025, "output_per_1k": 0.0100},
}

DEBUG_TIMING = False
START_TS = time.perf_counter()

def _now_str() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")

def _elapsed() -> str:
    return f"{time.perf_counter() - START_TS:.1f}s"

def status(msg: str) -> None:
    """Timestamped status messages (debug only)."""
    if not DEBUG_TIMING:
        return
    print(f"[{_now_str()} +{_elapsed():>6}] {msg}", flush=True)

@contextmanager
def step(msg: str):
    """Timed step context manager (debug only)."""
    if not DEBUG_TIMING:
        yield
        return
    t0 = time.perf_counter()
    status(f"{msg} …")
    try:
        yield
    finally:
        dt_s = time.perf_counter() - t0
        status(f"{msg} ✓ ({dt_s:.1f}s)")

# Utilities
def require_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("ERROR: OPENAI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(2)
    return key

def iso_timestamp_local() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")

def safe_filename(name: str, max_len: int = 120) -> str:
    name = re.sub(r"[\/\\:\*\?\"<>\|]+", "-", name.strip())
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:max_len].rstrip() or "Untitled")

def ensure_output_dir(subpath: str) -> Path:
    out_dir = Path.home() / "Documents" / subpath
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

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
    return dur_min, dur_min * TRANSCRIPTION_GBP_PER_MIN

def estimate_cost_gbp(model: str, usage: dict) -> float:
    pricing = PRICING_GBP.get(model)
    if not pricing or not usage:
        return 0.0
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    return (in_tokens / 1000) * pricing["input_per_1k"] + (out_tokens / 1000) * pricing["output_per_1k"]

def format_usage(label: str, model: str, usage: dict) -> tuple[str, float]:
    cost = estimate_cost_gbp(model, usage)
    line = f"{label:<25} tokens={usage.get('total_tokens', 0):>6}  cost=£{cost:.4f}"
    return line, cost

def markdown_to_text(md: str) -> str:
    text = md
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"- \[ \]\s*", "- ", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    return text.strip()


# Recording (macOS)
def list_macos_audio_devices() -> None:
    cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print("ffmpeg not found", file=sys.stderr)

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


# faster-whisper local transcription
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

def split_audio_wav(src: Path, out_dir: Path, chunk_seconds: int) -> list[Path]:
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
    parts: list[str] = []
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
    - If duration > 10 minutes the splits audio into chunks and transcribes each chunk
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
        if dur_s and DEBUG_TIMING:
            status(f"Audio duration: {dur_s/60.0:.1f} minutes")

        should_chunk = bool(dur_s and dur_s > AUTO_CHUNK_IF_LONGER_THAN_S)

        if should_chunk:
            with step(f"Splitting into {chunk_seconds//60} minute chunks"):
                chunks_dir = tmp_dir / "chunks"
                chunks = split_audio_wav(wav_path, chunks_dir, chunk_seconds=chunk_seconds)

            if not DEBUG_TIMING:
                print(f"Transcribing in {len(chunks)} chunks…", flush=True)
            else:
                status(f"Starting faster-whisper transcription across {len(chunks)} chunks…")

            parts: list[str] = []
            for i, ch in enumerate(chunks, start=1):
                t0 = time.perf_counter()
                if DEBUG_TIMING:
                    status(f"faster-whisper: transcribing chunk {i}/{len(chunks)}")
                else:
                    print(f"  chunk {i}/{len(chunks)}", flush=True)

                txt = _transcribe_one_file_fw(model, ch, language="en")
                if txt:
                    parts.append(txt)

                if DEBUG_TIMING:
                    status(f"Chunk {i}/{len(chunks)} done ({time.perf_counter() - t0:.1f}s)")

            with step("Joining chunk transcripts"):
                return "\n\n".join(parts).strip()

        # Single file
        if not DEBUG_TIMING:
            print("Transcribing (single pass)…", flush=True)
        else:
            status("Starting faster-whisper transcription (single pass)…")

        t0 = time.perf_counter()
        txt = _transcribe_one_file_fw(model, wav_path, language="en")
        if DEBUG_TIMING:
            status(f"Transcription finished ({time.perf_counter() - t0:.1f}s)")
        return txt

    finally:
        if tmp_root_ctx is not None:
            tmp_root_ctx.cleanup()


# OpenAI Chat (map/title/notes)
def chat_completion(
    api_key: str,
    messages: list[dict],
    temperature: float,
    model: str = CHAT_MODEL,
    return_usage: bool = False,
):
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    r = requests.post(
        url,
        headers=headers,
        data=json.dumps({"model": model, "temperature": temperature, "messages": messages}),
        timeout=300,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Chat completion failed ({r.status_code}): {r.text}")

    data = r.json()
    content = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage", {})
    return (content, usage) if return_usage else content

def build_meeting_map(api_key: str, transcript: str) -> tuple[dict, dict]:
    raw, usage = chat_completion(
        api_key,
        model=CHAT_MODEL,
        temperature=0.2,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert technical research assistant.\n"
                    "Extract a structured meeting map from a transcript.\n"
                    "Return ONLY valid JSON (parseable by json.loads). No markdown, no commentary.\n\n"
                    "Prioritise:\n"
                    "- Correct topic segmentation\n"
                    "- Capturing paper-writing structure/framing when present\n"
                    "- Capturing engineering/setup attempts + blockers when present\n"
                    "- Information-dense bullet fragments (no narration)\n"
                ),
            },
            {"role": "user", "content": f"""
Extract a JSON object with EXACTLY this schema:

{{
  "topics": [
    {{
      "name": "short topic label",
      "time_range_hint": "early/mid/late or empty string",
      "details": ["dense bullet fragments capturing substance and rationale"],
      "paper_structure": ["outline/sections/framing/contributions/eval plan/related work if relevant"],
      "tooling_setup": ["what was tried, environment assumptions, components, commands, blockers if relevant"],
      "decisions_explicit": ["only if explicitly decided"],
      "emerging_directions": ["tentative preferences/directions; NOT decisions"],
      "action_items": [
        {{
          "action": "action described",
          "owner": "name or TBC",
          "due": "date or TBC"
        }}
      ],
      "risks_blockers": ["explicit risks/blockers; prefix inferred ones with 'Potential:'"],
      "open_questions": ["questions raised or left unresolved"]
    }}
  ],
  "summary_bullets": ["8–12 bullets capturing overall outcomes and themes"],
  "decisions": ["explicit decisions only; empty list if none"],
  "action_items": [
    {{
      "action": "action described",
      "owner": "name or TBC",
      "due": "date or TBC"
    }}
  ],
  "emerging_directions": ["tentative directions across the whole meeting"],
  "keywords": ["important names: tools, frameworks, scenarios, paper sections, datasets, systems"]
}}

Rules:
- Do NOT invent facts.
- No narration ('we discussed', 'the team').
- Prefer concrete artefacts (paper sections, simulator names, scenarios, frameworks, components).
- If both paper-structure and tool/setup occur, they MUST appear as separate topics.
- Ensure each major topic has at least 6 bullets in 'details' (unless the transcript is genuinely short).

Transcript:
{transcript}
"""},
        ],
    )

    cleaned = re.sub(r"^```json\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not m:
        raise RuntimeError(f"Pass 1 did not return JSON:\n{raw}")
    return json.loads(m.group(0)), usage

def generate_meeting_title_from_map(api_key: str, meeting_map: dict) -> tuple[str, dict]:
    payload = {
        "summary_bullets": meeting_map.get("summary_bullets", []),
        "topics": [t.get("name", "") for t in meeting_map.get("topics", [])],
        "keywords": meeting_map.get("keywords", []),
    }

    title, usage = chat_completion(
        api_key,
        model=CHAT_MODEL,
        temperature=0.3,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short, descriptive title (3–10 words) for technical/research meetings. "
                    "Be specific. Avoid dates and avoid the word 'meeting'. "
                    "Avoid generic titles like 'Project Update'."
                ),
            },
            {"role": "user", "content": "Generate a concise title from the structured summary below.\n\n"
                                        f"{json.dumps(payload, ensure_ascii=False)}"},
        ],
    )

    title = title.strip().strip('"')
    return (title.splitlines()[0].strip() or "Untitled"), usage

def generate_meeting_notes(
    api_key: str,
    transcript: str,
    meeting_map: dict,
    meeting_title: str,
    timestamp: str,
    *,
    pass2_model: str = CHAT_MODEL,
) -> tuple[str, dict]:
    notes_md, notes_usage = chat_completion(
        api_key,
        model=pass2_model,
        temperature=0.3,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert technical editor producing Notion-style meeting notes "
                    "for academic and research-oriented discussions.\n\n"
                    "Hard requirements:\n"
                    "- British English\n"
                    "- Bullet points only (no paragraphs)\n"
                    "- No narration ('we', 'the team', 'they discussed')\n"
                    "- Information-dense bullets: include rationale, constraints, and trade-offs\n"
                    "- Group content by topic using the topic names from meeting_map\n"
                    "- Do not invent facts, decisions, or action items\n"
                    "- If something is uncertain, label it as 'Unclear:' or 'Tentative:'\n"
                ),
            },
            {"role": "user", "content": f"""
Write detailed meeting notes using meeting_map as the authoritative structure.

Style:
- Concise bullet fragments (scan-friendly).
- Prefer specific technical nouns (tools, components, paper sections, scenarios) over generic phrasing.
- Depth targets: 8–12 bullets in Summary; 8–20 bullets per major topic in Key points.

Output Markdown using EXACTLY these headings and order:

---

# {meeting_title}

## Date and time
- {timestamp}

## Summary
- 8–12 dense bullets capturing the core themes/outcomes (no narration)

## Key points
- For each topic, use:
  - **Topic: <name>**
    - bullets (include paper_structure/tooling_setup detail when present)

## Decisions
- If none: "No formal decisions recorded."
- Otherwise: bullets of explicit decisions only.

## Action items
- Checklist only:
  - [ ] Action (Owner: ___, Due: ___)
- If none: "- [ ] None recorded (Owner: TBC, Due: TBC)"

## Risks / blockers
- Bullets (prefix inferred ones with "Potential:")

## Open questions
- Bullets, grouped by topic if useful

---

meeting_map:
{json.dumps(meeting_map, ensure_ascii=False)}

Transcript (for grounding only; do not quote large chunks):
{transcript}
"""},
        ],
    )
    return notes_md, notes_usage


# Main
def main() -> None:
    global DEBUG_TIMING, START_TS

    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--audio", type=str)
    g.add_argument("--record", action="store_true")

    p.add_argument("--device", type=str, default=":0")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--out-subpath", type=str, default="Meeting_Notes")
    p.add_argument("--format", choices=["md", "txt"], default="md")

    # Debug timing output (your requested flag name)
    p.add_argument("--debug_timing", action="store_true",
                   help="Enable timestamped step/timing logs.")

    # faster-whisper knobs
    p.add_argument("--whisper-model", type=str, default=DEFAULT_WHISPER_MODEL,
                   help="faster-whisper model name (default: small).")
    p.add_argument("--chunk-seconds", type=int, default=DEFAULT_CHUNK_SECONDS,
                   help="Chunk length for transcription when chunking is enabled (seconds).")
    p.add_argument("--keep-intermediate", action="store_true",
                   help="Keep intermediate WAV/chunks next to the audio file (for debugging).")
    p.add_argument("--fw-device", type=str, default=None,
                   help="faster-whisper device: cpu or cuda (default: auto).")
    p.add_argument("--fw-compute-type", type=str, default="int8",
                   help="faster-whisper compute_type (cpu: int8 recommended; cuda: float16).")

    # Optional model upgrade for pass 2
    p.add_argument("--pass2-model", type=str, default=CHAT_MODEL,
                   help="Chat model for pass 2 notes (e.g. gpt-4.1-mini or gpt-4.1).")

    args = p.parse_args()

    DEBUG_TIMING = bool(args.debug_timing)
    START_TS = time.perf_counter()

    if args.list_devices:
        list_macos_audio_devices()
        return

    api_key = require_api_key()
    out_dir = ensure_output_dir(args.out_subpath)
    timestamp = iso_timestamp_local()

    if args.record:
        audio_path = out_dir / f"Recording {timestamp.replace(':', '.')}.m4a"
        record_audio_macos(audio_path, args.device)
    else:
        if not args.audio:
            print("ERROR: Provide --audio PATH or use --record", file=sys.stderr)
            sys.exit(2)
        audio_path = Path(args.audio).expanduser().resolve()
        if not audio_path.exists():
            print(f"Audio file not found: {audio_path}", file=sys.stderr)
            sys.exit(2)

    # Transcription
    if DEBUG_TIMING:
        with step("Transcribing audio locally with faster-whisper"):
            transcript = transcribe_audio_local(
                audio_path,
                whisper_model=args.whisper_model,
                chunk_seconds=args.chunk_seconds,
                keep_intermediate=bool(args.keep_intermediate),
                device=args.fw_device,
                compute_type=args.fw_compute_type,
            )
    else:
        print("Transcribing audio locally…", flush=True)
        transcript = transcribe_audio_local(
            audio_path,
            whisper_model=args.whisper_model,
            chunk_seconds=args.chunk_seconds,
            keep_intermediate=bool(args.keep_intermediate),
            device=args.fw_device,
            compute_type=args.fw_compute_type,
        )

    if not transcript:
        print("No transcript returned.", file=sys.stderr)
        sys.exit(1)

    dur_min, trans_cost = transcription_cost_gbp(audio_path)

    # Pass 1: map
    if DEBUG_TIMING:
        with step("Building meeting map (Pass 1)"):
            meeting_map, map_usage = build_meeting_map(api_key, transcript)
    else:
        print("Building meeting map…", flush=True)
        meeting_map, map_usage = build_meeting_map(api_key, transcript)

    # Title from map
    if DEBUG_TIMING:
        with step("Generating meeting title (from meeting map)"):
            meeting_title, title_usage = generate_meeting_title_from_map(api_key, meeting_map)
    else:
        print("Generating meeting title…", flush=True)
        meeting_title, title_usage = generate_meeting_title_from_map(api_key, meeting_map)

    # Pass 2: notes
    if DEBUG_TIMING:
        with step("Generating meeting notes (Pass 2)"):
            notes_md, notes_usage = generate_meeting_notes(
                api_key,
                transcript,
                meeting_map,
                meeting_title,
                timestamp,
                pass2_model=args.pass2_model,
            )
    else:
        print("Generating meeting notes…", flush=True)
        notes_md, notes_usage = generate_meeting_notes(
            api_key,
            transcript,
            meeting_map,
            meeting_title,
            timestamp,
            pass2_model=args.pass2_model,
        )

    # Cost breakdown
    cost_lines: list[str] = []
    total_cost = 0.0

    cost_lines.append(f"{'Transcription (local)':<25} minutes={dur_min:>6.1f}  cost=£{trans_cost:.4f}")
    total_cost += trans_cost

    for label, model, usage in [
        ("Title generation", CHAT_MODEL, title_usage),
        ("Pass 1 (structure)", CHAT_MODEL, map_usage),
        ("Pass 2 (notes)", args.pass2_model, notes_usage),
    ]:
        line, cost = format_usage(label, model, usage)
        cost_lines.append(line)
        total_cost += cost

    if DEBUG_TIMING:
        status("=== Cost breakdown ===")
    else:
        print("\n=== Cost breakdown ===")
    for l in cost_lines:
        print(l)
    print(f"{'TOTAL':<25} £{total_cost:.4f}\n")

    # Output
    base_name = f"{safe_filename(meeting_title)} - Notes"

    cost_footer = (
        "\n\n---\n\n"
        "## Generation cost\n"
        + "\n".join(f"- {l}" for l in cost_lines)
        + f"\n- **Total:** £{total_cost:.4f}\n"
    )

    final_md = (
        notes_md.rstrip()
        + "\n\n---\n\n## Transcript\n"
        + transcript.strip()
        + cost_footer
    )

    if args.format == "txt":
        output_text = markdown_to_text(final_md)
        out_path = out_dir / f"{base_name}.txt"
    else:
        output_text = final_md
        out_path = out_dir / f"{base_name}.md"

    if DEBUG_TIMING:
        with step("Saving output"):
            out_path.write_text(output_text, encoding="utf-8")
        status(f"Saved notes to: {out_path}")
    else:
        out_path.write_text(output_text, encoding="utf-8")
        print(f"Saved notes to: {out_path}")

if __name__ == "__main__":
    # Preserve backwards compatibility for direct script execution.
    from meeting2notes.cli import main as _main
    _main()
