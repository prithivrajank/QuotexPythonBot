"""Phase 2 tests for retry diagnostics, process metrics, and safe audits."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
import requests

import observability
import production_checklist
import resilience


def test_retry_call_recovers_after_retryable_failures():
    attempts = []
    retry_attempts = []

    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise resilience.SimulatedFailure("transient")
        return "ready"

    result = resilience.retry_call(
        operation,
        max_attempts=3,
        retry_on=(resilience.SimulatedFailure,),
        on_retry=retry_attempts.append,
    )
    assert result == "ready"
    assert attempts == [1, 2, 3]
    assert retry_attempts == [1, 2]


def test_retry_call_does_not_retry_unlisted_exception():
    attempts = []
    with pytest.raises(ValueError, match="stop"):
        resilience.retry_call(
            lambda: (attempts.append(1) or (_ for _ in ()).throw(ValueError("stop"))),
            max_attempts=5,
            retry_on=(resilience.SimulatedFailure,),
        )
    assert len(attempts) == 1


@pytest.mark.parametrize("attempts", [0, -1])
def test_retry_call_rejects_nonpositive_attempt_limit(attempts):
    with pytest.raises(ValueError, match="at least 1"):
        resilience.retry_call(lambda: None, max_attempts=attempts)


def test_resilience_suite_runs_only_isolated_scenarios_and_persists_report(monkeypatch, tmp_path):
    monkeypatch.setattr(resilience, "_METRICS", {
        "recovery_attempts": 0,
        "successful_recoveries": 0,
        "unrecoverable_failures": 0,
        "last_run_at": None,
    })
    report_path = tmp_path / "nested" / "resilience.json"
    monkeypatch.setenv("RESILIENCE_REPORT_PATH", str(report_path))
    report = resilience.run_resilience_suite()
    assert report["overall_status"] == "PASS"
    assert report["scenarios_run"] == 5
    assert report["scenarios_recovered"] == 5
    assert report["scenarios_failed"] == 0
    assert report["run_metrics"]["recovery_attempts"] == 7
    assert report["report_path"] == str(report_path)
    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["scope"].startswith("Isolated fault-injection simulations")
    assert resilience.resilience_metrics()["successful_recoveries"] == 5


def test_scenario_reports_unrecoverable_failure_without_exception_text(monkeypatch):
    monkeypatch.setattr(resilience, "_METRICS", {
        "recovery_attempts": 0,
        "successful_recoveries": 0,
        "unrecoverable_failures": 0,
        "last_run_at": None,
    })
    result = resilience._scenario(
        "permanent_failure",
        lambda _attempt: (_ for _ in ()).throw(RuntimeError("private detail")),
    )
    assert result["status"] == "FAILED"
    assert result["error_type"] == "RuntimeError"
    assert "private detail" not in str(result)
    assert resilience.resilience_metrics()["unrecoverable_failures"] == 1


def test_resilience_report_write_failure_is_nonfatal(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("RESILIENCE_REPORT_PATH", str(blocker / "report.json"))
    assert resilience._write_report({"ok": True}) is None


def test_observability_records_valid_and_sanitizes_invalid_durations(monkeypatch):
    monkeypatch.setattr(observability, "_request_count", 0)
    monkeypatch.setattr(observability, "_total_request_seconds", 0.0)
    monkeypatch.setattr(observability, "_max_request_seconds", 0.0)
    for value in (1.25, 0.75, -1, float("nan"), float("inf"), "bad"):
        observability.record_request(value)
    snap = observability.metrics_snapshot()
    assert snap["request_count"] == 6
    assert snap["average_request_seconds"] == 0.333333
    assert snap["max_request_seconds"] == 1.25


def test_observability_memory_usage_success_path(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(getrusage=lambda _who: SimpleNamespace(ru_maxrss=2048)),
    )
    monkeypatch.setattr(observability.platform, "system", lambda: "Linux")
    result = observability._memory_usage()
    assert result == {"peak_rss_mb": 2.0, "available": True}


def test_observability_memory_usage_unavailable_path(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("not supported")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "resource", raising=False)
    monkeypatch.setattr("builtins.__import__", fake_import)
    result = observability._memory_usage()
    assert result == {"peak_rss_mb": None, "available": False}


def test_audit_check_truncates_messages():
    item = production_checklist._check("name", "PASS", "x" * 300)
    assert len(item["message"]) == 240


def test_telegram_audit_skips_network_when_token_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setitem(
        sys.modules, "requests",
        SimpleNamespace(get=lambda *a, **k: pytest.fail("must not call Telegram")),
    )
    result = production_checklist._telegram_check()
    assert result["status"] == "WARNING"
    assert "not configured" in result["message"]


def test_telegram_audit_uses_get_me_only_and_does_not_expose_token(monkeypatch):
    token = "never-log-this-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"username": "sample_bot"}}

    monkeypatch.setitem(
        sys.modules, "requests",
        SimpleNamespace(get=lambda url, **kwargs: (calls.append((url, kwargs)) or FakeResponse())),
    )
    result = production_checklist._telegram_check()
    assert result["status"] == "PASS"
    assert calls[0][0].endswith("/getMe")
    assert calls[0][1]["timeout"] == 5
    assert token not in str(result)


def test_telegram_audit_failure_does_not_return_request_url_or_token(monkeypatch):
    token = "never-log-this-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    def fail(url, **kwargs):
        raise requests.ConnectionError(f"request failed for {url}")

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=fail))
    result = production_checklist._telegram_check()
    assert result["status"] == "FAIL"
    assert token not in str(result)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS", "PASS"], "PASS"),
        (["PASS", "WARNING"], "WARNING"),
        (["PASS", "FAIL"], "FAIL"),
    ],
)
def test_production_audit_aggregates_and_persists_status(monkeypatch, tmp_path, statuses, expected):
    monkeypatch.setattr(
        production_checklist, "_run_checks",
        lambda: [
            production_checklist._check(f"check-{index}", status, "safe")
            for index, status in enumerate(statuses)
        ],
    )
    path = tmp_path / "reports" / "audit.json"
    monkeypatch.setenv("AUDIT_REPORT_PATH", str(path))
    report = production_checklist.run_production_audit()
    assert report["overall_status"] == expected
    assert report["passed_checks"] == statuses.count("PASS")
    assert report["warnings"] == statuses.count("WARNING")
    assert report["failed_checks"] == statuses.count("FAIL")
    assert json.loads(path.read_text(encoding="utf-8"))["checks"] == report["checks"]


def test_production_audit_report_write_failure_is_nonfatal(monkeypatch, tmp_path):
    blocker = tmp_path / "existing-file"
    blocker.write_text("blocker", encoding="utf-8")
    monkeypatch.setattr(production_checklist, "_run_checks", lambda: [])
    monkeypatch.setenv("AUDIT_REPORT_PATH", str(blocker / "audit.json"))
    report = production_checklist.run_production_audit()
    assert report["overall_status"] == "PASS"
    assert report["export_path"] is None
    assert "could not be written" in report["export_warning"]


def test_log_audit_report_emits_aggregate_and_checks(caplog):
    report = {
        "overall_status": "WARNING", "passed_checks": 2,
        "failed_checks": 0, "warnings": 1, "uptime": 12,
        "checks": [{"name": "provider", "status": "WARNING", "message": "not validated"}],
    }
    with caplog.at_level("INFO", logger="production_audit"):
        production_checklist.log_audit_report(report)
    assert "passed=2" in caplog.text
    assert "provider" in caplog.text
