import pytest

from zugup.importers import chesscom
from zugup.storage.db import connect

BASE = "https://api.chess.com/pub/player/n1amo/games"
ARCHIVES = f"{BASE}/archives"


def raw_game(gid, date, time, white="n1amo", black="opp", rules="chess",
             eco_url="https://www.chess.com/openings/Scandinavian-Defense-2.exd5"):
    pgn = (
        f'[Event "Live Chess"]\n[Site "Chess.com"]\n[Date "{date}"]\n'
        f'[White "{white}"]\n[Black "{black}"]\n[Result "1-0"]\n[ECO "B01"]\n'
        f'[ECOUrl "{eco_url}"]\n[UTCDate "{date}"]\n[UTCTime "{time}"]\n'
        f'[TimeControl "600"]\n\n'
        "1. e4 {[%clk 0:09:59.1]} 1... d5 {[%clk 0:09:58]} 2. exd5 {[%clk 0:09:57.8]} 1-0\n"
    )
    return {"url": f"https://www.chess.com/game/live/{gid}", "pgn": pgn, "rules": rules}


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def api(monkeypatch):
    state = {"calls": [], "data": {}, "queue": []}

    def get(url, headers=None, timeout=None):
        state["calls"].append({"url": url, "headers": headers})
        if state["queue"]:
            return state["queue"].pop(0)
        return FakeResponse(200, state["data"][url])

    monkeypatch.setattr(chesscom.requests, "get", get)
    state["data"][ARCHIVES] = {"archives": [f"{BASE}/2026/09", f"{BASE}/2026/10"]}
    state["data"][f"{BASE}/2026/09"] = {"games": [raw_game(1, "2026.09.30", "10:00:00")]}
    state["data"][f"{BASE}/2026/10"] = {
        "games": [raw_game(2, "2026.10.01", "10:00:00"), raw_game(3, "2026.10.02", "10:00:00")]
    }
    return state


def test_parse_metadata_and_moves():
    meta, moves = chesscom.parse_game(raw_game(42, "2026.10.25", "19:20:41"), "N1amo")
    assert meta["game_id"] == "live/42"
    assert meta["played_at"] == "2026-10-25T19:20:41Z"
    assert meta["user_color"] == "white"
    assert meta["time_control"] == "600"
    assert meta["opening_eco"] == "B01"
    assert meta["opening_name"] == "Scandinavian Defense"
    assert [m["san"] for m in moves] == ["e4", "d5", "exd5"]
    assert moves[0]["clock_seconds"] == pytest.approx(599.1)
    assert all(m["eval"] is None for m in moves)


def test_parse_black_side():
    meta, _ = chesscom.parse_game(raw_game(1, "2026.10.25", "10:00:00", white="x", black="n1amo"), "n1amo")
    assert meta["user_color"] == "black"


def test_parse_skips_variants_and_foreign_games():
    assert chesscom.parse_game(raw_game(1, "2026.10.25", "10:00:00", rules="chess960"), "n1amo") is None
    assert chesscom.parse_game(raw_game(1, "2026.10.25", "10:00:00", white="a", black="b"), "n1amo") is None
    assert chesscom.parse_game({"url": "x", "pgn": "", "rules": "chess"}, "n1amo") is None


@pytest.mark.parametrize("url,expected", [
    ("https://www.chess.com/openings/Scandinavian-Defense-2.exd5", "Scandinavian Defense"),
    ("https://www.chess.com/openings/Sicilian-Defense-Smith-Morra-Gambit-3...cxd4", "Sicilian Defense Smith Morra Gambit"),
    ("https://www.chess.com/openings/Italian-Game", "Italian Game"),
    (None, None),
    ("", None),
])
def test_opening_name(url, expected):
    assert chesscom.opening_name(url) == expected


def test_select_months_first_import_is_newest_first():
    archives = [f"{BASE}/2026/09", f"{BASE}/2026/10", f"{BASE}/2026/08"]
    assert [u[-7:] for u in chesscom.select_months(archives, None)] == ["2026/10", "2026/09", "2026/08"]


def test_select_months_incremental_is_newest_first_from_last_month():
    archives = [f"{BASE}/2026/10", f"{BASE}/2026/08", f"{BASE}/2026/09"]
    assert [u[-7:] for u in chesscom.select_months(archives, "2026-09-15T10:00:00Z")] == ["2026/10", "2026/09"]


def test_first_import_takes_newest_and_stops_early(conn, api):
    stats = chesscom.import_games(conn, "n1amo", max_games=2)
    assert stats == {"fetched": 2, "new": 2, "skipped": 0}
    ids = {r[0] for r in conn.execute("SELECT game_id FROM games")}
    assert ids == {"live/2", "live/3"}
    assert [c["url"] for c in api["calls"]] == [ARCHIVES, f"{BASE}/2026/10"]


def test_import_is_idempotent_and_incremental(conn, api):
    chesscom.import_games(conn, "n1amo")
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 3
    api["data"][f"{BASE}/2026/10"]["games"].append(raw_game(4, "2026.10.03", "10:00:00"))
    api["calls"].clear()
    stats = chesscom.import_games(conn, "n1amo")
    assert stats == {"fetched": 3, "new": 1, "skipped": 2}
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM moves").fetchone()[0] == 12
    assert [c["url"] for c in api["calls"]] == [ARCHIVES, f"{BASE}/2026/10"]


def test_dry_run_writes_nothing(conn, api):
    stats = chesscom.import_games(conn, "n1amo", dry_run=True)
    assert stats == {"fetched": 3, "new": 3, "skipped": 0}
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def test_user_agent_is_sent(conn, api):
    chesscom.import_games(conn, "n1amo", max_games=1)
    assert all(c["headers"]["User-Agent"] == chesscom.USER_AGENT for c in api["calls"])


def test_retries_on_429(api):
    api["queue"].extend([FakeResponse(429), FakeResponse(200, {"archives": []})])
    waits = []
    assert chesscom.get_json(ARCHIVES, sleep=waits.append) == {"archives": []}
    assert waits == [chesscom.RETRY_WAIT]


def test_gives_up_after_retries(api):
    api["queue"].extend([FakeResponse(429)] * (chesscom.MAX_RETRIES + 1))
    waits = []
    with pytest.raises(chesscom.ChesscomError, match="429"):
        chesscom.get_json(ARCHIVES, sleep=waits.append)
    assert len(waits) == chesscom.MAX_RETRIES


def test_http_error_raises(api):
    api["queue"].append(FakeResponse(404))
    with pytest.raises(chesscom.ChesscomError, match="404"):
        chesscom.get_json(ARCHIVES)


def test_parse_speed_from_time_class():
    raw = raw_game(42, "2026.10.25", "19:20:41")
    raw["time_class"] = "blitz"
    meta, _ = chesscom.parse_game(raw, "N1amo")
    assert meta["speed"] == "blitz"



def test_incremental_import_with_cap_takes_newest_new_games(conn, api):
    chesscom.import_games(conn, "n1amo", max_games=1)
    api["data"][f"{BASE}/2026/10"]["games"] += [
        raw_game(4, "2026.10.03", "10:00:00"),
        raw_game(5, "2026.10.04", "10:00:00"),
        raw_game(6, "2026.10.05", "10:00:00"),
    ]
    stats = chesscom.import_games(conn, "n1amo", max_games=2)
    assert stats["new"] == 2
    ids = {r[0] for r in conn.execute("SELECT game_id FROM games")}
    assert {"live/6", "live/5"} <= ids
    assert "live/4" not in ids


def test_import_keeps_only_selected_speeds(conn, api):
    games = api["data"][f"{BASE}/2026/10"]["games"]
    games[0]["time_class"] = "bullet"
    games[1]["time_class"] = "blitz"
    stats = chesscom.import_games(conn, "n1amo", max_games=1, speeds=["bullet"])
    assert stats["new"] == 1
    assert {r[0] for r in conn.execute("SELECT game_id FROM games")} == {"live/2"}
