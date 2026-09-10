"""Low-frequency chronyc polling with machine-readable CSV parsing."""

from __future__ import annotations

import csv
import math
import os
import subprocess
import threading
import time
from typing import Any


def _number(value: str, integer: bool = False) -> int | float | None:
    try:
        parsed: int | float = int(value) if integer else float(value)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, float) and not math.isfinite(parsed):
        return None
    return parsed


def _rows(output: str) -> list[list[str]]:
    return [row for row in csv.reader(line for line in output.splitlines() if line.strip()) if row]


def parse_tracking(output: str) -> dict[str, Any]:
    rows = _rows(output)
    if not rows:
        raise ValueError("chronyc tracking returned no data")
    row = rows[0]
    if len(row) < 13:
        raise ValueError(f"unexpected chronyc tracking field count: {len(row)}")
    return {
        "reference_id": row[0],
        "stratum": _number(row[1], integer=True),
        "reference_time_epoch": _number(row[2]),
        "system_time_offset_s": _number(row[3]),
        "last_offset_s": _number(row[4]),
        "rms_offset_s": _number(row[5]),
        "frequency_ppm": _number(row[6]),
        "residual_frequency_ppm": _number(row[7]),
        "skew_ppm": _number(row[8]),
        "root_delay_s": _number(row[9]),
        "root_dispersion_s": _number(row[10]),
        "update_interval_s": _number(row[11]),
        "leap_status": row[12],
    }


def parse_sources(output: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for row in _rows(output):
        if len(row) < 7:
            continue
        sources.append(
            {
                "mode": row[0],
                "state": row[1],
                "name": row[2],
                "stratum": _number(row[3], integer=True),
                "poll": _number(row[4], integer=True),
                "reach": row[5],
                "last_rx_s": _number(row[6], integer=True),
                "adjusted_offset_s": _number(row[7]) if len(row) > 7 else None,
                "measured_offset_s": _number(row[8]) if len(row) > 8 else None,
                "estimated_error_s": _number(row[9]) if len(row) > 9 else None,
            }
        )
    return sources


def parse_sourcestats(output: str) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in _rows(output):
        if len(row) < 8:
            continue
        stats[row[0]] = {
            "samples": _number(row[1], integer=True),
            "runs": _number(row[2], integer=True),
            "span_s": _number(row[3], integer=True),
            "frequency_ppm": _number(row[4]),
            "frequency_skew_ppm": _number(row[5]),
            "offset_s": _number(row[6]),
            "standard_deviation_s": _number(row[7]),
        }
    return stats


def _reach_available(reach: str) -> bool:
    try:
        return int(reach, 8) != 0
    except (TypeError, ValueError):
        return False


class ChronyService:
    """Cache chrony state so web requests never spawn subprocesses."""

    def __init__(self, command: str = "chronyc", poll_interval: float = 2.0) -> None:
        self.command = command
        self.poll_interval = max(1.0, poll_interval)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "available": False,
            "error": None,
            "last_update_epoch": None,
            "age_seconds": None,
            "tracking": {},
            "sources": [],
            "selected_source": None,
            "synchronized": False,
            "pps_status": "unavailable",
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="chrony-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["tracking"] = dict(self._state["tracking"])
            state["sources"] = [dict(source) for source in self._state["sources"]]
            updated = self._state["last_update_epoch"]
        state["age_seconds"] = time.time() - updated if updated is not None else None
        return state

    def poll_once(self) -> dict[str, Any]:
        try:
            tracking = parse_tracking(self._run_command("tracking"))
            sources = parse_sources(self._run_command("sources"))
            try:
                stats = parse_sourcestats(self._run_command("sourcestats"))
            except (OSError, subprocess.SubprocessError, ValueError):
                stats = {}
            for source in sources:
                source["statistics"] = stats.get(source["name"], {})

            selected = next((source for source in sources if source["state"] == "*"), None)
            pps_sources = [source for source in sources if "PPS" in source["name"].upper()]
            if any(source["state"] == "*" for source in pps_sources):
                pps_status = "selected"
            elif any(source["state"] != "?" and _reach_available(source["reach"]) for source in pps_sources):
                pps_status = "available"
            else:
                pps_status = "unavailable"

            leap = str(tracking.get("leap_status", "")).strip().lower()
            synchronized = bool(tracking.get("stratum")) and leap not in {"3", "not synchronised", "not synchronized"}
            now = time.time()
            state = {
                "available": True,
                "error": None,
                "last_update_epoch": now,
                "age_seconds": 0.0,
                "tracking": tracking,
                "sources": sources,
                "selected_source": selected["name"] if selected else None,
                "synchronized": synchronized,
                "pps_status": pps_status,
            }
            with self._lock:
                self._state = state
            return self.snapshot()
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            with self._lock:
                self._state["available"] = False
                self._state["error"] = str(exc)
            return self.snapshot()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            if self._stop.wait(self.poll_interval):
                break

    def _run_command(self, report: str) -> str:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        result = subprocess.run(
            [self.command, "-c", report],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
            env=environment,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or f"chronyc {report} exited {result.returncode}"
            raise subprocess.SubprocessError(message)
        return result.stdout
