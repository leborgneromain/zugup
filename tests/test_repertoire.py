import chess

from zugup.profile.repertoire import position_moves
from zugup.storage.db import add_game, connect

START = chess.STARTING_FEN


def game(game_id, result, color="white", speed="blitz"):
    return {
        "source": "lichess", "game_id": game_id, "played_at": "2026-01-01T10:00:00Z",
        "white": "me", "black": "opp", "user_color": color, "result": result,
        "time_control": "180+0", "speed": speed, "opening_eco": None, "opening_name": None, "pgn": "*",
    }


def add_line(conn, gid, sans, serious_plies=()):
    board = chess.Board()
    for ply, san in enumerate(sans, 1):
        move = board.parse_san(san)
        cur = conn.execute(
            "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, ?, ?, ?, ?)",
            (gid, ply, san, move.uci(), board.fen()),
        )
        if ply in serious_plies:
            conn.execute("INSERT INTO mistakes (move_id, category, cp_loss, phase) VALUES (?, 'blunder', 300, 'opening')", (cur.lastrowid,))
        board.push(move)
    conn.commit()


def build(tmp_path):
    conn = connect(tmp_path / "r.db")
    add_line(conn, add_game(conn, game("a", "1-0")), ["e4", "e5", "Nf3"])
    add_line(conn, add_game(conn, game("b", "0-1")), ["e4", "c5"], serious_plies=(1,))
    add_line(conn, add_game(conn, game("c", "1/2-1/2", speed="rapid")), ["d4", "d5"])
    add_line(conn, add_game(conn, game("d", "1-0", color="black")), ["e4", "e5"])
    return conn


def test_start_position_counts_moves_results_and_serious_errors(tmp_path):
    data = position_moves(build(tmp_path), START, "white")
    assert data["mine"] is True and data["total"] == 3
    e4, d4 = data["moves"]
    assert (e4["san"], e4["games"], e4["win"], e4["loss"], e4["later_errors"]) == ("e4", 2, 1, 1, 1)
    assert (d4["san"], d4["draw"]) == ("d4", 1)


def test_errors_count_only_from_the_move_onwards_and_results_are_mine(tmp_path):
    conn = build(tmp_path)
    after_e4 = position_moves(conn, START, "white")["moves"][0]["fen"]
    data = position_moves(conn, after_e4, "white")
    assert data["mine"] is False
    assert {m["san"]: (m["games"], m["later_errors"]) for m in data["moves"]} == {"e5": (1, 0), "c5": (1, 0)}


def test_color_and_speed_filters(tmp_path):
    conn = build(tmp_path)
    assert position_moves(conn, START, "black")["total"] == 1
    only_rapid = position_moves(conn, START, "white", ["rapid"])
    assert [m["san"] for m in only_rapid["moves"]] == ["d4"]


def test_unknown_position_has_no_moves(tmp_path):
    fen = chess.Board("8/8/8/8/8/8/8/K6k w - - 0 1").fen()
    assert position_moves(build(tmp_path), fen, "white") == {"mine": True, "total": 0, "moves": []}
