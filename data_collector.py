"""Quotex feed adapter boundary.

The supplied quotexapi ZIP has incomplete candle methods and a missing SSID
channel module. This module intentionally does not fabricate prices or claim
that the account is connected. Implement and verify the upstream protocol before
returning any live candles here.
"""
from typing import Any


def connection_status() -> dict[str, Any]:
    return {
        "connected": False,
        "live_data": False,
        "message": "Quotex feed is not connected: the supplied library must be repaired and tested first.",
        "source": "ericpedra/quotexapi (unverified unofficial library)",
    }


def get_assets() -> list[dict[str, Any]]:
    """Return real asset metadata only after a verified feed is implemented."""
    raise RuntimeError("Asset discovery is not implemented until the Quotex connection is verified.")


def get_candles(asset: str, timeframe_seconds: int, limit: int = 100) -> list[dict[str, Any]]:
    """Return real OHLC candles only; never substitute mock/sample candles."""
    raise RuntimeError("Candle retrieval is not implemented until the Quotex connection is verified.")
