import sqlite3

import pytest

from zugup.storage.db import add_game, connect, exercise_attempts, record_attempt

GAME = {
    "source": "lichess",
    "game_id": "abc12345",
    "played_at": "2026-01-01T10:00:00Z",
    "white": "niamo",
    "black": "opponent",
    "user_color": "white",
    "result": "1-0",
    "time_control": "600+0",
    "opening_eco": "C50",
    "opening_name": "Italian Game",
    "pgn": "1. e4 e5 *",
}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_schema_creates_all_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"games", "moves", "evals", "mistakes", "attempts"} <= names


def test_connect_is_idempotent(tmp_path):
    connect(tmp_path / "test.db").close()
    connect(tmp_path / "test.db").close()


def test_add_game_twice_no_duplicate(conn):
    first = add_game(conn, GAME)
    second = add_game(conn, GAME)
    assert first is not None
    assert second is None
    assert count(conn, "games") == 1


def test_same_game_id_on_other_source_is_distinct(conn):
    add_game(conn, GAME)
    add_game(conn, {**GAME, "source": "chesscom"})
    assert count(conn, "games") == 2


def test_invalid_source_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_game(conn, {**GAME, "source": "other"})


def test_delete_game_cascades_to_moves(conn):
    gid = add_game(conn, GAME)
    conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'e4', 'e2e4', 'fen')",
        (gid,),
    )
    conn.execute("DELETE FROM games WHERE id = ?", (gid,))
    assert count(conn, "moves") == 0


def test_connect_adds_speed_column_to_existing_db(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, source TEXT, game_id TEXT)")
    old.commit()
    old.close()
    conn = connect(path)
    assert "speed" in {r["name"] for r in conn.execute("PRAGMA table_info(games)")}


@pytest.fixture
def move_id(conn):
    gid = add_game(conn, GAME)
    cur = conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'e4', 'e2e4', 'fen')",
        (gid,),
    )
    conn.commit()
    return cur.lastrowid


def test_record_attempts_are_returned_in_order(conn, move_id):
    record_attempt(conn, move_id, "d2d4", False, "2026-10-26T10:00:00Z")
    record_attempt(conn, move_id, "e2e4", True, "2026-10-26T10:05:00Z")
    assert exercise_attempts(conn, move_id) == [
        {"id": 1, "played_uci": "d2d4", "correct": False, "attempted_at": "2026-10-26T10:00:00Z"},
        {"id": 2, "played_uci": "e2e4", "correct": True, "attempted_at": "2026-10-26T10:05:00Z"},
    ]


def test_attempt_timestamp_defaults_to_now_utc(conn, move_id):
    record_attempt(conn, move_id, "e2e4", True)
    stamp = exercise_attempts(conn, move_id)[0]["attempted_at"]
    assert stamp.endswith("Z") and len(stamp) == 20


def test_attempts_only_for_the_requested_move(conn, move_id):
    record_attempt(conn, move_id, "e2e4", True)
    assert exercise_attempts(conn, move_id + 1) == []


def test_attempt_requires_existing_move(conn):
    with pytest.raises(sqlite3.IntegrityError):
        record_attempt(conn, 999, "e2e4", True)


def test_delete_move_cascades_to_attempts(conn, move_id):
    record_attempt(conn, move_id, "e2e4", True)
    conn.execute("DELETE FROM moves WHERE id = ?", (move_id,))
    assert count(conn, "attempts") == 0


def test_existing_database_gets_attempts_table(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, source TEXT, game_id TEXT)")
    old.commit()
    old.close()
    conn = connect(path)
    assert "attempts" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_connect_adds_the_classified_column_to_an_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE games (id INTEGER PRIMARY KEY, source TEXT NOT NULL, game_id TEXT NOT NULL, played_at TEXT NOT NULL, "
        "white TEXT NOT NULL, black TEXT NOT NULL, user_color TEXT NOT NULL, result TEXT NOT NULL, time_control TEXT, "
        "speed TEXT, opening_eco TEXT, opening_name TEXT, pgn TEXT NOT NULL, UNIQUE (source, game_id))"
    )
    old.execute("INSERT INTO games (source, game_id, played_at, white, black, user_color, result, pgn) VALUES ('lichess', 'a', 'x', 'w', 'b', 'white', '1-0', '*')")
    old.commit()
    old.close()
    conn = connect(path)
    assert conn.execute("SELECT classified FROM games").fetchone()[0] == 0
