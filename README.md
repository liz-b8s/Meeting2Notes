# Meeting to Notes

Record meeting audio, transcribe it with OpenAI, and generate structured meeting notes as **Markdown or plain text**.

Once set up, you can run everything with a single command:

```bash
meetingnotes
```

---

## Requirements
- macOS
- Conda (Miniconda or Anaconda)
- Python 3.9+
- OpenAI API key
- ffmpeg (needed for recording)

---

## Setup

### 1. Create and activate the Conda environment

```bash
conda create -n audio2notes python=3.10 -y
conda activate audio2notes
pip install requests
brew install ffmpeg
```

---

### 2. Set your OpenAI API key

In your terminal (replace `sk-...` with your actual key):

```bash
export OPENAI_API_KEY="sk-..."
```

To make this permanent:

```bash
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.zshrc
source ~/.zshrc
```

---

### 3. Allow microphone access (macOS)

System Settings → **Privacy & Security → Microphone**  
Enable access for **Terminal / iTerm / VS Code / PyCharm**.

---

## One-command setup (recommended)

This sets up a global command called `meetingnotes`.

### 1. Create a launcher directory

```bash
mkdir -p ~/bin
```

### 2. Create the launcher script

```bash
nano ~/bin/meetingnotes
```

Paste the following **and replace the path** with the location of this repo on your machine:

```bash
#!/usr/bin/env bash
set -e

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate audio2notes

python /ABSOLUTE/PATH/TO/REPO/meeting2notes.py --record --device ":0" --format txt
```

Save and exit (`Ctrl + O`, Enter, `Ctrl + X`).

---

### 3. Make it executable

```bash
chmod +x ~/bin/meetingnotes
```

---

### 4. Add `~/bin` to your PATH

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

---

## Using the tool

From **any directory**, run:

```bash
meetingnotes
```

- Recording starts immediately  
- Press **Enter** to stop  
- Progress messages appear while notes are generated  
- Notes are saved automatically  

---

## Output

Notes are saved to:

```
~/Documents/Meeting_Notes/<Meeting Title> - Notes.txt
```

(To save Markdown instead, edit the launcher and change `--format txt` to `--format md`.)

---

## Troubleshooting

If `meetingnotes` reports that the API key is missing, you can check:

```bash
echo $OPENAI_API_KEY
```
