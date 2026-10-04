import tempfile
import gc
import os
import sys
from pathlib import Path
import threading
import time
import tkinter as tk
from unittest.mock import patch
import unittest
import audio_uploader as app
from audio_editor import AudioEditor, Part


def widgets(parent):
    for widget in parent.winfo_children():
        yield widget
        yield from widgets(widget)


def button(root, label):
    return next(w for w in widgets(root) if w.winfo_class() == 'TButton' and w.cget('text') == label)


@unittest.skipIf(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'darwin',
                     'Tk window tests require a local macOS desktop; CI tests run on Windows/Linux')
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest('No graphical session: ' + str(exc))
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
    def tearDown(self):
        if hasattr(self, 'root'):
            for job in self.root.tk.call('after', 'info'):
                # ttk progress timers are Tcl callbacks, not Python commands.
                self.root.tk.call('after', 'cancel', job)
            self.root.destroy()
            self.root = None
            # Tcl interpreters must be finalized on the thread that created them,
            # before subsequent audio worker threads can trigger cyclic GC.
            gc.collect()
        if hasattr(self, 'temp'):
            self.temp.cleanup()
    def test_editor_destinations_cut_and_undo(self):
        result = []
        editor = AudioEditor(self.root, Path(self.temp.name), result.extend)
        source = Path(self.temp.name) / 'recording.wav'
        editor.sources[str(source)] = (120, None)
        editor.cuts[source] = []
        editor.source_box['values'] = [str(source)]
        editor.source_box.set(str(source))
        editor.change_source()
        editor.end.set('00:01:00')
        editor.split.set('00:00:30')
        editor.title.set('Predigt')
        editor.split_clip()
        self.assertEqual([c.route for c in editor.clips], ['spreaker', 'spreaker'])
        editor.start.set('00:01:00')
        editor.end.set('00:02:00')
        editor.route.set('Drive (Worship)')
        editor.title.set('Worship')
        editor.add_clip()
        self.assertEqual([c.route for c in editor.clips], ['spreaker', 'spreaker', 'drive'])
        editor.start.set('00:00:10')
        editor.end.set('00:00:20')
        editor.remove_range()
        self.assertEqual(editor.clips[0].parts, (Part(source, 0, 10), Part(source, 20, 30)))
        editor.undo()
        self.assertEqual(editor.clips[0].parts, (Part(source, 0, 30),))
        editor.close()
    def test_login_cancel_reenables_controls_and_ignores_stale_completion(self):
        cfg = {'spreaker': {'client_id': 'example', 'client_secret': 'example'}, 'drive': {},
               'audio': {}, 'updates': {'check_on_start': False}}
        entered, finished = threading.Event(), threading.Event()
        def login(*args, **kwargs):
            entered.set()
            kwargs['cancel'].wait(timeout=2)
            finished.set()
            raise RuntimeError('cancelled')
        def drive(*args, **kwargs):
            # Keep second authentication running, then let tearDown cancel it.
            kwargs['cancel'].wait(timeout=2)
        def exercise():
            button(self.root, 'Spreaker anmelden').invoke()
            self.assertTrue(entered.wait(timeout=1))
            self.assertIn('disabled', button(self.root, 'Einstellungen').state())
            button(self.root, 'Anmeldung abbrechen').invoke()
            self.assertNotIn('disabled', button(self.root, 'Einstellungen').state())
            self.assertTrue(finished.wait(timeout=1))
            button(self.root, 'Drive anmelden').invoke()
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            # Completion of the canceled first login must not unlock the second.
            self.assertIn('disabled', button(self.root, 'Einstellungen').state())
            button(self.root, 'Anmeldung abbrechen').invoke()
            self.assertNotIn('disabled', button(self.root, 'Einstellungen').state())
        with patch.object(tk, 'Tk', return_value=self.root), \
             patch.object(self.root, 'mainloop', side_effect=exercise), \
             patch.object(app, 'STATE', Path(self.temp.name)), \
             patch.object(app, 'login_spreaker', side_effect=login), \
             patch.object(app, 'drive_service', side_effect=drive):
            app.gui(cfg)

    def test_single_action_export_default_and_upload_choice(self):
        cfg = {'spreaker': {}, 'drive': {}, 'audio': {}, 'updates': {'check_on_start': False}}
        def exercise():
            self.root.update()
            self.assertEqual(len([w for w in widgets(self.root) if w.winfo_class() == 'TButton'
                                 and w.cget('style') == 'Primary.TButton']), 1)
            self.assertFalse(button(self.root, 'Drive anmelden').master.winfo_manager())
            source = str(Path(self.temp.name) / 'recording.wav')
            with patch('tkinter.filedialog.askopenfilenames', return_value=[source]):
                button(self.root, 'Dateien hinzufügen').invoke()
            button(self.root, 'MP3 speichern').invoke()
            self.assertTrue(called.wait(1))
            self.assertTrue(run.call_args.kwargs['convert_only'])
            self.assertEqual(run.call_args.args[0]['audio']['output_dir'], self.temp.name)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and 'disabled' in button(self.root, 'MP3 speichern').state():
                self.root.update()
                time.sleep(0.01)
            upload = next(w for w in widgets(self.root) if w.winfo_class() == 'TRadiobutton'
                          and w.cget('text') == 'MP3 speichern und hochladen')
            upload.invoke()
            self.root.update()
            self.assertEqual(button(self.root, 'Drive anmelden').master.winfo_manager(), 'pack')
            called.clear()
            button(self.root, 'Speichern und hochladen').invoke()
            self.assertTrue(called.wait(1))
            self.assertFalse(run.call_args.kwargs['convert_only'])
        called = threading.Event()
        def process(*args, **kwargs):
            called.set()
            return True
        with patch.object(tk, 'Tk', return_value=self.root), \
             patch.object(self.root, 'mainloop', side_effect=exercise), \
             patch.object(app, 'STATE', Path(self.temp.name)), \
             patch('tkinter.filedialog.askdirectory', return_value=self.temp.name), \
             patch.object(app, 'run_jobs', side_effect=process) as run:
            app.gui(cfg)
