"""Native file drops and folder opening, without shell interpolation."""
import os
from pathlib import Path
import subprocess
import sys
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY, REFUSE_DROP
from update_core import clean_environment


def create_root():
    try:
        return TkinterDnD.Tk()
    except RuntimeError as exc:
        raise RuntimeError('Drag-and-drop konnte nicht geladen werden: ' + str(exc.__context__ or exc)) from exc


def audio_paths(paths):
    accepted, rejected = [], []
    for value in paths:
        path = Path(value).expanduser().resolve()
        if path.is_file() and path.suffix.lower() in ('.wav', '.mp3'):
            if str(path) not in accepted:
                accepted.append(str(path))
        else:
            rejected.append(str(path))
    return accepted, rejected


def register_drop(widget, callback, busy=lambda: False):
    widget.drop_target_register(DND_FILES)
    def drop(event):
        if busy():
            return REFUSE_DROP
        paths = widget.tk.splitlist(event.data)
        callback(paths)
        return COPY
    widget.dnd_bind('<<Drop>>', drop)
    return drop


def open_folder(path):
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise RuntimeError('Der Ausgabeordner existiert noch nicht. Zuerst MP3-Dateien speichern.')
    if sys.platform == 'win32':
        os.startfile(str(folder))
    else:
        subprocess.Popen(['/usr/bin/open' if sys.platform == 'darwin' else 'xdg-open', str(folder)],
                         env=clean_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
