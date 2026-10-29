"""Quota-aware scheduled market refresh and optional Telegram signal alerts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import threading
from typing import Any

import requests

from data_collector import MarketDataError, get_candles
from signal_history import record_signal, score_due_outcomes
from strategies import analyze_candles, build_chart_data

SYMBOL = os.getenv("FOREX_SYMBOL", "EUR/USD").strip().upper()
TIMEFRAME_SECONDS = int(os.getenv("FOREX_TIMEFRAME_SECONDS", "60"))
CANDLE_LIMIT = 100
DEFAULT_REFRESH_SECONDS = 300
_lock = threading.Lock()
_snapshot: dict[str, Any] = {
    "available": False,
    "source": "Twelve Data (independent provider; not affiliated with Quotex)",
    "market_type": "standard forex, not Quotex OTC",
    "message": "Waiting for the first scheduled refresh.",
}
_last_alerted_signal: str | None = None


def refresh_interval_seconds() -> int:
    """Never refresh faster than five minutes to protect the free daily quota."""
    try:
        requested = int(os.getenv("REFRESH_INTERVAL_SECONDS", str(DEFAULT_REFRESH_SECONDS)))
    except ValueError:
        requested = DEFAULT_REFRESH_SECONDS
    return max(DEFAULT_REFRESH_SECONDS, min(requested, 3600))


def get_snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_snapshot)


def _telegram_alert(snapshot: dict[str, Any]) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    global _last_alerted_signal
    signal = snapshot["analysis"]["signal"]
    previous = _last_alerted_signal
    _last_alerted_signal = signal
    # Send the first summary, then only send subsequent signal changes to avoid spam.
    if previous is not None and signal == previous:
        return

    analysis = snapshot["analysis"]
    candle = snapshot["latest_candle"]
    text = (
        "Forex signal summary (standard forex, NOT Quotex OTC)\n"
        f"Symbol: {snapshot['symbol']}\n"
        f"Timeframe: {snapshot['timeframe_seconds']} seconds\n"
        f"Signal: {signal}\n"
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
        # Never fail market data refresh because Telegram is unavailable.
        return


def refresh_snapshot() -> dict[str, Any]:
    """Make exactly one candle API request, calculate indicators, store history."""
    global _snapshot
    try:
        candles = get_candles(SYMBOL, TIMEFRAME_SECONDS, CANDLE_LIMIT)
        if not candles:
            raise MarketDataError("Provider returned zero candles.")
        analysis = analyze_candles(candles)
        latest = candles[-1]
        record = record_signal(SYMBOL, TIMEFRAME_SECONDS, latest, analysis)
        score_due_outcomes(SYMBOL, TIMEFRAME_SECONDS, latest, horizon_candles=5)
        snapshot = {
            "available": True,
            "source": "Twelve Data (independent provider; not affiliated with Quotex)",
            "market_type": "standard forex, not Quotex OTC",
            "symbol": SYMBOL,
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
            "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
            "disclaimer": "Standard forex, not Quotex OTC. Heuristic only; not financial advice or a guarantee.",
        }
        with _lock:
            _snapshot = snapshot
        if record["inserted"]:
            _telegram_alert(snapshot)
        return dict(snapshot)
    except (MarketDataError, ValueError, TypeError) as exc:
        error_snapshot = {
            "available": False,
            "source": "Twelve Data (independent provider; not affiliated with Quotex)",
            "market_type": "standard forex, not Quotex OTC",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": str(exc),
            "refresh_interval_seconds": refresh_interval_seconds(),
            "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()),
        }
        with _lock:
            _snapshot = error_snapshot
        return dict(error_snapshot)


async def scheduled_refresh_loop() -> None:
    """Refresh once on startup, then every >=300 seconds while service is awake."""
    while True:
        await asyncio.to_thread(refresh_snapshot)
        await asyncio.sleep(refresh_interval_seconds())
