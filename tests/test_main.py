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
