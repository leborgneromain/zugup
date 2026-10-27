import threading

from zugup.analysis import runner
from zugup.analysis.classify import classify_stored_game
from zugup.config import engine_path
from zugup.importers import chesscom, lichess
from zugup.storage.db import connect, get_credential, pending_games, unclassified_games
from zugup.web import preferences

IDLE = {"state": "idle", "source": None, "step": None, "analyzed": 0, "total": 0, "error": None}


RESUME = "resume"


class SyncError(Exception):
    pass


def count_games(conn):
    return conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]


class SyncJob:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.thread = None
        self.baseline = 0
        self.depth = preferences.DEFAULTS["depth"]
        self.stockfish_path = ""
        self.state = dict(IDLE)

    def update(self, **changes):
        with self.lock:
            self.state.update(changes)

    def start(self, conn, source, name, limit):
        with self.lock:
            if self.state["state"] == "running":
                return False
            self.state = {**IDLE, "state": "running", "source": source}
        self.baseline = count_games(conn)
        stored = preferences.load(conn)
        self.depth = stored["depth"]
        self.import_speeds = stored["import_speeds"]
        self.stockfish_path = stored["stockfish_path"]
        self.thread = threading.Thread(target=self.run, args=(source, name, limit), daemon=True)
        self.thread.start()
        return True

    def running(self):
        with self.lock:
            return self.state["state"] == "running"

    def status(self, conn):
        with self.lock:
            state = dict(self.state)
        state["added"] = count_games(conn) - self.baseline if state["state"] != "idle" else 0
        return state

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)

    def run(self, source, name, limit):
        conn = connect(self.cfg["storage"]["db_path"])
        try:
            if source != RESUME:
                self.import_games(conn, source, name, limit)
            self.analyze(conn, limit)
            self.update(state="done", step=None)
        except Exception as exc:
            self.update(state="error", step=None, error=str(exc) or type(exc).__name__)
        finally:
            conn.close()

    def import_games(self, conn, source, name, limit):
        self.update(step=f"import_{source}")
        if source == "lichess":
            credential = get_credential(conn, "lichess")
            if credential is None:
                raise SyncError("Lichess account is not connected")
            lichess.import_games(conn, credential["username"], credential["token"], limit, speeds=self.import_speeds)
        else:
            chesscom.import_games(conn, name, limit, speeds=self.import_speeds)

    def classify_leftovers(self, conn):
        leftovers = unclassified_games(conn)
        if leftovers:
            self.update(step="classify", total=len(leftovers))
        for game_id in leftovers:
            classify_stored_game(conn, game_id)

    def resume_if_needed(self, conn):
        path = engine_path(self.cfg, preferences.load(conn)["stockfish_path"])
        if not path or not (pending_games(conn, 1) or unclassified_games(conn)):
            return False
        return self.start(conn, RESUME, None, None)

    def analyze(self, conn, limit):
        self.classify_leftovers(conn)
        sf = self.cfg.get("stockfish") or {}
        path = engine_path(self.cfg, self.stockfish_path)
        if not path:
            raise SyncError("Stockfish is not configured")
        self.update(step="analyze", total=len(pending_games(conn, limit)))

        def on_game(game_id, stats):
            classify_stored_game(conn, game_id)
            self.update(analyzed=stats["analyzed"])

        workers = self.cfg.get("analysis", {}).get("workers", 1)
        runner.run(
            conn, path, self.depth, sf.get("threads", 1), sf.get("hash_mb", 128),
            workers, limit, on_game=on_game,
        )
