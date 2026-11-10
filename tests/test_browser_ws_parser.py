import json

import pytest

from browser_ws_parser import (
    MinuteCandleAggregator,
    QuotexMarketFrameParser,
    parse_history_attachment,
    parse_quote_attachment,
)


def test_quote_binary_attachment_is_paired_with_event_header():
    parser = QuotexMarketFrameParser("USDDZD_otc")
    assert parser.feed('451-["quotes/stream",{"_placeholder":true,"num":0}]') == []
    records = parser.feed(b'\x04[["USDDZD_otc",1793803080.235,255.989,0]]')
    assert records == [{
        "kind": "tick",
        "asset": "USDDZD_otc",
        "timestamp": 1793803080.235,
        "price": 255.989,
        "flag": 0,
    }]


def test_quote_text_event_is_parsed():
    parser = QuotexMarketFrameParser("EURUSD_otc")
    records = parser.feed(
        '42["quotes/stream",[["EURUSD_otc",1793803080.235,1.1025,0]]]'
    )
    assert records[0]["kind"] == "tick"
    assert records[0]["price"] == 1.1025


def test_tick_aggregation_builds_one_minute_ohlc():
    aggregator = MinuteCandleAggregator()
    ticks = [
        {"asset": "EURUSD_otc", "timestamp": 120.5, "price": 1.10},
        {"asset": "EURUSD_otc", "timestamp": 125.0, "price": 1.12},
        {"asset": "EURUSD_otc", "timestamp": 151.0, "price": 1.08},
        {"asset": "EURUSD_otc", "timestamp": 181.0, "price": 1.09},
    ]
    updates = [aggregator.add(tick) for tick in ticks]
    assert updates[2]["time"] == 120
    assert updates[2]["open"] == 1.10
    assert updates[2]["high"] == 1.12
    assert updates[2]["low"] == 1.08
    assert updates[2]["close"] == 1.08
    assert updates[2]["tick_count"] == 3
    assert updates[3]["time"] == 180


def test_out_of_order_ticks_update_open_and_close_correctly():
    aggregator = MinuteCandleAggregator()
    aggregator.add({"asset": "EURUSD_otc", "timestamp": 130.0, "price": 1.11})
    candle = aggregator.add({"asset": "EURUSD_otc", "timestamp": 121.0, "price": 1.09})
    assert candle["open"] == 1.09
    assert candle["close"] == 1.11
    assert candle["high"] == 1.11
    assert candle["low"] == 1.09


def test_historical_binary_attachment_parses_explicit_ohlc():
    body = {
        "asset": "USDDZD_otc",
        "period": 60,
        "candles": [
            [1793797440, 255.885, 255.9, 255.912, 255.905, 76, 1793797499.921]
        ],
    }
    records = parse_history_attachment(
        b'\x04' + json.dumps(body).encode("utf-8"),
        "USDDZD_otc",
    )
    assert len(records) == 1
    assert records[0]["time"] == 1793797440
    assert records[0]["open"] == 255.885
    assert records[0]["high"] == 255.912
    assert records[0]["low"] == 255.9
    assert records[0]["close"] == 255.905


def test_history_binary_header_and_attachment_are_paired():
    parser = QuotexMarketFrameParser("USDDZD_otc")
    assert parser.feed(
        '451-["history/list/v2",{"_placeholder":true,"num":0}]'
    ) == []
    records = parser.feed(
        b'\x04' + json.dumps({
            "asset": "USDDZD_otc",
            "period": 60,
            "candles": [
                [1793797440, 255.885, 255.9, 255.912, 255.905, 76, 1793797499.921]
            ],
        }).encode("utf-8")
    )
    assert len(records) == 1
    assert records[0]["kind"] == "historical_candle"


def test_history_rejects_wrong_asset_and_timeframe():
    body = {
        "asset": "GBPUSD_otc",
        "period": 60,
        "candles": [[1793797440, 1.0, 0.9, 1.1, 1.0, 10, 1793797499.0]],
    }
    assert parse_history_attachment(
        b'\x04' + json.dumps(body).encode(), "EURUSD_otc"
    ) == []
    body["asset"] = "EURUSD_otc"
    body["period"] = 300
    assert parse_history_attachment(
        b'\x04' + json.dumps(body).encode(), "EURUSD_otc"
    ) == []


def test_unknown_or_malformed_binary_events_are_ignored():
    parser = QuotexMarketFrameParser("EURUSD_otc")
    assert parser.feed('451-["balance",{"_placeholder":true,"num":0}]') == []
    assert parser.feed(b'\x04{"private":"not market data"}') == []
    assert parse_quote_attachment(b"\x04not-json", "EURUSD_otc") == []


def test_invalid_attachment_count_is_rejected():
    parser = QuotexMarketFrameParser("EURUSD_otc")
    assert parser.feed(
        '459-["quotes/stream",{"_placeholder":true,"num":0}]'
    ) == []


def test_multiframe_attachment_is_waited_for_until_complete():
    parser = QuotexMarketFrameParser("EURUSD_otc")
    header = (
        '452-["quotes/stream",'
        '{"first":{"_placeholder":true,"num":0},'
        '"second":{"_placeholder":true,"num":1}}]'
    )
    assert parser.feed(header) == []
    assert parser.feed(b'\x04[["EURUSD_otc",120,1.1,0]]') == []
    result = parser.feed(b'\x04[["EURUSD_otc",121,1.2,0]]')
    assert len(result) == 2


@pytest.mark.parametrize("tick", [
    {},
    {"asset": "EURUSD_otc", "timestamp": "bad", "price": 1.0},
    {"asset": "EURUSD_otc", "timestamp": 120, "price": float("nan")},
])
def test_aggregator_rejects_invalid_ticks(tick):
    assert MinuteCandleAggregator().add(tick) is None
