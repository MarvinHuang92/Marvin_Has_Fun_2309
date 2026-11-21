"""Tractor game entry point.

Run with:
    python scripts/main.py
or double-click 01_Run.bat (which finds Python and uses pythonw).
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "run.log"

sys.path.insert(0, str(SCRIPTS_DIR))


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for handler in list(logging.root.handlers):
        logging.root.removeHandler(handler)
    handler = logging.FileHandler(str(LOG_FILE), mode="w", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[handler],
    )
    logging.getLogger(__name__).info("程序启动，项目目录：%s", PROJECT_DIR)


def _enable_dpi() -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _smoke() -> int:
    """Create the window, let it live briefly, then close.  For quick checks."""
    from tractor.ui import TractorApp
    import tkinter as tk
    root = tk.Tk()
    app = TractorApp(root, PROJECT_DIR)
    root.after(1500, root.destroy)
    root.mainloop()
    print("smoke ok", app.game.phase)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--smoke", action="store_true", help="start the GUI briefly and exit")
    args = parser.parse_args()
    setup_logging()
    _enable_dpi()
    try:
        if args.smoke:
            return _smoke()
        from tractor.ui import launch
        launch(PROJECT_DIR)
        return 0
    except Exception:
        logging.getLogger(__name__).exception("启动失败")
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror(
                "启动失败",
                f"游戏启动失败。\n详细信息见：\n{LOG_FILE}\n\n{traceback.format_exc(limit=3)}",
            )
            r.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
