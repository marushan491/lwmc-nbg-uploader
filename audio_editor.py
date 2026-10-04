"""Non-destructive WAV/MP3 range editor with waveform and upload destinations."""
from dataclasses import dataclass, replace
import copy
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from audio_paths import find_tool


@dataclass(frozen=True)
class Part:
    source: Path
    start: float
    end: float


@dataclass(frozen=True)
class Clip:
    title: str
    route: str
    parts: tuple


def parse_time(value):
    fields = str(value).strip().replace(',', '.').split(':')
    if not 1 <= len(fields) <= 3:
        raise ValueError('Zeit als Sekunden, MM:SS oder HH:MM:SS eingeben.')
    try:
        numbers = [float(x) for x in fields]
    except ValueError as exc:
        raise ValueError('Ungültige Zeitangabe.') from exc
    if any(not math.isfinite(x) or x < 0 for x in numbers):
        raise ValueError('Zeit muss endlich und positiv sein.')
    if len(numbers) > 1 and (numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60)):
        raise ValueError('Sekunden und Minuten müssen kleiner als 60 sein.')
    if any(n != int(n) for n in numbers[:-1]):
        raise ValueError('Nur die Sekunden dürfen Nachkommastellen haben.')
    return sum(n * 60 ** (len(numbers) - i - 1) for i, n in enumerate(numbers))


def time_text(value):
    milliseconds = round(float(value) * 1000)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{ms:03}'


def validate_range(start, end, duration):
    if not all(math.isfinite(x) for x in (start, end, duration)) or not 0 <= start < end <= duration + 0.001:
        raise ValueError('Es muss gelten: 0 ≤ Start < Ende ≤ Aufnahmedauer.')
    return start, min(end, duration)


def subtract(parts, source, start, end):
    result = []
    for part in parts:
        if part.source != source or end <= part.start or start >= part.end:
            result.append(part)
            continue
        if part.start < start:
            result.append(Part(source, part.start, start))
        if end < part.end:
            result.append(Part(source, end, part.end))
    return tuple(result)


def command(args):
    args = list(args)
    if args[0] in ('ffmpeg', 'ffprobe', 'ffplay'):
        args[0] = find_tool(args[0]) or args[0]
    result = subprocess.run(args, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:] or 'Audio-Verarbeitung fehlgeschlagen.')
    return result.stdout


def probe_audio(source):
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in ('.wav', '.mp3'):
        raise ValueError('Bitte eine vorhandene WAV- oder MP3-Datei wählen.')
    if not find_tool('ffmpeg') or not find_tool('ffprobe'):
        raise RuntimeError('Für den Editor werden FFmpeg und ffprobe benötigt (siehe README).')
    data = json.loads(command(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_type:format=duration', '-of', 'json', str(source)]))
    if not data.get('streams'):
        raise ValueError('Die Datei enthält keine Audiospur.')
    duration = float(data['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Aufnahmedauer konnte nicht ermittelt werden.')
    return source, duration


def waveform(source, target):
    command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source), '-filter_complex',
        '[0:a:0]aformat=channel_layouts=mono,showwavespic=s=1000x160:colors=0x60a5fa[v]',
        '-map', '[v]', '-frames:v', '1', str(target)])


def safe_title(title):
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip().rstrip('. ')[:100]
    if not title:
        raise ValueError('Bitte einen Titel für den Teil eingeben.')
    if title.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        title = '_' + title
    return title


def export_clip(clip, output):
    if not clip.parts:
        raise ValueError('Der Teil enthält nach dem Ausschneiden keine Audiodaten.')
    title = safe_title(clip.title)
    descriptors = []
    durations = {}
    for part in clip.parts:
        if part.source not in durations:
            _, durations[part.source] = probe_audio(part.source)
        validate_range(part.start, part.end, durations[part.source])
        st = part.source.stat()
        descriptors.append([str(part.source), st.st_size, st.st_mtime_ns, part.start, part.end])
    key = hashlib.sha256(json.dumps(descriptors).encode()).hexdigest()[:16]
    folder = Path(output) / key
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (title + '.wav')
    # Decode each kept range into lossless PCM; concatenate without a second MP3 encoding.
    # Seeking happens before decoding, and output duration trims with sample accuracy.
    with tempfile.TemporaryDirectory(dir=folder) as work:
        work = Path(work)
        for i, part in enumerate(clip.parts):
            command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-ss', f'{part.start:.6f}',
                '-i', str(part.source), '-t', f'{part.end - part.start:.6f}', '-map', '0:a:0', '-vn',
                '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s24le', '-rf64', 'auto', str(work / f'{i}.wav')])
        concat = work / 'concat.txt'
        concat.write_text(''.join(f"file '{i}.wav'\n" for i in range(len(clip.parts))), encoding='utf-8')
        combined = work / 'combined.wav'
        command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'concat', '-safe', '1', '-i', str(concat),
                 '-map', '0:a:0', '-c:a', 'copy', '-rf64', 'auto', str(combined)])
        combined.replace(target)
    return target


class AudioEditor:
    ROUTES = {'Spreaker': 'spreaker', 'Drive (Worship)': 'drive', 'Beide': 'both'}

    def __init__(self, parent, output, on_export):
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        self.tk, self.ttk, self.dialog, self.messages = tk, ttk, filedialog, messagebox
        self.output, self.on_export = Path(output), on_export
        self.window = tk.Toplevel(parent)
        self.window.title('Aufnahme schneiden · WAV / MP3')
        self.window.geometry('1080x760')
        self.window.minsize(1050, 700)
        self.window.transient(parent)
        self.window.grab_set()
        self.temp = tempfile.TemporaryDirectory()
        self.sources, self.cuts, self.clips, self.history = {}, {}, [], []
        self.current, self.player, self.image = None, None, None
        self.busy = False
        self.events = queue.Queue()
        self.controls = []
        f = ttk.Frame(self.window, padding=12)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text='Aufnahme schneiden und Teile zuordnen', font=('', 17, 'bold')).pack(anchor='w')
        ttk.Label(f, text='Originale bleiben erhalten. Start/Ende per Wellenform oder Zeitangabe; entfernte Bereiche werden übersprungen.').pack(anchor='w', pady=6)
        top = ttk.Frame(f)
        top.pack(fill='x')
        self.button(top, 'WAV / MP3 öffnen', self.open_files).pack(side='left')
        self.source_box = ttk.Combobox(top, state='readonly', width=80)
        self.source_box.pack(side='left', padx=10, fill='x', expand=True)
        self.source_box.bind('<<ComboboxSelected>>', self.change_source)
        self.canvas = tk.Canvas(f, width=1000, height=160, bg='#111827', highlightthickness=0)
        self.canvas.pack(pady=(10, 2), anchor='w')
        self.canvas.bind('<Button-1>', self.click_wave)
        self.info = tk.StringVar(value='Zuerst eine Aufnahme öffnen.')
        ttk.Label(f, textvariable=self.info).pack(anchor='w')
        times = ttk.Frame(f)
        times.pack(fill='x', pady=8)
        self.start = tk.StringVar(value='00:00:00.000')
        self.end = tk.StringVar(value='00:00:00.000')
        self.split = tk.StringVar(value='00:00:00.000')
        self.marker = tk.StringVar(value='start')
        for text, var, mode in [('Start', self.start, 'start'), ('Ende', self.end, 'end'), ('Teilung', self.split, 'split')]:
            ttk.Radiobutton(times, text=text, value=mode, variable=self.marker).pack(side='left')
            ttk.Entry(times, textvariable=var, width=15).pack(side='left', padx=(4, 15))
        self.title = tk.StringVar(value='Teil 1')
        self.route = tk.StringVar(value='Spreaker')
        meta = ttk.Frame(f)
        meta.pack(fill='x', pady=5)
        ttk.Label(meta, text='Titel').pack(side='left')
        ttk.Entry(meta, textvariable=self.title, width=44).pack(side='left', padx=8)
        ttk.Label(meta, text='Ziel').pack(side='left')
        ttk.Combobox(meta, textvariable=self.route, values=list(self.ROUTES), state='readonly', width=20).pack(side='left', padx=8)
        actions = ttk.Frame(f)
        actions.pack(fill='x', pady=5)
        for text, callback in [('Teil hinzufügen', self.add_clip), ('Bei Teilung teilen', self.split_clip),
                ('Auswahl ausschneiden', self.remove_range), ('Auswahl anhören', self.preview), ('Stop', self.stop), ('Rückgängig', self.undo)]:
            self.button(actions, text, callback).pack(side='left', padx=(0, 6))
        self.tree = ttk.Treeview(f, columns=('title', 'route', 'length', 'parts'), show='headings', selectmode='extended', height=8)
        for column, text, width in [('title', 'Teil / Titel', 300), ('route', 'Upload-Ziel', 140),
                ('length', 'Dauer', 120), ('parts', 'Datei und Originalzeiten', 450)]:
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width)
        self.tree.pack(fill='both', expand=True, pady=8)
        lower = ttk.Frame(f)
        lower.pack(fill='x')
        for text, callback in [('Markierte Teile löschen', self.delete_clips), ('Ziel auf markierte Teile anwenden', self.assign),
                               ('Markierte Teile verbinden', self.merge)]:
            self.button(lower, text, callback).pack(side='left', padx=(0, 6))
        self.status = tk.StringVar(value='Beispiel: Predigt 1 → Spreaker, Predigt 2 → Spreaker, Worship → Drive.')
        ttk.Label(f, textvariable=self.status, wraplength=1000).pack(anchor='w', pady=9)
        self.button(f, 'Teile erzeugen und in die Upload-Listen übernehmen', self.export).pack(fill='x')
        for var in (self.start, self.end, self.split):
            var.trace_add('write', lambda *_: self.paint())
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.window.after(100, self.poll)

    def button(self, parent, text, callback):
        b = self.ttk.Button(parent, text=text, command=lambda: self.guarded(callback))
        self.controls.append(b)
        return b

    def guarded(self, callback):
        if self.busy:
            return
        try:
            callback()
        except Exception as exc:
            self.messages.showerror('Audio-Editor', str(exc), parent=self.window)

    def background(self, fn, done):
        self.busy = True
        self.source_box.configure(state='disabled')
        for b in self.controls:
            b.configure(state='disabled')
        def work():
            try:
                self.events.put(('done', done, fn()))
            except Exception as exc:
                self.events.put(('error', None, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while True:
            try:
                kind, callback, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            self.source_box.configure(state='readonly')
            for b in self.controls:
                b.configure(state='normal')
            if kind == 'error':
                self.status.set('Fehler: ' + value)
                self.messages.showerror('Audio-Editor', value, parent=self.window)
            else:
                self.guarded(lambda: callback(value))
        self.poll_id = self.window.after(100, self.poll)

    def open_files(self):
        selected = self.dialog.askopenfilenames(parent=self.window, title='Aufnahmen öffnen',
                    filetypes=[('Audio', '*.wav *.WAV *.mp3 *.MP3')])
        if not selected:
            return
        self.status.set('Aufnahme analysieren und Wellenform erzeugen …')
        def load():
            result = []
            for filename in selected:
                source, duration = probe_audio(filename)
                image = Path(self.temp.name) / (hashlib.sha256(str(source).encode()).hexdigest() + '.png')
                try:
                    waveform(source, image)
                    image_path = str(image)
                except RuntimeError:
                    image_path = None
                result.append((source, duration, image_path))
            return result
        def loaded(result):
            for source, duration, image in result:
                self.sources[str(source)] = (duration, image)
                self.cuts.setdefault(source, [])
            self.source_box['values'] = list(self.sources)
            self.source_box.set(str(result[0][0]))
            self.change_source()
            self.status.set('Geladen. Start und Ende wählen, dann Teil hinzufügen oder bei Teilung teilen.')
        self.background(load, loaded)

    def change_source(self, *_):
        if self.busy:
            return
        value = self.source_box.get()
        if value not in self.sources:
            return
        self.current = Path(value)
        duration, image = self.sources[value]
        self.image = self.tk.PhotoImage(file=image) if image else None
        self.start.set(time_text(0))
        self.end.set(time_text(duration))
        self.split.set(time_text(duration / 2))
        self.title.set(self.current.stem + ' – Teil ' + str(len(self.clips) + 1))
        self.info.set(self.current.name + ' · Dauer ' + time_text(duration) + ' · Klick setzt den gewählten Zeitmarker.')
        self.paint()

    def paint(self):
        self.canvas.delete('all')
        if self.image:
            self.canvas.create_image(0, 0, anchor='nw', image=self.image)
        if not self.current:
            return
        duration = self.sources[str(self.current)][0]
        for start, end in self.cuts.get(self.current, []):
            self.canvas.create_rectangle(start / duration * 1000, 0, end / duration * 1000, 160,
                                         fill='#991b1b', stipple='gray50', outline='')
        for var, color in [(self.start, '#34d399'), (self.end, '#fbbf24'), (self.split, '#f472b6')]:
            try:
                position = min(1000, max(0, parse_time(var.get()) / duration * 1000))
                self.canvas.create_line(position, 0, position, 160, fill=color, width=2)
            except ValueError:
                pass

    def click_wave(self, event):
        if self.current and not self.busy:
            duration = self.sources[str(self.current)][0]
            {'start': self.start, 'end': self.end, 'split': self.split}[self.marker.get()].set(time_text(min(1, max(0, event.x / 1000)) * duration))

    def selected_range(self):
        if not self.current:
            raise ValueError('Zuerst eine WAV- oder MP3-Datei öffnen.')
        return validate_range(parse_time(self.start.get()), parse_time(self.end.get()), self.sources[str(self.current)][0])

    def kept(self, start, end):
        parts = (Part(self.current, start, end),)
        for a, b in self.cuts[self.current]:
            parts = subtract(parts, self.current, a, b)
        if not parts:
            raise ValueError('Dieser Bereich wurde vollständig ausgeschnitten.')
        return parts

    def snapshot(self):
        self.history.append((copy.deepcopy(self.cuts), list(self.clips)))

    def add_clip(self):
        start, end = self.selected_range()
        clip = Clip(safe_title(self.title.get()), self.ROUTES[self.route.get()], self.kept(start, end))
        self.snapshot()
        self.clips.append(clip)
        self.refresh()

    def split_clip(self):
        start, end = self.selected_range()
        split = parse_time(self.split.get())
        if not start < split < end:
            raise ValueError('Die Teilung muss zwischen Start und Ende liegen.')
        title = safe_title(self.title.get())
        route = self.ROUTES[self.route.get()]
        clips = [Clip(title + ' A', route, self.kept(start, split)), Clip(title + ' B', route, self.kept(split, end))]
        self.snapshot()
        self.clips.extend(clips)
        self.refresh()

    def remove_range(self):
        start, end = self.selected_range()
        self.snapshot()
        self.cuts[self.current].append((start, end))
        self.clips = [replace(c, parts=subtract(c.parts, self.current, start, end)) for c in self.clips]
        self.clips = [c for c in self.clips if c.parts]
        self.refresh()
        self.paint()
        self.status.set('Auswahl ausgeschnitten. Teile mit mehreren Restbereichen werden beim Export nahtlos verbunden.')

    def selected_indices(self):
        indices = sorted(int(i) for i in self.tree.selection())
        if not indices:
            raise ValueError('Zuerst einen oder mehrere Teile in der Liste markieren.')
        return indices

    def delete_clips(self):
        indices = self.selected_indices()
        self.snapshot()
        self.clips = [c for i, c in enumerate(self.clips) if i not in indices]
        self.refresh()

    def assign(self):
        indices = self.selected_indices()
        self.snapshot()
        for i in indices:
            self.clips[i] = replace(self.clips[i], route=self.ROUTES[self.route.get()])
        self.refresh()

    def merge(self):
        indices = self.selected_indices()
        if len(indices) < 2:
            raise ValueError('Mindestens zwei Teile markieren. Sie werden in Listenreihenfolge verbunden.')
        clip = Clip(safe_title(self.title.get()), self.ROUTES[self.route.get()],
                    tuple(p for i in indices for p in self.clips[i].parts))
        self.snapshot()
        result = []
        for i, c in enumerate(self.clips):
            if i == indices[0]:
                result.append(clip)
            elif i not in indices:
                result.append(c)
        self.clips = result
        self.refresh()

    def undo(self):
        if self.history:
            self.cuts, self.clips = self.history.pop()
            self.refresh()
            self.paint()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, clip in enumerate(self.clips):
            detail = ' + '.join(p.source.name + ' [' + time_text(p.start) + '–' + time_text(p.end) + ']' for p in clip.parts)
            self.tree.insert('', 'end', iid=str(i), values=(clip.title, clip.route,
                             time_text(sum(p.end - p.start for p in clip.parts)), detail))
        self.status.set(f'{len(self.clips)} Teile vorbereitet. Noch kein Upload gestartet.')

    def stop(self):
        if self.player and self.player.poll() is None:
            self.player.terminate()
        self.player = None

    def preview(self):
        if not find_tool('ffplay'):
            raise RuntimeError('Zum Anhören wird ffplay benötigt (gehört zu vielen FFmpeg-Installationen).')
        start, end = self.selected_range()
        clip = Clip('Vorschau', 'drive', self.kept(start, end))
        self.stop()
        self.status.set('Vorschau vorbereiten …')
        def play(path):
            self.player = subprocess.Popen([find_tool('ffplay'), '-v', 'error', '-nodisp', '-autoexit', str(path)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            self.status.set('Vorschau läuft. Stop beendet die Wiedergabe.')
        self.background(lambda: export_clip(clip, Path(self.temp.name) / 'preview'), play)

    def export(self):
        if not self.clips:
            raise ValueError('Zuerst mindestens einen Teil hinzufügen.')
        clips = list(self.clips)
        self.status.set('Teile werden als verlustfreie WAVs erzeugt …')
        def process():
            # Avoid accidentally overwriting equal titles and equal source ranges in one plan.
            result = []
            names = {}
            for clip in clips:
                base = safe_title(clip.title)
                count = names.get(base, 0) + 1
                names[base] = count
                clip = replace(clip, title=base if count == 1 else f'{base} ({count})')
                result.append((clip.route, str(export_clip(clip, self.output))))
            return result
        def ready(result):
            self.on_export(result)
            self.status.set('Teile übernommen. Im Hauptfenster den Upload starten.')
        self.background(process, ready)

    def close(self):
        if self.busy:
            self.messages.showinfo('Audio-Editor', 'Bitte die laufende Verarbeitung abschließen lassen.', parent=self.window)
            return
        self.stop()
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
        self.temp.cleanup()
