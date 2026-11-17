"""Shared fakes: an in-memory HTTP session and an RPC client that never touches the network."""
from __future__ import annotations

from typing import Any

import pytest
import requests

from transmission_client.rpc import SESSION_ID_HEADER, TransmissionClient


class FakeResponse:
    def __init__(self, status_code: int = 200, body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body if body is not None else {"result": "success", "arguments": {}}
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._body


class FakeSession:
    """Records every POST; replays queued responses (default: a plain success)."""

    def __init__(self, responses: list[FakeResponse] | None = None):
        self.auth: Any = None
        self.calls: list[dict[str, Any]] = []
        self.responses = list(responses or [])

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0) if self.responses else FakeResponse()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(session: FakeSession) -> TransmissionClient:
    return TransmissionClient(host="daemon.test", port=9091, http=session)


@pytest.fixture
def challenge() -> FakeResponse:
    return FakeResponse(409, headers={SESSION_ID_HEADER: "sid-123"})
