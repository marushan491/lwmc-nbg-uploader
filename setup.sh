#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v ffmpeg >/dev/null || { echo 'FFmpeg installieren (siehe README).' >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f config.json ]; then cp config.example.json config.json; fi
echo 'Einrichtung fertig. config.json bearbeiten; dann anmelden (siehe README).'
