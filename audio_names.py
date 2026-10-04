"""Human-readable episode titles and collision-safe export names."""
from datetime import datetime
from pathlib import Path
import re


def recording_titles(paths, route, date, speaker='', church='LWMC Nürnberg'):
    day = datetime.strptime(date.strip(), '%d.%m.%Y').strftime('%d.%m.%Y')
    base = f'{day} – {church.strip() or "LWMC Nürnberg"}'
    detail = speaker.strip() if route == 'spreaker' else 'Worship'
    if detail:
        base += ' – ' + detail
    return {str(Path(path).expanduser().resolve()): base + (f' – Teil {i+1}' if len(paths) > 1 else '')
            for i, path in enumerate(paths)}


def safe_filename(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip().rstrip('. ')
    name = name.encode('utf-8')[:190].decode('utf-8', errors='ignore').rstrip('. ')
    if not name:
        raise ValueError('Bitte einen Titel mit sichtbaren Zeichen eingeben.')
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I):
        name = '_' + name
    return name


def reserve_output(folder, title):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = safe_filename(title)
    number = 1
    while True:
        target = folder / (name + (f' ({number})' if number > 1 else '') + '.mp3')
        try:
            with target.open('xb'):
                pass
            return target
        except FileExistsError:
            number += 1
