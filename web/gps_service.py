"""Persistent gpsd client and thread-safe TPV/SKY cache."""

from __future__ import annotations

import json
import math
import socket
import threading
import time
from typing import Any, Callable


Numeric = int | float


def _finite(value: Any) -> Numeric | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _satellite_key(satellite: dict[str, Any]) -> str | None:
    prn = satellite.get("PRN")
    if prn is not None:
        return f"prn:{prn}"
    gnssid, svid = satellite.get("gnssid"), satellite.get("svid")
    if gnssid is not None and svid is not None:
        return f"gnss:{gnssid}:{svid}"
    if svid is not None:
        return f"svid:{svid}"
    return None


class GpsService:
    """Maintain one WATCH connection to gpsd and merge partial reports."""

    TPV_FIELDS = (
        "device", "time", "mode", "lat", "lon", "alt", "altHAE", "altMSL",
        "speed", "track", "climb", "epx", "epy", "epv", "eps", "ept",
    )
    SKY_FIELDS = ("device", "time", "nSat", "uSat", "gdop", "hdop", "pdop", "tdop", "vdop", "xdop", "ydop")
    SATELLITE_FIELDS = ("PRN", "az", "el", "ss", "used", "gnssid", "svid", "health")

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2947,
        history_observer: Callable[[list[dict[str, Any]], float], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.history_observer = history_observer
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._state: dict[str, Any] = {
            "connected": False,
            "error": None,
            "last_report_epoch": None,
            "last_report_monotonic": None,
            "tpv": {},
            "sky": {},
            "satellites": {},
            "device": None,
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="gpsd-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            last_monotonic = self._state["last_report_monotonic"]
            return {
                "connected": self._state["connected"],
                "error": self._state["error"],
                "last_report_epoch": self._state["last_report_epoch"],
                "age_seconds": (now - last_monotonic) if last_monotonic is not None else None,
                "device": self._state["device"],
                "tpv": dict(self._state["tpv"]),
                "sky": dict(self._state["sky"]),
                "satellites": [dict(satellite) for satellite in self._state["satellites"].values()],
            }

    def handle_report(self, report: dict[str, Any], observed_at: float | None = None) -> None:
        """Merge one decoded gpsd report. Public to support deterministic tests."""

        report_class = report.get("class")
        if report_class not in {"TPV", "SKY", "DEVICE", "DEVICES"}:
            return
        wall_now = observed_at if observed_at is not None else time.time()
        monotonic_now = time.monotonic()
        observed_satellites: list[dict[str, Any]] | None = None

        with self._lock:
            self._state["connected"] = True
            self._state["error"] = None
            self._state["last_report_epoch"] = wall_now
            self._state["last_report_monotonic"] = monotonic_now

            if report_class == "TPV":
                self._merge_fields(self._state["tpv"], report, self.TPV_FIELDS)
                if report.get("device"):
                    self._state["device"] = str(report["device"])
            elif report_class == "SKY":
                self._merge_fields(self._state["sky"], report, self.SKY_FIELDS)
                if report.get("device"):
                    self._state["device"] = str(report["device"])
                if isinstance(report.get("satellites"), list):
                    previous = self._state["satellites"]
                    current: dict[str, dict[str, Any]] = {}
                    for raw_satellite in report["satellites"]:
                        if not isinstance(raw_satellite, dict):
                            continue
                        key = _satellite_key(raw_satellite)
                        if key is None:
                            continue
                        merged = dict(previous.get(key, {}))
                        self._merge_fields(merged, raw_satellite, self.SATELLITE_FIELDS)
                        merged["id"] = key
                        merged["label"] = self._satellite_label(merged)
                        current[key] = merged
                    self._state["satellites"] = current
                    observed_satellites = [dict(satellite) for satellite in current.values()]
            elif report_class == "DEVICE" and report.get("path"):
                self._state["device"] = str(report["path"])

        if observed_satellites is not None and self.history_observer is not None:
            self.history_observer(observed_satellites, wall_now)

    @staticmethod
    def _merge_fields(target: dict[str, Any], source: dict[str, Any], fields: tuple[str, ...]) -> None:
        for field in fields:
            if field not in source or source[field] is None:
                continue
            value = source[field]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = _finite(value)
                if value is None:
                    continue
            target[field] = value

    @staticmethod
    def _satellite_label(satellite: dict[str, Any]) -> str:
        if satellite.get("PRN") is not None:
            return str(satellite["PRN"])
        if satellite.get("svid") is not None:
            return str(satellite["svid"])
        return "?"

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=5.0) as sock:
                    self._socket = sock
                    sock.settimeout(10.0)
                    sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    with self._lock:
                        self._state["connected"] = True
                        self._state["error"] = None
                    delay = 1.0
                    buffer = b""
                    while not self._stop.is_set():
                        chunk = sock.recv(8192)
                        if not chunk:
                            raise ConnectionError("gpsd closed the connection")
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                report = json.loads(line)
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue
                            if isinstance(report, dict):
                                self.handle_report(report)
            except (OSError, ConnectionError) as exc:
                with self._lock:
                    self._state["connected"] = False
                    self._state["error"] = str(exc)
                self._socket = None
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2.0, 15.0)
