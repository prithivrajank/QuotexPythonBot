"""Offline tests for the unofficial adapter's read-only data path.

No test starts a broker session, reads a browser profile, or uses credentials.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future

import pytest

import quotexapi_provider as provider


@pytest.fixture(autouse=True)
def clean_adapter_state(monkeypatch):
    monkeypatch.setattr(provider, "_connected", False)
    monkeypatch.setattr(provider, "_events", 0)
    monkeypatch.setattr(provider, "_rows", defaultdict(list))
    monkeypatch.setattr(provider, "_ticks", {})
    monkeypatch.setattr(provider, "_seen", set())
    monkeypatch.setenv("FOREX_SYMBOLS", "EURUSD_otc,EURUSD")
    monkeypatch.setenv("QUOTEX_ACCOUNT", "demo")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "true")


def test_symbols_are_normalized_and_deduplicated(monkeypatch):
    monkeypatch.setenv("FOREX_SYMBOLS", "eur/usd_otc,EURUSD_OTC,GBP-USD")
    assert provider._symbols() == ["EURUSD_otc", "GBPUSD"]


@pytest.mark.parametrize(
    "payload",
    [
        {"open": 1.0, "high": float("inf"), "low": 0.9, "close": 1.1, "time": 100},
        {"open": 1.0, "high": 1.2, "low": 0.9, "close": float("nan"), "time": 100},
        {"open": 0, "high": 1.2, "low": 0.9, "close": 1.1, "time": 100},
        {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "time": float("inf")},
        {"open": 1.0, "high": 0.9, "low": 0.8, "close": 0.85, "time": 100},
    ],
)
def test_candle_parser_rejects_nonfinite_or_invalid_values(payload):
    assert provider._candle_from_payload(payload, "EURUSD_otc") is None


def test_candle_parser_accepts_nested_ohlc_and_millisecond_time():
    payload = {"history": [{
        "o": "1.1", "h": "1.3", "l": "1.0", "c": "1.2",
        "timestamp": 1_700_000_000_000,
    }]}
    result = provider._candle_from_payload(payload, "EURUSD_otc")
    assert result is not None
    assert result["time"] == 1_700_000_000
    assert result["timeframe_seconds"] == 60
    assert result["market_type"] == "Quotex OTC"


@pytest.mark.parametrize(
    "quote",
    [
        {"asset": "EURUSD_otc", "price": float("inf"), "time": 100},
        {"asset": "EURUSD_otc", "price": 1.1, "time": float("inf")},
        {"asset": "EURUSD_otc", "price": float("nan"), "time": 100},
        {"asset": "EURUSD_otc", "price": -1, "time": 100},
        {"asset": "GBPUSD_otc", "price": 1.1, "time": 100},
        {"price": 1.1, "time": 100},
    ],
)
def test_quote_handler_ignores_invalid_or_unconfigured_quotes(quote):
    provider._on_quote(quote)
    assert provider.get_ticks() == []


def test_quote_handler_stores_only_matching_finite_quote():
    provider._on_quote({
        "asset": "eurusd_otc", "price": "1.1234",
        "time": 1_700_000_000_000,
    })
    ticks = provider.get_ticks()
    assert len(ticks) == 1
    assert ticks[0]["symbol"] == "EURUSD_otc"
    assert ticks[0]["price"] == 1.1234
    assert ticks[0]["time"] == 1_700_000_000


def test_event_handler_requires_symbol_and_updates_duplicate_candle():
    provider._on_event({"open": 1, "high": 1.2, "low": 0.9, "close": 1.1, "time": 100})
    provider._on_event({
        "asset": "EURUSD_otc", "open": 1.0, "high": 1.2,
        "low": 0.9, "close": 1.1, "time": 100,
    })
    provider._on_event({
        "asset": "EURUSD_otc", "open": 1.0, "high": 1.3,
        "low": 0.9, "close": 1.25, "time": 100,
    })
    provider._on_event({
        "asset": "GBPUSD_otc", "open": 1.0, "high": 1.2,
        "low": 0.9, "close": 1.1, "time": 100,
    })
    assert provider._events == 4
    assert len(provider._rows["EURUSD_otc"]) == 1
    assert provider._rows["EURUSD_otc"][0]["close"] == 1.25
    assert provider._rows["GBPUSD_otc"] == []


def test_get_ticks_fails_closed_for_real_account_configuration(monkeypatch):
    provider._ticks["EURUSD_otc"] = {"symbol": "EURUSD_otc", "price": 1.1, "time": 100}
    monkeypatch.setenv("QUOTEX_ACCOUNT", "real")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "false")
    assert provider.get_ticks() == []


def test_connection_status_is_passive_by_default(monkeypatch):
    monkeypatch.delenv("QUOTEX_SSID", raising=False)
    monkeypatch.setattr(
        provider, "_ensure_connection",
        lambda: pytest.fail("passive status must not start a connection"),
    )
    status = provider.connection_status()
    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["credentials_configured"] is False
    assert status["read_only"] is True


def test_candle_fetch_does_not_echo_connection_exception_text(monkeypatch):
    future = Future()
    future.set_exception(RuntimeError("sensitive connection detail"))
    monkeypatch.setattr(provider, "_ensure_connection", lambda: future)
    monkeypatch.setattr(provider, "_rows", defaultdict(list))
    with pytest.raises(RuntimeError, match="RuntimeError") as exc:
        provider.get_candles("EURUSD_otc", 60, 1)
    assert "sensitive connection detail" not in str(exc.value)
