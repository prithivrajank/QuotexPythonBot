"""Integration-surface tests for the production readiness checklist.

Every external or stateful dependency is replaced with an in-process stub.
"""
from __future__ import annotations

import pytest

import backtester
import health_monitor
import pair_performance
import production_checklist
import signal_history
import strategy_registry
import walkforward


def patch_audit_dependencies(monkeypatch):
    monkeypatch.setattr(signal_history, "get_history", lambda limit: [])
    monkeypatch.setattr(
        health_monitor, "snapshot",
        lambda: {"websocket": "healthy", "health_score": 100},
    )
    monkeypatch.setattr(
        health_monitor, "database_check",
        lambda: {"status": "healthy"},
    )
    monkeypatch.setattr(
        strategy_registry, "list_strategies",
        lambda: [{"name": "SAMPLE", "version": "1.0.0"}],
    )
    monkeypatch.setattr(
        strategy_registry, "get_strategy",
        lambda name: {"name": name, "version": "1.0.0"},
    )
    monkeypatch.setattr(strategy_registry, "analyze_with_strategy", lambda *a: {})
    monkeypatch.setattr(
        pair_performance, "pair_performance_summary",
        lambda: {
            "pairs": [],
            "top_performing_pairs": [],
            "worst_performing_pairs": [],
            "disabled_pairs": [],
            "priority_pairs": [],
        },
    )
    monkeypatch.setattr(backtester, "run_backtest", lambda *a, **k: {})
    monkeypatch.setattr(backtester, "run_all_strategies", lambda *a, **k: {})
    monkeypatch.setattr(backtester, "run_strategy_comparison", lambda *a, **k: {})
    monkeypatch.setattr(walkforward, "run_walkforward", lambda *a, **k: {})
    monkeypatch.setattr(
        production_checklist, "_telegram_check",
        lambda: production_checklist._check("telegram_connectivity", "PASS", "getMe verified"),
    )


def test_run_checks_reports_all_integrations_without_network_calls(monkeypatch):
    patch_audit_dependencies(monkeypatch)
    checks = production_checklist._run_checks()
    assert len(checks) == 8
    assert {item["name"] for item in checks} == {
        "database_connectivity",
        "websocket_connectivity",
        "telegram_connectivity",
        "strategy_registry",
        "pair_ranking_service",
        "health_monitor",
        "backtester",
        "walk_forward_validator",
    }
    assert all(item["status"] == "PASS" for item in checks)


@pytest.mark.parametrize(
    ("websocket_state", "expected"),
    [("degraded", "WARNING"), ("down", "WARNING"), ("unknown", "WARNING")],
)
def test_run_checks_reports_nonconnected_websocket_as_warning(
    monkeypatch, websocket_state, expected
):
    patch_audit_dependencies(monkeypatch)
    monkeypatch.setattr(
        health_monitor, "snapshot",
        lambda: {"websocket": websocket_state, "health_score": 70},
    )
    checks = production_checklist._run_checks()
    websocket = next(item for item in checks if item["name"] == "websocket_connectivity")
    assert websocket["status"] == expected


def test_run_checks_reports_database_failure_without_exception_details(monkeypatch):
    patch_audit_dependencies(monkeypatch)

    def fail(_limit):
        raise RuntimeError("private database path")

    monkeypatch.setattr(signal_history, "get_history", fail)
    checks = production_checklist._run_checks()
    database = next(item for item in checks if item["name"] == "database_connectivity")
    assert database["status"] == "FAIL"
    assert "private database path" not in database["message"]


def test_run_checks_reports_missing_pair_ranking_fields(monkeypatch):
    patch_audit_dependencies(monkeypatch)
    monkeypatch.setattr(pair_performance, "pair_performance_summary", lambda: {"pairs": []})
    checks = production_checklist._run_checks()
    ranking = next(item for item in checks if item["name"] == "pair_ranking_service")
    assert ranking["status"] == "FAIL"


def test_run_checks_reports_invalid_health_monitor_payload(monkeypatch):
    patch_audit_dependencies(monkeypatch)
    monkeypatch.setattr(
        health_monitor, "snapshot",
        lambda: {"websocket": "healthy"},
    )
    monkeypatch.setattr(
        health_monitor, "database_check",
        lambda: "not-a-dictionary",
    )
    checks = production_checklist._run_checks()
    health = next(item for item in checks if item["name"] == "health_monitor")
    assert health["status"] == "FAIL"


def test_run_checks_reports_unavailable_backtester_and_walkforward(monkeypatch):
    patch_audit_dependencies(monkeypatch)
    monkeypatch.setattr(backtester, "run_all_strategies", None)
    monkeypatch.setattr(walkforward, "run_walkforward", None)
    checks = production_checklist._run_checks()
    backtest = next(item for item in checks if item["name"] == "backtester")
    walk = next(item for item in checks if item["name"] == "walk_forward_validator")
    assert backtest["status"] == "FAIL"
    assert walk["status"] == "FAIL"


def test_run_checks_catches_strategy_registry_metadata_failure(monkeypatch):
    patch_audit_dependencies(monkeypatch)
    monkeypatch.setattr(
        strategy_registry, "get_strategy",
        lambda _name: (_ for _ in ()).throw(RuntimeError("private registry error")),
    )
    checks = production_checklist._run_checks()
    registry = next(item for item in checks if item["name"] == "strategy_registry")
    assert registry["status"] == "FAIL"
    assert "private registry error" not in registry["message"]
