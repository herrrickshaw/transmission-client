# transmission-client

A CLI and a web GUI for controlling `transmission-daemon` over its RPC API
(https://github.com/transmission/transmission).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Point it at your daemon via flags or environment variables (defaults:
`localhost:9091`, no auth):

```bash
export TRANSMISSION_HOST=localhost
export TRANSMISSION_PORT=9091
export TRANSMISSION_USER=...   # if RPC auth is enabled
export TRANSMISSION_PASS=...
```

If you don't already have a daemon running:

```bash
transmission-daemon --allowed ""   # allow all RPC hosts, dev only
```

## CLI

```bash
transmission-cli list
transmission-cli info <id>
transmission-cli add 'magnet:?xt=urn:btih:...'
transmission-cli add ./some.torrent --dir ~/Downloads --paused
transmission-cli start <id> [<id> ...]
transmission-cli stop <id> [<id> ...]
transmission-cli remove <id> [--delete-data]
```

Global flags (`--host`, `--port`, `--user`, `--password`) work on every
subcommand, e.g. `transmission-cli --host 192.168.1.10 list`.

## Web GUI

```bash
python3 -m transmission_client.web
```

Opens on http://127.0.0.1:5000 — lists torrents (auto-refreshing every 3s),
with add/start/stop/remove actions. Override the port with
`TRANSMISSION_WEB_PORT`.

## Library

Both the CLI and web GUI share `transmission_client.rpc.TransmissionClient`:

```python
from transmission_client import TransmissionClient

client = TransmissionClient(host="localhost", port=9091)
client.torrent_add("magnet:?xt=urn:btih:...")
for t in client.torrent_get():
    print(t["name"], t["percentDone"])
```

## Protocol notes

Uses Transmission's classic RPC envelope (`{"method", "arguments", "tag"}`)
with `X-Transmission-Session-Id` CSRF handling (409 retry) and optional HTTP
Basic auth, per `docs/rpc-spec.md` in the transmission repo.
