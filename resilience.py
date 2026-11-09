"""Safe fault-injection simulations and recovery metrics.

All scenarios use isolated in-memory fakes. They never disconnect the real
WebSocket, call Telegram, lock the production database, or contact a provider.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("resilience")
_LOCK = threading.RLock()
_METRICS = {
    "recovery_attempts": 0,
    "successful_recoveries": 0,
    "unrecoverable_failures": 0,
    "last_run_at": None,
}
REPORT_PATH_DEFAULT = "/tmp/resilience_report.json"


class SimulatedFailure(RuntimeError):
    """A deliberate fault used only by isolated resilience simulations."""


def retry_call(operation: Callable[[], Any], *, max_attempts: int = 3,
               retry_on: tuple[type[BaseException], ...] = (Exception,),
               on_retry: Callable[[int], None] | None = None) -> Any:
    """Retry an operation with bounded attempts; caller owns any backoff delay."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except retry_on:
            if attempt >= max_attempts:
                raise
            if on_retry:
                on_retry(attempt)
    raise RuntimeError("unreachable retry state")


def _scenario(name: str, operation: Callable[[], Any], max_attempts: int = 3) -> dict[str, Any]:
    local_attempts = 0
    recovered = False
    safe_error = None

    def counted_operation():
        nonlocal local_attempts
        local_attempts += 1
        return operation()

    def retry_metric(_attempt: int):
        with _LOCK:
            _METRICS["recovery_attempts"] += 1

    try:
        result = retry_call(counted_operation, max_attempts=max_attempts,
                            retry_on=(SimulatedFailure,), on_retry=retry_metric)
        recovered = True
        with _LOCK:
            _METRICS["successful_recoveries"] += 1
        return {
            "scenario": name, "status": "RECOVERED", "attempts": local_attempts,
            "recovery_attempts": max(0, local_attempts - 1),
            "result": str(result)[:160],
            "message": "Injected failure was recovered by bounded retry.",
        }
    except Exception as exc:
        safe_error = type(exc).__name__
        with _LOCK:
            _METRICS["unrecoverable_failures"] += 1
        return {
            "scenario": name, "status": "FAILED", "attempts": local_attempts,
            "recovery_attempts": max(0, local_attempts - 1),
            "error_type": safe_error,
            "message": "Scenario did not recover within its retry limit.",
        }


def _websocket_disconnect():
    state = {"connected": False, "tries": 0}
    def reconnect():
        state["tries"] += 1
        if state["tries"] == 1:
            raise SimulatedFailure("injected websocket disconnect")
        state["connected"] = True
        return "simulated websocket reconnected"
    return retry_call(reconnect, max_attempts=3, retry_on=(SimulatedFailure,))


def _telegram_timeout():
    state = {"tries": 0}
    def send_probe():
        state["tries"] += 1
        if state["tries"] == 1:
            raise SimulatedFailure("injected Telegram timeout")
        return "simulated Telegram delivery probe recovered"
    return retry_call(send_probe, max_attempts=3, retry_on=(SimulatedFailure,))


def _database_locked():
    state = {"tries": 0}
    def read_probe():
        state["tries"] += 1
        if state["tries"] <= 2:
            raise SimulatedFailure("injected SQLite locked")
        return "simulated database read succeeded"
    return retry_call(read_probe, max_attempts=4, retry_on=(SimulatedFailure,))


def _provider_unavailable():
    state = {"tries": 0}
    def provider_probe():
        state["tries"] += 1
        if state["tries"] <= 2:
            raise SimulatedFailure("injected provider unavailable")
        return "simulated provider request recovered"
    return retry_call(provider_probe, max_attempts=4, retry_on=(SimulatedFailure,))


def _invalid_candle_data():
    # First payload is malformed; validation rejects it. The next payload is
    # a valid replacement from the test fixture, not a production data fallback.
    samples = iter([
        {"time": "not-a-timestamp", "open": 1, "high": 2, "low": 0, "close": 1},
        {"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
    ])
    def validate():
        candle = next(samples)
        try:
            timestamp = int(candle["time"])
            values = [float(candle[key]) for key in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise SimulatedFailure("injected invalid candle fields") from None
        if timestamp <= 0 or not all(map(lambda x: x == x and abs(x) != float("inf"), values)):
            raise SimulatedFailure("injected invalid candle values")
        o, h, low, close = values
        if h < max(o, close, low) or low > min(o, close, h):
            raise SimulatedFailure("injected inconsistent OHLC")
        return "invalid candle rejected; valid fixture accepted"
    return retry_call(validate, max_attempts=2, retry_on=(SimulatedFailure,))


def _write_report(report: dict[str, Any]) -> str | None:
    path = Path(os.getenv("RESILIENCE_REPORT_PATH", REPORT_PATH_DEFAULT))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return str(path)
    except OSError:
        logger.exception("Could not write resilience report.")
        return None


def run_resilience_suite() -> dict[str, Any]:
    """Run five isolated fault scenarios and verify bounded retry recovery."""
    with _LOCK:
        before = dict(_METRICS)
    scenarios = [
        _scenario("websocket_disconnect", _websocket_disconnect),
        _scenario("telegram_timeout", _telegram_timeout),
        _scenario("database_locked", _database_locked),
        _scenario("provider_unavailable", _provider_unavailable),
        _scenario("invalid_candle_data", _invalid_candle_data),
    ]
    completed = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        _METRICS["last_run_at"] = completed
        metrics = dict(_METRICS)
    recovered = sum(item["status"] == "RECOVERED" for item in scenarios)
    failed = len(scenarios) - recovered
    total = recovered + failed
    report: dict[str, Any] = {
        "overall_status": "PASS" if failed == 0 else "WARNING" if recovered else "FAIL",
        "scenarios_run": len(scenarios),
        "scenarios_recovered": recovered,
        "scenarios_failed": failed,
        "recovery_success_rate": round(recovered / total * 100, 2) if total else None,
        "metrics": metrics,
        "run_metrics": {
            "recovery_attempts": sum(item["recovery_attempts"] for item in scenarios),
            "successful_recoveries": recovered,
            "unrecoverable_failures": failed,
        },
        "scenarios": scenarios,
        "generated_at": completed,
        "scope": "Isolated fault-injection simulations only; no live provider, WebSocket, Telegram, or production database was disrupted.",
    }
    report_path = _write_report(report)
    report["report_path"] = report_path
    report["report_warning"] = None if report_path else "Report could not be persisted to the configured filesystem path."
    return report


def resilience_metrics() -> dict[str, Any]:
    """Return cumulative in-process recovery counters without running simulations."""
    with _LOCK:
        return dict(_METRICS)
