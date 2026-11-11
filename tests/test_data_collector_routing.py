"""Remaining provider-routing and parsing branch tests."""
from __future__ import annotations

import pytest
import requests

import a11ksa_provider
import quotexapi_provider
import data_collector as dc
from data_collector import MarketDataError


class Response:
    def __init__(self, status=200, payload=None, ok=True):
        self.status_code = status
        self.payload = payload
        self.ok = ok

    def json(self):
        return self.payload


def test_quantex_candles_rejects_invalid_nested_data_and_rows(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    for data in (None, [], {"candles": None}, {"candles": [None]}):
        monkeypatch.setattr(dc, "_qx_request", lambda *a, data=data: {"data": data})
        with pytest.raises(MarketDataError):
            dc.get_candles("EURUSD_otc", 60, 1)


def test_otcharts_request_returns_success_payload_and_strips_path(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        dc.requests, "get",
        lambda *a, **k: (calls.append((a, k)) or Response(payload={"symbols": []})),
    )
    result = dc._otcharts_request("/v1/symbols")
    assert result == {"symbols": []}
    assert calls[0][0][0].endswith("/v1/symbols")
    assert calls[0][1]["params"] == {}


def test_otcharts_403_with_non_object_body_is_safe(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: Response(403, ["forbidden"], ok=False))
    with pytest.raises(MarketDataError, match="HTTP 403.*Unexpected response"):
        dc._otcharts_request("v1/symbols")


def test_otcharts_candles_normalizes_standard_forex_symbol(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    calls = []
    monkeypatch.setattr(
        dc, "_otcharts_request",
        lambda path, params: (calls.append((path, params)) or {"candles": []}),
    )
    assert dc.get_candles("eur/usd", 60, 5) == []
    assert calls[0][1]["symbol"] == "EURUSD"


def test_otcharts_status_without_key_is_disconnected(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.delenv("OTCHARTS_API_KEY", raising=False)
    status = dc.connection_status()
    assert status["connected"] is False
    assert status["credentials_configured"] is False
    assert "OTCHARTS_API_KEY is missing" in status["message"]


def test_quantex_status_without_key_is_disconnected(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.delenv("QUANTEX_API_KEY", raising=False)
    status = dc.connection_status()
    assert status["connected"] is False
    assert status["credentials_configured"] is False
    assert "QUANTEX_API_KEY is missing" in status["message"]


def test_quantex_status_rejects_malformed_catalogue(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.setenv("QUANTEX_API_KEY", "test-key")
    monkeypatch.setattr(dc, "_qx_request", lambda *a: {"data": None})
    status = dc.connection_status()
    assert status["connected"] is False
    assert "data list" in status["message"]


@pytest.mark.parametrize(
    ("provider", "module", "function_name", "result"),
    [
        ("a11ksa", a11ksa_provider, "connection_status", {"connected": False, "security_blocked": True}),
        ("quotexapi", quotexapi_provider, "connection_status", {"connected": False, "account_mode": "demo"}),
    ],
)
def test_connection_status_delegates_to_selected_adapter(
    monkeypatch, provider, module, function_name, result
):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    monkeypatch.setattr(module, function_name, lambda: result)
    assert dc.connection_status() == result


@pytest.mark.parametrize(
    ("provider", "module", "function_name", "result"),
    [
        ("a11ksa", a11ksa_provider, "get_assets", [{"symbol": "EURUSD_otc"}]),
        ("quotexapi", quotexapi_provider, "get_assets", [{"symbol": "EURUSD_otc"}]),
    ],
)
def test_get_assets_delegates_to_selected_adapter(
    monkeypatch, provider, module, function_name, result
):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    monkeypatch.setattr(module, function_name, lambda: result)
    assert dc.get_assets() == result


@pytest.mark.parametrize(
    ("provider", "module", "function_name"),
    [
        ("a11ksa", a11ksa_provider, "get_candles"),
        ("quotexapi", quotexapi_provider, "get_candles"),
    ],
)
def test_get_candles_delegates_to_selected_adapter(
    monkeypatch, provider, module, function_name
):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    calls = []
    monkeypatch.setattr(
        module, function_name,
        lambda asset, timeframe, limit: (calls.append((asset, timeframe, limit)) or [{"time": 1}]),
    )
    assert dc.get_candles("EURUSD_otc", 60, 3) == [{"time": 1}]
    assert calls == [("EURUSD_otc", 60, 3)]


@pytest.mark.parametrize("provider", ["otcharts", "quantex"])
def test_quotex_market_adapters_reject_whitespace_symbols(monkeypatch, provider):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", provider)
    with pytest.raises(ValueError, match="without spaces"):
        dc.get_candles("EUR USD", 60, 10)


def test_quantex_assets_ignore_non_object_and_invalid_pairs(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    responses = iter([
        {"data": [None, "not-an-object", {"symbol": 9}, {"symbol": "EURUSD"}]},
        {"data": [{"symbol": "EURUSD_otc"}]},
    ])
    monkeypatch.setattr(dc, "_qx_request", lambda *a: next(responses))
    assets = dc.get_assets()
    assert [item["symbol"] for item in assets] == ["EURUSD", "EURUSD_otc"]


def test_twelve_data_candles_accept_timezone_and_valid_volume(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setattr(dc, "_get", lambda *a: {"values": [{
        "datetime": "2026-11-11T10:00:00+05:30",
        "open": "1.0", "high": "1.2", "low": "0.9", "close": "1.1",
        "volume": "12.5",
    }]})
    result = dc.get_candles("EUR/USD", 60, 1)
    assert result[0]["volume"] == 12.5
    assert result[0]["time"] > 0


def test_twelve_data_rejects_more_candles_than_requested(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    row = {
        "datetime": "2026-11-11T10:00:00+00:00",
        "open": "1.0", "high": "1.2", "low": "0.9", "close": "1.1",
    }
    monkeypatch.setattr(dc, "_get", lambda *a: {"values": [row, dict(row, datetime="2026-11-11T10:01:00+00:00")]})
    with pytest.raises(MarketDataError, match="more candles than requested"):
        dc.get_candles("EUR/USD", 60, 1)
