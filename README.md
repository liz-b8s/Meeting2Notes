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
