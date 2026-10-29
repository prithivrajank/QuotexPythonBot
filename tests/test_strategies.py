import math

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


def test_analysis_includes_macd_bollinger_and_support_resistance():
    result = analyze_candles(make_candles())
    assert result["signal"] in {"CALL", "PUT", "WAIT"}
    assert "macd_histogram" in result
    assert "bollinger_upper" in result
    assert "bollinger_middle" in result
    assert "bollinger_lower" in result
    assert result["support_20"] <= result["resistance_20"]


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
