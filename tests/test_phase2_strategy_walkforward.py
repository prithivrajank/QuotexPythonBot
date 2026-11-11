"""Phase 2 tests for strategy selection, registry validation, and walk-forward splits."""
from __future__ import annotations

import math

import pytest

import strategy_manager
import strategy_registry
import walkforward


def candles(count=120):
    rows = []
    price = 1.1
    for index in range(count):
        close = price + 0.0001
        rows.append({
            "time": 1_700_000_000 + index * 60,
            "open": price,
            "high": close + 0.00005,
            "low": price - 0.00005,
            "close": close,
        })
        price = close
    return rows


@pytest.mark.parametrize("value", ["", "bad", None, "0", "-12", "5"])
def test_strategy_promotion_threshold_is_safe(value):
    if value is None:
        assert strategy_manager._minimum_completed_signals(value) == 20
    elif value == "5":
        assert strategy_manager._minimum_completed_signals(value) == 5
    elif value == "0" or value == "-12":
        assert strategy_manager._minimum_completed_signals(value) == 1
    else:
        assert strategy_manager._minimum_completed_signals(value) == 20


def test_strategy_manager_uses_operator_baselines_when_history_is_insufficient(monkeypatch):
    monkeypatch.setattr(strategy_manager, "MIN_COMPLETED_SIGNALS", 20)
    monkeypatch.setattr(strategy_manager, "get_strategy_statistics", lambda: {})
    monkeypatch.delenv("AUTO_STRATEGY_SELECTION", raising=False)
    status = strategy_manager.get_strategy_manager_status()
    assert status["auto_selection_enabled"] is True
    assert status["active_strategy"] == "BREAKOUT_V3"
    assert [row["name"] for row in status["strategies"]] == [
        "BREAKOUT_V3", "SCORE_ENGINE_V2", "EMA_RSI_V1"
    ]
    assert all(row["rate_source"] == "operator_baseline" for row in status["strategies"])
    assert status["strategies"][0]["management_status"] == "PROMOTED"
    assert status["strategies"][-1]["management_status"] == "DEMOTED"


def test_strategy_manager_uses_measured_history_only_after_minimum_sample(monkeypatch):
    monkeypatch.setattr(strategy_manager, "MIN_COMPLETED_SIGNALS", 20)
    monkeypatch.setattr(strategy_manager, "get_strategy_statistics", lambda: {
        "EMA_RSI_V1": {"scored_signals": 25, "win_rate": 82.5},
        "SCORE_ENGINE_V2": {"scored_signals": 19, "win_rate": 99.0},
        "BREAKOUT_V3": {"scored_signals": 20, "win_rate": 60.0},
    })
    status = strategy_manager.get_strategy_manager_status()
    rows = {row["name"]: row for row in status["strategies"]}
    assert rows["EMA_RSI_V1"]["win_rate"] == 82.5
    assert rows["EMA_RSI_V1"]["rate_source"] == "history"
    assert rows["SCORE_ENGINE_V2"]["win_rate"] == 64.0
    assert rows["SCORE_ENGINE_V2"]["rate_source"] == "operator_baseline"
    assert status["active_strategy"] == "EMA_RSI_V1"


def test_strategy_manager_ignores_corrupt_counts_and_nonfinite_rates(monkeypatch):
    monkeypatch.setattr(strategy_manager, "MIN_COMPLETED_SIGNALS", 1)
    monkeypatch.setattr(strategy_manager, "get_strategy_statistics", lambda: {
        "EMA_RSI_V1": {"scored_signals": "not-an-int", "win_rate": float("nan")},
        "SCORE_ENGINE_V2": {"scored_signals": 100, "win_rate": float("inf")},
        "BREAKOUT_V3": {"scored_signals": -4, "win_rate": 120},
    })
    status = strategy_manager.get_strategy_manager_status()
    rows = {row["name"]: row for row in status["strategies"]}
    assert rows["EMA_RSI_V1"]["win_rate"] == 58.0
    assert rows["SCORE_ENGINE_V2"]["win_rate"] == 64.0
    assert rows["BREAKOUT_V3"]["win_rate"] == 71.0
    assert all(row["rate_source"] == "operator_baseline" for row in rows.values())


def test_manual_strategy_override_is_validated_and_does_not_change_promotion(monkeypatch):
    monkeypatch.setattr(strategy_manager, "get_strategy_statistics", lambda: {})
    monkeypatch.setenv("AUTO_STRATEGY_SELECTION", "false")
    monkeypatch.setenv("STRATEGY_NAME", "ema_rsi_v1")
    status = strategy_manager.get_strategy_manager_status()
    assert status["active_strategy"] == "EMA_RSI_V1"
    assert status["promoted_strategy"] == "BREAKOUT_V3"
    monkeypatch.setenv("STRATEGY_NAME", "not-registered")
    with pytest.raises(ValueError, match="Unknown strategy"):
        strategy_manager.get_active_strategy()


def test_apply_strategy_management_preserves_signal_direction(monkeypatch):
    monkeypatch.setattr(strategy_manager, "get_strategy_statistics", lambda: {})
    analysis = {"signal": "WAIT", "reason": "No confirmation", "signal_score": 0}
    result = strategy_manager.apply_strategy_management(analysis)
    assert result["signal"] == "WAIT"
    assert result["reason"] == "No confirmation"
    assert "strategy_management" in result
    assert "strategy_management" not in analysis


def test_strategy_registry_rejects_short_or_invalid_history_with_wait():
    invalid = candles(30)
    for row in invalid:
        row["close"] = float("inf")
        row["high"] = float("inf")
    for name in ("EMA_RSI_V1", "BREAKOUT_V3"):
        result = strategy_registry.analyze_with_strategy(invalid, name)
        assert result["signal"] == "WAIT"
        assert result["candles_used"] == 0
        assert result["strategy_name"] == name


@pytest.mark.parametrize("bad_price", [0.0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_strategy_registry_does_not_generate_signals_from_invalid_ohlc(bad_price):
    rows = [
        {**row, "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0}
        for row in candles(40)
    ]
    rows[-1]["close"] = bad_price
    result = strategy_registry.analyze_with_strategy(rows, "BREAKOUT_V3")
    assert result["signal"] == "WAIT"
    assert result["candles_used"] == 39


def test_strategy_registry_metadata_is_versioned_and_input_is_not_mutated():
    rows = candles(40)
    original = [dict(row) for row in rows]
    result = strategy_registry.analyze_with_strategy(rows, "score_engine_v2")
    assert result["strategy_name"] == "SCORE_ENGINE_V2"
    assert result["strategy_version"] == "2.0.0"
    assert rows == original
    assert strategy_registry.strategy_metadata("EMA_RSI_V1")["version"] == "1.0.0"


def test_walkforward_sorts_chronologically_and_runs_independent_segments(monkeypatch):
    rows = candles(120)
    rows.reverse()
    calls = []

    def fake_backtest(segment, symbol, expiry):
        calls.append((list(segment), symbol, expiry))
        return {"win_rate": 60.0 if len(calls) == 1 else 55.0, "rows": len(segment)}

    monkeypatch.setattr(walkforward, "run_backtest", fake_backtest)
    result = walkforward.run_walkforward(rows, "EURUSD_otc", expiry=2)

    assert result["status"] == "HEALTHY"
    assert result["overfit_score"] == 5.0
    assert result["training_candles"] == 84
    assert result["validation_candles"] == 36
    assert calls[0][0][-1]["time"] < calls[1][0][0]["time"]
    assert calls[0][1:] == ("EURUSD_otc", 2)
    assert calls[1][1:] == ("EURUSD_otc", 2)


@pytest.mark.parametrize(
    ("training_rate", "validation_rate", "expected"),
    [
        (70.0, 65.0, "HEALTHY"),
        (70.0, 55.0, "WARNING"),
        (80.0, 60.0, "OVERFIT"),
        (None, 60.0, "INSUFFICIENT_DATA"),
    ],
)
def test_walkforward_status_thresholds(monkeypatch, training_rate, validation_rate, expected):
    values = iter([training_rate, validation_rate])
    monkeypatch.setattr(
        walkforward, "run_backtest",
        lambda *a, **k: {"win_rate": next(values)},
    )
    result = walkforward.run_walkforward(candles(120), "EUR/USD")
    assert result["status"] == expected
    if expected == "INSUFFICIENT_DATA":
        assert result["overfit_score"] is None


@pytest.mark.parametrize("expiry", [0, 4, True])
def test_walkforward_rejects_unsupported_expiry(expiry):
    with pytest.raises(ValueError, match="expiry must be"):
        walkforward.run_walkforward(candles(120), "EUR/USD", expiry=expiry)


@pytest.mark.parametrize(
    "bad_rows",
    [
        [None] + candles(120)[1:],
        [dict(candles(120)[0], time=0)] + candles(120)[1:],
        [dict(candles(120)[0], time="bad")] + candles(120)[1:],
        candles(120) + [dict(candles(120)[0])],
    ],
)
def test_walkforward_rejects_invalid_or_duplicate_timestamps(bad_rows):
    with pytest.raises(ValueError, match="candle|timestamp"):
        walkforward.run_walkforward(bad_rows, "EUR/USD")


def test_walkforward_rejects_insufficient_data():
    with pytest.raises(ValueError, match="110 chronological candles"):
        walkforward.run_walkforward(candles(109), "EUR/USD")

def make_rsi_candles(up_steps, down_steps, cycles=10, start=1.0):
    rows = []
    price = start
    pattern = [0.01] * up_steps + [-0.01] * down_steps
    for index in range(len(pattern) * cycles):
        change = pattern[index % len(pattern)]
        close = price + change
        rows.append({
            "time": 1_700_000_000 + index * 60,
            "open": price,
            "high": max(price, close) + 0.002,
            "low": min(price, close) - 0.002,
            "close": close,
        })
        price = close
    return rows


@pytest.mark.parametrize(
    ("up", "down", "start", "expected"),
    [
        (7, 3, 1.0, "CALL"),
        (4, 8, 2.0, "PUT"),
        (10, 0, 1.0, "WAIT"),
    ],
)
def test_ema_rsi_strategy_direction_and_rsi_filter(up, down, start, expected):
    result = strategy_registry.analyze_with_strategy(
        make_rsi_candles(up, down, start=start), "EMA_RSI_V1"
    )
    assert result["signal"] == expected
    assert result["strategy_name"] == "EMA_RSI_V1"
    assert result["strategy_version"] == "1.0.0"
    assert result["rsi_14"] is not None
