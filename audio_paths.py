"""Resolve FFmpeg tools when a native app has a restricted desktop PATH."""
import os
from pathlib import Path
import shutil
import sys


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    candidates = []
    if sys.platform == 'darwin':
        candidates = [Path('/opt/homebrew/bin') / name, Path('/usr/local/bin') / name]
    elif sys.platform == 'win32' and os.environ.get('LOCALAPPDATA'):
        candidates = [Path(os.environ['LOCALAPPDATA']) / 'Microsoft' / 'WinGet' / 'Links' / (name + '.exe')]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
