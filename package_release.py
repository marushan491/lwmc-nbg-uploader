"""Build ZIP with executable, instructions and third-party license notices."""
from pathlib import Path
import importlib.metadata
import shutil
import sys

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
    launcher = root / 'Start.command'
    launcher.write_text('#!/bin/bash\ncd -- "$(dirname -- "$0")"\nexec ./WorshipUploader\n')
    launcher.chmod(0o755)
Path('release').mkdir(exist_ok=True)
shutil.make_archive(str(Path('release') / ('WorshipUploader-' + label)), 'zip', 'dist', 'WorshipUploader')
