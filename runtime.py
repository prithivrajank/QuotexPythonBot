"""Quota-aware multi-symbol scheduler and optional Telegram signal alerts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import threading
from typing import Any

import requests

from data_collector import MarketDataError, data_source_label, get_candles
from signal_history import record_signal, score_due_outcomes
from strategies import analyze_candles, build_chart_data

DEFAULT_SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY",
]
DEFAULT_QUANTEX_SYMBOLS = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "EURUSD", "GBPUSD", "USDJPY"]


def _normalize_symbol(value: str) -> str:
    if os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower() in ("quantex", "otcharts", "quotexapi"):
        value = value.strip()
        return value[:-4] + "_otc" if value.lower().endswith("_otc") else value.replace("/", "").replace("-", "").upper()
    return value.strip().upper().replace("-", "/")
TIMEFRAME_SECONDS = int(os.getenv("FOREX_TIMEFRAME_SECONDS", "60"))
CANDLE_LIMIT = 100
DEFAULT_REFRESH_SECONDS = 300
_lock = threading.Lock()
_snapshots: dict[str, dict[str, Any]] = {}
_next_symbol_index = 0
_last_alerted_signal: dict[str, str] = {}
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
        defaults = DEFAULT_QUANTEX_SYMBOLS if os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower() in ("quantex", "otcharts", "quotexapi") else DEFAULT_SYMBOLS
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
        "market_type": "Quotex market" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() in ("quantex", "otcharts", "quotexapi") else "standard forex, not Quotex OTC",
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
        "market_type": "Quotex market" if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() in ("quantex", "otcharts", "quotexapi") else "standard forex, not Quotex OTC",
        "symbols": symbols,
        "scanned": snapshots,
        "refresh_interval_seconds": refresh_interval_seconds(),
        "estimated_minutes_per_symbol": round(len(symbols) * refresh_interval_seconds() / 60, 1),
        "note": ("OTCharts free tier: manual refresh only to protect the 200-request first-month allowance; no live stream." if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "otcharts" else "One symbol is fetched per interval. Provider is third-party; ensure your plan supports the requested market and endpoints."),
    }


def _telegram_alert(snapshot: dict[str, Any]) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    symbol = snapshot["symbol"]
    signal = snapshot["analysis"]["signal"]
    previous = _last_alerted_signal.get(symbol)
    _last_alerted_signal[symbol] = signal
    if previous is not None and signal == previous:
        return

    analysis = snapshot["analysis"]
    candle = snapshot["latest_candle"]
    text = (
        "Market-data signal summary (read-only; not a trade guarantee)\n"
        f"Symbol: {symbol}\n"
        f"Market type: {candle.get('market_type', 'provider-specific')}\n"
        f"Data source: {candle.get('source', data_source_label())}\n"
        f"Candle timeframe: {snapshot['timeframe_seconds']} seconds (1-minute candle)\n"
        f"Trade expiry: {str(analysis.get('expiry_recommendation_minutes')) + ' minute(s)' if analysis.get('expiry_recommendation_minutes') else 'WAIT / no expiry'}\n"
        f"Candle status: {snapshot.get('candle_status', 'provider-update-dependent')}\n"
        f"Signal: {signal}\n"
        f"Strength: {analysis.get('signal_strength', 'N/A')} (heuristic, not probability)\n"
        f"Expiry suggestion: {str(analysis.get('expiry_recommendation_minutes')) + ' minute(s)' if analysis.get('expiry_recommendation_minutes') else 'WAIT / no expiry'}\n"
        f"Expiry reason: {analysis.get('expiry_reason', 'N/A')}\n"
        f"Reason: {analysis.get('reason', 'N/A')}\n"
        f"Close: {candle.get('close')}\n"
        f"RSI(14): {analysis.get('rsi_14')}\n"
        f"MACD histogram: {analysis.get('macd_histogram')}\n"
        f"Support / resistance (20 bars): {analysis.get('support_20')} / {analysis.get('resistance_20')}\n"
        "Heuristic only; not financial advice or a guaranteed prediction."
    )
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        return


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
        candles = get_candles(selected, TIMEFRAME_SECONDS, CANDLE_LIMIT)
        if not candles:
            raise MarketDataError("Provider returned zero candles.")
        analysis = analyze_candles(candles)
        latest = candles[-1]
        record = record_signal(selected, TIMEFRAME_SECONDS, latest, analysis)
        score_due_outcomes(selected, TIMEFRAME_SECONDS, latest, horizon_candles=5)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        candle_age_seconds = max(0, now_ts - int(latest["time"]))
        # This labels the timestamp window only; REST polling does not guarantee tick-by-tick updates.
        candle_status = "LIVE WINDOW (provider-update-dependent)" if candle_age_seconds < TIMEFRAME_SECONDS else "CLOSED / STALE"
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
            "chart": build_chart_data(candles),
            "signal_history_inserted": record["inserted"],
            "message": "Scheduled refresh successful.",
            "refresh_interval_seconds": refresh_interval_seconds(),
            "estimated_minutes_per_symbol": round(len(symbols) * refresh_interval_seconds() / 60, 1),
            "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
            "disclaimer": "Data source depends on MARKET_DATA_PROVIDER. Third-party market data and heuristic signals are not a guarantee or financial advice.",
        }
        with _lock:
            _snapshots[selected] = snapshot
        # Alert on a changed signal even when the provider updates the same still-forming candle.
        # The scheduler remains quota-aware and does not provide true tick-by-tick streaming.
        _telegram_alert(snapshot)
        return dict(snapshot)
    except (MarketDataError, ValueError, TypeError) as exc:
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
            "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
        }
        with _lock:
            _snapshots[selected] = error_snapshot
        return dict(error_snapshot)


async def scheduled_refresh_loop() -> None:
    """Fetch one watchlist symbol each interval only while the bot is ON."""
    while True:
        with _lock:
            enabled = _bot_enabled
        provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
        if enabled and provider != "otcharts":
            await asyncio.to_thread(refresh_snapshot)
            await asyncio.sleep(refresh_interval_seconds())
        else:
            # OTCharts free tier allows only 200 requests in its first month and no live stream.
            # Avoid background polling; users must explicitly refresh one selected pair.
            await asyncio.sleep(5 if not enabled else 60)
