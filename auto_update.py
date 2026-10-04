"""Download verified release, stage beside the installation, start offline helper."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
import requests
from updates import platform_label, trusted_release_url, version_tuple
from update_core import clean_environment, detached_options

MAX_DOWNLOAD = 600 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def installation(executable=None, label=None):
    label = label or platform_label()
    exe = Path(executable or sys.executable).resolve()
    if label.startswith('macOS'):
        target = next((p for p in exe.parents if p.suffix == '.app'), None)
        if target is None:
            raise RuntimeError('Auto-Update benötigt die installierte WorshipUploader.app.')
        if 'AppTranslocation' in str(target):
            raise RuntimeError('Bitte die App zuerst in Programme oder einen eigenen Ordner verschieben und dort starten.')
        relative = Path('Contents/MacOS/WorshipUploader')
        helper = target / 'Contents/Resources/update-helper'
    else:
        target = exe.parent
        relative = Path('WorshipUploader.exe' if label.startswith('Windows') else 'WorshipUploader')
        helper = target / ('update-helper.exe' if label.startswith('Windows') else 'update-helper')
    if target.is_symlink() or not (target / relative).is_file() or not helper.is_file():
        raise RuntimeError('Auto-Update benötigt das vollständige Desktop-Paket inklusive Update-Helfer.')
    return target, relative, helper


def validate_archive(archive, mac=False):
    total = 0
    with zipfile.ZipFile(archive) as z:
        links = {}
        for item in z.infolist():
            name = item.filename
            path = PurePosixPath(name)
            if ('\\' in name or path.is_absolute() or '..' in path.parts or not path.parts
                    or ':' in name or path.parts[0] not in ('WorshipUploader', '__MACOSX')
                    or (path.parts[0] == '__MACOSX' and not mac)):
                raise RuntimeError('Das Update-Paket enthält einen ungültigen Dateipfad.')
            total += item.file_size
            if total > MAX_EXPANDED:
                raise RuntimeError('Das entpackte Update-Paket ist zu groß.')
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                link = PurePosixPath(z.read(item).decode('utf-8'))
                # macOS framework links may use .., but must stay inside the top-level package.
                depth = len(path.parent.parts)
                if link.is_absolute() or '\\' in str(link):
                    raise RuntimeError('Ungültige Verknüpfung im Update-Paket.')
                for part in link.parts:
                    depth += -1 if part == '..' else (0 if part == '.' else 1)
                    if depth < 1:
                        raise RuntimeError('Verknüpfung verlässt das Update-Paket.')
                if not mac:
                    raise RuntimeError('Unerwartete Verknüpfung im Update-Paket.')
                links[path.parts] = link.parts
        # Resolve links virtually before ditto writes anything. This also checks chains
        # where an ancestor link plus a later '..' could escape the package.
        for item in z.infolist():
            pending = list(PurePosixPath(item.filename).parts)
            resolved, expansions = [], 0
            while pending:
                part = pending.pop(0)
                if part == '..':
                    if len(resolved) <= 1:
                        raise RuntimeError('Verknüpfung verlässt das Update-Paket.')
                    resolved.pop()
                elif part != '.':
                    resolved.append(part)
                    link = links.get(tuple(resolved))
                    if link is not None:
                        expansions += 1
                        if expansions > 64:
                            raise RuntimeError('Zyklische Verknüpfung im Update-Paket.')
                        resolved.pop()
                        pending = list(link) + pending


def extract_archive(archive, destination, mac=False):
    validate_archive(archive, mac)
    if mac:
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(destination)],
                       env=clean_environment(), check=True, capture_output=True, timeout=120)
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(destination)
            if os.name != 'nt':
                for item in z.infolist():
                    path = destination / item.filename
                    if path.is_file():
                        mode = item.external_attr >> 16
                        path.chmod(0o755 if mode & 0o111 else 0o644)


def download_release(release, destination, progress=lambda value: None):
    url = release.get('download_url')
    expected = release.get('digest') or ''
    if not url or not trusted_release_url(url, download=True):
        raise RuntimeError('Kein gültiger Download für dieses Betriebssystem vorhanden.')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', expected):
        raise RuntimeError('GitHub liefert keine SHA-256-Prüfsumme für dieses Paket. Bitte später erneut versuchen.')
    digest, received = hashlib.sha256(), 0
    with requests.get(url, stream=True, timeout=(10, 30)) as response:
        response.raise_for_status()
        size = release.get('size') or int(response.headers.get('Content-Length', 0))
        if size > MAX_DOWNLOAD:
            raise RuntimeError('Das Update-Paket ist zu groß.')
        with destination.open('wb') as f:
            for chunk in response.iter_content(1024 * 256):
                if not chunk:
                    continue
                received += len(chunk)
                if received > MAX_DOWNLOAD:
                    raise RuntimeError('Das Update-Paket ist zu groß.')
                f.write(chunk)
                digest.update(chunk)
                progress(f'Update herunterladen: {received / size:.0%}' if size else f'Update herunterladen: {received // (1024*1024)} MB')
    if digest.hexdigest().lower() != expected[7:].lower() or (size and size != received):
        raise RuntimeError('Die Update-Datei ist unvollständig oder ihre Prüfsumme stimmt nicht. Die Anwendung bleibt unverändert.')


def prepare_update(release, executable=None, label=None, progress=lambda value: None):
    if executable is None and not getattr(sys, 'frozen', False):
        raise RuntimeError('Auto-Update ist im Desktop-Paket verfügbar; Quellcode bitte über Git aktualisieren.')
    label = label or platform_label()
    if release.get('platform') != label:
        raise RuntimeError('Das Update passt nicht zu diesem Betriebssystem.')
    version_tuple(release['version'])
    target, relative, helper = installation(executable, label)
    try:
        work = Path(tempfile.mkdtemp(prefix='.lwmc-update-', dir=target.parent))
    except OSError as exc:
        raise RuntimeError('Der Programmordner ist schreibgeschützt. Bitte die App in einem eigenen, beschreibbaren Ordner starten.') from exc
    try:
        download = work / 'release.zip'
        download_release(release, download, progress)
        progress('Download geprüft. Update wird vorbereitet …')
        extracted = work / 'unpacked'
        extracted.mkdir()
        extract_archive(download, extracted, label.startswith('macOS'))
        package = extracted / 'WorshipUploader'
        staged = package / 'WorshipUploader.app' if label.startswith('macOS') else package
        info_path = staged / 'Contents/Resources/update-manifest.json' if label.startswith('macOS') else staged / 'update-manifest.json'
        info = json.loads(info_path.read_text(encoding='utf-8'))
        if info != {'version': release['version'].lstrip('v'), 'platform': label} or not (staged / relative).is_file():
            raise RuntimeError('Versionsnummer oder Betriebssystem im Update-Paket stimmt nicht.')
        # Keep files users put beside the Windows/Linux app, including local exports.
        if not label.startswith('macOS'):
            managed = {'WorshipUploader', 'WorshipUploader.exe', '_internal', 'update-helper', 'update-helper.exe',
                       'update-manifest.json', 'README.md', 'LICENSE', 'config.example.json', 'licenses'}
            for path in target.iterdir():
                if path.name not in managed:
                    destination = staged / path.name
                    if destination.exists():
                        raise RuntimeError('Eine eigene Datei kollidiert mit dem Update: ' + path.name)
                    if path.is_dir() and not path.is_symlink():
                        shutil.copytree(path, destination, symlinks=True)
                    else:
                        shutil.copy2(path, destination, follow_symlinks=False)
        helper_copy = work / helper.name
        shutil.copy2(helper, helper_copy)
        manifest = work / 'install.json'
        manifest.write_text(json.dumps({'target': str(target), 'staged': str(staged),
            'backup': str(target.parent / ('.lwmc-backup-' + uuid.uuid4().hex)),
            'pid': os.getpid(), 'executable': str(relative), 'version': release['version'].lstrip('v')}), encoding='utf-8')
        download.unlink()
        return helper_copy, manifest
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def start_installer(prepared):
    helper, manifest = prepared
    return subprocess.Popen([str(helper), str(manifest)], cwd=manifest.parent,
                            env=clean_environment(), **detached_options())
