from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from data_collector import MarketDataError, connection_status, get_assets, get_candles
from strategies import analyze_candles

app = FastAPI(title="Standard Forex Data & Signal Bot", version="0.4.0")


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


def _validate_timeframe(timeframe_seconds: int) -> None:
    if timeframe_seconds not in {60, 300, 900, 1800, 2700, 3600, 7200, 14400, 28800, 86400, 604800, 2592000}:
        raise HTTPException(status_code=422, detail="Unsupported timeframe_seconds value")


@app.get("/api/candles")
def candles(
    asset: str = Query("EUR/USD", min_length=3, max_length=40),
    timeframe_seconds: int = Query(60, ge=1),
    limit: int = Query(100, ge=1, le=5000),
):
    _validate_timeframe(timeframe_seconds)
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


@app.get("/api/analysis")
def analysis(
    asset: str = Query("EUR/USD", min_length=3, max_length=40),
    timeframe_seconds: int = Query(60, ge=1),
    limit: int = Query(100, ge=30, le=5000),
):
    """One read-only request: fetch candles and compute a heuristic summary."""
    _validate_timeframe(timeframe_seconds)
    try:
        result = get_candles(asset, timeframe_seconds, limit)
        summary = analyze_candles(result)
        return {
            "source": "Twelve Data (independent provider; not affiliated with Quotex)",
            "market_type": "standard forex, not Quotex OTC",
            "symbol": asset,
            "timeframe_seconds": timeframe_seconds,
            "count": len(result),
            "latest_candle": result[-1] if result else None,
            "recent_candles": result[-10:],
            "analysis": summary,
            "disclaimer": "Heuristic educational summary, not financial advice or a guarantee. Standard forex data is not Quotex OTC pricing.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Free Forex Signal Bot</title><style>body{font-family:system-ui;max-width:1000px;margin:32px auto;padding:0 16px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:20px;margin:14px 0}small,.muted{color:#b6c0d1}.warn{color:#ffcc80}.signal{font-size:1.5rem;font-weight:700}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:8px;border-bottom:1px solid #3a4355}th:first-child,td:first-child{text-align:left}.tablewrap{overflow-x:auto}button{background:#7c9cff;color:#10131a;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}code{overflow-wrap:anywhere}</style></head><body><h1>Forex Live Data &amp; Signal Bot</h1><p>Read-only market data · No automatic trades</p><section><h2>Data provider</h2><p>Twelve Data — independent standard forex market-data API. Not affiliated with, endorsed by, or partnered with Quotex. This is not a Quotex OTC feed.</p><small>Standard forex candles may differ from Quotex OTC/synthetic prices. The free plan has a daily request quota.</small></section><section><h2>API status</h2><p id='status'>Checking API key…</p><small>The API key status does not prove candle data is available.</small></section><section><h2>Analysis summary</h2><p id='signal' class='signal'>Not loaded</p><p id='reason' class='muted'>Press Refresh to fetch a new candle set and calculate the starter EMA/RSI heuristic.</p><p id='metrics' class='muted'></p><button id='refresh'>Refresh candles &amp; analysis</button><p class='warn'>CALL / PUT / WAIT are heuristic labels only, not guaranteed predictions or financial advice.</p></section><section><h2>Latest OHLC candles</h2><p id='candlestatus' class='muted'>No candle request made yet.</p><div class='tablewrap'><table><thead><tr><th>Time (UTC)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody id='candles'><tr><td colspan='5'>Click Refresh to load data.</td></tr></tbody></table></div></section><script>
const fmtPrice = n => Number(n).toFixed(5);
function setError(msg){document.getElementById('candlestatus').textContent=msg;document.getElementById('signal').textContent='Unavailable';document.getElementById('reason').textContent='No signal calculated because valid candle data was not available.';document.getElementById('candles').innerHTML='<tr><td colspan="5">No data returned.</td></tr>';}
async function refresh(){const b=document.getElementById('refresh');b.disabled=true;b.textContent='Loading…';document.getElementById('candlestatus').textContent='Requesting latest candles…';try{const r=await fetch('/api/analysis?asset=EUR%2FUSD&timeframe_seconds=60&limit=100');const d=await r.json();if(!r.ok)throw new Error(d.detail||'Request failed (HTTP '+r.status+')');document.getElementById('candlestatus').textContent='Received '+d.count+' real standard-forex candles from Twelve Data.';document.getElementById('signal').textContent=d.analysis.signal;document.getElementById('reason').textContent=d.analysis.reason;document.getElementById('metrics').textContent='Symbol: '+d.symbol+' · Interval: '+d.timeframe_seconds+' sec · RSI(14): '+(d.analysis.rsi_14??'N/A')+' · Candles used: '+d.analysis.candles_used;const rows=[...(d.recent_candles||[])].reverse().map(c=>'<tr><td>'+new Date(c.time*1000).toISOString().replace('T',' ').slice(0,19)+'</td><td>'+fmtPrice(c.open)+'</td><td>'+fmtPrice(c.high)+'</td><td>'+fmtPrice(c.low)+'</td><td>'+fmtPrice(c.close)+'</td></tr>').join('');document.getElementById('candles').innerHTML=rows||'<tr><td colspan="5">No candles returned.</td></tr>';}catch(e){setError(e.message||'Could not fetch candles.');}finally{b.disabled=false;b.textContent='Refresh candles & analysis';}}
fetch('/api/status').then(r=>r.json()).then(d=>document.getElementById('status').textContent=d.message).catch(()=>document.getElementById('status').textContent='Status unavailable');document.getElementById('refresh').addEventListener('click',refresh);
</script></body></html>"""
