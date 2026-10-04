"""Build ZIP with executable, instructions and third-party license notices."""
from pathlib import Path
import importlib.metadata
import shutil
import sys
import subprocess

label = sys.argv[1]
root = Path('dist/WorshipUploader')
for name in ('README.md', 'LICENSE', 'config.example.json'):
    shutil.copy(name, root / name)
licenses = root / 'licenses'
licenses.mkdir(exist_ok=True)
for distribution in importlib.metadata.distributions():
    for file in distribution.files or []:
        if any(word in str(file).lower() for word in ('license', 'copying', 'notice')):
            src = Path(distribution.locate_file(file))
            if src.is_file():
                dest = licenses / distribution.metadata['Name'] / str(file).replace('..', '_')
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
if label.startswith('macOS'):
    # Ship the native .app, without the Terminal-launching Start.command.
    root.mkdir(exist_ok=True)
    destination = root / 'WorshipUploader.app'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(Path('dist/WorshipUploader.app'), destination, symlinks=True)
    shutil.rmtree(root / '_internal', ignore_errors=True)
    (root / 'WorshipUploader').unlink(missing_ok=True)
Path('release').mkdir(exist_ok=True)
archive = Path('release') / ('WorshipUploader-' + label)
if label.startswith('macOS'):
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(root), str(archive.with_suffix('.zip'))], check=True)
else:
    shutil.make_archive(str(archive), 'zip', 'dist', 'WorshipUploader')
