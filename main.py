from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from data_collector import (
    MarketDataError,
    connection_status,
    get_assets,
    get_candles,
)

app = FastAPI(title="Quotex OTC Signals — OTCharts data", version="0.2.0")


@app.get("/health")
def health():
    return {"status": "ok", "time_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status():
    # This checks API authentication, not the freshness of a candle request.
    return connection_status()


@app.get("/api/assets")
def assets():
    try:
        return {
            "source": "OTCharts (independent third-party; not affiliated with Quotex)",
            "venue": "quotex",
            "assets": get_assets(),
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/api/candles")
def candles(
    asset: str = Query(..., min_length=1, max_length=80),
    timeframe_seconds: int = Query(60, ge=1),
    limit: int = Query(100, ge=1, le=5000),
):
    try:
        result = get_candles(asset, timeframe_seconds, limit)
        return {
            "source": "OTCharts (independent third-party; not affiliated with Quotex)",
            "venue": "quotex",
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
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Quotex OTC Signal Bot</title><style>body{font-family:system-ui;max-width:850px;margin:40px auto;padding:0 18px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:22px;margin:14px 0}small{color:#b6c0d1}.warn{color:#ffcc80}</style></head><body><h1>Quotex OTC Live Data &amp; Signal Bot</h1><p>Signal-only dashboard · No automatic trades</p><section><h2>Data provider</h2><p>OTCharts — independent third-party market-data provider. Not affiliated with, endorsed by, or partnered with Quotex. This is not an official Quotex API.</p><small>OTC quotes may differ from standard forex market prices. This integration is read-only and does not place trades.</small></section><section><h2>Connection status</h2><p id='status'>Checking…</p><small>The health endpoint confirms only that this web service is running. API authentication does not alone prove candle data is available.</small></section><section><h2>Read-only data endpoints</h2><p><code>/api/assets</code> returns the provider's current Quotex symbol catalogue.</p><p><code>/api/candles?asset=EURUSD_otc&amp;timeframe_seconds=60&amp;limit=100</code> returns real OHLC candles if the symbol and plan are available.</p></section><section><h2>Signals</h2><p class='warn'>No sample or fabricated prices are shown. Validate fresh candle data before relying on any strategy output.</p></section><script>fetch('/api/status').then(r=>r.json()).then(d=>document.getElementById('status').textContent=d.message).catch(()=>document.getElementById('status').textContent='Status unavailable');</script></body></html>"""
