"""Flask web GUI for transmission-daemon's RPC API."""
from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from .rpc import TransmissionClient, TransmissionError, status_name

WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 5000
ENV_WEB_PORT = "TRANSMISSION_WEB_PORT"
RPC_ERROR_STATUS = 502  # daemon answered but refused the call


def create_app(client: TransmissionClient | None = None) -> Flask:
    """Build the Flask app; ``client`` is injected for tests, default reads ``TRANSMISSION_*`` env."""
    app = Flask(__name__)
    app.config["TRANSMISSION_CLIENT"] = client or TransmissionClient()

    def get_client() -> TransmissionClient:
        return app.config["TRANSMISSION_CLIENT"]

    @app.errorhandler(TransmissionError)
    def handle_rpc_error(exc: TransmissionError):
        return jsonify({"error": str(exc)}), RPC_ERROR_STATUS

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/torrents")
    def api_list_torrents():
        torrents = get_client().torrent_get()
        for t in torrents:
            t["statusName"] = status_name(t)
        return jsonify(torrents)

    @app.route("/api/torrents", methods=["POST"])
    def api_add_torrent():
        data = request.get_json(force=True)
        source = (data or {}).get("source", "").strip()
        if not source:
            return jsonify({"error": "source is required"}), 400
        result = get_client().torrent_add(source, download_dir=data.get("downloadDir") or None)
        return jsonify(result), 201

    @app.route("/api/torrents/<int:torrent_id>/start", methods=["POST"])
    def api_start_torrent(torrent_id: int):
        get_client().torrent_start([torrent_id])
        return jsonify({"ok": True})

    @app.route("/api/torrents/<int:torrent_id>/stop", methods=["POST"])
    def api_stop_torrent(torrent_id: int):
        get_client().torrent_stop([torrent_id])
        return jsonify({"ok": True})

    @app.route("/api/torrents/<int:torrent_id>", methods=["DELETE"])
    def api_remove_torrent(torrent_id: int):
        delete_data = request.args.get("deleteData", "false").lower() == "true"
        get_client().torrent_remove([torrent_id], delete_local_data=delete_data)
        return jsonify({"ok": True})

    return app


def main() -> None:
    """Serve the GUI on 127.0.0.1 (port from ``TRANSMISSION_WEB_PORT``, default 5000)."""
    app = create_app()
    app.run(host=WEB_HOST, port=int(os.environ.get(ENV_WEB_PORT, str(DEFAULT_WEB_PORT))))


if __name__ == "__main__":
    main()
