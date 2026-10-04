"""Ship only the TkDnD native library for the build's OS and architecture."""
import platform
import tkinter
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

system, machine = platform.system(), platform.machine().lower()
folder = {'Windows': 'win-x64', 'Linux': 'linux-x64', 'Darwin': 'osx-x64'}[system]
if machine in ('arm64', 'aarch64'):
    folder = {'Darwin': 'osx-arm64', 'Linux': 'linux-arm64', 'Windows': 'win-arm64'}[system]
# Match the native library ABI to the Tcl interpreter bundled by PyInstaller.
if tkinter.TclVersion >= 9:
    folder += '-tcl9'
datas = collect_data_files('tkinterdnd2', includes=[f'tkdnd/{folder}/**'])
# collect_data_files omits .so files as potential Python extensions. Include
# native binaries explicitly so Linux receives libtkdnd, too.
binaries = [(source, destination) for source, destination in collect_dynamic_libs('tkinterdnd2')
            if f'/tkdnd/{folder}/' in Path(source).as_posix()]
