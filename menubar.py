#!/usr/bin/env python3
"""
Meeting2Notes — macOS Menu Bar App

A professional menu bar utility for recording meetings and generating
AI-powered notes. Designed for minimal friction and maximum utility.
"""

from __future__ import annotations

import atexit
import datetime as dt
import fcntl
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from enum import Enum

import rumps


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Lock
# ─────────────────────────────────────────────────────────────────────────────

LOCK_FILE = Path.home() / ".meeting2notes.lock"
_lock_fd = None


def _is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_singleton_lock() -> bool:
    """Ensure only one instance runs. Returns True if lock acquired."""
    global _lock_fd

    # Check for stale lock file
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
            if not _is_pid_running(old_pid):
                # Stale lock, remove it
                LOCK_FILE.unlink(missing_ok=True)
        except (ValueError, OSError):
            # Invalid lock file, remove it
            LOCK_FILE.unlink(missing_ok=True)

    try:
        _lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except (IOError, OSError):
        return False


def release_singleton_lock():
    """Release the singleton lock."""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
            _lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

from meeting2notes.transcribe import transcribe_audio_local
from meeting2notes.openai_client import (
    build_meeting_map,
    generate_meeting_title_from_map,
    generate_meeting_notes,
)
from meeting2notes.utils import iso_timestamp_local, safe_filename, markdown_to_text


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path.home() / "Documents" / "Meeting_Notes"
MAX_RECENT_RECORDINGS = 5

# Menu bar icons - using text for visibility
ICON_IDLE = "M2N"
ICON_RECORDING = "⏺ REC"


# ─────────────────────────────────────────────────────────────────────────────
# Processing Stage Tracking
# ─────────────────────────────────────────────────────────────────────────────

class Stage(Enum):
    TRANSCRIBING = ("Transcribing", "⚙", 1, 4)
    ANALYZING = ("Analyzing", "◐", 2, 4)
    TITLING = ("Generating title", "◑", 3, 4)
    WRITING = ("Writing notes", "◕", 4, 4)

    def __init__(self, label: str, icon: str, step: int, total: int):
        self.label = label
        self.icon = icon
        self.step = step
        self.total = total

    @property
    def menu_text(self) -> str:
        return f"{self.icon} {self.label}... ({self.step}/{self.total})"

    @property
    def bar_text(self) -> str:
        return f"{self.icon} {self.step}/{self.total}"


# ─────────────────────────────────────────────────────────────────────────────
# Audio Device Utilities
# ─────────────────────────────────────────────────────────────────────────────

def get_audio_devices() -> List[Tuple[str, str]]:
    """Get available macOS audio input devices via ffmpeg/avfoundation."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return [("0", "Default")]

    devices = []
    in_audio_section = False

    for line in (result.stderr + result.stdout).splitlines():
        # Audio devices come AFTER video devices in ffmpeg output
        if "AVFoundation audio devices" in line:
            in_audio_section = True
            continue
        if in_audio_section:
            # Stop if we hit an error line
            if "Error opening" in line:
                break
            # Parse device lines like: [AVFoundation indev @ 0x...] [0] Device Name
            if "] [" in line:
                try:
                    # Extract the device index and name from second bracket pair
                    after_first = line.split("] ", 1)[1]  # "[0] Device Name"
                    idx = after_first.split("]")[0].strip("[ ")
                    name = after_first.split("]", 1)[1].strip()
                    if idx.isdigit():
                        devices.append((idx, name))
                except (IndexError, ValueError):
                    continue

    return devices if devices else [("0", "Default")]


def record_audio(device_idx: str, output_path: Path) -> subprocess.Popen:
    """Start ffmpeg recording process.

    Records to WAV format (PCM 16-bit) at 16kHz for reliable quality
    and optimal Whisper transcription performance.
    """
    return subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-y",
            "-f", "avfoundation",
            "-i", f":{device_idx}",
            "-ac", "1",           # Mono
            "-ar", "16000",       # 16kHz optimal for speech/Whisper
            "-c:a", "pcm_s16le",  # 16-bit PCM (lossless)
            str(output_path)
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Menu Bar Application
# ─────────────────────────────────────────────────────────────────────────────

class Meeting2NotesApp(rumps.App):
    """Professional menu bar app for meeting recording and transcription."""

    def __init__(self):
        super().__init__(ICON_IDLE, quit_button=None)

        # State
        self._recording = False
        self._process: Optional[subprocess.Popen] = None
        self._start_time: Optional[dt.datetime] = None
        self._output_path: Optional[Path] = None

        # Track processing stages per file: {path: Stage}
        self._processing: Dict[Path, Stage] = {}

        # Output format: "txt" or "md"
        self._output_format = "txt"

        # Load devices
        self._devices = get_audio_devices()
        self._selected_device = self._devices[0]

        # Build menu
        self._setup_menu()

        # Timer for elapsed time display
        self._timer = rumps.Timer(self._tick, 1)
        self._timer.start()

    def _setup_menu(self):
        """Build the menu structure."""

        # Primary action
        self._record_btn = rumps.MenuItem(
            "Start Recording  ⌘R",
            callback=self._toggle_recording,
            key="r"
        )

        # Device picker (flat list with checkmarks)
        self._device_items = {}
        device_section = []
        for idx, name in self._devices:
            # Truncate long device names
            display_name = name[:35] + "…" if len(name) > 35 else name
            item = rumps.MenuItem(display_name, callback=self._make_device_callback(idx, name))
            item.state = 1 if idx == self._selected_device[0] else 0
            self._device_items[idx] = item
            device_section.append(item)

        # Recent recordings
        self._recordings_section = rumps.MenuItem("Recent Recordings")
        self._refresh_recordings()

        # Output format selector
        self._format_items = {}
        self._format_txt = rumps.MenuItem("Plain Text (.txt)", callback=lambda _: self._set_format("txt"))
        self._format_md = rumps.MenuItem("Markdown (.md)", callback=lambda _: self._set_format("md"))
        self._format_txt.state = 1  # Default to txt
        self._format_items["txt"] = self._format_txt
        self._format_items["md"] = self._format_md

        format_section = rumps.MenuItem("Output Format")
        format_section.add(self._format_txt)
        format_section.add(self._format_md)

        # Assemble menu
        self.menu = [
            self._record_btn,
            None,
            *device_section,
            None,
            self._recordings_section,
            format_section,
            None,
            rumps.MenuItem("Open Notes Folder", callback=self._open_folder, key="o"),
            None,
            rumps.MenuItem("Quit Meeting2Notes", callback=self._quit, key="q"),
        ]

    def _make_device_callback(self, idx: str, name: str):
        """Create a callback for device selection."""
        def callback(_):
            self._selected_device = (idx, name)
            for dev_idx, item in self._device_items.items():
                item.state = 1 if dev_idx == idx else 0
        return callback

    def _set_format(self, fmt: str):
        """Set the output format."""
        self._output_format = fmt
        for f, item in self._format_items.items():
            item.state = 1 if f == fmt else 0

    def _refresh_recordings(self):
        """Update the recent recordings submenu."""
        # Clear existing
        for key in list(self._recordings_section.keys()):
            del self._recordings_section[key]

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Include both .wav (new) and .m4a (legacy) recordings
        all_recordings = list(OUTPUT_DIR.glob("*.wav")) + list(OUTPUT_DIR.glob("*.m4a"))
        recordings = sorted(
            all_recordings,
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:MAX_RECENT_RECORDINGS]

        if not recordings:
            self._recordings_section.add(rumps.MenuItem("No recordings yet"))
            return

        for rec in recordings:
            # Format: "Jan 10, 2:30 PM" style
            mtime = dt.datetime.fromtimestamp(rec.stat().st_mtime)
            time_str = mtime.strftime("%b %d, %-I:%M %p")

            rec_menu = rumps.MenuItem(time_str)

            # Check if currently processing
            if rec in self._processing:
                stage = self._processing[rec]
                rec_menu.add(rumps.MenuItem(stage.menu_text))
            else:
                rec_menu.add(rumps.MenuItem(
                    "Transcribe",
                    callback=self._make_transcribe_callback(rec)
                ))

            rec_menu.add(rumps.MenuItem(
                "Show in Finder",
                callback=self._make_reveal_callback(rec)
            ))

            self._recordings_section.add(rec_menu)

    def _make_transcribe_callback(self, path: Path):
        """Create a callback for transcription."""
        def callback(_):
            self._start_transcription(path)
        return callback

    def _make_reveal_callback(self, path: Path):
        """Create a callback to reveal file in Finder."""
        def callback(_):
            subprocess.run(["open", "-R", str(path)])
        return callback

    # ─────────────────────────────────────────────────────────────────────────
    # Recording
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_recording(self, _):
        """Start or stop recording."""
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        """Begin recording audio."""
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = dt.datetime.now().strftime("%Y-%m-%d %H.%M.%S")
            self._output_path = OUTPUT_DIR / f"Recording {timestamp}.wav"

            self._process = record_audio(self._selected_device[0], self._output_path)
            self._start_time = dt.datetime.now()
            self._recording = True

            self._record_btn.title = "Stop Recording  ⌘R"
            self.title = f"{ICON_RECORDING} 0:00"

        except Exception as e:
            rumps.notification(
                title="Recording Failed",
                subtitle="",
                message=str(e),
                sound=False
            )

    def _stop_recording(self):
        """Stop recording and save file."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

        duration = ""
        if self._start_time:
            elapsed = (dt.datetime.now() - self._start_time).total_seconds()
            mins, secs = divmod(int(elapsed), 60)
            duration = f" • {mins}:{secs:02d}"

        self._process = None
        self._recording = False
        self._start_time = None

        self._record_btn.title = "Start Recording  ⌘R"
        self.title = ICON_IDLE

        self._refresh_recordings()

        if self._output_path and self._output_path.exists():
            rumps.notification(
                title="Recording Saved",
                subtitle=duration.strip(" •"),
                message="Click to transcribe",
                sound=False
            )

    def _tick(self, _):
        """Update elapsed time display and processing status."""
        if self._recording and self._start_time:
            elapsed = (dt.datetime.now() - self._start_time).total_seconds()
            mins, secs = divmod(int(elapsed), 60)
            self.title = f"{ICON_RECORDING} {mins}:{secs:02d}"
        elif self._processing:
            # Show processing status in menu bar
            # Get the most recent stage being processed
            stage = list(self._processing.values())[-1]
            self.title = stage.bar_text
        elif self.title != ICON_IDLE:
            self.title = ICON_IDLE

    # ─────────────────────────────────────────────────────────────────────────
    # Transcription
    # ─────────────────────────────────────────────────────────────────────────

    def _start_transcription(self, audio_path: Path):
        """Start background transcription."""
        if audio_path in self._processing:
            return

        self._processing[audio_path] = Stage.TRANSCRIBING
        self.title = Stage.TRANSCRIBING.bar_text  # Update icon immediately
        self._refresh_recordings()

        thread = threading.Thread(
            target=self._transcribe_worker,
            args=(audio_path,),
            daemon=True
        )
        thread.start()

    def _set_stage(self, audio_path: Path, stage: Stage):
        """Update the processing stage for a file."""
        self._processing[audio_path] = stage
        # Schedule UI refresh on main thread (both icon and menu)
        def refresh(_):
            if self._processing:
                s = list(self._processing.values())[-1]
                self.title = s.bar_text
            self._refresh_recordings()
        rumps.Timer(refresh, 0.05).start()

    def _transcribe_worker(self, audio_path: Path):
        """Background transcription pipeline."""
        try:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")

            # Stage 1: Transcribe audio
            self._set_stage(audio_path, Stage.TRANSCRIBING)
            transcript = transcribe_audio_local(audio_path)
            if not transcript:
                raise RuntimeError("Transcription failed")

            # Stage 2: Analyze and build meeting map
            self._set_stage(audio_path, Stage.ANALYZING)
            meeting_map, _ = build_meeting_map(api_key, transcript)

            # Stage 3: Generate title
            self._set_stage(audio_path, Stage.TITLING)
            title, _ = generate_meeting_title_from_map(api_key, meeting_map)

            # Stage 4: Write notes
            self._set_stage(audio_path, Stage.WRITING)
            notes_md, _ = generate_meeting_notes(
                api_key, transcript, meeting_map, title, iso_timestamp_local()
            )

            # Save in selected format
            if self._output_format == "txt":
                content = markdown_to_text(notes_md)
                ext = "txt"
            else:
                content = notes_md
                ext = "md"

            out_path = OUTPUT_DIR / f"{safe_filename(title)} - Notes.{ext}"
            out_path.write_text(content, encoding="utf-8")

            rumps.notification(
                title="Notes Ready",
                subtitle=title[:50],
                message="",
                sound=True
            )

            # Open the notes file
            subprocess.run(["open", str(out_path)])

        except Exception as e:
            rumps.notification(
                title="Transcription Failed",
                subtitle="",
                message=str(e)[:100],
                sound=False
            )
        finally:
            self._processing.pop(audio_path, None)
            # Refresh UI on main thread (both icon and menu)
            def cleanup(_):
                if self._processing:
                    s = list(self._processing.values())[-1]
                    self.title = s.bar_text
                else:
                    self.title = ICON_IDLE
                self._refresh_recordings()
            rumps.Timer(cleanup, 0.1).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────────────────

    def _open_folder(self, _):
        """Open the notes folder in Finder."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(OUTPUT_DIR)])

    def _quit(self, _):
        """Clean shutdown."""
        if self._recording:
            self._stop_recording()
        rumps.quit_application()


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Ensure only one instance runs
    if not acquire_singleton_lock():
        print("Meeting2Notes is already running.", file=sys.stderr)
        sys.exit(1)

    # Clean up lock on exit
    atexit.register(release_singleton_lock)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    Meeting2NotesApp().run()


if __name__ == "__main__":
    main()
