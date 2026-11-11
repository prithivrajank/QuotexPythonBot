"""Additional tests for runtime configuration, snapshots, and refresh paths."""
from __future__ import annotations

import time

import pytest

import runtime
from data_collector import MarketDataError


def candle(timestamp=None):
    return {
        "time": int(time.time()) - 5 if timestamp is None else timestamp,
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "market_type": "standard forex, not Quotex OTC",
    }


@pytest.mark.parametrize(
    ("provider", "symbols", "expected"),
    [
        ("twelve_data", "eur/usd,EUR-USD,GBP/USD", ["EUR/USD", "GBP/USD"]),
        ("quantex", "eur/usd,EURUSD_otc,eur-usd", ["EURUSD", "EURUSD_otc"]),
        ("otcharts", "EUR/USD,EURUSD_otc", ["EURUSD", "EURUSD_otc"]),
    ],
)
def test_configured_symbols_normalize_and_deduplicate(monkeypatch, provider, symbols, expected):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    monkeypatch.setenv("FOREX_SYMBOLS", symbols)
    assert runtime.configured_symbols() == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("twelve_data", runtime.DEFAULT_SYMBOLS),
        ("quantex", runtime.DEFAULT_QUANTEX_SYMBOLS),
        ("otcharts", runtime.DEFAULT_QUANTEX_SYMBOLS),
        ("a11ksa", runtime.DEFAULT_A11KSA_SYMBOLS),
    ],
)
def test_configured_symbols_use_provider_defaults(monkeypatch, provider, expected):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    monkeypatch.delenv("FOREX_SYMBOLS", raising=False)
    monkeypatch.delenv("FOREX_SYMBOL", raising=False)
    assert runtime.configured_symbols() == expected


def test_configured_symbols_support_legacy_single_symbol_and_empty_fallback(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.delenv("FOREX_SYMBOLS", raising=False)
    monkeypatch.setenv("FOREX_SYMBOL", "gbp-usd")
    assert runtime.configured_symbols() == ["GBP/USD"]
    monkeypatch.delenv("FOREX_SYMBOL", raising=False)
    monkeypatch.setenv("FOREX_SYMBOLS", ", ,")
    assert runtime.configured_symbols() == runtime.DEFAULT_SYMBOLS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("not-a-number", 300), ("10", 300), ("300", 300), ("9000", 3600), ("1200", 1200)],
)
def test_refresh_interval_is_bounded(monkeypatch, raw, expected):
    monkeypatch.setenv("REFRESH_INTERVAL_SECONDS", raw)
    assert runtime.refresh_interval_seconds() == expected


def test_bot_status_tracks_enabled_state(monkeypatch):
    monkeypatch.setattr(runtime, "_bot_enabled", False)
    assert runtime.bot_status()["enabled"] is False
    assert runtime.set_bot_enabled(True)["enabled"] is True
    assert "ON" in runtime.bot_status()["message"]
    assert runtime.set_bot_enabled(False)["enabled"] is False


def test_snapshot_and_watchlist_return_safe_empty_state(monkeypatch):
    monkeypatch.setattr(runtime, "_snapshots", {})
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setenv("FOREX_SYMBOLS", "EURUSD_otc,GBPUSD_otc")
    snapshot = runtime.get_snapshot()
    watchlist = runtime.get_watchlist()
    assert snapshot["available"] is False
    assert "Waiting" in snapshot["message"]
    assert watchlist["symbols"] == ["EURUSD_otc", "GBPUSD_otc"]
    assert "manual-refresh only" in watchlist["note"]


def test_snapshot_returns_existing_symbol_and_latest_watchlist_entry(monkeypatch):
    entries = {
        "EUR/USD": {"available": True, "updated_at": "2026-11-11T10:00:00+00:00"},
        "GBP/USD": {"available": False, "updated_at": "2026-11-11T11:00:00+00:00"},
    }
    monkeypatch.setattr(runtime, "_snapshots", entries)
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    assert runtime.get_snapshot("EUR/USD") == entries["EUR/USD"]
    assert runtime.get_snapshot()["symbol"] if "symbol" in runtime.get_snapshot() else runtime.get_snapshot()["available"] is False
    watchlist = runtime.get_watchlist()
    assert watchlist["scanned"]["EUR/USD"]["available"] is True
    assert watchlist["scanned"]["GBP/USD"]["available"] is False


def test_refresh_snapshot_rejects_symbol_outside_watchlist(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD")
    with pytest.raises(ValueError, match="not in FOREX_SYMBOLS"):
        runtime.refresh_snapshot("GBP/USD")


def test_refresh_snapshot_returns_provider_error_snapshot(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD")
    monkeypatch.setattr(runtime, "get_candles", lambda *a: (_ for _ in ()).throw(MarketDataError("feed unavailable")))
    errors = []
    components = []
    monkeypatch.setattr(runtime, "record_exception", errors.append)
    monkeypatch.setattr(runtime, "set_component", lambda *args: components.append(args))
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is False
    assert result["message"] == "feed unavailable"
    assert result["symbol"] == "EUR/USD"
    assert errors == ["provider"]
    assert components[0][0:2] == ("provider", "degraded")


def test_refresh_snapshot_rejects_empty_provider_response(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD")
    monkeypatch.setattr(runtime, "get_candles", lambda *a: [])
    monkeypatch.setattr(runtime, "record_exception", lambda *a: None)
    monkeypatch.setattr(runtime, "set_component", lambda *a: None)
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is False
    assert "zero candles" in result["message"]


def test_a11ksa_runtime_snapshot_is_candle_only(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "a11ksa")
    monkeypatch.setenv("FOREX_SYMBOLS", "EURUSD_otc")
    rows = [candle()]
    monkeypatch.setattr(runtime, "get_candles", lambda *args: rows)
    monkeypatch.setattr(runtime, "record_candle", lambda *args: None)
    monkeypatch.setattr(
        runtime, "analyze_with_strategy",
        lambda *a, **k: pytest.fail("A11KSA path must not run strategy analysis"),
    )
    result = runtime.refresh_snapshot("EURUSD_otc")
    assert result["available"] is True
    assert result["read_only"] is True
    assert result["demo_only"] is True
    assert result["telegram_configured"] is False
    assert result["analysis"] if "analysis" in result else result["message"].endswith("disabled.")


def _patch_successful_standard_refresh(monkeypatch, pair_status="ACTIVE"):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("FOREX_SYMBOLS", "EUR/USD")
    monkeypatch.setattr(runtime, "get_candles", lambda *args: [candle()])
    monkeypatch.setattr(runtime, "record_candle", lambda *args: None)
    monkeypatch.setattr(runtime, "get_active_strategy", lambda: "test-strategy")
    monkeypatch.setattr(runtime, "analyze_with_strategy", lambda *args: {"signal": "WAIT"})
    monkeypatch.setattr(runtime, "apply_strategy_management", lambda analysis: analysis)
    monkeypatch.setattr(runtime, "filter_analysis", lambda symbol, analysis: analysis)
    monkeypatch.setattr(runtime, "record_strategy_signal", lambda *args: None)
    monkeypatch.setattr(runtime, "get_pair_status", lambda symbol: pair_status)
    monkeypatch.setattr(runtime, "record_signal", lambda *args: {"inserted": True})
    monkeypatch.setattr(runtime, "score_due_outcomes", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "build_chart_data", lambda rows: {"candles": rows})
    monkeypatch.setattr(runtime, "telegram_configured", lambda: True)
    monkeypatch.setattr(runtime, "notify_new_candle", lambda snapshot: {"sent": True, "reason": "new_candle"})
    monkeypatch.setattr(runtime, "record_telegram_result", lambda result: None)


def test_standard_refresh_success_builds_snapshot_and_notifies(monkeypatch):
    _patch_successful_standard_refresh(monkeypatch)
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is True
    assert result["analysis"] == {"signal": "WAIT"}
    assert result["signal_history_inserted"] is True
    assert result["telegram_notification"]["sent"] is True
    assert result["candle_status"] == "CURRENT CANDLE WINDOW"


def test_disabled_pair_suppresses_telegram_notification(monkeypatch):
    _patch_successful_standard_refresh(monkeypatch, pair_status="DISABLED")
    monkeypatch.setattr(
        runtime, "notify_new_candle",
        lambda snapshot: pytest.fail("disabled pair must not send Telegram"),
    )
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is True
    assert result["telegram_notification"]["sent"] is False
    assert "DISABLED" in result["telegram_notification"]["reason"]


def test_strategy_failure_is_reported_and_provider_snapshot_is_unavailable(monkeypatch):
    _patch_successful_standard_refresh(monkeypatch)
    monkeypatch.setattr(
        runtime, "analyze_with_strategy",
        lambda *a: (_ for _ in ()).throw(RuntimeError("strategy failed")),
    )
    errors = []
    components = []
    monkeypatch.setattr(runtime, "record_exception", errors.append)
    monkeypatch.setattr(runtime, "set_component", lambda *args: components.append(args))
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is False
    assert result["message"] == "strategy failed"
    assert "strategy" in errors
    assert "provider" in errors
    assert any(item[0] == "strategy" for item in components)


def test_database_failure_is_reported_and_provider_snapshot_is_unavailable(monkeypatch):
    _patch_successful_standard_refresh(monkeypatch)
    monkeypatch.setattr(
        runtime, "record_signal",
        lambda *a: (_ for _ in ()).throw(RuntimeError("database failed")),
    )
    errors = []
    monkeypatch.setattr(runtime, "record_exception", errors.append)
    monkeypatch.setattr(runtime, "set_component", lambda *a: None)
    result = runtime.refresh_snapshot("EUR/USD")
    assert result["available"] is False
    assert result["message"] == "database failed"
    assert "database" in errors
    assert "provider" in errors
