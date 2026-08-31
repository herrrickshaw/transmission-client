"""Client for Transmission's RPC protocol.

Spec: https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md
"""
from __future__ import annotations

import base64
import os
from itertools import count
from typing import Any

import requests

SESSION_ID_HEADER = "X-Transmission-Session-Id"

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
        rpc_path: str = "/transmission/rpc",
        timeout: float = 10.0,
    ) -> None:
        self.host = host or os.environ.get("TRANSMISSION_HOST", "localhost")
        self.port = port or int(os.environ.get("TRANSMISSION_PORT", "9091"))
        self.username = username or os.environ.get("TRANSMISSION_USER")
        self.password = password or os.environ.get("TRANSMISSION_PASS")
        scheme = "https" if use_https else "http"
        self.url = f"{scheme}://{self.host}:{self.port}{rpc_path}"
        self.timeout = timeout
        self._session_id: str | None = None
        self._tags = count(1)
        self._http = requests.Session()
        if self.username:
            self._http.auth = (self.username, self.password or "")

    def _request(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"method": method, "arguments": arguments or {}, "tag": next(self._tags)}
        headers = {SESSION_ID_HEADER: self._session_id} if self._session_id else {}

        response = self._http.post(self.url, json=payload, headers=headers, timeout=self.timeout)

        if response.status_code == 409:
            self._session_id = response.headers[SESSION_ID_HEADER]
            headers[SESSION_ID_HEADER] = self._session_id
            response = self._http.post(self.url, json=payload, headers=headers, timeout=self.timeout)

        response.raise_for_status()
        body = response.json()
        if body.get("result") != "success":
            raise TransmissionError(body.get("result", "unknown error"))
        return body.get("arguments", {})

    # -- session ---------------------------------------------------------

    def session_get(self, fields: list[str] | None = None) -> dict[str, Any]:
        return self._request("session-get", {"fields": fields} if fields else None)

    def session_stats(self) -> dict[str, Any]:
        return self._request("session-stats")

    # -- torrents ----------------------------------------------------------

    def torrent_get(
        self, ids: list[int] | None = None, fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
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

        if source.startswith(("magnet:", "http://", "https://")):
            args["filename"] = source
        else:
            with open(source, "rb") as fh:
                args["metainfo"] = base64.b64encode(fh.read()).decode("ascii")

        return self._request("torrent-add", args)

    def torrent_start(self, ids: list[int] | None = None) -> None:
        self._request("torrent-start", {"ids": ids} if ids else None)

    def torrent_stop(self, ids: list[int] | None = None) -> None:
        self._request("torrent-stop", {"ids": ids} if ids else None)

    def torrent_remove(self, ids: list[int], *, delete_local_data: bool = False) -> None:
        self._request(
            "torrent-remove", {"ids": ids, "delete-local-data": delete_local_data}
        )
