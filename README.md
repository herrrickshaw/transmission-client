# transmission-client

<!-- how-to-use-with-ai -->
> **New here?** See [How to use this repo with AI (Claude, Gemini, ChatGPT)](HOW_TO_USE_WITH_AI.md) — clone it, paste it into an AI tool, and ask in plain English.

A small Python client for `transmission-daemon`, the headless BitTorrent daemon from
[Transmission](https://github.com/transmission/transmission). It ships three things that share one
RPC library: a `transmission-cli` command-line tool, a single-page Flask web GUI, and the
`TransmissionClient` class itself for use from your own scripts. Output is whatever the daemon
reports — torrent lists, per-torrent details, and add/start/stop/remove acknowledgements.

> Status: maintained. Talks only to a daemon you run yourself; no data is bundled or collected.

## What it does
- Speaks Transmission's RPC envelope (`{"method", "arguments", "tag"}`) over HTTP(S) with optional Basic auth.
- Handles the `X-Transmission-Session-Id` CSRF handshake: a 409 reply is retried once with the new id.
- `transmission-cli list | info | add | start | stop | remove` with `--host/--port/--user/--password` on every subcommand.
- Adds torrents from a magnet link, an HTTP(S) URL, or a local `.torrent` file (sent base64-encoded as `metainfo`).
- Web GUI on `127.0.0.1:5000` that lists torrents (auto-refresh every 3 s) with add/start/stop/remove buttons.
- A `TransmissionClient` library class with `session_get`, `session_stats`, `torrent_get/add/start/stop/remove`.

## Quick start
```bash
git clone https://github.com/herrrickshaw/transmission-client.git
cd transmission-client
python -m venv .venv && source .venv/bin/activate
pip install -e .
transmission-cli list
```

If you don't already have a daemon running:

```bash
transmission-daemon --allowed ""   # allow all RPC hosts, dev only
```

### CLI
```bash
transmission-cli list
transmission-cli info <id>
transmission-cli add 'magnet:?xt=urn:btih:...'
transmission-cli add ./some.torrent --dir ~/Downloads --paused
transmission-cli start <id> [<id> ...]
transmission-cli stop <id> [<id> ...]
transmission-cli remove <id> [--delete-data]     # asks for confirmation; --yes skips it
transmission-cli --host 192.168.1.10 list       # global flags work on every subcommand
```

### Web GUI
```bash
python3 -m transmission_client.web     # http://127.0.0.1:5000
```

### Library
```python
from transmission_client import TransmissionClient

client = TransmissionClient(host="localhost", port=9091)
client.torrent_add("magnet:?xt=urn:btih:...")
for t in client.torrent_get():
    print(t["name"], t["percentDone"])
```

## How it works

| Stage | Module | Notes |
|---|---|---|
| Resolve host/port/auth | `rpc.resolve_settings` | explicit args → `TRANSMISSION_*` env → defaults |
| Build request | `rpc.TransmissionClient._request` | JSON envelope with an incrementing `tag` |
| Transport | injected `requests.Session` (`http=` kwarg) | tests pass a fake; business logic never imports network code directly |
| Session-id handshake | `rpc.TransmissionClient._request` | on HTTP 409, store `X-Transmission-Session-Id` and resend once |
| Decode | `rpc.check_rpc_result` | non-`success` result → `TransmissionError` |
| Present | `cli.format_list_line` / `cli.format_info_lines`, `web.create_app` | pure formatters; Flask routes under `/api/torrents` |

Design decisions:
- The HTTP session is injected (`TransmissionClient(http=...)`) so every method is testable without a daemon.
- Pure helpers (`encode_torrent_source`, `status_name`, the formatters) are kept free of I/O and unit-tested directly.
- `web.create_app(client=...)` takes the client as a parameter for the same reason.
- Protocol reference: `docs/rpc-spec.md` in the Transmission repository.

## Repository layout
| Path | Purpose |
|---|---|
| `transmission_client/rpc.py` | `TransmissionClient`, `TransmissionError`, settings/URL/encoding helpers, `TORRENT_FIELDS`, `STATUS_NAMES` |
| `transmission_client/cli.py` | click CLI (`transmission-cli` console script) |
| `transmission_client/web.py` | Flask app factory and `python -m transmission_client.web` entry point |
| `transmission_client/templates/`, `static/` | the single-page GUI (HTML, CSS, vanilla JS) |
| `tests/` | pytest suite; all network calls go through an in-memory fake session |
| `graphify-out/` | generated knowledge-graph output (not source) |
| `transmission_client.egg-info/` | setuptools metadata left from an editable install |

## Configuration
| Variable | Default | Used by |
|---|---|---|
| `TRANSMISSION_HOST` | `localhost` | CLI, web, library |
| `TRANSMISSION_PORT` | `9091` | CLI, web, library |
| `TRANSMISSION_USER` | unset (no auth) | CLI, web, library |
| `TRANSMISSION_PASS` | unset | CLI, web, library |
| `TRANSMISSION_WEB_PORT` | `5000` | web GUI only |

CLI flags override the environment. Credentials are read at runtime only and are never written to
disk or committed.

## Testing
```bash
pip install -e ".[dev]"
ruff check transmission_client tests
pytest
```

## Limitations and known issues
- The web GUI binds to `127.0.0.1` with no authentication of its own; anyone who can reach that port
  can control the daemon.
- The GUI does not expose `--paused` or a download directory on add; use the CLI for those.
- Only the torrent fields in `TORRENT_FIELDS` are fetched by default; pass `fields=` to `torrent_get` for more.
- `torrent_add` reads a local `.torrent` fully into memory before sending.

## Licence
No licence file yet — all rights reserved.
