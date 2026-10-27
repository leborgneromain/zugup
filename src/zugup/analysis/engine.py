import chess.engine


class Analyzer:
    def __init__(self, path, depth, threads=1, hash_mb=128):
        self.depth = depth
        self.engine = chess.engine.SimpleEngine.popen_uci(path)
        self.engine.configure({"Threads": threads, "Hash": hash_mb})

    def evaluate(self, board):
        info = self.engine.analyse(board, chess.engine.Limit(depth=self.depth))
        score = info["score"].white()
        pv = info.get("pv")
        return {
            "cp": score.score(),
            "mate": score.mate(),
            "best_uci": pv[0].uci() if pv else None,
        }

    def close(self):
        self.engine.quit()
