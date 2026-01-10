"""
CLI entrypoint and orchestration for meeting2notes.

This module wires together the refactored components and exposes a main()
function which can be run as: python -m meeting2notes.cli
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__ as VERSION
from . import auth
from . import config
from . import timing
from . import utils
from . import io as io_mod
from . import audio
from . import transcribe
from . import openai_client


def main() -> None:
    timing.DEBUG_TIMING = False
    timing.START_TS = time.perf_counter()

    p = argparse.ArgumentParser(prog="meeting2notes", description="Transcribe audio and generate meeting notes.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--audio", type=str, help="Path to audio file to transcribe")
    g.add_argument("--record", action="store_true", help="Record audio from macOS device")

    p.add_argument("--device", type=str, default=":0", help="macOS avfoundation device id (for --record)")
    p.add_argument("--list-devices", action="store_true", help="List macOS audio devices and exit")
    p.add_argument("--out-subpath", type=str, default="Meeting_Notes", help="Output subpath under ~/Documents")
    p.add_argument("--format", choices=["md", "txt"], default="md", help="Output format")

    p.add_argument("--debug_timing", action="store_true",
                   help="Enable timestamped step/timing logs.")

    # faster-whisper knobs
    p.add_argument("--whisper-model", type=str, default=config.DEFAULT_WHISPER_MODEL,
                   help="faster-whisper model name (default: small).")
    p.add_argument("--chunk-seconds", type=int, default=config.DEFAULT_CHUNK_SECONDS,
                   help="Chunk length for transcription when chunking is enabled (seconds).")
    p.add_argument("--keep-intermediate", action="store_true",
                   help="Keep intermediate WAV/chunks next to the audio file (for debugging).")
    p.add_argument("--fw-device", type=str, default=None,
                   help="faster-whisper device: cpu or cuda (default: auto).")
    p.add_argument("--fw-compute-type", type=str, default="int8",
                   help="faster-whisper compute_type (cpu: int8 recommended; cuda: float16).")

    # Optional model upgrade for pass 2
    p.add_argument("--pass2-model", type=str, default=config.CHAT_MODEL,
                   help="Chat model for pass 2 notes (e.g. gpt-4.1-mini or gpt-4.1).")

    p.add_argument("--version", action="store_true", help="Print version and exit")

    args = p.parse_args()

    if args.version:
        print(f"meeting2notes {VERSION}")
        return

    timing.DEBUG_TIMING = bool(args.debug_timing)
    timing.START_TS = time.perf_counter()

    if args.list_devices:
        audio.list_macos_audio_devices()
        return

    api_key = auth.require_api_key()
    out_dir = io_mod.ensure_output_dir(args.out_subpath)
    timestamp = utils.iso_timestamp_local()

    if args.record:
        timestamp_name = timestamp.replace(":", ".")
        audio_path = out_dir / f"Recording {timestamp_name}.m4a"
        audio.record_audio_macos(audio_path, args.device)
    else:
        if not args.audio:
            print("ERROR: Provide --audio PATH or use --record", file=sys.stderr)
            sys.exit(2)
        audio_path = Path(args.audio).expanduser().resolve()
        if not audio_path.exists():
            print(f"Audio file not found: {audio_path}", file=sys.stderr)
            sys.exit(2)

    # Transcription
    if timing.DEBUG_TIMING:
        with timing.step("Transcribing audio locally with faster-whisper"):
            transcript = transcribe.transcribe_audio_local(
                audio_path,
                whisper_model=args.whisper_model,
                chunk_seconds=args.chunk_seconds,
                keep_intermediate=bool(args.keep_intermediate),
                device=args.fw_device,
                compute_type=args.fw_compute_type,
            )
    else:
        print("Transcribing audio locally…", flush=True)
        transcript = transcribe.transcribe_audio_local(
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

    dur_min, trans_cost = audio.transcription_cost_gbp(audio_path)

    # Pass 1: map
    if timing.DEBUG_TIMING:
        with timing.step("Building meeting map (Pass 1)"):
            meeting_map, map_usage = openai_client.build_meeting_map(api_key, transcript)
    else:
        print("Building meeting map…", flush=True)
        meeting_map, map_usage = openai_client.build_meeting_map(api_key, transcript)

    # Title from map
    if timing.DEBUG_TIMING:
        with timing.step("Generating meeting title (from meeting map)"):
            meeting_title, title_usage = openai_client.generate_meeting_title_from_map(api_key, meeting_map)
    else:
        print("Generating meeting title…", flush=True)
        meeting_title, title_usage = openai_client.generate_meeting_title_from_map(api_key, meeting_map)

    # Pass 2: notes
    if timing.DEBUG_TIMING:
        with timing.step("Generating meeting notes (Pass 2)"):
            notes_md, notes_usage = openai_client.generate_meeting_notes(
                api_key,
                transcript,
                meeting_map,
                meeting_title,
                timestamp,
                pass2_model=args.pass2_model,
            )
    else:
        print("Generating meeting notes…", flush=True)
        notes_md, notes_usage = openai_client.generate_meeting_notes(
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
        ("Title generation", config.CHAT_MODEL, title_usage),
        ("Pass 1 (structure)", config.CHAT_MODEL, map_usage),
        ("Pass 2 (notes)", args.pass2_model, notes_usage),
    ]:
        line, cost = openai_client.format_usage(label, model, usage)
        cost_lines.append(line)
        total_cost += cost

    if timing.DEBUG_TIMING:
        timing.status("=== Cost breakdown ===")
    else:
        print("\n=== Cost breakdown ===")
    for l in cost_lines:
        print(l)
    print(f"{'TOTAL':<25} £{total_cost:.4f}\n")

    # Output
    base_name = f"{utils.safe_filename(meeting_title)} - Notes"

    out_path = io_mod.save_notes(out_dir, base_name, notes_md, transcript, cost_lines, fmt=args.format)

    if timing.DEBUG_TIMING:
        with timing.step("Saving output"):
            timing.status(f"Saved notes to: {out_path}")
    else:
        print(f"Saved notes to: {out_path}")


if __name__ == "__main__":
    main()
