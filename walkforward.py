"""Chronological 70/30 walk-forward validation for the existing strategy.

Each segment is evaluated independently through the existing timestamp-safe
backtester. The validation segment never contributes candles to training.
Win rates are directional price-movement estimates, not broker payout results.
"""
from __future__ import annotations

from typing import Any

from backtester import MINIMUM_HISTORY, run_backtest
from strategies import STRATEGY_VERSION

TRAINING_RATIO = 0.70
VALIDATION_RATIO = 0.30


def run_walkforward(candles: list[dict], symbol: str, expiry: int = 1) -> dict[str, Any]:
    """Split chronological candles 70/30 and evaluate each period independently."""
    if isinstance(expiry, bool) or expiry not in (1, 2, 3):
        raise ValueError("expiry must be 1, 2, or 3 candles")

    if not isinstance(candles, list):
        raise ValueError("candles must be a list of timestamped OHLC records")
    seen_timestamps: set[int] = set()
    normalized: list[tuple[int, dict]] = []
    for index, row in enumerate(candles):
        if not isinstance(row, dict):
            raise ValueError(f"candle #{index + 1} is not an object")
        raw_timestamp = row.get("time")
        if isinstance(raw_timestamp, bool):
            raise ValueError(f"candle #{index + 1} has an invalid timestamp")
        try:
            timestamp = int(raw_timestamp)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"candle #{index + 1} has an invalid timestamp") from None
        if timestamp <= 0 or timestamp in seen_timestamps:
            raise ValueError(f"candle #{index + 1} has a non-positive or duplicate timestamp")
        seen_timestamps.add(timestamp)
        normalized.append((timestamp, row))
    ordered = [row for _timestamp, row in sorted(normalized, key=lambda item: item[0])]
    split_index = int(len(ordered) * TRAINING_RATIO)
    training = ordered[:split_index]
    validation = ordered[split_index:]

    # run_backtest compares all supported expiries and therefore requires
    # enough candles in each segment to settle the 3-candle comparison.
    minimum_segment = MINIMUM_HISTORY + 3
    if len(training) < minimum_segment or len(validation) < minimum_segment:
        raise ValueError(
            "At least 110 chronological candles are required so both the "
            "70% training and 30% validation periods contain enough history"
        )

    training_result = run_backtest(training, symbol=symbol, expiry=expiry)
    validation_result = run_backtest(validation, symbol=symbol, expiry=expiry)

    training_win_rate = training_result.get("win_rate")
    validation_win_rate = validation_result.get("win_rate")
    if training_win_rate is None or validation_win_rate is None:
        overfit_score = None
        status = "INSUFFICIENT_DATA"
    else:
        # Absolute percentage-point gap between in-sample and out-of-sample.
        overfit_score = round(abs(float(training_win_rate) - float(validation_win_rate)), 2)
        if overfit_score <= 5:
            status = "HEALTHY"
        elif overfit_score <= 15:
            status = "WARNING"
        else:
            status = "OVERFIT"

    return {
        "symbol": symbol,
        "training_ratio": 70,
        "validation_ratio": 30,
        "training_candles": len(training),
        "validation_candles": len(validation),
        "total_candles": len(ordered),
        "expiry": expiry,
        "training_win_rate": training_win_rate,
        "validation_win_rate": validation_win_rate,
        "overfit_score": overfit_score,
        "strategy_health": status,
        "status": status,
        "training": training_result,
        "validation": validation_result,
        "strategy_version": STRATEGY_VERSION,
        "methodology": (
            "Candles are sorted chronologically and split once: first 70% for "
            "training, final 30% for validation. The existing timestamp-safe "
            "strategy backtest is run independently inside each segment. "
            "Win rate excludes WAIT and flat outcomes. Overfit score is the "
            "absolute difference between training and validation win rates "
            "in percentage points; it is not a calibrated probability."
        ),
    }
