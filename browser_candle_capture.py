"""Local, read-only capture of observed Quotex Demo market WebSocket frames."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class MarketCapture:
    def __init__(self, asset: str):
        # Lazy import keeps parser tests independent from Playwright.
        from browser_ws_parser import MinuteCandleAggregator, QuotexMarketFrameParser

        self.parser = QuotexMarketFrameParser(asset)
        self.aggregator = MinuteCandleAggregator()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.ticks_path = Path(f"browser_ticks_{stamp}.jsonl")
        self.candles_path = Path(f"browser_candles_{stamp}.jsonl")
        self.history_path = Path(f"browser_history_{stamp}.jsonl")
        self.tick_count = 0
        self.candle_count = 0
        self.history_count = 0

    @staticmethod
    def _append(path: Path, record: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def on_frame(self, payload: str | bytes) -> None:
        # Never print or persist raw frames; they may contain private account data.
        for record in self.parser.feed(payload):
            captured_at = datetime.now(timezone.utc).isoformat()
            if record["kind"] == "tick":
                self._append(self.ticks_path, {
                    **record,
                    "captured_at": captured_at,
                    "source": "manual_quotex_demo_browser",
                })
                candle = self.aggregator.add(record)
                self.tick_count += 1
                if candle:
                    self._append(self.candles_path, {
                        **candle,
                        "captured_at": captured_at,
                        "source": "aggregated_quotex_demo_ticks",
                    })
                    self.candle_count += 1
                    print(
                        "LIVE TICK", record["asset"],
                        "price=", record["price"],
                        "timestamp=", record["timestamp"],
                        "| 1m OHLC",
                        candle["open"], candle["high"],
                        candle["low"], candle["close"],
                        "ticks=", candle["tick_count"],
                    )
            elif record["kind"] == "historical_candle":
                self._append(self.history_path, {
                    **record,
                    "captured_at": captured_at,
                    "source": "manual_quotex_demo_browser",
                })
                self.history_count += 1
                print(
                    "HISTORICAL OHLC", record["asset"], record["time"],
                    "O=", record["open"], "H=", record["high"],
                    "L=", record["low"], "C=", record["close"],
                )


async def main() -> None:
    from playwright.async_api import async_playwright

    asset = input("Enter exact Demo chart symbol (example EURUSD_otc): ").strip()
    if not asset:
        raise SystemExit("A chart symbol is required.")
    capture = MarketCapture(asset)

    print("Opening a local Chromium window. Sign in manually to Quotex Demo.")
    print("Select the same symbol entered above and keep its chart visible.")
    print("Only parsed incoming quote/history market data will be saved.")
    print("Cookies, credentials, session IDs and raw frames are never saved.")
    print("Press Ctrl+C in this terminal to stop.")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            "quotex_browser_profile",
            headless=False,
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        def on_websocket(websocket) -> None:
            if urlsplit(websocket.url).hostname != "ws2.quotex.com":
                return
            print("Observed the Quotex market WebSocket.")
            websocket.on("framereceived", capture.on_frame)

        page.on("websocket", on_websocket)
        try:
            await page.goto("https://qxbroker.com/en", wait_until="domcontentloaded")
            print("Complete Demo login yourself, then open", asset, "chart.")
            while True:
                await asyncio.sleep(1)
        finally:
            await context.close()

    print("Capture summary:")
    print("Ticks:", capture.tick_count)
    print("Live 1-minute OHLC updates:", capture.candle_count)
    print("Historical candles:", capture.history_count)
    print("Tick file:", capture.ticks_path)
    print("Live OHLC file:", capture.candles_path)
    print("History file:", capture.history_path)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCapture stopped.")
