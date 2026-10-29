"""Read-only standard forex OHLC adapter using Twelve Data's free REST API.

Important: Twelve Data provides standard forex market data, NOT Quotex OTC/synthetic
quotes. It is an independent market-data provider and is not affiliated with Quotex.
This module never places trades. Store TWELVE_DATA_API_KEY in Render secrets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any

import requests

BASE_URL = "https://api.twelvedata.com"
SOURCE = "Twelve Data standard forex (independent provider; not Quotex OTC)"
TIMEOUT_SECONDS = 12
TIMEFRAME_MAP = {
    60: "1min",
    300: "5min",
    900: "15min",
    1800: "30min",
    2700: "45min",
    3600: "1h",
    7200: "2h",
    14400: "4h",
    28800: "8h",
    86400: "1day",
    604800: "1week",
    2592000: "1month",
}
# Display helpers only; the actual catalogue is returned by Twelve Data.
COMMON_FOREX_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
                      "USD/CHF", "NZD/USD", "EUR/GBP", "EUR/JPY", "GBP/JPY"]


class MarketDataError(RuntimeError):
    """Raised when Twelve Data cannot return valid market data."""


def _api_key() -> str:
    key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not key:
        raise MarketDataError(
            "TWELVE_DATA_API_KEY is missing. Add your API key in Render → Environment."
        )
    return key


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    request_params = dict(params or {})
    try:
        response = requests.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            headers={"Authorization": f"apikey {_api_key()}",
                     "User-Agent": "QuotexPythonBot-readonly/0.3"},
            params=request_params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise MarketDataError(
            f"Could not reach Twelve Data: {type(exc).__name__}."
        ) from None

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code == 401:
        raise MarketDataError("Twelve Data rejected the API key (HTTP 401). Check TWELVE_DATA_API_KEY.")
    if response.status_code == 429:
        raise MarketDataError(
            "Twelve Data rate/credit limit reached (HTTP 429). Wait for the quota reset."
        )
    if not response.ok:
        detail = payload.get("message", "") if isinstance(payload, dict) else ""
        raise MarketDataError(f"Twelve Data returned HTTP {response.status_code}. {str(detail)[:200]}")
    if not isinstance(payload, dict):
        raise MarketDataError("Twelve Data returned an unexpected JSON response.")
    if payload.get("status") == "error" or "code" in payload and "message" in payload:
        message = payload.get("message", "provider request failed")
        raise MarketDataError(f"Twelve Data: {str(message)[:240]}")
    return payload


def connection_status() -> dict[str, Any]:
    """Validate the key against Twelve Data's API usage endpoint."""
    if not os.getenv("TWELVE_DATA_API_KEY", "").strip():
        return {
            "connected": False,
            "live_data": False,
            "credentials_configured": False,
            "message": "TWELVE_DATA_API_KEY is not configured in Render environment variables.",
            "source": SOURCE,
            "affiliation": "Not affiliated with Quotex; standard forex only.",
        }
    try:
        usage = _get("api_usage")
    except MarketDataError as exc:
        return {
            "connected": False,
            "live_data": False,
            "credentials_configured": True,
            "message": str(exc),
            "source": SOURCE,
            "affiliation": "Not affiliated with Quotex; standard forex only.",
        }
    return {
        "connected": True,
        "live_data": False,
        "credentials_configured": True,
        "message": "Twelve Data API key accepted. Request real forex candles from /api/candles to verify data access.",
        "source": SOURCE,
        "market_type": "standard forex, not Quotex OTC",
        "usage": usage.get("current_usage"),
        "limit": usage.get("plan_limit"),
        "affiliation": "Independent market-data provider; not affiliated with Quotex.",
    }


def get_assets() -> list[dict[str, Any]]:
    """Fetch the live forex-pair catalogue from Twelve Data."""
    payload = _get("forex_pairs")
    pairs = payload.get("data")
    if not isinstance(pairs, list):
        raise MarketDataError("Twelve Data forex_pairs response did not contain a data list.")
    assets: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        symbol = pair.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        assets.append({
            "symbol": symbol,
            "name": symbol,
            "market_type": "standard forex",
            "venue": "twelve_data",
            "source": SOURCE,
        })
    return assets


def get_candles(
    asset: str, timeframe_seconds: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Fetch real standard-forex OHLC bars, oldest first; never fabricate candles."""
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset must not be empty")
    symbol = asset.strip().upper().replace("-", "/")
    if any(ch.isspace() for ch in symbol):
        raise ValueError("asset must be a symbol such as EUR/USD without spaces")
    if timeframe_seconds not in TIMEFRAME_MAP:
        raise ValueError(f"timeframe_seconds must be one of {sorted(TIMEFRAME_MAP)}")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5000:
        raise ValueError("limit must be an integer between 1 and 5000")

    payload = _get("time_series", {
        "symbol": symbol,
        "interval": TIMEFRAME_MAP[timeframe_seconds],
        "outputsize": limit,
        "timezone": "UTC",
        "format": "JSON",
    })
    rows = payload.get("values")
    if not isinstance(rows, list):
        raise MarketDataError("Twelve Data time_series response did not contain a values list.")

    candles: list[dict[str, Any]] = []
    seen_times: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MarketDataError(f"Twelve Data candle #{index + 1} is not an object.")
        try:
            raw_time = str(row["datetime"])
            try:
                parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except ValueError:
                parsed = datetime.strptime(raw_time, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamp = int(parsed.astimezone(timezone.utc).timestamp())
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise MarketDataError(f"Twelve Data candle #{index + 1} has missing/invalid OHLC fields.") from None

        if timestamp < 0 or any(not math.isfinite(v) for v in values.values()):
            raise MarketDataError(f"Twelve Data candle #{index + 1} contains invalid values.")
        if timestamp in seen_times:
            raise MarketDataError(f"Twelve Data returned duplicate candle timestamp {timestamp}.")
        seen_times.add(timestamp)

        o, h, low, c = values["open"], values["high"], values["low"], values["close"]
        if h < max(o, c, low) or low > min(o, c, h):
            raise MarketDataError(f"Twelve Data candle #{index + 1} has inconsistent OHLC values.")

        candle: dict[str, Any] = {
            "time": timestamp,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "symbol": symbol,
            "timeframe_seconds": timeframe_seconds,
            "venue": "twelve_data",
            "market_type": "standard forex, not Quotex OTC",
            "source": SOURCE,
        }
        if row.get("volume") not in (None, "", "null"):
            try:
                volume = float(row["volume"])
            except (TypeError, ValueError):
                raise MarketDataError(f"Twelve Data candle #{index + 1} has invalid volume.") from None
            if not math.isfinite(volume) or volume < 0:
                raise MarketDataError(f"Twelve Data candle #{index + 1} has invalid volume.")
            candle["volume"] = volume
        candles.append(candle)

    candles.sort(key=lambda candle: candle["time"])
    if len(candles) > limit:
        raise MarketDataError("Twelve Data returned more candles than requested.")
    return candles
