"""Minimal fail-closed, read-only Quotex candle transport.

This deliberately does not import A11ksa's high-level client. It supports only
Engine.IO/Socket.IO handshake, authorization, and candle subscription events.
No balance, order, trade, or account-management API exists in this module.
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
from typing import Any
from urllib.parse import urlsplit

import websockets

DEFAULT_ENDPOINT = "wss://ws2.qxbroker.com/socket.io/?EIO=3&transport=websocket"
ALLOWED_OUTBOUND_EVENTS = frozenset({
    "authorization",
    "instruments/follow",
    "instruments/update",
    "chart_notification/get",
})
FORBIDDEN_EVENT_FRAGMENTS = ("balance", "order", "trade", "buy", "sell", "deal")


class CandleTransportError(RuntimeError):
    pass


def build_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "wss" or not parsed.hostname:
        raise CandleTransportError("Only a valid wss:// endpoint is permitted.")
    if parsed.hostname != "ws2.qxbroker.com":
        raise CandleTransportError("Endpoint host is not the reviewed Quotex host.")


def _event_frame(event: str, payload: Any) -> str:
    if event not in ALLOWED_OUTBOUND_EVENTS:
        raise CandleTransportError(f"Outbound event is not allowlisted: {event}")
    if any(fragment in event.lower() for fragment in FORBIDDEN_EVENT_FRAGMENTS):
        raise CandleTransportError("Forbidden account/trading event.")
    return "42" + json.dumps([event, payload], separators=(",", ":"))


def build_authorization_frame(ssid: str) -> str:
    if not isinstance(ssid, str) or not ssid.strip():
        raise CandleTransportError("Demo session is not configured.")
    payload = {
        "session": ssid.strip(),
        "isDemo": 1,
        "tournamentId": 0,
        "isFastHistory": True,
    }
    return _event_frame("authorization", payload)


def build_candle_frames(asset: str, timeframe_seconds: int = 60) -> tuple[str, str, str]:
    if not isinstance(asset, str) or not asset.strip():
        raise CandleTransportError("Asset must be a non-empty symbol.")
    symbol = asset.strip()
    if timeframe_seconds != 60:
        raise CandleTransportError("Only 60-second candles are enabled.")
    return (
        _event_frame("instruments/follow", symbol),
        _event_frame("instruments/update", {"asset": symbol, "period": 60}),
        _event_frame("chart_notification/get", {"asset": symbol, "version": "1.0.0"}),
    )


def parse_candle_event(frame: str, expected_asset: str) -> list[dict[str, Any]]:
    """Parse only explicit candle event frames; unknown/ambiguous payloads fail closed."""
    if not isinstance(frame, str) or not frame.startswith("42"):
        return []
    try:
        packet = json.loads(frame[2:])
    except (TypeError, ValueError):
        return []
    if not isinstance(packet, list) or len(packet) < 2:
        return []
    event, body = packet[0], packet[1]
    if event not in {"history/list/v2", "chart_notification/get", "loadHistoryPeriod"}:
        return []
    if not isinstance(body, dict) or body.get("asset") != expected_asset:
        return []
    if body.get("period") != 60:
        return []
    rows = body.get("candles", body.get("history"))
    if not isinstance(rows, list):
        return []
    parsed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            timestamp = int(row.get("time", row.get("timestamp")))
            o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        except (TypeError, ValueError, KeyError, OverflowError):
            continue
        if timestamp <= 0 or not all(map(lambda x: x == x and abs(x) != float("inf"), (o, h, low, c))):
            continue
        if h < max(o, c, low) or low > min(o, c, h):
            continue
        parsed.append({"time": timestamp, "open": o, "high": h, "low": low, "close": c})
    parsed.sort(key=lambda row: row["time"])
    return parsed


class ReadOnlyCandleTransport:
    """Single-session candle reader; no trading/account methods are implemented."""

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 12.0):
        _validate_endpoint(endpoint)
        self.endpoint = endpoint
        self.timeout = timeout
        self._ws = None

    async def fetch_candles(self, asset: str, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= int(limit) <= 500:
            raise CandleTransportError("limit must be between 1 and 500.")
        ssid = os.getenv("QUOTEX_SSID", "").strip()
        if not ssid:
            raise CandleTransportError("QUOTEX_SSID is not configured in the private environment.")
        auth_frame = build_authorization_frame(ssid)
        follow, update, chart = build_candle_frames(asset, 60)
        context = build_tls_context()
        received: list[dict[str, Any]] = []
        try:
            async with websockets.connect(
                self.endpoint,
                ssl=context,
                open_timeout=self.timeout,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
                extra_headers={
                    "Origin": "https://qxbroker.com",
                    "Referer": "https://qxbroker.com/",
                    "User-Agent": "Mozilla/5.0",
                },
            ) as ws:
                self._ws = ws
                # Engine.IO open -> Socket.IO connect.
                first = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                if not isinstance(first, str) or not first.startswith("0"):
                    raise CandleTransportError("Unexpected Engine.IO opening frame.")
                await ws.send("40")
                connected = False
                deadline = asyncio.get_running_loop().time() + self.timeout
                while asyncio.get_running_loop().time() < deadline:
                    msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    if msg == "2":
                        await ws.send("3")
                    elif isinstance(msg, str) and msg.startswith("40"):
                        connected = True
                        break
                if not connected:
                    raise CandleTransportError("Socket.IO connect acknowledgement timed out.")
                await ws.send(auth_frame)
                authenticated = False
                deadline = asyncio.get_running_loop().time() + self.timeout
                while asyncio.get_running_loop().time() < deadline:
                    msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    if msg == "2":
                        await ws.send("3")
                    elif isinstance(msg, str) and msg.startswith('42["s_authorization"'):
                        authenticated = True
                        break
                    elif isinstance(msg, str) and msg.startswith("451-["):
                        raise CandleTransportError("Unexpected binary/multipart frame; refusing ambiguous protocol.")
                if not authenticated:
                    raise CandleTransportError("Demo authorization was not confirmed.")
                await ws.send(follow)
                await ws.send(update)
                await ws.send(chart)
                deadline = asyncio.get_running_loop().time() + self.timeout
                while asyncio.get_running_loop().time() < deadline and len(received) < limit:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_running_loop().time()))
                    except asyncio.TimeoutError:
                        break
                    if msg == "2":
                        await ws.send("3")
                    elif isinstance(msg, str):
                        received.extend(parse_candle_event(msg, asset))
                # Deduplicate by timestamp and return the newest rows.
                unique = {row["time"]: row for row in received}
                return sorted(unique.values(), key=lambda row: row["time"])[-limit:]
        finally:
            self._ws = None
