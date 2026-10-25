import base64

import pytest
import requests

from transmission_client.rpc import SESSION_ID_HEADER, TORRENT_FIELDS, TransmissionClient, TransmissionError
from conftest import FakeResponse


def test_defaults_and_env_overrides(monkeypatch):
    for var in ("TRANSMISSION_HOST", "TRANSMISSION_PORT", "TRANSMISSION_USER", "TRANSMISSION_PASS"):
        monkeypatch.delenv(var, raising=False)
    assert TransmissionClient().url == "http://localhost:9091/transmission/rpc"
    monkeypatch.setenv("TRANSMISSION_HOST", "nas")
    monkeypatch.setenv("TRANSMISSION_PORT", "1234")
    monkeypatch.setenv("TRANSMISSION_USER", "u")
    c = TransmissionClient(use_https=True, rpc_path="/rpc")
    assert c.url == "https://nas:1234/rpc"
    assert c._http.auth == ("u", "")


def test_409_handshake_stores_session_id_and_retries_once(make_client):
    c = make_client([FakeResponse(409, headers={SESSION_ID_HEADER: "abc"}),
                     FakeResponse(body={"result": "success", "arguments": {"x": 1}}),
                     FakeResponse()])
    assert c.session_stats() == {"x": 1}
    calls = c._http.calls
    assert SESSION_ID_HEADER not in calls[0]["headers"]
    assert calls[1]["headers"][SESSION_ID_HEADER] == "abc"
    assert calls[0]["json"] == calls[1]["json"]  # same payload re-sent
    c.session_stats()
    assert calls[2]["headers"][SESSION_ID_HEADER] == "abc"  # reused, no new 409
    assert calls[2]["json"]["tag"] == calls[0]["json"]["tag"] + 1


def test_non_success_result_raises(make_client):
    c = make_client([FakeResponse(body={"result": "duplicate torrent"})])
    with pytest.raises(TransmissionError, match="duplicate torrent"):
        c.session_get()


def test_http_error_raises(make_client):
    c = make_client([FakeResponse(401)])
    with pytest.raises(requests.HTTPError):
        c.session_get()


def test_session_get_fields(make_client):
    c = make_client([FakeResponse(), FakeResponse()])
    c.session_get(["version"])
    c.session_get()
    assert c._http.calls[0]["json"]["arguments"] == {"fields": ["version"]}
    assert c._http.calls[1]["json"]["arguments"] == {}


def test_torrent_get_default_fields_and_ids(make_client):
    body = {"result": "success", "arguments": {"torrents": [{"id": 1}]}}
    c = make_client([FakeResponse(body=body), FakeResponse(body=body)])
    assert c.torrent_get() == [{"id": 1}]
    assert c._http.calls[0]["json"]["arguments"] == {"fields": TORRENT_FIELDS}
    c.torrent_get(ids=[], fields=["id"])
    assert c._http.calls[1]["json"]["arguments"] == {"fields": ["id"], "ids": []}


@pytest.mark.parametrize("src", ["magnet:?xt=urn:btih:abc", "http://x/t.torrent", "https://x/t.torrent"])
def test_torrent_add_by_link_uses_filename(make_client, src):
    c = make_client()
    c.torrent_add(src, download_dir="/dl", paused=True)
    assert c._http.calls[0]["json"]["arguments"] == {"paused": True, "download-dir": "/dl", "filename": src}


def test_torrent_add_local_file_sends_base64_metainfo(make_client, tmp_path):
    f = tmp_path / "a.torrent"
    f.write_bytes(b"d4:infoe")
    c = make_client()
    c.torrent_add(str(f))
    args = c._http.calls[0]["json"]["arguments"]
    assert base64.b64decode(args["metainfo"]) == b"d4:infoe"
    assert "download-dir" not in args and args["paused"] is False


def test_torrent_remove_payload(make_client):
    c = make_client()
    c.torrent_remove([3], delete_local_data=True)
    assert c._http.calls[0]["json"] == {"method": "torrent-remove",
                                        "arguments": {"ids": [3], "delete-local-data": True}, "tag": 1}


def test_start_stop_with_ids(make_client):
    c = make_client([FakeResponse(), FakeResponse()])
    c.torrent_start([1, 2])
    c.torrent_stop([2])
    assert c._http.calls[0]["json"]["arguments"] == {"ids": [1, 2]}
    assert c._http.calls[1]["json"]["method"] == "torrent-stop"


@pytest.mark.parametrize("method", ["torrent_start", "torrent_stop"])
def test_empty_id_list_does_not_become_all_torrents(make_client, method):
    """Per rpc-spec.md an omitted `ids` means *every* torrent. An empty list
    (e.g. a filtered selection that matched nothing) must stay an empty list,
    not silently start/stop the whole daemon."""
    c = make_client()
    getattr(c, method)([])
    assert c._http.calls[0]["json"]["arguments"] == {"ids": []}
