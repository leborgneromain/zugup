import chess
import chess.engine

from zugup.analysis.classify import judge, user_pov
from zugup.analysis.engine import Analyzer

NO_ENGINE_MESSAGE = "checker.no_engine"


def open_analyzer(path, depth, threads=1, hash_mb=128, analyzer_factory=Analyzer):
    try:
        return analyzer_factory(path, depth, threads, hash_mb)
    except (OSError, chess.engine.EngineError):
        return None


def result(correct, verdict, message=None):
    return {"correct": correct, "verdict": verdict, "message": message}


def parse_legal_move(board, uci):
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise ValueError(f"Illegal move {uci} in position {board.fen()}")
    return move


def is_equivalent(exercise, board, move, evaluate):
    white = exercise["user_color"] == "white"
    before = user_pov(exercise["cp_before"], exercise["mate_before"], white)
    board = board.copy()
    board.push(move)
    if board.is_checkmate():
        return True
    if board.is_game_over():
        after = (0, None)
    else:
        score = evaluate(board)
        after = user_pov(score["cp"], score["mate"], white)
    return judge(before, after) is None


def check_answer(exercise, played_uci, evaluate=None):
    board = chess.Board(exercise["fen_before"])
    move = parse_legal_move(board, played_uci)
    if move.uci() == exercise["best_uci"]:
        return result(True, "reference")
    if evaluate is None:
        return result(False, "incorrect", NO_ENGINE_MESSAGE)
    if exercise["cp_before"] is None and exercise["mate_before"] is None:
        return result(False, "incorrect")
    try:
        equivalent = is_equivalent(exercise, board, move, evaluate)
    except chess.engine.EngineError:
        return result(False, "incorrect", NO_ENGINE_MESSAGE)
    return result(True, "equivalent") if equivalent else result(False, "incorrect")
