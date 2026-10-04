import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from audio_editor import Clip, Part, export_clip, parse_time, probe_audio, safe_title, subtract, time_text, waveform
from auth_flow import CallbackServer, LoginCancelled
import updates


class RangeTests(unittest.TestCase):
    def test_time_formats_and_roundtrip(self):
        self.assertEqual(parse_time('1:02:03,5'), 3723.5)
        self.assertEqual(parse_time('90.25'), 90.25)
        self.assertEqual(parse_time(time_text(3599.9996)), 3600)
        for invalid in ('-1', 'NaN', 'inf', '1:60', '1:2:70', '1:1:2:3', '1.1:02'):
            with self.assertRaises(ValueError):
                parse_time(invalid)
    def test_cut_preserves_other_file_and_order(self):
        a, b = Path('a.wav'), Path('b.wav')
        parts = (Part(a, 0, 10), Part(b, 0, 5))
        self.assertEqual(subtract(parts, a, 3, 7), (Part(a, 0, 3), Part(a, 7, 10), Part(b, 0, 5)))
        self.assertEqual(subtract(parts, a, 0, 10), (Part(b, 0, 5),))
    def test_safe_names(self):
        self.assertNotIn('/', safe_title('../outside'))
        self.assertEqual(safe_title('CON'), '_CON')
        with self.assertRaises(ValueError):
            safe_title('  ')


class UpdateTests(unittest.TestCase):
    def release(self, tag='v1.2.0'):
        base = 'https://github.com/marushan491/lwmc-nbg-uploader/releases/'
        return {'tag_name': tag, 'html_url': base + 'tag/' + tag, 'assets': [
            {'name': 'WorshipUploader-Windows-x64.zip', 'browser_download_url': base + 'download/' + tag + '/WorshipUploader-Windows-x64.zip'}]}
    def test_newer_platform_download(self):
        response = Mock()
        response.json.return_value = self.release()
        with patch.object(updates.requests, 'get', return_value=response):
            result = updates.check_update('1.1.2', 'Windows-x64')
            self.assertTrue(result['download_url'].endswith('Windows-x64.zip'))
            self.assertIsNone(updates.check_update('1.2.0', 'Windows-x64'))
            self.assertIsNone(updates.check_update('2.0.0', 'Windows-x64'))
    def test_prerelease_and_unexpected_link(self):
        response = Mock()
        release = self.release()
        release['prerelease'] = True
        response.json.return_value = release
        with patch.object(updates.requests, 'get', return_value=response):
            self.assertIsNone(updates.check_update('1.0.0'))
            release['prerelease'] = False
            release['html_url'] = 'https://github.com.evil.example/download'
            with self.assertRaises(RuntimeError):
                updates.check_update('1.0.0')
    def test_network_failure_is_not_current_version(self):
        with patch.object(updates.requests, 'get', side_effect=updates.requests.Timeout):
            with self.assertRaises(updates.requests.Timeout):
                updates.check_update('1.0.0')


class AuthTests(unittest.TestCase):
    def test_cancel_does_not_wait_for_browser(self):
        cancel = threading.Event()
        cancel.set()
        with CallbackServer(cancel=cancel) as server:
            started = time.monotonic()
            with self.assertRaises(LoginCancelled):
                server.wait('https://example.com/login', 'state', open_browser=False)
            self.assertLess(time.monotonic() - started, 1)
    def test_invalid_state_then_valid_callback(self):
        with CallbackServer(timeout=3) as server:
            result, errors = [], []
            def run():
                try:
                    result.append(server.wait('https://example.com/login', 'test-state', open_browser=False))
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            # wait() sets its state synchronously before handle_request().
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(server.redirect_uri + '?state=wrong&code=fake', timeout=2)
            self.assertEqual(error.exception.code, 400)
            urllib.request.urlopen(server.redirect_uri + '?state=test-state&code=fake', timeout=2).close()
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(result[0]['code'], ['fake'])
    def test_access_denied_releases_server(self):
        with CallbackServer(timeout=2) as server:
            errors = []
            def run():
                try:
                    server.wait('https://example.com/login', 'test-state', open_browser=False)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            urllib.request.urlopen(server.redirect_uri + '?state=test-state&error=access_denied', timeout=2).close()
            thread.join(timeout=3)
            self.assertIn('access_denied', str(errors[0]))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg not installed')
class EditIntegrationTests(unittest.TestCase):
    def test_cut_merge_mp3_and_source_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wav, mp3 = root / 'first.wav', root / 'second.mp3'
            for path, frequency in [(wav, 440), (mp3, 880)]:
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    f'sine=frequency={frequency}:duration=5', str(path)], check=True)
            hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wav, mp3)}
            # Keep seconds 0..1 and 3..4 from WAV, then 1..3 from MP3.
            parts = subtract((Part(wav, 0, 4),), wav, 1, 3) + (Part(mp3, 1, 3),)
            output = export_clip(Clip('Predigt', 'spreaker', parts), root / 'edits')
            self.assertAlmostEqual(probe_audio(output)[1], 4.0, delta=0.05)
            self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes}, hashes)
            waveform(mp3, root / 'wave.png')
            self.assertEqual((root / 'wave.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
    def test_invalid_range_never_exports(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wav = root / 'short.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', str(wav)], check=True)
            with self.assertRaises(ValueError):
                export_clip(Clip('invalid', 'drive', (Part(wav, 0, 20),)), root / 'edits')
            self.assertFalse((root / 'edits').exists())
