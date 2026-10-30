"""Read-only adapter for the unofficial A11ksa API-Quotex client.

Credentials are read only from environment variables. No order/trading methods are called.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

SOURCE = "A11ksa API-Quotex WebSocket (unofficial third-party client)"


def _credentials() -> tuple[str, str, bool]:
    email = os.getenv("QUOTEX_EMAIL", "").strip()
    password = os.getenv("QUOTEX_PASSWORD", "")
    is_demo = os.getenv("QUOTEX_DEMO", "true").strip().lower() in {"1", "true", "yes", "on"}
    if not email or not password:
        raise ValueError("Set QUOTEX_EMAIL and QUOTEX_PASSWORD in Render Environment.")
    return email, password, is_demo


async def _with_client(operation: str, asset: str | None = None, timeframe_seconds: int = 60, limit: int = 100):
    from api_quotex import AsyncQuotexClient, get_ssid

    email, password, is_demo = _credentials()
    ok, session = await get_ssid(email=email, password=password, is_demo=is_demo)
    if not ok or not isinstance(session, dict) or not session.get("ssid"):
        raise ValueError("A11ksa login failed or did not return a usable SSID.")
    client = AsyncQuotexClient(ssid=session["ssid"], is_demo=is_demo, enable_logging=False)
    connected = False
    try:
        connected = await client.connect()
        if not connected:
            raise ValueError("A11ksa WebSocket connection failed.")
        if operation == "assets":
            assets = await client.get_assets_and_payouts()
            return [
                {"symbol": symbol, "name": symbol, "payout": payout,
                 "market_type": "Quotex demo" if is_demo else "Quotex live",
                 "venue": "a11ksa", "source": SOURCE}
                for symbol, payout in sorted(assets.items())
            ]
        if operation == "candles":
            candles = await client.get_candles(asset, timeframe_seconds, count=limit)
            result = []
            for candle in candles:
                timestamp = candle.timestamp
                if hasattr(timestamp, "timestamp"):
                    timestamp = int(timestamp.timestamp())
                else:
                    timestamp = int(timestamp)
                result.append({
                    "time": timestamp, "open": float(candle.open),
                    "high": float(candle.high), "low": float(candle.low),
                    "close": float(candle.close), "symbol": asset,
                    "timeframe_seconds": timeframe_seconds, "venue": "a11ksa",
                    "market_type": "Quotex demo" if is_demo else "Quotex live",
                    "source": SOURCE,
                })
            result.sort(key=lambda row: row["time"])
            return result[-limit:]
        raise ValueError("Unsupported A11ksa operation.")
    finally:
        if connected:
            await client.disconnect()


def _run(operation: str, asset: str | None = None, timeframe_seconds: int = 60, limit: int = 100):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_with_client(operation, asset, timeframe_seconds, limit))
    raise RuntimeError("A11ksa synchronous adapter cannot run inside an active event loop.")


def get_assets() -> list[dict[str, Any]]:
    return _run("assets")


def get_candles(asset: str, timeframe_seconds: int, limit: int = 100) -> list[dict[str, Any]]:
    if timeframe_seconds not in (60, 300, 900, 1800, 3600, 14400):
        raise ValueError("A11ksa supports 60, 300, 900, 1800, 3600 and 14400 second candles.")
    return _run("candles", asset=asset, timeframe_seconds=timeframe_seconds, limit=limit)


def connection_status() -> dict[str, Any]:
    try:
        assets = get_assets()
        return {
            "connected": True, "live_data": True, "credentials_configured": True,
            "message": f"A11ksa WebSocket connected; {len(assets)} open assets returned.",
            "source": SOURCE,
            "market_type": "Quotex demo" if os.getenv("QUOTEX_DEMO", "true").lower() == "true" else "Quotex live",
            "affiliation": "Unofficial third-party client; not operated by or affiliated with Quotex.",
            "read_only": True,
        }
    except Exception as exc:
        return {
            "connected": False, "live_data": False,
            "credentials_configured": bool(os.getenv("QUOTEX_EMAIL") and os.getenv("QUOTEX_PASSWORD")),
            "message": f"A11ksa connection check failed: {type(exc).__name__}: {str(exc)[:180]}",
            "source": SOURCE, "read_only": True,
        }
