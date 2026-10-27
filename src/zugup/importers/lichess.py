import io
import re
import time
from datetime import datetime, timezone

import chess.pgn
import requests

from zugup.importers.pgn import clean, extract_moves, store_parsed
from zugup.storage.db import latest_played_at

SOURCE = "lichess"
URL = "https://lichess.org/api/games/user/{username}"
PERF_TYPES = "ultraBullet,bullet,blitz,rapid,classical,correspondence"
SPEED_PERF_TYPES = {"bullet": ("ultraBullet", "bullet"), "blitz": ("blitz",), "rapid": ("rapid",)}


def perf_types(speeds):
    if not speeds:
        return PERF_TYPES
    return ",".join(perf for speed in speeds for perf in SPEED_PERF_TYPES[speed])
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
EVENT_SPEED = re.compile(r"(\w+) game$", re.IGNORECASE)
RETRY_WAIT = 60
MAX_RETRIES = 3


class LichessError(Exception):
    pass


def fetch_pgn(username, token, max_games=None, since_ms=None, sleep=time.sleep, speeds=None):
    if not token:
        raise LichessError("LICHESS_API_TOKEN is not set")
    params = {"evals": "true", "clocks": "true", "opening": "true", "perfType": perf_types(speeds)}
    if max_games:
        params["max"] = max_games
    if since_ms:
        params["since"] = since_ms
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/x-chess-pgn"}

    def get():
        return requests.get(
            URL.format(username=username), params=params, headers=headers, timeout=(10, 300)
        )

    resp = get()
    for _ in range(MAX_RETRIES):
        if resp.status_code != 429:
            break
        sleep(RETRY_WAIT)
        resp = get()
    if resp.status_code != 200:
        raise LichessError(f"Lichess returned HTTP {resp.status_code}")
    resp.encoding = "utf-8"
    return resp.text


def event_speed(event):
    match = EVENT_SPEED.search(event or "")
    if not match:
        return None
    speed = match.group(1).lower()
    return "bullet" if speed == "ultrabullet" else speed


def parse_game(game, username):
    h = game.headers
    if h.get("Variant", "Standard") != "Standard":
        return None
    user = username.lower()
    if h.get("White", "").lower() == user:
        color = "white"
    elif h.get("Black", "").lower() == user:
        color = "black"
    else:
        return None

    meta = {
        "source": SOURCE,
        "game_id": h.get("GameId") or h["Site"].rstrip("/").rsplit("/", 1)[-1],
        "played_at": f"{h['UTCDate'].replace('.', '-')}T{h['UTCTime']}Z",
        "white": h["White"],
        "black": h["Black"],
        "user_color": color,
        "result": h["Result"],
        "time_control": clean(h.get("TimeControl")),
        "speed": event_speed(h.get("Event")),
        "opening_eco": clean(h.get("ECO")),
        "opening_name": clean(h.get("Opening")),
        "pgn": str(game),
    }

    return meta, extract_moves(game, eval_origin="lichess")


def parse_games(text, username):
    handle = io.StringIO(text)
    while (game := chess.pgn.read_game(handle)) is not None:
        parsed = parse_game(game, username)
        if parsed:
            yield parsed


def since_ms(conn):
    last = latest_played_at(conn, SOURCE)
    if last is None:
        return None
    return int(datetime.strptime(last, TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp() * 1000)


def import_games(conn, username, token, max_games=None, dry_run=False, sleep=time.sleep, speeds=None):
    text = fetch_pgn(username, token, max_games, since_ms(conn), sleep, speeds)
    stats = {"fetched": 0, "new": 0, "skipped": 0}
    for parsed in parse_games(text, username):
        store_parsed(conn, SOURCE, parsed, stats, dry_run)
        if max_games and stats["new"] >= max_games:
            break
    return stats
