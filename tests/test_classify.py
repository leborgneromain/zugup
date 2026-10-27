import chess
import pytest

from zugup.analysis import classify as c
from zugup.storage.db import connect, save_game


def cp(value):
    return (value, None)


def mate(value):
    return (None, value)


def build_moves(sans):
    board = chess.Board()
    moves = []
    for ply, san in enumerate(sans, start=1):
        move = board.parse_san(san)
        moves.append({"ply": ply, "san": san, "uci": move.uci(), "fen_before": board.fen(), "eval": None})
        board.push(move)
    return moves


def game(game_id="g1", color="white"):
    return {
        "source": "lichess", "game_id": game_id, "played_at": "2026-10-01T10:00:00Z",
        "white": "niamo", "black": "opp", "user_color": color, "result": "1-0", "pgn": "*",
    }


def ev(cp_before=None, cp_after=None, mate_before=None, mate_after=None):
    return {"origin": "stockfish", "cp_before": cp_before, "cp_after": cp_after,
            "mate_before": mate_before, "mate_after": mate_after}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def test_winning_chances_is_symmetric_and_saturates():
    assert c.winning_chances(0) == 0
    assert c.winning_chances(150) == pytest.approx(-c.winning_chances(-150))
    assert c.winning_chances(1000) == c.winning_chances(5000)
    assert c.winning_chances(1000) < 1


@pytest.mark.parametrize("before,after,expected", [
    (0, -50, None),
    (0, -60, "inaccuracy"),
    (0, -120, "mistake"),
    (0, -200, "blunder"),
    (0, 100, None),
    (800, 500, "inaccuracy"),
    (-800, -1000, None),
    (-300, -100, None),
])
def test_judge_centipawns(before, after, expected):
    assert c.judge(cp(before), cp(after)) == expected


@pytest.mark.parametrize("before,after,expected", [
    (cp(0), mate(-2), "blunder"),
    (cp(-800), mate(-2), "mistake"),
    (cp(-1000), mate(-2), "inaccuracy"),
    (cp(0), mate(0), "blunder"),
    (mate(3), cp(500), "blunder"),
    (mate(3), cp(800), "mistake"),
    (mate(3), cp(1000), "inaccuracy"),
    (mate(3), mate(-4), "blunder"),
    (mate(3), mate(5), None),
    (mate(-3), cp(0), None),
    (mate(-3), mate(-5), None),
    (cp(0), mate(4), None),
])
def test_judge_mate_cases(before, after, expected):
    assert c.judge(before, after) == expected


def test_user_pov_flips_for_black():
    assert c.user_pov(120, None, False) == (-120, None)
    assert c.user_pov(None, 3, False) == (None, -3)
    assert c.user_pov(120, None, True) == (120, None)


def test_equivalent_cp_caps_and_maps_mate():
    assert c.equivalent_cp(cp(5000)) == 1000
    assert c.equivalent_cp(cp(-30)) == -30
    assert c.equivalent_cp(mate(2)) == 1000
    assert c.equivalent_cp(mate(-2)) == -1000


def test_phases_are_monotonic():
    start = chess.Board()
    sparse = chess.Board("rnbqkbnr/pppppppp/8/8/8/2NBBN2/PPPPPPPP/R3K2R w KQkq - 0 1")
    endgame = chess.Board("4k3/8/8/8/8/8/4R3/4K2R w - - 0 1")
    crowded = chess.Board()
    assert c.game_phases([start, sparse, endgame, crowded]) == ["opening", "middlegame", "endgame", "endgame"]


def test_phase_middlegame_when_ten_or_fewer_pieces():
    board = chess.Board("1nbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN1 w - - 0 1")
    ten = chess.Board("rnbqk3/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB2 w - - 0 1")
    assert c.game_phases([board])[0] == "opening"
    assert c.game_phases([ten])[0] == "middlegame"


def test_classify_game_only_user_moves_and_pov(conn):
    moves = build_moves(["e4", "e5", "Nf3", "Nc6"])
    moves[0]["eval"] = ev(0, 20)
    moves[1]["eval"] = ev(20, -400)
    moves[2]["eval"] = ev(-400, -900)
    moves[3]["eval"] = ev(-900, -910)
    save_game(conn, game(color="white"), moves)
    stats = c.classify(conn)
    rows = conn.execute("SELECT m.san, k.* FROM mistakes k JOIN moves m ON m.id = k.move_id").fetchall()
    assert [(r["san"], r["category"]) for r in rows] == [("Nf3", "blunder")]
    assert rows[0]["cp_loss"] == 500
    assert rows[0]["phase"] == "opening"
    assert stats == {"games": 1, "inaccuracy": 0, "mistake": 0, "blunder": 1}


def test_classify_game_black_user(conn):
    moves = build_moves(["e4", "e5", "Nf3", "Nc6"])
    moves[0]["eval"] = ev(0, 20)
    moves[1]["eval"] = ev(20, 300)
    moves[2]["eval"] = ev(300, 310)
    moves[3]["eval"] = ev(310, 0)
    save_game(conn, game(color="black"), moves)
    c.classify(conn)
    rows = conn.execute("SELECT m.san, k.category, k.cp_loss FROM mistakes k JOIN moves m ON m.id = k.move_id").fetchall()
    assert [(r["san"], r["category"], r["cp_loss"]) for r in rows] == [("e5", "blunder", 280)]


def test_checkmating_move_is_not_a_mistake(conn):
    moves = build_moves(["f3", "e5", "g4", "Qh4#"])
    moves[1]["eval"] = ev(0, 0)
    moves[2]["eval"] = ev(0, None, mate_after=-1)
    moves[3]["eval"] = ev(None, None, mate_before=-1)
    save_game(conn, game(color="black"), moves)
    c.classify(conn)
    assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 0


def test_stalemating_a_won_position_is_a_blunder(conn):
    fen = "k7/8/1K6/8/8/8/8/2Q5 w - - 0 1"
    board = chess.Board(fen)
    board.push_uci("c1c7")
    assert board.is_stalemate()
    moves = [{"ply": 1, "san": "Qc7", "uci": "c1c7", "fen_before": fen, "eval": ev(900, None)}]
    save_game(conn, game(), moves)
    c.classify(conn)
    row = conn.execute("SELECT category, cp_loss FROM mistakes").fetchone()
    assert (row["category"], row["cp_loss"]) == ("blunder", 900)


def test_classify_is_idempotent_and_replaces_results(conn):
    moves = build_moves(["e4", "e5", "Nf3"])
    moves[0]["eval"] = ev(0, -300)
    moves[1]["eval"] = ev(-300, -300)
    moves[2]["eval"] = ev(-300, -300)
    save_game(conn, game(), moves)
    c.classify(conn)
    c.classify(conn)
    assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 1
    conn.execute("UPDATE evals SET cp_after = 10 WHERE move_id = 1")
    conn.commit()
    c.classify(conn)
    assert conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0] == 0


def test_moves_without_eval_are_ignored(conn):
    moves = build_moves(["e4", "e5", "Nf3"])
    moves[2]["eval"] = ev(0, -500)
    save_game(conn, game(), moves)
    assert c.classify(conn)["blunder"] == 1


def test_games_without_evals_are_not_visited(conn):
    save_game(conn, game(), build_moves(["e4", "e5"]))
    assert c.classify(conn)["games"] == 0
