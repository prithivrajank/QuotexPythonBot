import json
import ssl

import pytest

from a11ksa_candle_transport import (
    ALLOWED_OUTBOUND_EVENTS,
    CandleTransportError,
    _event_frame,
    _validate_endpoint,
    build_authorization_frame,
    build_candle_frames,
    build_tls_context,
    parse_candle_event,
)


def test_tls_context_requires_verified_tls():
    context = build_tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_endpoint_is_pinned_to_reviewed_wss_host():
    _validate_endpoint("wss://ws2.qxbroker.com/socket.io/?EIO=3&transport=websocket")
    with pytest.raises(CandleTransportError):
        _validate_endpoint("ws://ws2.qxbroker.com/socket.io/")
    with pytest.raises(CandleTransportError):
        _validate_endpoint("wss://example.com/socket.io/")


def test_only_allowlisted_events_can_be_sent():
    assert ALLOWED_OUTBOUND_EVENTS == {
        "authorization", "instruments/follow", "instruments/update",
        "chart_notification/get"
    }
    for forbidden in ("balance", "orders/open", "orders/close", "place_order"):
        with pytest.raises(CandleTransportError):
            _event_frame(forbidden, {})


def test_demo_authorization_frame_never_selects_live_mode():
    frame = build_authorization_frame("demo-session")
    event, payload = json.loads(frame[2:])
    assert event == "authorization"
    assert payload["isDemo"] == 1
    assert payload["session"] == "demo-session"


def test_empty_session_is_rejected():
    with pytest.raises(CandleTransportError):
        build_authorization_frame(" ")


def test_candle_subscription_frames_are_only_60_seconds():
    frames = build_candle_frames("EURUSD_otc")
    assert len(frames) == 3
    assert json.loads(frames[0][2:]) == ["instruments/follow", "EURUSD_otc"]
    assert json.loads(frames[1][2:]) == [
        "instruments/update", {"asset": "EURUSD_otc", "period": 60}
    ]
    assert json.loads(frames[2][2:])[0] == "chart_notification/get"
    with pytest.raises(CandleTransportError):
        build_candle_frames("EURUSD_otc", 300)


def test_parse_accepts_only_explicit_matching_candle_payload():
    frame = "42" + json.dumps(["history/list/v2", {
        "asset": "EURUSD_otc", "period": 60,
        "history": [{"time": 1700000000, "open": 1.0, "high": 1.2,
                     "low": 0.9, "close": 1.1}]
    }])
    rows = parse_candle_event(frame, "EURUSD_otc")
    assert rows == [{
        "time": 1700000000, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1
    }]


@pytest.mark.parametrize("frame", [
    "42" + json.dumps(["balance", {"balance": 100}]),
    "42" + json.dumps(["history/list/v2", {
        "asset": "GBPUSD_otc", "period": 60, "history": []
    }]),
    "42" + json.dumps(["history/list/v2", {
        "asset": "EURUSD_otc", "period": 300, "history": []
    }]),
    "not-json",
    "451-[\"history/list/v2\",{\"_placeholder\":true}]",
])
def test_parser_rejects_non_candle_wrong_asset_wrong_timeframe_and_binary(frame):
    assert parse_candle_event(frame, "EURUSD_otc") == []


def test_parser_rejects_invalid_ohlc():
    frame = "42" + json.dumps(["history/list/v2", {
        "asset": "EURUSD_otc", "period": 60,
        "history": [{"time": 1700000000, "open": 1.2, "high": 1.0,
                     "low": 0.9, "close": 1.1}]
    }])
    assert parse_candle_event(frame, "EURUSD_otc") == []
