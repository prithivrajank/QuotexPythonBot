"""Fail-closed A11ksa candle adapter.

The upstream A11ksa API-Quotex WebSocket client currently constructs a TLS
context with hostname checks disabled and CERT_NONE. This adapter intentionally
does not import or connect that client until upstream TLS verification is fixed.

Only candle-history access is in scope. No balance, order, buy/sell, or result
methods are exposed here.
"""
from __future__ import annotations

import os
from typing import Any

SOURCE = "A11ksa API-Quotex (unofficial; disabled pending TLS verification fix)"


class A11ksaSecurityError(RuntimeError):
    """Raised when the upstream client cannot meet the TLS security gate."""


def _security_gate() -> None:
    # Explicit opt-in is not sufficient: upstream TLS verification must first
    # be corrected and independently reviewed. Never bypass this guard using
    # an environment variable.
    raise A11ksaSecurityError(
        "A11ksa adapter is disabled: upstream WebSocket code disables TLS "
        "certificate and hostname verification. Use a provider with verified "
        "TLS until the upstream client is corrected and reviewed."
    )


def connection_status() -> dict[str, Any]:
    return {
        "connected": False,
        "live_data": False,
        "credentials_configured": bool(os.getenv("QUOTEX_SSID", "").strip()),
        "message": (
            "A11ksa integration is blocked by a TLS security issue in the "
            "upstream WebSocket client. No session was used."
        ),
        "source": SOURCE,
        "market_type": "Quotex OTC (unverified; unavailable)",
        "read_only": True,
        "security_blocked": True,
    }


def get_assets() -> list[dict[str, Any]]:
    _security_gate()


def get_candles(
    asset: str,
    timeframe_seconds: int = 60,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError("asset must be a non-empty string")
    if timeframe_seconds != 60:
        raise ValueError("Only 60-second candles are in scope for this test.")
    if not 1 <= int(limit) <= 500:
        raise ValueError("limit must be between 1 and 500")
    _security_gate()
