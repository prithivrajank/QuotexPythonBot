"""Pure strategy calculations for validated OHLC candles (no trading actions)."""
from __future__ import annotations
import pandas as pd

REQUIRED = {"open", "high", "low", "close"}


def analyze_candles(candles: list[dict], min_rows: int = 30) -> dict:
    """Analyze a list of real OHLC candles and return CALL/PUT/WAIT plus reasons.

    This is a starting heuristic, not a validated profitable strategy. Caller must
    validate freshness and timestamps before invoking it.
    """
    if not candles:
        return {"signal": "WAIT", "reason": "No candle data available"}
    df = pd.DataFrame(candles)
    if not REQUIRED.issubset(df.columns):
        return {"signal": "WAIT", "reason": "Candle data is missing OHLC fields"}
    for col in REQUIRED:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(REQUIRED))
    if len(df) < min_rows:
        return {"signal": "WAIT", "reason": f"Need at least {min_rows} valid candles"}
    close = df["close"]
    ema_fast = close.ewm(span=9, adjust=False).mean()
    ema_slow = close.ewm(span=21, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    last_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None
    bullish = ema_fast.iloc[-1] > ema_slow.iloc[-1] and close.iloc[-1] > df["open"].iloc[-1]
    bearish = ema_fast.iloc[-1] < ema_slow.iloc[-1] and close.iloc[-1] < df["open"].iloc[-1]
    if bullish and last_rsi is not None and 50 <= last_rsi <= 68:
        signal, reason = "CALL", "EMA(9) above EMA(21), bullish latest candle, RSI in momentum range"
    elif bearish and last_rsi is not None and 32 <= last_rsi <= 50:
        signal, reason = "PUT", "EMA(9) below EMA(21), bearish latest candle, RSI in momentum range"
    else:
        signal, reason = "WAIT", "Trend/candle/RSI filters do not align"
    return {"signal": signal, "reason": reason, "rsi_14": round(last_rsi, 2) if last_rsi is not None else None, "candles_used": len(df), "strategy_version": "starter-0.1"}
