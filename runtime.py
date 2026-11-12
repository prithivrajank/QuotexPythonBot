"""Quota-aware multi-symbol scheduler and optional Telegram signal alerts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import os
import threading
from typing import Any


from data_collector import MarketDataError, data_source_label, get_candles
from signal_history import record_signal, score_due_outcomes
from pair_performance import filter_analysis, get_pair_status
from strategies import build_chart_data
from strategy_registry import analyze_with_strategy
from strategy_manager import get_active_strategy, apply_strategy_management
from telegram_market_data import notify_new_candle, telegram_configured
from health_monitor import record_candle, record_exception, record_signal as record_strategy_signal, record_telegram_result, set_component

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
]
DEFAULT_QUANTEX_SYMBOLS = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "EURUSD", "GBPUSD", "USDJPY"]
DEFAULT_A11KSA_SYMBOLS = ["EURUSD_otc"]


def _normalize_symbol(value: str) -> str:
    if os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower() in ("quantex", "otcharts", "quotexapi", "a11ksa"):
        value = value.strip()
        normalized = value.replace("/", "").replace("-", "").upper()
        return normalized[:-4] + "_otc" if normalized.endswith("_OTC") else normalized
    return value.strip().upper().replace("-", "/")
TIMEFRAME_SECONDS = int(os.getenv("FOREX_TIMEFRAME_SECONDS", "60"))
CANDLE_LIMIT = 100
DEFAULT_REFRESH_SECONDS = 300
_lock = threading.Lock()
_snapshots: dict[str, dict[str, Any]] = {}
_next_symbol_index = 0
_bot_enabled = False


def bot_status() -> dict[str, Any]:
    with _lock:
        return {"enabled": _bot_enabled, "message": "Bot is ON" if _bot_enabled else "Bot is OFF; scheduled provider requests are paused."}


def set_bot_enabled(enabled: bool) -> dict[str, Any]:
    global _bot_enabled
    with _lock:
        _bot_enabled = bool(enabled)
    return bot_status()


def configured_symbols() -> list[str]:
    """Read a comma-separated watchlist; one provider request scans one symbol."""
    raw = os.getenv("FOREX_SYMBOLS", "").strip()
    if not raw:
        legacy = os.getenv("FOREX_SYMBOL", "").strip()
        provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
        defaults = DEFAULT_A11KSA_SYMBOLS if provider == "a11ksa" else DEFAULT_QUANTEX_SYMBOLS if provider in ("quantex", "otcharts", "quotexapi") else DEFAULT_SYMBOLS
        raw = legacy or ",".join(defaults)
    symbols: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        symbol = _normalize_symbol(item)
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return symbols or DEFAULT_SYMBOLS.copy()


def refresh_interval_seconds() -> int:
    """Never refresh faster than five minutes to protect the free daily quota."""
    try:
        requested = int(os.getenv("REFRESH_INTERVAL_SECONDS", str(DEFAULT_REFRESH_SECONDS)))
    except ValueError:
        requested = DEFAULT_REFRESH_SECONDS
    return max(DEFAULT_REFRESH_SECONDS, min(requested, 3600))


def get_snapshot(symbol: str | None = None) -> dict[str, Any]:
    with _lock:
        if symbol:
            return dict(_snapshots.get(_normalize_symbol(symbol), {
                "available": False,
                "symbol": _normalize_symbol(symbol),
                "market_type": "provider-specific live/OTC market",
                "message": "This symbol has not been scanned yet. Wait for its turn in the rotating watchlist.",
            }))
        if _snapshots:
            # Most recently refreshed symbol snapshot.
            return dict(max(_snapshots.values(), key=lambda x: x.get("updated_at", "")))
    return {
        "available": False,
        "source": data_source_label(),
        "market_type": "Quotex demo OTC (read-only)" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa" else "Quotex market" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() in ("quantex", "otcharts", "quotexapi") else "standard forex, not Quotex OTC",
        "message": "Waiting for the first scheduled refresh.",
        "watchlist": configured_symbols(),
    }


def get_watchlist() -> dict[str, Any]:
    with _lock:
        snapshots = {key: {
            "available": value.get("available", False),
            "signal": (value.get("analysis") or {}).get("signal"),
            "updated_at": value.get("updated_at"),
            "message": value.get("message"),
        } for key, value in _snapshots.items()}
    symbols = configured_symbols()
    return {
        "source": data_source_label(),
        "market_type": "Quotex demo OTC (read-only)" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa" else "Quotex market" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() in ("quantex", "otcharts", "quotexapi") else "standard forex, not Quotex OTC",
        "symbols": symbols,
        "scanned": snapshots,
        "refresh_interval_seconds": refresh_interval_seconds(),
        "estimated_minutes_per_symbol": round(len(symbols) * refresh_interval_seconds() / 60, 1),
        "note": ("OTCharts free tier: manual refresh only to protect the 200-request first-month allowance; no live stream." if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "otcharts" else "A11KSA is manual-refresh only and uses a fail-closed demo/read-only adapter." if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa" else "One symbol is fetched per interval. Provider is third-party; ensure your plan supports the requested market and endpoints."),
    }


def refresh_snapshot(symbol: str | None = None) -> dict[str, Any]:
    """Fetch one symbol; scheduled calls rotate through the watchlist."""
    global _next_symbol_index
    symbols = configured_symbols()
    if symbol:
        selected = _normalize_symbol(symbol)
        if selected not in symbols:
            raise ValueError(f"{selected} is not in FOREX_SYMBOLS. Add it in Render Environment first.")
    else:
        with _lock:
            selected = symbols[_next_symbol_index % len(symbols)]
            _next_symbol_index = (_next_symbol_index + 1) % len(symbols)

    try:
        provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
        timeframe_seconds = 60 if provider == "a11ksa" else TIMEFRAME_SECONDS
        candles = get_candles(selected, timeframe_seconds, CANDLE_LIMIT)
        if not candles:
            raise MarketDataError("Provider returned zero candles.")
        record_candle(candles[-1].get("time"))
        if provider == "a11ksa":
            latest = candles[-1]
            now = datetime.now(timezone.utc)
            snapshot = {
                "available": True, "source": data_source_label(),
                "market_type": "Quotex demo OTC (read-only)", "symbol": selected,
                "watchlist": symbols, "timeframe_seconds": 60, "count": len(candles),
                "updated_at": now.isoformat(), "latest_candle": latest,
                "recent_candles": candles[-10:],
                "chart": {"candles": [{k: row[k] for k in ("time", "open", "high", "low", "close")} for row in candles]},
                "read_only": True, "demo_only": True,
                "message": "A11KSA candle data fetched; analysis and notifications are disabled.",
                "telegram_configured": False,
            }
            with _lock:
                _snapshots[selected] = snapshot
            return dict(snapshot)
        try:
            active_strategy = get_active_strategy()
            analysis = filter_analysis(selected, apply_strategy_management(analyze_with_strategy(candles, active_strategy)))
            record_strategy_signal(candles[-1].get("time"), analysis.get("signal"))
        except Exception:
            record_exception("strategy")
            set_component("strategy", "down", "Strategy analysis failed.")
            raise
        pair_status = get_pair_status(selected)
        latest = candles[-1]
        try:
            record = record_signal(selected, TIMEFRAME_SECONDS, latest, analysis)
            score_due_outcomes(selected, TIMEFRAME_SECONDS, latest, horizon_candles=5)
        except Exception:
            record_exception("database")
            set_component("database", "down", "Signal-history database write failed.")
            raise
        now_ts = int(datetime.now(timezone.utc).timestamp())
        candle_age_seconds = max(0, now_ts - int(latest["time"]))
        # This labels the timestamp window only; REST polling does not guarantee tick-by-tick updates.
        candle_status = "RECENT (timestamp within timeframe; live ticks not verified)" if candle_age_seconds < TIMEFRAME_SECONDS else "CLOSED / STALE"
        snapshot = {
            "available": True,
            "candle_status": candle_status,
            "candle_age_seconds": candle_age_seconds,
            "source": data_source_label(),
            "market_type": latest.get("market_type", "provider-specific market"),
            "symbol": selected,
            "watchlist": symbols,
            "timeframe_seconds": TIMEFRAME_SECONDS,
            "count": len(candles),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "latest_candle": latest,
            "recent_candles": candles[-10:],
            "analysis": analysis,
            "pair_status": pair_status,
            "chart": build_chart_data(candles),
            "signal_history_inserted": record["inserted"],
            "message": "Scheduled refresh successful.",
            "refresh_interval_seconds": refresh_interval_seconds(),
            "estimated_minutes_per_symbol": round(len(symbols) * refresh_interval_seconds() / 60, 1),
            "telegram_configured": telegram_configured(),
            "disclaimer": "Data source depends on MARKET_DATA_PROVIDER. Third-party market data and heuristic signals are not a guarantee or financial advice.",
        }
        with _lock:
            _snapshots[selected] = snapshot
        # Telegram receives market-data candle updates only; never send strategy outputs.
        notification = (
            {"sent": False, "reason": "Pair is DISABLED; Telegram alerts suppressed."}
            if pair_status == "DISABLED"
            else notify_new_candle(snapshot)
        )
        record_telegram_result(notification)
        snapshot["telegram_notification"] = notification
        with _lock:
            _snapshots[selected] = snapshot
        return dict(snapshot)
    except (MarketDataError, ValueError, TypeError, RuntimeError) as exc:
        record_exception("provider")
        set_component("provider", "degraded", "Provider candle refresh failed.")
        error_snapshot = {
            "available": False,
            "source": data_source_label(),
            "market_type": "Quotex market" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() in ("quantex", "otcharts", "quotexapi") else "standard forex, not Quotex OTC",
            "symbol": selected,
            "watchlist": symbols,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": str(exc),
            "refresh_interval_seconds": refresh_interval_seconds(),
            "estimated_minutes_per_symbol": round(len(symbols) * refresh_interval_seconds() / 60, 1),
            "telegram_configured": False if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa" else bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
        }
        with _lock:
            _snapshots[selected] = error_snapshot
        return dict(error_snapshot)


async def scheduled_refresh_loop() -> None:
    """Refresh symbols independently; recover from an unexpected iteration failure."""
    while True:
        try:
            with _lock:
                enabled = _bot_enabled
            provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
            if enabled and provider not in ("otcharts", "a11ksa"):
                # Provider-level errors return an error snapshot; this guards unexpected failures.
                await asyncio.to_thread(refresh_snapshot)
                await asyncio.sleep(refresh_interval_seconds())
            else:
                # OTCharts/A11KSA remain manual-refresh only; no background provider polling.
                await asyncio.sleep(5 if not enabled else 60)
        except asyncio.CancelledError:
            logger.info("Scheduled refresh loop cancelled; shutting down cleanly.")
            raise
        except Exception:
            # One unexpected symbol/provider failure must not terminate the scheduler.
            logger.exception("Unexpected scheduled refresh failure; retrying after 5 seconds.")
            await asyncio.sleep(5)
