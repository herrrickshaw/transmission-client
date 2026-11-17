from __future__ import annotations

import base64

import pytest

from transmission_client import rpc
from transmission_client.rpc import (
    SESSION_ID_HEADER,
    TORRENT_FIELDS,
    TransmissionClient,
    TransmissionError,
    build_rpc_url,
    check_rpc_result,
    encode_torrent_source,
    is_remote_source,
    resolve_settings,
    status_name,
)

from .conftest import FakeResponse

# -- pure helpers ------------------------------------------------------------


def test_resolve_settings_defaults_when_env_empty():
    s = resolve_settings(env={})
    assert (s.host, s.port, s.username, s.password) == ("localhost", 9091, None, None)


def test_resolve_settings_reads_env():
    env = {
        "TRANSMISSION_HOST": "nas",
        "TRANSMISSION_PORT": "9999",
        "TRANSMISSION_USER": "u",
        "TRANSMISSION_PASS": "p",
    }
    s = resolve_settings(env=env)
    assert (s.host, s.port, s.username, s.password) == ("nas", 9999, "u", "p")


def test_resolve_settings_explicit_args_win_over_env():
    env = {"TRANSMISSION_HOST": "nas", "TRANSMISSION_PORT": "9999"}
    s = resolve_settings(host="box", port=1, env=env)
    assert (s.host, s.port) == ("box", 1)


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({}, "http://h:9091/transmission/rpc"),
        ({"use_https": True}, "https://h:9091/transmission/rpc"),
        ({"rpc_path": "/rpc"}, "http://h:9091/rpc"),
    ],
)
def test_build_rpc_url(kwargs, expected):
    assert build_rpc_url("h", 9091, **kwargs) == expected


@pytest.mark.parametrize("code, name", [(0, "stopped"), (4, "downloading"), (6, "seeding"), (42, "42")])
def test_status_name(code, name):
    assert status_name({"status": code}) == name


@pytest.mark.parametrize(
    "source, remote",
    [("magnet:?xt=urn:btih:abc", True), ("http://x/a.torrent", True), ("https://x/a", True), ("./a.torrent", False)],
)
def test_is_remote_source(source, remote):
    assert is_remote_source(source) is remote


def test_encode_torrent_source_remote_uses_filename():
    assert encode_torrent_source("magnet:?xt=urn:btih:abc") == {"filename": "magnet:?xt=urn:btih:abc"}


def test_encode_torrent_source_local_base64s_metainfo():
    out = encode_torrent_source("a.torrent", b"\x00\x01raw")
    assert base64.b64decode(out["metainfo"]) == b"\x00\x01raw"


def test_encode_torrent_source_local_requires_bytes():
    with pytest.raises(ValueError):
        encode_torrent_source("a.torrent")


def test_check_rpc_result_returns_arguments():
    assert check_rpc_result({"result": "success", "arguments": {"a": 1}}) == {"a": 1}
    assert check_rpc_result({"result": "success"}) == {}


@pytest.mark.parametrize("body, msg", [({"result": "nope"}, "nope"), ({}, "unknown error")])
def test_check_rpc_result_raises(body, msg):
    with pytest.raises(TransmissionError, match=msg):
        check_rpc_result(body)


# -- client over a fake transport --------------------------------------------


def test_client_url_and_default_session():
    c = TransmissionClient(host="h", port=1)
    assert c.url == "http://h:1/transmission/rpc"
    assert isinstance(c._http, rpc.requests.Session)


def test_client_sets_basic_auth_only_when_username_given(session):
    TransmissionClient(host="h", port=1, http=session)
    assert session.auth is None
    TransmissionClient(host="h", port=1, username="u", http=session)
    assert session.auth == ("u", "")


def test_request_envelope_and_incrementing_tag(client, session):
    client.session_stats()
    client.session_stats()
    first, second = session.calls
    assert first["url"] == "http://daemon.test:9091/transmission/rpc"
    assert first["json"] == {"method": "session-stats", "arguments": {}, "tag": 1}
    assert second["json"]["tag"] == 2
    assert first["headers"] == {}
    assert first["timeout"] == 10.0


def test_409_challenge_is_retried_with_session_id(client, session, challenge):
    session.responses = [challenge]
    client.session_stats()
    assert len(session.calls) == 2
    assert session.calls[1]["headers"] == {SESSION_ID_HEADER: "sid-123"}
    client.session_stats()  # subsequent calls carry the id immediately
    assert session.calls[2]["headers"] == {SESSION_ID_HEADER: "sid-123"}


def test_non_success_result_raises(client, session):
    session.responses = [FakeResponse(body={"result": "invalid or corrupt torrent file"})]
    with pytest.raises(TransmissionError, match="corrupt"):
        client.session_stats()


def test_http_error_propagates(client, session):
    session.responses = [FakeResponse(500)]
    with pytest.raises(rpc.requests.HTTPError):
        client.session_stats()


def test_torrent_get_default_fields_and_ids(client, session):
    ok = FakeResponse(body={"result": "success", "arguments": {"torrents": [{"id": 1}]}})
    session.responses = [ok, ok]
    assert client.torrent_get() == [{"id": 1}]
    assert session.calls[0]["json"]["arguments"] == {"fields": TORRENT_FIELDS}
    client.torrent_get(ids=[1, 2], fields=["name"])
    assert session.calls[1]["json"]["arguments"] == {"fields": ["name"], "ids": [1, 2]}


def test_torrent_add_magnet(client, session):
    client.torrent_add("magnet:?xt=urn:btih:abc", download_dir="/dl", paused=True)
    args = session.calls[0]["json"]["arguments"]
    assert args == {"paused": True, "download-dir": "/dl", "filename": "magnet:?xt=urn:btih:abc"}


def test_torrent_add_local_file(client, session, tmp_path):
    f = tmp_path / "x.torrent"
    f.write_bytes(b"d8:announce0:e")
    client.torrent_add(str(f))
    args = session.calls[0]["json"]["arguments"]
    assert args["paused"] is False and "download-dir" not in args
    assert base64.b64decode(args["metainfo"]) == b"d8:announce0:e"


@pytest.mark.parametrize(
    "method, call, expected",
    [
        ("torrent-start", lambda c: c.torrent_start([3]), {"ids": [3]}),
        ("torrent-start", lambda c: c.torrent_start(), {}),
        ("torrent-stop", lambda c: c.torrent_stop([4, 5]), {"ids": [4, 5]}),
        ("torrent-remove", lambda c: c.torrent_remove([6]), {"ids": [6], "delete-local-data": False}),
        (
            "torrent-remove",
            lambda c: c.torrent_remove([6], delete_local_data=True),
            {"ids": [6], "delete-local-data": True},
        ),
        ("session-get", lambda c: c.session_get(["version"]), {"fields": ["version"]}),
        ("session-get", lambda c: c.session_get(), {}),
    ],
)
def test_simple_methods_send_expected_arguments(client, session, method, call, expected):
    call(client)
    assert session.calls[0]["json"]["method"] == method
    assert session.calls[0]["json"]["arguments"] == expected

