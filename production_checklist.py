"""Read-only production readiness audit for application subsystems.

Checks validate local integration surfaces. Telegram uses Bot API getMe only:
it never sends a message. WebSocket connectivity is reported as WARNING when
no dashboard client is connected; startup cannot manufacture a client.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

logger = logging.getLogger("production_audit")
_STARTED_MONOTONIC = time.monotonic()
_AUDIT_VERSION = "1.0.0"


def _check(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message[:240]}


def _telegram_check() -> dict[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return _check("telegram_connectivity", "WARNING",
                      "TELEGRAM_BOT_TOKEN is not configured; no connectivity test was made.")
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("ok") is True:
            return _check("telegram_connectivity", "PASS",
                          "Telegram Bot API getMe succeeded; no message was sent.")
        return _check("telegram_connectivity", "FAIL",
                      "Telegram Bot API rejected the bot authentication check.")
    except Exception:
        # Do not include exception text: HTTP errors may contain sensitive request URLs.
        return _check("telegram_connectivity", "FAIL",
                      "Telegram Bot API connectivity/authentication check failed.")


def _run_checks() -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    # SQLite connectivity: run the same read-only check used by the health monitor.
    try:
        from signal_history import get_history
        get_history(1)
        checks.append(_check("database_connectivity", "PASS", "Signal-history database read succeeded."))
    except Exception:
        checks.append(_check("database_connectivity", "FAIL", "Signal-history database read failed."))

    # A WebSocket is an inbound browser connection. A process startup cannot
    # establish one itself, so report the actual observed client state.
    try:
        from health_monitor import snapshot as health_snapshot
        health = health_snapshot()
        ws = str(health.get("websocket", "unknown")).lower()
        if ws == "healthy":
            checks.append(_check("websocket_connectivity", "PASS", "At least one market WebSocket client is connected."))
        elif ws in {"degraded", "down"}:
            checks.append(_check("websocket_connectivity", "WARNING", "No active market WebSocket client is connected; REST dashboard remains available."))
        else:
            checks.append(_check("websocket_connectivity", "WARNING", "WebSocket client connectivity has not yet been observed."))
    except Exception:
        checks.append(_check("websocket_connectivity", "FAIL", "WebSocket health monitor could not be queried."))

    checks.append(_telegram_check())

    try:
        from strategy_registry import list_strategies, get_strategy, analyze_with_strategy
        registered = list_strategies()
        valid = bool(registered) and all(
            get_strategy(item["name"])["version"] == item["version"]
            for item in registered
        ) and callable(analyze_with_strategy)
        checks.append(_check("strategy_registry", "PASS" if valid else "FAIL",
                             f"{len(registered)} registered strategies validated." if valid else "Strategy registry validation failed."))
    except Exception:
        checks.append(_check("strategy_registry", "FAIL", "Strategy registry import or metadata validation failed."))

    try:
        from pair_performance import pair_performance_summary
        summary = pair_performance_summary()
        if isinstance(summary, dict) and all(key in summary for key in (
            "pairs", "top_performing_pairs", "worst_performing_pairs",
            "disabled_pairs", "priority_pairs"
        )):
            checks.append(_check("pair_ranking_service", "PASS",
                                 f"Pair ranking service returned {len(summary['pairs'])} pair records."))
        else:
            checks.append(_check("pair_ranking_service", "FAIL", "Pair ranking response is missing required fields."))
    except Exception:
        checks.append(_check("pair_ranking_service", "FAIL", "Pair ranking service could not read performance data."))

    try:
        from health_monitor import snapshot as health_snapshot, database_check
        health = health_snapshot()
        database = database_check()
        valid = isinstance(health, dict) and "health_score" in health and isinstance(database, dict)
        checks.append(_check("health_monitor", "PASS" if valid else "FAIL",
                             "Health monitor snapshot and database component check succeeded." if valid else "Health monitor returned an invalid payload."))
    except Exception:
        checks.append(_check("health_monitor", "FAIL", "Health monitor could not produce a valid snapshot."))

    try:
        from backtester import run_backtest, run_all_strategies, run_strategy_comparison
        valid = all(callable(fn) for fn in (run_backtest, run_all_strategies, run_strategy_comparison))
        checks.append(_check("backtester", "PASS" if valid else "FAIL",
                             "Backtesting entry points imported successfully; no synthetic trades or candle data were run." if valid else "Backtester entry points are unavailable."))
    except Exception:
        checks.append(_check("backtester", "FAIL", "Backtester import or entry-point validation failed."))

    try:
        from walkforward import run_walkforward
        checks.append(_check("walk_forward_validator", "PASS" if callable(run_walkforward) else "FAIL",
                             "Walk-forward validator imported successfully; no synthetic candle data was used."))
    except Exception:
        checks.append(_check("walk_forward_validator", "FAIL", "Walk-forward validator import failed."))

    return checks


def run_production_audit() -> dict[str, Any]:
    """Run every readiness check, persist audit_report.json, and return report."""
    started = time.monotonic()
    checks = _run_checks()
    passed = sum(item["status"] == "PASS" for item in checks)
    failed = sum(item["status"] == "FAIL" for item in checks)
    warnings = sum(item["status"] == "WARNING" for item in checks)
    overall = "FAIL" if failed else "WARNING" if warnings else "PASS"
    report: dict[str, Any] = {
        "overall_status": overall,
        "passed_checks": passed,
        "failed_checks": failed,
        "warnings": warnings,
        "uptime": max(0, int(time.monotonic() - _STARTED_MONOTONIC)),
        "version": _AUDIT_VERSION,
        "application_version": "0.6.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "checks": checks,
    }
    path = Path(os.getenv("AUDIT_REPORT_PATH", "/tmp/audit_report.json"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        report["export_path"] = str(path)
    except OSError:
        logger.exception("Could not persist production audit report.")
        report["export_path"] = None
        report["export_warning"] = "Audit completed, but audit_report.json could not be written."
    return report


def log_audit_report(report: dict[str, Any]) -> None:
    """Log safe aggregate results and each subsystem's status."""
    logger.info(
        "Production audit: %s | passed=%s failed=%s warnings=%s uptime=%ss",
        report.get("overall_status"), report.get("passed_checks"),
        report.get("failed_checks"), report.get("warnings"), report.get("uptime"),
    )
    for item in report.get("checks", []):
        logger.info("Production audit [%s] %s: %s",
                    item.get("status"), item.get("name"), item.get("message"))
