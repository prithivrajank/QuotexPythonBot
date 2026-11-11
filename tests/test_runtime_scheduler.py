"""Scheduler and remaining runtime branch tests."""
from __future__ import annotations

import asyncio

import pytest

import runtime


@pytest.mark.parametrize("timeframe", [0, -1, True, 1.5])
def test_validate_latest_candle_rejects_invalid_timeframe_types(timeframe):
    with pytest.raises(ValueError, match="positive integer"):
        runtime.validate_latest_candle({"time": 10_000}, timeframe, 10_000)


def test_refresh_snapshot_rotates_watchlist_when_symbol_not_supplied(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD,GBP/USD")
    monkeypatch.setattr(runtime, "_next_symbol_index", 0)
    monkeypatch.setattr(runtime, "_snapshots", {})
    calls = []

    def fail_for_symbol(symbol, *args):
        calls.append(symbol)
        raise runtime.MarketDataError("test provider offline")

    monkeypatch.setattr(runtime, "get_candles", fail_for_symbol)
    monkeypatch.setattr(runtime, "record_exception", lambda *a: None)
    monkeypatch.setattr(runtime, "set_component", lambda *a: None)

    first = runtime.refresh_snapshot()
    second = runtime.refresh_snapshot()

    assert calls == ["EUR/USD", "GBP/USD"]
    assert first["symbol"] == "EUR/USD"
    assert second["symbol"] == "GBP/USD"


def _run_scheduler_with_cancel(monkeypatch, *, enabled, provider, expected_delay):
    monkeypatch.setattr(runtime, "_bot_enabled", enabled)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    delays = []

    async def stop_on_sleep(delay):
        delays.append(delay)
        raise asyncio.CancelledError()

    monkeypatch.setattr(runtime.asyncio, "sleep", stop_on_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.scheduled_refresh_loop())
    assert delays == [expected_delay]


def test_scheduler_pauses_when_bot_is_off(monkeypatch):
    _run_scheduler_with_cancel(
        monkeypatch, enabled=False, provider="twelve_data", expected_delay=5
    )


def test_scheduler_uses_slow_manual_interval_for_otcharts(monkeypatch):
    _run_scheduler_with_cancel(
        monkeypatch, enabled=True, provider="otcharts", expected_delay=60
    )


def test_scheduler_uses_slow_manual_interval_for_a11ksa(monkeypatch):
    _run_scheduler_with_cancel(
        monkeypatch, enabled=True, provider="a11ksa", expected_delay=60
    )


def test_scheduler_refreshes_enabled_standard_provider(monkeypatch):
    monkeypatch.setattr(runtime, "_bot_enabled", True)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    calls = []

    async def fake_to_thread(func):
        calls.append(func)
        return {"available": True}

    async def stop_on_sleep(delay):
        assert delay == runtime.refresh_interval_seconds()
        raise asyncio.CancelledError()

    monkeypatch.setattr(runtime.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(runtime.asyncio, "sleep", stop_on_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.scheduled_refresh_loop())
    assert calls == [runtime.refresh_snapshot]


def test_scheduler_recovers_from_unexpected_iteration_error(monkeypatch):
    monkeypatch.setattr(runtime, "_bot_enabled", True)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    delays = []

    async def fail_to_thread(func):
        raise RuntimeError("unexpected scheduler error")

    async def stop_on_retry(delay):
        delays.append(delay)
        raise asyncio.CancelledError()

    monkeypatch.setattr(runtime.asyncio, "to_thread", fail_to_thread)
    monkeypatch.setattr(runtime.asyncio, "sleep", stop_on_retry)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.scheduled_refresh_loop())
    assert delays == [5]
