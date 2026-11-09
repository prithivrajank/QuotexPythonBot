"""Adaptive per-symbol performance classification with a five-minute cache."""
from __future__ import annotations

import threading
import time
from typing import Any

from signal_history import get_pair_performance_records

CACHE_TTL_SECONDS = 300
RECENT_WINDOW = 20
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def _classify(win_rate: float | None, scored_trades: int) -> str:
    # Small samples are not promoted to PRIORITY or demoted to DISABLED.
    if win_rate is None:
        return "WATCHLIST"
    if win_rate >= 65.0 and scored_trades >= 20:
        return "PRIORITY"
    if win_rate >= 55.0:
        return "NORMAL"
    if win_rate >= 45.0:
        return "WATCHLIST"
    if scored_trades >= 15:
        return "DISABLED"
    # Low sample count: monitor rather than permanently suppress the pair.
    return "WATCHLIST"


def _build_performance() -> dict[str, dict[str, Any]]:
    records_by_symbol = get_pair_performance_records()
    result: dict[str, dict[str, Any]] = {}

    for symbol, records in records_by_symbol.items():
        scored = [row for row in records if row.get("outcome") in ("WIN", "LOSS")]
        wins = sum(row.get("outcome") == "WIN" for row in scored)
        losses = len(scored) - wins
        win_rate = round(wins / len(scored) * 100.0, 2) if scored else None

        recent = scored[:RECENT_WINDOW]
        recent_wins = sum(row.get("outcome") == "WIN" for row in recent)
        recent_rate = (
            round(recent_wins / len(recent) * 100.0, 2) if recent else None
        )
        scores = [
            float(row["signal_score"])
            for row in records
            if row.get("signal_score") is not None
        ]
        average_score = round(sum(scores) / len(scores), 2) if scores else None
        status = _classify(win_rate, len(scored))

        result[symbol] = {
            "symbol": symbol,
            "win_rate": win_rate,
            "total_signals": len(records),
            "scored_trades": len(scored),
            "wins": wins,
            "losses": losses,
            "recent_20_signal_win_rate": recent_rate,
            "recent_20_scored_signals": len(recent),
            "average_signal_score": average_score,
            "status": status,
        }

    return result


def get_pair_performance(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return cached performance, refreshing from signal history every 5 minutes."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get("payload")
        if not force_refresh and cached is not None and now < float(_cache["expires_at"]):
            return {key: dict(value) for key, value in cached.items()}

        payload = _build_performance()
        _cache["payload"] = payload
        _cache["expires_at"] = now + CACHE_TTL_SECONDS
        return {key: dict(value) for key, value in payload.items()}


def get_pair_status(symbol: str) -> str:
    """Return the adaptive status for a symbol; unseen symbols default to WATCHLIST."""
    normalized = str(symbol).strip().upper()
    performance = get_pair_performance()
    for key, stats in performance.items():
        if key.strip().upper() == normalized:
            return str(stats["status"])
    return "WATCHLIST"


def filter_analysis(symbol: str, analysis: dict[str, Any]) -> dict[str, Any]:
    """Replace actionable output for a disabled pair with a backward-compatible WAIT."""
    status = get_pair_status(symbol)
    if status != "DISABLED":
        return analysis

    filtered = dict(analysis)
    filtered.update({
        "signal": "WAIT",
        "reason": "Pair temporarily disabled due to low performance",
        "pair_status": "DISABLED",
        "pair_filter_applied": True,
        "expiry_recommendation_minutes": None,
        "expiry_reason": "Disabled pair: no expiry recommended",
        "signal_strength": "LOW",
    })
    return filtered


def pair_performance_summary() -> dict[str, Any]:
    """Dashboard-ready sorted lists and cache metadata."""
    performance = list(get_pair_performance().values())
    top = sorted(
        (row for row in performance if row["win_rate"] is not None),
        key=lambda row: (-row["win_rate"], -row["scored_trades"], row["symbol"]),
    )
    worst = sorted(
        (row for row in performance if row["win_rate"] is not None),
        key=lambda row: (row["win_rate"], -row["scored_trades"], row["symbol"]),
    )
    return {
        "pairs": performance,
        "top_performing_pairs": top[:5],
        "worst_performing_pairs": worst[:5],
        "disabled_pairs": [row for row in performance if row["status"] == "DISABLED"],
        "priority_pairs": [row for row in performance if row["status"] == "PRIORITY"],
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }
