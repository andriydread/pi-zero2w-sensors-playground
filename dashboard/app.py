import os
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from storage import AirMonitorDatabase


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value


def choose_bucket_seconds(hours: int) -> int:
    if hours <= 6:
        return 60
    if hours <= 24:
        return 300
    if hours <= 72:
        return 900
    return 1800


def create_app() -> Flask:
    app = Flask(__name__)
    database = AirMonitorDatabase(env_str("AIRMONITOR_DATABASE_PATH", "data/airmonitor.db"))

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/summary")
    def api_summary() -> Any:
        return jsonify(database.get_dashboard_summary())

    @app.get("/api/history")
    def api_history() -> Any:
        hours = max(1, min(env_int_from_request("hours", 24), 24 * 30))
        bucket_seconds = choose_bucket_seconds(hours)
        return jsonify(
            {
                "hours": hours,
                "bucket_seconds": bucket_seconds,
                "rows": database.query_history(hours, bucket_seconds),
            }
        )

    @app.post("/api/commands")
    def api_commands() -> Any:
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        command = str(body.get("command", "")).strip()
        payload = body.get("payload") or {}
        if not command:
            return jsonify({"error": "command is required"}), 400

        allowed_commands = {
            "display_full_refresh",
            "display_partial_refresh",
            "sps30_force_clean",
            "sps30_set_auto_cleaning_interval",
            "scd41_force_calibration",
            "scd41_set_asc",
        }
        if command not in allowed_commands:
            return jsonify({"error": f"unsupported command: {command}"}), 400

        command_id = database.queue_command(command, payload)
        return jsonify({"id": command_id, "status": "pending"}), 202

    return app


def env_int_from_request(name: str, default: int) -> int:
    value = request.args.get(name)
    if value is None:
        return default
    return int(value)


app = create_app()


if __name__ == "__main__":
    host = env_str("AIRMONITOR_WEB_HOST", "0.0.0.0")
    port = env_int("AIRMONITOR_WEB_PORT", 8080)
    app.run(host=host, port=port, debug=False)
