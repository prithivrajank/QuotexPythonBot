import main


def test_rest_provider_does_not_claim_tick_stream(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quantex")
    result = main.latest_ticks()
    assert result["ticks"] == []
    assert result["streaming_available"] is False
    assert "not a verified tick stream" in result["message"]


def test_quotex_provider_returns_only_observed_ticks(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "quotexapi")
    monkeypatch.setattr("quotexapi_provider.get_ticks", lambda: [
        {"symbol": "EURUSD_otc", "price": 1.2345, "time": 1790000000}
    ])
    result = main.latest_ticks()
    assert result["streaming_available"] is True
    assert result["ticks"][0]["symbol"] == "EURUSD_otc"


def test_a11ksa_assets_security_gate_returns_controlled_502(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "a11ksa")
    with pytest.raises(HTTPException) as exc:
        main.assets()
    assert exc.value.status_code == 502
    assert "disabled" in exc.value.detail.lower()


def test_a11ksa_candles_security_gate_returns_controlled_502(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setenv("MARKET_DATA_PROVIDER", "a11ksa")
    with pytest.raises(HTTPException) as exc:
        main.candles(asset="EURUSD_otc", timeframe_seconds=60, limit=100)
    assert exc.value.status_code == 502
    assert "disabled" in exc.value.detail.lower()
