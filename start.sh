#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Zuerst ./setup.sh ausführen.' >&2
  exit 1
fi
exec .venv/bin/python audio_uploader.py "$@"
