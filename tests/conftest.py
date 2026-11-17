"""Shared fakes: a scripted stand-in for requests.Session (no network)."""
import pytest
import requests

from transmission_client.rpc import TransmissionClient


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {"result": "success", "arguments": {}}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.auth = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": dict(headers or {}), "timeout": timeout})
        return self.responses.pop(0)


@pytest.fixture
def make_client(monkeypatch):
    for var in ("TRANSMISSION_HOST", "TRANSMISSION_PORT", "TRANSMISSION_USER", "TRANSMISSION_PASS"):
        monkeypatch.delenv(var, raising=False)

    def _make(responses=None, **kw):
        c = TransmissionClient(**kw)
        c._http = FakeHTTP(responses or [FakeResponse()])
        return c
    return _make
