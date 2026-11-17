import pytest

from transmission_client.rpc import TransmissionError
from transmission_client.web import create_app


class Stub:
    def __init__(self):
        self.calls = []

    def torrent_get(self):
        return [{"id": 1, "status": 6}, {"id": 2, "status": 42}]

    def torrent_add(self, source, download_dir=None):
        self.calls.append(("add", source, download_dir))
        return {"torrent-added": {"id": 9}}

    def torrent_start(self, ids):
        self.calls.append(("start", ids))

    def torrent_stop(self, ids):
        self.calls.append(("stop", ids))

    def torrent_remove(self, ids, delete_local_data=False):
        self.calls.append(("remove", ids, delete_local_data))


@pytest.fixture
def app_client():
    stub = Stub()
    app = create_app(stub)
    return app.test_client(), stub


def test_list_adds_status_names(app_client):
    c, _ = app_client
    data = c.get("/api/torrents").get_json()
    assert [t["statusName"] for t in data] == ["seeding", "42"]


def test_add_requires_source(app_client):
    c, stub = app_client
    assert c.post("/api/torrents", json={"source": "  "}).status_code == 400
    r = c.post("/api/torrents", json={"source": " magnet:?a ", "downloadDir": ""})
    assert r.status_code == 201
    assert stub.calls == [("add", "magnet:?a", None)]


def test_start_stop_remove_routes(app_client):
    c, stub = app_client
    c.post("/api/torrents/5/start")
    c.post("/api/torrents/5/stop")
    c.delete("/api/torrents/5?deleteData=TRUE")
    c.delete("/api/torrents/6")
    assert stub.calls == [("start", [5]), ("stop", [5]), ("remove", [5], True), ("remove", [6], False)]


def test_rpc_error_maps_to_502():
    class Failing(Stub):
        def torrent_get(self):
            raise TransmissionError("boom")
    r = create_app(Failing()).test_client().get("/api/torrents")
    assert r.status_code == 502 and r.get_json() == {"error": "boom"}


def test_add_rejects_non_json_content_type(app_client):
    """A text/plain POST is a CORS 'simple request' any web page can send
    without a preflight. Accepting it (get_json(force=True)) lets a hostile
    site add arbitrary torrents to the local daemon via the GUI (CSRF)."""
    c, stub = app_client
    r = c.post("/api/torrents", data='{"source": "magnet:?evil"}', content_type="text/plain")
    assert r.status_code in (400, 415)
    assert stub.calls == []
