import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from transmission_client.rpc import TransmissionClient


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {"result": "success", "arguments": {}}
        self.headers = headers or {}

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._body


class FakeSession:
    """Stands in for requests.Session: replays queued responses and records the posts."""

    def __init__(self):
        self.queue = []
        self.posts = []
        self.auth = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": dict(headers or {}), "timeout": timeout})
        return self.queue.pop(0) if self.queue else FakeResponse()


def ok(arguments=None):
    return FakeResponse(200, {"result": "success", "arguments": arguments or {}})


@pytest.fixture
def client(monkeypatch):
    for k in ("TRANSMISSION_HOST", "TRANSMISSION_PORT", "TRANSMISSION_USER", "TRANSMISSION_PASS"):
        monkeypatch.delenv(k, raising=False)
    c = TransmissionClient()
    c._http = FakeSession()
    return c
