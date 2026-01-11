#!/usr/bin/env python3
"""
Meeting2Notes — macOS Menu Bar App

A professional menu bar utility for recording meetings and generating
AI-powered notes. Designed for minimal friction and maximum utility.
"""

from __future__ import annotations

import datetime as dt
import time
import logging
import os
import sys
import subprocess
import threading
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from enum import Enum

import rumps

# Ensure CFBundleIdentifier is present when running from a plain interpreter
# (not an app bundle). Rumps notifications require this key in the main bundle's
# Info.plist. We attempt two mitigations:
# 1) Set CFBundleIdentifier at runtime via PyObjC (Foundation.NSBundle)
# 2) Create a minimal Info.plist next to the interpreter if one is missing
#    (e.g., ~/miniforge3/bin/Info.plist) so rumps can initialize notifications.
try:
    from Foundation import NSBundle
    bundle = NSBundle.mainBundle()
    if bundle is not None:
        info = bundle.infoDictionary() or {}
        # Only set if missing or empty
        if not info.get("CFBundleIdentifier"):
            info["CFBundleIdentifier"] = "com.lizb8s.meeting2notes"
except Exception:
    # If PyObjC/Foundation isn't available for some reason, continue without crashing.
    pass

# Fallback: ensure Info.plist exists alongside the interpreter if missing.
# This addresses environments like Conda/miniforge where rumps expects
# an Info.plist at <env>/bin/Info.plist and errors if absent.
try:
    exe_dir = Path(sys.executable).resolve().parent
    plist_path = exe_dir / "Info.plist"
    if not plist_path.exists():
        minimal_plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.lizb8s.meeting2notes</string>
    <key>CFBundleName</key>
    <string>Meeting2Notes</string>
</dict>
</plist>
"""
        # Best-effort create; ignore errors to avoid crashing
        try:
            plist_path.write_text(minimal_plist, encoding="utf-8")
        except Exception:
            pass
except Exception:
    pass

from meeting2notes.transcribe import transcribe_audio_local
from meeting2notes.openai_client import (
    build_meeting_map,
    generate_meeting_title_from_map,
    generate_meeting_notes,
)
from meeting2notes.utils import iso_timestamp_local, safe_filename, markdown_to_text

# Python interpreter to use for CLI subprocess (can be overridden via env)
SUBPROC_PYBIN = os.environ.get("MEETING2NOTES_PY") or sys.executable

# Configure logging.
# Default: do not create a file logger so the app runs cleanly for users who
# don't need debug logs. Debug logging can be enabled from the menu (adds a
# file handler writing to ~/Library/Logs/meeting2notes.log).
LOG_PATH = Path.home() / "Library" / "Logs" / "meeting2notes.log"

logger = logging.getLogger("meeting2notes")
# Default to INFO for normal operations
logger.setLevel(logging.INFO)

# module-level file handler reference (None when logging is disabled)
_file_handler: logging.Handler | None = None


def enable_debug_logging(enable: bool = True) -> None:
    """
    Enable or disable debug file logging. When enabled a file handler is
    created writing DEBUG logs to LOG_PATH. When disabled the handler is
    removed and closed.
    """
    global _file_handler
    if enable and _file_handler is None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Truncate existing log so a new debug session starts clean
        try:
            with open(LOG_PATH, "w", encoding="utf-8"):
                pass
        except Exception:
            pass
        fh = logging.FileHandler(str(LOG_PATH))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.DEBUG)
        _file_handler = fh
        logger.debug("Debug logging enabled")
    elif not enable and _file_handler is not None:
        logger.debug("Disabling debug logging")
        logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
        logger.setLevel(logging.INFO)


def clear_debug_log() -> None:
    """
    Clear the debug log file (truncate to zero length) if it exists.
    This is used before starting a new transcription so the user sees only
    the current run's debug output when debugging is enabled.
    """
    try:
        if LOG_PATH.exists():
            # Truncate file
            with open(LOG_PATH, "w", encoding="utf-8"):
                pass
            # Also log to the (new) file handler if present
            logger.debug("Cleared debug log %s", LOG_PATH)
    except Exception:
        # Avoid raising from this helper; log to the default logger handler.
        try:
            logger.exception("Failed to clear debug log %s", LOG_PATH)
        except Exception:
            pass


def _normalize_path(p: Path) -> str:
    """
    Normalize a Path to a consistent string key used for the internal
    processing dictionary. Resolve and convert to string so the same file
    is identified regardless of how Path objects were constructed.
    """
    try:
        return str(Path(p).resolve())
    except Exception:
        return str(p)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path.home() / "Documents" / "Meeting_Notes"
MAX_RECENT_RECORDINGS = 5

# Clean monospace-friendly symbols for menu bar
ICON_IDLE = "◉"
ICON_RECORDING = "●"


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
        logger.warning("ffmpeg not found when listing devices")
        return [("0", "Default")]

    devices = []
    in_audio_section = False

    for line in (result.stderr + result.stdout).splitlines():
        if "AVFoundation audio devices" in line:
            in_audio_section = True
            continue
        if "AVFoundation video devices" in line:
            break
        if in_audio_section and "[" in line and "]" in line:
            try:
                idx = line.split("]")[0].split("[")[-1].strip()
                name = line.split("]", 1)[1].strip()
                if idx.isdigit():
                    devices.append((idx, name))
            except (IndexError, ValueError):
                continue

    return devices if devices else [("0", "Default")]


def record_audio(device_idx: str, output_path: Path) -> subprocess.Popen:
    """Start ffmpeg recording process."""
    try:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-y",
                "-f", "avfoundation",
                "-i", f":{device_idx}",
                "-ac", "1",
                "-ar", "16000",
                str(output_path)
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.debug("Started ffmpeg recording: device=%s output=%s", device_idx, output_path)
        return proc
    except FileNotFoundError as e:
        logger.exception("ffmpeg not found when starting recording")
        raise


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
        # Use string paths as keys to avoid Path identity/equality edge-cases
        self._processing: Dict[str, Stage] = {}
        # Track if we were processing on the previous tick to trigger UI refresh on transition
        self._was_processing: bool = False

        # Output format: "txt" or "md"
        self._output_format = "txt"

        # Load devices
        try:
            self._devices = get_audio_devices()
        except Exception:
            logger.exception("Failed to get audio devices; falling back to default")
            self._devices = [("0", "Default")]

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

        # Debug toggle (disabled by default)
        self._debug_item = rumps.MenuItem("Enable Debug Logging", callback=self._toggle_debug)
        self._debug_enabled = False

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
            self._debug_item,
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
        """Update the recent recordings submenu (in-place clear and rebuild)."""
        # Clear existing children safely
        for k in list(self._recordings_section.keys()):
            try:
                del self._recordings_section[k]
            except Exception:
                pass

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        recordings = sorted(
            OUTPUT_DIR.glob("*.m4a"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )[:MAX_RECENT_RECORDINGS]

        if not recordings:
            self._recordings_section.add(rumps.MenuItem("No recordings yet"))
            return

        for rec in recordings:
            # Format: "Jan 10, 2:30 PM" style
            try:
                mtime = dt.datetime.fromtimestamp(rec.stat().st_mtime)
                time_str = mtime.strftime("%b %d, %-I:%M %p")
            except Exception:
                time_str = rec.name

            rec_menu = rumps.MenuItem(time_str)

            key = _normalize_path(rec)
            if key in self._processing:
                stage = self._processing.get(key)
                stage_title = stage.menu_text if stage is not None else "Processing"
                rec_menu.add(rumps.MenuItem(stage_title))
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
        """Create a callback for transcription that delegates to a short wrapper thread
        to avoid blocking the rumps menu callback context.
        """
        def callback(_):
            logger.debug("Transcribe menu clicked for %s", path)

            def start_wrapper():
                try:
                    if not path.exists():
                        logger.warning("Requested transcription for missing file: %s", path)
                        rumps.notification(title="Transcription Failed", message="File not found.", sound=False)
                        return

                    # If the file's modification time is very recent, it may still be being written.
                    # Wait briefly to avoid reading a file that's actively being recorded.
                    if (time.time() - path.stat().st_mtime) < 2:
                        logger.debug("File %s appears to be recently modified; asking user to wait", path)
                        rumps.notification(
                            title="Transcription",
                            message="File still being written. Please wait a few seconds and try again.",
                            sound=False
                        )
                        return

                    # Start transcription (this method itself starts a background thread)
                    self._start_transcription(path)
                except Exception as e:
                    logger.exception("Error in transcribe click wrapper for %s: %s", path, e)
                    rumps.notification(title="Transcription Failed", message=str(e)[:100], sound=False)

            threading.Thread(target=start_wrapper, daemon=True).start()

        return callback

    def _make_reveal_callback(self, path: Path):
        """Create a callback to reveal file in Finder."""
        def callback(_):
            subprocess.run(["open", "-R", str(path)])
        return callback

    def _toggle_debug(self, _):
        """Toggle debug logging on/off from the menu.

        When enabling debug logging we also open the log file in the user's
        default editor so they can immediately inspect runtime output.
        """
        try:
            new_state = not getattr(self, "_debug_enabled", False)
            self._debug_enabled = bool(new_state)
            enable_debug_logging(self._debug_enabled)
            # Update menu title
            self._debug_item.title = "Disable Debug Logging" if self._debug_enabled else "Enable Debug Logging"

            if self._debug_enabled:
                # Notify and open the log file so the user can see debug output
                rumps.notification(
                    title="Debug Logging",
                    subtitle="Enabled",
                    message=str(LOG_PATH),
                    sound=False
                )
                try:
                    # Use macOS `open` to launch the log in the default app (TextEdit/Console)
                    subprocess.run(["open", str(LOG_PATH)], check=False)
                except Exception:
                    logger.exception("Failed to open log file %s", LOG_PATH)
            else:
                rumps.notification(
                    title="Debug Logging",
                    subtitle="Disabled",
                    message="",
                    sound=False
                )
        except Exception as e:
            logger.exception("Failed to toggle debug logging: %s", e)
            rumps.notification(title="Debug Logging", message=f"Error: {e}", sound=False)

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
            self._output_path = OUTPUT_DIR / f"Recording {timestamp}.m4a"

            self._process = record_audio(self._selected_device[0], self._output_path)
            self._start_time = dt.datetime.now()
            self._recording = True

            self._record_btn.title = "Stop Recording  ⌘R"
            self.title = f"{ICON_RECORDING} 0:00"

        except Exception as e:
            logger.exception("Recording failed: %s", e)
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
        now_processing = bool(self._processing)
        if self._recording and self._start_time:
            elapsed = (dt.datetime.now() - self._start_time).total_seconds()
            mins, secs = divmod(int(elapsed), 60)
            self.title = f"{ICON_RECORDING} {mins}:{secs:02d}"
        elif now_processing:
            # Show processing status in menu bar
            # Get the most recent stage being processed
            stage = list(self._processing.values())[-1]
            self.title = stage.bar_text
        else:
            if self.title != ICON_IDLE:
                self.title = ICON_IDLE
            # If we just finished processing, force a recordings submenu refresh
            if self._was_processing and not now_processing:
                try:
                    self._refresh_recordings()
                except Exception:
                    logger.exception("Failed to refresh recordings after processing finished")
        self._was_processing = now_processing

    # ─────────────────────────────────────────────────────────────────────────
    # Transcription
    # ─────────────────────────────────────────────────────────────────────────

    def _start_transcription(self, audio_path: Path):
        """Start background transcription."""
        logger.debug("Transcription requested for %s", audio_path)
        key = _normalize_path(audio_path)
        if key in self._processing:
            logger.debug("Transcription already in progress for %s", audio_path)
            return

        self._processing[key] = Stage.TRANSCRIBING
        self._refresh_recordings()

        thread = threading.Thread(
            target=self._transcribe_worker,
            args=(audio_path,),
            daemon=True
        )
        thread.start()
        logger.debug("Transcription thread started for %s", audio_path)

    def _set_stage(self, audio_path: Path, stage: Stage):
        """Update the processing stage for a file only if it's still tracked."""
        key = _normalize_path(audio_path)
        # Avoid setting stages for files that are no longer being processed.
        if key not in self._processing:
            return
        self._processing[key] = stage

        # Schedule UI refresh on main thread
        rumps.Timer(lambda _: self._refresh_recordings(), 0.05).start()

    def _transcribe_worker(self, audio_path: Path):
        """Background transcription pipeline.

        NOTE: run the full transcription + LLM pipeline in a separate Python
        process (via the CLI) to avoid deadlocks / multiprocessing issues
        that can occur when faster-whisper / torch spawn processes from a
        non-main thread inside a GUI process.
        """
        logger.debug("Transcription worker (wrapper) started for %s", audio_path)
        try:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")

            # Debug logging is session-based; do not truncate here to avoid losing
            # early lines from this run in the UI-opened log viewer.
            # (Log file is truncated when enabling debug logging instead.)

            # Start a small UI-stage cycler so the user sees progress while the
            # heavy work runs in the subprocess (we can't get intermediate
            # stages back from the subprocess easily).
            stages_cycle = [Stage.TRANSCRIBING, Stage.ANALYZING, Stage.TITLING, Stage.WRITING]
            cycle_idx = {"i": 0}

            def _cycle_stage(_):
                try:
                    st = stages_cycle[cycle_idx["i"] % len(stages_cycle)]
                    self._set_stage(audio_path, st)
                    cycle_idx["i"] += 1
                except Exception:
                    logger.exception("Stage cycler failed for %s", audio_path)

            cycler = rumps.Timer(_cycle_stage, 1.0)
            # Start with the first stage immediately
            _cycle_stage(None)
            cycler.start()

            # Run the CLI in a separate process which will perform the full
            # transcription + analysis + notes generation and write the output.
            cmd = [
                SUBPROC_PYBIN, "-m", "meeting2notes.cli",
                "--audio", str(audio_path),
                "--format", self._output_format,
            ]
            logger.debug("Spawning CLI subprocess (%s): %s", SUBPROC_PYBIN, " ".join(map(str, cmd)))
            r = subprocess.run(cmd, capture_output=True, text=True)
            # Stop the UI cycler now that the subprocess has finished
            try:
                cycler.stop()
            except Exception:
                logger.exception("Failed to stop stage cycler for %s", audio_path)

            # Clear the processing marker immediately so the UI updates (menu item
            # will be replaced with the "Transcribe" action) while we handle results.
            try:
                self._processing.pop(_normalize_path(audio_path), None)
                rumps.Timer(lambda _: self._refresh_recordings(), 0.05).start()
            except Exception:
                logger.exception("Failed to clear processing state for %s", audio_path)

            if r.returncode != 0:
                # Friendly handling if the Python used for the subprocess is missing dependencies
                missing_fw = "No module named 'faster_whisper'" in (r.stderr or "") or "No module named 'faster_whisper'" in (r.stdout or "")
                if missing_fw:
                    msg = (
                        f"Interpreter missing faster-whisper: {SUBPROC_PYBIN}\n"
                        f"Install dependencies:\n"
                        f'  "{SUBPROC_PYBIN}" -m pip install faster-whisper ctranslate2 requests\n'
                        f"Or set MEETING2NOTES_PY to a venv with the packages installed."
                    )
                    logger.error(msg)
                    rumps.Timer(lambda _: rumps.notification(
                        title="Dependency missing",
                        subtitle="faster-whisper not installed",
                        message=msg,
                        sound=False
                    ), 0).start()
                    return
                logger.error("CLI subprocess failed: returncode=%s stdout=%s stderr=%s",
                             r.returncode, r.stdout, r.stderr)
                raise RuntimeError(f"Transcription process failed: {r.stderr.strip()[:200]}")

            # If CLI succeeded, attempt to detect output file from stdout or
            # fall back to scanning OUTPUT_DIR for newest notes file.
            out_path = None
            for line in r.stdout.splitlines():
                if "Saved notes to:" in line:
                    try:
                        out_path_str = line.split("Saved notes to:")[-1].strip()
                        out_path = Path(out_path_str)
                        break
                    except Exception:
                        continue

            if not out_path:
                # Fallback: look for newest .md/.txt file in OUTPUT_DIR
                candidates = sorted(OUTPUT_DIR.glob("*.md")) + sorted(OUTPUT_DIR.glob("*.txt"))
                if candidates:
                    out_path = max(candidates, key=lambda p: p.stat().st_mtime)

            if out_path and out_path.exists():
                logger.debug("Transcription succeeded, opening %s", out_path)
                rumps.Timer(lambda _: rumps.notification(title="Notes Ready", subtitle=out_path.name, message="", sound=True), 0).start()
                rumps.Timer(lambda _: subprocess.run(["open", str(out_path)]), 0).start()
            else:
                logger.warning("Transcription finished but no output file found")
                rumps.Timer(lambda _: rumps.notification(title="Notes Ready", subtitle="No notes file found", message="", sound=True), 0).start()

        except Exception as e:
            logger.exception("Transcription failed for %s: %s", audio_path, e)
            rumps.Timer(lambda _: rumps.notification(
                title="Transcription Failed",
                subtitle="",
                message=str(e)[:200],
                sound=False
            ), 0).start()
        finally:
            # Ensure processing state is cleared and rebuild menu on main thread so
            # stale "Processing" child items are removed reliably.
            key = _normalize_path(audio_path)
            self._processing.pop(key, None)

            # Aggressively refresh UI on the main thread to eliminate any stale
            # "Transcribing..." entries that may linger due to rumps menu caching.
            def _post_finish_refresh(_):
                try:
                    # Reset menu bar title and rebuild the recordings list
                    self.title = ICON_IDLE
                    self._refresh_recordings()
                except Exception:
                    logger.exception("post-finish refresh failed for %s", key)

            # Staggered refreshes to catch late UI updates
            rumps.Timer(_post_finish_refresh, 0.05).start()
            rumps.Timer(lambda _: self._refresh_recordings(), 0.5).start()
            rumps.Timer(lambda _: self._refresh_recordings(), 1.0).start()

            # Full menu rebuild shortly after, as a final guarantee
            rumps.Timer(lambda _: self._setup_menu(), 0.2).start()

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
    try:
        Meeting2NotesApp().run()
    except Exception:
        logger.exception("Unhandled exception in menu app")
        raise


if __name__ == "__main__":
    main()
