import random
import re

MASTERY_STREAK = 2

QUERY = """
SELECT m.id AS move_id, m.fen_before, e.best_uci, e.cp_before, e.mate_before,
       mk.category, mk.phase,
       m.ply, g.id AS game_id, g.user_color,
       g.source, g.speed, g.time_control, g.played_at, g.white, g.black, g.pgn
FROM mistakes mk
JOIN moves m ON m.id = mk.move_id
JOIN evals e ON e.move_id = m.id
JOIN games g ON g.id = m.game_id
WHERE mk.category IN ('mistake', 'blunder') AND e.best_uci IS NOT NULL
"""


ELO_HEADER = re.compile(r'^\[(White|Black)Elo "(\d+)"\]', re.MULTILINE)


def player_ratings(pgn):
    found = {color.lower(): int(elo) for color, elo in ELO_HEADER.findall(pgn)}
    return found.get("white"), found.get("black")


def is_mastered(results):
    return len(results) >= MASTERY_STREAK and all(results[-MASTERY_STREAK:])


def priority(results):
    if not results:
        return 0
    if not results[-1]:
        return 1
    return 2


def attempt_results(conn):
    results = {}
    for row in conn.execute("SELECT move_id, correct FROM attempts ORDER BY id"):
        results.setdefault(row["move_id"], []).append(bool(row["correct"]))
    return results


def list_exercises(conn, speeds=None):
    results = attempt_results(conn)
    exercises = []
    for row in conn.execute(QUERY + " ORDER BY m.id"):
        if speeds is not None and row["speed"] not in speeds:
            continue
        exercise = dict(row)
        exercise["results"] = results.get(row["move_id"], [])
        exercises.append(exercise)
    return exercises


def get_exercise(conn, move_id):
    row = conn.execute(QUERY + " AND m.id = ?", (move_id,)).fetchone()
    return dict(row) if row else None


def history(conn, exercise):
    rows = conn.execute(
        "SELECT san, fen_before FROM moves WHERE game_id = ? AND ply < ? ORDER BY ply",
        (exercise["game_id"], exercise["ply"]),
    ).fetchall()
    return {
        "sans": [r["san"] for r in rows],
        "positions": [r["fen_before"] for r in rows] + [exercise["fen_before"]],
    }


def available(conn, speeds=None):
    return [e for e in list_exercises(conn, speeds) if not is_mastered(e["results"])]


def next_exercise(conn, rng=random, speeds=None):
    candidates = available(conn, speeds)
    if not candidates:
        return None
    best = min(priority(e["results"]) for e in candidates)
    return rng.choice([e for e in candidates if priority(e["results"]) == best])
