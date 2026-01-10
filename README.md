# Meeting2Notes

Record meeting audio (or use an existing audio file), **transcribe locally for free** using **faster-whisper**, then 
use OpenAI (GPT) to generate detailed meeting notes.

Outputs as **Markdown or plain text**.

---

## Requirements
- macOS
- Conda (Miniconda or Anaconda)
- Python 3.9+ (recommended: 3.10)
- OpenAI API key (for map/title/notes)
- ffmpeg + ffprobe (recording + audio handling)
- faster-whisper + ctranslate2 (local transcription)

---

## Setup

### 1) Install ffmpeg

```bash
brew install ffmpeg
```

Verify:

```bash
ffmpeg -version
ffprobe -version
```

---

### 2) Create + activate the Conda environment

```bash
conda create -n audio2notes python=3.10 -y
conda activate audio2notes
```

Install dependencies:

```bash
pip install -U requests faster-whisper ctranslate2
```

Optional (only if you want CUDA detection on machines with NVIDIA GPUs):

```bash
pip install -U torch
```

---

### 3) Set your OpenAI API key

In your terminal:

```bash
export OPENAI_API_KEY="sk-..."
```

To make it permanent:

```bash
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc
source ~/.zshrc
```


---

### 4) Allow microphone access (macOS)

System Settings → **Privacy & Security → Microphone**  
Enable access for whichever app you use to run the script (Terminal / iTerm / VS Code etc.).

---

## Using the tool

### Transcribe an existing audio file

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --format txt
```

Markdown output:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --format md
```

### Record a meeting (macOS)

List input devices:

```bash
python meeting2notes.py --list-devices
```

Record (default device `:0`):

```bash
python meeting2notes.py --record --device ":0" --format txt
```

Press **Enter** to stop recording.

---

## Debug timing mode

Your script is quiet by default. To get timestamped step timings + detailed progress:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --format txt --debug_timing
```

---

## Long audio files

- If audio duration is **> 10 minutes**, your script **automatically splits into chunks** (default: 10-minute chunks) and transcribes chunk-by-chunk.
- You can change chunk size:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --chunk-seconds 900 --format txt
```

(Example above: 15-minute chunks)

---

## faster-whisper performance

### Model size

Default is:

- `--whisper-model small`

You can choose:

- `tiny` (fastest, lowest accuracy)
- `base`
- `small` (good speed/accuracy)
- `medium` (better accuracy, slower)
- `large-v3` (best accuracy, slowest)

Example:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --whisper-model base --format txt
```
When you first use this, it will need to download the model weights (may take a while if you use a big model).
### Device + compute type

On macOS, **CPU + int8** is usually best for faster-whisper.

Defaults:
- device: auto (usually `cpu`)
- compute: `int8`

You can force:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --fw-device cpu --fw-compute-type int8 --format txt
```

If you’re on an NVIDIA GPU box:

```bash
python meeting2notes.py --audio "/path/to/file.m4a" --fw-device cuda --fw-compute-type float16 --format txt
```

---

## Output

Files are saved to:

```
~/Documents/Meeting_Notes/<Meeting Title> - Notes.txt
```

or `.md` if `--format md`.

The output includes:
- structured notes
- full transcript
- a cost breakdown for the OpenAI calls

---

## One-command launcher (recommended)

This creates a global command called `meetingnotes`.

### 1) Create a launcher directory

```bash
mkdir -p ~/bin
```

### 2) Create the launcher script

```bash
nano ~/bin/meetingnotes
```

Paste this and **replace** `/ABSOLUTE/PATH/TO/REPO`:

```bash
#!/usr/bin/env bash
set -e

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate audio2notes

python /ABSOLUTE/PATH/TO/REPO/meeting2notes.py --record --device ":0" --format txt
```

Optional: enable debug timing by default:

```bash
python /ABSOLUTE/PATH/TO/REPO/meeting2notes.py --record --device ":0" --format txt --debug_timing
```

Save and exit (`Ctrl + O`, Enter, `Ctrl + X`).

### 3) Make it executable

```bash
chmod +x ~/bin/meetingnotes
```

### 4) Add `~/bin` to your PATH

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Now run from anywhere:

```bash
meetingnotes
```

---

## Troubleshooting

### “OPENAI_API_KEY environment variable is not set.”
Check:

```bash
echo $OPENAI_API_KEY
```

If empty, re-export it or add it to `~/.zshrc`.

---

### Hugging Face warning about unauthenticated requests
This is normal without `HF_TOKEN`. It still works, but downloads may be slower / rate-limited. Set:

```bash
export HF_TOKEN="hf_..."
```

---

### ffmpeg not found
Install:

```bash
brew install ffmpeg
```

