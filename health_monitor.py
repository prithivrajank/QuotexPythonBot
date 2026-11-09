"""In-process production health monitoring for provider, websocket, Telegram and storage.

The monitor is intentionally dependency-light and process-local. It never exposes
credentials or exception text; only component state, counters and safe timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any

_STARTED_MONOTONIC = time.monotonic()
_STARTED_AT = datetime.now(timezone.utc).isoformat()
_LOCK = threading.RLock()
_COMPONENTS: dict[str, dict[str, Any]] = {
    name: {"status": "unknown", "message": "No health check recorded yet.", "checked_at": None}
    for name in ("websocket", "provider", "telegram", "strategy", "database")
}
_COUNTERS = {"exceptions": 0, "websocket_errors": 0, "provider_errors": 0,
             "telegram_failures": 0, "database_errors": 0, "strategy_errors": 0}
_LAST_CANDLE_TIME: int | None = None
_LAST_SIGNAL_TIME: int | None = None
_CANDLE_COUNT = 0
_SIGNAL_COUNT = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_component(name: str, status: str, message: str = "") -> None:
    if name not in _COMPONENTS:
        return
    normalized = status.lower()
    if normalized not in {"healthy", "degraded", "down", "unknown"}:
        normalized = "unknown"
    with _LOCK:
        _COMPONENTS[name] = {
            "status": normalized,
            "message": str(message)[:240],
            "checked_at": _now(),
        }


def record_exception(component: str = "application") -> None:
    """Increment aggregate and component-specific exception counters."""
    with _LOCK:
        _COUNTERS["exceptions"] += 1
        key = {
            "websocket": "websocket_errors",
            "provider": "provider_errors",
            "telegram": "telegram_failures",
            "database": "database_errors",
            "strategy": "strategy_errors",
        }.get(component)
        if key:
            _COUNTERS[key] += 1


def record_candle(candle_time: int | None = None) -> None:
    global _LAST_CANDLE_TIME, _CANDLE_COUNT
    with _LOCK:
        _CANDLE_COUNT += 1
        if candle_time is not None:
            _LAST_CANDLE_TIME = int(candle_time)
    set_component("provider", "healthy", "Candles received successfully.")


def record_signal(signal_time: int | None = None, signal: str | None = None) -> None:
    global _LAST_SIGNAL_TIME, _SIGNAL_COUNT
    with _LOCK:
        if str(signal or "").upper() in {"CALL", "PUT"}:
            _SIGNAL_COUNT += 1
            _LAST_SIGNAL_TIME = int(signal_time) if signal_time is not None else int(time.time())
    set_component("strategy", "healthy", "Strategy analysis completed.")


def record_telegram_result(result: dict[str, Any] | None) -> None:
    result = result or {}
    if result.get("sent"):
        set_component("telegram", "healthy", "Telegram notification delivered.")
    else:
        reason = str(result.get("reason") or "Telegram notification not sent")
        # Not configured or intentionally suppressed is not a delivery failure.
        if reason in {"telegram_not_configured", "missing_symbol_or_candle_timestamp"} or "suppressed" in reason.lower():
            set_component("telegram", "unknown", reason)
        else:
            record_exception("telegram")
            set_component("telegram", "degraded", reason)


def websocket_connected() -> None:
    set_component("websocket", "healthy", "At least one market WebSocket client is connected.")


def websocket_disconnected() -> None:
    set_component("websocket", "degraded", "No active market WebSocket client is connected.")


def database_check() -> dict[str, Any]:
    """Run a lightweight SQLite read through the existing history module."""
    try:
        from signal_history import get_history
        get_history(1)
        set_component("database", "healthy", "Signal-history database read succeeded.")
    except Exception:
        record_exception("database")
        set_component("database", "down", "Signal-history database check failed.")
    with _LOCK:
        return dict(_COMPONENTS["database"])


def snapshot(provider_status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the stable health payload plus diagnostic component details."""
    global _CANDLE_COUNT, _SIGNAL_COUNT
    if provider_status is not None:
        connected = provider_status.get("connected")
        if connected is True:
            set_component("provider", "healthy", "Provider reports connected.")
        elif connected is False:
            set_component("provider", "degraded", "Provider reports disconnected or not yet validated.")
    database_check()
    with _LOCK:
        components = {key: dict(value) for key, value in _COMPONENTS.items()}
        counters = dict(_COUNTERS)
        candles_seen = _CANDLE_COUNT
        signals_seen = _SIGNAL_COUNT
        last_candle = _LAST_CANDLE_TIME
        last_signal = _LAST_SIGNAL_TIME

    score = 100
    websocket_status = components["websocket"]["status"]
    provider_component_status = components["provider"]["status"]
    telegram_status = components["telegram"]["status"]
    strategy_status = components["strategy"]["status"]
    database_status = components["database"]["status"]

    if websocket_status in {"degraded", "down"}:
        score -= 15
    if database_status == "down":
        score -= 30
    if telegram_status == "degraded":
        score -= 15
    if candles_seen == 0:
        score -= 20
    if signals_seen == 0:
        score -= 20
    if provider_component_status in {"degraded", "down"}:
        score -= 20
    if strategy_status == "down":
        score -= 10
    score = max(0, score)

    status = "HEALTHY"
    if score < 50:
        status = "CRITICAL"
    elif score < 70:
        status = "WARNING"

    uptime = max(0, int(time.monotonic() - _STARTED_MONOTONIC))
    payload = {
        "health_score": score,
        "status": status,
        "websocket": websocket_status,
        "database": database_status,
        "provider": provider_component_status,
        "telegram": telegram_status,
        "uptime_seconds": uptime,
        "strategy": strategy_status,
        "exception_counts": counters,
        "error_count": counters["exceptions"],
        "last_signal_time": last_signal,
        "last_candle_time": last_candle,
        "candles_received": candles_seen,
        "signals_generated": signals_seen,
        "started_at": _STARTED_AT,
        "components": components,
        "warning": (
            "CRITICAL: system health score is below 50."
            if score < 50 else
            "WARNING: system health score is below 70."
            if score < 70 else None
        ),
    }
    return payload
