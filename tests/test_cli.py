from __future__ import annotations

import pytest
from click.testing import CliRunner

from transmission_client import cli as cli_mod
from transmission_client.cli import LIST_HEADER, _human_size, cli, format_info_lines, format_list_line
from transmission_client.rpc import TransmissionError

TORRENT = {
    "id": 7,
    "hashString": "abc123",
    "name": "ubuntu.iso",
    "status": 4,
    "percentDone": 0.5,
    "rateDownload": 1024 * 1024,
    "rateUpload": 2048,
    "totalSize": 3 * 1024**3,
    "uploadRatio": 1.2345,
    "peersConnected": 12,
    "downloadDir": "/dl",
    "error": 0,
    "errorString": "",
}


class FakeClient:
    """Records calls; returns canned torrents."""

    def __init__(self, torrents=None, add_result=None):
        self.torrents = torrents if torrents is not None else [TORRENT]
        self.add_result = add_result if add_result is not None else {}
        self.calls = []

    def torrent_get(self, ids=None, fields=None):
        self.calls.append(("get", ids))
        return [t for t in self.torrents if ids is None or t["id"] in ids]

    def torrent_add(self, source, *, download_dir=None, paused=False):
        self.calls.append(("add", source, download_dir, paused))
        return self.add_result

    def torrent_start(self, ids=None):
        self.calls.append(("start", ids))

    def torrent_stop(self, ids=None):
        self.calls.append(("stop", ids))

    def torrent_remove(self, ids, *, delete_local_data=False):
        self.calls.append(("remove", ids, delete_local_data))


def run(fake, *args, **kwargs):
    return CliRunner().invoke(cli, list(args), obj=fake, catch_exceptions=False, **kwargs)


# -- pure formatters -----------------------------------------------------------


@pytest.mark.parametrize(
    "n, text",
    [(0, "0.0B"), (1023, "1023.0B"), (1024, "1.0KB"), (1536, "1.5KB"), (1024**3, "1.0GB"), (1024**5 * 2, "2.0PB")],
)
def test_human_size(n, text):
    assert _human_size(n) == text


def test_format_list_line_is_fixed_width():
    line = format_list_line(TORRENT)
    assert line == "   7  downloading    50.0%      3.0GB    1.0MB/s    2.0KB/s  ubuntu.iso"
    assert len(LIST_HEADER.split("NAME")[0]) == len(line.split("ubuntu.iso")[0])


def test_format_info_lines_omit_error_when_clean():
    lines = format_info_lines(TORRENT)
    assert lines[0] == "Name:      ubuntu.iso"
    assert "Ratio:     1.23" in lines
    assert not any(line.startswith("Error:") for line in lines)


def test_format_info_lines_show_error():
    lines = format_info_lines({**TORRENT, "error": 3, "errorString": "tracker down"})
    assert lines[-1] == "Error:     tracker down"


# -- commands over a fake client ------------------------------------------------


def test_list_empty():
    assert run(FakeClient(torrents=[]), "list").output == "No torrents.\n"


def test_list_prints_header_and_rows():
    out = run(FakeClient(), "list").output.splitlines()
    assert out[0] == LIST_HEADER
    assert out[1] == format_list_line(TORRENT)


def test_info_found():
    result = run(FakeClient(), "info", "7")
    assert result.exit_code == 0
    assert result.output.splitlines() == format_info_lines(TORRENT)


def test_info_missing_exits_1():
    result = run(FakeClient(), "info", "99")
    assert result.exit_code == 1
    assert "No torrent with id 99" in result.output


def test_add_reports_added_or_duplicate():
    fake = FakeClient(add_result={"torrent-added": {"name": "x", "id": 3}})
    result = run(fake, "add", "magnet:?xt=urn:btih:abc", "--dir", "/dl", "--paused")
    assert result.output == "Added: x (id=3)\n"
    assert fake.calls == [("add", "magnet:?xt=urn:btih:abc", "/dl", True)]

    fake = FakeClient(add_result={"torrent-duplicate": {"name": "y", "id": 4}})
    assert run(fake, "add", "magnet:?x").output == "Added: y (id=4)\n"

    assert run(FakeClient(add_result={}), "add", "magnet:?x").output == "Torrent submitted.\n"


def test_start_stop_remove():
    fake = FakeClient()
    assert run(fake, "start", "1", "2").output == "Started 2 torrent(s).\n"
    assert run(fake, "stop", "3").output == "Stopped 1 torrent(s).\n"
    assert run(fake, "remove", "4", "--delete-data", "--yes").output == "Removed 1 torrent(s).\n"
    assert fake.calls == [("start", [1, 2]), ("stop", [3]), ("remove", [4], True)]


def test_remove_aborts_without_confirmation():
    fake = FakeClient()
    result = run(fake, "remove", "4", input="n\n")
    assert result.exit_code == 1
    assert fake.calls == []


def test_group_builds_client_from_flags(monkeypatch):
    captured = {}

    def fake_ctor(**kwargs):
        captured.update(kwargs)
        return FakeClient(torrents=[])

    monkeypatch.setattr(cli_mod, "TransmissionClient", fake_ctor)
    CliRunner().invoke(cli, ["--host", "nas", "--port", "1", "--user", "u", "--password", "p", "list"])
    assert captured == {"host": "nas", "port": 1, "username": "u", "password": "p"}


def test_main_maps_rpc_error_to_exit_1(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise TransmissionError("bad")

    monkeypatch.setattr(cli_mod, "cli", boom)
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    assert "Transmission RPC error: bad" in capsys.readouterr().err


def test_main_maps_connection_error_to_exit_1(monkeypatch, capsys):
    def boom(*_a, **_k):
        raise cli_mod.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(cli_mod, "cli", boom)
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    assert "Could not connect" in capsys.readouterr().err
