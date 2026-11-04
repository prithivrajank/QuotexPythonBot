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
    parse_quote_event,
    aggregate_ticks_to_candles,
)


def test_tls_context_requires_verified_tls():
    context = build_tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_endpoint_is_pinned_to_reviewed_wss_host():
    _validate_endpoint("wss://ws2.quotex.com/socket.io/?EIO=3&transport=websocket")
    with pytest.raises(CandleTransportError):
        _validate_endpoint("ws://ws2.quotex.com/socket.io/")
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


def test_parse_observed_binary_candle_payload():
    body = {
        "asset": "USDDZD_otc",
        "period": 60,
        "history": [[1793796987.576, 255.91, 0]],
        "candles": [
            [1793797500, 255.905, 255.9, 255.906, 255.9, 7, 1793797504.949],
            [1793797440, 255.885, 255.905, 255.912, 255.885, 76, 1793797499.921],
        ],
    }
    frame = b"\x04" + json.dumps(body).encode("utf-8")
    rows = parse_candle_event(frame, "USDDZD_otc")
    assert rows == [
        {
            "time": 1793797440, "open": 255.885, "high": 255.912,
            "low": 255.885, "close": 255.905, "tick_count": 76,
            "last_update": 1793797499.921,
        },
        {
            "time": 1793797500, "open": 255.905, "high": 255.906,
            "low": 255.9, "close": 255.9, "tick_count": 7,
            "last_update": 1793797504.949,
        },
    ]


def test_parse_accepts_matching_socketio_json_candle_event():
    frame = "42" + json.dumps(["history/list/v2", {
        "asset": "EURUSD_otc", "period": 60,
        "candles": [[1700000040, 1.0, 1.1, 1.2, 0.9, 12, 1700000099.0]]
    }])
    assert parse_candle_event(frame, "EURUSD_otc")[0]["close"] == 1.1


@pytest.mark.parametrize("frame", [
    "42" + json.dumps(["balance", {"balance": 100}]),
    "42" + json.dumps(["history/list/v2", {
        "asset": "GBPUSD_otc", "period": 60, "candles": []
    }]),
    "42" + json.dumps(["history/list/v2", {
        "asset": "EURUSD_otc", "period": 300, "candles": []
    }]),
    "not-json",
    b"\x04not-json",
    b"\x04" + json.dumps({
        "asset": "EURUSD_otc", "period": 60, "history": [[1, 1, 1]]
    }).encode(),
])
def test_parser_rejects_wrong_asset_timeframe_or_non_candle_payload(frame):
    assert parse_candle_event(frame, "EURUSD_otc") == []


def test_parser_rejects_invalid_ohlc():
    frame = b"\x04" + json.dumps({
        "asset": "EURUSD_otc", "period": 60,
        "candles": [[1700000040, 1.2, 1.1, 1.0, 0.9, 12, 1700000099.0]]
    }).encode()
    assert parse_candle_event(frame, "EURUSD_otc") == []


def test_parser_rejects_unaligned_candle_timestamp():
    frame = b"\x04" + json.dumps({
        "asset": "EURUSD_otc", "period": 60,
        "candles": [[1700000001, 1.0, 1.1, 1.2, 0.9, 12, 1700000099.0]]
    }).encode()
    assert parse_candle_event(frame, "EURUSD_otc") == []

def test_parse_observed_quotes_stream_binary_attachment():
    frame = b'\\x04[["USDDZD_otc",1793803080.235,255.989,0]]'
    ticks = parse_quote_event(frame, "USDDZD_otc")
    assert ticks == [{
        "asset": "USDDZD_otc",
        "timestamp": 1793803080.235,
        "price": 255.989,
        "flag": 0,
    }]


def test_quote_parser_rejects_wrong_asset_and_invalid_values():
    frame = b'\\x04' + json.dumps([
        ["EURUSD_otc", 1793803080.235, 1.2, 0],
        ["USDDZD_otc", "bad-time", 255.9, 0],
        ["USDDZD_otc", 1793803080.235, float("inf"), 0],
    ]).encode()
    assert parse_quote_event(frame, "USDDZD_otc") == []


def test_quote_ticks_aggregate_into_one_minute_ohlc():
    ticks = parse_quote_event(
        b'\\x04' + json.dumps([
            ["USDDZD_otc", 1793803080.235, 255.989, 0],
            ["USDDZD_otc", 1793803082.0, 255.995, 0],
            ["USDDZD_otc", 1793803095.0, 255.980, 0],
            ["USDDZD_otc", 1793803141.0, 256.010, 0],
        ]).encode(),
        "USDDZD_otc",
    )
    candles = aggregate_ticks_to_candles(ticks, "USDDZD_otc")
    assert len(candles) == 2
    assert candles[0] == {
        "time": 1793803080,
        "open": 255.989,
        "high": 255.995,
        "low": 255.980,
        "close": 255.980,
        "tick_count": 3,
        "last_update": 1793803095.0,
    }
    assert candles[1]["open"] == candles[1]["close"] == 256.010

