# Audio to Meeting Notes

Record meeting audio (or use an existing audio file), transcribe it with OpenAI, and generate structured meeting notes as **Markdown or plain text**.

## Requirements
- macOS
- Conda (Miniconda or Anaconda)
- Python 3.9+
- OpenAI API key
- ffmpeg (needed for recording)

## Setup

```bash
conda create -n audio2notes python=3.10 -y
conda activate audio2notes
pip install requests
brew install ffmpeg
```

Set your API key in terminal:
```bash
export OPENAI_API_KEY="sk-..."
```

## Microphone Permission (macOS)
System Settings → Privacy & Security → Microphone  
Enable access for Terminal / iTerm / PyCharm / VS Code.

## List audio devices
Find the index for your microphone (for most laptops this is `0`):

```bash
python3 meeting2notes.py --list-devices
```

## Record audio and generate notes
```bash
python3 meeting2notes.py --record --device ":0"
```

Press **Enter** to stop recording.  
Progress messages will appear while the audio is transcribed and notes are generated.

## Use an existing audio file
```bash
python3 meeting2notes.py --audio "/path/to/audio.m4a"
```

## Output format

### Default (Markdown)
```bash
python3 meeting2notes.py --record --device ":0"
```

### Plain text
```bash
python3 meeting2notes.py --record --device ":0" --format txt
```

## Output location
Notes are saved to:
```
~/Documents/Meeting_Notes/<Meeting Title> - Notes.md
~/Documents/Meeting_Notes/<Meeting Title> - Notes.txt
```
