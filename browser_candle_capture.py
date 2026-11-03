"""Local read-only capture of explicit OHLC records from a manually logged-in Quotex browser."""
from __future__ import annotations
import asyncio, json, re, time
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright

OUTPUT = Path("browser_candles.jsonl")
SENSITIVE = re.compile(r"(ssid|session|token|cookie|authorization|password|secret|auth)", re.I)

def decode_packet(frame: str):
    text = frame.strip()
    if text.startswith("42"):
        text = text[2:]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

def find_ohlc(value: Any):
    if isinstance(value, dict):
        for keys in (("open","high","low","close"), ("o","h","l","c")):
            try:
                o,h,lo,c = (float(value[k]) for k in keys)
                raw_ts = next(value[k] for k in ("time","timestamp","from","at","epoch") if k in value)
                ts = int(float(raw_ts))
                if ts > 10_000_000_000: ts //= 1000
                if ts > 0 and all(map(lambda x: x == x and abs(x) != float("inf"), (o,h,lo,c))) and h >= max(o,lo,c) and lo <= min(o,h,c):
                    symbol = next((str(value[k]) for k in ("asset","symbol","pair","instrument") if k in value), "UNKNOWN")
                    yield {"time":ts,"open":o,"high":h,"low":lo,"close":c,"symbol":symbol}
                    break
            except (KeyError,TypeError,ValueError,StopIteration,OverflowError):
                pass
        for child in value.values():
            yield from find_ohlc(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_ohlc(child)

def handler(url: str):
    seen = set()
    def on_frame(payload):
        if isinstance(payload, bytes): payload = payload.decode("utf-8", errors="ignore")
        if not isinstance(payload, str): return
        data = decode_packet(payload)
        if data is None: return
        event = data[0] if isinstance(data,list) and data and isinstance(data[0],str) else "non-event-packet"
        rows = list(find_ohlc(data))
        for row in rows:
            key = (row["symbol"],row["time"])
            if key in seen: continue
            seen.add(key)
            record = {**row,"captured_at":int(time.time()),"event":event,"source":"manual_Quotex_browser"}
            with OUTPUT.open("a",encoding="utf-8") as f: f.write(json.dumps(record)+"\n")
            print("VALID OHLC:",json.dumps(record))
        if not rows and event != "non-event-packet":
            kind = type(data[1]).__name__ if isinstance(data,list) and len(data)>1 else type(data).__name__
            print("WS EVENT:",event,"payload type:",kind)
    return on_frame

async def main():
    print("Opening browser. Sign in manually to Quotex Demo; never share cookies or session data.")
    print("Open a chart and leave it visible for 2-3 minutes. Ctrl+C stops capture.")
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context("quotex_browser_profile",headless=False,viewport={"width":1440,"height":900})
        page = context.pages[0] if context.pages else await context.new_page()
        def on_ws(ws):
            host = re.sub(r"wss?://([^/]+).*",r"\1",ws.url)
            print("WEBSOCKET:",host)
            ws.on("framereceived",handler(ws.url))
        page.on("websocket",on_ws)
        await page.goto("https://qxbroker.com/en",wait_until="domcontentloaded")
        print("After login, open EUR/USD OTC or your Demo pair.")
        try:
            while True: await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
