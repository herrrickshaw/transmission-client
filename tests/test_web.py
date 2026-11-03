from __future__ import annotations

import pytest

from transmission_client.rpc import TransmissionError
from transmission_client.web import DEFAULT_WEB_PORT, ENV_WEB_PORT, WEB_HOST, create_app

from .test_cli import TORRENT, FakeClient


class FailingClient(FakeClient):
    def torrent_get(self, ids=None, fields=None):
        raise TransmissionError("daemon says no")


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def app(fake):
    return create_app(client=fake).test_client()


def test_index_renders(app):
    res = app.get("/")
    assert res.status_code == 200
    assert b"<html" in res.data.lower()


def test_list_adds_status_name(app):
    res = app.get("/api/torrents")
    assert res.status_code == 200
    assert res.get_json()[0]["statusName"] == "downloading"
    assert res.get_json()[0]["name"] == TORRENT["name"]


def test_rpc_error_becomes_502():
    res = create_app(client=FailingClient()).test_client().get("/api/torrents")
    assert res.status_code == 502
    assert res.get_json() == {"error": "daemon says no"}


def test_add_requires_source(app, fake):
    assert app.post("/api/torrents", json={}).status_code == 400
    assert app.post("/api/torrents", json={"source": "  "}).status_code == 400
    assert fake.calls == []


def test_add_passes_source_and_dir(app, fake):
    res = app.post("/api/torrents", json={"source": "magnet:?x", "downloadDir": "/dl"})
    assert res.status_code == 201
    assert fake.calls == [("add", "magnet:?x", "/dl", False)]
    app.post("/api/torrents", json={"source": "magnet:?y", "downloadDir": ""})
    assert fake.calls[-1] == ("add", "magnet:?y", None, False)


def test_start_stop_remove(app, fake):
    assert app.post("/api/torrents/7/start").get_json() == {"ok": True}
    assert app.post("/api/torrents/7/stop").get_json() == {"ok": True}
    assert app.delete("/api/torrents/7").get_json() == {"ok": True}
    assert app.delete("/api/torrents/7?deleteData=TRUE").get_json() == {"ok": True}
    assert fake.calls == [("start", [7]), ("stop", [7]), ("remove", [7], False), ("remove", [7], True)]


def test_main_runs_on_loopback_with_env_port(monkeypatch):
    captured = {}

    class App:
        def run(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("transmission_client.web.create_app", lambda: App())
    monkeypatch.setenv(ENV_WEB_PORT, "8123")
    from transmission_client import web

    web.main()
    assert captured == {"host": WEB_HOST, "port": 8123}
    monkeypatch.delenv(ENV_WEB_PORT)
    web.main()
    assert captured["port"] == DEFAULT_WEB_PORT
