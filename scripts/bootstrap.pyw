"""Initialize the local desktop environment and start the Qt application."""
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import traceback

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".studio"
PYTHON = VENV / "Scripts" / "python.exe"
TITLE = "歌声工作台"
ICON = ROOT / "voice_studio" / "assets" / "voice-cover.ico"
QT_CHECK = "from PyQt5 import QtWidgets, QtMultimedia"


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, str(message), TITLE, 0x10)


@contextlib.contextmanager
def setup_lock():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    digest = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:24]
    handle = create(None, False, "Local\\VoiceCoverStudioSetup-" + digest)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        yield error != 183  # ERROR_ALREADY_EXISTS
    finally:
        close(handle)


def run(command, log, *, check=True):
    return subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                          check=check)


def prepare(log, report):
    sys.path.insert(0, str(ROOT))
    if not PYTHON.is_file():
        report("正在创建 Python 桌面环境…")
        run([sys.executable, "-m", "venv", VENV], log)
    if run([PYTHON, "-I", "-c", QT_CHECK], log, check=False).returncode:
        report("正在安装桌面组件，首次启动需要联网…")
        run([PYTHON, "-m", "pip", "--disable-pip-version-check", "install", "-e", "."], log)
        run([PYTHON, "-I", "-c", QT_CHECK], log)
    from voice_studio.runtime import prepare_runtime
    try:
        prepare_runtime(ROOT, log, report)
    except Exception as exc:
        traceback.print_exc(file=log)
        log.flush()
        show_error(f"音频引擎准备未完成。下次启动会继续。可以先使用音频库。\n\n{exc}\n\n日志：{log.name}")


def prepare_with_status(log):
    # Tk comes with the standard Windows Python installer. A Python installation
    # without Tk can still install and launch the Qt desktop.
    def prepare_without_window():
        prepare(log, lambda text: print(text, file=log, flush=True))

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        prepare_without_window()
        return
    try:
        window = tk.Tk()
    except tk.TclError:
        prepare_without_window()
        return

    window.title(TITLE)
    window.iconbitmap(str(ICON))
    window.resizable(False, False)
    window.protocol("WM_DELETE_WINDOW", window.iconify)
    frame = ttk.Frame(window, padding=(22, 18))
    frame.pack(fill="both", expand=True)
    status = tk.StringVar(value="正在检查桌面组件…")
    ttk.Label(frame, textvariable=status, width=56).pack(anchor="w")
    bar = ttk.Progressbar(frame, mode="indeterminate")
    bar.pack(fill="x", pady=(14, 0))
    bar.start(15)
    window.update_idletasks()
    x = (window.winfo_screenwidth() - window.winfo_width()) // 2
    y = (window.winfo_screenheight() - window.winfo_height()) // 2
    window.geometry(f"+{max(0,x)}+{max(0,y)}")
    messages = queue.Queue()
    errors = []

    def worker():
        try:
            prepare(log, messages.put)
        except Exception as exc:
            errors.append(exc)
        finally:
            messages.put(None)

    def update():
        while not messages.empty():
            message = messages.get_nowait()
            if message is None:
                window.destroy()
                return
            status.set(message)
        window.after(100, update)

    task = threading.Thread(target=worker)
    task.start()
    window.after(50, update)
    window.mainloop()
    task.join()
    if errors:
        raise errors[0]


def open_log():
    home = Path(os.environ.get("VOICE_STUDIO_HOME") or
                Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VoiceCoverStudio")
    for folder in (home / "logs", Path(tempfile.gettempdir()) / "VoiceCoverStudio"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return (folder / "startup.log").open("a", encoding="utf-8", buffering=1)
        except OSError:
            continue
    raise OSError("无法创建启动日志，请检查当前账户的目录写入权限。")


def start(log):
    os.environ.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    os.chdir(ROOT)
    if "--ready" in sys.argv:
        sys.path.insert(0, str(ROOT))
        from voice_studio.app import main
        return main()

    with setup_lock() as acquired:
        if not acquired:
            return 0
        prepare_with_status(log)
        subprocess.Popen([str(PYTHON), "-I", "-X", "utf8", str(Path(__file__).resolve()), "--ready"],
                         cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT)
    return 0


def main():
    try:
        log = open_log()
    except OSError as exc:
        show_error(exc)
        return 1
    with log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            return start(log)
        except Exception as exc:
            traceback.print_exc(file=log)
            show_error(f"桌面程序启动失败。\n\n{exc}\n\n启动日志：{log.name}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
