import pytest
import requests
from click.testing import CliRunner

from conftest import FakeResponse, FakeSession, ok
from transmission_client import cli as cli_mod
from transmission_client.cli import _human_size, cli


def torrent(**kw):
    t = {"id": 1, "hashString": "abc123", "name": "Ubuntu", "status": 6, "percentDone": 0.5,
         "rateDownload": 2048, "rateUpload": 512, "totalSize": 3 * 1024 ** 3, "uploadRatio": 1.234,
         "peersConnected": 7, "downloadDir": "/dl", "error": 0, "errorString": ""}
    t.update(kw)
    return t


@pytest.fixture
def run(monkeypatch):
    """Invoke the CLI with every TransmissionClient talking to one shared FakeSession."""
    session = FakeSession()
    real_init = cli_mod.TransmissionClient.__init__

    def init(self, *a, **k):
        real_init(self, *a, **k)
        self._http = session

    monkeypatch.setattr(cli_mod.TransmissionClient, "__init__", init)

    def invoke(args, queue=None, input=None):
        session.queue = list(queue or [])
        session.posts.clear()
        return CliRunner().invoke(cli, args, input=input)

    invoke.session = session
    return invoke


@pytest.mark.parametrize("n,expected", [(0, "0.0B"), (1023, "1023.0B"), (1024, "1.0KB"), (1536, "1.5KB"),
                                        (1024 ** 2, "1.0MB"), (1024 ** 3, "1.0GB"), (1024 ** 4, "1.0TB"),
                                        (1024 ** 5, "1.0PB"), (5 * 1024 ** 6, "5120.0PB")])
def test_human_size(n, expected):
    assert _human_size(n) == expected


def test_global_options_build_the_client(run):
    r = run(["--host", "h", "--port", "1", "--user", "u", "--password", "p", "list"], [ok({"torrents": []})])
    assert r.exit_code == 0
    assert run.session.posts[0]["url"] == "http://h:1/transmission/rpc"
    assert r.output == "No torrents.\n"


def test_list_empty(run):
    r = run(["list"], [ok({"torrents": []})])
    assert r.output == "No torrents.\n"


def test_list_rows(run):
    r = run(["list"], [ok({"torrents": [torrent(), torrent(id=22, status=42, percentDone=1.0, name="Other")]})])
    lines = r.output.splitlines()
    assert lines[0].split() == ["ID", "STATUS", "DONE", "SIZE", "DOWN", "UP", "NAME"]
    assert lines[1].split() == ["1", "seeding", "50.0%", "3.0GB", "2.0KB/s", "512.0B/s", "Ubuntu"]
    assert lines[2].split()[:3] == ["22", "42", "100.0%"] and lines[2].endswith("Other")


def test_info_output(run):
    r = run(["info", "1"], [ok({"torrents": [torrent()]})])
    assert r.exit_code == 0
    assert r.output.splitlines() == [
        "Name:      Ubuntu", "ID:        1", "Hash:      abc123", "Status:    seeding", "Progress:  50.0%",
        "Size:      3.0GB", "Down/Up:   2.0KB/s / 512.0B/s", "Ratio:     1.23", "Peers:     7", "Dir:       /dl"]
    assert run.session.posts[0]["json"]["arguments"]["ids"] == [1]


def test_info_shows_error_text_when_flagged(run):
    r = run(["info", "1"], [ok({"torrents": [torrent(error=3, errorString="tracker gone")]})])
    assert r.output.splitlines()[-1] == "Error:     tracker gone"


def test_info_unknown_id_exits_1(run):
    r = run(["info", "5"], [ok({"torrents": []})])
    assert r.exit_code == 1 and "No torrent with id 5" in r.output


def test_info_requires_an_integer(run):
    assert run(["info", "x"]).exit_code == 2


@pytest.mark.parametrize("result,expected", [
    ({"torrent-added": {"id": 3, "name": "N"}}, "Added: N (id=3)\n"),
    ({"torrent-duplicate": {"id": 4, "name": "D"}}, "Added: D (id=4)\n"),
    ({}, "Torrent submitted.\n"),
])
def test_add_messages(run, result, expected):
    r = run(["add", "magnet:?x"], [ok(result)])
    assert r.output == expected


def test_add_options_are_forwarded(run):
    run(["add", "magnet:?x", "--dir", "/d", "--paused"], [ok()])
    assert run.session.posts[0]["json"]["arguments"] == {"paused": True, "download-dir": "/d", "filename": "magnet:?x"}


@pytest.mark.parametrize("cmd,word", [("start", "Started"), ("stop", "Stopped")])
def test_start_stop_many(run, cmd, word):
    r = run([cmd, "1", "2", "3"], [ok()])
    assert r.output == f"{word} 3 torrent(s).\n"
    assert run.session.posts[0]["json"]["arguments"] == {"ids": [1, 2, 3]}


@pytest.mark.parametrize("cmd", ["start", "stop", "remove"])
def test_id_arguments_are_required(run, cmd):
    assert run([cmd]).exit_code == 2


def test_remove_asks_for_confirmation(run):
    r = run(["remove", "1", "2"], [ok()], input="n\n")
    assert r.exit_code != 0 and run.session.posts == []
    r = run(["remove", "1", "2"], [ok()], input="y\n")
    assert "Removed 2 torrent(s)." in r.output
    assert run.session.posts[0]["json"]["arguments"] == {"ids": [1, 2], "delete-local-data": False}


def test_remove_delete_data_and_yes_flag(run):
    r = run(["remove", "--delete-data", "--yes", "9"], [ok()])
    assert r.exit_code == 0
    assert run.session.posts[0]["json"]["arguments"] == {"ids": [9], "delete-local-data": True}


# ------------------------------------------------------------------ main()
def test_main_reports_rpc_errors(monkeypatch, capsys):
    def boom():
        raise cli_mod.TransmissionError("denied")

    monkeypatch.setattr(cli_mod, "cli", boom)
    with pytest.raises(SystemExit) as e:
        cli_mod.main()
    assert e.value.code == 1 and "Transmission RPC error: denied" in capsys.readouterr().err


def test_main_reports_connection_errors(monkeypatch, capsys):
    def boom():
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(cli_mod, "cli", boom)
    with pytest.raises(SystemExit) as e:
        cli_mod.main()
    assert e.value.code == 1 and "Could not connect to transmission-daemon: refused" in capsys.readouterr().err


def test_main_runs_the_group(monkeypatch):
    called = []
    monkeypatch.setattr(cli_mod, "cli", lambda: called.append(1))
    cli_mod.main()
    assert called == [1]


@pytest.mark.xfail(strict=True, reason="a missing .torrent file raises FileNotFoundError, which main() does not catch "
                   "(only RPC and connection errors are reported cleanly)")
def test_adding_a_missing_torrent_file_is_reported_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["transmission-cli", "add", str(tmp_path / "missing.torrent")])
    with pytest.raises(SystemExit):
        cli_mod.main()
