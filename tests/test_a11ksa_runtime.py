import runtime


def test_a11ksa_refresh_never_runs_analysis_history_or_telegram(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "a11ksa")
    monkeypatch.setenv("FOREX_SYMBOLS", "EURUSD_otc")
    candles = [{
        "time": 1793803080, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
        "symbol": "EURUSD_otc", "timeframe_seconds": 60,
        "market_type": "Quotex demo OTC (read-only)",
    }]
    monkeypatch.setattr(runtime, "get_candles", lambda *args: candles)
    def forbidden(*args, **kwargs):
        raise AssertionError("A11KSA candle-only mode must not run signal or alert code")
    monkeypatch.setattr(runtime, "analyze_candles", forbidden, raising=False)
    monkeypatch.setattr(runtime, "record_signal", forbidden)
    monkeypatch.setattr(runtime, "score_due_outcomes", forbidden)
    monkeypatch.setattr(runtime, "notify_new_candle", forbidden)

    snapshot = runtime.refresh_snapshot("EURUSD_otc")

    assert snapshot["available"] is True
    assert snapshot["demo_only"] is True
    assert snapshot["read_only"] is True
    assert snapshot["timeframe_seconds"] == 60
    assert "analysis" not in snapshot
    assert "telegram_notification" not in snapshot
    assert snapshot["telegram_configured"] is False
    assert snapshot["chart"]["candles"][0]["close"] == 1.15


def test_a11ksa_uses_one_otc_symbol_by_default(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "a11ksa")
    monkeypatch.delenv("FOREX_SYMBOLS", raising=False)
    monkeypatch.delenv("FOREX_SYMBOL", raising=False)
    assert runtime.configured_symbols() == ["EURUSD_otc"]
