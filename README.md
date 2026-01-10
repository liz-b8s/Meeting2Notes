## Meeting2Notes

Simple tool to transcribe local audio (via faster-whisper) and generate structured meeting notes using an LLM.

### What it does
- Re-encodes or records audio, transcribes locally with faster-whisper.
- Calls an LLM (OpenAI) to extract a meeting structure, generate a title, and produce Notion-style notes.
- Saves notes (Markdown or plain text) with transcript and a small cost breakdown.

### Prerequisites
- Python 3.10+ (use a virtual environment).
- ffmpeg and ffprobe installed and on PATH (macOS: brew install ffmpeg).
- Python packages: faster-whisper, ctranslate2 (optional/platform-dependent), requests.
  Example:
    python -m pip install faster-whisper ctranslate2 requests

- An OpenAI API key set in your environment:
    export OPENAI_API_KEY="sk-..."

### Quick start (project root)
1. Make the helper script executable (one-time):
   chmod +x run.sh

2. Run the CLI:
   ./run.sh --help

3. Typical commands:
   - Transcribe an audio file:
     ./run.sh --audio /path/to/meeting.m4a

   - Record (macOS avfoundation; press Enter to stop):
     ./run.sh --record --device ":0"

   - Output plain text instead of Markdown:
     ./run.sh --audio /path/to/meeting.m4a --format txt

### Run from anywhere

- Create ~/bin, make the script executable, and symlink:
    chmod +x run.sh
    mkdir -p ~/bin
    ln -sf "$(pwd)/run.sh" ~/bin/meeting2notes

- Ensure ~/bin is in your PATH (for zsh):
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
    source ~/.zshrc

- Then run:
    meeting2notes --help
    meeting2notes --audio /path/to/meeting.m4a

### Notes and recommendations
- Local transcription keeps audio on your machine, avoiding API costs for transcription.
- The LLM calls (structure/title/notes) send transcripts to OpenAI — do not upload sensitive data unless you are comfortable.
- Consider adding unit tests for utils and openai_client (mock requests), and mocks for audio/transcription during CI.

### Troubleshooting
- Permission denied running ./run.sh: run chmod +x run.sh
- Command not found after symlink: ensure ~/bin is in PATH and reload your shell
- ffmpeg not found: install it and ensure it's on PATH

