import pytest

from zugup.importers import lichess
from zugup.storage.db import connect

PGN = """[Event "rated blitz game"]
[Site "https://lichess.org/game/AAAAAAAA"]
[White "niamo"]
[Black "opp"]
[Result "1-0"]
[GameId "AAAAAAAA"]
[UTCDate "2026.10.22"]
[UTCTime "22:49:55"]
[Variant "Standard"]
[TimeControl "180+0"]
[ECO "C44"]
[Opening "Scotch Game"]

1. e4 { [%eval 0.2] [%clk 0:03:00] } 1... e5 { [%eval 0.3] [%clk 0:02:59] } 2. Nf3 { [%eval #3] [%clk 0:02:58] } 1-0

[Event "rated blitz game"]
[Site "https://lichess.org/game/BBBBBBBB"]
[White "opp"]
[Black "Niamo"]
[Result "0-1"]
[UTCDate "2026.10.23"]
[UTCTime "10:00:00"]
[TimeControl "600+0"]
[ECO "?"]
[Opening "?"]

1. d4 d5 0-1

[Event "rated atomic game"]
[Site "https://lichess.org/game/CCCCCCCC"]
[White "niamo"]
[Black "opp"]
[Result "1-0"]
[GameId "CCCCCCCC"]
[UTCDate "2026.10.24"]
[UTCTime "10:00:00"]
[Variant "Atomic"]

1. e4 e5 1-0

[Event "rated blitz game"]
[Site "https://lichess.org/game/DDDDDDDD"]
[White "a"]
[Black "b"]
[Result "1/2-1/2"]
[GameId "DDDDDDDD"]
[UTCDate "2026.10.25"]
[UTCTime "10:00:00"]

1. e4 e5 1/2-1/2
"""


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text
        self.encoding = None


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def fake_get(monkeypatch):
    calls = []
    responses = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        return responses.pop(0)

    monkeypatch.setattr(lichess.requests, "get", get)
    return calls, responses


def test_parse_keeps_only_user_standard_games():
    games = list(lichess.parse_games(PGN, "niamo"))
    assert [g["game_id"] for g, _ in games] == ["AAAAAAAA", "BBBBBBBB"]


def test_parse_metadata():
    (meta, _), (meta2, _) = lichess.parse_games(PGN, "niamo")
    assert meta["played_at"] == "2026-10-22T22:49:55Z"
    assert meta["user_color"] == "white"
    assert meta["time_control"] == "180+0"
    assert meta["opening_eco"] == "C44"
    assert meta2["user_color"] == "black"
    assert meta2["opening_eco"] is None
    assert meta2["opening_name"] is None
    assert meta2["game_id"] == "BBBBBBBB"


def test_parse_moves_clock_and_eval():
    (_, moves), _ = lichess.parse_games(PGN, "niamo")
    assert [m["san"] for m in moves] == ["e4", "e5", "Nf3"]
    assert [m["uci"] for m in moves] == ["e2e4", "e7e5", "g1f3"]
    assert moves[0]["fen_before"].startswith("rnbqkbnr/pppppppp")
    assert moves[0]["clock_seconds"] == 180
    assert moves[0]["eval"] == {
        "origin": "lichess", "cp_before": None, "mate_before": None,
        "cp_after": 20, "mate_after": None,
    }
    assert moves[1]["eval"]["cp_before"] == 20
    assert moves[1]["eval"]["cp_after"] == 30
    assert moves[2]["eval"]["cp_after"] is None
    assert moves[2]["eval"]["mate_after"] == 3


def test_parse_moves_without_eval():
    _, (_, moves) = lichess.parse_games(PGN, "niamo")
    assert all(m["eval"] is None for m in moves)
    assert all(m["clock_seconds"] is None for m in moves)


def test_fetch_sends_token_and_params(fake_get):
    calls, responses = fake_get
    responses.append(FakeResponse(200, PGN))
    text = lichess.fetch_pgn("niamo", "tok", max_games=5)
    assert text == PGN
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert calls[0]["params"]["max"] == 5
    assert "since" not in calls[0]["params"]


def test_fetch_since_keeps_default_newest_first(fake_get):
    calls, responses = fake_get
    responses.append(FakeResponse(200, ""))
    lichess.fetch_pgn("niamo", "tok", max_games=5, since_ms=1000)
    assert calls[0]["params"]["since"] == 1000
    assert "sort" not in calls[0]["params"]


def test_fetch_retries_on_429(fake_get):
    calls, responses = fake_get
    responses.extend([FakeResponse(429), FakeResponse(200, PGN)])
    waits = []
    assert lichess.fetch_pgn("niamo", "tok", sleep=waits.append) == PGN
    assert waits == [lichess.RETRY_WAIT]
    assert len(calls) == 2


def test_fetch_gives_up_after_retries(fake_get):
    _, responses = fake_get
    responses.extend([FakeResponse(429)] * (lichess.MAX_RETRIES + 1))
    waits = []
    with pytest.raises(lichess.LichessError, match="429"):
        lichess.fetch_pgn("niamo", "tok", sleep=waits.append)
    assert len(waits) == lichess.MAX_RETRIES


def test_fetch_requires_token(fake_get):
    with pytest.raises(lichess.LichessError, match="TOKEN"):
        lichess.fetch_pgn("niamo", "")


def test_fetch_error_does_not_leak_token(fake_get):
    _, responses = fake_get
    responses.append(FakeResponse(404))
    with pytest.raises(lichess.LichessError) as exc:
        lichess.fetch_pgn("niamo", "secret-token")
    assert "secret-token" not in str(exc.value)


def test_import_is_idempotent(conn, fake_get):
    _, responses = fake_get
    responses.extend([FakeResponse(200, PGN), FakeResponse(200, PGN)])
    first = lichess.import_games(conn, "niamo", "tok")
    second = lichess.import_games(conn, "niamo", "tok")
    assert first == {"fetched": 2, "new": 2, "skipped": 0}
    assert second == {"fetched": 2, "new": 0, "skipped": 2}
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM moves").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM evals").fetchone()[0] == 3


def test_import_uses_latest_game_as_since(conn, fake_get):
    calls, responses = fake_get
    responses.extend([FakeResponse(200, PGN), FakeResponse(200, "")])
    lichess.import_games(conn, "niamo", "tok")
    lichess.import_games(conn, "niamo", "tok")
    assert "since" not in calls[0]["params"]
    assert calls[1]["params"]["since"] == 1792749600000


def test_dry_run_writes_nothing(conn, fake_get):
    _, responses = fake_get
    responses.append(FakeResponse(200, PGN))
    stats = lichess.import_games(conn, "niamo", "tok", dry_run=True)
    assert stats == {"fetched": 2, "new": 2, "skipped": 0}
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0


def test_import_stops_at_max_games(conn, fake_get):
    _, responses = fake_get
    responses.append(FakeResponse(200, PGN))
    stats = lichess.import_games(conn, "niamo", "tok", max_games=1)
    assert stats == {"fetched": 1, "new": 1, "skipped": 0}
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def test_parse_speed_from_event():
    games = list(lichess.parse_games(PGN, "niamo"))
    assert games[0][0]["speed"] == "blitz"
    assert lichess.event_speed("rated ultraBullet game") == "bullet"
    assert lichess.event_speed("Casual rapid game") == "rapid"
    assert lichess.event_speed(None) is None


def test_fetch_filters_by_selected_speeds(fake_get):
    calls, responses = fake_get
    responses.extend([FakeResponse(200, ""), FakeResponse(200, ""), FakeResponse(200, "")])
    lichess.fetch_pgn("niamo", "tok", speeds=["bullet", "rapid"])
    lichess.fetch_pgn("niamo", "tok", speeds=["blitz"])
    lichess.fetch_pgn("niamo", "tok")
    assert calls[0]["params"]["perfType"] == "ultraBullet,bullet,rapid"
    assert calls[1]["params"]["perfType"] == "blitz"
    assert calls[2]["params"]["perfType"] == lichess.PERF_TYPES
