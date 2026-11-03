import telegram_market_data as notifier


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {"ok": True}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def sample_snapshot(timestamp=1790000000):
    return {
        "symbol": "EURUSD_otc",
        "source": "Demo provider",
        "market_type": "Quotex OTC",
        "timeframe_seconds": 60,
        "analysis": {"signal": "CALL", "reason": "must not be sent"},
        "latest_candle": {
            "time": timestamp,
            "open": 1.1,
            "high": 1.3,
            "low": 1.0,
            "close": 1.2,
            "market_type": "Quotex OTC",
        },
    }


def test_sends_new_candle_without_signal_content(monkeypatch):
    notifier._last_notified_candle.clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **kw: (calls.append((a, kw)) or FakeResponse()))

    result = notifier.notify_new_candle(sample_snapshot())

    assert result == {"sent": True, "reason": "new_candle"}
    message = calls[0][1]["json"]["text"]
    assert "EURUSD_otc" in message
    assert "Quotex OTC" in message
    assert "Open: 1.1" in message
    assert "Close: 1.2" in message
    assert "CALL" not in message
    assert "must not be sent" not in message


def test_skips_duplicate_candle(monkeypatch):
    notifier._last_notified_candle.clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **kw: (calls.append(1) or FakeResponse()))

    first = notifier.notify_new_candle(sample_snapshot())
    second = notifier.notify_new_candle(sample_snapshot())

    assert first["sent"] is True
    assert second["reason"] == "duplicate_candle"
    assert len(calls) == 1


def test_missing_telegram_credentials_do_not_send(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    notifier._last_notified_candle.clear()

    result = notifier.notify_new_candle(sample_snapshot())

    assert result == {"sent": False, "reason": "telegram_not_configured"}



def test_telegram_api_rejection_is_not_marked_sent(monkeypatch):
    notifier._last_notified_candle.clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(
        notifier.requests,
        "post",
        lambda *a, **kw: FakeResponse({"ok": False, "error_code": 400, "description": "chat not found"}),
    )

    result = notifier.notify_new_candle(sample_snapshot())

    assert result == {
        "sent": False,
        "reason": "telegram_rejected_message",
        "error_code": 400,
    }
    assert "EURUSD_otc" not in notifier._last_notified_candle
