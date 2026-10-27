from zugup.storage.db import game_exists, save_game


def clean(value):
    return None if value in (None, "", "?") else value


def split_score(pov):
    if pov is None:
        return None, None
    score = pov.white()
    return score.score(), score.mate()


def extract_moves(game, eval_origin=None):
    moves = []
    board = game.board()
    prev_eval = None
    for ply, node in enumerate(game.mainline(), start=1):
        fen_before = board.fen()
        san = board.san(node.move)
        board.push(node.move)
        current = node.eval()
        move = {
            "ply": ply,
            "san": san,
            "uci": node.move.uci(),
            "fen_before": fen_before,
            "clock_seconds": node.clock(),
            "eval": None,
        }
        if eval_origin and current is not None:
            cp_before, mate_before = split_score(prev_eval)
            cp_after, mate_after = split_score(current)
            move["eval"] = {
                "origin": eval_origin,
                "cp_before": cp_before,
                "mate_before": mate_before,
                "cp_after": cp_after,
                "mate_after": mate_after,
            }
        prev_eval = current
        moves.append(move)
    return moves


def store_parsed(conn, source, parsed, stats, dry_run=False):
    meta, moves = parsed
    stats["fetched"] += 1
    if game_exists(conn, source, meta["game_id"]):
        stats["skipped"] += 1
    elif dry_run:
        stats["new"] += 1
    elif save_game(conn, meta, moves) is not None:
        stats["new"] += 1
