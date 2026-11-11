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



def test_build_performance_handles_empty_and_unscored_symbols(monkeypatch: Any) -> None:
    """Symbols with no WIN/LOSS outcomes remain WATCHLIST with null rates."""
    monkeypatch.setattr(
        pair_performance,
        "get_pair_performance_records",
        lambda: {
            "EMPTY": [],
            "PENDING": [{"outcome": "PENDING", "signal_score": None}],
        },
    )

    result = pair_performance._build_performance()

    assert result["EMPTY"]["total_signals"] == 0
    assert result["EMPTY"]["scored_trades"] == 0
    assert result["EMPTY"]["win_rate"] is None
    assert result["EMPTY"]["recent_20_signal_win_rate"] is None
    assert result["EMPTY"]["average_signal_score"] is None
    assert result["EMPTY"]["status"] == "WATCHLIST"
    assert result["PENDING"]["total_signals"] == 1
    assert result["PENDING"]["status"] == "WATCHLIST"


def test_build_performance_calculates_recent_window_and_average_score(
    monkeypatch: Any,
) -> None:
    """Recent win rate uses only the newest 20 scored outcomes."""
    records = (
        [{"outcome": "LOSS", "signal_score": 4} for _ in range(20)]
        + [{"outcome": "WIN", "signal_score": 8} for _ in range(2)]
        + [{"outcome": "PENDING", "signal_score": 10}]
    )
    monkeypatch.setattr(
        pair_performance,
        "get_pair_performance_records",
        lambda: {"EURUSD": records},
    )

    result = pair_performance._build_performance()["EURUSD"]

    assert result["total_signals"] == 23
    assert result["scored_trades"] == 22
    assert result["wins"] == 2
    assert result["losses"] == 20
    assert result["win_rate"] == 9.09
    assert result["recent_20_scored_signals"] == 20
    assert result["recent_20_signal_win_rate"] == 0.0
    assert result["average_signal_score"] == 5.64
    assert result["status"] == "DISABLED"


def test_get_pair_performance_cache_hit_force_refresh_and_expiry(
    monkeypatch: Any,
) -> None:
    """Cache hits avoid rebuilds; force refresh and TTL expiry rebuild the payload."""
    _reset_cache()
    clock = {"now": 100.0}
    builds: list[int] = []

    def fake_build() -> dict[str, dict[str, Any]]:
        builds.append(len(builds) + 1)
        return {"EURUSD": {"status": "NORMAL", "build": len(builds)}}

    monkeypatch.setattr(pair_performance.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(pair_performance, "_build_performance", fake_build)

    try:
        first = pair_performance.get_pair_performance()
        assert first["EURUSD"]["build"] == 1
        assert len(builds) == 1

        # Returned rows are copies, so callers cannot mutate the cached mapping.
        first["EURUSD"]["status"] = "MUTATED"
        clock["now"] = 399.999
        cached = pair_performance.get_pair_performance()
        assert cached["EURUSD"]["status"] == "NORMAL"
        assert cached["EURUSD"]["build"] == 1
        assert len(builds) == 1

        refreshed = pair_performance.get_pair_performance(force_refresh=True)
        assert refreshed["EURUSD"]["build"] == 2
        assert len(builds) == 2

        # The refresh at 399.999 expires exactly at 699.999.
        clock["now"] = 699.999
        still_cached = pair_performance.get_pair_performance()
        assert still_cached["EURUSD"]["build"] == 2
        assert len(builds) == 2

        clock["now"] = 700.0
        expired = pair_performance.get_pair_performance()
        assert expired["EURUSD"]["build"] == 3
        assert len(builds) == 3
    finally:
        _reset_cache()


def test_get_pair_status_normalizes_symbol_and_defaults_unknown_to_watchlist(
    monkeypatch: Any,
) -> None:
    """Symbol matching trims whitespace and ignores case."""
    monkeypatch.setattr(
        pair_performance,
        "get_pair_performance",
        lambda: {
            " eurusd ": {"status": "PRIORITY"},
            "GBPUSD": {"status": "DISABLED"},
        },
    )

    assert pair_performance.get_pair_status("  EurUsd ") == "PRIORITY"
    assert pair_performance.get_pair_status("gbpusd") == "DISABLED"
    assert pair_performance.get_pair_status("UNKNOWN") == "WATCHLIST"


def test_filter_analysis_preserves_actionable_analysis_for_enabled_pair(
    monkeypatch: Any,
) -> None:
    """Non-disabled pairs retain the original analysis object unchanged."""
    monkeypatch.setattr(
        pair_performance, "get_pair_status", lambda _symbol: "NORMAL"
    )
    analysis = {"signal": "CALL", "reason": "trend aligned"}

    result = pair_performance.filter_analysis("EURUSD", analysis)

    assert result is analysis
    assert result == {"signal": "CALL", "reason": "trend aligned"}


def test_summary_handles_empty_performance(monkeypatch: Any) -> None:
    """An empty performance cache produces empty dashboard lists."""
    monkeypatch.setattr(pair_performance, "get_pair_performance", lambda: {})

    summary = pair_performance.pair_performance_summary()

    assert summary["pairs"] == []
    assert summary["top_performing_pairs"] == []
    assert summary["worst_performing_pairs"] == []
    assert summary["disabled_pairs"] == []
    assert summary["priority_pairs"] == []
    assert summary["cache_ttl_seconds"] == pair_performance.CACHE_TTL_SECONDS


def test_summary_limits_and_sorts_lists_and_status_groups(
    monkeypatch: Any,
) -> None:
    """Dashboard rankings honor tie-breakers, top-five limits, and status groups."""
    rows = {
        "A": {"symbol": "A", "win_rate": 90.0, "scored_trades": 20, "status": "PRIORITY"},
        "B": {"symbol": "B", "win_rate": 90.0, "scored_trades": 30, "status": "PRIORITY"},
        "C": {"symbol": "C", "win_rate": 50.0, "scored_trades": 15, "status": "WATCHLIST"},
        "D": {"symbol": "D", "win_rate": 30.0, "scored_trades": 20, "status": "DISABLED"},
        "E": {"symbol": "E", "win_rate": 70.0, "scored_trades": 10, "status": "NORMAL"},
        "F": {"symbol": "F", "win_rate": 60.0, "scored_trades": 18, "status": "NORMAL"},
        "G": {"symbol": "G", "win_rate": 10.0, "scored_trades": 20, "status": "DISABLED"},
        "H": {"symbol": "H", "win_rate": None, "scored_trades": 0, "status": "WATCHLIST"},
    }
    monkeypatch.setattr(
        pair_performance, "get_pair_performance", lambda: rows
    )

    summary = pair_performance.pair_performance_summary()

    assert [row["symbol"] for row in summary["top_performing_pairs"]] == [
        "B", "A", "E", "F", "C"
    ]
    assert [row["symbol"] for row in summary["worst_performing_pairs"]] == [
        "G", "D", "C", "F", "E"
    ]
    assert [row["symbol"] for row in summary["disabled_pairs"]] == ["D", "G"]
    assert [row["symbol"] for row in summary["priority_pairs"]] == ["A", "B"]
    assert len(summary["pairs"]) == 8
