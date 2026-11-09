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
