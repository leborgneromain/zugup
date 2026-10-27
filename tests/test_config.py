from zugup import config


FIND = config.find_stockfish


def make_engine(folder, name="stockfish"):
    path = folder / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return str(path)


def test_default_config_needs_no_file():
    cfg = config.default_config()
    assert cfg["storage"]["db_path"].endswith("data/zugup.db") and cfg["stockfish"]["path"] == ""
    assert 1 <= cfg["analysis"]["workers"] <= config.MAX_WORKERS


def test_detection_prefers_the_environment_then_the_path(tmp_path, monkeypatch):
    on_path = tmp_path / "bin"
    on_path.mkdir()
    path_engine = make_engine(on_path)
    env_engine = make_engine(tmp_path, "from-env")
    monkeypatch.setenv("PATH", str(on_path))
    monkeypatch.setattr(config, "STOCKFISH_LOCATIONS", ())
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    assert FIND() == path_engine
    monkeypatch.setenv(config.STOCKFISH_ENV, env_engine)
    assert FIND() == env_engine


def test_detection_returns_nothing_when_no_engine_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(config, "STOCKFISH_LOCATIONS", ())
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    assert FIND() == ""


def test_engine_path_prefers_the_stored_path_then_the_config_then_detection(monkeypatch):
    monkeypatch.setattr(config, "find_stockfish", lambda: "/detected")
    assert config.engine_path({"stockfish": {"path": "/bundled"}}, "/stored") == "/stored"
    assert config.engine_path({"stockfish": {"path": "/bundled"}}) == "/bundled"
    assert config.engine_path({}) == "/detected"


def test_usable_requires_an_executable_file(tmp_path):
    engine = make_engine(tmp_path)
    plain = tmp_path / "plain"
    plain.write_text("x")
    assert config.usable(engine) and not config.usable(str(plain)) and not config.usable("") and not config.usable(str(tmp_path))
