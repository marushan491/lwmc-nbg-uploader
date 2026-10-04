"""CI: extract the actual built ZIP, verify its platform/version and bundled helper."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from auto_update import extract_archive, installation
from app_version import VERSION

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
