"""Telegram notifications for newly observed market-data candles only."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

import requests

_lock = threading.Lock()
_last_notified_candle: dict[str, int] = {}


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def notify_new_candle(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Send one plain-text update per newly observed candle timestamp and symbol."""
    candle = snapshot.get("latest_candle") or {}
    symbol = str(snapshot.get("symbol") or "").strip()
    try:
        candle_time = int(candle.get("time") or 0)
    except (TypeError, ValueError):
        candle_time = 0
    if not symbol or candle_time <= 0:
        return {"sent": False, "reason": "missing_symbol_or_candle_timestamp"}
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"sent": False, "reason": "telegram_not_configured"}

    # Hold the lock through delivery so concurrent refreshes cannot send duplicates.
    with _lock:
        if _last_notified_candle.get(symbol) == candle_time:
            return {"sent": False, "reason": "duplicate_candle"}
        market_type = str(candle.get("market_type") or snapshot.get("market_type") or "provider-specific")
        source = str(snapshot.get("source") or candle.get("source") or "configured provider")
        timeframe = int(snapshot.get("timeframe_seconds") or 60)
        candle_time_text = datetime.fromtimestamp(candle_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = (
            "New market-data candle (read-only)\n"
            f"Symbol: {symbol}\n"
            f"Market: {market_type}\n"
            f"Provider: {source}\n"
            f"Timeframe: {timeframe} seconds\n"
            f"Candle time: {candle_time_text}\n"
            f"Open: {candle.get('open', '—')}\n"
            f"High: {candle.get('high', '—')}\n"
            f"Low: {candle.get('low', '—')}\n"
            f"Close: {candle.get('close', '—')}\n"
            "Data update only. No trading signal or trade has been generated."
        )
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                error_code = payload.get("error_code") if isinstance(payload, dict) else None
                return {"sent": False, "reason": "telegram_rejected_message", "error_code": error_code}
        except (requests.RequestException, ValueError):
            return {"sent": False, "reason": "telegram_delivery_failed"}
        _last_notified_candle[symbol] = candle_time
        return {"sent": True, "reason": "new_candle"}
