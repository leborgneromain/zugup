import chess.engine
import pytest

from zugup.puzzles.checker import NO_ENGINE_MESSAGE, check_answer, open_analyzer

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def exercise(**overrides):
    base = {
        "fen_before": START, "best_uci": "e2e4", "cp_before": 30, "mate_before": None,
        "user_color": "white",
    }
    return {**base, **overrides}


def engine_returning(cp=None, mate=None, calls=None):
    def evaluate(board):
        if calls is not None:
            calls.append(board.fen())
        return {"cp": cp, "mate": mate, "best_uci": None}
    return evaluate


def test_reference_move_is_correct_without_calling_the_engine():
    calls = []
    outcome = check_answer(exercise(), "e2e4", engine_returning(0, calls=calls))
    assert outcome == {"correct": True, "verdict": "reference", "message": None}
    assert calls == []


def test_equivalent_move_is_accepted():
    outcome = check_answer(exercise(), "d2d4", engine_returning(cp=28))
    assert outcome["correct"] is True
    assert outcome["verdict"] == "equivalent"


def test_worse_move_is_rejected():
    outcome = check_answer(exercise(), "f2f3", engine_returning(cp=-150))
    assert outcome == {"correct": False, "verdict": "incorrect", "message": None}


def test_engine_scores_are_read_from_the_user_side_for_black():
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    black = exercise(fen_before=fen, best_uci="e7e5", cp_before=-30, user_color="black")
    assert check_answer(black, "c7c5", engine_returning(cp=-28))["verdict"] == "equivalent"
    assert check_answer(black, "f7f6", engine_returning(cp=150))["verdict"] == "incorrect"


def test_losing_a_forced_mate_is_rejected():
    outcome = check_answer(exercise(cp_before=None, mate_before=3), "a2a3", engine_returning(cp=0))
    assert outcome["correct"] is False


def test_without_engine_only_the_reference_move_counts():
    assert check_answer(exercise(), "e2e4")["correct"] is True
    outcome = check_answer(exercise(), "d2d4")
    assert outcome == {"correct": False, "verdict": "incorrect", "message": NO_ENGINE_MESSAGE}


def test_engine_failure_falls_back_to_reference_only():
    def broken(board):
        raise chess.engine.EngineTerminatedError("gone")

    outcome = check_answer(exercise(), "d2d4", broken)
    assert outcome == {"correct": False, "verdict": "incorrect", "message": NO_ENGINE_MESSAGE}


def test_illegal_or_malformed_move_is_a_value_error():
    with pytest.raises(ValueError):
        check_answer(exercise(), "e2e5")
    with pytest.raises(ValueError):
        check_answer(exercise(), "zzzz")


def test_open_analyzer_returns_none_when_engine_cannot_start():
    def factory(*args):
        raise FileNotFoundError("no stockfish")

    assert open_analyzer("/nope", 10, analyzer_factory=factory) is None


def test_open_analyzer_returns_the_analyzer():
    sentinel = object()
    assert open_analyzer("/ok", 10, analyzer_factory=lambda *a: sentinel) is sentinel
