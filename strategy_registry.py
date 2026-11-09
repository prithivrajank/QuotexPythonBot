"""Versioned, read-only strategy registry.

All strategies consume historical OHLC candles and return the common analysis shape.
No strategy in this module places trades or sends notifications.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from strategies import analyze_candles

STRATEGIES: dict[str, dict[str, Any]] = {
    "EMA_RSI_V1": {
        "name": "EMA_RSI_V1", "version": "1.0.0",
        "description": "EMA 9/21 trend with RSI momentum confirmation.",
    },
    "SCORE_ENGINE_V2": {
        "name": "SCORE_ENGINE_V2", "version": "2.0.0",
        "description": "Weighted EMA, RSI, MACD, candle-body and breakout score.",
    },
    "BREAKOUT_V3": {
        "name": "BREAKOUT_V3", "version": "3.0.0",
        "description": "20-candle range breakout confirmed by EMA trend and RSI.",
    },
}

def list_strategies() -> list[dict[str, str]]:
    return [dict(item) for item in STRATEGIES.values()]

def get_strategy(name: str | None = None) -> dict[str, Any]:
    key = (name or "SCORE_ENGINE_V2").strip().upper()
    if key not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{key}'. Supported: {', '.join(STRATEGIES)}")
    return STRATEGIES[key]

def _ema_rsi(candles: list[dict]) -> dict[str, Any]:
    result = analyze_candles(candles)
    frame = pd.DataFrame(candles)
    if len(frame) < 22 or not {"close", "high", "low", "open"}.issubset(frame.columns):
        result.update(signal="WAIT", reason="EMA_RSI_V1 requires at least 22 valid OHLC candles")
    else:
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi = 100 - 100 / (1 + rs)
        rsi_value = 100.0 if loss.iloc[-1] == 0 and gain.iloc[-1] > 0 else float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
        signal = "CALL" if ema9 > ema21 and 50 <= rsi_value <= 70 else "PUT" if ema9 < ema21 and 30 <= rsi_value <= 50 else "WAIT"
        result.update(signal=signal, reason="EMA 9/21 and RSI confirmation" if signal != "WAIT" else "EMA/RSI conditions are not aligned",
                      signal_strength="MODERATE" if signal != "WAIT" else "LOW",
                      signal_score=4 if signal != "WAIT" else 0, signal_grade="MODERATE" if signal != "WAIT" else "WAIT",
                      ema_9=round(float(ema9), 6), ema_21=round(float(ema21), 6), rsi_14=round(rsi_value, 2),
                      expiry_recommendation_minutes=1 if signal != "WAIT" else None)
    return result

def _score_engine(candles: list[dict]) -> dict[str, Any]:
    return analyze_candles(candles)

def _breakout(candles: list[dict]) -> dict[str, Any]:
    result = analyze_candles(candles)
    frame = pd.DataFrame(candles)
    required = {"open", "high", "low", "close"}
    if len(frame) < 22 or not required.issubset(frame.columns):
        result.update(signal="WAIT", reason="BREAKOUT_V3 requires at least 22 valid OHLC candles")
        return result
    for col in required:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=list(required))
    if len(frame) < 22:
        result.update(signal="WAIT", reason="Insufficient valid OHLC candles")
        return result
    prior = frame.iloc[-21:-1]
    last = frame.iloc[-1]
    close = frame["close"]
    ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    resistance, support = float(prior.high.max()), float(prior.low.min())
    signal = "CALL" if float(last.close) > resistance and ema9 > ema21 else "PUT" if float(last.close) < support and ema9 < ema21 else "WAIT"
    result.update(signal=signal,
        reason="20-candle breakout confirmed by EMA trend" if signal != "WAIT" else "No confirmed 20-candle breakout",
        signal_score=8 if signal != "WAIT" else 0, signal_grade="MODERATE" if signal != "WAIT" else "WAIT",
        signal_strength="MODERATE" if signal != "WAIT" else "LOW",
        support_20=round(support, 6), resistance_20=round(resistance, 6),
        ema_9=round(float(ema9), 6), ema_21=round(float(ema21), 6),
        expiry_recommendation_minutes=1 if signal != "WAIT" else None)
    return result

_ANALYZERS: dict[str, Callable[[list[dict]], dict[str, Any]]] = {
    "EMA_RSI_V1": _ema_rsi,
    "SCORE_ENGINE_V2": _score_engine,
    "BREAKOUT_V3": _breakout,
}

def analyze_with_strategy(candles: list[dict], strategy_name: str | None = None) -> dict[str, Any]:
    metadata = get_strategy(strategy_name)
    result = _ANALYZERS[metadata["name"]](candles)
    result["strategy_name"] = metadata["name"]
    result["strategy_version"] = metadata["version"]
    return result

def strategy_metadata(name: str | None = None) -> dict[str, str]:
    return dict(get_strategy(name))
