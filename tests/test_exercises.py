import random

import pytest

from zugup.puzzles.exercises import available, is_mastered, list_exercises, next_exercise, priority
from zugup.storage.db import add_game, connect, record_attempt

GAME = {
    "source": "lichess", "game_id": "g1", "played_at": "2026-01-01T10:00:00Z",
    "white": "me", "black": "opp", "user_color": "white", "result": "1-0",
    "time_control": "60+0", "opening_eco": None, "opening_name": None, "pgn": "*",
}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def game_id(conn):
    return add_game(conn, GAME)


def add_exercise(conn, game_id, ply, category="blunder", best_uci="e2e4", phase="middlegame"):
    cur = conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, ?, 'x', 'a2a3', 'fen')",
        (game_id, ply),
    )
    move_id = cur.lastrowid
    conn.execute(
        "INSERT INTO evals (move_id, origin, best_uci, depth) VALUES (?, ?, ?, 10)",
        (move_id, "stockfish" if best_uci else "lichess", best_uci),
    )
    conn.execute(
        "INSERT INTO mistakes (move_id, category, cp_loss, phase) VALUES (?, ?, 300, ?)",
        (move_id, category, phase),
    )
    conn.commit()
    return move_id


def attempt(conn, move_id, *results):
    for ok in results:
        record_attempt(conn, move_id, "e2e4" if ok else "a2a3", ok)


def test_lists_only_serious_errors_with_a_reference_move(conn, game_id):
    blunder = add_exercise(conn, game_id, 1, "blunder")
    mistake = add_exercise(conn, game_id, 3, "mistake")
    add_exercise(conn, game_id, 5, "inaccuracy")
    add_exercise(conn, game_id, 7, "blunder", best_uci=None)
    assert [e["move_id"] for e in list_exercises(conn)] == [blunder, mistake]


def test_exercise_carries_position_and_context(conn, game_id):
    move_id = add_exercise(conn, game_id, 1, phase="endgame")
    (exercise,) = list_exercises(conn)
    assert exercise["move_id"] == move_id
    assert exercise["best_uci"] == "e2e4"
    assert exercise["fen_before"] == "fen"
    assert exercise["user_color"] == "white"
    assert exercise["phase"] == "endgame"
    assert exercise["results"] == []


def test_mastered_needs_last_two_attempts_correct():
    assert not is_mastered([])
    assert not is_mastered([True])
    assert not is_mastered([True, False])
    assert not is_mastered([False, True])
    assert is_mastered([False, True, True])


def test_priority_groups():
    assert priority([]) == 0
    assert priority([True, False]) == 1
    assert priority([False, True]) == 2


def test_mastered_exercise_is_not_proposed(conn, game_id):
    move_id = add_exercise(conn, game_id, 1)
    attempt(conn, move_id, False, True, True)
    assert next_exercise(conn) is None


def test_never_attempted_comes_first(conn, game_id):
    tried = add_exercise(conn, game_id, 1)
    fresh = add_exercise(conn, game_id, 3)
    attempt(conn, tried, False)
    assert {next_exercise(conn, random.Random(i))["move_id"] for i in range(20)} == {fresh}


def test_last_wrong_comes_before_one_success_pending(conn, game_id):
    wrong = add_exercise(conn, game_id, 1)
    pending = add_exercise(conn, game_id, 3)
    attempt(conn, wrong, True, False)
    attempt(conn, pending, False, True)
    assert {next_exercise(conn, random.Random(i))["move_id"] for i in range(20)} == {wrong}


def test_exercise_with_one_success_is_still_proposed_last(conn, game_id):
    pending = add_exercise(conn, game_id, 1)
    attempt(conn, pending, False, True)
    assert next_exercise(conn)["move_id"] == pending


def test_choice_inside_a_group_is_random(conn, game_id):
    ids = {add_exercise(conn, game_id, ply) for ply in (1, 3, 5)}
    picked = {next_exercise(conn, random.Random(i))["move_id"] for i in range(50)}
    assert picked == ids


def test_no_exercise_when_database_is_empty(conn):
    assert next_exercise(conn) is None


def test_player_ratings_read_from_pgn_headers():
    from zugup.puzzles.exercises import player_ratings

    assert player_ratings('[WhiteElo "1650"]\n[BlackElo "1702"]\n\n1. e4 *') == (1650, 1702)
    assert player_ratings('[Event "x"]\n\n1. e4 *') == (None, None)


@pytest.fixture
def two_speeds(conn):
    bullet = add_game(conn, {**GAME, "game_id": "b", "speed": "bullet"})
    rapid = add_game(conn, {**GAME, "game_id": "r", "speed": "rapid"})
    return add_exercise(conn, bullet, 1), add_exercise(conn, rapid, 1)


def test_speed_filter_restricts_the_exercises(conn, two_speeds):
    bullet, rapid = two_speeds
    assert [e["move_id"] for e in available(conn, ["bullet"])] == [bullet]
    assert {next_exercise(conn, random.Random(i), ["rapid"])["move_id"] for i in range(20)} == {rapid}


def test_no_filter_means_every_speed(conn, two_speeds):
    assert len(available(conn)) == 2
    assert len(available(conn, ["bullet", "blitz", "rapid"])) == 2


def test_empty_filter_selects_nothing(conn, two_speeds):
    assert available(conn, []) == []
    assert next_exercise(conn, speeds=[]) is None


def test_available_excludes_mastered(conn, two_speeds):
    bullet, _ = two_speeds
    attempt(conn, bullet, True, True)
    assert len(available(conn)) == 1
