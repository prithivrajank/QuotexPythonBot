"""Tests for candle freshness gates and safe runtime behavior."""
from __future__ import annotations

import time

import pytest

import runtime
from data_collector import MarketDataError


def test_latest_candle_accepts_current_and_recently_closed_candles():
    now = 10_000
    assert runtime.validate_latest_candle({"time": now - 20}, 60, now) == 20
    assert runtime.validate_latest_candle({"time": now - 120}, 60, now) == 120
    # Small clock skew is tolerated but is never reported as negative age.
    assert runtime.validate_latest_candle({"time": now + 3}, 60, now) == 0


@pytest.mark.parametrize(
    "candle",
    [{}, {"time": None}, {"time": "not-a-timestamp"}, {"time": 0}, {"time": -1}],
)
def test_latest_candle_rejects_missing_or_invalid_timestamps(candle):
    with pytest.raises(MarketDataError, match="timestamp"):
        runtime.validate_latest_candle(candle, 60, now_timestamp=10_000)


def test_latest_candle_rejects_future_dated_candles():
    with pytest.raises(MarketDataError, match="future-dated"):
        runtime.validate_latest_candle(
            {"time": 10_006}, 60, now_timestamp=10_000
        )


def test_latest_candle_rejects_stale_candles():
    with pytest.raises(MarketDataError, match="stale"):
        runtime.validate_latest_candle(
            {"time": 9_879}, 60, now_timestamp=10_000
        )


def test_stale_provider_candle_never_reaches_strategy_or_history(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD")
    stale_candles = [{
        "time": int(time.time()) - 121,
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "market_type": "standard forex, not Quotex OTC",
    }]
    monkeypatch.setattr(runtime, "get_candles", lambda *args: stale_candles)
    monkeypatch.setattr(
        runtime,
        "analyze_with_strategy",
        lambda *args, **kwargs: pytest.fail("stale candles must not be analyzed"),
    )
    monkeypatch.setattr(
        runtime,
        "record_signal",
        lambda *args, **kwargs: pytest.fail("stale candles must not be recorded"),
    )
    monkeypatch.setattr(
        runtime,
        "score_due_outcomes",
        lambda *args, **kwargs: pytest.fail("stale candles must not be scored"),
    )
    monkeypatch.setattr(runtime, "record_candle", lambda *args: None)
    monkeypatch.setattr(runtime, "record_exception", lambda *args: None)
    monkeypatch.setattr(runtime, "set_component", lambda *args: None)

    result = runtime.refresh_snapshot("EUR/USD")

    assert result["available"] is False
    assert "stale" in result["message"].lower()
    assert result["symbol"] == "EUR/USD"
