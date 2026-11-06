"""Minimal fail-closed, read-only Quotex candle transport.

This deliberately does not import A11ksa's high-level client. It supports only
Engine.IO/Socket.IO handshake, authorization, and candle subscription events.
No balance, order, trade, or account-management API exists in this module.
"""
from __future__ import annotations

import asyncio
import json
import inspect
import math
import os
import ssl
from typing import Any
from urllib.parse import urlsplit

import websockets

DEFAULT_ENDPOINT = "wss://ws2.quotex.com/socket.io/?EIO=3&transport=websocket"
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
    if parsed.hostname != "ws2.quotex.com":
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


def _decode_binary_history(frame: str | bytes) -> dict[str, Any] | None:
    """Decode the observed binary attachment: EOT byte followed by UTF-8 JSON."""
    if isinstance(frame, bytes):
        raw = frame
    elif isinstance(frame, str):
        raw = frame.encode("utf-8")
    else:
        return None
    raw = raw.lstrip(b"\x04 \t\r\n")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def parse_quote_event(frame: str | bytes, expected_asset: str) -> list[dict[str, Any]]:
    """Parse observed quotes/stream binary attachments.

    Observed row: [asset, timestamp_seconds, price, flag].
    The flag is preserved without assigning undocumented semantics.
    """
    if isinstance(frame, bytes):
        raw = frame.lstrip(b"\x04 \t\r\n")
    elif isinstance(frame, str):
        raw = frame.encode("utf-8").lstrip(b"\x04 \t\r\n")
    else:
        return []
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    ticks: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        asset, timestamp, price, flag = row[:4]
        if asset != expected_asset:
            continue
        try:
            timestamp = float(timestamp)
            price = float(price)
            if not math.isfinite(timestamp) or not math.isfinite(price) or timestamp <= 0:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        ticks.append({
            "asset": asset,
            "timestamp": timestamp,
            "price": price,
            "flag": flag,
        })
    return sorted(ticks, key=lambda tick: tick["timestamp"])


def aggregate_ticks_to_candles(
    ticks: list[dict[str, Any]], expected_asset: str
) -> list[dict[str, Any]]:
    """Build UTC-aligned 60-second OHLC candles from validated quote ticks."""
    buckets: dict[int, list[dict[str, Any]]] = {}
    for tick in ticks:
        if tick.get("asset") != expected_asset:
            continue
        try:
            timestamp = float(tick["timestamp"])
            price = float(tick["price"])
            if not math.isfinite(timestamp) or not math.isfinite(price) or timestamp <= 0:
                continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        minute = int(timestamp // 60) * 60
        buckets.setdefault(minute, []).append({"timestamp": timestamp, "price": price})
    candles = []
    for minute, rows in sorted(buckets.items()):
        rows.sort(key=lambda row: row["timestamp"])
        prices = [row["price"] for row in rows]
        candles.append({
            "time": minute,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "tick_count": len(prices),
            "last_update": rows[-1]["timestamp"],
        })
    return candles


def parse_candle_event(frame: str | bytes, expected_asset: str) -> list[dict[str, Any]]:
    """Parse verified 60-second candle arrays; ignore tick history and placeholders.

    Observed candle row:
    [timestamp, open, close, high, low, tick_count, last_update_timestamp]
    """
    body: Any = None
    if isinstance(frame, str) and frame.startswith("42"):
        try:
            packet = json.loads(frame[2:])
        except (TypeError, ValueError):
            return []
        if not isinstance(packet, list) or len(packet) < 2:
            return []
        event, body = packet[0], packet[1]
        if event not in {"history/list/v2", "chart_notification/get", "loadHistoryPeriod"}:
            return []
    else:
        body = _decode_binary_history(frame)

    if not isinstance(body, dict):
        return []
    if body.get("asset") != expected_asset or body.get("period") != 60:
        return []
    rows = body.get("candles")
    if not isinstance(rows, list):
        return []

    parsed: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue
            timestamp = int(float(row[0]))
            open_price, close_price, high_price, low_price = map(float, row[1:5])
            tick_count = int(row[5])
            last_update = float(row[6])
            values = (open_price, close_price, high_price, low_price, last_update)
            if timestamp <= 0 or tick_count < 0 or not all(math.isfinite(v) for v in values):
                continue
            if timestamp % 60 != 0:
                continue
            if high_price < max(open_price, close_price, low_price):
                continue
            if low_price > min(open_price, close_price, high_price):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        parsed[timestamp] = {
            "time": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "tick_count": tick_count,
            "last_update": last_update,
        }
    return [parsed[t] for t in sorted(parsed)]


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
            headers = {
                "Origin": "https://quotex.com",
                "Referer": "https://quotex.com/",
                "User-Agent": "Mozilla/5.0",
            }
            # websockets 14+ renamed extra_headers to additional_headers.
            connect_parameters = inspect.signature(websockets.connect).parameters
            header_argument = "additional_headers" if "additional_headers" in connect_parameters else "extra_headers"
            connect_options = {
                "ssl": context,
                "open_timeout": self.timeout,
                "close_timeout": 5,
                "ping_interval": 20,
                "ping_timeout": 10,
                header_argument: headers,
            }
            async with websockets.connect(self.endpoint, **connect_options) as ws:
                self._ws = ws
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
                        raise CandleTransportError("Unexpected multipart frame during authorization.")
                if not authenticated:
                    raise CandleTransportError("Demo authorization was not confirmed.")
                await ws.send(follow)
                await ws.send(update)
                await ws.send(chart)
                deadline = asyncio.get_running_loop().time() + self.timeout
                pending_binary = False
                pending_event = ""
                while asyncio.get_running_loop().time() < deadline and len(received) < limit:
                    try:
                        msg = await asyncio.wait_for(
                            ws.recv(),
                            timeout=max(0.1, deadline - asyncio.get_running_loop().time()),
                        )
                    except asyncio.TimeoutError:
                        break
                    if msg == "2":
                        await ws.send("3")
                    elif isinstance(msg, str) and msg.startswith("451-"):
                        # Socket.IO binary event header; the following frame is its attachment.
                        try:
                            packet = json.loads(msg[4:])
                            pending_event = packet[0] if isinstance(packet, list) and packet else ""
                            pending_binary = (
                                isinstance(packet, list)
                                and len(packet) > 1
                                and packet[0] in {"history/list/v2", "quotes/stream"}
                                and isinstance(packet[1], dict)
                                # The binary-event header contains a placeholder only.
                                # Validate asset and period after decoding the attachment.
                            )
                        except (TypeError, ValueError):
                            pending_binary = False
                    elif pending_binary and isinstance(msg, bytes):
                        # The attachment type is determined by the preceding Socket.IO event.
                        if pending_event == "quotes/stream":
                            ticks = parse_quote_event(msg, asset)
                            received.extend(aggregate_ticks_to_candles(ticks, asset))
                        else:
                            received.extend(parse_candle_event(msg, asset))
                        pending_binary = False
                    elif isinstance(msg, str) and msg.startswith("42"):
                        received.extend(parse_candle_event(msg, asset))
                unique = {row["time"]: row for row in received}
                return sorted(unique.values(), key=lambda row: row["time"])[-limit:]
        finally:
            self._ws = None
