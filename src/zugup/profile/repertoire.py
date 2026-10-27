import re

import chess

QUERY = """
SELECT m.game_id, m.san, m.uci, g.result, g.user_color,
       EXISTS (
           SELECT 1 FROM moves m2 JOIN mistakes k ON k.move_id = m2.id
           WHERE m2.game_id = m.game_id AND m2.ply >= m.ply
             AND k.phase = 'opening' AND k.category IN ('mistake', 'blunder')
       ) AS later_error
FROM moves m
JOIN games g ON g.id = m.game_id
WHERE g.user_color = ?
  AND substr(m.fen_before, 1, length(?)) = ?
"""
RESULTS = {"1-0": "white", "0-1": "black"}


def position_key(fen):
    return " ".join(fen.split()[:4]) + " "


def outcome(result, user_color):
    winner = RESULTS.get(result)
    if winner is None:
        return "draw"
    return "win" if winner == user_color else "loss"


def position_moves(conn, fen, color, speeds=None):
    key = position_key(fen)
    sql, params = QUERY, [color, key, key]
    if speeds:
        sql += f" AND g.speed IN ({','.join('?' * len(speeds))})"
        params += list(speeds)
    board = chess.Board(fen)
    mine = (board.turn == chess.WHITE) == (color == "white")
    moves = {}
    for row in conn.execute(sql, params):
        entry = moves.setdefault(row["uci"], {
            "san": row["san"], "uci": row["uci"], "games": set(),
            "win": 0, "draw": 0, "loss": 0, "later_errors": 0,
        })
        if row["game_id"] in entry["games"]:
            continue
        entry["games"].add(row["game_id"])
        entry[outcome(row["result"], row["user_color"])] += 1
        entry["later_errors"] += row["later_error"]
    rows = []
    for entry in moves.values():
        after = board.copy()
        after.push_uci(entry["uci"])
        rows.append({
            "san": entry["san"], "uci": entry["uci"], "fen": after.fen(), "mine": mine,
            "games": len(entry["games"]), "win": entry["win"], "draw": entry["draw"], "loss": entry["loss"],
            "later_errors": entry["later_errors"],
        })
    rows.sort(key=lambda r: (-r["games"], r["san"]))
    return {"mine": mine, "total": len(set().union(*(e["games"] for e in moves.values()))), "moves": rows}


BRANCH_QUERY = """
SELECT m.game_id, m.ply, m.san, m.uci, m.fen_before, g.user_color,
       (mk.phase = 'opening' AND mk.category IN ('mistake', 'blunder')) AS opening_error
FROM moves m
JOIN games g ON g.id = m.game_id
LEFT JOIN mistakes mk ON mk.move_id = m.id
WHERE g.speed = ?
ORDER BY m.game_id, m.ply
"""


def line_text(sans):
    parts = []
    for i, san in enumerate(sans):
        parts.append(f"{i // 2 + 1}. {san}" if i % 2 == 0 else san)
    return " ".join(parts)


def game_moves(conn, speed):
    games = {}
    for row in conn.execute(BRANCH_QUERY, (speed,)):
        games.setdefault(row["game_id"], []).append(row)
    return games.values()


def branch_stats(conn, speed, max_ply):
    stats = {}
    for moves in game_moves(conn, speed):
        later = False
        flags = [False] * len(moves)
        for i in range(len(moves) - 1, -1, -1):
            later = later or bool(moves[i]["opening_error"])
            flags[i] = later
        sans = [m["san"] for m in moves]
        for i, m in enumerate(moves):
            if m["ply"] > max_ply:
                break
            node = stats.setdefault((m["user_color"], position_key(m["fen_before"])), {})
            entry = node.setdefault(m["uci"], {"games": 0, "errors": 0, "line": sans[: i + 1], "color": m["user_color"]})
            entry["games"] += 1
            entry["errors"] += flags[i]
    return stats


def worst_branch(conn, speed, min_games=8, min_gap=0.10, max_ply=20):
    best = None
    for node in branch_stats(conn, speed, max_ply).values():
        games = sum(e["games"] for e in node.values())
        baseline = sum(e["errors"] for e in node.values()) / games
        for entry in node.values():
            if entry["games"] < min_games:
                continue
            rate = entry["errors"] / entry["games"]
            if rate - baseline < min_gap:
                continue
            excess = (rate - baseline) * entry["games"]
            if best is None or excess > best["excess"]:
                best = {
                    "line": line_text(entry["line"]), "key": re.sub(r"[^a-z0-9 ]", "", " ".join(entry["line"]).lower()),
                    "color": entry["color"], "games": entry["games"], "errors": entry["errors"],
                    "rate": rate, "baseline": baseline, "excess": excess,
                }
    return best
