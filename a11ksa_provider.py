"""Fail-closed A11ksa candle adapter.

The custom candle transport uses verified TLS, but live demo authorization
and real 60-second candle delivery have not yet been independently verified.
This adapter therefore remains disabled and does not open a session.

Only candle-history access is in scope. No balance, order, buy/sell, or result
methods are exposed here.
"""
from __future__ import annotations

import os
from typing import Any

SOURCE = "A11ksa API-Quotex (unofficial; disabled pending live demo-protocol verification)"


class A11ksaSecurityError(RuntimeError):
    """Raised while live demo authorization and candle delivery remain unverified."""


def _security_gate() -> None:
    # Verified TLS in the custom transport is necessary but not sufficient.
    # Keep this gate closed until the real server confirms demo authorization
    # and delivers independently validated 60-second candles. Never bypass
    # this guard using an environment variable.
    raise A11ksaSecurityError(
        "A11ksa adapter is disabled: live demo authorization and real "
        "60-second candle delivery have not been independently verified. "
        "No session was used."
    )


def connection_status() -> dict[str, Any]:
    return {
        "connected": False,
        "live_data": False,
        "credentials_configured": bool(os.getenv("QUOTEX_DEMO_SSID", "").strip()),
        "message": (
            "A11ksa integration remains disabled pending independent "
            "verification of live demo authorization and real 60-second "
            "candle delivery. No session was used."
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
