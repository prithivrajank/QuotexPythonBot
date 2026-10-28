"""Quotex feed adapter boundary.

The supplied ZIP is not a working client yet: stable_api.py has syntax errors,
its import expects a QuotexAPI symbol that api.py does not define, the SSID
channel module is missing, and candle methods are placeholders. Do not fabricate
prices or claim a live connection until a protocol implementation is verified.
"""
from __future__ import annotations

import os
from typing import Any


def connection_status() -> dict[str, Any]:
    """Report deployment readiness without exposing the SSID or other secrets."""
    has_ssid = bool(os.getenv("QUOTEX_SSID", "").strip())
    if not has_ssid:
        message = "QUOTEX_SSID is not configured in Render environment variables."
    else:
        message = (
            "QUOTEX_SSID is configured, but the supplied Quotex client is not "
            "implemented/verified yet; no live feed is connected."
        )
    return {
        "connected": False,
        "live_data": False,
        "credentials_configured": has_ssid,
        "message": message,
        "source": "unofficial Quotex client; live protocol not yet verified",
    }


def get_assets() -> list[dict[str, Any]]:
    """Return real asset metadata only after verified asset discovery is implemented."""
    raise RuntimeError(
        "Live asset discovery is not implemented: the upstream WebSocket client "
        "must be repaired and tested first."
    )


def get_candles(
    asset: str, timeframe_seconds: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Return real OHLC candles only; never substitute mock/sample candles."""
    if not asset.strip():
        raise ValueError("asset must not be empty")
    if timeframe_seconds <= 0:
        raise ValueError("timeframe_seconds must be positive")
    if limit < 1 or limit > 5000:
        raise ValueError("limit must be between 1 and 5000")
    raise RuntimeError(
        "Live candle retrieval is not implemented: the upstream WebSocket client "
        "must be repaired and tested first."
    )
