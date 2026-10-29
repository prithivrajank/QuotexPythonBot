import pytest

import data_collector
from data_collector import MarketDataError, connection_status, get_candles


def test_status_without_key_is_disconnected(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    status = connection_status()
    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["credentials_configured"] is False
    assert "not Quotex OTC" in status["source"]


def test_status_validates_key_with_api_usage(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(data_collector, "_get", lambda path, params=None: {
        "current_usage": 2, "plan_limit": 800
    })
    status = connection_status()
    assert status["connected"] is True
    assert status["live_data"] is False
    assert status["usage"] == 2
    assert "not affiliated with Quotex" in status["affiliation"]


@pytest.mark.parametrize(
    ("asset", "timeframe", "limit"),
    [("", 60, 10), ("EUR/USD", 0, 10), ("EUR/USD", 60, 0),
     ("EUR/USD", 60, 5001), ("EUR USD", 60, 10), ("EUR/USD", 7, 10)],
)
def test_invalid_candle_arguments(asset, timeframe, limit):
    with pytest.raises(ValueError):
        get_candles(asset, timeframe, limit)


def test_returns_real_ohlc_sorted_oldest_first(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    payload = {
        "meta": {"symbol": "EUR/USD"},
        "values": [
            {"datetime": "2026-10-29 10:02:00", "open": "1.2", "high": "1.4", "low": "1.1", "close": "1.3"},
            {"datetime": "2026-10-29 10:01:00", "open": "1.0", "high": "1.2", "low": "0.9", "close": "1.1"},
        ],
    }
    monkeypatch.setattr(data_collector, "_get", lambda path, params=None: payload)
    candles = get_candles("EUR/USD", 60, 2)
    assert [item["time"] for item in candles] == sorted(item["time"] for item in candles)
    assert candles[0]["open"] == 1.0
    assert candles[-1]["high"] == 1.4
    assert candles[0]["market_type"] == "standard forex, not Quotex OTC"


def test_invalid_ohlc_is_rejected(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    payload = {"values": [{"datetime": "2026-10-29 10:00:00", "open": "1.2", "high": "1.1", "low": "1.0", "close": "1.15"}]}
    monkeypatch.setattr(data_collector, "_get", lambda path, params=None: payload)
    with pytest.raises(MarketDataError, match="inconsistent OHLC"):
        get_candles("EUR/USD", 60, 1)


def test_api_error_does_not_return_fake_candles(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")

    def fail(path, params=None):
        raise MarketDataError("provider unavailable")

    monkeypatch.setattr(data_collector, "_get", fail)
    with pytest.raises(MarketDataError, match="provider unavailable"):
        get_candles("EUR/USD", 60, 100)
