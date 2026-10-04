#!/usr/bin/env python3
"""WAV -> MP3 -> Spreaker / Google Drive; GUI and CLI, Python >= 3.10."""
import argparse
import concurrent.futures
import getpass
import hashlib
import http.server
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from app_version import VERSION
from audio_paths import find_tool
from audio_names import recording_titles, reserve_output
from desktop_ui import create_root, register_drop, audio_paths as accept_audio_paths, open_folder

FROZEN = getattr(sys, 'frozen', False)
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
STATE = Path(os.environ.get('AUDIO_UPLOADER_STATE', str(Path.home() / '.audio-uploader'))).expanduser()
CONFIG_PATH = BASE / 'config.json' if not FROZEN and (BASE / 'config.json').exists() else STATE / 'config.json'
LOCK = threading.Lock()


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def config():
    cfg = read_json(CONFIG_PATH)
    cfg.setdefault('spreaker', {})
    cfg.setdefault('drive', {})
    cfg.setdefault('audio', {})
    cfg.setdefault('updates', {})
    return cfg


def request_ok(response, label):
    if not response.ok:
        raise RuntimeError(f'{label}: HTTP {response.status_code}. Zugang, Ziel-ID und Kontolimits prüfen.')
    return response.json()


def spreaker_exchange(data, cancel=None):
    import requests
    token = request_ok(requests.post('https://api.spreaker.com/oauth2/token',
                                    data=data, timeout=(15, 60)), 'Spreaker Anmeldung')
    if cancel is not None and cancel.is_set():
        raise RuntimeError('Anmeldung abgebrochen.')
    if not token.get('access_token'):
        raise RuntimeError('Spreaker hat keinen Access-Token geliefert.')
    token['expires_at'] = time.time() + float(token.get('expires_in', 3600))
    save_json(STATE / 'spreaker_token.json', token)
    return token


def spreaker_token(cfg):
    direct = os.environ.get('SPREAKER_ACCESS_TOKEN')
    if direct:
        return direct
    token = read_json(STATE / 'spreaker_token.json')
    if not token.get('access_token'):
        raise RuntimeError('Zuerst anmelden: python audio_uploader.py login-spreaker')
    if token.get('expires_at', 0) <= time.time() + 120:
        sp = cfg['spreaker']
        if not token.get('refresh_token'):
            raise RuntimeError('Spreaker-Token abgelaufen; erneut anmelden.')
        token = spreaker_exchange({'grant_type': 'refresh_token',
            'client_id': sp.get('client_id', ''),
            'client_secret': os.environ.get('SPREAKER_CLIENT_SECRET') or sp.get('client_secret', ''),
            'refresh_token': token['refresh_token']})
    return token['access_token']


def login_spreaker(cfg, manual=False, cancel=None):
    sp = cfg['spreaker']
    client = sp.get('client_id') or input('Spreaker Client-ID: ').strip()
    secret = os.environ.get('SPREAKER_CLIENT_SECRET') or sp.get('client_secret') or getpass.getpass('Client-Secret: ')
    redirect = sp.get('redirect_uri', 'http://127.0.0.1:8765/callback')
    state = secrets.token_urlsafe(32)
    query = {'client_id': client, 'response_type': 'code', 'scope': 'basic',
             'state': state, 'redirect_uri': redirect}
    url = 'https://www.spreaker.com/oauth2/authorize?' + urllib.parse.urlencode(query)
    if manual:
        print('Im Browser öffnen:\n' + url)
        callback = input('Komplette Weiterleitungs-URL einfügen (enthält code und state): ').strip()
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(callback).query)
    else:
        from auth_flow import CallbackServer
        parsed = urllib.parse.urlsplit(redirect)
        if parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.scheme != 'http':
            raise RuntimeError('Automatischer Login benötigt eine HTTP-Loopback-Redirect-URI; sonst --manual verwenden.')
        with CallbackServer(parsed.port or 80, parsed.path or '/', cancel=cancel) as callback:
            params = callback.wait(url, state)
    if params.get('state') != [state] or not params.get('code'):
        raise RuntimeError('Login abgebrochen, abgelaufen oder ungültiger OAuth-State.')
    spreaker_exchange({'grant_type': 'authorization_code', 'client_id': client,
                      'client_secret': secret, 'redirect_uri': redirect, 'code': params['code'][0]}, cancel=cancel)
    # Retain credentials for refresh; state files have owner-only permissions on Unix.
    save_json(STATE / 'spreaker_client.json', {'client_id': client, 'client_secret': secret})
    print('Spreaker angemeldet.')


def drive_service(cfg, login=False, port=0, no_browser=False, cancel=None):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    scope = 'https://www.googleapis.com/auth/' + ('drive' if cfg['drive'].get('full_access', False) else 'drive.file')
    token_path = STATE / ('drive_full_token.json' if cfg['drive'].get('full_access') else 'drive_token.json')
    creds = Credentials.from_authorized_user_file(str(token_path), [scope]) if token_path.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_json(token_path, json.loads(creds.to_json()))
    if not creds or not creds.valid:
        if not login:
            raise RuntimeError('Zuerst anmelden: python audio_uploader.py login-drive')
        client_path = Path(cfg['drive'].get('credentials_file') or str(STATE / 'google_credentials.json')).expanduser()
        if not client_path.is_absolute():
            client_path = BASE / client_path
        if not client_path.is_file():
            raise RuntimeError(f'OAuth-Desktop-JSON fehlt: {client_path}')
        if 'installed' not in read_json(client_path):
            raise RuntimeError('Bitte eine Google-OAuth-JSON vom Typ Desktop-App verwenden, keinen Web-Client oder Service-Account-Key. Einrichtungshilfe öffnen.')
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), [scope])
        from auth_flow import CallbackServer
        with CallbackServer(port=port, cancel=cancel) as callback:
            flow.redirect_uri = callback.redirect_uri
            url, state = flow.authorization_url(access_type='offline', prompt='consent')
            callback.wait(url, state, open_browser=not no_browser)
            # oauthlib validates OAuth state; HTTPS here only permits parsing the received
            # loopback response, matching InstalledAppFlow.run_local_server's behavior.
            flow.fetch_token(authorization_response=callback.response_url.replace('http:', 'https:', 1))
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Anmeldung abgebrochen.')
            creds = flow.credentials
        save_json(token_path, json.loads(creds.to_json()))
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    return build('drive', 'v3', http=AuthorizedHttp(creds, http=httplib2.Http(timeout=120)), cache_discovery=False)


def drive_folder(service, cfg):
    folder = cfg['drive'].get('folder_id')
    if not folder:
        saved = read_json(STATE / 'drive_folder.json')
        folder = saved.get('id')
    if folder:
        info = service.files().get(fileId=folder, fields='id,mimeType,trashed,capabilities(canAddChildren)',
                                   supportsAllDrives=True).execute()
        if info.get('trashed') or info['mimeType'] != 'application/vnd.google-apps.folder':
            raise RuntimeError('Drive-Ziel ist kein gültiger Ordner.')
        if not info.get('capabilities', {}).get('canAddChildren', False):
            raise RuntimeError('Keine Schreibberechtigung im Drive-Zielordner.')
        return folder
    folder = service.files().create(body={'name': 'Worship', 'mimeType': 'application/vnd.google-apps.folder'},
                                    fields='id').execute()['id']
    save_json(STATE / 'drive_folder.json', {'id': folder})
    return folder


def ffmpeg(args):
    proc = subprocess.run([find_tool('ffmpeg') or 'ffmpeg', '-hide_banner', '-nostdin', '-threads', '2', *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    if proc.returncode:
        raise RuntimeError('FFmpeg: ' + proc.stderr[-2000:])
    return proc.stderr


def convert(source, target, normalize, bitrate, lufs, log):
    target.parent.mkdir(parents=True, exist_ok=True)
    common = ['-i', str(source), '-map', '0:a:0', '-vn', '-ac', '2']
    filters = []
    if normalize:
        log('Lautheit messen (1/2) …')
        base_filter = f'loudnorm=I={lufs}:TP=-1.5:LRA=11'
        measured = ffmpeg([*common, '-af', 'aformat=channel_layouts=stereo,' + base_filter + ':print_format=json', '-f', 'null', '-'])
        matches = re.findall(r'\{\s*"input_i".*?\}', measured, flags=re.S)
        if not matches:
            raise RuntimeError('Lautheitsmessung lieferte keine Daten.')
        stats = json.loads(matches[-1])
        keys = ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']
        if not all(math.isfinite(float(stats[k])) for k in keys):
            raise RuntimeError('Lautheit nicht messbar (z. B. stille Aufnahme).')
        filters = ['-af', 'aformat=channel_layouts=stereo,' + base_filter +
            f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}" +
            f":measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true"]
    log('MP3 konvertieren' + (' (2/2)' if normalize else '') + ' …')
    temporary = target.with_suffix('.partial.mp3')
    try:
        ffmpeg(['-y', *common, *filters, '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', f'{bitrate}k', str(temporary)])
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def upload_spreaker(path, title, cfg, token, public):
    import requests
    from requests_toolbelt.multipart.encoder import MultipartEncoder
    fields = {'title': title, 'description': cfg['spreaker'].get('description', ''),
              'hidden': 'false' if public else 'true'}
    with path.open('rb') as audio:
        body = MultipartEncoder(fields={**fields, 'media_file': (path.name, audio, 'audio/mpeg')})
        try:
            response = requests.post(f"https://api.spreaker.com/v2/shows/{cfg['spreaker']['show_id']}/episodes",
                headers={'Authorization': f'Bearer {token}', 'Content-Type': body.content_type,
                         'User-Agent': 'WorshipAudioUploader/1.0'}, data=body, timeout=(20, 900))
        except requests.RequestException as exc:
            raise RuntimeError('Spreaker Netzwerkfehler: Uploadstatus unklar. Vor erneutem Upload im Konto prüfen.') from exc
    data = request_ok(response, 'Spreaker Upload')
    ep = data['response']['episode']
    return {'episode_id': ep['episode_id'], 'url': ep.get('site_url'), 'encoding_status': ep.get('encoding_status')}


def upload_drive(path, title, service, folder, log):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(path), mimetype='audio/mpeg', chunksize=8 * 1024 * 1024, resumable=True)
    request = service.files().create(body={'name': title + '.mp3', 'parents': [folder]}, media_body=media,
                                     fields='id,name,webViewLink', supportsAllDrives=True)
    result = None
    while result is None:
        status, result = request.next_chunk(num_retries=3)
        if status:
            log(f'Drive Upload {status.progress():.0%}')
    return result


def fingerprint(source, options):
    h = hashlib.sha256(json.dumps(options, sort_keys=True).encode())
    with source.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run_jobs(cfg, sp_files, drive_files, normalize_drive=False, parallel=True,
             public=False, convert_only=False, force=False, log=print, titles=None):
    if not find_tool('ffmpeg'):
        raise RuntimeError('FFmpeg fehlt. Siehe README.')
    all_files = [Path(p).expanduser().resolve() for p in [*sp_files, *drive_files]]
    if not all_files:
        raise RuntimeError('Mindestens eine WAV- oder MP3-Datei auswählen.')
    for p in all_files:
        if not p.is_file() or p.suffix.lower() not in ('.wav', '.mp3'):
            raise RuntimeError(f'Keine gültige WAV- oder MP3-Datei: {p}')
    bitrate = int(cfg['audio'].get('bitrate_kbps', 192))
    lufs = float(cfg['audio'].get('target_lufs', -16))
    if bitrate not in (64, 96, 128, 160, 192, 224, 256, 320) or not math.isfinite(lufs) or not -30 <= lufs <= -5:
        raise RuntimeError('Ungültige Bitrate oder Ziel-Lautheit in config.json.')
    output = Path(cfg['audio'].get('output_dir') or str(Path.home() / 'Music' / 'WorshipUploader')).expanduser()
    if not output.is_absolute():
        output = BASE / output
    token, service, folder = None, None, None
    if not convert_only:
        if sp_files:
            if not str(cfg['spreaker'].get('show_id', '')).isdigit():
                raise RuntimeError('Spreaker show_id in config.json fehlt.')
            token = spreaker_token(cfg)
        if drive_files:
            service = drive_service(cfg)
            folder = drive_folder(service, cfg)
    jobs = []
    for route, files, norm in [('spreaker', sp_files, True), ('drive', drive_files, normalize_drive)]:
        for path in dict.fromkeys(files):
            jobs.append((route, Path(path).expanduser().resolve(), norm))
    successes = read_json(STATE / 'successful_uploads.json')
    def one(job):
        route, source, norm = job
        prefix = f'[{route} / {source.name}] '
        emit = lambda message: log(prefix + message)
        target = None
        try:
            title = (titles or {}).get(route, {}).get(str(source), source.stem).strip()
            if not title:
                raise ValueError('Der Titel darf nicht leer sein.')
            options = {'route': route, 'normalize': norm, 'bitrate': bitrate, 'lufs': lufs,
                'title': title, 'public': public if route == 'spreaker' else False,
                'destination': str(cfg['spreaker'].get('show_id')) if route == 'spreaker' else folder,
                'description': cfg['spreaker'].get('description', '') if route == 'spreaker' else ''}
            key = fingerprint(source, options)
            if not convert_only and not force and key in successes:
                emit('Bereits erfolgreich hochgeladen – übersprungen.')
                return True
            target = reserve_output(output / route, title)
            convert(source, target, norm, bitrate, lufs, emit)
            if convert_only:
                emit('Fertig: ' + str(target))
                return True
            emit('Upload startet …')
            result = upload_spreaker(target, title, cfg, token, public) if route == 'spreaker' else upload_drive(target, title, service, folder, emit)
            with LOCK:
                successes[key] = {'source': str(source), 'mp3': str(target), 'options': options, 'result': result,
                                  'uploaded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
                save_json(STATE / 'successful_uploads.json', successes)
            emit('Upload angenommen: ' + str(result.get('url') or result.get('webViewLink') or result.get('id') or result.get('episode_id')))
            if route == 'spreaker':
                emit('Spreaker verarbeitet die Audiodatei anschließend serverseitig.')
            return True
        except Exception as exc:
            if target and target.exists() and target.stat().st_size == 0:
                target.unlink()
            emit('FEHLER: ' + str(exc))
            return False
    # One worker per route: Google clients are not thread safe; files on each route remain sequential.
    def route_worker(route):
        return [one(job) for job in jobs if job[0] == route]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2 if parallel else 1) as pool:
        futures = [pool.submit(route_worker, route) for route in ('spreaker', 'drive')]
        return all(result for future in futures for result in future.result())


def gui(cfg):
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog, ttk
    except ImportError as exc:
        raise RuntimeError('Tkinter fehlt; README beachten oder Terminal-Modus verwenden.') from exc
    root = create_root()
    root.title('LWMC NBG Uploader · v' + VERSION)
    root.geometry('960x780')
    root.minsize(900, 760)
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('.', font=('', 10), background='#f4f6fa', foreground='#202d42')
    style.configure('TButton', padding=(12, 7))
    style.configure('TLabel', background='#f4f6fa')
    style.configure('Muted.TLabel', foreground='#52627a')
    style.configure('Title.TLabel', font=('', 22, 'bold'))
    style.configure('Primary.TButton', font=('', 11, 'bold'), background='#275bcb', foreground='white', padding=(18, 10))
    style.map('Primary.TButton', background=[('disabled', '#ccd3df'), ('active', '#1948a7')],
              foreground=[('disabled', '#64748b'), ('active', 'white')])
    style.configure('TLabelframe', padding=12)
    style.configure('TLabelframe.Label', font=('', 11, 'bold'))
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Deine Aufnahme. Fertig als MP3.', style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame, text='WAV / MP3 hineinziehen, bei Bedarf schneiden und anschließend speichern oder hochladen.', style='Muted.TLabel').pack(anchor='w', pady=(4, 10))
    files = {'spreaker': [], 'drive': []}
    route_lists = {}
    buttons = []
    custom_titles = {'spreaker': {}, 'drive': {}}
    naming = cfg.get('naming', {})
    use_names = tk.BooleanVar(value=naming.get('use_template', True))
    from datetime import date
    recording_date = tk.StringVar(value=date.today().strftime('%d.%m.%Y'))
    speaker = tk.StringVar(value=naming.get('speaker', ''))
    def job_titles():
        return {route: {**(recording_titles(paths, route, recording_date.get(), speaker.get()) if use_names.get() else
                           {p: Path(p).stem for p in paths}), **custom_titles[route]}
                for route, paths in files.items()}
    def refresh_titles(*_):
        try:
            titles = job_titles()
        except ValueError:
            titles = {r: {p: custom_titles[r].get(p, Path(p).stem) for p in paths} for r, paths in files.items()}
        for route, listing in route_lists.items():
            selected = listing.curselection()
            listing.delete(0, 'end')
            for path in files[route]:
                listing.insert('end', titles[route][path])
            for index in selected:
                if index < len(files[route]):
                    listing.selection_set(index)
    def add_paths(route, selected):
        accepted, rejected = accept_audio_paths(selected)
        for path in accepted:
            if path not in files[route]:
                files[route].append(path)
        refresh_titles()
        if rejected:
            messagebox.showinfo('WAV / MP3 auswählen', f'{len(rejected)} Einträge ignoriert. Bitte vorhandene WAV- oder MP3-Dateien hineinziehen.', parent=root)
    def rename_selected(route):
        selected = route_lists[route].curselection()
        if not selected:
            messagebox.showinfo('Titel ändern', 'Zuerst eine Datei in der Liste markieren.', parent=root)
            return
        path = files[route][selected[0]]
        try:
            current = job_titles()[route][path]
        except ValueError:
            current = custom_titles[route].get(path, Path(path).stem)
        title = simpledialog.askstring('Titel ändern', 'Titel für diese Datei (Original bleibt unverändert):', initialvalue=current, parent=root)
        if title is not None and title.strip():
            custom_titles[route][path] = title.strip()
            refresh_titles()
    editor_bar = ttk.Frame(frame)
    editor_bar.pack(fill='x', pady=(0, 8))
    name_bar = ttk.Frame(frame)
    name_bar.pack(fill='x', pady=(0, 10))
    name_choice = ttk.Checkbutton(name_bar, text='Titel wie im Podcast', variable=use_names, command=refresh_titles)
    name_choice.pack(side='left', padx=(0, 12))
    buttons.append(name_choice)
    for label, var, width in [('Aufnahmedatum', recording_date, 12), ('Sprecher', speaker, 24)]:
        ttk.Label(name_bar, text=label).pack(side='left')
        entry = ttk.Entry(name_bar, textvariable=var, width=width)
        entry.pack(side='left', padx=(6, 12))
        buttons.append(entry)
        var.trace_add('write', refresh_titles)
    route_area = ttk.Frame(frame)
    route_area.pack(fill='x')
    route_area.columnconfigure((0, 1), weight=1, uniform='routes')
    for column, (route, heading) in enumerate([('spreaker', 'Predigt · Spreaker'), ('drive', 'Worship · Google Drive')]):
        group = ttk.LabelFrame(route_area, text=heading, padding=12)
        group.grid(row=0, column=column, sticky='nsew', padx=(0, 8) if column == 0 else (8, 0))
        ttk.Label(group, text='Lautstärke wird immer normalisiert.' if route == 'spreaker' else 'Normalisierung kannst du unten einschalten.', style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        listing = tk.Listbox(group, height=3, background='white', foreground='#202d42',
                             selectbackground='#275bcb', relief='flat', highlightthickness=1,
                             highlightbackground='#d8dfe9', activestyle='none')
        route_lists[route] = listing
        listing.pack(fill='both', expand=True)
        horizontal = ttk.Scrollbar(group, orient='horizontal', command=listing.xview)
        horizontal.pack(fill='x')
        listing.configure(xscrollcommand=horizontal.set)
        register_drop(listing, lambda paths, r=route: add_paths(r, paths), busy=lambda: busy)
        register_drop(group, lambda paths, r=route: add_paths(r, paths), busy=lambda: busy)
        listing.bind('<Double-Button-1>', lambda _, r=route: rename_selected(r) if not busy else None)
        ttk.Label(group, text='WAV / MP3 hier hineinziehen · Doppelklick ändert den Titel', style='Muted.TLabel').pack(anchor='w', pady=(5, 0))
        controls = ttk.Frame(group)
        controls.pack(fill='x', pady=(8, 0))
        def add(r=route, box=listing):
            selected = filedialog.askopenfilenames(title='Audiodateien auswählen', filetypes=[('WAV / MP3', '*.wav *.WAV *.mp3 *.MP3')])
            add_paths(r, selected)
        def clear(r=route, box=listing):
            files[r].clear()
            custom_titles[r].clear()
            box.delete(0, 'end')
        for label, command in [('Dateien hinzufügen', add), ('Liste leeren', clear)]:
            b = ttk.Button(controls, text=label, command=command)
            b.pack(side='left', padx=(0, 6))
            buttons.append(b)
        title_button = ttk.Button(controls, text='Titel ändern', command=lambda r=route: rename_selected(r))
        title_button.pack(side='left')
        buttons.append(title_button)
    def receive_clips(result):
        for route, path in result:
            destinations = ('spreaker', 'drive') if route == 'both' else (route,)
            for destination in destinations:
                if path not in files[destination]:
                    files[destination].append(str(Path(path).resolve()))
        refresh_titles()
        events.put(('log', f'{len(result)} geschnittene Teile in die Dateilisten übernommen.'))
    def open_editor():
        from audio_editor import AudioEditor
        AudioEditor(root, STATE / 'edits', receive_clips)
    editor_button = ttk.Button(editor_bar, text='Aufnahme schneiden / teilen', command=open_editor)
    editor_button.pack(side='left')
    buttons.append(editor_button)
    update_label = tk.StringVar(value='Version ' + VERSION)
    ttk.Label(editor_bar, textvariable=update_label).pack(side='right', padx=8)
    update_button = ttk.Button(editor_bar, text='Nach Updates suchen', command=lambda: start_update_check(True))
    update_button.pack(side='right')
    norm, parallel, public = tk.BooleanVar(), tk.BooleanVar(value=True), tk.BooleanVar()
    mode = tk.StringVar(value='export')
    output = ttk.LabelFrame(frame, text='Was möchtest du machen?', padding=12)
    output.pack(fill='x', pady=(14, 8))
    mode_bar = ttk.Frame(output)
    mode_bar.pack(fill='x')
    for label, value in [('MP3 speichern', 'export'), ('MP3 speichern und hochladen', 'upload')]:
        choice = ttk.Radiobutton(mode_bar, text=label, value=value, variable=mode, command=lambda: refresh_mode())
        choice.pack(side='left', padx=(0, 22))
        buttons.append(choice)
    mode_hint = tk.StringVar()
    ttk.Label(output, textvariable=mode_hint, style='Muted.TLabel').pack(anchor='w', pady=(8, 4))
    norm_button = ttk.Checkbutton(output, text='Worship-Lautstärke normalisieren', variable=norm)
    norm_button.pack(anchor='w', pady=3)
    buttons.append(norm_button)
    upload_options = ttk.Frame(output)
    public_button = ttk.Checkbutton(upload_options, text='Spreaker öffentlich veröffentlichen (sonst privat)', variable=public)
    public_button.pack(anchor='w', pady=3)
    buttons.append(public_button)
    advanced = ttk.Frame(frame)
    advanced.pack(fill='x')
    parallel_button = ttk.Checkbutton(advanced, text='Predigt und Worship gleichzeitig verarbeiten', variable=parallel)
    parallel_button.pack(anchor='w')
    buttons.append(parallel_button)
    account_bar = ttk.Frame(frame)
    # Accounts appear only for upload; saving MP3s never requires signing in.
    def settings():
        popup = tk.Toplevel(root)
        popup.title('Einstellungen')
        form = ttk.Frame(popup, padding=12)
        form.pack(fill='both', expand=True)
        values = {}
        fields = [('spreaker', 'client_id', 'Spreaker Client-ID', ''),
                  ('spreaker', 'client_secret', 'Spreaker Client-Secret', ''),
                  ('spreaker', 'show_id', 'Spreaker Show-ID', ''),
                  ('spreaker', 'redirect_uri', 'Spreaker Redirect-URI', 'http://127.0.0.1:8765/callback'),
                  ('drive', 'folder_id', 'Drive Ordner-ID (leer = neuer Worship-Ordner)', ''),
                  ('drive', 'credentials_file', 'Google OAuth Desktop-JSON', '')]
        for row, (section, key, label, default) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=4)
            value = tk.StringVar(value=str(cfg[section].get(key, default)))
            values[(section, key)] = value
            ttk.Entry(form, textvariable=value, width=45, show='*' if key == 'client_secret' else '').grid(row=row, column=1, padx=8)
        def choose_credentials():
            path = filedialog.askopenfilename(parent=popup, title='Google OAuth Desktop-JSON', filetypes=[('JSON', '*.json')])
            if path:
                values[('drive', 'credentials_file')].set(path)
        ttk.Button(form, text='Google JSON auswählen', command=choose_credentials).grid(row=6, column=1, sticky='w')
        full = tk.BooleanVar(value=cfg['drive'].get('full_access', False))
        ttk.Checkbutton(form, text='Drive-Vollzugriff für vorhandenen Ordner (erneute Anmeldung nötig)', variable=full).grid(row=7, column=0, columnspan=2, pady=8)
        auto_updates = tk.BooleanVar(value=cfg['updates'].get('check_on_start', True))
        ttk.Checkbutton(form, text='Beim Start automatisch auf GitHub-Updates prüfen (max. täglich)', variable=auto_updates).grid(row=8, column=0, columnspan=2, pady=8)
        def save():
            for (section, key), value in values.items():
                cfg[section][key] = value.get().strip()
            cfg['drive']['full_access'] = full.get()
            cfg['updates']['check_on_start'] = auto_updates.get()
            save_json(CONFIG_PATH, cfg)
            popup.destroy()
        ttk.Button(form, text='Speichern', command=save).grid(row=9, column=1, sticky='e')
    settings_button = ttk.Button(account_bar, text='Einstellungen', command=settings)
    settings_button.pack(side='left')
    buttons.append(settings_button)
    def show_help():
        from setup_help import show_setup_help
        show_setup_help(root)
    help_button = ttk.Button(account_bar, text='Einrichtungshilfe', command=show_help)
    help_button.pack(side='left', padx=6)
    # Help and cancellation remain usable during OAuth waiting.
    login_cancel = threading.Event()
    login_active = False
    login_generation = 0
    def cancel_login():
        nonlocal busy, login_active, login_generation
        login_cancel.set()
        login_generation += 1
        busy = False
        login_active = False
        cancel_button.configure(state='disabled')
        for b in buttons:
            b.configure(state='normal')
        start_button.configure(state='normal')
        events.put(('log', 'Anmeldung abgebrochen. Du kannst sie erneut starten.'))
    cancel_button = ttk.Button(account_bar, text='Anmeldung abbrechen', command=cancel_login, state='disabled')
    cancel_button.pack(side='right')
    def login(route):
        nonlocal busy, login_active, login_cancel, login_generation
        if route == 'spreaker' and not (cfg['spreaker'].get('client_id') and cfg['spreaker'].get('client_secret')):
            messagebox.showinfo('Einstellungen', 'Bitte zuerst Client-ID und Client-Secret in den Einstellungen eintragen.')
            return
        busy = True
        login_active = True
        login_cancel = threading.Event()
        cancellation = login_cancel
        login_generation += 1
        generation = login_generation
        def report(kind, value=None):
            events.put(('login_event', (generation, kind, value)))
        cancel_button.configure(state='normal')
        for b in buttons:
            b.configure(state='disabled')
        start_button.configure(state='disabled')
        def work():
            try:
                report('log', 'Anmeldung im Browser öffnen … Bei 403 oder geschlossenem Tab: Anmeldung abbrechen.')
                if route == 'spreaker':
                    login_spreaker(cfg, cancel=cancellation)
                else:
                    drive_service(cfg, login=True, cancel=cancellation)
                report('log', route + ': Anmeldung erfolgreich.')
            except Exception as exc:
                report('log', 'Anmeldung: ' + str(exc))
            finally:
                report('done')
        threading.Thread(target=work, daemon=True).start()
    for route, text in [('spreaker', 'Spreaker anmelden'), ('drive', 'Drive anmelden')]:
        button = ttk.Button(account_bar, text=text, command=lambda r=route: login(r))
        button.pack(side='left', padx=6)
        buttons.append(button)
    action_bar = ttk.Frame(frame)
    action_bar.pack(fill='x', pady=(12, 8))
    status = tk.StringVar(value='Bereit · WAV- oder MP3-Dateien hinzufügen.')
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.pack(fill='x', pady=(0, 4))
    ttk.Label(frame, textvariable=status, style='Muted.TLabel').pack(anchor='w')
    details = ttk.LabelFrame(frame, text='Verlauf', padding=6)
    details.pack(fill='both', expand=True, pady=(8, 0))
    logs = tk.Text(details, height=5, wrap='word', state='disabled', relief='flat',
                   background='white', foreground='#52627a', padx=8, pady=8)
    logs.pack(fill='both', expand=True)
    events = queue.Queue()
    busy = False
    def start():
        nonlocal busy
        sp, dr = files['spreaker'][:], files['drive'][:]
        if not sp and not dr:
            messagebox.showinfo('Dateien fehlen', 'Bitte mindestens eine WAV- oder MP3-Datei auswählen.')
            return
        try:
            titles = job_titles()
        except ValueError:
            messagebox.showinfo('Aufnahmedatum prüfen', 'Bitte ein gültiges Aufnahmedatum im Format TT.MM.JJJJ eintragen.', parent=root)
            return
        export = mode.get() == 'export'
        job_cfg = json.loads(json.dumps(cfg))
        destination = filedialog.askdirectory(parent=root, title='Ordner zum Speichern der MP3-Dateien wählen', mustexist=True)
        if not destination:
            return
        job_cfg['audio']['output_dir'] = destination
        last_output.set(destination)
        open_output_button.configure(state='normal')
        cfg['audio']['output_dir'] = destination
        cfg['naming'] = {'use_template': use_names.get(), 'speaker': speaker.get().strip()}
        try:
            save_json(CONFIG_PATH, cfg)
        except OSError:
            events.put(('log', 'Der Zielordner wird für diese Sitzung verwendet; Einstellungen konnten nicht gespeichert werden.'))
        busy = True
        for b in buttons:
            b.configure(state='disabled')
        start_button.configure(state='disabled')
        status.set('MP3-Dateien werden gespeichert …' if export else 'MP3-Dateien werden gespeichert und hochgeladen …')
        progress.start(12)
        options = dict(normalize_drive=norm.get(), parallel=parallel.get(), public=public.get(), convert_only=export, titles=titles)
        def work():
            try:
                ok = run_jobs(job_cfg, sp, dr, log=lambda x: events.put(('log', x)), **options)
                events.put(('log', 'Abgeschlossen.' if ok else 'Mit Fehlern abgeschlossen; Protokoll prüfen.'))
                events.put(('status', f'MP3-Dateien gespeichert in {destination}' if ok and export else
                            ('MP3-Dateien gespeichert und Upload abgeschlossen.' if ok else 'Ein Vorgang ist fehlgeschlagen. Details stehen im Verlauf.')))
            except Exception as exc:
                events.put(('log', 'FEHLER: ' + str(exc)))
                events.put(('status', 'Vorgang fehlgeschlagen. Details stehen im Verlauf.'))
            finally:
                events.put(('done', None))
        threading.Thread(target=work, daemon=True).start()
    start_button = ttk.Button(action_bar, text='MP3 speichern', style='Primary.TButton', command=start)
    start_button.pack(side='right')
    last_output = tk.StringVar(value=cfg['audio'].get('output_dir', ''))
    def open_output():
        try:
            open_folder(last_output.get())
        except (OSError, RuntimeError) as exc:
            messagebox.showerror('Ausgabeordner', str(exc), parent=root)
    open_output_button = ttk.Button(action_bar, text='Ausgabeordner öffnen', command=open_output,
                                   state='normal' if last_output.get() and Path(last_output.get()).expanduser().is_dir() else 'disabled')
    open_output_button.pack(side='left')
    ttk.Label(action_bar, text='Zielordner beim Start wählen', style='Muted.TLabel').pack(side='left', padx=10)
    def refresh_mode():
        upload = mode.get() == 'upload'
        start_button.configure(text='Speichern und hochladen' if upload else 'MP3 speichern')
        mode_hint.set('Speichert MP3s im gewählten Ordner und lädt sie in die zugeordneten Konten hoch.' if upload else
                      'Speichert MP3s auf deinem Gerät. Funktioniert ohne Anmeldung und auch offline.')
        if upload:
            upload_options.pack(fill='x')
            account_bar.pack(fill='x', pady=6, before=action_bar)
        else:
            upload_options.pack_forget()
            account_bar.pack_forget()
    refresh_mode()
    def start_update_check(manual=False):
        if not manual and not cfg['updates'].get('check_on_start', True):
            return
        last = read_json(STATE / 'update_check.json').get('last_check', 0)
        if not manual and time.time() - last < 86400:
            return
        update_button.configure(state='disabled')
        update_label.set('Version prüfen …')
        def work():
            try:
                from updates import check_update
                release = check_update()
                save_json(STATE / 'update_check.json', {'last_check': time.time()})
                events.put(('update', (release, manual, None)))
            except Exception as exc:
                events.put(('update', (None, manual, str(exc))))
        threading.Thread(target=work, daemon=True).start()
    def show_update(release):
        popup = tk.Toplevel(root)
        popup.title('Neue Version verfügbar')
        content = ttk.Frame(popup, padding=18)
        content.pack(fill='both', expand=True)
        ttk.Label(content, text=f"Neue Version {release['version']} verfügbar", font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(content, text='Die App lädt das Update herunter und startet anschließend neu.\nDeine Anmeldung, Einstellungen und Aufnahmen bleiben erhalten.').pack(anchor='w', pady=12)
        install_status = tk.StringVar(value='Bereit zum Aktualisieren.')
        ttk.Label(content, textvariable=install_status, wraplength=480).pack(anchor='w', pady=(0, 8))
        installing = False
        def install():
            nonlocal busy, installing
            if busy:
                messagebox.showinfo('Vorgang läuft', 'Bitte zuerst den laufenden Vorgang abschließen oder die Anmeldung abbrechen.', parent=popup)
                return
            busy = installing = True
            for b in buttons:
                b.configure(state='disabled')
            start_button.configure(state='disabled')
            install_button.configure(state='disabled')
            later_button.configure(state='disabled')
            progress.start(12)
            def work():
                try:
                    from auto_update import prepare_update
                    prepared = prepare_update(release, progress=lambda text: events.put(('install_progress', (install_status, text))))
                    events.put(('install_ready', (prepared, popup, install_status, failed)))
                except Exception as exc:
                    events.put(('install_error', (str(exc), failed)))
            threading.Thread(target=work, daemon=True).start()
        def failed(error):
            nonlocal busy, installing
            busy = installing = False
            progress.stop()
            for b in buttons:
                b.configure(state='normal')
            start_button.configure(state='normal')
            install_button.configure(state='normal')
            later_button.configure(state='normal')
            status.set('Update konnte nicht installiert werden. Deine Anwendung bleibt erhalten.')
            install_status.set(error)
        install_button = ttk.Button(content, text='Jetzt aktualisieren und neu starten', style='Primary.TButton', command=install)
        if FROZEN and release.get('download_url'):
            install_button.pack(fill='x', pady=3)
        else:
            install_status.set('Auto-Update ist im Desktop-Paket verfügbar. Quellcode bitte über Git aktualisieren.')
            if release.get('download_url'):
                ttk.Button(content, text='Desktop-Paket herunterladen', command=lambda: webbrowser.open(release['download_url'])).pack(fill='x', pady=3)
        ttk.Button(content, text='Release / Änderungen öffnen', command=lambda: webbrowser.open(release['url'])).pack(fill='x', pady=3)
        later_button = ttk.Button(content, text='Später', command=popup.destroy)
        later_button.pack(fill='x', pady=3)
        popup.protocol('WM_DELETE_WINDOW', lambda: None if installing else popup.destroy())
    def poll():
        nonlocal busy, login_active
        while True:
            try:
                kind, value = events.get_nowait()
            except queue.Empty:
                break
            if kind == 'login_event':
                generation, kind, value = value
                if generation != login_generation:
                    continue
            if kind == 'install_progress':
                variable, text = value
                variable.set(text)
                status.set(text)
            elif kind == 'install_error':
                error, failed = value
                failed(error)
            elif kind == 'install_ready':
                prepared, popup, variable, failed = value
                try:
                    from auto_update import start_installer
                    process = start_installer(prepared)
                    variable.set('Update wird installiert. Die App startet gleich neu …')
                    deadline = time.monotonic() + 30
                    def handoff():
                        manifest = prepared[1]
                        if manifest.with_name('started.json').exists():
                            root.destroy()
                        elif process.poll() is not None or time.monotonic() > deadline:
                            if process.poll() is None:
                                process.terminate()
                            failed('Der Update-Helfer konnte nicht gestartet werden. Bitte erneut versuchen.')
                        else:
                            root.after(200, handoff)
                    root.after(200, handoff)
                except Exception as exc:
                    failed(str(exc))
            elif kind == 'update':
                release, manual, error = value
                update_button.configure(state='normal')
                if error:
                    update_label.set('Update-Prüfung nicht erreichbar')
                    if manual:
                        messagebox.showinfo('Updates', 'GitHub konnte nicht erreicht werden. Internetverbindung prüfen.\n' + error)
                elif release:
                    update_label.set(release['version'] + ' verfügbar')
                    show_update(release)
                else:
                    update_label.set('Version ' + VERSION + ' ist aktuell')
                    if manual:
                        messagebox.showinfo('Updates', 'Du verwendest die aktuelle stabile Version.')
            elif kind == 'done':
                progress.stop()
                busy = False
                login_active = False
                cancel_button.configure(state='disabled')
                for b in buttons:
                    b.configure(state='normal')
                start_button.configure(state='normal')
            elif kind == 'status':
                status.set(value)
            else:
                logs.configure(state='normal')
                logs.insert('end', value + '\n')
                logs.see('end')
                logs.configure(state='disabled')
        root.after(100, poll)
    def close():
        if login_active:
            login_cancel.set()
            root.destroy()
        elif busy:
            messagebox.showinfo('Vorgang läuft', 'Bitte den laufenden Vorgang abschließen lassen.')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    poll()
    root.after(1500, start_update_check)
    from update_core import confirm_startup, cleanup_finished
    active_update = confirm_startup(VERSION)
    if FROZEN:
        try:
            from auto_update import installation
            target, _, _ = installation()
            cleanup_finished(target, active_update)
        except (OSError, RuntimeError):
            pass
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('check-update')
    sub.add_parser('gui')
    sp = sub.add_parser('login-spreaker')
    sp.add_argument('--manual', action='store_true', help='Weiterleitungs-URL manuell einfügen')
    dr = sub.add_parser('login-drive')
    dr.add_argument('--port', type=int, default=0)
    dr.add_argument('--no-browser', action='store_true', help='Für SSH mit lokalem Port-Forwarding')
    upload = sub.add_parser('upload')
    upload.add_argument('--spreaker', nargs='+', default=[], metavar='AUDIO')
    upload.add_argument('--drive', nargs='+', default=[], metavar='AUDIO')
    upload.add_argument('--normalize-drive', action='store_true')
    upload.add_argument('--sequential', action='store_true')
    upload.add_argument('--public', action='store_true', help='Spreaker öffentlich veröffentlichen')
    upload.add_argument('--convert-only', action='store_true')
    upload.add_argument('--force', action='store_true', help='Auch bereits erfolgreich hochgeladene Dateien erneut hochladen')
    args = parser.parse_args()
    cfg = config()
    saved = read_json(STATE / 'spreaker_client.json')
    for key in ('client_id', 'client_secret'):
        if not cfg['spreaker'].get(key) and saved.get(key):
            cfg['spreaker'][key] = saved[key]
    try:
        if args.command == 'check-update':
            from updates import check_update
            release = check_update()
            print(json.dumps(release, ensure_ascii=False, indent=2) if release else 'Aktuell: ' + VERSION)
        elif args.command == 'login-spreaker':
            login_spreaker(cfg, args.manual)
        elif args.command == 'login-drive':
            drive_service(cfg, login=True, port=args.port, no_browser=args.no_browser)
            print('Google Drive angemeldet.')
        elif args.command == 'upload':
            return 0 if run_jobs(cfg, args.spreaker, args.drive, args.normalize_drive,
                not args.sequential, args.public, args.convert_only, args.force) else 1
        else:
            gui(cfg)
        return 0
    except KeyboardInterrupt:
        print('\nAbgebrochen. Bei begonnenem Upload zuerst Zielkonto prüfen.', file=sys.stderr)
        return 130
    except Exception as exc:
        if FROZEN and sys.stderr is None:
            import tkinter as tk
            from tkinter import messagebox
            error_root = tk.Tk()
            error_root.withdraw()
            messagebox.showerror('LWMC NBG Uploader', str(exc))
            error_root.destroy()
        else:
            print('FEHLER: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
