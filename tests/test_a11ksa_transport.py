import json

import pytest

from a11ksa_candle_transport import (
    CandleTransportError,
    build_authorization_frame,
    parse_authorization_response,
)


def test_authorization_frame_matches_upstream_raw_ssid_handshake():
    assert build_authorization_frame("  demo-session-value  ") == "demo-session-value"


def test_authorization_frame_rejects_missing_session():
    with pytest.raises(CandleTransportError, match="QUOTEX_DEMO_SSID"):
        build_authorization_frame("  ")


def test_authorization_response_requires_explicit_demo_confirmation():
    body = {"isDemo": 1, "userId": 123}
    assert parse_authorization_response(
        '42["s_authorization",' + json.dumps(body) + "]"
    ) == body


def test_authorization_response_rejects_auth_success_without_demo_marker():
    with pytest.raises(CandleTransportError, match="did not explicitly confirm demo"):
        parse_authorization_response('42["s_authorization",{"userId":123}]')


def test_authorization_response_rejects_server_rejection():
    with pytest.raises(CandleTransportError, match="rejected"):
        parse_authorization_response('42["authorization/reject",{"reason":"invalid"}]')


def test_parse_candle_event_accepts_upstream_history_row_format():
    from a11ksa_candle_transport import parse_candle_event

    body = {
        "asset": "EURUSD_otc",
        "period": 60,
        "history": [
            [1_800_000_000, 1.1000, 1.0990, 1.1020, 1.1010, 25],
            [1_800_000_060, 1.1010, 1.1000, 1.1030, 1.1020],
        ],
    }
    frame = '42["history/list/v2",' + json.dumps(body) + "]"

    candles = parse_candle_event(frame, "EURUSD_otc")

    assert candles == [
        {
            "time": 1_800_000_000,
            "open": 1.1000,
            "high": 1.1020,
            "low": 1.0990,
            "close": 1.1010,
            "volume": 25.0,
        },
        {
            "time": 1_800_000_060,
            "open": 1.1010,
            "high": 1.1030,
            "low": 1.1000,
            "close": 1.1020,
            "volume": 0.0,
        },
    ]


def test_parse_candle_event_accepts_binary_attachment_and_candles_key():
    from a11ksa_candle_transport import parse_candle_event

    body = {
        "asset": "EURUSD_otc",
        "period": 60,
        "candles": [[1_800_000_000, 1.1, 1.0, 1.2, 1.15, 10]],
    }

    candles = parse_candle_event(b"\\x04" + json.dumps(body).encode(), "EURUSD_otc")

    assert len(candles) == 1
    assert candles[0]["open"] == 1.1
    assert candles[0]["low"] == 1.0
    assert candles[0]["high"] == 1.2
    assert candles[0]["close"] == 1.15
    assert candles[0]["volume"] == 10.0


@pytest.mark.parametrize(
    "asset,period",
    [("GBPUSD_otc", 60), ("EURUSD_otc", 300)],
)
def test_parse_candle_event_rejects_wrong_asset_or_period(asset, period):
    from a11ksa_candle_transport import parse_candle_event

    body = {
        "asset": asset,
        "period": period,
        "candles": [[1_800_000_000, 1.1, 1.0, 1.2, 1.15]],
    }
    frame = '42["history/list/v2",' + json.dumps(body) + "]"

    assert parse_candle_event(frame, "EURUSD_otc") == []


def test_parse_candle_event_skips_invalid_ohlc_rows():
    from a11ksa_candle_transport import parse_candle_event

    body = {
        "asset": "EURUSD_otc",
        "period": 60,
        "candles": [
            [1_800_000_000, 1.1, 1.0, 1.2, 1.15],
            [1_800_000_060, 1.1, 1.3, 1.2, 1.15],
            [1_800_000_120, 1.1, 1.0, float("nan"), 1.15],
        ],
    }
    frame = '42["history/list/v2",' + json.dumps(body) + "]"

    candles = parse_candle_event(frame, "EURUSD_otc")

    assert [candle["time"] for candle in candles] == [1_800_000_000]
