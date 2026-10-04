import tempfile
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
                self.root.after_cancel(job)
            self.root.destroy()
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
