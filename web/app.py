"""Flask entry point for the ZenithTick dashboard."""

from __future__ import annotations

import atexit
import os
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template

from .chrony_service import ChronyService
from .gps_service import GpsService
from .history import SatelliteHistory
from .time_service import time_sample


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_app(
    *,
    start_services: bool = True,
    gps_service: GpsService | None = None,
    chrony_service: ChronyService | None = None,
    history_service: SatelliteHistory | None = None,
) -> Flask:
    app = Flask(__name__)

    history_path = os.environ.get(
        "ZENITICK_HISTORY_DB",
        str(PROJECT_ROOT / "var" / "satellite_history.sqlite3"),
    )
    history = history_service or SatelliteHistory(history_path)
    gps = gps_service or GpsService(
        host=os.environ.get("ZENITICK_GPSD_HOST", "127.0.0.1"),
        port=int(os.environ.get("ZENITICK_GPSD_PORT", "2947")),
        history_observer=history.observe,
    )
    chrony = chrony_service or ChronyService(
        command=os.environ.get("ZENITICK_CHRONYC", "chronyc"),
        poll_interval=float(os.environ.get("ZENITICK_CHRONY_INTERVAL", "2")),
    )

    app.extensions["zenitick_services"] = {"gps": gps, "chrony": chrony, "history": history}

    if start_services:
        history.start()
        gps.start()
        chrony.start()

        def stop_services() -> None:
            gps.stop()
            chrony.stop()
            history.stop()

        atexit.register(stop_services)

    @app.after_request
    def response_headers(response: Any) -> Any:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/status")
    def api_status() -> Any:
        gps_state = gps.snapshot()
        satellite_ids = [satellite["id"] for satellite in gps_state["satellites"]]
        history_rows = history.snapshot(satellite_ids)
        for satellite in gps_state["satellites"]:
            satellite.update(history_rows.get(satellite["id"], {}))
        return jsonify(
            {
                "generated_at_ns": str(time.time_ns()),
                "gps": gps_state,
                "chrony": chrony.snapshot(),
                "history": history.status(),
            }
        )

    @app.get("/api/time")
    def api_time() -> Any:
        def chrony_summary() -> dict[str, Any]:
            chrony_state = chrony.snapshot()
            return {
                "available": chrony_state.get("available"),
                "synchronized": chrony_state.get("synchronized"),
                "pps_status": chrony_state.get("pps_status"),
                "selected_source": chrony_state.get("selected_source"),
            }

        return jsonify(time_sample(chrony_summary))

    @app.get("/api/history")
    def api_history() -> Any:
        return jsonify({"satellites": list(history.snapshot().values()), "status": history.status()})

    return app


if __name__ == "__main__":
    bind_address = os.environ.get("ZENITICK_BIND", "127.0.0.1")
    port = int(os.environ.get("ZENITICK_PORT", "8989"))
    application = create_app()
    application.run(host=bind_address, port=port, debug=False, threaded=True)
