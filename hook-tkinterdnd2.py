"""Ship only the TkDnD native library for the build's OS and architecture."""
import platform
from PyInstaller.utils.hooks import collect_data_files

system, machine = platform.system(), platform.machine().lower()
folder = {'Windows': 'win-x64', 'Linux': 'linux-x64', 'Darwin': 'osx-x64'}[system]
if machine in ('arm64', 'aarch64'):
    folder = {'Darwin': 'osx-arm64', 'Linux': 'linux-arm64', 'Windows': 'win-arm64'}[system]
datas = collect_data_files('tkinterdnd2', includes=[f'tkdnd/{folder}/**', f'tkdnd/{folder}-tcl9/**'])
