import math

import chess

from zugup.storage.db import evaluated_games, game_eval_moves, mark_classified, replace_mistakes

CP_CEILING = 1000
WIN_MULTIPLIER = -0.00368208
WIN_THRESHOLDS = ((0.3, "blunder"), (0.2, "mistake"), (0.1, "inaccuracy"))
MATE_MISTAKE_CP = 700
MATE_INACCURACY_CP = 999
ENDGAME_PIECES = 6
MIDDLEGAME_PIECES = 10
SPARSE_BACKRANK = 4


def clamp(cp):
    return max(-CP_CEILING, min(CP_CEILING, cp))


def winning_chances(cp):
    return 2 / (1 + math.exp(WIN_MULTIPLIER * clamp(cp))) - 1


def user_pov(cp, mate, white):
    sign = 1 if white else -1
    return (None if cp is None else sign * cp, None if mate is None else sign * mate)


def equivalent_cp(score):
    cp, mate = score
    if mate is not None:
        return CP_CEILING if mate > 0 else -CP_CEILING
    return clamp(cp)


def graded_by_remaining_advantage(advantage):
    if advantage > MATE_INACCURACY_CP:
        return "inaccuracy"
    if advantage > MATE_MISTAKE_CP:
        return "mistake"
    return "blunder"


def judge(before, after):
    b_cp, b_mate = before
    a_cp, a_mate = after
    if b_mate is None and a_mate is None:
        delta = winning_chances(b_cp) - winning_chances(a_cp)
        return next((name for limit, name in WIN_THRESHOLDS if delta >= limit), None)
    if b_mate is None and a_mate <= 0:
        return graded_by_remaining_advantage(-b_cp)
    if b_mate is not None and b_mate > 0:
        if a_mate is not None and a_mate > 0:
            return None
        return graded_by_remaining_advantage(a_cp if a_mate is None else 0)
    return None


def game_phases(boards):
    phase = "opening"
    phases = []
    for b in boards:
        pieces = chess.popcount(b.occupied & ~(b.kings | b.pawns))
        if phase != "endgame":
            if pieces <= ENDGAME_PIECES:
                phase = "endgame"
            elif phase == "opening" and (pieces <= MIDDLEGAME_PIECES or backrank_sparse(b)):
                phase = "middlegame"
        phases.append(phase)
    return phases


def backrank_sparse(board):
    white = chess.popcount(board.occupied_co[chess.WHITE] & chess.BB_RANK_1)
    black = chess.popcount(board.occupied_co[chess.BLACK] & chess.BB_RANK_8)
    return white < SPARSE_BACKRANK or black < SPARSE_BACKRANK


def classify_game(moves, boards=None, phases=None):
    user_white = moves[0]["user_color"] == "white"
    boards = boards or [chess.Board(m["fen_before"]) for m in moves]
    phases = phases or game_phases(boards)
    rows = []
    for i, m in enumerate(moves):
        if (m["ply"] % 2 == 1) != user_white:
            continue
        if m["cp_before"] is None and m["mate_before"] is None:
            continue
        before = user_pov(m["cp_before"], m["mate_before"], user_white)
        if m["cp_after"] is None and m["mate_after"] is None:
            board = boards[i].copy()
            board.push_uci(m["uci"])
            if board.is_checkmate():
                continue
            after = (0, None)
        else:
            after = user_pov(m["cp_after"], m["mate_after"], user_white)
        category = judge(before, after)
        if category:
            rows.append({
                "move_id": m["id"],
                "category": category,
                "cp_loss": max(0, equivalent_cp(before) - equivalent_cp(after)),
                "phase": phases[i],
            })
    return rows


def classify_stored_game(conn, game_id):
    rows = classify_game(game_eval_moves(conn, game_id))
    replace_mistakes(conn, game_id, rows)
    mark_classified(conn, game_id)
    return rows


def classify(conn):
    stats = {"games": 0, "inaccuracy": 0, "mistake": 0, "blunder": 0}
    for game_id in evaluated_games(conn):
        rows = classify_stored_game(conn, game_id)
        stats["games"] += 1
        for r in rows:
            stats[r["category"]] += 1
    return stats
