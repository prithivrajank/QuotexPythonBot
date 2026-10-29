"""Read-only Quotex OTC market-data adapter backed by independent OTCharts.

This is NOT an official Quotex API and is not affiliated with Quotex.
The OTCharts API key is separate from Quotex credentials; never use/share a
Quotex password or SSID for this adapter. This module never places trades.
"""
from __future__ import annotations

import math
import os
from typing import Any

import requests

BASE_URL = "https://otcharts.com/v1"
VENUE = "quotex"
SOURCE = "OTCharts (independent third-party; not affiliated with Quotex)"
TIMEOUT_SECONDS = 10
SUPPORTED_TIMEFRAMES = {
    5, 15, 30, 60, 120, 180, 300, 600, 900, 1800, 3600, 14400, 86400
}


class MarketDataError(RuntimeError):
    """Raised when the third-party market-data API cannot return valid data."""


def _api_key() -> str:
    key = os.getenv("OTCHARTS_API_KEY", "").strip()
    if not key:
        raise MarketDataError(
            "OTCHARTS_API_KEY is missing. Add it as a secret environment "
            "variable in Render; do not commit the key to GitHub."
        )
    return key


def _provider_error_detail(response: requests.Response) -> str:
    """Return a short provider error message without dumping arbitrary response data."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    detail = body.get("error") or body.get("message")
    if isinstance(detail, str):
        return detail[:240]
    return ""


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Perform an authenticated HTTPS GET without logging secrets."""
    try:
        response = requests.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {_api_key()}", "User-Agent": "QuotexPythonBot/0.2"},
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise MarketDataError(
            f"Could not reach the OTCharts market-data service: {type(exc).__name__}."
        ) from None

    detail = _provider_error_detail(response)
    if response.status_code == 401:
        raise MarketDataError(
            "OTCharts returned HTTP 401: key is missing/unknown/revoked or the account email "
            "is unconfirmed. Check the OTCharts key. " + detail
        )
    if response.status_code == 402:
        raise MarketDataError(
            "OTCharts returned HTTP 402: its documentation says this means the account has "
            "a plan the server does not support; it is not an invalid-key error. Contact "
            "OTCharts support with the failed endpoint and status. " + detail
        )
    if response.status_code == 403:
        raise MarketDataError(
            "OTCharts returned HTTP 403: this API key's plan may not open the Quotex venue "
            "or requested instrument. Check GET /v1/venues and your key's selected book. " + detail
        )
    if response.status_code == 404:
        raise MarketDataError(
            "OTCharts did not find that symbol for the Quotex venue. "
            "Use an exact symbol returned by get_assets(). " + detail
        )
    if response.status_code == 429:
        raise MarketDataError("OTCharts request limit reached; check your plan and usage. " + detail)
    if not response.ok:
        raise MarketDataError(
            f"OTCharts returned HTTP {response.status_code} for the market-data request. " + detail
        )
    try:
        payload = response.json()
    except ValueError:
        raise MarketDataError("OTCharts returned a response that was not valid JSON.") from None
    if not isinstance(payload, dict):
        raise MarketDataError("OTCharts returned an unexpected response format.")
    return payload


def connection_status() -> dict[str, Any]:
    """Check which venues the API key can access, using documented /v1/venues."""
    if not os.getenv("OTCHARTS_API_KEY", "").strip():
        return {
            "connected": False,
            "live_data": False,
            "credentials_configured": False,
            "message": "OTCHARTS_API_KEY is not configured in Render environment variables.",
            "source": SOURCE,
        }

    try:
        payload = _get("venues")
        venues = payload.get("venues")
        if not isinstance(venues, list):
            raise MarketDataError("OTCharts /v1/venues response did not contain a venues list.")
        quotex = next((v for v in venues if isinstance(v, dict) and v.get("id") == VENUE), None)
        if quotex is None:
            raise MarketDataError("OTCharts did not list a Quotex venue for this API key.")
        if quotex.get("open") is not True:
            raise MarketDataError(
                "OTCharts API key is reachable, but the Quotex venue is not enabled for this key. "
                "Open OTCharts Account → API keys, select Quotex, and save the selected books."
            )
    except MarketDataError as exc:
        return {
            "connected": False,
            "live_data": False,
            "credentials_configured": True,
            "message": str(exc),
            "source": SOURCE,
        }

    return {
        "connected": True,
        "live_data": False,
        "credentials_configured": True,
        "message": (
            "OTCharts API key is accepted and the Quotex venue is enabled. "
            "This confirms access only; real candle data is verified separately by /api/candles."
        ),
        "source": SOURCE,
        "venue": VENUE,
        "affiliation": "Independent third-party provider; not affiliated with Quotex.",
    }


def get_assets() -> list[dict[str, Any]]:
    """Return the actual symbol catalogue published by OTCharts for Quotex."""
    payload = _get("symbols", {"venue": VENUE})
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise MarketDataError("OTCharts symbols response did not contain a symbols list.")

    assets: list[dict[str, Any]] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        assets.append({
            "symbol": symbol,
            "name": str(item.get("name") or symbol),
            "open": item.get("open"),
            "is_otc": item.get("isOtc", symbol.lower().endswith("_otc")),
            "payout": item.get("payout"),
            "venue": VENUE,
            "source": SOURCE,
        })
    return assets


def get_candles(
    asset: str, timeframe_seconds: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Fetch validated real OHLC candles, oldest first; never synthesize bars."""
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset must not be empty")
    if any(ch.isspace() for ch in asset):
        raise ValueError("asset must be an exact OTCharts symbol without whitespace")
    if timeframe_seconds not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"timeframe_seconds must be one of {sorted(SUPPORTED_TIMEFRAMES)}"
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5000:
        raise ValueError("limit must be an integer between 1 and 5000")

    payload = _get("candles", {
        "venue": VENUE,
        "symbol": asset.strip(),
        "tf": timeframe_seconds,
        "limit": limit,
    })
    rows = payload.get("candles")
    if not isinstance(rows, list):
        raise MarketDataError("OTCharts candle response did not contain a candles list.")

    candles: list[dict[str, Any]] = []
    seen_times: set[int] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MarketDataError(f"OTCharts candle #{index + 1} is not an object.")
        try:
            timestamp = int(row["time"])
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            raise MarketDataError(f"OTCharts candle #{index + 1} has missing/invalid OHLC fields.") from None

        if timestamp < 0 or any(not math.isfinite(v) for v in values.values()):
            raise MarketDataError(f"OTCharts candle #{index + 1} contains invalid values.")
        if timestamp in seen_times:
            raise MarketDataError(f"OTCharts returned duplicate candle timestamp {timestamp}.")
        seen_times.add(timestamp)

        o, h, low, c = values["open"], values["high"], values["low"], values["close"]
        if h < max(o, c, low) or low > min(o, c, h):
            raise MarketDataError(f"OTCharts candle #{index + 1} has inconsistent OHLC values.")

        candle: dict[str, Any] = {
            "time": timestamp,
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "symbol": str(payload.get("symbol") or asset.strip()),
            "timeframe_seconds": timeframe_seconds,
            "venue": VENUE,
            "source": SOURCE,
        }
        if row.get("volume") is not None:
            try:
                volume = float(row["volume"])
            except (TypeError, ValueError):
                raise MarketDataError(f"OTCharts candle #{index + 1} has invalid volume.") from None
            if not math.isfinite(volume) or volume < 0:
                raise MarketDataError(f"OTCharts candle #{index + 1} has invalid volume.")
            candle["volume"] = volume
        candles.append(candle)

    candles.sort(key=lambda candle: candle["time"])
    if len(candles) > limit:
        raise MarketDataError("OTCharts returned more candles than requested.")
    return candles
