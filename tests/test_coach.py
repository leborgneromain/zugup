from datetime import datetime, timezone

from tests.test_repertoire import add_line, game
from zugup.coach.advice import focus_axis, generate_advice, strongest_axis
from zugup.coach.plan import build_plan, week_start
from zugup.profile.repertoire import worst_branch
from zugup.storage.db import add_game, connect, set_check


def axis(key, score, peer):
    return {"key": key, "label": key.capitalize(), "score": score, "peer_score": peer, "moves": 50}


def test_week_starts_on_monday_utc():
    assert week_start(datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)) == "2026-10-26"
    assert week_start(datetime(2026, 11, 1, 23, 59, tzinfo=timezone.utc)) == "2026-10-26"
    assert week_start(datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)) == "2026-11-02"


def test_focus_axis_is_the_biggest_gap_against_peers():
    axes = [axis("opening", 90, 90), axis("endgame", 80, 90), axis("time", 70, 72)]
    assert focus_axis(axes)["key"] == "endgame"
    assert strongest_axis(axes) is None


def test_focus_axis_falls_back_to_the_lowest_score_without_peers():
    axes = [axis("opening", 90, None), axis("endgame", 80, None)]
    assert focus_axis(axes)["key"] == "endgame"
    assert focus_axis([axis("opening", None, None)]) is None


def test_advice_quotes_the_numbers_it_is_given():
    text = generate_advice({
        "speed": "blitz", "games": 40, "serious_rate": 0.125,
        "axes": [axis("endgame", 80, 90), axis("opening", 95, 90)],
        "branch": {"line": "1. e4 e5", "color": "white", "games": 10, "errors": 8, "rate": 0.8, "baseline": 0.5},
    })
    assert "40 parties" in text and "12,5 %" in text
    assert "Axe à travailler : Finale (80,0 %, contre 90,0 %" in text
    assert "Point fort : Ouverture" in text
    assert "1. e4 e5" in text and "8 parties sur 10" in text


def build_branch_db(tmp_path):
    conn = connect(tmp_path / "c.db")
    for i in range(8):
        add_line(conn, add_game(conn, game(f"x{i}", "1-0")), ["e4", "e5"], serious_plies=(2,))
    for i in range(8):
        add_line(conn, add_game(conn, game(f"y{i}", "1-0")), ["e4", "c5"])
    return conn


def test_worst_branch_needs_enough_games_and_a_clear_gap(tmp_path):
    conn = build_branch_db(tmp_path)
    branch = worst_branch(conn, "blitz")
    assert (branch["line"], branch["key"], branch["games"], branch["errors"]) == ("1. e4 e5", "e4 e5", 8, 8)
    assert worst_branch(conn, "blitz", min_games=9) is None
    assert worst_branch(conn, "rapid") is None


def test_plan_without_analyzed_games_is_empty(tmp_path):
    conn = connect(tmp_path / "e.db")
    plan = build_plan(conn, "blitz", datetime(2026, 10, 28, tzinfo=timezone.utc))
    assert plan["tasks"] == [] and plan["advice"] == ""


def test_manual_task_progress_comes_from_checks(tmp_path):
    conn = build_branch_db(tmp_path)
    conn.execute("INSERT INTO evals (move_id, origin, cp_before, cp_after, depth) SELECT id, 'stockfish', 0, 0, 10 FROM moves")
    conn.commit()
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    key = next(t["key"] for t in build_plan(conn, "blitz", now)["tasks"] if t["kind"] == "manual")
    set_check(conn, "2026-10-26", "blitz", key, True)
    tasks = {t["key"]: t for t in build_plan(conn, "blitz", now)["tasks"]}
    assert tasks[key]["done"] is True
    next_week = datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert {t["key"]: t for t in build_plan(conn, "blitz", next_week)["tasks"]}[key]["done"] is False
