from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from data_collector import MarketDataError, connection_status, get_assets, get_candles

app = FastAPI(title="Standard Forex Data & Signal Bot", version="0.3.0")


@app.get("/health")
def health():
    return {"status": "ok", "time_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status():
    return connection_status()


@app.get("/api/assets")
def assets():
    try:
        return {
            "source": "Twelve Data (independent provider; not affiliated with Quotex)",
            "market_type": "standard forex, not Quotex OTC",
            "assets": get_assets(),
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/api/candles")
def candles(
    asset: str = Query("EUR/USD", min_length=3, max_length=40),
    timeframe_seconds: int = Query(60, ge=1),
    limit: int = Query(100, ge=1, le=5000),
):
    try:
        result = get_candles(asset, timeframe_seconds, limit)
        return {
            "source": "Twelve Data (independent provider; not affiliated with Quotex)",
            "market_type": "standard forex, not Quotex OTC",
            "symbol": asset,
            "timeframe_seconds": timeframe_seconds,
            "count": len(result),
            "candles": result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Free Forex Signal Bot</title><style>body{font-family:system-ui;max-width:850px;margin:40px auto;padding:0 18px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:22px;margin:14px 0}small{color:#b6c0d1}.warn{color:#ffcc80}</style></head><body><h1>Forex Live Data &amp; Signal Bot</h1><p>Signal-only dashboard · No automatic trades</p><section><h2>Data provider</h2><p>Twelve Data — independent standard forex market-data API. Not affiliated with, endorsed by, or partnered with Quotex. This is not a Quotex OTC feed.</p><small>Standard forex OHLC candles can differ from Quotex OTC/synthetic prices. The free Basic plan has a daily request quota and does not provide the same data as Quotex.</small></section><section><h2>Connection status</h2><p id='status'>Checking…</p><small>Health confirms only that this web service is running. API authentication does not alone prove candle data is available.</small></section><section><h2>Read-only data endpoints</h2><p><code>/api/assets</code> returns forex pairs listed by Twelve Data.</p><p><code>/api/candles?asset=EUR%2FUSD&amp;timeframe_seconds=60&amp;limit=100</code> returns standard forex OHLC candles if available on your plan.</p></section><section><h2>Signals</h2><p class='warn'>Treat these candles as standard forex reference data only, not as the exact price feed on Quotex OTC. No sample or fabricated prices are shown.</p></section><script>fetch('/api/status').then(r=>r.json()).then(d=>document.getElementById('status').textContent=d.message).catch(()=>document.getElementById('status').textContent='Status unavailable');</script></body></html>"""
