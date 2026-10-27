import shutil

import chess
import pytest

from zugup.analysis import runner
from zugup.analysis.engine import Analyzer
from zugup.storage.db import add_game, connect, game_moves, pending_games, save_game

STOCKFISH = shutil.which("stockfish") or "/opt/homebrew/bin/stockfish"


def build_moves(sans):
    board = chess.Board()
    moves = []
    for ply, san in enumerate(sans, start=1):
        move = board.parse_san(san)
        moves.append({"ply": ply, "san": san, "uci": move.uci(), "fen_before": board.fen(), "eval": None})
        board.push(move)
    return moves


def game(game_id, played_at="2026-10-01T10:00:00Z"):
    return {
        "source": "lichess", "game_id": game_id, "played_at": played_at,
        "white": "niamo", "black": "opp", "user_color": "white", "result": "1-0",
        "pgn": "*",
    }


class FakeAnalyzer:
    instances = []

    def __init__(self, path, depth, threads, hash_mb):
        self.calls = 0
        self.closed = False
        self.fail_after = None
        FakeAnalyzer.instances.append(self)

    def evaluate(self, board):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("engine crashed")
        sign = 1 if board.turn == chess.WHITE else -1
        return {
            "cp": sign * 10 * board.fullmove_number,
            "mate": None,
            "best_uci": next(iter(board.legal_moves)).uci(),
        }

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_instances():
    FakeAnalyzer.instances = []


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def run(conn, **kw):
    return runner.run(conn, "sf", 10, analyzer_factory=FakeAnalyzer, **kw)


def evals(conn):
    return conn.execute(
        "SELECT m.ply, e.* FROM evals e JOIN moves m ON m.id = e.move_id ORDER BY m.game_id, m.ply"
    ).fetchall()


def test_eval_after_equals_next_eval_before(conn):
    save_game(conn, game("g1"), build_moves(["e4", "e5", "Nf3", "Nc6"]))
    run(conn)
    rows = evals(conn)
    assert len(rows) == 4
    for cur, nxt in zip(rows, rows[1:]):
        assert cur["cp_after"] == nxt["cp_before"]
    assert all(r["origin"] == "stockfish" and r["depth"] == 10 for r in rows)
    assert all(r["best_uci"] for r in rows)


def test_terminal_position_has_no_eval_after(conn):
    save_game(conn, game("g1"), build_moves(["f3", "e5", "g4", "Qh4#"]))
    run(conn)
    last = evals(conn)[-1]
    assert last["cp_after"] is None and last["mate_after"] is None
    assert last["cp_before"] is not None


def test_second_run_has_nothing_to_do(conn):
    save_game(conn, game("g1"), build_moves(["e4", "e5"]))
    run(conn)
    FakeAnalyzer.instances = []
    stats = run(conn)
    assert stats["pending"] == 0 and stats["analyzed"] == 0
    assert FakeAnalyzer.instances == []


def test_position_cache_shared_between_games(conn):
    save_game(conn, game("g1", "2026-10-01T10:00:00Z"), build_moves(["e4", "e5", "Nf3"]))
    save_game(conn, game("g2", "2026-10-02T10:00:00Z"), build_moves(["e4", "e5", "Nc3"]))
    stats = run(conn, workers=1)
    assert stats["positions"] == 8
    assert stats["cache_hits"] == 3
    assert sum(a.calls for a in FakeAnalyzer.instances) == 5


def test_fully_evaluated_games_are_skipped(conn):
    moves = build_moves(["e4", "e5"])
    for m in moves:
        m["eval"] = {"origin": "lichess", "cp_after": 20}
    save_game(conn, game("g1"), moves)
    assert pending_games(conn) == []


def test_partially_evaluated_game_is_redone(conn):
    moves = build_moves(["e4", "e5"])
    moves[0]["eval"] = {"origin": "lichess", "cp_after": 20}
    gid = save_game(conn, game("g1"), moves)
    assert pending_games(conn) == [gid]
    run(conn)
    rows = evals(conn)
    assert len(rows) == 2
    assert all(r["origin"] == "stockfish" for r in rows)


def test_max_games_takes_most_recent(conn):
    save_game(conn, game("old", "2026-01-01T10:00:00Z"), build_moves(["e4", "e5"]))
    new = save_game(conn, game("new", "2026-10-01T10:00:00Z"), build_moves(["d4", "d5"]))
    assert pending_games(conn, 1) == [new]
    assert run(conn, max_games=1)["analyzed"] == 1


def test_game_without_moves_is_not_pending(conn):
    add_game(conn, game("empty"))
    assert pending_games(conn) == []


def test_dry_run_starts_no_engine(conn):
    save_game(conn, game("g1"), build_moves(["e4", "e5"]))
    stats = run(conn, dry_run=True)
    assert stats["pending"] == 1 and stats["analyzed"] == 0
    assert FakeAnalyzer.instances == []
    assert evals(conn) == []


def test_engine_failure_keeps_finished_games_and_closes_engines(conn):
    save_game(conn, game("g1", "2026-10-02T10:00:00Z"), build_moves(["e4", "e5", "Nf3", "Nc6"]))
    save_game(conn, game("g2", "2026-10-01T10:00:00Z"), build_moves(["d4", "d5", "c4", "e6"]))

    class Flaky(FakeAnalyzer):
        def __init__(self, *a):
            super().__init__(*a)
            self.fail_after = 6

    with pytest.raises(RuntimeError, match="crashed"):
        runner.run(conn, "sf", 10, analyzer_factory=Flaky, workers=1)
    assert all(a.closed for a in FakeAnalyzer.instances)
    done = {r["move_id"] for r in evals(conn)}
    games_done = {game_moves(conn, g)[0]["id"] in done for g in (1, 2)}
    assert games_done == {True, False}
    assert len(pending_games(conn)) == 1


def test_parallel_workers_analyze_all_games(conn):
    for i in range(6):
        save_game(conn, game(f"g{i}", f"2026-10-0{i + 1}T10:00:00Z"), build_moves(["e4", "e5", "Nf3"]))
    stats = run(conn, workers=3)
    assert stats["analyzed"] == 6
    assert len(evals(conn)) == 18
    assert pending_games(conn) == []
    assert len(FakeAnalyzer.instances) == 3
    assert all(a.closed for a in FakeAnalyzer.instances)


@pytest.mark.skipif(not shutil.which("stockfish") and not __import__("os").path.exists(STOCKFISH),
                    reason="Stockfish not installed")
def test_real_stockfish_finds_fools_mate(conn):
    save_game(conn, game("g1"), build_moves(["f3", "e5", "g4", "Qh4#"]))
    runner.run(conn, STOCKFISH, 8)
    rows = evals(conn)
    assert rows[2]["mate_after"] == -1
    assert rows[3]["mate_before"] == -1
    assert rows[3]["best_uci"] == "d8h4"
    assert rows[3]["cp_after"] is None
    assert rows[0]["mate_before"] is None


@pytest.mark.skipif(not __import__("os").path.exists(STOCKFISH), reason="Stockfish not installed")
def test_analyzer_scores_are_from_white_point_of_view():
    a = Analyzer(STOCKFISH, 8)
    try:
        black_up = a.evaluate(chess.Board("3qk3/pppppppp/8/8/8/8/PPPPPPPP/4K3 w - - 0 1"))
        white_up = a.evaluate(chess.Board("4k3/pppppppp/8/8/8/8/PPPPPPPP/3QK3 b - - 0 1"))
    finally:
        a.close()
    assert black_up["cp"] < -500
    assert white_up["cp"] > 500
