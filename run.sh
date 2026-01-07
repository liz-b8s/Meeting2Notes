#!/usr/bin/env bash
set -e

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set."
  echo 'Set it for this session:  export OPENAI_API_KEY="sk-..."'
  exit 1
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: conda not found. Install Miniconda/Anaconda first."
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate audio2notes

python meeting2notes.py --record --device ":0" --format txt