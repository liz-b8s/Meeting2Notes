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

From the project directory:

```bash
pip install -e .
```

This installs two commands:
- `m2n` - starts the menu bar app
- `meeting2notes` - CLI for processing audio files

### Starting the app

```bash
m2n &
```

The `&` runs it in the background so you can close the terminal. Look for **M2N** in your menu bar.

Only one instance can run at a time. If you try to start a second instance, you'll see: "Meeting2Notes is already running."

### Features

- **M2N** in menu bar (changes to **⏺ REC** with timer when recording)
- Start/stop recording with **⌘R**
- Select audio input device (MacBook mic, Bluetooth headphones, USB mics, etc.)
- Choose output format (Plain Text or Markdown)
- View recent recordings and transcribe with one click
- Live progress indicators during transcription
- Records in WAV format (lossless) at 16kHz for optimal transcription quality

### Stopping the app

From the menu bar:
- Click **M2N** → **Quit Meeting2Notes**

Or from terminal:
```bash
pkill -f "menubar.py"
```

The app stays quit until you manually start it again.

---

## Run from anywhere

After running `pip install -e .` (see Menu Bar App section), you can use these commands from anywhere:

```bash
# Start the menu bar app
m2n &

# Process an audio file via CLI
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
