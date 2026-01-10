## Meeting2Notes

A simple tool to transcribe local audio (via `faster-whisper`) and generate structured meeting notes using an LLM.

---

## What it does

- Re-encodes or records audio and transcribes locally with `faster-whisper`.
- Calls an LLM (OpenAI) to extract meeting structure, generate a title, and produce Notion-style notes.
- Saves notes (Markdown or plain text) along with the transcript and a small cost breakdown.

---

## Prerequisites

- Python 3.10+ (use a virtual environment).
- `ffmpeg` and `ffprobe` installed and available on `PATH`  
  (macOS: `brew install ffmpeg`).
- Python packages:
  - `faster-whisper`
  - `ctranslate2` (optional / platform-dependent)
  - `requests`

```bash
python -m pip install faster-whisper ctranslate2 requests
```

- An OpenAI API key set in your environment:

```bash
export OPENAI_API_KEY="sk-..."
```

---

## Quick start (project root)

1. Make the helper script executable (one-time):

```bash
chmod +x run.sh
```

2. View CLI help:

```bash
./run.sh --help
```

3. Typical commands:

- Transcribe an audio file:

```bash
./run.sh --audio /path/to/meeting.m4a
```

- Record audio (macOS `avfoundation`; press Enter to stop):

```bash
./run.sh --record --device ":0"
```

- Output plain text instead of Markdown:

```bash
./run.sh --audio /path/to/meeting.m4a --format txt
```

---

## Menu Bar App (macOS)

For a more convenient experience, use the menu bar app instead of the CLI.

### Install

```bash
# Install the menu bar dependency
pip install rumps

# Run it
python menubar.py
```

### Auto-start on login

To have the app always running in your menu bar:

1. Create a Launch Agent:

```bash
cat > ~/Library/LaunchAgents/com.meeting2notes.menubar.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.meeting2notes.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/Meeting2Notes/menubar.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>OPENAI_API_KEY</key>
        <string>sk-your-api-key-here</string>
    </dict>
</dict>
</plist>
EOF
```

2. Edit the plist to set:
   - The correct path to `python3` (run `which python3`)
   - The correct path to `menubar.py`
   - Your `OPENAI_API_KEY`

3. Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.meeting2notes.menubar.plist
```

### Features

- **◉** icon in menu bar (changes to **●** with timer when recording)
- Start/stop recording with **⌘R**
- Select audio input device
- Choose output format (Plain Text or Markdown)
- View recent recordings and transcribe with one click
- Live progress indicators during transcription

### Manage

```bash
# Stop the app
launchctl unload ~/Library/LaunchAgents/com.meeting2notes.menubar.plist

# Start the app
launchctl load ~/Library/LaunchAgents/com.meeting2notes.menubar.plist

# Remove auto-start
rm ~/Library/LaunchAgents/com.meeting2notes.menubar.plist
```

---

## Run from anywhere

1. Create `~/bin`, make the script executable, and symlink it:

```bash
chmod +x run.sh
mkdir -p ~/bin
ln -sf "$(pwd)/run.sh" ~/bin/meeting2notes
```

2. Ensure `~/bin` is on your `PATH` (for `zsh`):

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

3. Run from anywhere:

```bash
meeting2notes --help
meeting2notes --audio /path/to/meeting.m4a
```

---

## Notes and recommendations

- Local transcription keeps audio on your machine and avoids API costs for transcription.
- LLM calls (structure, title, notes) send transcripts to OpenAI. Do not upload sensitive data unless you are comfortable.
- Consider adding unit tests for `utils` and `openai_client` (mocking requests), and mocks for audio/transcription during CI.

---

## Troubleshooting

- **Permission denied running `./run.sh`**  
  Run:
  ```bash
  chmod +x run.sh
  ```

- **Command not found after symlink**  
  Ensure `~/bin` is on `PATH` and reload your shell.

- **`ffmpeg` not found**  
  Install it and ensure it is available on `PATH`.
