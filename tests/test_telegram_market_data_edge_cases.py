"""Edge cases for safe market-data-only Telegram notifications."""
from __future__ import annotations

import pytest
import requests

import telegram_market_data as notifier


class Response:
    def __init__(self, payload=None, error=None, json_error=False):
        self.payload = {"ok": True} if payload is None else payload
        self.error = error
        self.json_error = json_error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        if self.json_error:
            raise ValueError("invalid JSON")
        return self.payload


def snapshot(timestamp=1_790_000_000, **overrides):
    result = {
        "symbol": "EURUSD_otc",
        "source": "Read-only test provider",
        "market_type": "Quotex Demo OTC",
        "timeframe_seconds": 60,
        "latest_candle": {
            "time": timestamp, "open": 1.1, "high": 1.2,
            "low": 1.0, "close": 1.15,
        },
    }
    result.update(overrides)
    return result


@pytest.fixture(autouse=True)
def clear_delivery_state():
    notifier._last_notified_candle.clear()
    yield
    notifier._last_notified_candle.clear()


def configure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "unit-test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "unit-test-chat")


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "", "latest_candle": {"time": 100}},
        {"symbol": "EURUSD_otc", "latest_candle": {"time": "not-time"}},
        {"symbol": "EURUSD_otc", "latest_candle": {"time": 0}},
        {"symbol": "EURUSD_otc", "latest_candle": {"time": 10 ** 100}},
    ],
)
def test_invalid_or_unrepresentable_candle_timestamps_are_skipped(payload):
    result = notifier.notify_new_candle(payload)
    assert result == {
        "sent": False,
        "reason": "missing_symbol_or_candle_timestamp",
    }


@pytest.mark.parametrize(
    "missing",
    ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
)
def test_each_missing_credential_prevents_delivery(monkeypatch, missing):
    configure(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    result = notifier.notify_new_candle(snapshot())
    assert result == {"sent": False, "reason": "telegram_not_configured"}


def test_invalid_timeframe_falls_back_to_sixty_seconds(monkeypatch):
    configure(monkeypatch)
    captured = []
    monkeypatch.setattr(
        notifier.requests, "post",
        lambda *a, **k: (captured.append(k["json"]["text"]) or Response()),
    )
    result = notifier.notify_new_candle(snapshot(timeframe_seconds="bad"))
    assert result["sent"] is True
    assert "Timeframe: 60 seconds" in captured[0]


@pytest.mark.parametrize("timeframe", [0, -10])
def test_nonpositive_timeframe_falls_back_to_sixty_seconds(monkeypatch, timeframe):
    configure(monkeypatch)
    captured = []
    monkeypatch.setattr(
        notifier.requests, "post",
        lambda *a, **k: (captured.append(k["json"]["text"]) or Response()),
    )
    result = notifier.notify_new_candle(snapshot(timeframe_seconds=timeframe))
    assert result["sent"] is True
    assert "Timeframe: 60 seconds" in captured[0]


@pytest.mark.parametrize(
    "response",
    [
        Response(error=requests.HTTPError("failed")),
        Response(json_error=True),
        Response(payload=["unexpected"]),
        Response(payload={"ok": False}),
    ],
)
def test_telegram_delivery_errors_are_not_cached(monkeypatch, response):
    configure(monkeypatch)
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: response)
    result = notifier.notify_new_candle(snapshot())
    assert result["sent"] is False
    assert result["reason"] in {
        "telegram_delivery_failed",
        "telegram_rejected_message",
    }
    assert "EURUSD_otc" not in notifier._last_notified_candle


def test_network_exception_is_reported_without_exception_text(monkeypatch):
    configure(monkeypatch)

    def fail(*args, **kwargs):
        raise requests.ConnectionError("private response data")

    monkeypatch.setattr(notifier.requests, "post", fail)
    result = notifier.notify_new_candle(snapshot())
    assert result == {"sent": False, "reason": "telegram_delivery_failed"}
    assert "private response data" not in str(result)


def test_different_new_candle_is_sent_and_updates_deduplication_cache(monkeypatch):
    configure(monkeypatch)
    calls = []
    monkeypatch.setattr(
        notifier.requests, "post",
        lambda *a, **k: (calls.append(k["json"]["text"]) or Response()),
    )
    first = notifier.notify_new_candle(snapshot(1_790_000_000))
    second = notifier.notify_new_candle(snapshot(1_790_000_060))
    assert first["sent"] is True
    assert second["sent"] is True
    assert len(calls) == 2
    assert notifier._last_notified_candle["EURUSD_otc"] == 1_790_000_060
