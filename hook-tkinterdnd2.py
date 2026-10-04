"""Ship only the TkDnD native library for the build's OS and architecture."""
import platform
import tkinter
from PyInstaller.utils.hooks import collect_data_files

system, machine = platform.system(), platform.machine().lower()
folder = {'Windows': 'win-x64', 'Linux': 'linux-x64', 'Darwin': 'osx-x64'}[system]
if machine in ('arm64', 'aarch64'):
    folder = {'Darwin': 'osx-arm64', 'Linux': 'linux-arm64', 'Windows': 'win-arm64'}[system]
# Tcl 8 and Tcl 9 variants use the same native library basename. Shipping both
# can cause the loader to pick the wrong ABI in a frozen Linux application.
if tkinter.TclVersion >= 9:
    folder += '-tcl9'
datas = collect_data_files('tkinterdnd2', includes=[f'tkdnd/{folder}/**'])
