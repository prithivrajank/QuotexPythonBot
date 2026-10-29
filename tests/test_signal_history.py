from signal_history import get_history, history_summary, record_signal, score_due_outcomes


def test_history_records_unique_candles_and_scores_outcomes(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "history.db"))
    candle = {"time": 1000, "close": 1.1000}
    analysis = {"signal": "CALL", "reason": "test", "rsi_14": 55, "macd_histogram": 0.0001}

    first = record_signal("EUR/USD", 60, candle, analysis)
    duplicate = record_signal("EUR/USD", 60, candle, analysis)
    assert first["inserted"] is True
    assert duplicate["inserted"] is False

    changed = score_due_outcomes(
        "EUR/USD", 60, {"time": 1300, "close": 1.1010}, horizon_candles=5
    )
    assert changed == 1
    records = get_history()
    assert records[0]["outcome"] == "WIN"
    summary = history_summary()
    assert summary["wins"] == 1
    assert summary["scored_win_rate_pct"] == 100.0
