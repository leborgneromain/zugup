import math
import os
import re
import sys
import threading
from datetime import datetime, timezone

import chess
from flask import Flask, g, jsonify, redirect, render_template, request
from werkzeug.serving import make_server

from zugup.coach.plan import build_plan, week_start
from zugup.config import engine_path, usable
from zugup.i18n import LANGUAGES, translator
from zugup.profile.repertoire import position_moves
from zugup.profile.weaknesses import cached_report_data
from zugup.puzzles.checker import check_answer, open_analyzer
from zugup.puzzles.exercises import available, get_exercise, history, next_exercise, player_ratings
from zugup.storage.db import (
    analysis_counts, connect, delete_credential, get_credential, record_attempt, reset_data, set_credential, set_check,
    source_stats, unclassified_games,
)
from zugup.web import lichess_auth, preferences
from zugup.web.jobs import SyncJob
from zugup.web.preferences import SPEEDS

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


MENU = (
    ("entrainement", "/entrainement"),
    ("rapport", "/rapport"),
    ("repertoire", "/repertoire"),
    ("coach", "/coach"),
    ("compte", "/compte"),
)
VALUE_KEYS = ("opening", "middlegame", "endgame", "white", "black")
RADAR_FLOOR = 50
RADAR_RINGS = (60, 80, 100)
RADAR_CENTER = (180, 150)
RADAR_RADIUS = 100
TASK_KEY = re.compile(r"^(axis|opening):[a-z0-9 ]{1,120}$")


def radar_point(index, count, score, scale=1.0):
    ratio = 0 if score is None else max(0, score - RADAR_FLOOR) / (100 - RADAR_FLOOR)
    angle = 2 * math.pi * index / count - math.pi / 2
    radius = RADAR_RADIUS * ratio * scale
    return (round(RADAR_CENTER[0] + radius * math.cos(angle), 1), round(RADAR_CENTER[1] + radius * math.sin(angle), 1))


def localized_date(value, t):
    day = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    return t(
        "date.full", day_name=t.raw("date.days")[day.weekday()], day=day.day,
        month=t.raw("date.months")[day.month - 1], year=day.year,
    )


def french_date(value):
    return localized_date(value, translator("fr"))


def profile_name(names, default):
    return next((name for name in names.values() if name), default)


def error(message, status):
    return jsonify({"error": message}), status


def connected_accounts(conn, names):
    credential = get_credential(conn, "lichess")
    return {**names, "lichess": credential["username"] if credential else ""}


MAX_PENDING_AUTH = 5
QUIT_DELAY = 0.3
LICHESS_NOTICES = ("connected", "refused", "failed")


def create_app(cfg, evaluate=None, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    app = Flask(__name__)
    app.config["ZUGUP"] = cfg
    sync = app.config["SYNC"] = SyncJob(cfg)
    pending_auth = {}

    def db():
        if "db" not in g:
            g.db = connect(cfg["storage"]["db_path"])
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def tr():
        if "t" not in g:
            g.t = translator(preferences.load(db())["language"])
        return g.t

    @app.context_processor
    def inject_profile():
        prefs = preferences.load(db())
        t = tr()
        names = connected_accounts(db(), prefs["accounts"])
        name = profile_name(names, t("profile.default"))
        return {
            "prefs": prefs, "accounts": names, "all_speeds": SPEEDS, "t": t, "lang": t.lang,
            "js_messages": t.client_messages(), "MENU": [(key, t(f"menu.{key}"), href) for key, href in MENU],
            "profile_name": name, "profile_initial": name[0].upper(),
        }

    @app.get("/api/preferences")
    def preferences_get():
        return jsonify(preferences.load(db()))

    @app.put("/api/preferences")
    def preferences_put():
        try:
            return jsonify(preferences.save(db(), request.get_json(silent=True)))
        except ValueError as exc:
            return error(str(exc), 400)

    @app.get("/api/sync")
    def sync_get():
        return jsonify(sync.status(db()))

    @app.post("/api/sync")
    def sync_post():
        body = request.get_json(silent=True)
        source = body.get("source") if isinstance(body, dict) else None
        if source not in preferences.SOURCES:
            return error(f"'source' must be one of {', '.join(preferences.SOURCES)}", 400)
        conn = db()
        stored = preferences.load(conn)
        name = connected_accounts(conn, stored["accounts"])[source]
        if not name:
            return error("Lichess account is not connected" if source == "lichess" else "No account configured", 400)
        if not sync.start(conn, source, name, stored["import_limit"]):
            return error("A sync is already running", 409)
        return jsonify(sync.status(conn)), 202

    @app.get("/auth/lichess")
    def lichess_connect():
        verifier, challenge, state = lichess_auth.new_challenge()
        while len(pending_auth) >= MAX_PENDING_AUTH:
            pending_auth.pop(next(iter(pending_auth)))
        pending_auth[state] = verifier
        redirect_uri = request.url_root.rstrip("/") + "/auth/lichess/callback"
        return redirect(lichess_auth.authorize_url(redirect_uri, state, challenge))

    @app.get("/auth/lichess/callback")
    def lichess_callback():
        verifier = pending_auth.pop(request.args.get("state", ""), None)
        code = request.args.get("code")
        if verifier is None or not code or request.args.get("error"):
            return redirect("/compte?lichess=refused")
        redirect_uri = request.url_root.rstrip("/") + "/auth/lichess/callback"
        try:
            token = lichess_auth.exchange_code(code, verifier, redirect_uri)
            username = lichess_auth.fetch_username(token)
        except lichess_auth.LichessAuthError:
            return redirect("/compte?lichess=failed")
        set_credential(db(), "lichess", token, username)
        return redirect("/compte?lichess=connected")

    @app.post("/api/lichess/disconnect")
    def lichess_disconnect():
        if sync.running():
            return error("A sync is running", 409)
        conn = db()
        credential = get_credential(conn, "lichess")
        if credential:
            lichess_auth.revoke(credential["token"])
            delete_credential(conn, "lichess")
        return jsonify({"connected": False})

    @app.post("/api/quit")
    def quit_post():
        if not cfg.get("standalone"):
            return error("Not available", 404)
        stop = app.config.get("STOP")
        if stop is None:
            return error("Not available", 404)
        threading.Timer(QUIT_DELAY, stop).start()
        return jsonify({"stopping": True})

    @app.get("/compte")
    def account_page():
        conn = db()
        stats = source_stats(conn)
        counts = analysis_counts(conn)
        total = sum(v["games"] for v in stats.values())
        todo = sum(c["pending"] for c in counts.values()) + len(unclassified_games(conn))
        engine = engine_path(cfg, preferences.load(conn)["stockfish_path"])
        notice = request.args.get("lichess")
        return render_template(
            "compte.html", active="compte", title=tr()("menu.compte"), stats=stats, counts=counts, total=total, todo=todo,
            depths=preferences.DEPTHS, standalone=bool(cfg.get("standalone")),
            lichess_notice=tr()(f"compte.notice.{notice}") if notice in LICHESS_NOTICES else None,
            languages=LANGUAGES, engine=engine if usable(engine) else "",
        )

    @app.post("/api/reset")
    def reset_post():
        if sync.running():
            return error("A sync is running", 409)
        return jsonify({"deleted": reset_data(db())})

    @app.template_filter("local_date")
    def local_date(value):
        return localized_date(value, tr())

    @app.template_filter("pct")
    def pct(value):
        return tr().percent(value * 100)

    @app.template_filter("score")
    def score(value):
        return tr().percent(value, 0)

    @app.template_filter("gap_label")
    def gap_label(value):
        t = tr()
        text = f"{value:+.1f}"
        return t("report.gap", value=text.replace(".", ",") if t.lang == "fr" else text)

    @app.template_global()
    def radar_polygon(axes, score=None, key="score"):
        points = [radar_point(i, len(axes), a[key] if score is None else score) for i, a in enumerate(axes)]
        return " ".join(f"{x},{y}" for x, y in points)

    app.add_template_global(radar_point, "radar_point")
    app.add_template_global(RADAR_RINGS, "RADAR_RINGS")

    @app.template_filter("value_label")
    def value_label(value):
        return tr()(f"value.{value}") if value in VALUE_KEYS else value

    def visible(sections):
        shown = preferences.load(db())["speeds"]
        return [s for s in sections if s["speed"] in shown]

    @app.get("/rapport")
    def report_page():
        return render_template(
            "report.html", active="rapport", title=tr()("menu.rapport"), sections=visible(cached_report_data(db())),
        )

    @app.get("/repertoire")
    def repertoire_page():
        return render_template("repertoire.html", active="repertoire", title=tr()("menu.repertoire"))

    @app.get("/api/repertoire/moves")
    def repertoire_route():
        color = request.args.get("color", "white")
        speeds = request.args.getlist("speed") or None
        if color not in ("white", "black"):
            return error("Unknown color, expected white or black", 400)
        if speeds is not None and not set(speeds) <= set(SPEEDS):
            return error(f"Unknown speed, expected one of {', '.join(SPEEDS)}", 400)
        fen = request.args.get("fen", chess.STARTING_FEN)
        try:
            chess.Board(fen)
        except ValueError:
            return error("Invalid FEN", 400)
        return jsonify(position_moves(db(), fen, color, speeds))

    @app.get("/")
    def index():
        return redirect("/entrainement")

    @app.get("/entrainement")
    def training_page():
        return render_template("training.html", active="entrainement", title=tr()("menu.entrainement"))

    @app.get("/coach")
    def coach_page():
        speed = request.args.get("speed")
        sections = cached_report_data(db())
        shown = preferences.load(db())["speeds"]
        if speed is not None and speed not in SPEEDS:
            return error(f"Unknown speed, expected one of {', '.join(SPEEDS)}", 400)
        if speed not in shown:
            candidates = [s for s in sections if s["speed"] in shown]
            speed = max(candidates, key=lambda x: x["games"])["speed"] if candidates else shown[0]
        return render_template(
            "coach.html", active="coach", title=tr()("menu.coach"), speeds=shown,
            plan=build_plan(db(), speed, clock(), sections, tr()),
        )

    @app.post("/api/coach/check")
    def coach_check_route():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("JSON body required", 400)
        speed, task, done = payload.get("speed"), payload.get("task"), payload.get("done")
        if speed not in SPEEDS or not isinstance(done, bool):
            return error("Fields 'speed' (bullet, blitz or rapid) and 'done' (boolean) are required", 400)
        if not isinstance(task, str) or not TASK_KEY.match(task):
            return error("Unknown task", 400)
        set_check(db(), week_start(clock()), speed, task, done)
        return jsonify({"task": task, "done": done})

    @app.get("/api/exercise/next")
    def next_route():
        speeds = request.args.getlist("speed") or None
        if speeds is not None and not set(speeds) <= set(SPEEDS):
            return error(f"Unknown speed, expected one of {', '.join(SPEEDS)}", 400)
        remaining = len(available(db(), speeds))
        exercise = next_exercise(db(), speeds=speeds)
        if exercise is None:
            return jsonify({"exercise": None, "remaining": remaining})
        white_elo, black_elo = player_ratings(exercise["pgn"])
        return jsonify({"remaining": remaining, "exercise": {
            "move_id": exercise["move_id"],
            "fen": exercise["fen_before"],
            "orientation": exercise["user_color"],
            "category": exercise["category"],
            "phase": exercise["phase"],
            "source": exercise["source"],
            "speed": exercise["speed"],
            "time_control": exercise["time_control"],
            "played_at": exercise["played_at"],
            "white": {"name": exercise["white"], "elo": white_elo},
            "black": {"name": exercise["black"], "elo": black_elo},
        }})

    @app.get("/api/exercise/<int:move_id>/history")
    def history_route(move_id):
        exercise = get_exercise(db(), move_id)
        if exercise is None:
            return error("Unknown exercise", 404)
        return jsonify(history(db(), exercise))

    @app.post("/api/exercise/<int:move_id>/answer")
    def answer_route(move_id):
        exercise = get_exercise(db(), move_id)
        if exercise is None:
            return error("Unknown exercise", 404)
        payload = request.get_json(silent=True)
        played = payload.get("move") if isinstance(payload, dict) else None
        if not isinstance(played, str):
            return error("Field 'move' (UCI string) is required", 400)
        try:
            outcome = check_answer(exercise, played, evaluate)
        except ValueError as exc:
            return error(str(exc), 400)
        record_attempt(db(), move_id, played, outcome["correct"])
        board = chess.Board(exercise["fen_before"])
        best = chess.Move.from_uci(exercise["best_uci"])
        message = tr()(outcome["message"]) if outcome["message"] else None
        return jsonify({**outcome, "message": message, "best_uci": exercise["best_uci"], "best_san": board.san(best)})

    return app


def stored_preferences(cfg):
    path = cfg.get("storage", {}).get("db_path")
    if not path:
        return dict(preferences.DEFAULTS)
    conn = connect(path)
    try:
        return preferences.load(conn)
    finally:
        conn.close()


def warm_cache(cfg):
    path = cfg.get("storage", {}).get("db_path")
    if not path:
        return
    conn = connect(path)
    try:
        cached_report_data(conn)
    except Exception as exc:
        print(f"Report cache not warmed: {exc}", file=sys.stderr)
    finally:
        conn.close()


def auto_resume(app, cfg):
    path = cfg.get("storage", {}).get("db_path")
    if not path:
        return
    conn = connect(path)
    try:
        app.config["SYNC"].resume_if_needed(conn)
    except Exception as exc:
        print(f"Analysis not resumed: {exc}", file=sys.stderr)
    finally:
        conn.close()


def serve(cfg, port=DEFAULT_PORT, analyzer_factory=open_analyzer, dev=False):
    if dev and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        app = create_app(cfg)
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.run(host=HOST, port=port, debug=False, use_reloader=True, threaded=False)
        return
    sf = cfg.get("stockfish", {})
    stored = stored_preferences(cfg)
    analyzer = analyzer_factory(
        engine_path(cfg, stored["stockfish_path"]), stored["depth"], sf.get("threads", 1), sf.get("hash_mb", 128),
    )
    if analyzer is None:
        print("Stockfish unavailable: only reference moves will be accepted.", file=sys.stderr)
    warm_cache(cfg)
    try:
        app = create_app(cfg, analyzer.evaluate if analyzer else None)
        app.config["TEMPLATES_AUTO_RELOAD"] = dev
        auto_resume(app, cfg)
        if cfg.get("standalone"):
            server = make_server(HOST, port, app, threaded=False)
            app.config["STOP"] = server.shutdown
            server.serve_forever()
        else:
            app.run(host=HOST, port=port, debug=False, use_reloader=dev, threaded=False)
    finally:
        if analyzer:
            analyzer.close()
