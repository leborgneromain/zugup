import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('lichess', 'chesscom')),
    game_id TEXT NOT NULL,
    played_at TEXT NOT NULL,
    white TEXT NOT NULL,
    black TEXT NOT NULL,
    user_color TEXT NOT NULL CHECK (user_color IN ('white', 'black')),
    result TEXT NOT NULL,
    time_control TEXT,
    speed TEXT,
    opening_eco TEXT,
    opening_name TEXT,
    pgn TEXT NOT NULL,
    classified INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source, game_id)
);

CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    ply INTEGER NOT NULL,
    san TEXT NOT NULL,
    uci TEXT NOT NULL,
    fen_before TEXT NOT NULL,
    clock_seconds REAL,
    UNIQUE (game_id, ply)
);

CREATE TABLE IF NOT EXISTS evals (
    move_id INTEGER PRIMARY KEY REFERENCES moves(id) ON DELETE CASCADE,
    cp_before INTEGER,
    mate_before INTEGER,
    cp_after INTEGER,
    mate_after INTEGER,
    best_uci TEXT,
    depth INTEGER,
    origin TEXT NOT NULL CHECK (origin IN ('lichess', 'stockfish'))
);

CREATE TABLE IF NOT EXISTS mistakes (
    move_id INTEGER PRIMARY KEY REFERENCES moves(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (category IN ('inaccuracy', 'mistake', 'blunder')),
    cp_loss INTEGER NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('opening', 'middlegame', 'endgame'))
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    move_id INTEGER NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
    played_uci TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK (correct IN (0, 1)),
    attempted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coach_checks (
    week TEXT NOT NULL,
    speed TEXT NOT NULL,
    task TEXT NOT NULL,
    done INTEGER NOT NULL CHECK (done IN (0, 1)),
    PRIMARY KEY (week, speed, task)
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (
    source TEXT PRIMARY KEY CHECK (source IN ('lichess', 'chesscom')),
    token TEXT NOT NULL,
    username TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_move ON attempts(move_id, id);
CREATE INDEX IF NOT EXISTS idx_moves_game ON moves(game_id);
CREATE INDEX IF NOT EXISTS idx_mistakes_category ON mistakes(category, phase);
"""

GAME_FIELDS = (
    "source", "game_id", "played_at", "white", "black", "user_color",
    "result", "time_control", "speed", "opening_eco", "opening_name", "pgn",
)


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
    if "speed" not in columns:
        conn.execute("ALTER TABLE games ADD COLUMN speed TEXT")
    if "classified" not in columns:
        conn.execute("ALTER TABLE games ADD COLUMN classified INTEGER NOT NULL DEFAULT 0")
    return conn


EVAL_FIELDS = ("cp_before", "mate_before", "cp_after", "mate_after", "best_uci", "depth")


def _insert_game(conn, game):
    values = [game.get(k) for k in GAME_FIELDS]
    cur = conn.execute(
        f"INSERT INTO games ({', '.join(GAME_FIELDS)}) "
        f"VALUES ({', '.join('?' * len(GAME_FIELDS))}) "
        "ON CONFLICT (source, game_id) DO NOTHING",
        values,
    )
    return cur.lastrowid if cur.rowcount else None


def add_game(conn, game):
    with conn:
        return _insert_game(conn, game)


def save_game(conn, game, moves):
    with conn:
        row_id = _insert_game(conn, game)
        if row_id is None:
            return None
        for m in moves:
            cur = conn.execute(
                "INSERT INTO moves (game_id, ply, san, uci, fen_before, clock_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row_id, m["ply"], m["san"], m["uci"], m["fen_before"], m.get("clock_seconds")),
            )
            ev = m.get("eval")
            if ev:
                conn.execute(
                    f"INSERT INTO evals (move_id, origin, {', '.join(EVAL_FIELDS)}) "
                    f"VALUES (?, ?, {', '.join('?' * len(EVAL_FIELDS))})",
                    (cur.lastrowid, ev["origin"], *[ev.get(k) for k in EVAL_FIELDS]),
                )
        return row_id


def game_exists(conn, source, game_id):
    row = conn.execute(
        "SELECT 1 FROM games WHERE source = ? AND game_id = ?", (source, game_id)
    ).fetchone()
    return row is not None


def latest_played_at(conn, source):
    row = conn.execute("SELECT MAX(played_at) FROM games WHERE source = ?", (source,)).fetchone()
    return row[0]


def pending_games(conn, limit=None):
    rows = conn.execute(
        "SELECT g.id FROM games g WHERE EXISTS ("
        "SELECT 1 FROM moves m WHERE m.game_id = g.id "
        "AND NOT EXISTS (SELECT 1 FROM evals e WHERE e.move_id = m.id)) "
        "ORDER BY g.played_at DESC LIMIT ?",
        (limit or -1,),
    ).fetchall()
    return [r[0] for r in rows]


def game_moves(conn, game_id):
    rows = conn.execute(
        "SELECT id, ply, uci, fen_before FROM moves WHERE game_id = ? ORDER BY ply", (game_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def evaluated_games(conn):
    rows = conn.execute(
        "SELECT DISTINCT m.game_id FROM evals e JOIN moves m ON m.id = e.move_id ORDER BY m.game_id"
    ).fetchall()
    return [r[0] for r in rows]


def game_eval_moves(conn, game_id):
    rows = conn.execute(
        "SELECT m.id, m.ply, m.uci, m.fen_before, g.user_color, "
        "e.cp_before, e.mate_before, e.cp_after, e.mate_after "
        "FROM moves m JOIN games g ON g.id = m.game_id "
        "LEFT JOIN evals e ON e.move_id = m.id "
        "WHERE m.game_id = ? ORDER BY m.ply",
        (game_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def replace_mistakes(conn, game_id, rows):
    with conn:
        conn.execute(
            "DELETE FROM mistakes WHERE move_id IN (SELECT id FROM moves WHERE game_id = ?)",
            (game_id,),
        )
        conn.executemany(
            "INSERT INTO mistakes (move_id, category, cp_loss, phase) "
            "VALUES (:move_id, :category, :cp_loss, :phase)",
            rows,
        )


def save_evals(conn, rows):
    with conn:
        for r in rows:
            conn.execute(
                f"INSERT INTO evals (move_id, origin, {', '.join(EVAL_FIELDS)}) "
                f"VALUES (:move_id, :origin, {', '.join(':' + k for k in EVAL_FIELDS)}) "
                "ON CONFLICT (move_id) DO UPDATE SET origin = excluded.origin, "
                + ", ".join(f"{k} = excluded.{k}" for k in EVAL_FIELDS),
                r,
            )


def record_attempt(conn, move_id, played_uci, correct, attempted_at=None):
    attempted_at = attempted_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        cur = conn.execute(
            "INSERT INTO attempts (move_id, played_uci, correct, attempted_at) VALUES (?, ?, ?, ?)",
            (move_id, played_uci, int(bool(correct)), attempted_at),
        )
    return cur.lastrowid


def set_check(conn, week, speed, task, done):
    with conn:
        conn.execute(
            "INSERT INTO coach_checks (week, speed, task, done) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (week, speed, task) DO UPDATE SET done = excluded.done",
            (week, speed, task, int(bool(done))),
        )


def get_preferences(conn):
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM preferences")}


def set_preference(conn, key, value):
    with conn:
        conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


UNANALYZED = "EXISTS (SELECT 1 FROM moves m WHERE m.game_id = g.id AND NOT EXISTS (SELECT 1 FROM evals e WHERE e.move_id = m.id))"
HAS_MOVES = "EXISTS (SELECT 1 FROM moves m WHERE m.game_id = g.id)"


def unclassified_games(conn):
    rows = conn.execute(
        f"SELECT g.id FROM games g WHERE g.classified = 0 AND {HAS_MOVES} AND NOT {UNANALYZED} "
        "ORDER BY g.played_at DESC"
    ).fetchall()
    return [r[0] for r in rows]


def mark_classified(conn, game_id):
    with conn:
        conn.execute("UPDATE games SET classified = 1 WHERE id = ?", (game_id,))


def analysis_counts(conn):
    rows = conn.execute(
        f"SELECT g.source, SUM({UNANALYZED}), SUM({HAS_MOVES} AND NOT {UNANALYZED}) FROM games g GROUP BY g.source"
    ).fetchall()
    counts = {source: {"pending": 0, "analyzed": 0} for source in ("lichess", "chesscom")}
    counts.update({r[0]: {"pending": r[1] or 0, "analyzed": r[2] or 0} for r in rows})
    return counts


def source_stats(conn):
    rows = conn.execute("SELECT source, COUNT(*), MAX(played_at) FROM games GROUP BY source").fetchall()
    stats = {source: {"games": 0, "last": None} for source in ("lichess", "chesscom")}
    stats.update({r[0]: {"games": r[1], "last": r[2]} for r in rows})
    return stats


def reset_data(conn):
    with conn:
        deleted = conn.execute("DELETE FROM games").rowcount
        conn.execute("DELETE FROM coach_checks")
    return deleted


def get_credential(conn, source):
    row = conn.execute("SELECT token, username FROM credentials WHERE source = ?", (source,)).fetchone()
    return dict(row) if row else None


def set_credential(conn, source, token, username):
    with conn:
        conn.execute(
            "INSERT INTO credentials (source, token, username) VALUES (?, ?, ?) "
            "ON CONFLICT (source) DO UPDATE SET token = excluded.token, username = excluded.username",
            (source, token, username),
        )


def delete_credential(conn, source):
    with conn:
        conn.execute("DELETE FROM credentials WHERE source = ?", (source,))


def done_checks(conn, week, speed):
    rows = conn.execute(
        "SELECT task FROM coach_checks WHERE week = ? AND speed = ? AND done = 1", (week, speed)
    ).fetchall()
    return {r["task"] for r in rows}


def exercise_attempts(conn, move_id):
    rows = conn.execute(
        "SELECT id, played_uci, correct, attempted_at FROM attempts WHERE move_id = ? ORDER BY id",
        (move_id,),
    ).fetchall()
    return [{**dict(r), "correct": bool(r["correct"])} for r in rows]
