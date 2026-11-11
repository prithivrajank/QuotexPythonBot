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



def test_score_due_outcomes_covers_wait_flat_put_win_and_losses(
    monkeypatch, tmp_path
):
    """Matured WAIT, flat, PUT-win and losing signals receive correct outcomes."""
    import signal_history

    db_path = tmp_path / "outcomes.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    cases = [
        ("WAITPAIR", "WAIT", 1.0, "SKIPPED"),
        ("FLATPAIR", "CALL", 0.0, "FLAT"),
        ("PUTWIN", "PUT", 1.1, "WIN"),
        ("CALLLOSS", "CALL", 1.1, "LOSS"),
        ("PUTLOSS", "PUT", 0.9, "LOSS"),
    ]

    for index, (symbol, signal, entry, expected) in enumerate(cases):
        record_signal(
            symbol,
            60,
            {"time": 1000 + index, "close": entry},
            {"signal": signal, "reason": "outcome branch test"},
        )
        changed = score_due_outcomes(
            symbol,
            60,
            {"time": 1300 + index, "close": 1.0},
            horizon_candles=5,
        )
        assert changed == 1
        rows = get_history()
        record = next(row for row in rows if row["symbol"] == symbol)
        assert record["outcome"] == expected


def test_win_rate_handles_scored_and_empty_rows():
    """Internal win-rate helper handles both populated and empty aggregates."""
    import signal_history

    assert signal_history._win_rate([
        {"wins": 3, "losses": 1},
        {"wins": 1, "losses": 1},
    ]) == {
        "wins": 4,
        "losses": 2,
        "scored": 6,
        "win_rate_pct": 66.67,
    }
    assert signal_history._win_rate([]) == {
        "wins": 0,
        "losses": 0,
        "scored": 0,
        "win_rate_pct": None,
    }


def test_pair_performance_rankings_cover_categories_and_unscored(
    monkeypatch, tmp_path
):
    """Ranking categories honor sample thresholds and put unscored symbols last."""
    import sqlite3
    import signal_history

    db_path = tmp_path / "rankings.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    def seed(symbol, outcomes, base_time, score=7):
        for offset, outcome in enumerate(outcomes):
            record_signal(
                symbol,
                60,
                {"time": base_time + offset, "close": 1.0},
                {
                    "signal": "WAIT",
                    "reason": "ranking test",
                    "signal_score": score,
                    "signal_grade": "MODERATE",
                },
            )
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE signal_history SET outcome=? WHERE symbol=? AND signal_time=?",
                    (outcome, symbol, base_time + offset),
                )

    seed("AVOID", ["WIN"] * 4 + ["LOSS"] * 6, 1000)
    seed("HOT", ["WIN"] * 14 + ["LOSS"] * 6, 2000)
    seed("GOOD", ["WIN"] * 6 + ["LOSS"] * 4, 3000)
    seed("NEUTRAL", ["WIN", "LOSS"], 4000)
    seed("UNSCORED", ["PENDING"], 5000, score=None)

    rankings = signal_history.get_pair_performance_rankings()

    assert [row["symbol"] for row in rankings] == [
        "HOT", "GOOD", "NEUTRAL", "AVOID", "UNSCORED"
    ]
    by_symbol = {row["symbol"]: row for row in rankings}
    assert by_symbol["HOT"]["category"] == "HOT"
    assert by_symbol["HOT"]["win_rate"] == 70.0
    assert by_symbol["GOOD"]["category"] == "GOOD"
    assert by_symbol["GOOD"]["win_rate"] == 60.0
    assert by_symbol["AVOID"]["category"] == "AVOID"
    assert by_symbol["AVOID"]["win_rate"] == 40.0
    assert by_symbol["NEUTRAL"]["category"] == "NEUTRAL"
    assert by_symbol["UNSCORED"]["category"] == "NEUTRAL"
    assert by_symbol["UNSCORED"]["win_rate"] is None
    assert by_symbol["UNSCORED"]["average_signal_score"] is None


def test_pair_performance_records_group_and_sort_rows(
    monkeypatch, tmp_path
):
    """Adaptive performance records are grouped by symbol and newest first."""
    import signal_history

    db_path = tmp_path / "pair-records.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    record_signal(
        "EURUSD", 60, {"time": 1000, "close": 1.1},
        {"signal": "CALL", "signal_score": 8},
    )
    record_signal(
        "EURUSD", 60, {"time": 1120, "close": 1.2},
        {"signal": "PUT", "signal_score": 4},
    )
    record_signal(
        "GBPUSD", 60, {"time": 1060, "close": 1.3},
        {"signal": "WAIT"},
    )

    result = signal_history.get_pair_performance_records()

    assert list(result) == ["EURUSD", "GBPUSD"]
    assert [row["signal_time"] for row in result["EURUSD"]] == [1120, 1000]
    assert result["EURUSD"][0]["signal_score"] == 4
    assert result["GBPUSD"][0]["outcome"] == "PENDING"
