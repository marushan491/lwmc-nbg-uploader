"""CI: extract the actual built ZIP, verify its platform/version and bundled helper."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import signal
import sys
import tempfile
import time
from auto_update import extract_archive, installation, prepare_update, start_installer
from app_version import VERSION
from update_core import clean_environment, wait_for_exit
from unittest.mock import patch

archive, label = Path(sys.argv[1]).resolve(), sys.argv[2]
with tempfile.TemporaryDirectory() as d:
    destination = Path(d)
    extract_archive(archive, destination, label.startswith('macOS'))
    package = destination / 'WorshipUploader'
    exe = (package / 'WorshipUploader.app/Contents/MacOS/WorshipUploader' if label.startswith('macOS') else
           package / ('WorshipUploader.exe' if label.startswith('Windows') else 'WorshipUploader'))
    target, relative, helper = installation(exe, label)
    info_path = target/'Contents/Resources/update-manifest.json' if label.startswith('macOS') else target/'update-manifest.json'
    assert json.loads(info_path.read_text()) == {'version': VERSION, 'platform': label}
    subprocess.run([str(exe), '--version'], check=True, timeout=60)
    subprocess.run([str(helper), '--self-test'], check=True, timeout=60)
    print('Verified update package:', label, VERSION)
    if not label.startswith('macOS'):
        # Exercise real executables and file locks, not only Python installer functions.
        state = destination / 'state'
        state.mkdir()
        (state / 'config.json').write_text('{"updates":{"check_on_start":false}}')
        os.environ['AUDIO_UPLOADER_STATE'] = str(state)
        bootstrap = destination / '.lwmc-update-bootstrap'
        bootstrap.mkdir()
        original_ready = bootstrap / 'ready.json'
        env = clean_environment()
        env['LWMC_UPDATE_READY'] = str(original_ready)
        old = subprocess.Popen([str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        restarted_pid = None
        installer = None
        def await_file(path, timeout=60):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if path.exists():
                    return
                for error_path in destination.glob('.lwmc-update-*/error.json'):
                    raise RuntimeError(error_path.read_text())
                time.sleep(.2)
            raise RuntimeError('Missing update acknowledgement: ' + str(path))
        try:
            await_file(original_ready)
            release = {'version': 'v' + VERSION, 'platform': label}
            def local_download(_, dest, progress):
                shutil.copyfile(archive, dest)
            with patch('auto_update.download_release', side_effect=local_download):
                prepared = prepare_update(release, exe, label)
            manifest = prepared[1]
            data = json.loads(manifest.read_text())
            data['pid'] = old.pid
            manifest.write_text(json.dumps(data))
            installer = start_installer(prepared)
            await_file(manifest.with_name('started.json'))
            assert old.poll() is None, 'Old application must be running until handoff'
            old.terminate()
            old.wait(timeout=30)
            await_file(manifest.with_name('ready.json'))
            ready = json.loads(manifest.with_name('ready.json').read_text())
            restarted_pid = ready['pid']
            assert ready['version'] == VERSION and restarted_pid != old.pid
            await_file(manifest.with_name('finished.json'))
            installer.wait(timeout=30)
            assert installer.returncode == 0
            assert not Path(data['backup']).exists()
            print('Verified packaged update, parent shutdown, file replacement and GUI restart:', label)
        finally:
            if old.poll() is None:
                old.terminate()
                old.wait(timeout=10)
            if restarted_pid:
                try:
                    os.kill(restarted_pid, signal.SIGTERM)
                    wait_for_exit(restarted_pid, timeout=15)
                except ProcessLookupError:
                    pass
            if installer and installer.poll() is None:
                installer.terminate()
                installer.wait(timeout=10)
