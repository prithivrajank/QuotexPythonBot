"""Safety tests for the unofficial Quotex adapter's Demo-only boundary."""
from __future__ import annotations

import pytest

import quotexapi_provider as provider


def test_account_mode_defaults_to_demo(monkeypatch):
    monkeypatch.delenv("QUOTEX_ACCOUNT", raising=False)
    monkeypatch.delenv("QUOTEX_IS_DEMO", raising=False)

    assert provider._account_mode() == (True, "Demo")


@pytest.mark.parametrize(
    ("account", "legacy_demo"),
    [("real", "true"), ("demo", "false"), ("live", "true")],
)
def test_account_mode_rejects_real_or_conflicting_settings(
    monkeypatch, account, legacy_demo
):
    monkeypatch.setenv("QUOTEX_ACCOUNT", account)
    monkeypatch.setenv("QUOTEX_IS_DEMO", legacy_demo)

    with pytest.raises(ValueError, match="Demo-only"):
        provider._account_mode()


def test_real_account_configuration_is_reported_as_blocked(monkeypatch):
    monkeypatch.setenv("QUOTEX_ACCOUNT", "real")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "false")

    status = provider.connection_status()

    assert status["connected"] is False
    assert status["live_data"] is False
    assert status["account_mode"] == "blocked"
    assert status["security_blocked"] is True
    assert "Demo-only" in status["message"]


def test_real_account_configuration_cannot_start_or_read_provider_data(monkeypatch):
    monkeypatch.setenv("QUOTEX_ACCOUNT", "real")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "false")
    monkeypatch.delenv("QUOTEX_SSID", raising=False)

    with pytest.raises(ValueError, match="Demo-only"):
        provider.get_candles("EURUSD_otc", 60, 100)
    with pytest.raises(ValueError, match="Demo-only"):
        provider.get_assets()
    assert provider.get_ticks() == []


@pytest.mark.parametrize("limit", [0, -1, 501, True, 1.5])
def test_provider_rejects_invalid_history_limits_before_connecting(
    monkeypatch, limit
):
    monkeypatch.setenv("QUOTEX_ACCOUNT", "demo")
    monkeypatch.setenv("QUOTEX_IS_DEMO", "true")

    with pytest.raises(ValueError, match="limit must be an integer"):
        provider.get_candles("EURUSD_otc", 60, limit)
