from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from web.app import create_app
except ModuleNotFoundError:  # Flask is installed from requirements on the Pi.
    create_app = None

from web.history import SatelliteHistory


class StubService:
    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict:
        return self._snapshot


@unittest.skipIf(create_app is None, "Flask is not installed")
class ApiTests(unittest.TestCase):
    def test_status_time_and_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history = SatelliteHistory(Path(temporary_directory) / "history.sqlite3")
            gps = StubService(
                {
                    "connected": False,
                    "error": "offline",
                    "last_report_epoch": None,
                    "age_seconds": None,
                    "device": None,
                    "tpv": {},
                    "sky": {},
                    "satellites": [],
                }
            )
            chrony = StubService(
                {
                    "available": False,
                    "synchronized": False,
                    "pps_status": "unavailable",
                    "selected_source": None,
                    "tracking": {},
                    "sources": [],
                }
            )
            app = create_app(
                start_services=False,
                gps_service=gps,
                chrony_service=chrony,
                history_service=history,
            )
            client = app.test_client()

            response = client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["gps"]["satellites"], [])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

            sample = client.get("/api/time").json
            self.assertGreaterEqual(int(sample["server_transmit_ns"]), int(sample["server_receive_ns"]))
            self.assertGreaterEqual(
                int(sample["server_transmit_monotonic_ns"]),
                int(sample["server_receive_monotonic_ns"]),
            )


if __name__ == "__main__":
    unittest.main()
