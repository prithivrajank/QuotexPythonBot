"""Unauthenticated Socket.IO/Engine.IO upgrade check for Quotex.

Opens a WebSocket connection and verifies only the initial Engine.IO open
packet. It sends no SSID, cookies, login, account, or trading messages.
"""
from __future__ import annotations

import asyncio
import json
import ssl

import websockets

ENDPOINT = "wss://ws2.quotex.com/socket.io/?EIO=3&transport=websocket"


async def main() -> int:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    try:
        async with websockets.connect(
            ENDPOINT,
            ssl=context,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
            extra_headers={
                "Origin": "https://quotex.com",
                "Referer": "https://quotex.com/",
                "User-Agent": "Mozilla/5.0",
            },
        ) as ws:
            frame = await asyncio.wait_for(ws.recv(), timeout=10)
            if not isinstance(frame, str) or not frame.startswith("0"):
                print("WEBSOCKET_UPGRADE_OK=1")
                print("ENGINE_IO_OPEN_PACKET=0")
                print("UNEXPECTED_INITIAL_FRAME=1")
                return 2
            try:
                payload = json.loads(frame[1:])
            except (TypeError, ValueError):
                print("WEBSOCKET_UPGRADE_OK=1")
                print("ENGINE_IO_OPEN_PACKET=0")
                print("MALFORMED_INITIAL_FRAME=1")
                return 2
            if not isinstance(payload, dict) or not payload.get("sid"):
                print("WEBSOCKET_UPGRADE_OK=1")
                print("ENGINE_IO_OPEN_PACKET=0")
                print("INVALID_ENGINE_IO_OPEN_PACKET=1")
                return 2
            # Never print the session ID or the full server response.
            print("WEBSOCKET_UPGRADE_OK=1")
            print("ENGINE_IO_OPEN_PACKET=1")
            print("SERVER_SESSION_ID_RECEIVED=1")
            print("AUTHENTICATION_SENT=0")
            print("ACCOUNT_OR_TRADING_EVENTS_SENT=0")
            return 0
    except Exception as exc:
        print(f"WEBSOCKET_HANDSHAKE_FAILURE={type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
