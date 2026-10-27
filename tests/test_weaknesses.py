import pandas as pd

from zugup.profile.weaknesses import rank_weaknesses, render_report


def frame(rows):
    return pd.DataFrame(rows, columns=["game_id", "phase", "opening_name", "time_control", "user_color", "category", "cp_loss"])


def test_ranks_group_above_average_first():
    rows = [(i % 6, "endgame", "A", "blitz", "white", "blunder" if i % 2 else None, 300) for i in range(40)]
    rows += [(10 + i % 6, "middlegame", "A", "blitz", "white", "blunder" if i % 10 == 0 else None, 300) for i in range(40)]
    result = rank_weaknesses(frame(rows))
    assert result[0]["dimension"] == "Phase"
    assert result[0]["value"] == "endgame"


def test_small_groups_are_ignored():
    rows = [(1, "endgame", "A", "blitz", "white", "blunder", 300) for _ in range(5)]
    assert rank_weaknesses(frame(rows)) == []


def test_few_games_are_ignored():
    rows = [(i % 2, "endgame", "A", "blitz", "white", "blunder", 300) for i in range(40)]
    assert rank_weaknesses(frame(rows)) == []


def test_empty_frame():
    assert rank_weaknesses(frame([])) == []


def test_render_without_weakness():
    assert "Aucune faiblesse" in render_report([], 10, 1)


def test_speed_buckets():
    from zugup.profile.weaknesses import speed

    assert [speed(t) for t in ("60", "60+0", "60+1", "180", "180+2", "300", "600", "1/86400", None)] == [
        "bullet", "bullet", "bullet", "blitz", "blitz", "blitz", "rapid", None, None]


def test_radar_axes_scores_and_missing_axes():
    import pandas as pd
    from zugup.profile.weaknesses import radar_axes

    rows = [
        {"phase": "opening", "category": "blunder" if i < 10 else None, "advantage": 300 if i < 20 else -300, "low_time": True if i < 10 else False}
        for i in range(40)
    ]
    axes = {a["key"]: a for a in radar_axes(pd.DataFrame(rows), min_moves=20)}
    assert axes["opening"]["score"] == 75.0
    assert axes["winning"]["score"] == 50.0 and axes["losing"]["score"] == 100.0
    assert axes["time"]["score"] == 75.0
    assert axes["middlegame"]["score"] is None and axes["middlegame"]["moves"] == 0


def test_peer_moves_keep_opponents_within_100_elo():
    from zugup.profile.weaknesses import peer_moves

    df = pd.DataFrame([
        {"mine": False, "user_elo": 1500, "opp_elo": 1590},
        {"mine": False, "user_elo": 1500, "opp_elo": 1650},
        {"mine": True, "user_elo": 1500, "opp_elo": 1500},
        {"mine": False, "user_elo": None, "opp_elo": 1500},
    ])
    assert list(peer_moves(df).index) == [0]


def test_cached_report_is_reused_until_the_data_changes(tmp_path):
    from zugup.profile.weaknesses import cached_report_data
    from zugup.storage.db import connect

    conn = connect(tmp_path / "cache.db")
    first = cached_report_data(conn)
    assert cached_report_data(conn) is first
    conn.execute("INSERT INTO games (source, game_id, played_at, white, black, user_color, result, pgn) VALUES ('lichess', 'z', '2026-01-01T00:00:00Z', 'a', 'b', 'white', '1-0', '*')")
    conn.commit()
    assert cached_report_data(conn) is not first
