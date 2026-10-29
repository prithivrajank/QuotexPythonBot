"""Read-only technical indicators and heuristic analysis for OHLC candles."""
from __future__ import annotations

import pandas as pd

REQUIRED = {"open", "high", "low", "close"}


def _frame(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    df = pd.DataFrame(candles).copy()
    if not REQUIRED.issubset(df.columns):
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    for col in REQUIRED:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=list(REQUIRED)).reset_index(drop=True)


def _indicators(df: pd.DataFrame) -> dict[str, pd.Series]:
    close = df["close"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    return {
        "ema9": ema9,
        "ema21": ema21,
        "rsi14": rsi,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_mid": bb_mid,
        "bb_upper": bb_mid + 2 * bb_std,
        "bb_lower": bb_mid - 2 * bb_std,
    }


def _last(series: pd.Series):
    if series.empty or pd.isna(series.iloc[-1]):
        return None
    return float(series.iloc[-1])


def analyze_candles(candles: list[dict], min_rows: int = 30) -> dict:
    """Return CALL/PUT/WAIT plus indicator context; not a validated trading system."""
    df = _frame(candles)
    if len(df) < min_rows:
        return {
            "signal": "WAIT",
            "reason": f"Need at least {min_rows} valid candles",
            "candles_used": len(df),
            "strategy_version": "indicator-context-0.2",
        }

    ind = _indicators(df)
    close = df["close"]
    last_rsi = _last(ind["rsi14"])
    bullish = ind["ema9"].iloc[-1] > ind["ema21"].iloc[-1] and close.iloc[-1] > df["open"].iloc[-1]
    bearish = ind["ema9"].iloc[-1] < ind["ema21"].iloc[-1] and close.iloc[-1] < df["open"].iloc[-1]

    if bullish and last_rsi is not None and 50 <= last_rsi <= 68:
        signal, reason = "CALL", "EMA(9) above EMA(21), bullish latest candle, RSI in momentum range"
    elif bearish and last_rsi is not None and 32 <= last_rsi <= 50:
        signal, reason = "PUT", "EMA(9) below EMA(21), bearish latest candle, RSI in momentum range"
    else:
        signal, reason = "WAIT", "Trend/candle/RSI filters do not align"

    support = float(df["low"].tail(20).min())
    resistance = float(df["high"].tail(20).max())

    # Expiry hint is a transparent heuristic, not a probability or win guarantee.
    expiry_recommendation = None
    expiry_reason = "WAIT signal: no expiry recommended"
    signal_strength = "LOW"
    if signal in {"CALL", "PUT"}:
        direction = 1 if signal == "CALL" else -1
        last_row = df.iloc[-1]
        candle_range = max(float(last_row["high"] - last_row["low"]), 1e-12)
        body_ratio = abs(float(last_row["close"] - last_row["open"])) / candle_range
        last_three = df.tail(3)
        aligned_candles = sum(
            (float(row["close"]) > float(row["open"])) if direction > 0
            else (float(row["close"]) < float(row["open"]))
            for _, row in last_three.iterrows()
        )
        trend_aligned = (float(ind["ema9"].iloc[-1]) - float(ind["ema21"].iloc[-1])) * direction > 0
        macd_aligned = float(ind["macd_hist"].iloc[-1]) * direction > 0
        current_candle_aligned = (
            float(last_row["close"]) > float(last_row["open"] if direction > 0 else last_row["close"])
            if direction > 0 else float(last_row["close"]) < float(last_row["open"])
        )
        macd_hist = float(ind["macd_hist"].iloc[-1])
        previous_macd_hist = float(ind["macd_hist"].iloc[-2])
        macd_momentum_increasing = (
            macd_hist > previous_macd_hist if direction > 0 else macd_hist < previous_macd_hist
        )
        # Prefer 1 minute when momentum is strong and immediate; prefer 2 minutes
        # when direction is aligned but the latest candle is less decisive.
        if (
            trend_aligned and macd_aligned and macd_momentum_increasing
            and current_candle_aligned and body_ratio >= 0.65
        ):
            expiry_recommendation = 1
            expiry_reason = "Trend and MACD align, momentum is increasing, and latest candle body is strong; heuristic favours 1 minute"
            signal_strength = "MODERATE"
        elif trend_aligned and macd_aligned and aligned_candles >= 2:
            expiry_recommendation = 2
            expiry_reason = "Trend and MACD align across multiple candles, but immediate momentum is less decisive; heuristic favours 2 minutes"
            signal_strength = "MODERATE"
        else:
            expiry_recommendation = 1
            expiry_reason = "Trend confirmation is weak or mixed; 1 minute is only a short-duration heuristic, consider WAIT rather than treating this as a strong entry"
            signal_strength = "LOW"

    return {
        "signal": signal,
        "reason": reason,
        "expiry_recommendation_minutes": expiry_recommendation,
        "expiry_reason": expiry_reason,
        "signal_strength": signal_strength,
        "rsi_14": round(last_rsi, 2) if last_rsi is not None else None,
        "ema_9": round(float(ind["ema9"].iloc[-1]), 6),
        "ema_21": round(float(ind["ema21"].iloc[-1]), 6),
        "macd": round(_last(ind["macd"]), 7) if _last(ind["macd"]) is not None else None,
        "macd_signal": round(_last(ind["macd_signal"]), 7) if _last(ind["macd_signal"]) is not None else None,
        "macd_histogram": round(_last(ind["macd_hist"]), 7) if _last(ind["macd_hist"]) is not None else None,
        "bollinger_upper": round(_last(ind["bb_upper"]), 6) if _last(ind["bb_upper"]) is not None else None,
        "bollinger_middle": round(_last(ind["bb_mid"]), 6) if _last(ind["bb_mid"]) is not None else None,
        "bollinger_lower": round(_last(ind["bb_lower"]), 6) if _last(ind["bb_lower"]) is not None else None,
        "support_20": round(support, 6),
        "resistance_20": round(resistance, 6),
        "candles_used": len(df),
        "strategy_version": "indicator-context-0.2",
    }


def build_chart_data(candles: list[dict]) -> dict:
    """Build serializable candlestick, EMA, Bollinger, and MACD chart series."""
    df = _frame(candles)
    if df.empty:
        return {"candles": [], "ema9": [], "ema21": [], "bbUpper": [], "bbMiddle": [],
                "bbLower": [], "support20": [], "resistance20": [], "macd": [], "macdSignal": [], "macdHistogram": []}
    ind = _indicators(df)
    candle_rows = []
    for _, row in df.iterrows():
        timestamp = int(row["time"])
        candle_rows.append({
            "time": timestamp,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })

    def line(series: pd.Series) -> list[dict]:
        points = []
        for index, value in enumerate(series):
            if pd.notna(value):
                points.append({"time": int(df.iloc[index]["time"]), "value": float(value)})
        return points

    histogram = []
    for index, value in enumerate(ind["macd_hist"]):
        if pd.notna(value):
            histogram.append({
                "time": int(df.iloc[index]["time"]),
                "value": float(value),
                "color": "#26a69a" if value >= 0 else "#ef5350",
            })
    support = df["low"].rolling(20, min_periods=1).min()
    resistance = df["high"].rolling(20, min_periods=1).max()
    return {
        "candles": candle_rows,
        "ema9": line(ind["ema9"]),
        "ema21": line(ind["ema21"]),
        "bbUpper": line(ind["bb_upper"]),
        "bbMiddle": line(ind["bb_mid"]),
        "bbLower": line(ind["bb_lower"]),
        "support20": line(support),
        "resistance20": line(resistance),
        "macd": line(ind["macd"]),
        "macdSignal": line(ind["macd_signal"]),
        "macdHistogram": histogram,
    }
