from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audio_names import recording_titles, reserve_output, safe_filename
import desktop_ui


class NamingTests(unittest.TestCase):
    def test_template_parts_and_worship(self):
        paths = ['a.wav', 'b.wav']
        titles = list(recording_titles(paths, 'spreaker', '04.10.2026', 'Pas. Daniel').values())
        self.assertEqual(titles, ['04.10.2026 – LWMC Nürnberg – Pas. Daniel – Teil 1',
                                  '04.10.2026 – LWMC Nürnberg – Pas. Daniel – Teil 2'])
        self.assertEqual(next(iter(recording_titles(['w.wav'], 'drive', '04.10.2026').values())),
                         '04.10.2026 – LWMC Nürnberg – Worship')
        with self.assertRaises(ValueError):
            recording_titles(paths, 'drive', '31.02.2026')
    def test_safe_names_and_no_overwrite(self):
        self.assertEqual(safe_filename('CON'), '_CON')
        self.assertNotIn('/', safe_filename('../Name: Test'))
        self.assertLessEqual(len(safe_filename('ü'*300).encode()), 190)
        with tempfile.TemporaryDirectory() as d:
            first = reserve_output(d, '04.10.2026 – Predigt')
            first.write_bytes(b'original export')
            second = reserve_output(d, '04.10.2026 – Predigt')
            self.assertEqual(second.name, '04.10.2026 – Predigt (2).mp3')
            self.assertEqual(first.read_bytes(), b'original export')
    def test_audio_drop_filters_invalid_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as d:
            wav, mp3, other = [Path(d)/name for name in ('with spaces.WAV','sound.mp3','readme.txt')]
            for p in (wav, mp3, other):
                p.write_bytes(b'data')
            valid, invalid = desktop_ui.audio_paths([str(wav),str(wav),str(mp3),str(other),d])
            self.assertEqual(valid, [str(wav.resolve()),str(mp3.resolve())])
            self.assertEqual(len(invalid), 2)
    def test_folder_open_without_shell(self):
        with tempfile.TemporaryDirectory() as d, patch.object(desktop_ui.sys,'platform','darwin'), \
             patch.object(desktop_ui.subprocess, 'Popen') as opened:
            desktop_ui.open_folder(d)
            self.assertEqual(opened.call_args.args[0], ['/usr/bin/open', str(Path(d).resolve())])
            self.assertNotIn('shell', opened.call_args.kwargs)
