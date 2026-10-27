import chess
import pandas as pd

from zugup.analysis.classify import classify_game, equivalent_cp, game_phases, user_pov
from zugup.puzzles.exercises import player_ratings

MIN_MOVES = 30
MIN_GAMES = 5
SERIOUS = ("mistake", "blunder")
EDGE_CP = 200
PEER_RANGE = 100
TIME_TROUBLE_SHARE = 0.1
RADAR_AXES = (
    ("opening", "Ouverture"),
    ("middlegame", "Milieu de partie"),
    ("endgame", "Finale"),
    ("winning", "Conversion"),
    ("losing", "Résilience"),
    ("time", "Gestion du temps"),
)
SPEEDS = ((180, "bullet"), (480, "blitz"), (1500, "rapid"))
DIMENSIONS = (
    ("phase", "Phase"),
    ("opening_name", "Ouverture"),
    ("user_color", "Couleur"),
)

DIMENSION_ORDER = {label: i for i, (_, label) in enumerate(DIMENSIONS)}

QUERY = """
SELECT g.id AS game_id, g.user_color, g.time_control, g.speed, g.opening_name,
       m.id AS move_id, m.ply, m.uci, m.clock_seconds, m.fen_before, mk.category, mk.cp_loss,
       e.cp_before, e.mate_before, e.cp_after, e.mate_after, g.pgn
FROM moves m
JOIN games g ON g.id = m.game_id
LEFT JOIN evals e ON e.move_id = m.id
LEFT JOIN mistakes mk ON mk.move_id = m.id
WHERE m.game_id IN (SELECT DISTINCT m2.game_id FROM evals e2 JOIN moves m2 ON m2.id = e2.move_id)
ORDER BY m.game_id, m.ply
"""


def speed(time_control):
    try:
        base, _, inc = str(time_control).partition("+")
        estimated = int(base) + 40 * int(inc or 0)
    except ValueError:
        return None
    return next((name for limit, name in SPEEDS if estimated < limit), None)


def base_seconds(time_control):
    try:
        return int(str(time_control).partition("+")[0])
    except ValueError:
        return None


def load_user_moves(conn):
    return pd.read_sql_query(QUERY, conn)


def add_phase(df):
    df = df.copy().reset_index(drop=True)
    df["mine"] = (df["ply"] % 2 == 1) == (df["user_color"] == "white")
    records = df.astype(object).where(df.notna(), None).to_dict("records")
    phases = [None] * len(df)
    opponent = {}
    user_elo = [None] * len(df)
    opp_elo = [None] * len(df)
    for idx in df.groupby("game_id").indices.values():
        boards = [chess.Board(records[i]["fen_before"]) for i in idx]
        game_ph = game_phases(boards)
        flipped = [opponent_view(records[i]) for i in idx]
        opponent.update({row["move_id"]: row for row in classify_game(flipped, boards, game_ph)})
        white_elo, black_elo = player_ratings(records[idx[0]]["pgn"])
        mine_white = records[idx[0]]["user_color"] == "white"
        for i, ph in zip(idx, game_ph):
            phases[i] = ph
            user_elo[i] = white_elo if mine_white else black_elo
            opp_elo[i] = black_elo if mine_white else white_elo
    df["phase"], df["user_elo"], df["opp_elo"] = phases, user_elo, opp_elo
    theirs = df["move_id"].map(opponent)
    df["category"] = df["category"].where(df["mine"], theirs.map(lambda r: r["category"] if isinstance(r, dict) else None))
    df["cp_loss"] = df["cp_loss"].where(df["mine"], theirs.map(lambda r: r["cp_loss"] if isinstance(r, dict) else None))
    df["speed"] = df["speed"].fillna(df["time_control"].map(speed))
    base = df["time_control"].map(base_seconds).astype(float)
    df["low_time"] = (df["clock_seconds"] < TIME_TROUBLE_SHARE * base).where(df["clock_seconds"].notna() & base.notna())
    df["advantage"] = [
        advantage(cp, mate, ply % 2 == 1) for cp, mate, ply in zip(df["cp_before"], df["mate_before"], df["ply"])
    ]
    return df


def opponent_view(record):
    return {**record, "id": record["move_id"], "user_color": "black" if record["user_color"] == "white" else "white"}


def advantage(cp, mate, white):
    cp, mate = (None if pd.isna(v) else int(v) for v in (cp, mate))
    if cp is None and mate is None:
        return None
    return equivalent_cp(user_pov(cp, mate, white))


def bad_column(key):
    return "low_time_flag" if key == "time" else "serious"


def radar_axes(df, min_moves=MIN_MOVES):
    df = df.assign(serious=df["category"].isin(SERIOUS), low_time_flag=df["low_time"].fillna(False).astype(bool))
    advantage_cp = df["advantage"].astype(float)
    subsets = {
        "opening": df[df["phase"] == "opening"],
        "middlegame": df[df["phase"] == "middlegame"],
        "endgame": df[df["phase"] == "endgame"],
        "winning": df[advantage_cp >= EDGE_CP],
        "losing": df[advantage_cp <= -EDGE_CP],
        "time": df[df["low_time"].notna()],
    }
    axes = []
    for key, label in RADAR_AXES:
        part = subsets[key]
        enough = len(part) >= min_moves
        axes.append({
            "key": key, "label": label, "moves": len(part),
            "score": float(100 * (1 - part[bad_column(key)].mean())) if enough else None,
        })
    return axes


def group_stats(df, min_moves=MIN_MOVES, min_games=MIN_GAMES):
    if df.empty:
        return []
    df = df.assign(serious=df["category"].isin(SERIOUS))
    overall = df["serious"].mean()
    rows = []
    for column, label in DIMENSIONS:
        sub = df.dropna(subset=[column])
        for value, group in sub.groupby(column):
            n = len(group)
            if n < min_moves or group["game_id"].nunique() < min_games:
                continue
            rate = group["serious"].mean()
            losses = group.loc[group["serious"], "cp_loss"]
            rows.append({
                "dimension": label,
                "column": column,
                "value": value,
                "moves": n,
                "games": group["game_id"].nunique(),
                "serious": int(group["serious"].sum()),
                "rate": float(rate),
                "overall": float(overall),
                "avg_cp_loss": float(losses.mean()) if len(losses) else None,
                "excess": float((rate - overall) * n),
            })
    return rows


def rank_weaknesses(df, top=5, min_moves=MIN_MOVES, min_games=MIN_GAMES):
    rows = [r for r in group_stats(df, min_moves, min_games) if r["excess"] > 0]
    rows.sort(key=lambda r: r["excess"], reverse=True)
    return rows[:top]


def render_report(weaknesses, total_moves, total_games):
    lines = [f"Échantillon : {total_games} parties, {total_moves} coups analysés."]
    if not weaknesses:
        lines.append(f"Aucune faiblesse significative (groupes d'au moins {MIN_MOVES} coups et {MIN_GAMES} parties).")
        return "\n".join(lines)
    lines.append("Faiblesses : erreurs + gaffes par coup, comparées à ta moyenne.")
    for i, w in enumerate(weaknesses, 1):
        lines.append(
            f"{i}. {w['dimension']} = {w['value']} : {w['rate']:.1%} d'erreurs graves "
            f"(moyenne {w['overall']:.1%}), {w['serious']} sur {w['moves']} coups, "
            f"{w['games']} parties, perte moyenne {w['avg_cp_loss']:.0f} cp"
        )
    return "\n".join(lines)


def peer_moves(df):
    opponents = df[~df["mine"]]
    gap = (pd.to_numeric(opponents["opp_elo"]) - pd.to_numeric(opponents["user_elo"])).abs()
    return opponents[gap <= PEER_RANGE]


def report_data(conn, top=5):
    all_moves = add_phase(load_user_moves(conn))
    df = all_moves[all_moves["mine"]]
    peers = peer_moves(all_moves)
    sections = []
    for _, name in SPEEDS:
        part = df[df["speed"] == name]
        if part.empty:
            continue
        peer_part = peers[peers["speed"] == name]
        radar = radar_axes(part)
        for axis, peer in zip(radar, radar_axes(peer_part)):
            axis["peer_score"] = peer["score"]
        sections.append({
            "speed": name,
            "games": int(part["game_id"].nunique()),
            "moves": len(part),
            "serious_rate": float(part["category"].isin(SERIOUS).mean()),
            "radar": radar,
            "peer_games": int(peer_part["game_id"].nunique()),
            "weaknesses": rank_weaknesses(part, top),
            "groups": sorted(group_stats(part), key=lambda r: (DIMENSION_ORDER[r["dimension"]], -r["rate"])),
        })
    return sections


def report(conn, top=5):
    sections = [
        f"== {s['speed'].capitalize()} ==\n" + render_report(s["weaknesses"], s["moves"], s["games"])
        for s in report_data(conn, top)
    ]
    return "\n\n".join(sections) or render_report([], 0, 0)


SIGNATURE = """
SELECT (SELECT COUNT(*) FROM games), (SELECT COUNT(*) FROM evals), (SELECT COALESCE(MAX(move_id), 0) FROM evals),
       (SELECT COUNT(*) FROM mistakes), (SELECT COALESCE(SUM(cp_loss), 0) FROM mistakes)
"""
_cache = {}


def cached_report_data(conn, top=5):
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    key = (db_file, top, tuple(conn.execute(SIGNATURE).fetchone()))
    if key not in _cache:
        for old in [k for k in _cache if k[:2] == key[:2]]:
            del _cache[old]
        _cache[key] = report_data(conn, top)
    return _cache[key]
