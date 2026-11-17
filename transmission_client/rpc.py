"""Client for Transmission's RPC protocol.

Spec: https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md

The transport (``requests.Session``) is injected so the business logic can be
exercised without a network; everything that does not need I/O lives in small
pure helpers (``resolve_settings``, ``build_rpc_url``, ``encode_torrent_source``,
``check_rpc_result``, ``status_name``).
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import count
from typing import Any, Protocol

import requests

logger = logging.getLogger(__name__)

SESSION_ID_HEADER = "X-Transmission-Session-Id"
HTTP_CONFLICT = 409  # Transmission answers 409 to hand out a fresh session id

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9091
DEFAULT_RPC_PATH = "/transmission/rpc"
DEFAULT_TIMEOUT = 10.0

ENV_HOST = "TRANSMISSION_HOST"
ENV_PORT = "TRANSMISSION_PORT"
ENV_USER = "TRANSMISSION_USER"
ENV_PASS = "TRANSMISSION_PASS"

REMOTE_SOURCE_PREFIXES = ("magnet:", "http://", "https://")

TORRENT_FIELDS = [
    "id",
    "hashString",
    "name",
    "status",
    "percentDone",
    "rateDownload",
    "rateUpload",
    "eta",
    "totalSize",
    "sizeWhenDone",
    "peersConnected",
    "uploadRatio",
    "downloadDir",
    "error",
    "errorString",
    "isFinished",
]

# Transmission's torrent "status" field, per rpc-spec.md
STATUS_NAMES = {
    0: "stopped",
    1: "check-wait",
    2: "checking",
    3: "download-wait",
    4: "downloading",
    5: "seed-wait",
    6: "seeding",
}


class TransmissionError(RuntimeError):
    """Raised when the RPC server returns a non-'success' result."""


class HttpSession(Protocol):
    """The slice of ``requests.Session`` the client depends on."""

    auth: Any

    def post(self, url: str, **kwargs: Any) -> requests.Response: ...


@dataclass(frozen=True)
class ConnectionSettings:
    """Where the daemon is and how to authenticate; password may be None."""

    host: str
    port: int
    username: str | None
    password: str | None


def resolve_settings(
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ConnectionSettings:
    """Merge explicit arguments over ``TRANSMISSION_*`` environment variables and defaults."""
    env = os.environ if env is None else env
    return ConnectionSettings(
        host=host or env.get(ENV_HOST, DEFAULT_HOST),
        port=port or int(env.get(ENV_PORT, str(DEFAULT_PORT))),
        username=username or env.get(ENV_USER),
        password=password or env.get(ENV_PASS),
    )


def build_rpc_url(
    host: str, port: int, *, use_https: bool = False, rpc_path: str = DEFAULT_RPC_PATH
) -> str:
    """Return the full RPC endpoint URL, e.g. ``http://localhost:9091/transmission/rpc``."""
    scheme = "https" if use_https else "http"
    return f"{scheme}://{host}:{port}{rpc_path}"


def status_name(torrent: Mapping[str, Any]) -> str:
    """Human name for a torrent's numeric ``status``; unknown codes echo the number."""
    return STATUS_NAMES.get(torrent["status"], str(torrent["status"]))


def is_remote_source(source: str) -> bool:
    """True for magnet links and HTTP(S) URLs, False for local file paths."""
    return source.startswith(REMOTE_SOURCE_PREFIXES)


def encode_torrent_source(source: str, metainfo: bytes | None = None) -> dict[str, str]:
    """Build the ``torrent-add`` source argument.

    Remote sources go through ``filename``; local files are sent base64-encoded
    as ``metainfo`` (the raw bytes must be supplied by the caller).
    """
    if is_remote_source(source):
        return {"filename": source}
    if metainfo is None:
        raise ValueError("metainfo bytes are required for a local .torrent source")
    return {"metainfo": base64.b64encode(metainfo).decode("ascii")}


def check_rpc_result(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``arguments`` of a successful RPC envelope, else raise ``TransmissionError``."""
    if body.get("result") != "success":
        raise TransmissionError(body.get("result", "unknown error"))
    return body.get("arguments", {})


class TransmissionClient:
    """Minimal client for Transmission's session-id-protected RPC API."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        use_https: bool = False,
        rpc_path: str = DEFAULT_RPC_PATH,
        timeout: float = DEFAULT_TIMEOUT,
        http: HttpSession | None = None,
    ) -> None:
        settings = resolve_settings(host, port, username, password)
        self.host = settings.host
        self.port = settings.port
        self.username = settings.username
        self.password = settings.password
        self.url = build_rpc_url(
            self.host, self.port, use_https=use_https, rpc_path=rpc_path
        )
        self.timeout = timeout
        self._session_id: str | None = None
        self._tags = count(1)
        self._http: HttpSession = http if http is not None else requests.Session()
        if self.username:
            self._http.auth = (self.username, self.password or "")

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        headers = {SESSION_ID_HEADER: self._session_id} if self._session_id else {}
        return self._http.post(
            self.url, json=payload, headers=headers, timeout=self.timeout
        )

    def _request(
        self, method: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one RPC call, transparently retrying once on a 409 session-id challenge."""
        payload = {
            "method": method,
            "arguments": arguments or {},
            "tag": next(self._tags),
        }

        response = self._post(payload)
        if response.status_code == HTTP_CONFLICT:
            self._session_id = response.headers[SESSION_ID_HEADER]
            logger.debug("refreshed %s, retrying %s", SESSION_ID_HEADER, method)
            response = self._post(payload)

        response.raise_for_status()
        return check_rpc_result(response.json())

    # -- session ---------------------------------------------------------

    def session_get(self, fields: list[str] | None = None) -> dict[str, Any]:
        """Return daemon session settings (all, or only ``fields``)."""
        return self._request("session-get", {"fields": fields} if fields else None)

    def session_stats(self) -> dict[str, Any]:
        """Return daemon transfer statistics."""
        return self._request("session-stats")

    # -- torrents ----------------------------------------------------------

    def torrent_get(
        self, ids: list[int] | None = None, fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return torrents (all, or only ``ids``) with ``fields`` (default ``TORRENT_FIELDS``)."""
        args: dict[str, Any] = {"fields": fields or TORRENT_FIELDS}
        if ids is not None:
            args["ids"] = ids
        return self._request("torrent-get", args)["torrents"]

    def torrent_add(
        self,
        source: str,
        *,
        download_dir: str | None = None,
        paused: bool = False,
    ) -> dict[str, Any]:
        """Add a torrent from a magnet link, URL, or local .torrent file path."""
        args: dict[str, Any] = {"paused": paused}
        if download_dir:
            args["download-dir"] = download_dir

        metainfo: bytes | None = None
        if not is_remote_source(source):
            with open(source, "rb") as fh:
                metainfo = fh.read()
        args.update(encode_torrent_source(source, metainfo))

        return self._request("torrent-add", args)

    def torrent_start(self, ids: list[int] | None = None) -> None:
        """Start the given torrents (all when ``ids`` is empty/None)."""
        self._request("torrent-start", {"ids": ids} if ids else None)

    def torrent_stop(self, ids: list[int] | None = None) -> None:
        """Stop the given torrents (all when ``ids`` is empty/None)."""
        self._request("torrent-stop", {"ids": ids} if ids else None)

    def torrent_remove(
        self, ids: list[int], *, delete_local_data: bool = False
    ) -> None:
        """Remove torrents, optionally deleting their downloaded data."""
        self._request(
            "torrent-remove", {"ids": ids, "delete-local-data": delete_local_data}
        )
