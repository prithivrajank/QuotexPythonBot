from data_collector import connection_status, get_candles
import pytest


def test_status_never_claims_live_feed_without_implementation(monkeypatch):
    monkeypatch.delenv("QUOTEX_SSID", raising=False)
    status = connection_status()
    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["credentials_configured"] is False


def test_status_does_not_expose_ssid(monkeypatch):
    monkeypatch.setenv("QUOTEX_SSID", "secret-test-value")
    status = connection_status()
    assert status["credentials_configured"] is True
    assert "secret-test-value" not in str(status)


def test_candle_request_validation():
    with pytest.raises(ValueError):
        get_candles("", 60)
    with pytest.raises(ValueError):
        get_candles("EURUSD", 0)
    with pytest.raises(ValueError):
        get_candles("EURUSD", 60, 0)


def test_candle_request_does_not_fake_data():
    with pytest.raises(RuntimeError, match="not implemented"):
        get_candles("EURUSD", 60, 100)
