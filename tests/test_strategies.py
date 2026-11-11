import math

import pandas as pd
import pytest

import strategies
from strategies import analyze_candles, build_chart_data


def make_candles(count=100):
    rows = []
    price = 1.10
    for i in range(count):
        open_price = price
        close = price + (0.0001 if i % 5 != 0 else -0.00002)
        rows.append({
            "time": 1_700_000_000 + i * 60,
            "open": open_price,
            "high": max(open_price, close) + 0.00005,
            "low": min(open_price, close) - 0.00005,
            "close": close,
        })
        price = close
    return rows


def make_signal_candles(direction="CALL", strong_body=False, breakout=False, count=30):
    """Create valid candles with predictable previous-20 support/resistance."""
    rows = []
    for i in range(count - 1):
        rows.append({
            "time": 1_700_000_000 + i * 60,
            "open": 1.0,
            "high": 1.02,
            "low": 0.98,
            "close": 1.01,
        })

    if strong_body and breakout:
        last = (
            {"open": 1.0, "high": 1.21, "low": 0.98, "close": 1.20}
            if direction == "CALL"
            else {"open": 1.0, "high": 1.02, "low": 0.79, "close": 0.80}
        )
    elif strong_body:
        last = (
            {"open": 1.0, "high": 1.015, "low": 0.996, "close": 1.014}
            if direction == "CALL"
            else {"open": 0.986, "high": 1.004, "low": 0.985, "close": 0.986}
        )
    elif breakout:
        last = (
            {"open": 1.0, "high": 1.21, "low": 0.98, "close": 1.20}
            if direction == "CALL"
            else {"open": 1.0, "high": 1.02, "low": 0.79, "close": 0.80}
        )
    else:
        last = (
            {"open": 1.0, "high": 1.05, "low": 0.95, "close": 1.001}
            if direction == "CALL"
            else {"open": 1.001, "high": 1.05, "low": 0.95, "close": 1.0}
        )
    rows.append({"time": 1_700_000_000 + (count - 1) * 60, **last})
    return rows


def patch_indicators(
    monkeypatch,
    count,
    direction="CALL",
    macd_improving=False,
    low_volatility=False,
):
    """Stub indicators so individual signal-scoring branches are deterministic."""
    if direction == "CALL":
        ema9, ema21, rsi = 2.0, 1.0, 60.0
        previous_hist, current_hist = (
            (0.01, 0.02) if macd_improving else (0.02, 0.01)
        )
    elif direction == "PUT":
        ema9, ema21, rsi = 0.5, 1.0, 40.0
        previous_hist, current_hist = (
            (-0.01, -0.02) if macd_improving else (-0.02, -0.01)
        )
    else:
        ema9, ema21, rsi = 1.0, 1.0, 80.0
        previous_hist, current_hist = 0.0, 0.0

    def series(value):
        return pd.Series([value] * count, dtype="float64")

    histogram = [previous_hist] * count
    if count >= 2:
        histogram[-1] = current_hist

    result = {
        "ema9": series(ema9),
        "ema21": series(ema21),
        "rsi14": series(rsi),
        "macd": series(0.1),
        "macd_signal": series(0.05),
        "macd_hist": pd.Series(histogram, dtype="float64"),
        "atr14": series(0.5 if low_volatility else 2.0),
        "atr_average": series(1.0),
        "bb_mid": series(1.0),
        "bb_upper": series(1.1),
        "bb_lower": series(0.9),
    }
    monkeypatch.setattr(strategies, "_indicators", lambda _df: result)


def test_analysis_includes_macd_bollinger_and_support_resistance():
    result = analyze_candles(make_candles())
    assert result["signal"] in {"CALL", "PUT", "WAIT"}
    assert "macd_histogram" in result
    assert "bollinger_upper" in result
    assert "bollinger_middle" in result
    assert "bollinger_lower" in result
    assert result["support_20"] <= result["resistance_20"]
    assert result["expiry_recommendation_minutes"] in {1, 2, None}
    assert result["signal_strength"] in {"LOW", "MODERATE", "HIGH"}


def test_chart_data_contains_candles_ema_bollinger_and_macd():
    result = build_chart_data(make_candles())
    assert len(result["candles"]) == 100
    assert len(result["ema9"]) == 100
    assert len(result["ema21"]) == 100
    assert result["bbUpper"]
    assert result["bbLower"]
    assert result["macd"]
    assert result["macdSignal"]
    assert result["macdHistogram"]


def test_short_history_returns_wait():
    result = analyze_candles(make_candles(10))
    assert result["signal"] == "WAIT"


def test_frame_handles_empty_missing_and_invalid_ohlc_rows():
    assert strategies._frame([]).empty
    assert strategies._frame([{"open": 1, "close": 1}]).empty

    valid = {
        "time": 1,
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": 1.1,
    }
    invalid_rows = [
        {**valid, "time": 2, "high": 0.8, "low": 0.9},
        {**valid, "time": 3, "high": 1.05, "close": 1.1},
        {**valid, "time": 4, "low": 1.15},
        {**valid, "time": 5, "close": "not-a-price"},
    ]
    result = strategies._frame([valid, *invalid_rows])
    assert len(result) == 1
    assert result.iloc[0]["time"] == 1


def test_last_handles_empty_nan_and_regular_series():
    assert strategies._last(pd.Series(dtype="float64")) is None
    assert strategies._last(pd.Series([1.0, float("nan")])) is None
    assert strategies._last(pd.Series([1.0, 2.5])) == 2.5


@pytest.mark.parametrize("direction", ["CALL", "PUT"])
def test_fully_confirmed_call_and_put_signals(monkeypatch, direction):
    candles = make_signal_candles(direction, strong_body=True, breakout=True)
    patch_indicators(
        monkeypatch, len(candles), direction=direction, macd_improving=True
    )

    result = analyze_candles(candles)

    assert result["signal"] == direction
    assert result["signal_score"] == 10
    assert result["signal_grade"] == "STRONG"
    assert result["signal_strength"] == "HIGH"
    assert result["expiry_recommendation_minutes"] == 1
    assert result["score_breakdown"] == {
        "ema_trend_alignment": 2,
        "rsi_momentum_alignment": 2,
        "macd_histogram_alignment": 2,
        "strong_candle_body": 2,
        "breakout_confirmation": 2,
    }


def test_direction_filter_returns_wait_when_rsi_is_outside_range(monkeypatch):
    candles = make_signal_candles()
    patch_indicators(monkeypatch, len(candles), direction="NONE")

    result = analyze_candles(candles)

    assert result["signal"] == "WAIT"
    assert result["signal_score"] == 0
    assert result["signal_grade"] == "WAIT"
    assert result["expiry_recommendation_minutes"] is None
    assert "EMA trend and RSI do not align" in result["reason"]


def test_aligned_ema_rsi_without_confirmations_returns_weak_wait_expiry(monkeypatch):
    candles = make_signal_candles()
    patch_indicators(monkeypatch, len(candles), direction="CALL")

    result = analyze_candles(candles)

    assert result["signal"] == "CALL"
    assert result["signal_score"] == 4
    assert result["signal_grade"] == "WEAK"
    assert result["signal_strength"] == "LOW"
    assert result["expiry_recommendation_minutes"] == 2
    assert result["reason"] == "EMA and RSI are aligned"


def test_macd_and_strong_body_confirmation_make_moderate_score(monkeypatch):
    candles = make_signal_candles(strong_body=True)
    patch_indicators(
        monkeypatch, len(candles), direction="CALL", macd_improving=True
    )

    result = analyze_candles(candles)

    assert result["signal_score"] == 8
    assert result["signal_grade"] == "MODERATE"
    assert result["signal_strength"] == "MODERATE"
    assert result["expiry_recommendation_minutes"] == 1
    assert "MACD histogram aligned and improving" in result["reason"]
    assert "Strong candle body exceeds 60% of range" in result["reason"]


def test_low_volatility_downgrades_moderate_signal_and_uses_two_minute_expiry(monkeypatch):
    candles = make_signal_candles(strong_body=True)
    patch_indicators(
        monkeypatch,
        len(candles),
        direction="CALL",
        macd_improving=True,
        low_volatility=True,
    )

    result = analyze_candles(candles)

    assert result["signal_grade"] == "MODERATE"
    assert result["signal_strength"] == "LOW"
    assert result["atr_low_volatility"] is True
    assert result["expiry_recommendation_minutes"] == 2
    assert "ATR(14) below recent average volatility" in result["reason"]


def test_low_volatility_does_not_upgrade_an_already_low_signal(monkeypatch):
    candles = make_signal_candles()
    patch_indicators(
        monkeypatch, len(candles), direction="CALL", low_volatility=True
    )

    result = analyze_candles(candles)

    assert result["signal_score"] == 4
    assert result["signal_grade"] == "WEAK"
    assert result["signal_strength"] == "LOW"
    assert result["expiry_recommendation_minutes"] == 2


def test_chart_data_empty_input_returns_all_empty_series():
    result = build_chart_data([])

    assert result == {
        "candles": [],
        "ema9": [],
        "ema21": [],
        "bbUpper": [],
        "bbMiddle": [],
        "bbLower": [],
        "support20": [],
        "resistance20": [],
        "macd": [],
        "macdSignal": [],
        "macdHistogram": [],
    }


def test_chart_data_keeps_positive_and_negative_macd_histogram_colors(monkeypatch):
    candles = make_candles(30)
    count = len(candles)

    def series(values):
        return pd.Series(values, dtype="float64")

    histogram = [0.1] * (count - 1) + [-0.1]
    indicator_data = {
        "ema9": series([1.0] * count),
        "ema21": series([1.0] * count),
        "rsi14": series([50.0] * count),
        "macd": series([0.1] * count),
        "macd_signal": series([0.0] * count),
        "macd_hist": series(histogram),
        "atr14": series([0.1] * count),
        "atr_average": series([0.1] * count),
        "bb_mid": series([1.0] * count),
        "bb_upper": series([1.1] * count),
        "bb_lower": series([0.9] * count),
    }
    monkeypatch.setattr(
        strategies, "_indicators", lambda _df: indicator_data
    )

    result = build_chart_data(candles)
    colors = {row["color"] for row in result["macdHistogram"]}

    assert colors == {"#26a69a", "#ef5350"}



def test_analysis_returns_wait_when_an_indicator_is_unavailable(monkeypatch):
    """A missing final EMA value prevents a CALL/PUT direction decision."""
    candles = make_candles(30)
    count = len(candles)

    def series(value):
        return pd.Series([value] * count, dtype="float64")

    indicator_data = {
        "ema9": series(float("nan")),
        "ema21": series(1.0),
        "rsi14": series(60.0),
        "macd": series(0.1),
        "macd_signal": series(0.05),
        "macd_hist": series(0.05),
        "atr14": series(0.1),
        "atr_average": series(0.2),
        "bb_mid": series(1.0),
        "bb_upper": series(1.1),
        "bb_lower": series(0.9),
    }
    monkeypatch.setattr(
        strategies, "_indicators", lambda _df: indicator_data
    )

    result = analyze_candles(candles)

    assert result["signal"] == "WAIT"
    assert result["signal_grade"] == "WAIT"
    assert result["signal_score"] == 0
    assert result["expiry_recommendation_minutes"] is None
    assert "EMA trend and RSI do not align" in result["reason"]
