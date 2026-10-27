import socket
import sys
import time
from pathlib import Path

import pytest

from zugup import config, standalone
from zugup.web import app as web


def test_data_dir_can_be_overridden_and_is_per_user(monkeypatch, tmp_path):
    monkeypatch.setenv(standalone.DATA_DIR_ENV, str(tmp_path))
    assert standalone.data_dir() == tmp_path
    monkeypatch.delenv(standalone.DATA_DIR_ENV)
    assert standalone.data_dir().name == standalone.APP_NAME


def test_config_points_to_the_bundled_engine_and_the_data_folder(tmp_path):
    cfg = standalone.build_config(tmp_path)
    assert cfg["storage"]["db_path"] == str(tmp_path / "zugup.db")
    assert cfg["stockfish"]["path"].endswith(("stockfish", "stockfish.exe")) and cfg["standalone"] is True
    assert 1 <= cfg["analysis"]["workers"] <= config.MAX_WORKERS


@pytest.mark.parametrize("cpus, workers", [(None, 1), (1, 1), (4, 2), (12, 8), (64, 8)])
def test_workers_follow_the_cpu_count(monkeypatch, cpus, workers):
    monkeypatch.setattr(standalone.os, "cpu_count", lambda: cpus)
    assert standalone.default_workers() == workers


def test_busy_port_is_detected_and_a_free_one_is_found():
    with socket.socket() as sock:
        sock.bind((web.HOST, 0))
        busy = sock.getsockname()[1]
        assert standalone.port_is_free(busy) is False
    assert standalone.port_is_free(standalone.free_port()) is True


def test_main_serves_on_the_default_port_and_creates_the_data_folder(monkeypatch, tmp_path):
    served = []
    monkeypatch.setenv(standalone.DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.setenv(standalone.NO_BROWSER_ENV, "1")
    monkeypatch.setattr(standalone, "port_is_free", lambda port: True)
    monkeypatch.setattr(web, "serve", lambda cfg, port: served.append((cfg["standalone"], port)))
    assert standalone.main() == 0
    assert served == [(True, web.DEFAULT_PORT)] and (tmp_path / "data").is_dir()


def test_main_reuses_a_running_instance_instead_of_starting_a_second(monkeypatch, tmp_path):
    monkeypatch.setenv(standalone.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(standalone.NO_BROWSER_ENV, "1")
    monkeypatch.setattr(standalone, "port_is_free", lambda port: False)
    monkeypatch.setattr(standalone, "is_zugup", lambda port: True)
    monkeypatch.setattr(web, "serve", lambda *a: pytest.fail("a second server must not start"))
    assert standalone.main() == 0


def test_main_falls_back_to_a_free_port_when_another_program_uses_the_default(monkeypatch, tmp_path):
    ports = []
    monkeypatch.setenv(standalone.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(standalone.NO_BROWSER_ENV, "1")
    monkeypatch.setattr(standalone, "port_is_free", lambda port: False)
    monkeypatch.setattr(standalone, "is_zugup", lambda port: False)
    monkeypatch.setattr(standalone, "free_port", lambda: 9999)
    monkeypatch.setattr(web, "serve", lambda cfg, port: ports.append(port))
    standalone.main()
    assert ports == [9999]


def test_main_logs_the_crash_and_reports_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(standalone.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(standalone.NO_BROWSER_ENV, "1")
    monkeypatch.setattr(standalone, "port_is_free", lambda port: True)
    monkeypatch.setattr(web, "serve", lambda *a: 1 / 0)
    assert standalone.main() == 1
    assert "ZeroDivisionError" in capsys.readouterr().err


def test_quit_is_only_available_in_standalone_mode(tmp_path, monkeypatch):
    db_path = tmp_path / "quit.db"
    stops = []
    plain = web.create_app({"storage": {"db_path": str(db_path)}}).test_client()
    assert plain.post("/api/quit").status_code == 404
    app = web.create_app({"storage": {"db_path": str(db_path)}, "standalone": True})
    app.config["STOP"] = lambda: stops.append(1)
    monkeypatch.setattr(web, "QUIT_DELAY", 0)
    client = app.test_client()
    assert 'id="quit-button"' in client.get("/compte").get_data(as_text=True)
    assert client.post("/api/quit").status_code == 200
    time.sleep(0.2)
    assert stops == [1]
    assert 'id="quit-button"' not in plain.get("/compte").get_data(as_text=True)


def test_standalone_serve_uses_a_stoppable_server(tmp_path, monkeypatch):
    events = []

    class FakeServer:
        def shutdown(self):
            events.append("shutdown")

        def serve_forever(self):
            events.append("serving")

    monkeypatch.setattr(web, "make_server", lambda host, port, app, threaded: events.append((host, port, threaded)) or FakeServer())
    monkeypatch.setattr(web, "auto_resume", lambda app, cfg: None)
    monkeypatch.setattr(web, "warm_cache", lambda cfg: None)
    web.serve({"storage": {"db_path": str(tmp_path / "s.db")}, "standalone": True}, 9100, analyzer_factory=lambda *a: None)
    assert events == [("127.0.0.1", 9100, False), "serving"]


def test_stockfish_license_files_are_shipped_with_the_bundle(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import build_standalone
    binary = tmp_path / "stockfish"
    binary.write_text("engine")
    folder = build_standalone.stage_stockfish(binary, tmp_path / "stage")
    assert {p.name for p in folder.iterdir()} == {"stockfish", "Copying.txt", "AUTHORS", "NOTICE.md"}
    assert "GNU GENERAL PUBLIC LICENSE" in (folder / "Copying.txt").read_text()


def test_bundle_carries_the_license_files(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import build_standalone
    args = build_standalone.pyinstaller_args(tmp_path / "stage", tmp_path / "work")
    data = [a for a in args if "LICENSE" in a or a.endswith("licenses")]
    assert len(data) == 2
    assert (build_standalone.ROOT / "third_party" / "THIRD_PARTY.md").is_file()
    assert (build_standalone.ROOT / "third_party" / "SOURCE_OFFER.md").is_file()
