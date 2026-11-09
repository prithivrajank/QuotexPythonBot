"""Unit tests for adaptive pair performance classification."""
from __future__ import annotations

from typing import Any

import pair_performance


def _records(wins: int, losses: int) -> list[dict[str, Any]]:
    """Build newest-first completed outcome records."""
    return (
        [{"outcome": "WIN", "signal_score": 9} for _ in range(wins)]
        + [{"outcome": "LOSS", "signal_score": 4} for _ in range(losses)]
    )


def _reset_cache() -> None:
    """Expire the process-local cache between tests."""
    with pair_performance._cache_lock:
        pair_performance._cache.update(expires_at=0.0, payload=None)


def test_classification_thresholds() -> None:
    """Apply sample-size-aware status thresholds."""
    assert pair_performance._classify(70.0, 20) == "PRIORITY"
    assert pair_performance._classify(60.0, 10) == "NORMAL"
    assert pair_performance._classify(50.0, 10) == "WATCHLIST"
    assert pair_performance._classify(40.0, 15) == "DISABLED"
    assert pair_performance._classify(20.0, 14) == "WATCHLIST"
    assert pair_performance._classify(None, 0) == "WATCHLIST"


def test_performance_build_uses_completed_outcomes(monkeypatch: Any) -> None:
    """Pending outcomes do not affect the calculated win rate."""
    monkeypatch.setattr(
        pair_performance,
        "get_pair_performance_records",
        lambda: {"EURUSD": _records(14, 6) + [{"outcome": "PENDING", "signal_score": 8}]},
    )
    result = pair_performance._build_performance()["EURUSD"]
    assert result["scored_trades"] == 20
    assert result["total_signals"] == 21
    assert result["win_rate"] == 70.0
    assert result["status"] == "PRIORITY"
    assert result["average_signal_score"] is not None


def test_disabled_pair_is_filtered_to_wait(monkeypatch: Any) -> None:
    """A disabled pair cannot retain an actionable CALL/PUT recommendation."""
    monkeypatch.setattr(pair_performance, "get_pair_status", lambda symbol: "DISABLED")
    original = {"signal": "CALL", "reason": "old", "expiry_recommendation_minutes": 1}
    filtered = pair_performance.filter_analysis("EURUSD", original)
    assert filtered["signal"] == "WAIT"
    assert filtered["pair_filter_applied"] is True
    assert filtered["expiry_recommendation_minutes"] is None
    assert original["signal"] == "CALL"


def test_summary_sorts_best_and_worst(monkeypatch: Any) -> None:
    """Return ordered top and worst pair lists."""
    monkeypatch.setattr(
        pair_performance,
        "get_pair_performance",
        lambda: {
            "A": {"symbol": "A", "win_rate": 80.0, "scored_trades": 20, "status": "PRIORITY"},
            "B": {"symbol": "B", "win_rate": 40.0, "scored_trades": 20, "status": "DISABLED"},
        },
    )
    summary = pair_performance.pair_performance_summary()
    assert summary["top_performing_pairs"][0]["symbol"] == "A"
    assert summary["worst_performing_pairs"][0]["symbol"] == "B"
