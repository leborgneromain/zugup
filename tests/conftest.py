import pytest

from zugup import config


@pytest.fixture(autouse=True)
def no_stockfish_detection(monkeypatch):
    monkeypatch.setattr(config, "find_stockfish", lambda: "")
