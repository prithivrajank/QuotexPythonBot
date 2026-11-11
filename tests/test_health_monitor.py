"""Tests for process-local health monitoring without external dependencies."""
from __future__ import annotations

import pytest

import health_monitor as hm


@pytest.fixture(autouse=True)
def reset_monitor(monkeypatch):
    monkeypatch.setattr(hm, "_COMPONENTS", {
        name: {"status": "unknown", "message": "No health check recorded yet.", "checked_at": None}
        for name in ("websocket", "provider", "telegram", "strategy", "database")
    })
    monkeypatch.setattr(hm, "_COUNTERS", {
        "exceptions": 0, "websocket_errors": 0, "provider_errors": 0,
        "telegram_failures": 0, "database_errors": 0, "strategy_errors": 0,
    })
    monkeypatch.setattr(hm, "_LAST_CANDLE_TIME", None)
    monkeypatch.setattr(hm, "_LAST_SIGNAL_TIME", None)
    monkeypatch.setattr(hm, "_CANDLE_COUNT", 0)
    monkeypatch.setattr(hm, "_SIGNAL_COUNT", 0)
    monkeypatch.setattr(hm, "_WEBSOCKET_CLIENTS", 0)


def test_set_component_normalizes_status_and_ignores_unknown_name():
    hm.set_component("provider", "HEALTHY", "ok")
    assert hm._COMPONENTS["provider"]["status"] == "healthy"
    hm.set_component("provider", "not-a-status", "bad state")
    assert hm._COMPONENTS["provider"]["status"] == "unknown"
    previous = dict(hm._COMPONENTS["provider"])
    hm.set_component("unknown-component", "down", "ignored")
    assert hm._COMPONENTS["provider"] == previous


@pytest.mark.parametrize(
    ("component", "counter"),
    [
        ("websocket", "websocket_errors"),
        ("provider", "provider_errors"),
        ("telegram", "telegram_failures"),
        ("database", "database_errors"),
        ("strategy", "strategy_errors"),
        ("application", None),
    ],
)
def test_record_exception_updates_aggregate_and_specific_counters(component, counter):
    hm.record_exception(component)
    assert hm._COUNTERS["exceptions"] == 1
    if counter:
        assert hm._COUNTERS[counter] == 1


def test_candle_and_signal_counters_only_count_directional_signals():
    hm.record_candle(123)
    hm.record_candle()
    hm.record_signal(456, "WAIT")
    hm.record_signal(789, "call")
    hm.record_signal(None, "PUT")
    assert hm._CANDLE_COUNT == 2
    assert hm._LAST_CANDLE_TIME == 123
    assert hm._SIGNAL_COUNT == 2
    assert hm._LAST_SIGNAL_TIME == 0 or hm._LAST_SIGNAL_TIME > 0
    assert hm._COMPONENTS["provider"]["status"] == "healthy"
    assert hm._COMPONENTS["strategy"]["status"] == "healthy"


@pytest.mark.parametrize(
    ("result", "status", "failures"),
    [
        ({"sent": True}, "healthy", 0),
        ({"sent": False, "reason": "telegram_not_configured"}, "unknown", 0),
        ({"sent": False, "reason": "missing_symbol_or_candle_timestamp"}, "unknown", 0),
        ({"sent": False, "reason": "Pair suppressed by policy"}, "unknown", 0),
        ({"sent": False, "reason": "network error"}, "degraded", 1),
    ],
)
def test_record_telegram_result_classifies_delivery_state(result, status, failures):
    hm.record_telegram_result(result)
    assert hm._COMPONENTS["telegram"]["status"] == status
    assert hm._COUNTERS["telegram_failures"] == failures


def test_websocket_disconnect_count_never_goes_negative():
    hm.websocket_disconnected()
    assert hm._WEBSOCKET_CLIENTS == 0
    assert hm._COMPONENTS["websocket"]["status"] == "degraded"
    hm.websocket_connected()
    hm.websocket_connected()
    assert hm._WEBSOCKET_CLIENTS == 2
    hm.websocket_disconnected()
    assert hm._WEBSOCKET_CLIENTS == 1
    assert hm._COMPONENTS["websocket"]["status"] == "healthy"


def test_database_check_records_success(monkeypatch):
    import signal_history
    monkeypatch.setattr(signal_history, "get_history", lambda limit: [])
    result = hm.database_check()
    assert result["status"] == "healthy"


def test_database_check_records_failure_without_exposing_exception(monkeypatch):
    import signal_history
    monkeypatch.setattr(
        signal_history, "get_history",
        lambda limit: (_ for _ in ()).throw(RuntimeError("private database detail")),
    )
    result = hm.database_check()
    assert result["status"] == "down"
    assert "private database detail" not in result["message"]
    assert hm._COUNTERS["database_errors"] == 1


def test_snapshot_reports_warning_for_missing_first_candle_and_signal(monkeypatch):
    monkeypatch.setattr(hm, "database_check", lambda: {"status": "healthy"})
    result = hm.snapshot()
    assert result["health_score"] == 60
    assert result["status"] == "WARNING"
    assert result["warning"].startswith("WARNING:")


def test_snapshot_can_report_critical_health_and_provider_disconnection(monkeypatch):
    monkeypatch.setattr(hm, "database_check", lambda: hm._COMPONENTS["database"])
    hm.set_component("database", "down")
    hm.set_component("websocket", "degraded")
    hm.set_component("telegram", "degraded")
    hm.set_component("strategy", "down")
    result = hm.snapshot({"connected": False})
    assert result["provider"] == "degraded"
    assert result["status"] == "CRITICAL"
    assert result["health_score"] == 0


def test_snapshot_reports_healthy_provider_when_connected(monkeypatch):
    monkeypatch.setattr(hm, "database_check", lambda: {"status": "healthy"})
    hm.record_candle(123)
    hm.record_signal(456, "CALL")
    result = hm.snapshot({"connected": True})
    assert result["provider"] == "healthy"
    assert result["health_score"] == 100
    assert result["warning"] is None
