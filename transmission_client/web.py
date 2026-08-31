"""Flask web GUI for transmission-daemon's RPC API."""
from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from .rpc import STATUS_NAMES, TransmissionClient, TransmissionError


def create_app(client: TransmissionClient | None = None) -> Flask:
    app = Flask(__name__)
    app.config["TRANSMISSION_CLIENT"] = client or TransmissionClient()

    def get_client() -> TransmissionClient:
        return app.config["TRANSMISSION_CLIENT"]

    @app.errorhandler(TransmissionError)
    def handle_rpc_error(exc: TransmissionError):
        return jsonify({"error": str(exc)}), 502

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/torrents")
    def api_list_torrents():
        torrents = get_client().torrent_get()
        for t in torrents:
            t["statusName"] = STATUS_NAMES.get(t["status"], str(t["status"]))
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
    import os

    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("TRANSMISSION_WEB_PORT", "5000")))


if __name__ == "__main__":
    main()
