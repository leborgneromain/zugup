import queue
from concurrent.futures import ThreadPoolExecutor, as_completed

import chess

from zugup.analysis.engine import Analyzer
from zugup.storage.db import game_moves, pending_games, save_evals


def analyze_moves(moves, evaluate, depth):
    boards = [chess.Board(m["fen_before"]) for m in moves]
    final = boards[-1].copy()
    final.push_uci(moves[-1]["uci"])
    boards.append(final)
    evals = [None if b.is_game_over() else evaluate(b) for b in boards]
    rows = []
    for i, m in enumerate(moves):
        before, after = evals[i], evals[i + 1]
        rows.append({
            "move_id": m["id"],
            "origin": "stockfish",
            "cp_before": before["cp"],
            "mate_before": before["mate"],
            "cp_after": after["cp"] if after else None,
            "mate_after": after["mate"] if after else None,
            "best_uci": before["best_uci"],
            "depth": depth,
        })
    return rows


def run(conn, path, depth, threads=1, hash_mb=128, workers=1, max_games=None,
        dry_run=False, analyzer_factory=Analyzer, on_game=None):
    pending = pending_games(conn, max_games)
    stats = {"pending": len(pending), "analyzed": 0, "positions": 0, "cache_hits": 0}
    if dry_run or not pending:
        return stats

    jobs = {gid: game_moves(conn, gid) for gid in pending}
    cache = {}
    pool = queue.Queue()
    analyzers = [analyzer_factory(path, depth, threads, hash_mb) for _ in range(min(workers, len(pending)))]
    for a in analyzers:
        pool.put(a)

    def task(moves):
        analyzer = pool.get()
        counts = {"positions": 0, "hits": 0}

        def evaluate(board):
            key = board.epd()
            counts["positions"] += 1
            if key in cache:
                counts["hits"] += 1
            else:
                cache[key] = analyzer.evaluate(board)
            return cache[key]

        try:
            return analyze_moves(moves, evaluate, depth), counts
        finally:
            pool.put(analyzer)

    executor = ThreadPoolExecutor(len(analyzers))
    try:
        futures = {executor.submit(task, moves): gid for gid, moves in jobs.items() if moves}
        for future in as_completed(futures):
            rows, counts = future.result()
            save_evals(conn, rows)
            stats["analyzed"] += 1
            stats["positions"] += counts["positions"]
            stats["cache_hits"] += counts["hits"]
            if on_game:
                on_game(futures[future], stats)
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        executor.shutdown(wait=True)
        for a in analyzers:
            a.close()
    return stats
