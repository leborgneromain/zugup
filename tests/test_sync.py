import pytest

from tests.test_web import GAME, START, make_client
from zugup.storage.db import add_game, connect, set_credential
from zugup.web import jobs, preferences
from zugup.web import app as web


@pytest.fixture
def cfg(tmp_path):
    return {"storage": {"db_path": str(tmp_path / "sync.db")}, "stockfish": {"path": "sf"}}


SOURCE = {"source": "lichess"}


def connect_lichess(cfg, name="me"):
    conn = connect(cfg["storage"]["db_path"])
    set_credential(conn, "lichess", "<TOKEN>", name)
    conn.close()


def make_app(cfg):
    app = web.create_app(cfg)
    return app, app.test_client(), app.config["SYNC"]


def fake_imports(monkeypatch, calls):
    monkeypatch.setattr(jobs.lichess, "import_games", lambda conn, name, token, limit, speeds=None: calls.append(("lichess", name, limit)))
    monkeypatch.setattr(jobs.chesscom, "import_games", lambda conn, name, limit, speeds=None: calls.append(("chesscom", name, limit)))


def test_sync_without_account_is_refused(cfg):
    _, client, _ = make_app(cfg)
    response = client.post("/api/sync", json=SOURCE)
    assert response.status_code == 400 and client.get("/api/sync").get_json()["state"] == "idle"


def test_sync_imports_the_requested_account_then_analyzes_and_classifies(cfg, monkeypatch):
    calls = []
    fake_imports(monkeypatch, calls)
    _, client, sync = make_app(cfg)
    conn = connect(cfg["storage"]["db_path"])
    gid = add_game(conn, GAME)
    conn.execute("INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'a3', 'a2a3', ?)", (gid, START))
    conn.commit()
    classified = []

    def fake_run(conn, path, depth, threads, hash_mb, workers, limit, on_game):
        calls.append(("run", path, limit))
        stats = {"analyzed": 1}
        on_game(gid, stats)

    monkeypatch.setattr(jobs.runner, "run", fake_run)
    monkeypatch.setattr(jobs, "classify_stored_game", lambda conn, game_id: classified.append(game_id))
    connect_lichess(cfg)
    client.put("/api/preferences", json={"accounts": {"chesscom": "you"}, "import_limit": 7})
    assert client.post("/api/sync", json=SOURCE).status_code == 202
    sync.join(5)
    status = client.get("/api/sync").get_json()
    assert status["state"] == "done" and status["analyzed"] == 1 and status["error"] is None
    assert calls == [("lichess", "me", 7), ("run", "sf", 7)]
    assert status["source"] == "lichess"
    assert classified == [gid]


def test_sync_imports_only_the_requested_platform(cfg, monkeypatch):
    calls = []
    fake_imports(monkeypatch, calls)
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: calls.append("run"))
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.put("/api/preferences", json={"accounts": {"chesscom": "you"}})
    client.post("/api/sync", json={"source": "chesscom"})
    sync.join(5)
    assert calls == [("chesscom", "you", 50), "run"]


@pytest.mark.parametrize("body", [None, {}, {"source": "twitch"}, {"source": 3}, ["lichess"]])
def test_sync_rejects_a_missing_or_unknown_source(cfg, body):
    _, client, _ = make_app(cfg)
    connect_lichess(cfg)
    assert client.post("/api/sync", json=body).status_code == 400


def test_sync_refuses_a_platform_without_account(cfg):
    _, client, _ = make_app(cfg)
    connect_lichess(cfg)
    assert client.post("/api/sync", json={"source": "chesscom"}).status_code == 400


def test_sync_reports_errors_and_can_restart(cfg, monkeypatch):
    def boom(conn, name, token, limit, speeds=None):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(jobs.lichess, "import_games", boom)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    status = client.get("/api/sync").get_json()
    assert status["state"] == "error" and status["error"] == "rate limited"
    assert client.post("/api/sync", json=SOURCE).status_code == 202
    sync.join(5)


def test_sync_requires_stockfish_path(tmp_path, monkeypatch):
    cfg = {"storage": {"db_path": str(tmp_path / "s.db")}}
    fake_imports(monkeypatch, [])
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    assert client.get("/api/sync").get_json()["error"] == "Stockfish is not configured"


def test_second_sync_while_running_gets_409(cfg, monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(jobs.lichess, "import_games", lambda *a, **k: gate.wait(5))
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    assert client.post("/api/sync", json=SOURCE).status_code == 202
    assert client.post("/api/sync", json=SOURCE).status_code == 409
    assert client.get("/api/sync").get_json()["state"] == "running"
    gate.set()
    sync.join(5)
    assert client.get("/api/sync").get_json()["state"] == "done"


def test_status_counts_games_added_during_the_job(cfg, monkeypatch):
    def add(conn, name, token, limit, speeds=None):
        add_game(conn, {**GAME, "game_id": "new1"})

    monkeypatch.setattr(jobs.lichess, "import_games", add)
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    assert client.get("/api/sync").get_json()["added"] == 1


def seeded(cfg):
    conn = connect(cfg["storage"]["db_path"])
    gid = add_game(conn, GAME)
    cur = conn.execute("INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'a3', 'a2a3', ?)", (gid, START))
    move_id = cur.lastrowid
    conn.execute("INSERT INTO evals (move_id, cp_before, cp_after, best_uci, depth, origin) VALUES (?, 0, -300, 'e2e4', 10, 'stockfish')", (move_id,))
    conn.execute("INSERT INTO mistakes (move_id, category, cp_loss, phase) VALUES (?, 'blunder', 300, 'opening')", (move_id,))
    conn.execute("INSERT INTO attempts (move_id, played_uci, correct, attempted_at) VALUES (?, 'e2e4', 1, 'now')", (move_id,))
    conn.execute("INSERT INTO coach_checks (week, speed, task, done) VALUES ('2026-01-05', 'bullet', 'axis:time', 1)")
    conn.commit()
    return conn


def test_reset_deletes_imports_and_history_but_keeps_preferences(cfg):
    conn = seeded(cfg)
    _, client, _ = make_app(cfg)
    connect_lichess(cfg)
    client.put("/api/preferences", json={"import_limit": 9})
    response = client.post("/api/reset")
    assert response.status_code == 200 and response.get_json() == {"deleted": 1}
    for table in ("games", "moves", "evals", "mistakes", "attempts", "coach_checks"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    prefs = client.get("/api/preferences").get_json()
    assert prefs["import_limit"] == 9
    assert conn.execute("SELECT username FROM credentials").fetchone()[0] == "me"


def test_reset_is_refused_while_a_sync_runs(cfg, monkeypatch):
    import threading

    gate = threading.Event()
    monkeypatch.setattr(jobs.lichess, "import_games", lambda *a, **k: gate.wait(5))
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    conn = seeded(cfg)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.post("/api/sync", json=SOURCE)
    assert client.post("/api/reset").status_code == 409
    gate.set()
    sync.join(5)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1


def test_reset_button_shows_the_game_count(cfg):
    seeded(cfg)
    _, client, _ = make_app(cfg)
    html = client.get("/compte").get_data(as_text=True)
    assert 'id="reset-button"' in html and 'data-games="1"' in html
    client.post("/api/reset")
    assert 'data-games="0"' in client.get("/compte").get_data(as_text=True)


def test_pages_still_render_after_a_reset(cfg):
    seeded(cfg)
    _, client, _ = make_app(cfg)
    client.get("/rapport")
    client.post("/api/reset")
    for path in ("/rapport", "/coach", "/entrainement", "/repertoire", "/compte"):
        assert client.get(path).status_code == 200


def pending_game(conn, game_id="p1", source="lichess"):
    gid = add_game(conn, {**GAME, "game_id": game_id, "source": source})
    conn.execute("INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'a3', 'a2a3', ?)", (gid, START))
    conn.commit()
    return gid


def test_resume_classifies_leftovers_then_analyzes_everything_without_importing(cfg, monkeypatch):
    calls = []
    fake_imports(monkeypatch, calls)
    conn = seeded(cfg)
    pending_game(conn)
    classified = []
    monkeypatch.setattr(jobs, "classify_stored_game", lambda conn, game_id: classified.append(game_id))
    monkeypatch.setattr(jobs.runner, "run", lambda conn, path, d, t, h, w, limit, on_game: calls.append(("run", limit)))
    _, client, sync = make_app(cfg)
    assert sync.resume_if_needed(conn) is True
    sync.join(5)
    status = client.get("/api/sync").get_json()
    assert status["state"] == "done" and status["source"] == "resume"
    assert calls == [("run", None)] and len(classified) == 1


def test_resume_if_needed_requires_work_and_stockfish(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    conn = connect(cfg["storage"]["db_path"])
    _, _, sync = make_app(cfg)
    assert sync.resume_if_needed(conn) is False
    pending_game(conn)
    assert sync.resume_if_needed(conn) is True
    sync.join(5)
    no_stockfish = jobs.SyncJob({"storage": cfg["storage"]})
    assert no_stockfish.resume_if_needed(conn) is False


def test_auto_resume_starts_a_job_and_serve_calls_it(cfg, monkeypatch):
    runs = []
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: runs.append(1))
    pending_game(connect(cfg["storage"]["db_path"]))
    app = web.create_app(cfg)
    web.auto_resume(app, cfg)
    app.config["SYNC"].join(5)
    assert runs == [1]
    seen = []
    monkeypatch.setattr(web, "auto_resume", lambda app, cfg: seen.append(cfg))
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: None)
    web.serve(cfg, analyzer_factory=lambda *a: None)
    assert seen == [cfg]


def test_auto_resume_survives_failures_and_missing_storage(cfg, capsys):
    web.auto_resume(web.create_app({}), {})
    app = web.create_app(cfg)
    app.config["SYNC"].resume_if_needed = lambda conn: 1 / 0
    web.auto_resume(app, cfg)
    assert "Analysis not resumed" in capsys.readouterr().err


def test_account_page_shows_analysis_counts_and_the_resume_button(cfg):
    conn = seeded(cfg)
    pending_game(conn, "p2", "chesscom")
    _, client, _ = make_app(cfg)
    html = client.get("/compte").get_data(as_text=True)
    assert "1 analysée, 0 en attente" in html and "0 analysées, 1 en attente" in html
    assert "2 parties à analyser ou à classer" in html


def test_account_page_says_when_nothing_is_left(cfg):
    _, client, _ = make_app(cfg)
    html = client.get("/compte").get_data(as_text=True)
    assert "Toutes les parties importées sont analysées." in html


def test_classification_marks_games_and_clears_the_leftovers(cfg):
    from zugup.analysis.classify import classify_stored_game
    from zugup.storage.db import analysis_counts, unclassified_games

    conn = seeded(cfg)
    pending = pending_game(conn)
    gid = unclassified_games(conn)[0]
    assert pending not in unclassified_games(conn)
    assert analysis_counts(conn)["lichess"] == {"pending": 1, "analyzed": 1}
    classify_stored_game(conn, gid)
    assert unclassified_games(conn) == []
    assert conn.execute("SELECT classified FROM games WHERE id = ?", (gid,)).fetchone()[0] == 1
    assert conn.execute("SELECT classified FROM games WHERE id = ?", (pending,)).fetchone()[0] == 0


def test_resume_cannot_be_started_from_the_api(cfg):
    _, client, _ = make_app(cfg)
    assert client.post("/api/sync", json={"source": "resume"}).status_code == 400


def test_sync_analyzes_at_the_chosen_depth_and_defaults_to_16(cfg, monkeypatch):
    depths = []
    fake_imports(monkeypatch, [])
    monkeypatch.setattr(jobs.runner, "run", lambda conn, path, depth, *a, **k: depths.append(depth))
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    client.put("/api/preferences", json={"depth": 14})
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    assert depths == [16, 14]


def test_resume_uses_the_chosen_depth_over_the_config(cfg, monkeypatch):
    depths = []
    monkeypatch.setattr(jobs.runner, "run", lambda conn, path, depth, *a, **k: depths.append(depth))
    conn = connect(cfg["storage"]["db_path"])
    pending_game(conn)
    _, client, sync = make_app({**cfg, "stockfish": {"path": "sf", "depth": 20}})
    client.put("/api/preferences", json={"depth": 15})
    assert sync.resume_if_needed(conn) is True
    sync.join(5)
    assert depths == [15]


def test_sync_passes_the_selected_import_speeds(cfg, monkeypatch):
    seen = []
    monkeypatch.setattr(jobs.lichess, "import_games", lambda conn, name, token, limit, speeds=None: seen.append(speeds))
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg)
    client.put("/api/preferences", json={"import_speeds": ["blitz", "rapid"]})
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    assert seen == [["blitz", "rapid"]]


def test_lichess_import_is_refused_until_the_account_is_connected(cfg):
    _, client, _ = make_app(cfg)
    client.put("/api/preferences", json={"accounts": {"lichess": "someone-else"}})
    response = client.post("/api/sync", json=SOURCE)
    assert response.status_code == 400 and client.get("/api/sync").get_json()["state"] == "idle"


def test_lichess_import_uses_the_connected_account_not_the_typed_pseudo(cfg, monkeypatch):
    seen = []
    monkeypatch.setattr(jobs.lichess, "import_games", lambda conn, name, token, limit, speeds=None: seen.append((name, token)))
    monkeypatch.setattr(jobs.runner, "run", lambda *a, **k: None)
    _, client, sync = make_app(cfg)
    connect_lichess(cfg, "owner")
    client.put("/api/preferences", json={"accounts": {"lichess": "someone-else"}})
    client.post("/api/sync", json=SOURCE)
    sync.join(5)
    assert seen == [("owner", "<TOKEN>")]


class FakeAuth:
    def __init__(self, monkeypatch, username="owner", fail=False):
        self.revoked = []
        monkeypatch.setattr(web.lichess_auth, "exchange_code", self.exchange)
        monkeypatch.setattr(web.lichess_auth, "fetch_username", lambda token: self.username(fail, username))
        monkeypatch.setattr(web.lichess_auth, "revoke", lambda token: self.revoked.append(token))

    def exchange(self, code, verifier, redirect_uri):
        self.args = (code, verifier, redirect_uri)
        return "<TOKEN>"

    @staticmethod
    def username(fail, username):
        if fail:
            raise web.lichess_auth.LichessAuthError("no")
        return username


def start_oauth(client):
    from urllib.parse import parse_qs, urlparse

    response = client.get("/auth/lichess")
    assert response.status_code == 302
    url = urlparse(response.headers["Location"])
    return url, {k: v[0] for k, v in parse_qs(url.query).items()}


def test_connect_redirects_to_lichess_with_pkce(cfg):
    _, client, _ = make_app(cfg)
    url, query = start_oauth(client)
    assert url.netloc == "lichess.org" and url.path == "/oauth"
    assert query["response_type"] == "code" and query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == "http://localhost/auth/lichess/callback" and query["code_challenge"] and query["state"]
    assert "scope" not in query


def test_callback_stores_the_account_owning_the_token(cfg, monkeypatch):
    auth = FakeAuth(monkeypatch)
    _, client, _ = make_app(cfg)
    _, query = start_oauth(client)
    response = client.get("/auth/lichess/callback", query_string={"code": "abc", "state": query["state"]})
    assert response.headers["Location"].endswith("/compte?lichess=connected")
    assert auth.args[0] == "abc" and auth.args[2] == query["redirect_uri"]
    page = client.get("/compte").get_data(as_text=True)
    assert "Connecté : owner" in page and "<TOKEN>" not in page
    assert "<TOKEN>" not in client.get("/api/preferences").get_data(as_text=True)
    assert 'class="secondary sync-button" data-source="lichess"' in client.get("/compte").get_data(as_text=True)


def test_callback_rejects_unknown_state_denial_and_failures(cfg, monkeypatch):
    FakeAuth(monkeypatch, fail=True)
    _, client, _ = make_app(cfg)
    assert client.get("/auth/lichess/callback", query_string={"code": "abc", "state": "forged"}).headers["Location"].endswith("refused")
    _, query = start_oauth(client)
    assert client.get("/auth/lichess/callback", query_string={"error": "access_denied", "state": query["state"]}).headers["Location"].endswith("refused")
    _, query = start_oauth(client)
    assert client.get("/auth/lichess/callback", query_string={"code": "abc", "state": query["state"]}).headers["Location"].endswith("failed")
    conn = connect(cfg["storage"]["db_path"])
    assert conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0


def test_state_is_single_use(cfg, monkeypatch):
    FakeAuth(monkeypatch)
    _, client, _ = make_app(cfg)
    _, query = start_oauth(client)
    params = {"code": "abc", "state": query["state"]}
    assert client.get("/auth/lichess/callback", query_string=params).headers["Location"].endswith("connected")
    assert client.get("/auth/lichess/callback", query_string=params).headers["Location"].endswith("refused")


def test_disconnect_revokes_and_forgets_the_token(cfg, monkeypatch):
    auth = FakeAuth(monkeypatch)
    _, client, _ = make_app(cfg)
    connect_lichess(cfg)
    assert client.post("/api/lichess/disconnect").status_code == 200
    assert auth.revoked == ["<TOKEN>"]
    assert client.post("/api/sync", json=SOURCE).status_code == 400
    page = client.get("/compte").get_data(as_text=True)
    assert "Connecter Lichess" in page and 'sync-button" data-source="lichess"' not in page


def test_dev_mode_reloads_and_only_the_child_starts_the_services(cfg, monkeypatch):
    runs, opened, resumed = [], [], []
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: runs.append(kwargs))
    monkeypatch.setattr(web, "auto_resume", lambda app, cfg: resumed.append(1))
    monkeypatch.setattr(web, "warm_cache", lambda cfg: opened.append("warm"))
    factory = lambda *a: opened.append("analyzer")
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    web.serve(cfg, analyzer_factory=factory, dev=True)
    assert runs[-1]["use_reloader"] is True and opened == [] and resumed == []
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    web.serve(cfg, analyzer_factory=factory, dev=True)
    assert runs[-1]["use_reloader"] is True and opened == ["analyzer", "warm"] and resumed == [1]


def test_normal_mode_does_not_reload(cfg, monkeypatch):
    runs = []
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: runs.append(kwargs))
    monkeypatch.setattr(web, "auto_resume", lambda app, cfg: None)
    web.serve(cfg, analyzer_factory=lambda *a: None)
    assert runs[-1]["use_reloader"] is False and runs[-1]["debug"] is False
