"""Authoritative Raspberry Pi system-clock timestamps for browser synchronization."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def time_sample(
    chrony_summary: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture paired realtime/monotonic timestamps around a minimal payload build.

    Integer nanoseconds are serialized as strings by the caller so JavaScript can
    retain their precision with ``BigInt``.
    """

    receive_realtime_ns = time.time_ns()
    receive_monotonic_ns = time.monotonic_ns()

    summary = chrony_summary() if callable(chrony_summary) else chrony_summary
    sample: dict[str, Any] = {
        "clock": "CLOCK_REALTIME",
        "resolution_ns": max(1, round(time.get_clock_info("time").resolution * 1_000_000_000)),
        "chrony": summary or {},
    }

    sample["server_receive_ns"] = str(receive_realtime_ns)
    sample["server_receive_monotonic_ns"] = str(receive_monotonic_ns)
    sample["server_transmit_ns"] = str(time.time_ns())
    sample["server_transmit_monotonic_ns"] = str(time.monotonic_ns())
    return sample
