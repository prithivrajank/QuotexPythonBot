"""Automatic strategy promotion and demotion based on completed outcomes.

Seed rates are the operator-provided baseline (V1 58%, V2 64%, V3 71%).
Once a strategy has enough completed historical outcomes, its measured win rate
replaces its seed rate. Selection is advisory for analysis only; it places no trades.
"""
from __future__ import annotations

import os
from typing import Any

from signal_history import get_strategy_statistics
from strategy_registry import get_strategy, list_strategies

SEED_WIN_RATES = {
    "EMA_RSI_V1": 58.0,
    "SCORE_ENGINE_V2": 64.0,
    "BREAKOUT_V3": 71.0,
}
MIN_COMPLETED_SIGNALS = max(1, int(os.getenv("STRATEGY_PROMOTION_MIN_SIGNALS", "20")))
AUTO_SELECTION_DEFAULT = True


def _auto_enabled() -> bool:
    return os.getenv("AUTO_STRATEGY_SELECTION", "true").strip().lower() not in {"0", "false", "no", "off"}


def get_strategy_manager_status() -> dict[str, Any]:
    """Return the current rank, active promotion and demotion decisions."""
    history = get_strategy_statistics()
    rows: list[dict[str, Any]] = []
    for meta in list_strategies():
        name = meta["name"]
        observed = history.get(name, {})
        scored = int(observed.get("scored_signals", 0) or 0)
        measured_rate = observed.get("win_rate")
        use_measured = scored >= MIN_COMPLETED_SIGNALS and measured_rate is not None
        rate = float(measured_rate) if use_measured else SEED_WIN_RATES[name]
        rows.append({
            **meta,
            "win_rate": round(rate, 2),
            "measured_win_rate": measured_rate,
            "scored_signals": scored,
            "rate_source": "history" if use_measured else "operator_baseline",
        })
    rows.sort(key=lambda row: (-row["win_rate"], -row["scored_signals"], row["name"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["management_status"] = "PROMOTED" if rank == 1 else "DEMOTED" if rank == len(rows) else "RETAINED"
    active = rows[0]["name"] if rows else "SCORE_ENGINE_V2"
    configured = os.getenv("STRATEGY_NAME", "").strip().upper()
    auto_enabled = _auto_enabled()
    if not auto_enabled:
        active = get_strategy(configured or "SCORE_ENGINE_V2")["name"]
    return {
        "auto_selection_enabled": auto_enabled,
        "active_strategy": active,
        "promoted_strategy": rows[0]["name"] if rows else None,
        "demoted_strategy": rows[-1]["name"] if rows else None,
        "minimum_completed_signals_for_history": MIN_COMPLETED_SIGNALS,
        "strategies": rows,
        "decision": (
            "Highest win-rate strategy is promoted; lowest is demoted. Historical rates replace the supplied baseline after the minimum sample."
            if auto_enabled else "Automatic selection is disabled; STRATEGY_NAME controls the active strategy."
        ),
    }


def get_active_strategy() -> str:
    """Resolve the active strategy for live analysis."""
    status = get_strategy_manager_status()
    return status["active_strategy"]


def apply_strategy_management(analysis: dict[str, Any]) -> dict[str, Any]:
    """Attach current promotion state to a signal without changing its direction."""
    result = dict(analysis)
    status = get_strategy_manager_status()
    result["strategy_management"] = {
        "auto_selection_enabled": status["auto_selection_enabled"],
        "active_strategy": status["active_strategy"],
        "promoted_strategy": status["promoted_strategy"],
        "demoted_strategy": status["demoted_strategy"],
    }
    return result
