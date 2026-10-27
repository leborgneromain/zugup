import re

from zugup.config import usable
from zugup.i18n import LANGUAGES
from zugup.storage.db import get_preferences, set_preference

SPEEDS = ("bullet", "blitz", "rapid")
SOURCES = ("lichess", "chesscom")
USERNAME = re.compile(r"^[A-Za-z0-9_-]{2,30}$")
LIMIT_RANGE = (1, 500)
DEPTHS = (14, 15, 16)
THEMES = ("dark", "light")
DEFAULTS = {"speeds": list(SPEEDS), "accounts": {s: "" for s in SOURCES}, "import_limit": 50, "depth": 16, "import_speeds": list(SPEEDS), "theme": "dark", "language": "fr", "stockfish_path": ""}


def load(conn):
    stored = get_preferences(conn)
    loaded = {key: stored.get(key, default) for key, default in DEFAULTS.items()}
    loaded["accounts"] = {**DEFAULTS["accounts"], **loaded["accounts"]}
    return loaded


def clean_speeds(speeds):
    if not isinstance(speeds, list) or not speeds or not set(speeds) <= set(SPEEDS):
        raise ValueError(f"Speeds must be a non-empty list of {', '.join(SPEEDS)}")
    return [s for s in SPEEDS if s in speeds]


def clean_accounts(value):
    if not isinstance(value, dict) or not set(value) <= set(SOURCES):
        raise ValueError(f"'accounts' must be an object with keys among {', '.join(SOURCES)}")
    for name in value.values():
        if not isinstance(name, str) or (name and not USERNAME.match(name)):
            raise ValueError("Invalid username")
    return value


def clean_limit(value):
    low, high = LIMIT_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"'import_limit' must be an integer between {low} and {high}")
    return value


def clean_depth(value):
    if isinstance(value, bool) or value not in DEPTHS:
        raise ValueError(f"'depth' must be one of {', '.join(str(d) for d in DEPTHS)}")
    return value


def clean_theme(value):
    if value not in THEMES:
        raise ValueError(f"'theme' must be one of {', '.join(THEMES)}")
    return value


def clean_language(value):
    if value not in LANGUAGES:
        raise ValueError(f"'language' must be one of {', '.join(LANGUAGES)}")
    return value


def clean_stockfish_path(value):
    if not isinstance(value, str) or len(value) > 500 or "\0" in value:
        raise ValueError("'stockfish_path' must be a string")
    value = value.strip()
    if value and not usable(value):
        raise ValueError("Stockfish not found at this path")
    return value


CLEANERS = {"speeds": clean_speeds, "import_speeds": clean_speeds, "accounts": clean_accounts, "import_limit": clean_limit, "depth": clean_depth, "theme": clean_theme, "language": clean_language, "stockfish_path": clean_stockfish_path}


def clean(payload):
    if not isinstance(payload, dict) or not set(payload) <= set(DEFAULTS):
        raise ValueError("Unknown preference")
    return {key: CLEANERS[key](value) for key, value in payload.items()}


def save(conn, payload):
    cleaned = clean(payload)
    if "accounts" in cleaned:
        cleaned["accounts"] = {**load(conn)["accounts"], **cleaned["accounts"]}
    for key, value in cleaned.items():
        set_preference(conn, key, value)
    return load(conn)
