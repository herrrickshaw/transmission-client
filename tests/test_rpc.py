import base64

import pytest
import requests

from conftest import FakeResponse, FakeSession, ok
from transmission_client import rpc
from transmission_client.rpc import SESSION_ID_HEADER, TransmissionClient, TransmissionError


# ------------------------------------------------------------------ construction
def test_defaults(monkeypatch):
    for k in ("TRANSMISSION_HOST", "TRANSMISSION_PORT", "TRANSMISSION_USER", "TRANSMISSION_PASS"):
        monkeypatch.delenv(k, raising=False)
    c = TransmissionClient()
    assert c.url == "http://localhost:9091/transmission/rpc"
    assert c.timeout == 10.0 and c.username is None and c._http.auth is None


def test_environment_supplies_connection_details(monkeypatch):
    monkeypatch.setenv("TRANSMISSION_HOST", "nas")
    monkeypatch.setenv("TRANSMISSION_PORT", "9999")
    monkeypatch.setenv("TRANSMISSION_USER", "u")
    monkeypatch.setenv("TRANSMISSION_PASS", "p")
    c = TransmissionClient()
    assert c.url == "http://nas:9999/transmission/rpc"
    assert c._http.auth == ("u", "p")


def test_arguments_override_environment(monkeypatch):
    monkeypatch.setenv("TRANSMISSION_HOST", "nas")
    monkeypatch.setenv("TRANSMISSION_PORT", "9999")
    c = TransmissionClient("box", 1234, username="a", password="b", use_https=True, rpc_path="/x", timeout=3)
    assert c.url == "https://box:1234/x" and c.timeout == 3 and c._http.auth == ("a", "b")


def test_username_without_password_uses_empty_password():
    assert TransmissionClient(username="a")._http.auth == ("a", "")


# ------------------------------------------------------------------ _request
def test_request_payload_and_tag_counter(client):
    client._request("session-stats")
    client._request("x", {"a": 1})
    first, second = client._http.posts
    assert first["json"] == {"method": "session-stats", "arguments": {}, "tag": 1}
    assert second["json"] == {"method": "x", "arguments": {"a": 1}, "tag": 2}
    assert first["url"] == client.url and first["timeout"] == 10.0
    assert first["headers"] == {}


def test_request_returns_arguments_or_empty(client):
    client._http.queue = [ok({"k": 1}), FakeResponse(200, {"result": "success"})]
    assert client._request("m") == {"k": 1}
    assert client._request("m") == {}


def test_409_triggers_one_retry_with_the_session_id(client):
    client._http.queue = [FakeResponse(409, headers={SESSION_ID_HEADER: "abc"}), ok({"done": True})]
    assert client._request("m") == {"done": True}
    first, retry = client._http.posts
    assert first["headers"] == {} and retry["headers"] == {SESSION_ID_HEADER: "abc"}
    assert retry["json"] == first["json"]  # same payload and tag on retry
    # the id is remembered for later calls
    client._request("again")
    assert client._http.posts[-1]["headers"] == {SESSION_ID_HEADER: "abc"}


def test_second_409_is_an_http_error(client):
    client._http.queue = [FakeResponse(409, headers={SESSION_ID_HEADER: "a"}),
                          FakeResponse(409, headers={SESSION_ID_HEADER: "b"})]
    with pytest.raises(requests.HTTPError):
        client._request("m")
    assert len(client._http.posts) == 2


def test_http_errors_propagate(client):
    client._http.queue = [FakeResponse(500)]
    with pytest.raises(requests.HTTPError):
        client._request("m")


def test_non_success_result_raises_transmission_error(client):
    client._http.queue = [FakeResponse(200, {"result": "no such torrent"}), FakeResponse(200, {})]
    with pytest.raises(TransmissionError, match="no such torrent"):
        client._request("m")
    with pytest.raises(TransmissionError, match="unknown error"):
        client._request("m")


# ------------------------------------------------------------------ session
def test_session_get_with_and_without_fields(client):
    client.session_get()
    client.session_get(["version"])
    client.session_get([])
    a, b, c = client._http.posts
    assert a["json"]["method"] == "session-get" and a["json"]["arguments"] == {}
    assert b["json"]["arguments"] == {"fields": ["version"]}
    assert c["json"]["arguments"] == {}  # empty list is treated as "no fields filter"


def test_session_stats(client):
    client._http.queue = [ok({"torrentCount": 3})]
    assert client.session_stats() == {"torrentCount": 3}
    assert client._http.posts[0]["json"]["method"] == "session-stats"


# ------------------------------------------------------------------ torrents
def test_torrent_get_defaults_and_ids(client):
    client._http.queue = [ok({"torrents": [{"id": 1}]}), ok({"torrents": []})]
    assert client.torrent_get() == [{"id": 1}]
    assert client.torrent_get(ids=[7], fields=["id"]) == []
    a, b = client._http.posts
    assert a["json"]["arguments"] == {"fields": rpc.TORRENT_FIELDS}
    assert b["json"]["arguments"] == {"fields": ["id"], "ids": [7]}


def test_torrent_get_with_empty_ids_still_sends_the_filter(client):
    client._http.queue = [ok({"torrents": []})]
    client.torrent_get(ids=[])
    assert client._http.posts[0]["json"]["arguments"]["ids"] == []


@pytest.mark.parametrize("source", ["magnet:?xt=urn:btih:abc", "http://h/x.torrent", "https://h/x.torrent"])
def test_torrent_add_url_sources_use_filename(client, source):
    client.torrent_add(source)
    args = client._http.posts[0]["json"]["arguments"]
    assert args == {"paused": False, "filename": source}


def test_torrent_add_options(client):
    client.torrent_add("magnet:?x", download_dir="/dl", paused=True)
    assert client._http.posts[0]["json"]["arguments"] == {"paused": True, "download-dir": "/dl", "filename": "magnet:?x"}


def test_torrent_add_empty_download_dir_is_omitted(client):
    client.torrent_add("magnet:?x", download_dir="")
    assert "download-dir" not in client._http.posts[0]["json"]["arguments"]


def test_torrent_add_local_file_is_base64_metainfo(client, tmp_path):
    f = tmp_path / "a.torrent"
    f.write_bytes(b"\x00\x01binary")
    client.torrent_add(str(f))
    args = client._http.posts[0]["json"]["arguments"]
    assert base64.b64decode(args["metainfo"]) == b"\x00\x01binary" and "filename" not in args


def test_torrent_add_missing_file_raises(client, tmp_path):
    with pytest.raises(FileNotFoundError):
        client.torrent_add(str(tmp_path / "nope.torrent"))
    assert client._http.posts == []


def test_torrent_add_returns_the_arguments(client):
    client._http.queue = [ok({"torrent-added": {"id": 5, "name": "n"}})]
    assert client.torrent_add("magnet:?x") == {"torrent-added": {"id": 5, "name": "n"}}


@pytest.mark.parametrize("method,rpc_name", [("torrent_start", "torrent-start"), ("torrent_stop", "torrent-stop")])
def test_start_stop_with_ids(client, method, rpc_name):
    assert getattr(client, method)([1, 2]) is None
    p = client._http.posts[0]["json"]
    assert p["method"] == rpc_name and p["arguments"] == {"ids": [1, 2]}


@pytest.mark.parametrize("method", ["torrent_start", "torrent_stop"])
def test_start_stop_without_ids_apply_to_all_torrents(client, method):
    getattr(client, method)()
    assert client._http.posts[0]["json"]["arguments"] == {}


@pytest.mark.xfail(strict=True, reason="an explicit empty id list is falsy, so torrent_start([]) / torrent_stop([]) "
                   "send no ids, and Transmission then acts on ALL torrents")
@pytest.mark.parametrize("method", ["torrent_start", "torrent_stop"])
def test_start_stop_with_an_empty_id_list_do_not_touch_all_torrents(client, method):
    getattr(client, method)([])
    assert client._http.posts[0]["json"]["arguments"] == {"ids": []}


def test_torrent_remove(client):
    client.torrent_remove([3])
    client.torrent_remove([3, 4], delete_local_data=True)
    a, b = client._http.posts
    assert a["json"]["method"] == "torrent-remove"
    assert a["json"]["arguments"] == {"ids": [3], "delete-local-data": False}
    assert b["json"]["arguments"] == {"ids": [3, 4], "delete-local-data": True}


def test_status_names_cover_the_documented_codes():
    assert [rpc.STATUS_NAMES[i] for i in range(7)] == [
        "stopped", "check-wait", "checking", "download-wait", "downloading", "seed-wait", "seeding"]


def test_package_exports():
    import transmission_client

    assert transmission_client.TransmissionClient is TransmissionClient
    assert issubclass(transmission_client.TransmissionError, RuntimeError)
