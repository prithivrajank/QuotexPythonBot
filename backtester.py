"""Timestamp-safe historical backtesting for the existing CALL/PUT/WAIT strategy.

Signals are calculated using candles available up to the decision candle only.
Entry is the decision candle close; exit is the close N candles later.
This is a directional price-movement simulation, not a binary-options payout model.
"""
from __future__ import annotations

from typing import Any

from strategies import STRATEGY_VERSION, analyze_candles

SUPPORTED_EXPIRIES = (1, 2, 3)
MINIMUM_HISTORY = 30


def _empty_stats(expiry: int) -> dict[str, Any]:
    return {
        "expiry": expiry,
        "total_signals": 0,
        "call_signals": 0,
        "put_signals": 0,
        "wait_signals": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "profit_factor": None,
        "gross_profit_pct": 0.0,
        "gross_loss_pct": 0.0,
    }


def _evaluate_expiry(candles: list[dict], expiry: int) -> dict[str, Any]:
    stats = _empty_stats(expiry)
    gross_profit = 0.0
    gross_loss = 0.0

    # Keep enough future candles to settle each trade. Prefix-only analysis
    # prevents future candles from leaking into the signal calculation.
    last_decision_index = len(candles) - expiry - 1
    for index in range(MINIMUM_HISTORY - 1, last_decision_index + 1):
        history = candles[: index + 1]
        analysis = analyze_candles(history)
        signal = str(analysis.get("signal", "WAIT")).upper()
        stats["total_signals"] += 1

        if signal == "WAIT":
            stats["wait_signals"] += 1
            continue
        if signal not in {"CALL", "PUT"}:
            stats["wait_signals"] += 1
            continue

        stats["call_signals" if signal == "CALL" else "put_signals"] += 1
        entry = float(candles[index]["close"])
        exit_price = float(candles[index + expiry]["close"])
        if entry <= 0:
            continue

        move_pct = (exit_price - entry) / entry * 100.0
        directional_return = move_pct if signal == "CALL" else -move_pct

        if directional_return > 0:
            stats["wins"] += 1
            gross_profit += directional_return
        elif directional_return < 0:
            stats["losses"] += 1
            gross_loss += abs(directional_return)
        # Equal entry/exit is neither a win nor a loss and is excluded from
        # the win-rate denominator, but the signal remains in total_signals.

    scored = stats["wins"] + stats["losses"]
    stats["win_rate"] = round(stats["wins"] / scored * 100.0, 2) if scored else None
    stats["gross_profit_pct"] = round(gross_profit, 6)
    stats["gross_loss_pct"] = round(gross_loss, 6)
    stats["profit_factor"] = (
        round(gross_profit / gross_loss, 4) if gross_loss > 0
        else (None if gross_profit == 0 else None)
    )
    return stats


def run_backtest(
    candles: list[dict],
    symbol: str,
    expiry: int = 1,
) -> dict[str, Any]:
    """Backtest the strategy at 1/2/3-candle expiries on chronological OHLC."""
    if expiry not in SUPPORTED_EXPIRIES:
        raise ValueError("expiry must be 1, 2, or 3 candles")
    if len(candles) < MINIMUM_HISTORY + expiry + 1:
        raise ValueError(
            f"At least {MINIMUM_HISTORY + expiry + 1} candles are required "
            f"for a {expiry}-candle expiry"
        )

    ordered = sorted(candles, key=lambda row: int(row.get("time", 0)))
    expiry_results = [_evaluate_expiry(ordered, value) for value in SUPPORTED_EXPIRIES]
    selected = next(item for item in expiry_results if item["expiry"] == expiry)

    eligible = [item for item in expiry_results if item["wins"] + item["losses"] > 0]
    best = max(
        eligible,
        key=lambda item: (
            item["win_rate"],
            item["profit_factor"] if item["profit_factor"] is not None else -1,
            item["wins"] + item["losses"],
        ),
    ) if eligible else None

    return {
        **selected,
        "symbol": symbol,
        "best_asset": symbol,
        "best_expiry": best["expiry"] if best else None,
        "expiry_comparison": expiry_results,
        "strategy_version": STRATEGY_VERSION,
        "candles_used": len(ordered),
        "methodology": (
            "Signals use only candles up to each decision candle. Entry is its close; "
            "exit is the close after the selected number of candles. Win rate excludes "
            "WAIT and flat outcomes. Profit factor uses summed directional percentage "
            "moves, not broker payout, fees, or executable fills."
        ),
    }
