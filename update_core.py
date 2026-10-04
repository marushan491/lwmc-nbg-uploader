"""Offline installation helper. Runs outside the application being replaced."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def clean_environment():
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        original = env.pop(name + '_ORIG', None)
        env.pop(name, None)
        if original:
            env[name] = original
    return env


def detached_options():
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    return options


def wait_for_exit(pid, timeout=60):
    if pid <= 0 or pid == os.getpid():
        raise RuntimeError('Ungültiger Anwendungsprozess.')
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # PID has already exited.
                return
            raise RuntimeError('Anwendungsprozess konnte nicht geprüft werden.')
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise RuntimeError('Die Anwendung wurde nicht rechtzeitig geschlossen.')
        finally:
            kernel.CloseHandle(handle)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        # A zombie has closed all its files but may not yet have been reaped.
        proc = Path(f'/proc/{pid}/stat')
        try:
            if proc.exists() and proc.read_text().rsplit(')', 1)[1].strip().startswith('Z'):
                return
        except OSError:
            pass
        time.sleep(.2)
    raise RuntimeError('Die Anwendung wurde nicht rechtzeitig geschlossen.')


def launch(target, relative_executable, ready=None):
    env = clean_environment()
    env.pop('LWMC_UPDATE_READY', None)
    if ready:
        env['LWMC_UPDATE_READY'] = str(ready)
    return subprocess.Popen([str(target / relative_executable)], cwd=target.parent,
                            env=env, **detached_options())


def rename_retry(source, destination, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        try:
            source.rename(destination)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def apply_update(manifest_path, wait=wait_for_exit, restart=launch, startup_timeout=45):
    manifest_path = Path(manifest_path).resolve()
    work = manifest_path.parent
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    raw_target, raw_staged, raw_backup = (Path(data[key]) for key in ('target', 'staged', 'backup'))
    target, staged, backup = (p.resolve() for p in (raw_target, raw_staged, raw_backup))
    relative = Path(data['executable'])
    if (not raw_target.is_absolute() or target.parent == target or not target.is_dir() or raw_target.is_symlink()
            or not staged.is_relative_to(work) or target.parent != work.parent
            or not work.name.startswith('.lwmc-update-') or raw_staged.is_symlink()
            or backup.parent != target.parent or raw_backup.is_symlink() or not backup.name.startswith('.lwmc-backup-')
            or relative.is_absolute() or '..' in relative.parts or not (staged / relative).is_file()
            or backup.exists()):
        raise RuntimeError('Ungültiger Update-Auftrag. Die Anwendung bleibt unverändert.')
    ready = work / 'ready.json'
    ready.unlink(missing_ok=True)
    (work / 'started.json').write_text('{}', encoding='utf-8')
    wait(int(data['pid']))
    moved_old = moved_new = False
    process = None
    try:
        rename_retry(target, backup)
        moved_old = True
        rename_retry(staged, target)
        moved_new = True
        process = restart(target, relative, ready)
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if ready.exists():
                try:
                    if json.loads(ready.read_text(encoding='utf-8')).get('version') == data['version']:
                        (work / 'finished.json').write_text('{"success": true}', encoding='utf-8')
                        shutil.rmtree(backup, ignore_errors=True)
                        return
                except (ValueError, OSError):
                    pass
            if process.poll() is not None:
                break
            time.sleep(.2)
        raise RuntimeError('Die neue Version konnte nicht gestartet werden. Die alte Version wird wiederhergestellt.')
    except Exception:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if moved_new:
            rename_retry(target, staged)
        if moved_old:
            rename_retry(backup, target)
            restart(target, relative)
        elif target.exists():
            restart(target, relative)
        raise


def confirm_startup(version):
    value = os.environ.pop('LWMC_UPDATE_READY', None)
    if value:
        path = Path(value)
        if path.name == 'ready.json' and path.parent.name.startswith('.lwmc-update-'):
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'version': version}), encoding='utf-8')
            temp.replace(path)


def cleanup_finished(target):
    """A previous Windows helper cannot delete its own executable while running."""
    target = Path(target).resolve()
    for work in target.parent.glob('.lwmc-update-*'):
        if not work.is_dir() or work.is_symlink() or not (work / 'finished.json').is_file():
            continue
        try:
            data = json.loads((work / 'install.json').read_text(encoding='utf-8'))
            if Path(data['target']).resolve() == target:
                shutil.rmtree(work, ignore_errors=True)
        except (OSError, ValueError, KeyError):
            pass
