import time

import pytest

import quotexapi_provider as provider


def test_symbols_default_to_otc_only(monkeypatch):
    monkeypatch.delenv("FOREX_SYMBOLS", raising=False)
    assert provider._symbols() == ["EURUSD_otc", "GBPUSD_otc"]


def test_symbols_reject_standard_forex(monkeypatch):
    monkeypatch.setenv("FOREX_SYMBOLS", "EURUSD_otc,GBPUSD")
    with pytest.raises(ValueError, match="OTC-only"):
        provider._symbols()


def test_account_mode_is_demo_only(monkeypatch):
    monkeypatch.delenv("QUOTEX_ACCOUNT", raising=False)
    monkeypatch.setenv("QUOTEX_IS_DEMO", "true")
    assert provider._account_mode() == (True, "Demo")


def test_account_mode_rejects_real(monkeypatch):
    monkeypatch.setenv("QUOTEX_ACCOUNT", "real")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "true")
    with pytest.raises(ValueError, match="Demo account only"):
        provider._account_mode()


def test_get_candles_rejects_non_otc_without_connecting():
    with pytest.raises(ValueError, match="OTC-only"):
        provider.get_candles("EURUSD", 60)


def test_get_candles_rejects_stale_otc_data(monkeypatch):
    monkeypatch.setattr(provider, "_connected", True)
    provider._rows["EURUSD_otc"] = [
        {
            "time": int(time.time()) - 600,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "symbol": "EURUSD_otc",
            "timeframe_seconds": 60,
        }
        for _ in range(30)
    ]
    with pytest.raises(RuntimeError, match="stale"):
        provider.get_candles("EURUSD_otc", 60)
    provider._rows.pop("EURUSD_otc", None)
