"""Throttled SQLite persistence for satellite observation history."""

from __future__ import annotations

import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable


class SatelliteHistory:
    """Keep live history in memory and flush aggregates periodically.

    The gpsd reader never performs disk I/O. SQLite failures are contained here
    and retried on the next flush without affecting the live dashboard.
    """

    def __init__(self, database_path: str | Path, flush_interval: float = 10.0) -> None:
        self.database_path = Path(database_path)
        self.flush_interval = max(2.0, flush_interval)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pending: dict[str, dict[str, Any]] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._error: str | None = None
        self._thread: threading.Thread | None = None
        self._load()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="satellite-history", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.flush()

    def observe(self, satellites: Iterable[dict[str, Any]], observed_at: float | None = None) -> None:
        now = observed_at if observed_at is not None else time.time()
        with self._lock:
            for satellite in satellites:
                satellite_id = str(satellite.get("id") or "").strip()
                if not satellite_id:
                    continue
                signal = satellite.get("ss")
                best_signal = (
                    float(signal)
                    if isinstance(signal, (int, float)) and math.isfinite(signal)
                    else None
                )
                cached = self._cache.get(satellite_id)
                if cached is None:
                    cached = {
                        "id": satellite_id,
                        "first_seen": now,
                        "last_seen": now,
                        "best_signal": best_signal,
                        "observations": 0,
                    }
                    self._cache[satellite_id] = cached
                cached["last_seen"] = max(float(cached["last_seen"]), now)
                cached["first_seen"] = min(float(cached["first_seen"]), now)
                if best_signal is not None:
                    previous = cached.get("best_signal")
                    cached["best_signal"] = best_signal if previous is None else max(float(previous), best_signal)
                cached["observations"] = int(cached.get("observations", 0)) + 1

                pending = self._pending.get(satellite_id)
                if pending is None:
                    pending = {
                        "first_seen": now,
                        "last_seen": now,
                        "best_signal": best_signal,
                        "observations": 0,
                    }
                    self._pending[satellite_id] = pending
                pending["first_seen"] = min(float(pending["first_seen"]), now)
                pending["last_seen"] = max(float(pending["last_seen"]), now)
                if best_signal is not None:
                    previous = pending.get("best_signal")
                    pending["best_signal"] = best_signal if previous is None else max(float(previous), best_signal)
                pending["observations"] = int(pending["observations"]) + 1

    def snapshot(self, satellite_ids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
        wanted = set(satellite_ids) if satellite_ids is not None else None
        with self._lock:
            return {
                key: dict(value)
                for key, value in self._cache.items()
                if wanted is None or key in wanted
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": True,
                "database": str(self.database_path),
                "satellites": len(self._cache),
                "pending": len(self._pending),
                "error": self._error,
            }

    def flush(self) -> None:
        with self._lock:
            if not self._pending:
                return
            pending = self._pending
            self._pending = {}

        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database_path, timeout=1.0) as connection:
                self._initialize(connection)
                connection.executemany(
                    """
                    INSERT INTO satellite_history
                        (satellite_id, first_seen, last_seen, best_signal, observations)
                    VALUES (:satellite_id, :first_seen, :last_seen, :best_signal, :observations)
                    ON CONFLICT(satellite_id) DO UPDATE SET
                        first_seen = MIN(first_seen, excluded.first_seen),
                        last_seen = MAX(last_seen, excluded.last_seen),
                        best_signal = CASE
                            WHEN excluded.best_signal IS NULL THEN best_signal
                            WHEN best_signal IS NULL THEN excluded.best_signal
                            ELSE MAX(best_signal, excluded.best_signal)
                        END,
                        observations = observations + excluded.observations
                    """,
                    [dict(values, satellite_id=key) for key, values in pending.items()],
                )
            with self._lock:
                self._error = None
        except (OSError, sqlite3.Error) as exc:
            with self._lock:
                self._error = str(exc)
                for key, values in pending.items():
                    existing = self._pending.get(key)
                    if existing is None:
                        self._pending[key] = values
                        continue
                    existing["first_seen"] = min(existing["first_seen"], values["first_seen"])
                    existing["last_seen"] = max(existing["last_seen"], values["last_seen"])
                    signals = [v for v in (existing.get("best_signal"), values.get("best_signal")) if v is not None]
                    existing["best_signal"] = max(signals) if signals else None
                    existing["observations"] += values["observations"]

    def _run(self) -> None:
        while not self._stop.wait(self.flush_interval):
            self.flush()

    def _load(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database_path, timeout=1.0) as connection:
                self._initialize(connection)
                rows = connection.execute(
                    "SELECT satellite_id, first_seen, last_seen, best_signal, observations FROM satellite_history"
                ).fetchall()
            with self._lock:
                self._cache = {
                    row[0]: {
                        "id": row[0],
                        "first_seen": row[1],
                        "last_seen": row[2],
                        "best_signal": row[3],
                        "observations": row[4],
                    }
                    for row in rows
                }
                self._error = None
        except (OSError, sqlite3.Error) as exc:
            self._error = str(exc)

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS satellite_history (
                satellite_id TEXT PRIMARY KEY,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                best_signal REAL,
                observations INTEGER NOT NULL DEFAULT 0
            )
            """
        )
