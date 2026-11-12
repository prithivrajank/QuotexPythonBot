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


def test_postgres_adapter_translates_placeholders_and_conflict_handling():
    from signal_history import _PostgresConnection

    class FakeConnection:
        def __init__(self):
            self.statement = None
            self.params = None

        def execute(self, statement, params):
            self.statement = statement
            self.params = params
            return "cursor"

    raw = FakeConnection()
    adapter = _PostgresConnection(raw)
    result = adapter.execute(
        "INSERT INTO signal_history (symbol) VALUES (?) "
        "ON CONFLICT(symbol) DO NOTHING",
        ("EURUSD_otc",),
    )
    assert result == "cursor"
    assert "VALUES (%s)" in raw.statement
    assert "ON CONFLICT(symbol) DO NOTHING" in raw.statement
    assert raw.params == ("EURUSD_otc",)
