"""Decode only observed, read-only Quotex Socket.IO market-data frames."""
from __future__ import annotations

import json
import math
import re
from typing import Any

_BINARY_HEADER = re.compile(r"^45(\d+)-", re.DOTALL)
_MARKET_EVENTS = {"quotes/stream", "history/list/v2"}
_MAX_ATTACHMENTS = 8


def _json_from_attachment(frame: str | bytes) -> Any:
    if isinstance(frame, str):
        raw = frame.encode("utf-8")
    elif isinstance(frame, bytes):
        raw = frame
    else:
        return None
    raw = raw.lstrip(b"\x04 \t\r\n")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _quote_rows(value: Any, asset: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    ticks: list[dict[str, Any]] = []
    for row in value:
        if isinstance(row, (list, tuple)) and len(row) >= 3 and row[0] == asset:
            timestamp = _number(row[1])
            price = _number(row[2])
            if timestamp is not None and timestamp > 0 and price is not None:
                ticks.append({
                    "asset": asset,
                    "timestamp": timestamp,
                    "price": price,
                    "flag": row[3] if len(row) > 3 else None,
                })
        elif isinstance(row, (list, tuple)):
            ticks.extend(_quote_rows(list(row), asset))
    return sorted(ticks, key=lambda item: item["timestamp"])


def parse_quote_attachment(frame: str | bytes, expected_asset: str) -> list[dict[str, Any]]:
    """Parse observed [asset, timestamp_seconds, price, flag] rows."""
    if not isinstance(expected_asset, str) or not expected_asset.strip():
        return []
    return _quote_rows(_json_from_attachment(frame), expected_asset.strip())


def _parse_candle_body(body: Any, asset: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        records: list[dict[str, Any]] = []
        for child in body:
            records.extend(_parse_candle_body(child, asset))
        return records
    if not isinstance(body, dict):
        return []

    if body.get("asset", body.get("symbol")) != asset:
        return []
    period = body.get("period", body.get("timeframe", body.get("timePeriod")))
    try:
        if int(period) != 60:
            return []
    except (TypeError, ValueError, OverflowError):
        return []

    rows = body.get("candles")
    if rows is None:
        rows = body.get("history")
    if not isinstance(rows, list):
        return []

    parsed: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        timestamp = _number(row[0])
        open_price = _number(row[1])
        if timestamp is None or open_price is None or timestamp <= 0:
            continue

        if len(row) > 6:
            second, third, fourth = (_number(row[index]) for index in (2, 3, 4))
            count, last_update = _number(row[5]), _number(row[6])
            if None in (second, third, fourth, count, last_update):
                continue
            candidates = {(second, third, fourth), (fourth, third, second)}
            valid = {
                (low, high, close)
                for low, high, close in candidates
                if high >= max(open_price, close, low)
                and low <= min(open_price, close, high)
            }
            if len(valid) != 1 or count < 0 or int(count) != count:
                continue
            low_price, high_price, close_price = next(iter(valid))
            if last_update < timestamp:
                continue
            extra = {"tick_count": int(count), "last_update": last_update}
        else:
            low_price, high_price, close_price = (
                _number(row[index]) for index in (2, 3, 4)
            )
            volume = _number(row[5]) if len(row) > 5 and row[5] is not None else 0.0
            if None in (low_price, high_price, close_price, volume) or volume < 0:
                continue
            extra = {"volume": volume}

        if int(timestamp) != timestamp or int(timestamp) % 60:
            continue
        if high_price < max(open_price, close_price, low_price):
            continue
        if low_price > min(open_price, close_price, high_price):
            continue
        parsed[int(timestamp)] = {
            "asset": asset,
            "time": int(timestamp),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            **extra,
        }
    return [parsed[key] for key in sorted(parsed)]


def parse_history_attachment(frame: str | bytes, expected_asset: str) -> list[dict[str, Any]]:
    """Parse only explicit, internally consistent 60-second OHLC history."""
    if not isinstance(expected_asset, str) or not expected_asset.strip():
        return []
    return _parse_candle_body(_json_from_attachment(frame), expected_asset.strip())


class QuotexMarketFrameParser:
    """Pair Socket.IO binary headers with attachments; ignore unrelated events."""

    def __init__(self, expected_asset: str):
        if not isinstance(expected_asset, str) or not expected_asset.strip():
            raise ValueError("expected_asset must be a non-empty symbol")
        self.expected_asset = expected_asset.strip()
        self._event: str | None = None
        self._attachment_count = 0
        self._attachments: list[bytes] = []

    def _finish(self) -> list[dict[str, Any]]:
        event = self._event
        attachments = self._attachments
        self._event = None
        self._attachment_count = 0
        self._attachments = []
        results: list[dict[str, Any]] = []
        for attachment in attachments:
            if event == "quotes/stream":
                results.extend(
                    {"kind": "tick", **tick}
                    for tick in parse_quote_attachment(attachment, self.expected_asset)
                )
            elif event == "history/list/v2":
                results.extend(
                    {"kind": "historical_candle", **candle}
                    for candle in parse_history_attachment(attachment, self.expected_asset)
                )
        return results

    def feed(self, frame: str | bytes) -> list[dict[str, Any]]:
        if isinstance(frame, bytes):
            if self._event is None:
                return []
            self._attachments.append(frame)
            if len(self._attachments) >= self._attachment_count:
                return self._finish()
            return []
        if not isinstance(frame, str):
            return []

        header = _BINARY_HEADER.match(frame)
        if header:
            self._event = None
            self._attachment_count = 0
            self._attachments = []
            count = int(header.group(1))
            if count < 1 or count > _MAX_ATTACHMENTS:
                return []
            try:
                packet = json.loads(frame[header.end():])
            except (TypeError, ValueError):
                return []
            if not isinstance(packet, list) or len(packet) < 2:
                return []
            event, payload = packet[0], packet[1]
            if event not in _MARKET_EVENTS or not isinstance(payload, dict):
                return []
            placeholders: list[Any] = []

            def collect(value: Any) -> None:
                if isinstance(value, dict):
                    if value.get("_placeholder") is True:
                        placeholders.append(value.get("num"))
                    for child in value.values():
                        collect(child)
                elif isinstance(value, list):
                    for child in value:
                        collect(child)

            collect(payload)
            if len(placeholders) != count or sorted(placeholders) != list(range(count)):
                return []
            self._event = event
            self._attachment_count = count
            return []

        if not frame.startswith("42"):
            return []
        try:
            packet = json.loads(frame[2:])
        except (TypeError, ValueError):
            return []
        if not isinstance(packet, list) or len(packet) < 2:
            return []
        event, payload = packet[0], packet[1]
        if event == "quotes/stream":
            return [
                {"kind": "tick", **tick}
                for tick in _quote_rows(payload, self.expected_asset)
            ]
        if event == "history/list/v2":
            return [
                {"kind": "historical_candle", **candle}
                for candle in _parse_candle_body(payload, self.expected_asset)
            ]
        return []


class MinuteCandleAggregator:
    """Incrementally aggregate market ticks into UTC-aligned 60-second OHLC."""

    def __init__(self):
        self._candles: dict[tuple[str, int], dict[str, Any]] = {}

    def add(self, tick: dict[str, Any]) -> dict[str, Any] | None:
        asset = tick.get("asset")
        timestamp = _number(tick.get("timestamp"))
        price = _number(tick.get("price"))
        if not isinstance(asset, str) or not asset or timestamp is None or timestamp <= 0 or price is None:
            return None

        minute = int(timestamp // 60) * 60
        key = (asset, minute)
        candle = self._candles.get(key)
        if candle is None:
            candle = {
                "asset": asset,
                "time": minute,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "tick_count": 0,
                "_first": timestamp,
                "_last": timestamp,
            }
            self._candles[key] = candle

        candle["tick_count"] += 1
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        if timestamp < candle["_first"]:
            candle["open"] = price
            candle["_first"] = timestamp
        if timestamp >= candle["_last"]:
            candle["close"] = price
            candle["_last"] = timestamp
        candle["last_update"] = max(candle.get("last_update", timestamp), timestamp)
        return {
            key: value for key, value in candle.items()
            if not key.startswith("_")
        }
