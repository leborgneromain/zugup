import pytest

from zugup import __main__ as main
from zugup.storage.db import add_game, connect
from zugup.web import app as web


def test_serve_binds_to_localhost_with_debug_off(monkeypatch):
    calls = []
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: calls.append(kwargs))
    web.serve({}, analyzer_factory=lambda *a: None)
    assert calls == [{"host": "127.0.0.1", "port": web.DEFAULT_PORT, "debug": False, "use_reloader": False, "threaded": False}]


def test_serve_port_can_change_but_not_host(monkeypatch):
    calls = []
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: calls.append(kwargs))
    web.serve({}, port=9000, analyzer_factory=lambda *a: None)
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 9000


def test_launcher_has_no_host_option():
    with pytest.raises(SystemExit):
        main.main(["--host", "0.0.0.0"])


def test_launcher_runs_the_server(monkeypatch):
    seen = []
    monkeypatch.setattr(main.web, "serve", lambda cfg, port, dev: seen.append((cfg["storage"]["db_path"].endswith("zugup.db"), port, dev)))
    assert main.main(["--port", "9100"]) == 0
    assert main.main(["--dev"]) == 0
    assert seen == [(True, 9100, False), (True, web.DEFAULT_PORT, True)]


START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
GAME = {
    "source": "lichess", "game_id": "g1", "played_at": "2026-01-01T10:00:00Z",
    "white": "me", "black": "opp", "user_color": "white", "result": "1-0",
    "time_control": "60+0", "opening_eco": None, "opening_name": None, "pgn": "*",
}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "web.db"
    conn = connect(path)
    gid = add_game(conn, GAME)
    cur = conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'a3', 'a2a3', ?)",
        (gid, START),
    )
    conn.execute(
        "INSERT INTO evals (move_id, origin, best_uci, cp_before, depth) VALUES (?, 'stockfish', 'e2e4', 30, 10)",
        (cur.lastrowid,),
    )
    conn.execute("INSERT INTO mistakes (move_id, category, cp_loss, phase) VALUES (?, 'blunder', 300, 'opening')", (cur.lastrowid,))
    conn.commit()
    conn.close()
    return path


def make_client(db_path, evaluate=None):
    app = web.create_app({"storage": {"db_path": str(db_path)}}, evaluate)
    return app.test_client()


def attempts(db_path):
    conn = connect(db_path)
    rows = [dict(r) for r in conn.execute("SELECT move_id, played_uci, correct FROM attempts ORDER BY id")]
    conn.close()
    return rows


def test_next_exercise_hides_the_solution(db_path):
    data = make_client(db_path).get("/api/exercise/next").get_json()
    exercise = data["exercise"]
    assert {k: exercise[k] for k in ("move_id", "fen", "orientation", "category", "phase")} == {
        "move_id": 1, "fen": START, "orientation": "white", "category": "blunder", "phase": "opening",
    }
    assert "pgn" not in exercise
    assert "e2e4" not in str(data)


def test_next_exercise_is_null_when_none_left(tmp_path):
    client = make_client(tmp_path / "empty.db")
    assert client.get("/api/exercise/next").get_json() == {"exercise": None, "remaining": 0}


def test_correct_answer_is_recorded_and_reveals_the_reference(db_path):
    response = make_client(db_path).post("/api/exercise/1/answer", json={"move": "e2e4"})
    assert response.status_code == 200
    assert response.get_json() == {
        "correct": True, "verdict": "reference", "message": None, "best_uci": "e2e4", "best_san": "e4",
    }
    assert attempts(db_path) == [{"move_id": 1, "played_uci": "e2e4", "correct": 1}]


def test_wrong_answer_without_engine_is_recorded_with_message(db_path):
    response = make_client(db_path).post("/api/exercise/1/answer", json={"move": "d2d4"})
    data = response.get_json()
    assert data["correct"] is False and data["message"].startswith("Moteur indisponible")
    assert attempts(db_path) == [{"move_id": 1, "played_uci": "d2d4", "correct": 0}]


def test_equivalent_answer_uses_the_engine(db_path):
    evaluate = lambda board: {"cp": 28, "mate": None, "best_uci": None}
    data = make_client(db_path, evaluate).post("/api/exercise/1/answer", json={"move": "d2d4"}).get_json()
    assert data["verdict"] == "equivalent" and data["correct"] is True


@pytest.mark.parametrize("body", [{"move": "e2e5"}, {"move": "zzzz"}, {"move": 3}, {}, None])
def test_invalid_answers_are_rejected_and_not_recorded(db_path, body):
    response = make_client(db_path).post("/api/exercise/1/answer", json=body)
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert attempts(db_path) == []


def test_unknown_exercise_is_404(db_path):
    response = make_client(db_path).post("/api/exercise/99/answer", json={"move": "e2e4"})
    assert response.status_code == 404
    assert attempts(db_path) == []


def test_mastered_exercise_is_no_longer_proposed(db_path):
    client = make_client(db_path)
    client.post("/api/exercise/1/answer", json={"move": "e2e4"})
    client.post("/api/exercise/1/answer", json={"move": "e2e4"})
    assert client.get("/api/exercise/next").get_json() == {"exercise": None, "remaining": 0}


VENDOR = "/static/vendor/cm-chessboard"


@pytest.mark.parametrize("path", [
    "/src/Chessboard.js", "/assets/chessboard.css", "/assets/pieces/standard.svg", "/LICENSE", "/NOTICE.md",
])
def test_chessboard_files_are_served_locally(db_path, path):
    assert make_client(db_path).get(VENDOR + path).status_code == 200


def test_only_the_cc_by_sa_piece_set_is_shipped(db_path):
    assert make_client(db_path).get(VENDOR + "/assets/pieces/staunty.svg").status_code == 404


def test_training_page_is_served_and_loads_local_assets_only(db_path):
    response = make_client(db_path).get("/entrainement")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="board"' in html and 'type="module" src="/static/training.js"' in html
    assert "http://" not in html and "https://" not in html
    assert make_client(db_path).get("/static/training.js").status_code == 200


def test_root_redirects_to_training(db_path):
    response = make_client(db_path).get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/entrainement")


@pytest.mark.parametrize("path,label", [
    ("/entrainement", "Entraînement"), ("/rapport", "Rapport"), ("/repertoire", "Répertoire"), ("/coach", "Coach"),
])
def test_every_page_has_the_menu_and_marks_itself_active(db_path, path, label):
    html = make_client(db_path).get(path).get_data(as_text=True)
    for href in ("/entrainement", "/rapport", "/repertoire", "/coach"):
        assert f'href="{href}"' in html
    assert f'href="{path}" class="active"' in html
    assert "http://" not in html and "https://" not in html


def test_next_exercise_includes_date_and_players(db_path):
    exercise = make_client(db_path).get("/api/exercise/next").get_json()["exercise"]
    assert len(exercise["played_at"]) == 20
    assert exercise["white"]["name"] and exercise["black"]["name"]
    assert {"elo"} <= set(exercise["white"])
    assert exercise["source"] in ("lichess", "chesscom")


def test_next_exercise_includes_cadence_fields(db_path):
    exercise = make_client(db_path).get("/api/exercise/next").get_json()["exercise"]
    assert {"speed", "time_control"} <= set(exercise)


def test_history_lists_moves_before_the_exercise_and_never_the_solution(db_path):
    conn = connect(db_path)
    gid = conn.execute("SELECT game_id FROM moves WHERE id = 1").fetchone()[0]
    conn.execute("UPDATE moves SET ply = 2 WHERE id = 1")
    conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 1, 'e4', 'e2e4', 'start-fen')",
        (gid,),
    )
    conn.execute(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before) VALUES (?, 3, 'Nf3', 'g1f3', 'later-fen')",
        (gid,),
    )
    conn.commit()
    conn.close()
    data = make_client(db_path).get("/api/exercise/1/history").get_json()
    assert data == {"sans": ["e4"], "positions": ["start-fen", START]}


def test_history_of_a_first_move_exercise_is_only_the_start_position(db_path):
    data = make_client(db_path).get("/api/exercise/1/history").get_json()
    assert data == {"sans": [], "positions": [START]}


def test_history_unknown_exercise_is_404(db_path):
    assert make_client(db_path).get("/api/exercise/99/history").status_code == 404


def test_training_page_has_the_move_list_container(db_path):
    html = make_client(db_path).get("/entrainement").get_data(as_text=True)
    assert 'id="moves"' in html and 'id="replay"' in html


def set_speed(db_path, speed):
    conn = connect(db_path)
    conn.execute("UPDATE games SET speed = ?", (speed,))
    conn.commit()
    conn.close()


def test_next_returns_remaining_count(db_path):
    assert make_client(db_path).get("/api/exercise/next").get_json()["remaining"] == 1


def test_speed_filter_keeps_matching_exercises_only(db_path):
    set_speed(db_path, "blitz")
    client = make_client(db_path)
    kept = client.get("/api/exercise/next?speed=blitz&speed=rapid").get_json()
    assert kept["exercise"]["move_id"] == 1 and kept["remaining"] == 1
    excluded = client.get("/api/exercise/next?speed=bullet").get_json()
    assert excluded == {"exercise": None, "remaining": 0}


def test_unknown_speed_is_rejected(db_path):
    assert make_client(db_path).get("/api/exercise/next?speed=daily").status_code == 400


def test_training_page_has_the_speed_filter_buttons_pressed_by_default(db_path):
    html = make_client(db_path).get("/entrainement").get_data(as_text=True)
    for speed in ("bullet", "blitz", "rapid"):
        assert f'data-speed="{speed}" aria-pressed="true"' in html
    assert 'id="counter"' in html


def test_report_page_without_analyzed_games_says_no_data(tmp_path):
    path = tmp_path / "empty.db"
    connect(path).close()
    html = make_client(path).get("/rapport").get_data(as_text=True)
    assert "Aucune donnée" in html


def test_report_page_shows_a_section_per_speed(db_path):
    html = make_client(db_path).get("/rapport").get_data(as_text=True)
    assert "<h2>Bullet</h2>" in html
    assert "1 partie, 1 coup analysé" in html
    assert "Aucun groupe assez grand" in html


def test_report_page_has_a_radar_with_the_six_axes(db_path):
    html = make_client(db_path).get("/rapport").get_data(as_text=True)
    assert 'class="radar"' in html
    for label in ("Ouverture", "Milieu de partie", "Finale", "Conversion", "Résilience", "Gestion du temps"):
        assert label in html


def test_repertoire_page_has_the_board_and_filters(db_path):
    html = make_client(db_path).get("/repertoire").get_data(as_text=True)
    assert 'id="board"' in html and 'data-color="black"' in html and 'src="/static/repertoire.js"' in html
    assert "http://" not in html and "https://" not in html


def test_repertoire_moves_lists_my_first_move(db_path):
    data = make_client(db_path).get("/api/repertoire/moves?color=white").get_json()
    assert data["mine"] is True and data["total"] == 1
    assert [(m["san"], m["games"], m["win"], m["later_errors"]) for m in data["moves"]] == [("a3", 1, 1, 1)]


def test_repertoire_moves_rejects_bad_input(db_path):
    client = make_client(db_path)
    assert client.get("/api/repertoire/moves?color=green").status_code == 400
    assert client.get("/api/repertoire/moves?speed=daily").status_code == 400
    assert client.get("/api/repertoire/moves?fen=nonsense").status_code == 400


def coach_client(db_path):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    return web.create_app({"storage": {"db_path": str(db_path)}}, None, lambda: now).test_client()


def test_coach_page_shows_the_weekly_plan_and_advice(db_path):
    set_speed(db_path, "bullet")
    html = coach_client(db_path).get("/coach?speed=bullet").get_data(as_text=True)
    assert "Semaine du 2026-10-26" in html
    assert "Résoudre 1 exercice en Bullet" in html and "Jouer 5 parties en Bullet" in html
    assert "Conseils" in html and 'src="/static/coach.js"' in html


def test_coach_page_without_data_for_a_speed_says_so(db_path):
    html = coach_client(db_path).get("/coach?speed=rapid").get_data(as_text=True)
    assert "Aucune donnée" in html


def test_coach_rejects_an_unknown_speed(db_path):
    assert coach_client(db_path).get("/coach?speed=daily").status_code == 400


def test_coach_check_is_stored_and_can_be_undone(db_path):
    client = coach_client(db_path)
    body = {"speed": "bullet", "task": "axis:opening", "done": True}
    assert client.post("/api/coach/check", json=body).get_json() == {"task": "axis:opening", "done": True}
    conn = connect(db_path)
    rows = [tuple(r) for r in conn.execute("SELECT week, speed, task, done FROM coach_checks")]
    assert rows == [("2026-10-26", "bullet", "axis:opening", 1)]
    client.post("/api/coach/check", json={**body, "done": False})
    assert [r[0] for r in conn.execute("SELECT done FROM coach_checks")] == [0]
    conn.close()


@pytest.mark.parametrize("body", [
    {"speed": "daily", "task": "axis:time", "done": True},
    {"speed": "bullet", "task": "exercises", "done": True},
    {"speed": "bullet", "task": "axis:time", "done": "yes"},
    {"speed": "bullet", "task": "axis:time"},
    None,
])
def test_coach_check_rejects_bad_input(db_path, body):
    assert coach_client(db_path).post("/api/coach/check", json=body).status_code == 400


def test_serve_warms_the_report_cache_before_listening(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(web, "cached_report_data", lambda conn: order.append("warm"))
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: order.append("run"))
    web.serve({"storage": {"db_path": str(tmp_path / "w.db")}}, analyzer_factory=lambda *a: None)
    assert order == ["warm", "run"]


def test_serve_survives_a_failing_warm_up(monkeypatch, tmp_path, capsys):
    def boom(conn):
        raise RuntimeError("broken")

    monkeypatch.setattr(web, "cached_report_data", boom)
    monkeypatch.setattr(web.Flask, "run", lambda self, **kwargs: None)
    web.serve({"storage": {"db_path": str(tmp_path / "w.db")}}, analyzer_factory=lambda *a: None)
    assert "Report cache not warmed: broken" in capsys.readouterr().err


DEFAULT_PREFS = {
    "speeds": ["bullet", "blitz", "rapid"], "accounts": {"lichess": "", "chesscom": ""}, "import_limit": 50, "depth": 16,
    "import_speeds": ["bullet", "blitz", "rapid"], "theme": "dark", "language": "fr", "stockfish_path": "",
}


def test_preferences_default_to_all_speeds(db_path):
    assert make_client(db_path).get("/api/preferences").get_json() == DEFAULT_PREFS


def test_preferences_are_saved_in_canonical_order_and_survive_reconnect(db_path):
    client = make_client(db_path)
    response = client.put("/api/preferences", json={"speeds": ["rapid", "bullet", "bullet"]})
    assert response.get_json() == {**DEFAULT_PREFS, "speeds": ["bullet", "rapid"]}
    assert make_client(db_path).get("/api/preferences").get_json() == {**DEFAULT_PREFS, "speeds": ["bullet", "rapid"]}


@pytest.mark.parametrize("body", [
    {"speeds": []}, {"speeds": ["daily"]}, {"speeds": "bullet"}, {"font": "mono"}, [], None,
    {"accounts": {"twitch": "me"}}, {"accounts": {"lichess": "a b"}}, {"accounts": {"lichess": 3}}, {"accounts": []},
    {"import_limit": 0}, {"import_limit": 501}, {"import_limit": "50"}, {"import_limit": True},
    {"import_speeds": []}, {"import_speeds": ["daily"]}, {"import_speeds": "bullet"},
    {"theme": "blue"}, {"theme": None}, {"theme": 1},
    {"language": "de"}, {"language": None}, {"language": 1},
    {"stockfish_path": "/no/such/stockfish"}, {"stockfish_path": 3}, {"stockfish_path": None},
    {"depth": 13}, {"depth": 17}, {"depth": "16"}, {"depth": True}, {"depth": None},
])
def test_invalid_preferences_are_rejected(db_path, body):
    client = make_client(db_path)
    assert client.put("/api/preferences", json=body).status_code == 400
    assert client.get("/api/preferences").get_json() == DEFAULT_PREFS


def test_banner_links_to_the_account_page_on_every_page(db_path):
    for path in ("/entrainement", "/rapport", "/repertoire", "/coach", "/compte"):
        html = make_client(db_path).get(path).get_data(as_text=True)
        assert '<a class="profile" href="/compte"' in html and 'href="/compte">Réglages</a>' in html.replace(' class="active" aria-current="page"', "")


def test_banner_shows_the_stored_username_and_a_default_without_one(db_path):
    client = make_client(db_path)
    assert '<span class="profile-name">Profil</span>' in client.get("/rapport").get_data(as_text=True)
    client.put("/api/preferences", json={"accounts": {"chesscom": "magnus"}})
    html = client.get("/rapport").get_data(as_text=True)
    assert '<span class="profile-name">magnus</span>' in html and '<span class="avatar">M</span>' in html


def test_hidden_speeds_leave_the_filters_report_and_coach(db_path):
    set_speed(db_path, "bullet")
    client = make_client(db_path)
    client.put("/api/preferences", json={"speeds": ["blitz", "rapid"]})
    for path in ("/entrainement", "/repertoire"):
        html = client.get(path).get_data(as_text=True)
        assert 'data-speed="bullet"' not in html and 'data-speed="blitz"' in html
    assert "<h2>Bullet</h2>" not in client.get("/rapport").get_data(as_text=True)
    coach = client.get("/coach?speed=bullet").get_data(as_text=True)
    assert "speed=bullet" not in coach and "speed=blitz" in coach


def test_accounts_and_limit_are_saved_and_merged(db_path):
    client = make_client(db_path)
    client.put("/api/preferences", json={"accounts": {"lichess": "magnus"}, "import_limit": 20})
    body = client.put("/api/preferences", json={"accounts": {"chesscom": "hikaru"}}).get_json()
    assert body["accounts"] == {"lichess": "magnus", "chesscom": "hikaru"} and body["import_limit"] == 20
    assert client.put("/api/preferences", json={"accounts": {"lichess": ""}}).get_json()["accounts"]["lichess"] == ""


def test_stored_account_names_the_profile_and_fills_the_field(db_path):
    client = make_client(db_path)
    client.put("/api/preferences", json={"accounts": {"chesscom": "stored"}})
    assert 'class="profile-name">stored<' in client.get("/rapport").get_data(as_text=True)
    assert 'name="chesscom" value="stored"' in client.get("/compte").get_data(as_text=True)


def test_depth_is_saved_and_shown_as_the_pressed_choice(db_path):
    client = make_client(db_path)
    assert client.put("/api/preferences", json={"depth": 14}).get_json()["depth"] == 14
    html = client.get("/compte").get_data(as_text=True)
    assert 'data-depth="14" aria-pressed="true"' in html and 'data-depth="16" aria-pressed="false"' in html
    assert "16 (défaut)" in html and 'data-depth="15"' in html


def test_account_page_has_every_control(db_path):
    html = make_client(db_path).get("/compte").get_data(as_text=True)
    markers = ('id="pref-accounts"', 'id="pref-limit"', 'data-source="lichess"', 'data-source="chesscom"',
               'id="pref-speeds"', 'id="reset-button"', "compte.js")
    for marker in markers:
        assert marker in html
    assert html.count('role="progressbar"') == 3 and html.count('class="secondary sync-button"') == 1 and "Importer depuis Lichess" not in html
    assert "Importer depuis Chess.com" in html and 'id="sync-button"' not in html


def test_account_page_shows_games_per_platform_and_last_date(db_path):
    html = make_client(db_path).get("/compte").get_data(as_text=True)
    assert "1 partie importée, dernière le jeu. 1 janv 2026." in html and "Aucune partie importée." in html


@pytest.mark.parametrize("value, expected", [
    ("2026-10-23T18:00:00Z", "ven. 23 oct 2026"), ("2026-10-25", "dim. 25 oct 2026"),
    ("2026-08-03T00:00:00Z", "lun. 3 août 2026"), ("2026-12-31", "jeu. 31 déc 2026"),
])
def test_french_date(value, expected):
    assert web.french_date(value) == expected


def test_import_speeds_are_saved_independently_from_displayed_speeds(db_path):
    client = make_client(db_path)
    body = client.put("/api/preferences", json={"import_speeds": ["rapid", "bullet"]}).get_json()
    assert body["import_speeds"] == ["bullet", "rapid"] and body["speeds"] == DEFAULT_PREFS["speeds"]


def test_theme_is_saved_and_applied_on_every_page(db_path):
    client = make_client(db_path)
    assert 'data-theme="dark"' in client.get("/compte").get_data(as_text=True)
    assert client.put("/api/preferences", json={"theme": "light"}).get_json()["theme"] == "light"
    for path in ("/entrainement", "/compte"):
        assert 'data-theme="light"' in make_client(db_path).get(path).get_data(as_text=True)


def english_client(db_path):
    client = make_client(db_path)
    assert client.put("/api/preferences", json={"language": "en"}).get_json()["language"] == "en"
    return client


def test_language_is_saved_and_applied_on_every_page(db_path):
    client = make_client(db_path)
    assert '<html lang="fr"' in client.get("/compte").get_data(as_text=True)
    client = english_client(db_path)
    for path in ("/entrainement", "/rapport", "/repertoire", "/coach", "/compte"):
        html = make_client(db_path).get(path).get_data(as_text=True)
        assert '<html lang="en"' in html and 'id="messages"' in html


def test_english_pages_show_english_texts_only(db_path):
    english_client(db_path)
    client = make_client(db_path)
    assert "Link your accounts" in client.get("/compte").get_data(as_text=True)
    assert "Where you make the most mistakes" in client.get("/rapport").get_data(as_text=True)
    assert "Previous move" in client.get("/repertoire").get_data(as_text=True)
    assert "Review the game" in client.get("/entrainement").get_data(as_text=True)
    for path in ("/entrainement", "/rapport", "/repertoire", "/coach", "/compte"):
        html = client.get(path).get_data(as_text=True)
        for french in ("Entraînement", "Réglages", "Aucune", "Cadences", "Parties", "Importer"):
            assert french not in html


def test_english_account_page_formats_counts_and_dates(db_path):
    english_client(db_path)
    html = make_client(db_path).get("/compte").get_data(as_text=True)
    assert "1 game imported, latest on Thu Jan 1, 2026." in html and "No game imported." in html
    assert "1 analyzed, 0 pending." in html


def test_english_coach_page_uses_english_plan_and_advice(db_path):
    set_speed(db_path, "bullet")
    client = coach_client(db_path)
    client.put("/api/preferences", json={"language": "en"})
    html = client.get("/coach?speed=bullet").get_data(as_text=True)
    assert "Week of 2026-10-26" in html and "Solve 1 exercise in Bullet" in html and "Play 5 games in Bullet" in html
    assert "Advice" in html and "serious errors" in html


def test_answer_message_is_translated(db_path):
    client = english_client(db_path)
    data = client.post("/api/exercise/1/answer", json={"move": "d2d4"}).get_json()
    assert data["message"] == "Engine unavailable: only the reference move is accepted."


def test_client_messages_are_embedded_in_the_page(db_path):
    html = english_client(db_path).get("/entrainement").get_data(as_text=True)
    assert "Select at least one speed." in html and "js.pick_speed" in html


def test_language_buttons_mark_the_current_choice(db_path):
    client = english_client(db_path)
    html = client.get("/compte").get_data(as_text=True)
    assert 'data-language="en" aria-pressed="true"' in html and 'data-language="fr" aria-pressed="false"' in html


@pytest.mark.parametrize("value, expected", [
    ("2026-10-23T18:00:00Z", "Fri Oct 23, 2026"), ("2026-12-31", "Thu Dec 31, 2026"),
])
def test_english_date(value, expected):
    from zugup.i18n import translator
    assert web.localized_date(value, translator("en")) == expected


def test_stockfish_path_is_saved_when_it_points_to_an_executable(db_path, tmp_path):
    engine = tmp_path / "stockfish"
    engine.write_text("#!/bin/sh\n")
    engine.chmod(0o755)
    client = make_client(db_path)
    assert client.put("/api/preferences", json={"stockfish_path": str(engine)}).get_json()["stockfish_path"] == str(engine)
    html = client.get("/compte").get_data(as_text=True)
    assert 'id="pref-stockfish"' in html and f"Stockfish utilisé : {engine}" in html
    assert client.put("/api/preferences", json={"stockfish_path": ""}).get_json()["stockfish_path"] == ""


def test_settings_page_says_when_stockfish_is_missing(db_path):
    assert "Stockfish est introuvable" in make_client(db_path).get("/compte").get_data(as_text=True)


def test_standalone_settings_page_hides_the_stockfish_field(db_path):
    app = web.create_app({"storage": {"db_path": str(db_path)}, "standalone": True})
    assert 'id="pref-stockfish"' not in app.test_client().get("/compte").get_data(as_text=True)
