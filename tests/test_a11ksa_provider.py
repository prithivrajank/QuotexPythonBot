import pytest

from a11ksa_provider import (
    A11ksaSecurityError,
    connection_status,
    get_assets,
    get_candles,
)


def test_status_is_fail_closed(monkeypatch):
    monkeypatch.setenv("QUOTEX_SSID", "placeholder-not-used")
    status = connection_status()
    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["security_blocked"] is True
    assert "No session was used" in status["message"]


def test_assets_refuses_to_connect():
    with pytest.raises(A11ksaSecurityError, match="TLS"):
        get_assets()


def test_candles_refuses_to_connect():
    with pytest.raises(A11ksaSecurityError, match="TLS"):
        get_candles("EURUSD_otc", 60, 100)


@pytest.mark.parametrize(
    "asset,timeframe,limit",
    [
        ("", 60, 100),
        ("EURUSD_otc", 300, 100),
        ("EURUSD_otc", 60, 0),
        ("EURUSD_otc", 60, 501),
    ],
)
def test_candle_arguments_validated_before_security_gate(asset, timeframe, limit):
    with pytest.raises(ValueError):
        get_candles(asset, timeframe, limit)
