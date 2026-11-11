"""Lightweight process-local request and memory telemetry."""
from __future__ import annotations

import logging
import math
import threading
import platform
from typing import Any

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_request_count = 0
_total_request_seconds = 0.0
_max_request_seconds = 0.0


def record_request(duration_seconds: float) -> None:
    """Record one completed HTTP request duration."""
    global _request_count, _total_request_seconds, _max_request_seconds
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError, OverflowError):
        duration = 0.0
    if not math.isfinite(duration) or duration < 0:
        duration = 0.0
    with _lock:
        _request_count += 1
        _total_request_seconds += duration
        _max_request_seconds = max(_max_request_seconds, duration)


def _memory_usage() -> dict[str, Any]:
    """Return best-effort resident memory usage without requiring psutil."""
    try:
        import resource

        peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes.
        peak_mb = peak / (1024.0 * 1024.0 if platform.system() == "Darwin" else 1024.0)
        return {"peak_rss_mb": round(peak_mb, 2), "available": True}
    except (ImportError, OSError, ValueError):
        logger.debug("Process RSS metrics are unavailable on this platform.")
        return {"peak_rss_mb": None, "available": False}


def metrics_snapshot() -> dict[str, Any]:
    """Return a consistent snapshot of process-local execution and memory metrics."""
    with _lock:
        count = _request_count
        total = _total_request_seconds
        maximum = _max_request_seconds
    memory = _memory_usage()
    return {
        "request_count": count,
        "average_request_seconds": round(total / count, 6) if count else 0.0,
        "max_request_seconds": round(maximum, 6),
        "memory": memory,
        "scope": "Process-local metrics; reset on restart and separate per worker.",
    }
