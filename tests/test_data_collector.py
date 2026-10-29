import pytest

import data_collector
from data_collector import MarketDataError, connection_status, get_candles


def test_status_without_key_is_disconnected(monkeypatch):
    monkeypatch.delenv("OTCHARTS_API_KEY", raising=False)
    status = connection_status()
    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["credentials_configured"] is False
    assert "not affiliated with Quotex" in status["source"]


def test_status_does_not_expose_api_key(monkeypatch):
    secret = "otc_live_test_secret"
    monkeypatch.setenv("OTCHARTS_API_KEY", secret)

    def fake_get(path, params=None):
        assert path == "usage"
        return {"plan": "test"}

    monkeypatch.setattr(data_collector, "_get", fake_get)
    status = connection_status()
    assert status["connected"] is True
    assert status["live_data"] is False
    assert secret not in str(status)


@pytest.mark.parametrize(
    ("asset", "timeframe", "limit"),
    [("", 60, 10), ("EURUSD_otc", 0, 10), ("EURUSD_otc", 60, 0),
     ("EURUSD_otc", 60, 5001), ("EUR USD_otc", 60, 10), ("EURUSD_otc", 7, 10)],
)
def test_invalid_candle_arguments(asset, timeframe, limit):
    with pytest.raises(ValueError):
        get_candles(asset, timeframe, limit)


def test_returns_real_ohlc_sorted_oldest_first(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    payload = {
        "symbol": "EURUSD_otc",
        "candles": [
            {"time": 120, "open": 1.2, "high": 1.4, "low": 1.1, "close": 1.3},
            {"time": 60, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        ],
    }
    monkeypatch.setattr(data_collector, "_get", lambda path, params=None: payload)
    candles = get_candles("EURUSD_otc", 60, 2)
    assert [item["time"] for item in candles] == [60, 120]
    assert candles[0]["open"] == 1.0
    assert candles[1]["high"] == 1.4
    assert candles[0]["source"] == data_collector.SOURCE


def test_invalid_ohlc_is_rejected(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    payload = {"candles": [{"time": 60, "open": 1.2, "high": 1.1, "low": 1.0, "close": 1.15}]}
    monkeypatch.setattr(data_collector, "_get", lambda path, params=None: payload)
    with pytest.raises(MarketDataError, match="inconsistent OHLC"):
        get_candles("EURUSD_otc", 60, 1)


def test_api_error_does_not_return_fake_candles(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")

    def fail(path, params=None):
        raise MarketDataError("provider unavailable")

    monkeypatch.setattr(data_collector, "_get", fail)
    with pytest.raises(MarketDataError, match="provider unavailable"):
        get_candles("EURUSD_otc", 60, 100)
