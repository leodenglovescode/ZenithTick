from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web.chrony_service import ChronyService, parse_sources, parse_sourcestats, parse_tracking
from web.gps_service import GpsService
from web.history import SatelliteHistory


class ChronyParsingTests(unittest.TestCase):
    def test_tracking_csv(self) -> None:
        tracking = parse_tracking(
            "50505300,PPS,1,1789056610.125,-0.000000124,0.000000032,0.000000410,"
            "-1.250,0.004,0.015,0.000420,0.000710,1.0,Normal\n"
        )
        self.assertEqual(tracking["reference_id"], "50505300")
        self.assertEqual(tracking["reference_name"], "PPS")
        self.assertEqual(tracking["stratum"], 1)
        self.assertAlmostEqual(tracking["reference_time_epoch"], 1789056610.125)
        self.assertAlmostEqual(tracking["system_time_offset_s"], -0.000000124)
        self.assertAlmostEqual(tracking["rms_offset_s"], 0.000000410)
        self.assertAlmostEqual(tracking["root_dispersion_s"], 0.000710)
        self.assertAlmostEqual(tracking["update_interval_s"], 1.0)
        self.assertEqual(tracking["leap_status"], "Normal")

    def test_tracking_rejects_rows_missing_reference_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "field count: 13"):
            parse_tracking(
                "50505300,1,1789056610.125,-0.000000124,0.000000032,0.000000410,"
                "-1.250,0.004,0.015,0.000420,0.000710,1.0,Normal\n"
            )

    def test_sources_and_stats_csv(self) -> None:
        sources = parse_sources(
            "#,*,PPS,0,0,377,0,0.000000010,0.000000012,0.000000050\n"
            "^,+,ntp.example,2,6,377,12,-0.000120,-0.000121,0.000800\n"
        )
        stats = parse_sourcestats("PPS,12,7,15,0.001,0.005,0.000000011,0.000000020\n")
        self.assertEqual(sources[0]["state"], "*")
        self.assertEqual(sources[0]["reach"], "377")
        self.assertAlmostEqual(stats["PPS"]["standard_deviation_s"], 0.000000020)

    def test_selected_pps_is_reported_as_synchronized(self) -> None:
        reports = {
            "tracking": (
                "50505300,PPS,1,1789056610.125,-0.000000124,0.000000032,0.000000410,"
                "-1.250,0.004,0.015,0.000420,0.000710,16.0,Normal\n"
            ),
            "sources": "#,*,PPS,0,4,377,9,-0.000002199,-0.000002555,0.000000300\n",
            "sourcestats": "PPS,12,7,15,0.001,0.005,0.000000011,0.000000020\n",
        }
        service = ChronyService()
        service._run_command = reports.__getitem__  # type: ignore[method-assign]

        state = service.poll_once()

        self.assertTrue(state["available"])
        self.assertTrue(state["synchronized"])
        self.assertEqual(state["pps_status"], "selected")
        self.assertEqual(state["selected_source"], "PPS")
        self.assertEqual(state["tracking"]["stratum"], 1)
        self.assertEqual(state["tracking"]["leap_status"], "Normal")


class GpsMergeTests(unittest.TestCase):
    def test_partial_sky_preserves_valid_fields_and_satellites(self) -> None:
        observations: list[tuple[list[dict], float]] = []
        gps = GpsService(history_observer=lambda satellites, timestamp: observations.append((satellites, timestamp)))
        gps.handle_report(
            {
                "class": "SKY",
                "nSat": 2,
                "uSat": 1,
                "hdop": 0.9,
                "satellites": [
                    {"PRN": 3, "az": 120.0, "el": 45.0, "ss": 36.0, "used": True},
                    {"PRN": 7, "az": 300.0, "el": 18.0, "ss": 21.0, "used": False},
                ],
            },
            observed_at=100.0,
        )
        gps.handle_report({"class": "SKY", "vdop": 1.2}, observed_at=101.0)
        snapshot = gps.snapshot()
        self.assertEqual(snapshot["sky"]["nSat"], 2)
        self.assertEqual(snapshot["sky"]["hdop"], 0.9)
        self.assertEqual(snapshot["sky"]["vdop"], 1.2)
        self.assertEqual(len(snapshot["satellites"]), 2)
        self.assertEqual(len(observations), 1)

    def test_partial_satellite_fields_are_merged(self) -> None:
        gps = GpsService()
        gps.handle_report({"class": "SKY", "satellites": [{"PRN": 3, "az": 20, "el": 30, "ss": 25}]})
        gps.handle_report({"class": "SKY", "satellites": [{"PRN": 3, "ss": 31, "used": True}]})
        satellite = gps.snapshot()["satellites"][0]
        self.assertEqual(satellite["az"], 20)
        self.assertEqual(satellite["el"], 30)
        self.assertEqual(satellite["ss"], 31)
        self.assertTrue(satellite["used"])


class HistoryTests(unittest.TestCase):
    def test_history_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.sqlite3"
            history = SatelliteHistory(path)
            history.observe([{"id": "prn:3", "ss": 20.0}], observed_at=100.0)
            history.observe([{"id": "prn:3", "ss": 35.0}], observed_at=120.0)
            history.flush()

            reopened = SatelliteHistory(path)
            row = reopened.snapshot()["prn:3"]
            self.assertEqual(row["first_seen"], 100.0)
            self.assertEqual(row["last_seen"], 120.0)
            self.assertEqual(row["best_signal"], 35.0)
            self.assertEqual(row["observations"], 2)


if __name__ == "__main__":
    unittest.main()
