import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_WORKERS = 8
STOCKFISH_ENV = "ZUGUP_STOCKFISH"
STOCKFISH_LOCATIONS = (
    "/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish", "/usr/games/stockfish", "/usr/bin/stockfish",
)


def default_workers():
    return max(1, min(MAX_WORKERS, (os.cpu_count() or 2) * 2 // 3))


def default_config():
    return {
        "stockfish": {"path": "", "depth": 16, "threads": 1, "hash_mb": 128},
        "analysis": {"workers": default_workers()},
        "storage": {"db_path": str(ROOT / "data" / "zugup.db")},
    }


def usable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_stockfish():
    candidates = [os.environ.get(STOCKFISH_ENV), shutil.which("stockfish"), *STOCKFISH_LOCATIONS]
    return next((path for path in candidates if usable(path)), "")


def engine_path(cfg, stored=""):
    return stored or (cfg.get("stockfish") or {}).get("path") or find_stockfish()
