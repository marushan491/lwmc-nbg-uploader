import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import auto_update
import update_core


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / 'WorshipUploader'
        self.target.mkdir()
        (self.target / 'WorshipUploader').write_text('old')
        self.work = self.root / '.lwmc-update-test'
        self.work.mkdir()
        self.staged = self.work / 'unpacked' / 'WorshipUploader'
        self.staged.mkdir(parents=True)
        (self.staged / 'WorshipUploader').write_text('new')
        self.backup = self.root / '.lwmc-backup-test'
        self.manifest = self.work / 'install.json'
        self.manifest.write_text(json.dumps({'target': str(self.target), 'staged': str(self.staged),
            'backup': str(self.backup), 'pid': 123, 'executable': 'WorshipUploader', 'version': '1.2.0'}))
    def tearDown(self):
        self.tmp.cleanup()
    def test_swap_confirm_and_backup_cleanup(self):
        def restart(target, exe, ready):
            self.assertEqual((target / exe).read_text(), 'new')
            self.assertEqual((self.backup / exe).read_text(), 'old')
            ready.write_text('{"version":"1.2.0"}')
            return Mock()
        wait = Mock()
        update_core.apply_update(self.manifest, wait=wait, restart=restart, startup_timeout=.01)
        wait.assert_called_once_with(123)
        self.assertFalse(self.backup.exists())
        self.assertTrue((self.work / 'finished.json').exists())
    def test_failed_start_restores_previous_version(self):
        process = Mock()
        process.poll.return_value = 1
        restart = Mock(return_value=process)
        with self.assertRaisesRegex(RuntimeError, 'wiederhergestellt'):
            update_core.apply_update(self.manifest, wait=Mock(), restart=restart, startup_timeout=.01)
        self.assertEqual((self.target / 'WorshipUploader').read_text(), 'old')
        self.assertEqual(restart.call_count, 2)
        self.assertFalse(self.backup.exists())
    def test_invalid_target_never_touched(self):
        data = json.loads(self.manifest.read_text())
        data['staged'] = str(self.root)
        self.manifest.write_text(json.dumps(data))
        wait = Mock()
        with self.assertRaises(RuntimeError):
            update_core.apply_update(self.manifest, wait=wait)
        wait.assert_not_called()
        self.assertEqual((self.target / 'WorshipUploader').read_text(), 'old')
    def test_cleanup_only_completed_installations_for_this_app(self):
        (self.work / 'finished.json').write_text('{}')
        other = self.root / '.lwmc-update-other'
        other.mkdir()
        update_core.cleanup_finished(self.target)
        self.assertFalse(self.work.exists())
        self.assertTrue(other.exists())
    def test_current_update_work_is_kept_until_next_regular_start(self):
        (self.work / 'finished.json').write_text('{}')
        ready = self.work / 'ready.json'
        with patch.dict(os.environ, {'LWMC_UPDATE_READY': str(ready)}):
            active = update_core.confirm_startup('1.2.0')
        update_core.cleanup_finished(self.target, active)
        self.assertTrue(self.work.exists())
        self.assertEqual(json.loads(ready.read_text())['version'], '1.2.0')
        update_core.cleanup_finished(self.target)
        self.assertFalse(self.work.exists())


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def archive(self, name='WorshipUploader/WorshipUploader', value=b'executable'):
        path = self.root / 'release.zip'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr(name, value)
        return path
    def test_reject_traversal_absolute_and_windows_paths(self):
        for name in ('../outside', '/outside', 'WorshipUploader/../../outside',
                     'WorshipUploader/C:outside', 'WorshipUploader\\..\\outside'):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                auto_update.validate_archive(self.archive(name))
    def test_mac_links_cannot_leave_package(self):
        path = self.root / 'release.zip'
        with zipfile.ZipFile(path, 'w') as z:
            item = zipfile.ZipInfo('WorshipUploader/escape')
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(item, '../../outside')
        with self.assertRaises(RuntimeError):
            auto_update.validate_archive(path, mac=True)
    def test_symlink_chain_cannot_escape_during_extraction(self):
        path = self.root / 'release.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, target in [('WorshipUploader/a/b', '..'), ('WorshipUploader/c', 'a/b/../../outside')]:
                item = zipfile.ZipInfo(name)
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(item, target)
        with self.assertRaises(RuntimeError):
            auto_update.validate_archive(path, mac=True)
    def test_verified_download_and_corruption(self):
        data = b'update contents'
        release = {'download_url': 'https://github.com/marushan491/lwmc-nbg-uploader/releases/download/v1.2.0/WorshipUploader-Linux-x64.zip',
                   'digest': 'sha256:' + hashlib.sha256(data).hexdigest(), 'size': len(data)}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [data]
        with patch.object(auto_update.requests, 'get', return_value=response):
            output = self.root / 'download.zip'
            auto_update.download_release(release, output)
            self.assertEqual(output.read_bytes(), data)
            response.iter_content.return_value = [b'corrupted']
            with self.assertRaisesRegex(RuntimeError, 'Prüfsumme'):
                auto_update.download_release(release, output)
    def test_prepare_preserves_own_files_and_rejects_wrong_version(self):
        target = self.root / 'installed'
        target.mkdir()
        (target / 'WorshipUploader').write_text('old')
        (target / 'update-helper').write_text('helper')
        (target / 'my-recording.wav').write_text('private recording')
        release = {'platform': 'Linux-x64', 'version': 'v1.2.0'}
        archive = self.root / 'release.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('WorshipUploader/WorshipUploader', 'new')
            z.writestr('WorshipUploader/update-manifest.json', '{"version":"1.2.0","platform":"Linux-x64"}')
        def download(_, dest, progress):
            shutil.copyfile(archive, dest)
        with patch.object(auto_update, 'download_release', side_effect=download):
            helper, manifest = auto_update.prepare_update(release, target/'WorshipUploader', 'Linux-x64')
            data = json.loads(manifest.read_text())
            self.assertEqual((Path(data['staged'])/'my-recording.wav').read_text(), 'private recording')
            self.assertEqual((target/'WorshipUploader').read_text(), 'old')
            self.assertTrue(helper.exists())
            release['version'] = 'v1.3.0'
            with self.assertRaisesRegex(RuntimeError, 'Versionsnummer'):
                auto_update.prepare_update(release, target/'WorshipUploader', 'Linux-x64')
    def test_source_code_does_not_replace_python_interpreter(self):
        with patch.object(sys, 'frozen', False, create=True), self.assertRaises(RuntimeError):
            auto_update.prepare_update({})


@unittest.skipIf(os.name == 'nt', 'Uses a POSIX executable fixture; Windows swap/rollback tested above')
class RealRestartTests(unittest.TestCase):
    def test_restart_acknowledges_new_version_in_separate_process(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target, work = root/'WorshipUploader', root/'.lwmc-update-test'
            staged = work/'unpacked'/'WorshipUploader'
            target.mkdir()
            staged.mkdir(parents=True)
            (target/'WorshipUploader').write_text('old')
            exe = staged/'WorshipUploader'
            exe.write_text('#!' + sys.executable + '\nimport os,json\nfrom pathlib import Path\n'
                           'Path(os.environ["LWMC_UPDATE_READY"]).write_text(json.dumps({"version":"1.2.0"}))\n')
            exe.chmod(0o755)
            manifest = work/'install.json'
            manifest.write_text(json.dumps({'target':str(target),'staged':str(staged),
                'backup':str(root/'.lwmc-backup-test'),'executable':'WorshipUploader','pid':123,'version':'1.2.0'}))
            processes = []
            def restart(*args):
                process = update_core.launch(*args)
                processes.append(process)
                return process
            update_core.apply_update(manifest, wait=Mock(), restart=restart, startup_timeout=5)
            for process in processes:
                process.wait(timeout=5)
            self.assertTrue((work/'finished.json').exists())
