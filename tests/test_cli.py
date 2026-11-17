from click.testing import CliRunner

from transmission_client import cli as cli_mod
from transmission_client.cli import _human_size


def test_human_size_units():
    assert _human_size(0) == "0.0B"
    assert _human_size(1023) == "1023.0B"
    assert _human_size(1024) == "1.0KB"
    assert _human_size(1536 * 1024) == "1.5MB"
    assert _human_size(1024 ** 5) == "1.0PB"


class StubClient:
    def __init__(self, torrents=None, add_result=None):
        self.torrents = torrents or []
        self.add_result = add_result or {}
        self.calls = []

    def torrent_get(self, ids=None):
        self.calls.append(("get", ids))
        return [t for t in self.torrents if ids is None or t["id"] in ids]

    def torrent_add(self, source, download_dir=None, paused=False):
        self.calls.append(("add", source, download_dir, paused))
        return self.add_result

    def torrent_start(self, ids):
        self.calls.append(("start", ids))

    def torrent_stop(self, ids):
        self.calls.append(("stop", ids))

    def torrent_remove(self, ids, delete_local_data=False):
        self.calls.append(("remove", ids, delete_local_data))


T = {"id": 7, "name": "ubuntu.iso", "status": 4, "percentDone": 0.5, "totalSize": 2048,
     "rateDownload": 1024, "rateUpload": 0, "hashString": "h", "uploadRatio": 0.25,
     "peersConnected": 3, "downloadDir": "/dl", "error": 0, "errorString": ""}


def run(stub, args, input=None):
    import transmission_client.cli as m
    orig = m.TransmissionClient
    m.TransmissionClient = lambda **kw: stub
    try:
        return CliRunner().invoke(cli_mod.cli, args, input=input)
    finally:
        m.TransmissionClient = orig


def test_list_empty_and_rows():
    assert "No torrents." in run(StubClient(), ["list"]).output
    out = run(StubClient([T]), ["list"]).output
    assert "downloading" in out and " 50.0%" in out and "ubuntu.iso" in out and "1.0KB/s" in out


def test_info_missing_id_exits_1():
    r = run(StubClient([T]), ["info", "99"])
    assert r.exit_code == 1


def test_info_shows_fields():
    r = run(StubClient([T]), ["info", "7"])
    assert "Ratio:     0.25" in r.output and "Status:    downloading" in r.output


def test_add_reports_added_or_duplicate():
    r = run(StubClient(add_result={"torrent-duplicate": {"name": "x", "id": 2}}), ["add", "magnet:?a", "--paused"])
    assert "Added: x (id=2)" in r.output
    assert "Torrent submitted." in run(StubClient(), ["add", "magnet:?a"]).output


def test_start_stop_require_ids_and_remove_needs_confirmation():
    stub = StubClient()
    assert run(stub, ["start"]).exit_code != 0
    run(stub, ["start", "1", "2"])
    run(stub, ["stop", "2"])
    r = run(stub, ["remove", "3"], input="n\n")
    assert r.exit_code != 0
    run(stub, ["remove", "3", "--delete-data", "--yes"])
    assert stub.calls == [("start", [1, 2]), ("stop", [2]), ("remove", [3], True)]
