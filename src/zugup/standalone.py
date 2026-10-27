import os
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

import requests

from zugup.config import default_workers
from zugup.web import app as web

APP_NAME = "ZugUp"
DATA_DIR_ENV = "ZUGUP_DATA_DIR"
NO_BROWSER_ENV = "ZUGUP_NO_BROWSER"
BROWSER_DELAY = 1.5


def data_dir():
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def bundle_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def stockfish_path():
    name = "stockfish.exe" if sys.platform == "win32" else "stockfish"
    return bundle_dir() / "stockfish" / name


def build_config(folder):
    return {
        "stockfish": {"path": str(stockfish_path()), "depth": 16, "threads": 1, "hash_mb": 128},
        "analysis": {"workers": default_workers()},
        "storage": {"db_path": str(Path(folder) / "zugup.db")},
        "standalone": True,
    }


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((web.HOST, port))
        except OSError:
            return False
    return True


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((web.HOST, 0))
        return sock.getsockname()[1]


def is_zugup(port):
    try:
        body = requests.get(f"http://{web.HOST}:{port}/api/preferences", timeout=1).json()
    except (requests.RequestException, ValueError):
        return False
    return isinstance(body, dict) and "import_speeds" in body


def open_browser(port):
    if not os.environ.get(NO_BROWSER_ENV):
        threading.Timer(BROWSER_DELAY, webbrowser.open, args=(f"http://{web.HOST}:{port}/",)).start()


def log_to_file(folder):
    stream = open(Path(folder) / "zugup.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = stream


def main():
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        log_to_file(folder)
    port = web.DEFAULT_PORT
    if not port_is_free(port):
        if is_zugup(port):
            open_browser(port)
            return 0
        port = free_port()
    open_browser(port)
    try:
        web.serve(build_config(folder), port)
    except Exception:
        traceback.print_exc()
        return 1
    return 0
