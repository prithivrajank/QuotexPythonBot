"""Unit tests for historical backtesting and expiry comparisons."""
from __future__ import annotations

from typing import Any

import backtester


def make_candles(count: int = 40) -> list[dict[str, float | int]]:
    """Create deterministic rising OHLC candles for backtest tests."""
    rows: list[dict[str, float | int]] = []
    price = 1.0
    for index in range(count):
        close = price + 0.001
        rows.append({
            "time": 1_700_000_000 + index * 60,
            "open": price,
            "high": close + 0.0002,
            "low": price - 0.0002,
            "close": close,
        })
        price = close
    return rows


def test_run_backtest_uses_registered_strategy_and_returns_comparison(
    monkeypatch: Any,
) -> None:
    """Check result compatibility, expiry coverage, and analyzer invocation."""
    monkeypatch.setattr(
        backtester,
        "analyze_with_strategy",
        lambda candles, name: {"signal": "CALL", "strategy_name": name},
    )
    result = backtester.run_backtest(make_candles(), "EUR/USD", expiry=1)
    assert result["symbol"] == "EUR/USD"
    assert result["strategy_name"] == "SCORE_ENGINE_V2"
    assert result["expiry"] == 1
    assert [item["expiry"] for item in result["expiry_comparison"]] == [1, 2, 3]
    assert result["wins"] > 0
    assert result["win_rate"] == 100.0


def test_run_backtest_rejects_unsupported_expiry() -> None:
    """Reject expiry values outside the supported candle horizons."""
    try:
        backtester.run_backtest(make_candles(), "EUR/USD", expiry=5)
    except ValueError as exc:
        assert "expiry must be" in str(exc)
    else:
        raise AssertionError("Expected unsupported expiry to raise ValueError")


def test_run_backtest_requires_sufficient_history() -> None:
    """Reject data too short for the longest supported expiry."""
    try:
        backtester.run_backtest(make_candles(32), "EUR/USD")
    except ValueError as exc:
        assert "At least" in str(exc)
    else:
        raise AssertionError("Expected insufficient history to raise ValueError")



def test_evaluate_expiry_counts_wait_put_wins_and_losses() -> None:
    """Score directional CALL/PUT results and count WAIT decisions separately."""
    candles = make_candles(35)
    # The decision indexes for expiry=1 are 29 through 33.
    candles[30]["close"] = 1.0
    candles[31]["close"] = 1.1
    candles[32]["close"] = 1.0
    candles[33]["close"] = 1.1
    candles[34]["close"] = 1.1
    signals = iter(["WAIT", "CALL", "PUT", "PUT", "CALL"])

    result = backtester._evaluate_expiry(
        candles, 1, lambda _history: {"signal": next(signals)}
    )

    assert result["total_signals"] == 5
    assert result["wait_signals"] == 1
    assert result["call_signals"] == 2
    assert result["put_signals"] == 2
    assert result["wins"] == 2
    assert result["losses"] == 1
    assert result["win_rate"] == 66.67
    assert result["gross_profit_pct"] == 19.090909
    assert result["gross_loss_pct"] == 10.0
    assert result["profit_factor"] == 1.9091


def test_evaluate_expiry_skips_non_positive_entry_and_returns_empty_rates() -> None:
    """A non-positive entry is counted as a signal but excluded from scoring."""
    candles = make_candles(31)
    candles[29]["close"] = 0.0

    result = backtester._evaluate_expiry(
        candles, 1, lambda _history: {"signal": "CALL"}
    )

    assert result["total_signals"] == 1
    assert result["call_signals"] == 1
    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["win_rate"] is None
    assert result["profit_factor"] is None
    assert result["gross_profit_pct"] == 0.0
    assert result["gross_loss_pct"] == 0.0


def test_run_strategy_backtest_without_scored_results_has_no_best_expiry(
    monkeypatch: Any,
) -> None:
    """When every strategy decision is WAIT, no expiry is declared best."""
    monkeypatch.setattr(
        backtester,
        "analyze_with_strategy",
        lambda _candles, _name: {"signal": "WAIT"},
    )

    result = backtester.run_strategy_backtest(
        make_candles(33), "EUR/USD", "SCORE_ENGINE_V2"
    )

    assert result["best_expiry"] is None
    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["win_rate"] is None
    assert all(item["win_rate"] is None for item in result["expiry_comparison"])


def test_run_all_strategies_ranks_by_win_rate_then_sample_size(
    monkeypatch: Any,
) -> None:
    """All strategy results are ranked with sample size as the tie-breaker."""
    names = ["SMALL", "LARGE", "LOWER", "UNSCORED"]
    results = {
        "SMALL": {"strategy_name": "SMALL", "win_rate": 80.0, "wins": 4, "losses": 1},
        "LARGE": {"strategy_name": "LARGE", "win_rate": 80.0, "wins": 8, "losses": 2},
        "LOWER": {"strategy_name": "LOWER", "win_rate": 60.0, "wins": 3, "losses": 2},
        "UNSCORED": {"strategy_name": "UNSCORED", "win_rate": None, "wins": 0, "losses": 0},
    }
    monkeypatch.setattr(
        backtester, "list_strategies", lambda: [{"name": name} for name in names]
    )
    monkeypatch.setattr(
        backtester,
        "run_strategy_backtest",
        lambda _candles, _symbol, name, _expiry: dict(results[name]),
    )

    report = backtester.run_all_strategies(make_candles(), "EUR/USD", expiry=2)

    assert report["symbol"] == "EUR/USD"
    assert report["expiry"] == 2
    assert [item["strategy_name"] for item in report["strategies"]] == [
        "LARGE", "SMALL", "LOWER", "UNSCORED"
    ]
    assert [item["rank"] for item in report["strategies"]] == [1, 2, 3, 4]
    assert report["leader"] == "LARGE"


def test_run_all_strategies_empty_registry_has_no_leader(monkeypatch: Any) -> None:
    """An empty strategy registry returns an empty ranking and no leader."""
    monkeypatch.setattr(backtester, "list_strategies", lambda: [])

    report = backtester.run_all_strategies(make_candles(), "EUR/USD")

    assert report["strategies"] == []
    assert report["leader"] is None


def test_run_strategy_comparison_is_alias_for_all_strategy_report(
    monkeypatch: Any,
) -> None:
    """The named comparison API delegates its arguments unchanged."""
    expected = {"symbol": "EUR/USD", "expiry": 3, "strategies": []}
    calls = []
    monkeypatch.setattr(
        backtester,
        "run_all_strategies",
        lambda candles, symbol, expiry: calls.append((candles, symbol, expiry)) or expected,
    )
    candles = make_candles()

    result = backtester.run_strategy_comparison(candles, "EUR/USD", expiry=3)

    assert result is expected
    assert calls == [(candles, "EUR/USD", 3)]
