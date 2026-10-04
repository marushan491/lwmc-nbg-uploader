import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import audio_uploader as app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a = self.root / 'Predigt.wav'
        self.b = self.root / 'Worship.wav'
        self.a.write_bytes(b'audio A')
        self.b.write_bytes(b'audio B')
        self.cfg = {'spreaker': {'show_id': '123'}, 'drive': {},
                    'audio': {'output_dir': str(self.root / 'mp3')}}
        self.state_patch = patch.object(app, 'STATE', self.root / 'state')
        self.state_patch.start()
    def tearDown(self):
        self.state_patch.stop()
        self.temp.cleanup()
    def test_parallel_paths_and_duplicate_skip(self):
        barrier = threading.Barrier(2)
        observed = []
        def fake_convert(source, target, norm, bitrate, lufs, log):
            observed.append((source.name, norm))
            barrier.wait(timeout=5)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'mp3')
        with patch.object(app.shutil, 'which', return_value='/ffmpeg'), \
             patch.object(app, 'convert', side_effect=fake_convert), \
             patch.object(app, 'spreaker_token', return_value='TOKEN'), \
             patch.object(app, 'drive_service', return_value=object()), \
             patch.object(app, 'drive_folder', return_value='FOLDER'), \
             patch.object(app, 'upload_spreaker', return_value={'episode_id': 1}) as sp, \
             patch.object(app, 'upload_drive', return_value={'id': 'drive-file'}) as dr:
            self.assertTrue(app.run_jobs(self.cfg, [str(self.a)], [str(self.b)], log=lambda _: None))
            self.assertCountEqual(observed, [('Predigt.wav', True), ('Worship.wav', False)])
            self.assertTrue(app.run_jobs(self.cfg, [str(self.a)], [str(self.b)], log=lambda _: None))
            self.assertEqual(sp.call_count, 1)
            self.assertEqual(dr.call_count, 1)
        self.assertEqual(len(app.read_json(app.STATE / 'successful_uploads.json')), 2)
    def test_failed_route_does_not_stop_other(self):
        with patch.object(app.shutil, 'which', return_value='/ffmpeg'), \
             patch.object(app, 'convert'), patch.object(app, 'spreaker_token', return_value='TOKEN'), \
             patch.object(app, 'drive_service', return_value=object()), \
             patch.object(app, 'drive_folder', return_value='FOLDER'), \
             patch.object(app, 'upload_spreaker', side_effect=RuntimeError('failed')), \
             patch.object(app, 'upload_drive', return_value={'id': 'drive-file'}) as dr:
            self.assertFalse(app.run_jobs(self.cfg, [str(self.a)], [str(self.b)], log=lambda _: None))
            self.assertEqual(dr.call_count, 1)
        self.assertEqual(len(app.read_json(app.STATE / 'successful_uploads.json')), 1)
    def test_source_content_changes_fingerprint(self):
        first = app.fingerprint(self.a, {'route': 'drive'})
        self.a.write_bytes(b'different')
        self.assertNotEqual(first, app.fingerprint(self.a, {'route': 'drive'}))
    def test_invalid_source_before_auth(self):
        with patch.object(app.shutil, 'which', return_value='/ffmpeg'), patch.object(app, 'spreaker_token') as auth:
            with self.assertRaises(RuntimeError):
                app.run_jobs(self.cfg, [str(self.root / 'missing.wav')], [])
            auth.assert_not_called()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/ffprobe not installed')
class AudioIntegrationTests(unittest.TestCase):
    def test_normalized_and_plain_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wav = root / 'audio.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=4', '-ar', '44100', str(wav)], check=True)
            for norm in (True, False):
                mp3 = root / f'{norm}.mp3'
                app.convert(wav, mp3, norm, 192, -16, lambda _: None)
                data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                    '-show_format', '-of', 'json', str(mp3)], text=True))
                self.assertEqual(data['streams'][0]['codec_name'], 'mp3')
                self.assertEqual(data['streams'][0]['channels'], 2)
                self.assertEqual(data['streams'][0]['sample_rate'], '44100')
                self.assertGreater(float(data['format']['duration']), 3.9)
                if norm:
                    measured = app.ffmpeg(['-i', str(mp3), '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
                    stats = json.loads(app.re.findall(r'\{\s*"input_i".*?\}', measured, flags=app.re.S)[-1])
                    self.assertAlmostEqual(float(stats['input_i']), -16, delta=0.7)
    def test_silence_is_rejected_without_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wav = root / 'silent.wav'
            target = root / 'output.mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
                            '-t', '2', str(wav)], check=True)
            with self.assertRaisesRegex(RuntimeError, 'nicht messbar'):
                app.convert(wav, target, True, 192, -16, lambda _: None)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
