import io
import re
import time

import chess.pgn
import requests

from zugup.importers.pgn import clean, extract_moves, store_parsed
from zugup.storage.db import latest_played_at

SOURCE = "chesscom"
ARCHIVES_URL = "https://api.chess.com/pub/player/{username}/games/archives"
USER_AGENT = "zugup-personal-tool"
RETRY_WAIT = 60
MAX_RETRIES = 3
MOVE_SUFFIX = re.compile(r"^\d+\.")


class ChesscomError(Exception):
    pass


def get_json(url, sleep=time.sleep):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    def get():
        return requests.get(url, headers=headers, timeout=(10, 60))

    resp = get()
    for _ in range(MAX_RETRIES):
        if resp.status_code != 429:
            break
        sleep(RETRY_WAIT)
        resp = get()
    if resp.status_code != 200:
        raise ChesscomError(f"Chess.com returned HTTP {resp.status_code} for {url}")
    return resp.json()


def opening_name(url):
    if not url:
        return None
    parts = []
    for part in url.rstrip("/").rsplit("/", 1)[-1].split("-"):
        if MOVE_SUFFIX.match(part):
            break
        parts.append(part)
    return " ".join(parts) or None


def parse_game(raw, username):
    if raw.get("rules") != "chess":
        return None
    game = chess.pgn.read_game(io.StringIO(raw.get("pgn") or ""))
    if game is None:
        return None
    h = game.headers
    link = raw.get("url") or h.get("Link")
    if not link or "UTCDate" not in h or "UTCTime" not in h:
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
        "game_id": link.split("/game/", 1)[-1],
        "played_at": f"{h['UTCDate'].replace('.', '-')}T{h['UTCTime']}Z",
        "white": h["White"],
        "black": h["Black"],
        "user_color": color,
        "result": h["Result"],
        "time_control": clean(h.get("TimeControl")),
        "speed": raw.get("time_class"),
        "opening_eco": clean(h.get("ECO")),
        "opening_name": opening_name(h.get("ECOUrl")),
        "pgn": raw["pgn"],
    }
    return meta, extract_moves(game)


def select_months(archives, last_played_at):
    months = sorted(archives, key=lambda url: url[-7:])
    if last_played_at is not None:
        current = last_played_at[:7].replace("-", "/")
        months = [url for url in months if url[-7:] >= current]
    return months[::-1]


def import_games(conn, username, max_games=None, dry_run=False, sleep=time.sleep, speeds=None):
    archives = get_json(ARCHIVES_URL.format(username=username), sleep)["archives"]
    last = latest_played_at(conn, SOURCE)
    stats = {"fetched": 0, "new": 0, "skipped": 0}
    for url in select_months(archives, last):
        games = get_json(url, sleep).get("games", [])
        for raw in reversed(games):
            parsed = parse_game(raw, username)
            if parsed is None or (speeds and parsed[0]["speed"] not in speeds):
                continue
            store_parsed(conn, SOURCE, parsed, stats, dry_run)
            if max_games and stats["new"] >= max_games:
                return stats
    return stats
