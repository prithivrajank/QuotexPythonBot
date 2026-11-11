"""Phase 2 database-backed validation and weekly report tests."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import validation_dashboard
import signal_history
import weekly_report


def configure_database(monkeypatch, tmp_path):
    database = tmp_path / "phase2.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("WEEKLY_REPORT_DIR", str(tmp_path / "weekly-exports"))
    signal_history.init_history()
    return database


def add_signal(now, symbol, days_ago, outcome, grade, strategy):
    moment = now - timedelta(days=days_ago)
    signal_time = int(moment.timestamp())
    signal_history.record_signal(
        symbol,
        60,
        {"time": signal_time, "close": 1.1},
        {
            "signal": "CALL" if outcome == "WIN" else "PUT",
            "reason": "phase two test",
            "signal_grade": grade,
            "signal_score": 8,
            "strategy_name": strategy,
            "strategy_version": "1.0.0",
        },
    )
    with signal_history._connection() as conn:
        conn.execute(
            """UPDATE signal_history
               SET outcome=?, exit_price=?, price_change_pct=?
               WHERE symbol=? AND timeframe_seconds=60 AND signal_time=?""",
            (outcome, 1.2 if outcome == "WIN" else 1.0, 1.0 if outcome == "WIN" else -1.0,
             symbol, signal_time),
        )
    return signal_time


def test_validation_dashboard_aggregates_outcomes_grades_periods_and_csv(monkeypatch, tmp_path):
    configure_database(monkeypatch, tmp_path)
    now_aware = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    add_signal(now_aware, "EUR/USD", 1, "WIN", "STRONG", "EMA_RSI_V1")
    add_signal(now_aware, "EUR/USD", 2, "LOSS", "WEAK", "SCORE_ENGINE_V2")
    add_signal(now_aware, "GBP/USD", 3, "PENDING", "MODERATE", "BREAKOUT_V3")
    add_signal(now_aware, "OLD/PAIR", 40, "WIN", "STRONG", "EMA_RSI_V1")

    # Naive timestamps are interpreted as UTC, not the machine's local timezone.
    payload = validation_dashboard.get_validation_payload(
        now=datetime(2026, 11, 11, 12, 0)
    )
    assert payload["generated_at"] == "2026-11-11T12:00:00+00:00"
    assert payload["metrics"]["total_signals"] == 4
    assert payload["metrics"]["wins"] == 2
    assert payload["metrics"]["losses"] == 1
    assert payload["metrics"]["scored_signals"] == 3
    assert payload["metrics"]["win_rate"] == 66.67
    assert payload["metrics"]["by_signal_grade"]["strong"]["wins"] == 2
    assert payload["recent_performance"]["30d"]["total_signals"] == 3
    assert payload["recent_performance"]["7d"]["total_signals"] == 3
    assert payload["recent_performance"]["24h"]["total_signals"] == 1
    assert {row["symbol"] for row in payload["top_pairs"]} == {"OLD/PAIR", "EUR/USD", "GBP/USD"}

    csv_rows = validation_dashboard.validation_csv_rows(payload)
    assert len(csv_rows) == 4
    assert all("signal_time_iso" in row for row in csv_rows)
    assert csv_rows[0]["symbol"] == "OLD/PAIR"


def test_validation_dashboard_empty_database_returns_zeroed_metrics(monkeypatch, tmp_path):
    configure_database(monkeypatch, tmp_path)
    payload = validation_dashboard.get_validation_payload(
        now=datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    )
    assert payload["metrics"]["total_signals"] == 0
    assert payload["metrics"]["win_rate"] is None
    assert payload["top_pairs"] == []
    assert payload["top_strategies"] == []
    assert payload["records"] == []
    assert payload["metrics"]["by_signal_grade"]["strong"]["win_rate"] is None


def test_weekly_report_uses_utc_dates_health_trend_and_writes_exports(monkeypatch, tmp_path):
    configure_database(monkeypatch, tmp_path)
    now_aware = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    add_signal(now_aware, "<img src=x onerror=alert(1)>", 1, "WIN", "STRONG", "EMA_RSI_V1")
    add_signal(now_aware, "EUR/USD", 3, "LOSS", "WEAK", "SCORE_ENGINE_V2")
    add_signal(now_aware, "EUR/USD", 10, "PENDING", "MODERATE", "BREAKOUT_V3")
    weekly_report.record_health_snapshot(
        {"health_score": 88, "status": "HEALTHY", "error_count": 0},
        captured_at=now_aware - timedelta(days=2),
    )
    weekly_report.record_health_snapshot(
        {"health_score": 40, "status": "WARNING", "error_count": 3},
        captured_at=now_aware - timedelta(days=9),
    )

    report = weekly_report.generate_weekly_report(now=datetime(2026, 11, 11, 12, 0))
    assert report["period"]["end_utc"] == "2026-11-11T12:00:00+00:00"
    assert report["total_signals"] == 2
    assert report["wins"] == 1
    assert report["losses"] == 1
    assert report["overall_win_rate"] == 50.0
    assert report["health_observations"] == 1
    trend_dates = [row["date"] for row in report["health_score_trend"]]
    assert trend_dates == [row["date"] for row in report["win_rate_trend"]]
    observation_days = [
        row["date"] for row in report["health_score_trend"] if row["observations"]
    ]
    assert observation_days == ["2026-11-09"]

    json_path = report["exports"]["json"]
    html_path = report["exports"]["html"]
    with open(json_path, encoding="utf-8") as source:
        stored = json.load(source)
    with open(html_path, encoding="utf-8") as source:
        html = source.read()
    assert stored["total_signals"] == 2
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html


def test_weekly_report_handles_no_signal_or_health_rows(monkeypatch, tmp_path):
    configure_database(monkeypatch, tmp_path)
    report = weekly_report.generate_weekly_report(
        now=datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    )
    assert report["total_signals"] == 0
    assert report["overall_win_rate"] is None
    assert report["strongest_pair"] is None
    assert report["weakest_pair"] is None
    assert report["health_observations"] == 0
    assert all(row["average_health_score"] is None for row in report["health_score_trend"])


def test_weekly_report_health_snapshot_clamps_score_and_stores_naive_time(monkeypatch, tmp_path):
    database = configure_database(monkeypatch, tmp_path)
    captured = datetime(2026, 11, 11, 10, 30)
    weekly_report.record_health_snapshot(
        {"health_score": 500, "status": "HEALTHY", "error_count": 2},
        captured_at=captured,
    )
    with sqlite3.connect(database) as conn:
        row = conn.execute(
            "SELECT captured_at, health_score FROM weekly_health_snapshots"
        ).fetchone()
    assert row == ("2026-11-11T10:30:00+00:00", 100)


def test_weekly_report_loads_empty_health_when_table_does_not_exist(monkeypatch, tmp_path):
    configure_database(monkeypatch, tmp_path)
    # The signal-history schema exists, but the additive weekly health table has not been created.
    start = datetime(2026, 11, 4, tzinfo=timezone.utc)
    end = datetime(2026, 11, 11, tzinfo=timezone.utc)
    signals, health = weekly_report._load_data(start, end)
    assert signals == []
    assert health == []
