"""Command-line client for transmission-daemon's RPC API."""
from __future__ import annotations

import sys
from typing import Any

import click
import requests

from .rpc import TransmissionClient, TransmissionError, status_name

LIST_HEADER = f"{'ID':>4}  {'STATUS':<13} {'DONE':>6}  {'SIZE':>9}  {'DOWN':>9}  {'UP':>9}  NAME"


def _human_size(n: float) -> str:
    """Format a byte count as e.g. ``1.5MB`` (1024-based, one decimal)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def format_list_line(t: dict[str, Any]) -> str:
    """One fixed-width row of ``transmission-cli list`` for torrent dict ``t``."""
    return (
        f"{t['id']:>4}  {status_name(t):<13} {t['percentDone'] * 100:5.1f}%  "
        f"{_human_size(t['totalSize']):>9}  {_human_size(t['rateDownload']) + '/s':>9}  "
        f"{_human_size(t['rateUpload']) + '/s':>9}  {t['name']}"
    )


def format_info_lines(t: dict[str, Any]) -> list[str]:
    """The ``transmission-cli info`` report for torrent dict ``t``, one entry per line."""
    lines = [
        f"Name:      {t['name']}",
        f"ID:        {t['id']}",
        f"Hash:      {t['hashString']}",
        f"Status:    {status_name(t)}",
        f"Progress:  {t['percentDone'] * 100:.1f}%",
        f"Size:      {_human_size(t['totalSize'])}",
        f"Down/Up:   {_human_size(t['rateDownload'])}/s / {_human_size(t['rateUpload'])}/s",
        f"Ratio:     {t['uploadRatio']:.2f}",
        f"Peers:     {t['peersConnected']}",
        f"Dir:       {t['downloadDir']}",
    ]
    if t.get("error"):
        lines.append(f"Error:     {t['errorString']}")
    return lines


@click.group()
@click.option("--host", default=None, help="Transmission host (default: localhost, or $TRANSMISSION_HOST)")
@click.option("--port", default=None, type=int, help="Transmission RPC port (default: 9091, or $TRANSMISSION_PORT)")
@click.option("--user", default=None, help="RPC username ($TRANSMISSION_USER)")
@click.option("--password", default=None, help="RPC password ($TRANSMISSION_PASS)")
@click.pass_context
def cli(ctx: click.Context, host: str | None, port: int | None, user: str | None, password: str | None) -> None:
    """Talk to a transmission-daemon RPC endpoint."""
    if ctx.obj is None:  # tests inject a client via `cli(obj=...)`
        ctx.obj = TransmissionClient(host=host, port=port, username=user, password=password)


@cli.command("list")
@click.pass_obj
def list_torrents(client: TransmissionClient) -> None:
    """List all torrents."""
    torrents = client.torrent_get()
    if not torrents:
        click.echo("No torrents.")
        return
    click.echo(LIST_HEADER)
    for t in torrents:
        click.echo(format_list_line(t))


@cli.command("info")
@click.argument("torrent_id", type=int)
@click.pass_obj
def info(client: TransmissionClient, torrent_id: int) -> None:
    """Show details for a single torrent."""
    torrents = client.torrent_get(ids=[torrent_id])
    if not torrents:
        click.echo(f"No torrent with id {torrent_id}", err=True)
        raise SystemExit(1)
    for line in format_info_lines(torrents[0]):
        click.echo(line)


@cli.command("add")
@click.argument("source")
@click.option("--dir", "download_dir", default=None, help="Download directory")
@click.option("--paused", is_flag=True, help="Add without starting")
@click.pass_obj
def add(client: TransmissionClient, source: str, download_dir: str | None, paused: bool) -> None:
    """Add a torrent from a magnet link, URL, or local .torrent file."""
    result = client.torrent_add(source, download_dir=download_dir, paused=paused)
    added = result.get("torrent-added") or result.get("torrent-duplicate")
    if added:
        click.echo(f"Added: {added['name']} (id={added['id']})")
    else:
        click.echo("Torrent submitted.")


@cli.command("start")
@click.argument("torrent_ids", type=int, nargs=-1, required=True)
@click.pass_obj
def start(client: TransmissionClient, torrent_ids: tuple[int, ...]) -> None:
    """Start one or more torrents."""
    client.torrent_start(list(torrent_ids))
    click.echo(f"Started {len(torrent_ids)} torrent(s).")


@cli.command("stop")
@click.argument("torrent_ids", type=int, nargs=-1, required=True)
@click.pass_obj
def stop(client: TransmissionClient, torrent_ids: tuple[int, ...]) -> None:
    """Stop one or more torrents."""
    client.torrent_stop(list(torrent_ids))
    click.echo(f"Stopped {len(torrent_ids)} torrent(s).")


@cli.command("remove")
@click.argument("torrent_ids", type=int, nargs=-1, required=True)
@click.option("--delete-data", is_flag=True, help="Also delete downloaded data")
@click.confirmation_option(prompt="Remove the selected torrent(s)?")
@click.pass_obj
def remove(client: TransmissionClient, torrent_ids: tuple[int, ...], delete_data: bool) -> None:
    """Remove one or more torrents."""
    client.torrent_remove(list(torrent_ids), delete_local_data=delete_data)
    click.echo(f"Removed {len(torrent_ids)} torrent(s).")


def main() -> None:
    """Console-script entry point: run the CLI, mapping RPC/connection errors to exit 1."""
    try:
        cli()
    except TransmissionError as exc:
        click.echo(f"Transmission RPC error: {exc}", err=True)
        sys.exit(1)
    except requests.exceptions.ConnectionError as exc:
        click.echo(f"Could not connect to transmission-daemon: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
