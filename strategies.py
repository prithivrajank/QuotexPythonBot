"""Read-only technical indicators and scored heuristic analysis for OHLC candles."""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED = {"open", "high", "low", "close"}
STRATEGY_VERSION = "signal-score-v0.3"


def _frame(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    df = pd.DataFrame(candles).copy()
    if not REQUIRED.issubset(df.columns):
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    for col in REQUIRED:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(REQUIRED)).reset_index(drop=True)
    numeric = df[list(REQUIRED)].to_numpy(dtype=float)
    finite_positive = np.isfinite(numeric).all(axis=1) & (numeric > 0).all(axis=1)
    df = df.loc[finite_positive].reset_index(drop=True)
    valid = (
        (df["high"] >= df["low"])
        & (df["high"] >= df[["open", "close"]].max(axis=1))
        & (df["low"] <= df[["open", "close"]].min(axis=1))
    )
    return df.loc[valid].reset_index(drop=True)


def _indicators(df: pd.DataFrame) -> dict[str, pd.Series]:
    close = df["close"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0.0)
    rsi = rsi.mask((gain == 0) & (loss == 0), 50.0)

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    atr_average = atr14.shift(1).rolling(20, min_periods=10).mean()

    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    return {
        "ema9": ema9, "ema21": ema21, "rsi14": rsi,
        "macd": macd, "macd_signal": macd_signal, "macd_hist": macd_hist,
        "atr14": atr14, "atr_average": atr_average,
        "bb_mid": bb_mid, "bb_upper": bb_mid + 2 * bb_std,
        "bb_lower": bb_mid - 2 * bb_std,
    }


def _last(series: pd.Series):
    if series.empty or pd.isna(series.iloc[-1]):
        return None
    return float(series.iloc[-1])


def _empty_analysis(reason: str, candles_used: int) -> dict:
    return {
        "signal": "WAIT", "reason": reason,
        "expiry_recommendation_minutes": None,
        "expiry_reason": "WAIT signal: no expiry recommended",
        "signal_strength": "LOW",
        "signal_score": 0, "signal_grade": "WAIT",
        "rsi_14": None, "ema_9": None, "ema_21": None,
        "macd": None, "macd_signal": None, "macd_histogram": None,
        "bollinger_upper": None, "bollinger_middle": None, "bollinger_lower": None,
        "support_20": None, "resistance_20": None,
        "atr_14": None, "atr_recent_average": None, "atr_low_volatility": None,
        "candles_used": candles_used, "strategy_version": STRATEGY_VERSION,
    }


def analyze_candles(candles: list[dict], min_rows: int = 30) -> dict:
    """Return scored CALL/PUT/WAIT analysis with backward-compatible fields."""
    df = _frame(candles)
    if len(df) < max(min_rows, 21):
        return _empty_analysis(
            f"Need at least {max(min_rows, 21)} valid candles", len(df)
        )

    ind = _indicators(df)
    last = df.iloc[-1]
    ema9, ema21 = _last(ind["ema9"]), _last(ind["ema21"])
    rsi = _last(ind["rsi14"])
    macd_value = _last(ind["macd"])
    macd_signal_value = _last(ind["macd_signal"])
    macd_hist = _last(ind["macd_hist"])
    previous_hist = _last(ind["macd_hist"].iloc[:-1])
    atr14, atr_average = _last(ind["atr14"]), _last(ind["atr_average"])

    # Previous 20-candle levels exclude the current candle.
    previous_20 = df.iloc[-21:-1]
    support = float(previous_20["low"].min())
    resistance = float(previous_20["high"].max())

    parts = {
        "ema_trend_alignment": 0,
        "rsi_momentum_alignment": 0,
        "macd_histogram_alignment": 0,
        "strong_candle_body": 0,
        "breakout_confirmation": 0,
    }
    direction = None
    sign = 0

    # Strict direction filter: CALL RSI 55-70; PUT RSI 30-45.
    if ema9 is not None and ema21 is not None and rsi is not None:
        if ema9 > ema21 and 55 <= rsi <= 70:
            direction, sign = "CALL", 1
        elif ema9 < ema21 and 30 <= rsi <= 45:
            direction, sign = "PUT", -1

    reasons = []
    if direction is not None:
        parts["ema_trend_alignment"] = 2
        parts["rsi_momentum_alignment"] = 2

        # MACD earns points only if aligned and improving vs previous candle.
        macd_aligned = macd_hist is not None and macd_hist * sign > 0
        macd_improving = (
            previous_hist is not None and macd_hist is not None
            and (macd_hist > previous_hist if sign > 0 else macd_hist < previous_hist)
        )
        if macd_aligned and macd_improving:
            parts["macd_histogram_alignment"] = 2
            reasons.append("MACD histogram aligned and improving")

        candle_range = max(float(last["high"] - last["low"]), 1e-12)
        body_ratio = abs(float(last["close"] - last["open"])) / candle_range
        candle_aligned = (
            float(last["close"]) > float(last["open"])
            if sign > 0 else float(last["close"]) < float(last["open"])
        )
        if candle_aligned and body_ratio > 0.60:
            parts["strong_candle_body"] = 2
            reasons.append("Strong candle body exceeds 60% of range")

        breakout = (
            float(last["close"]) > resistance
            if sign > 0 else float(last["close"]) < support
        )
        if breakout:
            parts["breakout_confirmation"] = 2
            reasons.append("Previous 20-candle breakout confirmed")

    score = sum(parts.values())
    low_volatility = (
        atr14 is not None and atr_average is not None and atr14 < atr_average
    )

    # Requested score bands.
    if direction is None or score <= 3:
        signal, grade, strength = "WAIT", "WAIT", "LOW"
        expiry = None
        expiry_reason = "WAIT signal: no expiry recommended"
        reason = (
            "EMA trend and RSI do not align; CALL requires RSI 55-70 "
            "and PUT requires RSI 30-45"
            if direction is None else "Score 0-3: insufficient confirmation; WAIT"
        )
    else:
        signal = direction
        if score <= 6:
            grade, strength = "WEAK", "LOW"
        elif score <= 8:
            grade, strength = "MODERATE", "MODERATE"
        else:
            grade, strength = "STRONG", "HIGH"

        if low_volatility:
            # Downgrade one level; never upgrade an already LOW signal.
            strength = {
                "HIGH": "MODERATE",
                "MODERATE": "LOW",
                "LOW": "LOW",
            }[strength]
            expiry = 2
            expiry_reason = (
                "ATR(14) is below recent average volatility; signal strength "
                "downgraded and aggressive 1-minute expiry avoided"
            )
            reasons.append("ATR(14) below recent average volatility")
        else:
            expiry = 1 if score >= 7 else 2
            expiry_reason = (
                "Confirmation score supports a 1-minute heuristic expiry"
                if expiry == 1
                else "Lower confirmation score favours a less aggressive 2-minute heuristic expiry"
            )
        reason = "; ".join(reasons) if reasons else "EMA and RSI are aligned"

    return {
        # Existing response field names retained.
        "signal": signal,
        "reason": reason,
        "expiry_recommendation_minutes": expiry,
        "expiry_reason": expiry_reason,
        "signal_strength": strength,
        "rsi_14": round(rsi, 2) if rsi is not None else None,
        "ema_9": round(ema9, 6) if ema9 is not None else None,
        "ema_21": round(ema21, 6) if ema21 is not None else None,
        "macd": round(macd_value, 7) if macd_value is not None else None,
        "macd_signal": round(macd_signal_value, 7) if macd_signal_value is not None else None,
        "macd_histogram": round(macd_hist, 7) if macd_hist is not None else None,
        "bollinger_upper": round(_last(ind["bb_upper"]), 6) if _last(ind["bb_upper"]) is not None else None,
        "bollinger_middle": round(_last(ind["bb_mid"]), 6) if _last(ind["bb_mid"]) is not None else None,
        "bollinger_lower": round(_last(ind["bb_lower"]), 6) if _last(ind["bb_lower"]) is not None else None,
        "support_20": round(support, 6),
        "resistance_20": round(resistance, 6),
        # New response fields.
        "signal_score": int(score),
        "signal_grade": grade,
        "score_breakdown": parts,
        "atr_14": round(atr14, 7) if atr14 is not None else None,
        "atr_recent_average": round(atr_average, 7) if atr_average is not None else None,
        "atr_low_volatility": bool(low_volatility),
        "candles_used": len(df),
        "strategy_version": STRATEGY_VERSION,
    }


def build_chart_data(candles: list[dict]) -> dict:
    """Build serializable candlestick, EMA, Bollinger, and MACD chart series."""
    df = _frame(candles)
    if df.empty:
        return {
            "candles": [], "ema9": [], "ema21": [], "bbUpper": [],
            "bbMiddle": [], "bbLower": [], "support20": [],
            "resistance20": [], "macd": [], "macdSignal": [],
            "macdHistogram": [],
        }

    ind = _indicators(df)
    candle_rows = []
    for _, row in df.iterrows():
        candle_rows.append({
            "time": int(row["time"]), "open": float(row["open"]),
            "high": float(row["high"]), "low": float(row["low"]),
            "close": float(row["close"]),
        })

    def line(series: pd.Series) -> list[dict]:
        return [
            {"time": int(df.iloc[i]["time"]), "value": float(value)}
            for i, value in enumerate(series) if pd.notna(value)
        ]

    histogram = [
        {
            "time": int(df.iloc[i]["time"]),
            "value": float(value),
            "color": "#26a69a" if value >= 0 else "#ef5350",
        }
        for i, value in enumerate(ind["macd_hist"]) if pd.notna(value)
    ]
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
