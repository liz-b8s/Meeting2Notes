Meeting2Notes

Menu bar tool and CLI for recording meetings (ffmpeg/avfoundation), transcribing locally (faster-whisper), and generating structured notes (OpenAI). No packaging required. Use a single command from anywhere: meeting2notes.

What you can do
- Launch the macOS menu bar utility to record and transcribe from the status bar.
- Or use the CLI to record/transcribe directly from the terminal.
- Local transcription (faster-whisper); OpenAI used for structure/title/notes.

Prerequisites
- macOS, Python 3.10+ (recommended to use a virtual environment).
- ffmpeg (and ffprobe) installed and on PATH:
  brew install ffmpeg
- Python packages:
  python -m pip install faster-whisper ctranslate2 requests rumps
- Environment:
  export OPENAI_API_KEY="sk-..."

Install the meeting2notes command (one-time)
- From the project root:
  chmod +x bin/meeting2notes
  mkdir -p ~/bin
  ln -sf "$(pwd)/bin/meeting2notes" ~/bin/meeting2notes
  echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
  source ~/.zshrc

- After that, you can run meeting2notes from any directory.

Select the Python interpreter for the menubar (recommended)
- The menubar spawns a subprocess to run the CLI. By default it uses the same Python that launched the menubar. If that Python does not have the dependencies (faster-whisper, ctranslate2, requests), set MEETING2NOTES_PY to a venv that does.
- One-time (persistent) setup for zsh:
  echo 'export MEETING2NOTES_PY="/full/path/to/venv/bin/python"' >> ~/.zshrc
  source ~/.zshrc
  Example (Conda/miniforge env):
  echo 'export MEETING2NOTES_PY=/Users/$(whoami)/miniforge3/envs/audio2notes/bin/python' >> ~/.zshrc
  source ~/.zshrc

- One-off for the current terminal session only:
  export MEETING2NOTES_PY="/full/path/to/venv/bin/python"

- Ensure the chosen interpreter has the required packages:
  "$MEETING2NOTES_PY" -m pip install faster-whisper ctranslate2 requests

- You can confirm which interpreter is used by enabling “Enable Debug Logging” in the menubar; the log shows the interpreter path it spawns.


Usage
- Launch the menu bar app:
  meeting2notes menubar

- Record from the command line (press Enter to stop):
  meeting2notes --record --device ":0"

- Transcribe an existing audio file:
  meeting2notes --audio "/path/to/meeting.m4a" --format txt

- List audio devices (macOS avfoundation):
  meeting2notes --list-devices

Menu bar notes
- Click Start Recording ⌘R to record; stop to save under ~/Documents/Meeting_Notes.
- Under Recent Recordings, click Transcribe to generate notes. The stage cycles 1→4 and the menu resets to “Transcribe” when done.
- Debug logging is OFF by default. Toggle “Enable Debug Logging” in the menu to create and open ~/Library/Logs/meeting2notes.log. The log is truncated when you enable debugging.

Troubleshooting
- ffmpeg not found:
  brew install ffmpeg
  Make sure /opt/homebrew/bin is in PATH (Apple Silicon).
- OPENAI_API_KEY not set:
  export OPENAI_API_KEY="sk-..."
- Microphone permission:
  First run from Terminal to accept the prompt; or grant Terminal (or your shell) Microphone access in System Settings → Privacy & Security → Microphone.
- If the menu seems stale:
  Toggle “Enable Debug Logging” and rerun; check the log at ~/Library/Logs/meeting2notes.log.

Developer notes
- CLI entrypoint:
  python -m meeting2notes.cli --help
- Modules:
  meeting2notes/audio.py, transcribe.py, openai_client.py, io.py, utils.py, auth.py, timing.py, cli.py
- Menubar app:
  menubar.py (uses rumps; spawns the CLI as a subprocess to keep the UI responsive).

Git workflow tip (avoid losing edits)
- Create a feature branch and rebase on origin’s default branch:
  BR=$(git remote show origin | sed -n 's/ *HEAD branch: //p')
  git fetch origin
  git switch -c menu-ui-fixes
  git add -A && git commit -m "Menubar + CLI fixes"
  git switch "$BR" && git pull --rebase origin "$BR"
  git switch menu-ui-fixes && git rebase "$BR"
  git push -u origin menu-ui-fixes


Recommended environment setup (auto-detected)
- The launcher tries MEETING2NOTES_PY first; if not set, it auto-detects:
  1) ~/miniforge3/envs/audio2notes/bin/python
  2) $CONDA_PREFIX/bin/python (active conda env)
  3) .venv/bin/python in the repo
  4) Fallback: python3 on PATH

Option A — Create a repo-local venv (auto-detected)
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install faster-whisper ctranslate2 requests rumps
  # After this, meeting2notes will auto-detect .venv; no extra config needed.

Option B — Create a conda/miniforge env named audio2notes (auto-detected)
  conda create -n audio2notes python=3.10 -y
  conda activate audio2notes
  python -m pip install --upgrade pip
  python -m pip install faster-whisper ctranslate2 requests rumps
  # The launcher will auto-detect ~/miniforge3/envs/audio2notes/bin/python.

Option C — Use a custom env and set MEETING2NOTES_PY explicitly
  # One-off for this terminal:
  export MEETING2NOTES_PY="/full/path/to/venv/bin/python"
  # Persistent for zsh:
  echo 'export MEETING2NOTES_PY="/full/path/to/venv/bin/python"' >> ~/.zshrc
  source ~/.zshrc

Verify environment quickly
  meeting2notes doctor
  # Prints the interpreter used, checks ffmpeg on PATH, shows OPENAI_API_KEY presence,
  # and verifies Python deps. If anything is missing, it prints exact pip commands.

Notes
- Ensure ffmpeg is installed (brew install ffmpeg) and on PATH.
- Set export OPENAI_API_KEY="sk-..." in your shell profile or before running.
- You can confirm the interpreter used by enabling “Enable Debug Logging” in the menubar; the log shows the path it spawns.
