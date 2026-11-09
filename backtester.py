"""Timestamp-safe historical backtesting for registered strategy versions."""
from __future__ import annotations

from typing import Any, Callable

from strategy_registry import analyze_with_strategy, get_strategy, list_strategies

SUPPORTED_EXPIRIES = (1, 2, 3)
MINIMUM_HISTORY = 30


def _empty_stats(expiry: int) -> dict[str, Any]:
    return {"expiry": expiry, "total_signals": 0, "call_signals": 0,
            "put_signals": 0, "wait_signals": 0, "wins": 0, "losses": 0,
            "win_rate": None, "profit_factor": None,
            "gross_profit_pct": 0.0, "gross_loss_pct": 0.0}


def _evaluate_expiry(candles: list[dict], expiry: int,
                     analyzer: Callable[[list[dict]], dict[str, Any]]) -> dict[str, Any]:
    stats = _empty_stats(expiry)
    gross_profit = gross_loss = 0.0
    last_decision_index = len(candles) - expiry - 1
    for index in range(MINIMUM_HISTORY - 1, last_decision_index + 1):
        analysis = analyzer(candles[:index + 1])
        signal = str(analysis.get("signal", "WAIT")).upper()
        stats["total_signals"] += 1
        if signal not in {"CALL", "PUT"}:
            stats["wait_signals"] += 1
            continue
        stats["call_signals" if signal == "CALL" else "put_signals"] += 1
        entry, exit_price = float(candles[index]["close"]), float(candles[index + expiry]["close"])
        if entry <= 0:
            continue
        move = (exit_price - entry) / entry * 100.0
        directional = move if signal == "CALL" else -move
        if directional > 0:
            stats["wins"] += 1
            gross_profit += directional
        elif directional < 0:
            stats["losses"] += 1
            gross_loss += abs(directional)
    scored = stats["wins"] + stats["losses"]
    stats["win_rate"] = round(stats["wins"] / scored * 100, 2) if scored else None
    stats["gross_profit_pct"], stats["gross_loss_pct"] = round(gross_profit, 6), round(gross_loss, 6)
    stats["profit_factor"] = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    return stats


def run_strategy_backtest(candles: list[dict], symbol: str, strategy_name: str,
                          expiry: int = 1) -> dict[str, Any]:
    """Run one registered strategy across 1/2/3-candle expiries."""
    if expiry not in SUPPORTED_EXPIRIES:
        raise ValueError("expiry must be 1, 2, or 3 candles")
    metadata = get_strategy(strategy_name)
    minimum = MINIMUM_HISTORY + max(SUPPORTED_EXPIRIES)
    if len(candles) < minimum:
        raise ValueError(f"At least {minimum} candles are required to compare all supported expiries")
    ordered = sorted(candles, key=lambda row: int(row.get("time", 0)))
    analyzer = lambda history: analyze_with_strategy(history, metadata["name"])
    comparisons = [_evaluate_expiry(ordered, e, analyzer) for e in SUPPORTED_EXPIRIES]
    selected = next(item for item in comparisons if item["expiry"] == expiry)
    eligible = [item for item in comparisons if item["wins"] + item["losses"]]
    best = max(eligible, key=lambda item: (item["win_rate"], item["wins"] + item["losses"])) if eligible else None
    return {**selected, "symbol": symbol, "best_asset": symbol,
            "best_expiry": best["expiry"] if best else None,
            "expiry_comparison": comparisons, "strategy_name": metadata["name"],
            "strategy_version": metadata["version"], "candles_used": len(ordered),
            "methodology": ("Signals use only candles up to each decision candle. Entry is its close; "
                "exit is the close after the selected number of candles. Win rate excludes WAIT "
                "and flat outcomes. Profit factor uses summed directional percentage moves, "
                "not broker payout, fees, or executable fills.")}


def run_all_strategies(candles: list[dict], symbol: str, expiry: int = 1) -> dict[str, Any]:
    """Backtest every registered strategy and rank by win rate, then sample size."""
    results = [run_strategy_backtest(candles, symbol, item["name"], expiry)
               for item in list_strategies()]
    ranked = sorted(results, key=lambda x: (
        x["win_rate"] is None,
        -(x["win_rate"] if x["win_rate"] is not None else 0),
        -(x["wins"] + x["losses"]), x["strategy_name"]))
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    return {"symbol": symbol, "expiry": expiry, "strategies": ranked,
            "leader": ranked[0]["strategy_name"] if ranked and ranked[0]["win_rate"] is not None else None,
            "ranking_method": "Win rate descending; completed WIN/LOSS sample size descending as tie-breaker."}


def run_backtest(candles: list[dict], symbol: str, expiry: int = 1,
                 strategy_name: str = "SCORE_ENGINE_V2") -> dict[str, Any]:
    """Backward-compatible single-strategy backtest (defaults to SCORE_ENGINE_V2)."""
    return run_strategy_backtest(candles, symbol, strategy_name, expiry)


def run_strategy_comparison(candles: list[dict], symbol: str, expiry: int = 1) -> dict[str, Any]:
    """Named alias for the all-strategy comparison report."""
    return run_all_strategies(candles, symbol, expiry)
