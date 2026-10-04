"""Small independently packaged executable, so Windows can replace the main app."""
import argparse
import json
from pathlib import Path
from update_core import apply_update


def main():
    parser = argparse.ArgumentParser(description='LWMC Update-Helfer')
    parser.add_argument('manifest', nargs='?')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return 0
    if not args.manifest:
        return 1
    try:
        apply_update(args.manifest)
        return 0
    except Exception as exc:
        path = Path(args.manifest)
        path.with_name('error.json').write_text(json.dumps({'error': str(exc)}), encoding='utf-8')
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Update konnte nicht installiert werden', str(exc))
        root.destroy()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
