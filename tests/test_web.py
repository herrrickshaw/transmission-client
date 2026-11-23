import pytest

from conftest import FakeResponse, ok
from transmission_client import web
from transmission_client.rpc import TransmissionClient


@pytest.fixture
def app_client(client):
    app = web.create_app(client)
    app.testing = True
    return app.test_client(), client


def queue(client, *arguments):
    client._http.queue = [ok(a) for a in arguments]


def test_index_page_renders(app_client):
    c, _ = app_client
    r = c.get("/")
    assert r.status_code == 200 and b"<html" in r.data.lower()


def test_default_client_is_built_when_none_is_given(monkeypatch):
    monkeypatch.delenv("TRANSMISSION_HOST", raising=False)
    app = web.create_app()
    assert isinstance(app.config["TRANSMISSION_CLIENT"], TransmissionClient)


def test_list_adds_status_names(app_client):
    c, client = app_client
    queue(client, {"torrents": [{"id": 1, "status": 4}, {"id": 2, "status": 99}]})
    body = c.get("/api/torrents").get_json()
    assert [t["statusName"] for t in body] == ["downloading", "99"]


def test_add_torrent(app_client):
    c, client = app_client
    queue(client, {"torrent-added": {"id": 9}})
    r = c.post("/api/torrents", json={"source": "  magnet:?x  ", "downloadDir": "/dl"})
    assert r.status_code == 201 and r.get_json() == {"torrent-added": {"id": 9}}
    sent = client._http.posts[0]["json"]["arguments"]
    assert sent["filename"] == "magnet:?x" and sent["download-dir"] == "/dl"


def test_add_torrent_blank_download_dir_is_ignored(app_client):
    c, client = app_client
    c.post("/api/torrents", json={"source": "magnet:?x", "downloadDir": ""})
    assert "download-dir" not in client._http.posts[0]["json"]["arguments"]


@pytest.mark.parametrize("body", ['{}', '{"source": ""}', '{"source": "   "}', 'null'])
def test_add_torrent_requires_a_source(app_client, body):
    c, client = app_client
    r = c.post("/api/torrents", data=body)
    assert r.status_code == 400 and r.get_json() == {"error": "source is required"}
    assert client._http.posts == []


def test_add_torrent_with_invalid_json_is_400(app_client):
    c, client = app_client
    assert c.post("/api/torrents", data="not json").status_code == 400
    assert client._http.posts == []


def test_add_torrent_accepts_json_without_a_content_type(app_client):
    c, client = app_client
    r = c.post("/api/torrents", data='{"source": "magnet:?x"}')
    assert r.status_code == 201


@pytest.mark.xfail(strict=True, reason="a JSON body that is a list (not an object) makes data.get() raise -> HTTP 500")
def test_add_torrent_with_a_json_list_body_is_a_client_error(app_client):
    c, _ = app_client
    r = c.post("/api/torrents", json=["magnet:?x"])
    assert 400 <= r.status_code < 500


def test_start_and_stop(app_client):
    c, client = app_client
    assert c.post("/api/torrents/4/start").get_json() == {"ok": True}
    assert c.post("/api/torrents/4/stop").get_json() == {"ok": True}
    methods = [p["json"]["method"] for p in client._http.posts]
    assert methods == ["torrent-start", "torrent-stop"]
    assert client._http.posts[0]["json"]["arguments"] == {"ids": [4]}


@pytest.mark.parametrize("query,expected", [("", False), ("?deleteData=true", True), ("?deleteData=TRUE", True),
                                            ("?deleteData=false", False), ("?deleteData=1", False)])
def test_remove_delete_data_flag(app_client, query, expected):
    c, client = app_client
    assert c.delete(f"/api/torrents/6{query}").get_json() == {"ok": True}
    assert client._http.posts[0]["json"]["arguments"] == {"ids": [6], "delete-local-data": expected}


def test_non_integer_ids_are_404(app_client):
    c, _ = app_client
    assert c.post("/api/torrents/abc/start").status_code == 404


def test_rpc_errors_become_502(app_client):
    c, client = app_client
    client._http.queue = [FakeResponse(200, {"result": "duplicate torrent"})]
    r = c.get("/api/torrents")
    assert r.status_code == 502 and r.get_json() == {"error": "duplicate torrent"}


def test_main_runs_the_app_on_localhost(monkeypatch):
    seen = {}
    monkeypatch.setattr(web.Flask, "run", lambda self, **kw: seen.update(kw))
    monkeypatch.setenv("TRANSMISSION_WEB_PORT", "5055")
    web.main()
    assert seen == {"host": "127.0.0.1", "port": 5055}
    monkeypatch.delenv("TRANSMISSION_WEB_PORT")
    web.main()
    assert seen["port"] == 5000
