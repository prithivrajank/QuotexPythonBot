"""Edge-case tests for provider transports and market-data validation."""
from __future__ import annotations


import pytest
import requests

import data_collector as dc
from data_collector import MarketDataError


class FakeResponse:
    def __init__(self, status=200, payload=None, ok=None, json_error=False):
        self.status_code = status
        self.ok = (200 <= status < 400) if ok is None else ok
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("invalid JSON")
        return self.payload


def test_quantex_request_requires_key(monkeypatch):
    monkeypatch.delenv("QUANTEX_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="QUANTEX_API_KEY is missing"):
        dc._qx_request("pairs", {})


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(401, {"error": {"message": "bad key"}}), "HTTP 401"),
        (FakeResponse(429, {"error": {"message": "quota"}}), "HTTP 429"),
        (FakeResponse(503, {"error": {"code": "down", "message": "offline"}}), "offline"),
        (FakeResponse(200, {"ok": False, "error": {"code": "bad", "message": "rejected"}}), "rejected"),
        (FakeResponse(200, ["not", "an", "object"]), "Unexpected response"),
        (FakeResponse(200, None, json_error=True), "Unexpected response"),
    ],
)
def test_quantex_request_rejects_provider_errors(monkeypatch, response, message):
    monkeypatch.setenv("QUANTEX_API_KEY", "test-key")
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: response)
    with pytest.raises(MarketDataError, match=message):
        dc._qx_request("pairs", {})


def test_quantex_request_maps_network_errors(monkeypatch):
    monkeypatch.setenv("QUANTEX_API_KEY", "test-key")

    def fail(*args, **kwargs):
        raise requests.ConnectionError("private detail")

    monkeypatch.setattr(dc.requests, "get", fail)
    with pytest.raises(MarketDataError, match="ConnectionError") as exc:
        dc._qx_request("pairs", {})
    assert "private detail" not in str(exc.value)


def test_quantex_request_sends_bearer_header(monkeypatch):
    monkeypatch.setenv("QUANTEX_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        dc.requests, "get",
        lambda *a, **k: (calls.append((a, k)) or FakeResponse(payload={"ok": True})),
    )
    assert dc._qx_request("pairs", {"market": "otc"}) == {"ok": True}
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0][1]["timeout"] == 15


def test_quantex_candles_normalize_sort_and_limit(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    payload = {"data": {"candles": [
        {"epoch": 120, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
        {"epoch": 60, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
    ]}}
    calls = []
    monkeypatch.setattr(dc, "_qx_request", lambda path, params: (calls.append((path, params)) or payload))
    candles = dc.get_candles("EURUSD_otc", 60, 1)
    assert len(candles) == 1
    assert candles[0]["time"] == 120
    assert candles[0]["symbol"] == "EURUSD_otc"
    assert candles[0]["market_type"] == "Quotex OTC"
    assert calls[0][1]["tf"] == "M1"
    assert calls[0][1]["limit"] == 1


def test_quantex_candles_support_iso_time_and_reject_bad_timeframe(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.setattr(dc, "_qx_request", lambda *a: {"data": {"candles": [{
        "time": "2026-11-11T10:00:00Z",
        "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1,
    }]}})
    with pytest.raises(ValueError, match="supports M1"):
        dc.get_candles("EURUSD", 120, 1)
    assert dc._qx_candles("EURUSD", 60, 5)[0]["time"] > 0


@pytest.mark.parametrize(
    "row",
    [
        {"epoch": 100, "open": 1.0, "high": 0.9, "low": 0.8, "close": 0.85},
        {"epoch": 100, "open": "nan", "high": 1.2, "low": 0.9, "close": 1.1},
        {"epoch": 0, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
        {"epoch": 100, "open": 1.0, "high": 1.2, "low": 0.9},
    ],
)
def test_quantex_candles_reject_invalid_rows(monkeypatch, row):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.setattr(dc, "_qx_request", lambda *a: {"data": {"candles": [row]}})
    with pytest.raises(MarketDataError):
        dc.get_candles("EURUSD_otc", 60, 1)


def test_otcharts_request_requires_key(monkeypatch):
    monkeypatch.delenv("OTCHARTS_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="OTCHARTS_API_KEY is missing"):
        dc._otcharts_request("v1/symbols")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(401, {"error": "bad key"}), "HTTP 401"),
        (FakeResponse(403, {"error": "book not enabled"}), "book not enabled"),
        (FakeResponse(429, {"error": "quota"}), "HTTP 429"),
        (FakeResponse(503, {"error": "offline"}), "API error 503"),
        (FakeResponse(200, {"error": "provider error"}), "provider error"),
        (FakeResponse(200, ["unexpected"]), "Unexpected response"),
        (FakeResponse(200, None, json_error=True), "Unexpected response"),
    ],
)
def test_otcharts_request_rejects_provider_errors(monkeypatch, response, message):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: response)
    with pytest.raises(MarketDataError, match=message):
        dc._otcharts_request("/v1/symbols")


def test_otcharts_request_maps_network_errors(monkeypatch):
    monkeypatch.setenv("OTCHARTS_API_KEY", "test-key")
    monkeypatch.setattr(
        dc.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("private detail")),
    )
    with pytest.raises(MarketDataError, match="Timeout") as exc:
        dc._otcharts_request("v1/symbols")
    assert "private detail" not in str(exc.value)


def test_otcharts_candles_normalize_and_validate(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setattr(dc, "_otcharts_request", lambda *a: {"candles": [
        {"time": 120, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
        {"time": 60, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
    ]})
    candles = dc.get_candles("EURUSD_otc", 60, 2)
    assert [c["time"] for c in candles] == [60, 120]
    assert candles[0]["symbol"] == "EURUSD_otc"
    assert candles[0]["venue"] == "otcharts"
    assert candles[0]["market_type"] == "Quotex OTC"


@pytest.mark.parametrize(
    "payload",
    [
        {"candles": "not-a-list"},
        {"candles": [{"time": "bad", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]},
        {"candles": [{"time": 1, "open": 1, "high": float("inf"), "low": 0.5, "close": 1.5}]},
        {"candles": [{"time": 1, "open": 1, "high": 0.9, "low": 0.5, "close": 1.5}]},
    ],
)
def test_otcharts_candles_reject_invalid_payloads(monkeypatch, payload):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setattr(dc, "_otcharts_request", lambda *a: payload)
    if payload["candles"] == "not-a-list":
        message = "candles list"
    else:
        message = "candle"
    with pytest.raises(MarketDataError, match=message):
        dc.get_candles("EURUSD_otc", 60, 1)


def test_otcharts_candles_reject_unsupported_timeframe(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    with pytest.raises(ValueError, match="OTCharts supports"):
        dc.get_candles("EURUSD_otc", 120, 1)


def test_twelve_data_get_requires_key(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    with pytest.raises(MarketDataError, match="TWELVE_DATA_API_KEY is missing"):
        dc._get("api_usage")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(401, {"message": "unauthorized"}), "HTTP 401"),
        (FakeResponse(429, {"message": "quota"}), "HTTP 429"),
        (FakeResponse(503, {"message": "unavailable"}), "HTTP 503"),
        (FakeResponse(200, ["unexpected"]), "unexpected JSON"),
        (FakeResponse(200, {"status": "error", "message": "bad symbol"}), "bad symbol"),
        (FakeResponse(200, {"code": 400, "message": "bad request"}), "bad request"),
        (FakeResponse(200, None, json_error=True), "unexpected JSON"),
    ],
)
def test_twelve_data_get_rejects_provider_errors(monkeypatch, response, message):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: response)
    with pytest.raises(MarketDataError, match=message):
        dc._get("time_series")


def test_twelve_data_get_maps_network_error_without_details(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(
        dc.requests, "get",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("private detail")),
    )
    with pytest.raises(MarketDataError, match="ConnectionError") as exc:
        dc._get("time_series")
    assert "private detail" not in str(exc.value)


def test_twelve_data_get_assets_filters_bad_rows(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setattr(dc, "_get", lambda *a: {"data": [
        {"symbol": "EUR/USD"}, None, {"symbol": ""}, {"name": "missing symbol"},
    ]})
    assert [row["symbol"] for row in dc.get_assets()] == ["EUR/USD"]


def test_twelve_data_get_assets_rejects_missing_data_list(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setattr(dc, "_get", lambda *a: {"data": None})
    with pytest.raises(MarketDataError, match="data list"):
        dc.get_assets()


def test_otcharts_get_assets_filters_invalid_symbols(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setattr(dc, "_otcharts_request", lambda *a: {"symbols": [
        {"symbol": "EURUSD_otc", "name": "EUR/USD OTC"}, {"symbol": 7}, None,
    ]})
    assets = dc.get_assets()
    assert [item["symbol"] for item in assets] == ["EURUSD_otc"]
    assert assets[0]["market_type"] == "Quotex OTC"


def test_otcharts_get_assets_rejects_empty_catalogue(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setattr(dc, "_otcharts_request", lambda *a: {"symbols": []})
    with pytest.raises(MarketDataError, match="no Quotex symbols"):
        dc.get_assets()


def test_quantex_get_assets_reads_live_and_otc_catalogues(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    calls = []
    def catalogue(path, params):
        calls.append(params["market"])
        return {"data": [{"symbol": "EURUSD" if params["market"] == "live" else "EURUSD_otc"}]}
    monkeypatch.setattr(dc, "_qx_request", catalogue)
    assets = dc.get_assets()
    assert calls == ["live", "otc"]
    assert [item["market_type"] for item in assets] == ["live", "otc"]


def test_quantex_get_assets_rejects_empty_catalogues(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.setattr(dc, "_qx_request", lambda *a: {"data": []})
    with pytest.raises(MarketDataError, match="no open pairs"):
        dc.get_assets()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (None, "values list"),
        ([None], "not an object"),
        ([{"datetime": "bad-time", "open": 1, "high": 2, "low": 0, "close": 1}], "missing/invalid"),
        ([{"datetime": "2026-11-11 10:00:00", "open": "nan", "high": 2, "low": 0, "close": 1}], "invalid values"),
        ([
            {"datetime": "2026-11-11 10:00:00", "open": 1, "high": 2, "low": 0, "close": 1},
            {"datetime": "2026-11-11 10:00:00", "open": 1, "high": 2, "low": 0, "close": 1},
        ], "duplicate candle timestamp"),
        ([{"datetime": "2026-11-11 10:00:00", "open": 1, "high": 2, "low": 0, "close": 1, "volume": "bad"}], "invalid volume"),
        ([{"datetime": "2026-11-11 10:00:00", "open": 1, "high": 2, "low": 0, "close": 1, "volume": "-1"}], "invalid volume"),
    ],
)
def test_twelve_data_candles_reject_malformed_rows(monkeypatch, rows, message):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setattr(dc, "_get", lambda *a: {"values": rows})
    with pytest.raises(MarketDataError, match=message):
        dc.get_candles("EUR/USD", 60, 5)


def test_connection_status_handles_provider_failure(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "twelve_data")
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    monkeypatch.setattr(dc, "_get", lambda *a: (_ for _ in ()).throw(MarketDataError("offline")))
    status = dc.connection_status()
    assert status["connected"] is False
    assert status["credentials_configured"] is True
    assert status["message"] == "offline"


def test_otcharts_status_does_not_claim_live_data(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "otcharts")
    monkeypatch.setenv("OTCHARTS_API_KEY", "configured-but-not-validated")
    status = dc.connection_status()
    assert status["connected"] is True
    assert status["live_data"] is False
    assert status["manual_refresh_only"] is True
    assert "not yet validated" in status["message"]


def test_quantex_status_reports_catalogue_failure(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    monkeypatch.setenv("QUANTEX_API_KEY", "test-key")
    monkeypatch.setattr(dc, "_qx_request", lambda *a: (_ for _ in ()).throw(MarketDataError("denied")))
    status = dc.connection_status()
    assert status["connected"] is False
    assert status["credentials_configured"] is True
    assert status["message"] == "denied"
