#!/usr/bin/env python3
"""
Meeting2Notes

Record audio or use an existing audio file, transcribe it, and generate
structured meeting notes saved as Markdown or plain text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests


OPENAI_BASE_URL = "https://api.openai.com/v1"
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
CHAT_MODEL = "gpt-4.1-mini"


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


def transcribe_audio(api_key: str, audio_path: Path) -> str:
    url = f"{OPENAI_BASE_URL}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    with audio_path.open("rb") as f:
        r = requests.post(
            url,
            headers=headers,
            files={"file": (audio_path.name, f)},
            data={"model": TRANSCRIBE_MODEL},
            timeout=300,
        )

    if r.status_code != 200:
        raise RuntimeError(f"Transcription failed ({r.status_code}): {r.text}")

    return (r.json().get("text") or "").strip()


def chat_completion(api_key: str, messages: list[dict], temperature: float) -> str:
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    r = requests.post(
        url,
        headers=headers,
        data=json.dumps(
            {
                "model": CHAT_MODEL,
                "temperature": temperature,
                "messages": messages,
            }
        ),
        timeout=300,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Chat completion failed ({r.status_code}): {r.text}")

    return (r.json()["choices"][0]["message"]["content"] or "").strip()


def generate_meeting_title(api_key: str, transcript: str) -> str:
    title = chat_completion(
        api_key,
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short, professional meeting title (3–8 words). "
                    "Do not include dates or the word 'meeting'."
                ),
            },
            {"role": "user", "content": transcript},
        ],
        temperature=0.3,
    )
    return title.strip().strip('"').splitlines()[0] or "Untitled"


def generate_meeting_notes(api_key: str, transcript: str, meeting_title: str, timestamp: str) -> str:
    return chat_completion(
        api_key,
        messages=[
            {
                "role": "system",
                "content": (
                    "Produce clear, structured meeting notes in British English. "
                    "Do not infer decisions or actions not explicitly stated."
                ),
            },
            {
                "role": "user",
                "content": f"""---

# {meeting_title}

## Date and time
- {timestamp}

## Summary

## Key points

## Decisions

## Action items
- [ ] Action (Owner: TBC, Due: TBC)

## Risks / blockers

## Open questions

---

## Transcript
{transcript}
""",
            },
        ],
        temperature=0.2,
    )


def markdown_to_text(md: str) -> str:
    text = md
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"- \[ \]\s*", "- ", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    return text.strip()


def list_macos_audio_devices() -> None:
    cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print("ffmpeg not found", file=sys.stderr)


def record_audio_macos(output_path: Path, device: str) -> None:
    print(f"Recording to: {output_path}")
    print("Press Enter to stop recording...\n")

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

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found")

    try:
        input()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    print("Recording stopped.")

    if not output_path.exists() or output_path.stat().st_size < 1024:
        raise RuntimeError("Recording failed or produced an empty file")


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--audio", type=str)
    g.add_argument("--record", action="store_true")
    p.add_argument("--device", type=str, default=":0")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--out-subpath", type=str, default="Meeting_Notes")
    p.add_argument("--format", choices=["md", "txt"], default="md")
    args = p.parse_args()

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

    print("Transcribing audio...")
    transcript = transcribe_audio(api_key, audio_path)
    if not transcript:
        print("No transcript returned.", file=sys.stderr)
        sys.exit(1)

    print("Generating meeting title...")
    meeting_title = generate_meeting_title(api_key, transcript)

    print("Generating meeting notes...")
    notes_md = generate_meeting_notes(api_key, transcript, meeting_title, timestamp)

    base_name = f"{safe_filename(meeting_title)} - Notes"

    if args.format == "txt":
        output_text = markdown_to_text(notes_md)
        out_path = out_dir / f"{base_name}.txt"
    else:
        output_text = notes_md
        out_path = out_dir / f"{base_name}.md"

    print("Saving output...")
    out_path.write_text(output_text, encoding="utf-8")
    print(f"Saved notes to: {out_path}")


if __name__ == "__main__":
    main()