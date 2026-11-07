from contextlib import asynccontextmanager
import asyncio
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

from data_collector import MarketDataError, connection_status, data_source_label, get_assets, get_candles
from runtime import bot_status, get_snapshot, get_watchlist, refresh_snapshot, scheduled_refresh_loop, set_bot_enabled
from signal_history import get_history, history_summary
from strategies import analyze_candles, build_chart_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduled_refresh_loop())
    app.state.refresh_task = task
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Quotex Demo Read-Only Signal Bot", version="0.6.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "time_utc": datetime.now(timezone.utc).isoformat()}


@app.get("/api/bot")
def bot_state():
    if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa":
        return {"enabled": False, "message": "Automatic bot mode is disabled for A11KSA candle-only mode."}
    return bot_status()


@app.post("/api/bot/{action}")
def bot_control(action: str):
    if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa":
        raise HTTPException(status_code=404, detail="Bot controls are disabled for A11KSA candle-only mode.")
    if action not in {"on", "off"}:
        raise HTTPException(status_code=422, detail="Action must be on or off")
    return set_bot_enabled(action == "on")


@app.get("/api/status")
def status():
    return connection_status()



@app.get("/market", response_class=HTMLResponse)
def market_data_dashboard():
    """Clean read-only market-data view; deliberately excludes the legacy signal UI."""
    return """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Read-only Market Data</title><script src='https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'></script><style>
*{box-sizing:border-box}body{font:15px system-ui,-apple-system,sans-serif;background:#10131a;color:#f3f4f6;margin:22px auto;padding:0 14px;max-width:1000px}section{background:#1c2230;padding:16px;border-radius:12px;margin:12px 0}.muted,small{color:#aab4c5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.metric{background:#121722;padding:12px;border-radius:9px}.metric strong{display:block;margin-top:5px;overflow-wrap:anywhere}select,button{padding:10px;border-radius:8px;border:1px solid #46516a;background:#121722;color:#f3f4f6}button{background:#8da8ff;color:#10131a;font-weight:700;cursor:pointer}button:disabled{opacity:.55}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{text-align:left;padding:9px;border-bottom:1px solid #39445a;white-space:nowrap}.price{font-weight:700}.chart{height:360px;width:100%}.pill{display:inline-block;background:#303b52;padding:5px 9px;border-radius:20px}
</style></head><body><h1>Read-only Market Data</h1><p class='muted'>Multi-pair market snapshots · OTC and standard Forex are identified separately · no trading or signal recommendations</p>
<section><div class='grid'><div class='metric'>Provider<strong id='provider'>Loading…</strong></div><div class='metric'>Market type<strong id='marketType'>Loading…</strong></div><div class='metric'>Connection<strong id='connection'>Checking…</strong></div></div><p id='statusMessage' class='muted'>Checking provider status…</p></section>
<section><h2>Pair watchlist</h2><label for='pair'>Select pair </label> <select id='pair'><option>Loading pairs…</option></select> <button id='refresh'>Fetch latest candles (1 request)</button><p id='pairStatus' class='muted'>Snapshots are cached. Manual fetch may use provider quota.</p></section>
<section><h2>Latest candle</h2><div class='grid'><div class='metric'>Open<strong id='open'>—</strong></div><div class='metric'>High<strong id='high'>—</strong></div><div class='metric'>Low<strong id='low'>—</strong></div><div class='metric'>Close<strong id='close'>—</strong></div></div><p id='candleInfo' class='muted'>No cached candle yet.</p></section>
<section><h2>60-second candlestick chart</h2><div id='candleChart' class='chart'></div><p class='muted'>Read-only OHLC display · no indicators or signal calculations.</p></section>
<section><h2>Recent candles</h2><div class='tablewrap'><table><thead><tr><th>Time (local)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody id='candles'><tr><td colspan='5'>No cached candles yet. Choose a pair and fetch once.</td></tr></tbody></table></div></section>
<section><h2>Observed quote ticks</h2><p id='tickStatus' class='muted'>Connecting to quote stream…</p><div class='tablewrap'><table><thead><tr><th>Symbol</th><th>Market</th><th>Price</th><th>Time (local)</th></tr></thead><tbody id='ticks'><tr><td colspan='4'>No verified quote events received.</td></tr></tbody></table></div><small>REST candle closes are never presented as live ticks. Tick rows appear only when the selected integration emits actual quote events.</small></section>
<script>
const $=id=>document.getElementById(id), fmt=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':Number(v).toPrecision(9);
let symbols=[];let chart=null,candleSeries=null;
if(window.LightweightCharts){chart=LightweightCharts.createChart($('candleChart'),{height:360,layout:{background:{color:'#1c2230'},textColor:'#d6deeb'},grid:{vertLines:{color:'#30384a'},horzLines:{color:'#30384a'}},timeScale:{timeVisible:true,secondsVisible:false}});candleSeries=chart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});window.addEventListener('resize',()=>chart.applyOptions({width:$('candleChart').clientWidth}));}
function showSnapshot(d){if(!d||!d.available){$('pairStatus').textContent=d?.message||'No cached snapshot for this pair yet.';return}
const c=d.latest_candle||{};$('open').textContent=fmt(c.open);$('high').textContent=fmt(c.high);$('low').textContent=fmt(c.low);$('close').textContent=fmt(c.close);
$('candleInfo').textContent='Symbol: '+(d.symbol||'—')+' · '+(d.timeframe_seconds||60)+'s candle · '+(c.market_type||d.market_type||'provider-specific')+' · Candle time: '+(c.time?new Date(c.time*1000).toLocaleString():'—')+' · Snapshot fetched: '+(d.updated_at||'—');
$('pairStatus').textContent=(d.source||'Provider')+' · '+(d.count||0)+' candles available. Read-only display; no signal analysis or alerts.'
const rows=(d.recent_candles||[]).slice().reverse().map(x=>'<tr><td>'+new Date(x.time*1000).toLocaleString()+'</td><td>'+fmt(x.open)+'</td><td>'+fmt(x.high)+'</td><td>'+fmt(x.low)+'</td><td class="price">'+fmt(x.close)+'</td></tr>').join('');
$('candles').innerHTML=rows||'<tr><td colspan="5">No candle history.</td></tr>';if(candleSeries){const chartRows=(d.chart?.candles||d.recent_candles||[]).map(x=>({time:Number(x.time),open:Number(x.open),high:Number(x.high),low:Number(x.low),close:Number(x.close)})).filter(x=>Number.isFinite(x.time)&&Number.isFinite(x.open)&&Number.isFinite(x.high)&&Number.isFinite(x.low)&&Number.isFinite(x.close));candleSeries.setData(chartRows);chart.timeScale().fitContent();}}
async function loadStatus(){try{const r=await fetch('/api/status',{cache:'no-store'}),d=await r.json();$('provider').textContent=d.source||'Unknown';$('marketType').textContent=d.market_type||'Provider-specific';$('connection').textContent=d.connected?'Connected':(d.streaming_available?'Stream configured':'Status reported by provider');$('statusMessage').textContent=d.message||'Provider status loaded. Check provider-specific availability before relying on data.';}catch(e){$('statusMessage').textContent='Status unavailable: '+e.message;}}
async function loadPairs(){try{const r=await fetch('/api/watchlist',{cache:'no-store'}),d=await r.json();symbols=d.symbols||[];$('pair').innerHTML=symbols.map(s=>'<option value="'+s+'">'+s+'</option>').join('')||'<option value="">No configured pairs</option>';$('marketType').textContent=d.market_type||'Provider-specific';$('provider').textContent=d.source||'Unknown';$('pairStatus').textContent='Configured '+symbols.length+' pairs · '+(d.note||'Cached data only until manually refreshed.');await loadSnapshot();}catch(e){$('pairStatus').textContent='Could not load watchlist: '+e.message;}}
async function loadSnapshot(){const s=$('pair').value;if(!s)return;try{const r=await fetch('/api/latest?asset='+encodeURIComponent(s),{cache:'no-store'});showSnapshot(await r.json());}catch(e){$('pairStatus').textContent='Snapshot unavailable: '+e.message;}}
async function refreshPair(){const b=$('refresh');b.disabled=true;b.textContent='Fetching…';try{const s=$('pair').value;if(!s)throw new Error('No pair selected');const r=await fetch('/api/refresh?asset='+encodeURIComponent(s),{method:'POST',cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Provider fetch failed');showSnapshot(d);}catch(e){$('pairStatus').textContent='Fetch failed: '+e.message;}finally{b.disabled=false;b.textContent='Fetch latest candles (1 request)';}}
function connectTicks(){const scheme=location.protocol==='https:'?'wss':'ws',ws=new WebSocket(scheme+'://'+location.host+'/ws/market');ws.onmessage=e=>{const d=JSON.parse(e.data),ticks=d.ticks||[];$('tickStatus').textContent=d.streaming_available?'Quote stream adapter active; waiting for observed events.':'No verified tick-stream adapter for this provider.';if(ticks.length)$('ticks').innerHTML=ticks.map(t=>'<tr><td>'+t.symbol+'</td><td>'+t.market_type+'</td><td class="price">'+fmt(t.price)+'</td><td>'+new Date(t.time*1000).toLocaleString()+'</td></tr>').join('');};ws.onopen=()=>{ $('tickStatus').textContent='WebSocket connected; awaiting provider events.';window.marketHeartbeat=setInterval(()=>{if(ws.readyState===1)ws.send('ping')},5000);};ws.onclose=()=>{clearInterval(window.marketHeartbeat);$('tickStatus').textContent='Quote connection closed; reconnecting…';setTimeout(connectTicks,4000);};ws.onerror=()=>{$('tickStatus').textContent='Quote WebSocket connection error.';};}
$('pair').addEventListener('change',loadSnapshot);$('refresh').addEventListener('click',refreshPair);loadStatus();loadPairs();connectTicks();
</script></body></html>"""


@app.get("/live", response_class=HTMLResponse)
def live_ticks_page():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Quotex Live Ticks</title><style>
body{font:16px system-ui;background:#10131a;color:#f3f4f6;margin:24px auto;padding:0 14px;max-width:850px}section{background:#1c2230;padding:16px;border-radius:12px;margin:12px 0}small,.muted{color:#aab4c5}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #39445a}.price{font-variant-numeric:tabular-nums;font-weight:700}.pill{padding:5px 9px;border-radius:20px;background:#303b52}
</style></head><body><h1>Quotex Live Ticks</h1><p class='muted'>Read-only quote stream · OTC + normal symbols · no trades</p><section><span id='status' class='pill'>Connecting…</span><p id='source' class='muted'>Waiting for first quote…</p><table><thead><tr><th>Symbol</th><th>Market</th><th>Price</th><th>Time (local)</th></tr></thead><tbody id='rows'><tr><td colspan='4'>No ticks received yet.</td></tr></tbody></table></section><p class='muted'>This page sends a heartbeat to keep the Render WebSocket active. Data appears only when the configured provider sends actual quote events.</p>
<script>
const statusEl=document.getElementById('status'),rowsEl=document.getElementById('rows');
let ws,heartbeat;
function connect(){const scheme=location.protocol==='https:'?'wss':'ws';ws=new WebSocket(scheme+'://'+location.host+'/ws/market');
ws.onopen=()=>{statusEl.textContent='Connected';heartbeat=setInterval(()=>{if(ws&&ws.readyState===1)ws.send('ping')},5000)};
ws.onmessage=e=>{const d=JSON.parse(e.data);const ticks=d.ticks||[];if(!ticks.length){document.getElementById('source').textContent='WebSocket connected; waiting for provider tick events.';return}
document.getElementById('source').textContent='Last server update: '+new Date(d.server_time).toLocaleTimeString();
rowsEl.innerHTML=ticks.map(t=>'<tr><td>'+t.symbol+'</td><td>'+t.market_type+'</td><td class="price">'+Number(t.price).toPrecision(9)+'</td><td>'+new Date(t.time*1000).toLocaleTimeString()+'</td></tr>').join('')};
ws.onclose=()=>{statusEl.textContent='Disconnected · reconnecting';clearInterval(heartbeat);setTimeout(connect,3000)};
ws.onerror=()=>{statusEl.textContent='Connection error'};}
connect();
</script></body></html>"""


@app.get("/api/ticks")
def latest_ticks():
    """Return only genuine provider quote events; candle closes are never relabelled as ticks."""
    provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
    if provider != "quotexapi":
        return {
            "source": data_source_label(),
            "ticks": [],
            "streaming_available": False,
            "message": (
                "The selected provider exposes REST candle data in this integration, not a verified tick stream. "
                "No candle close is being presented as a live tick."
            ),
            "read_only": True,
        }
    from quotexapi_provider import get_ticks
    return {
        "source": data_source_label(),
        "ticks": get_ticks(),
        "streaming_available": True,
        "read_only": True,
    }


@app.websocket("/ws/market")
async def market_stream(websocket: WebSocket):
    """Push genuine quote snapshots only when the selected provider has a quote stream."""
    await websocket.accept()
    provider = os.getenv("MARKET_DATA_PROVIDER", "twelve_data").strip().lower()
    get_ticks = None
    if provider == "quotexapi":
        from quotexapi_provider import _ensure_connection, get_ticks as quotex_get_ticks
        _ensure_connection()
        get_ticks = quotex_get_ticks
    try:
        while True:
            ticks = get_ticks() if get_ticks else []
            await websocket.send_json({
                "type": "ticks",
                "ticks": ticks,
                "streaming_available": get_ticks is not None,
                "message": (
                    "Waiting for verified quote events."
                    if get_ticks is not None else
                    "Selected provider has no verified tick-stream adapter; use the candle endpoint for REST data."
                ),
                "source": data_source_label(),
                "server_time": datetime.now(timezone.utc).isoformat(),
                "read_only": True,
            })
            # Browser heartbeat counts as inbound WebSocket traffic on Render Free.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=12)
            except asyncio.TimeoutError:
                await websocket.close(code=1001, reason="Client heartbeat timeout")
                break
    except WebSocketDisconnect:
        pass


@app.get("/api/assets")
def assets():
    try:
        return {
            "source": data_source_label(),
            "assets": get_assets(),
            "market_type": "Quotex Demo subscriptions",
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except RuntimeError as exc:
        # The A11KSA security gate raises RuntimeError subclasses while the
        # adapter is intentionally disabled. Keep this a controlled 502.
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from None


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
            "source": data_source_label(),
            "market_type": result[-1].get("market_type", "provider-specific market") if result else "provider-specific market",
            "symbol": asset,
            "timeframe_seconds": timeframe_seconds,
            "count": len(result),
            "candles": result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except RuntimeError as exc:
        # Fail-closed provider gates are operational errors, not server crashes.
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from None


@app.get("/api/analysis")
def analysis(
    asset: str = Query("EUR/USD", min_length=3, max_length=40),
    timeframe_seconds: int = Query(60, ge=1),
    limit: int = Query(100, ge=30, le=5000),
):
    """Direct one-off analysis; disabled for the A11KSA demo candle-only mode."""
    if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa":
        raise HTTPException(status_code=404, detail="Analysis is disabled for A11KSA candle-only mode.")
    _validate_timeframe(timeframe_seconds)
    try:
        result = get_candles(asset, timeframe_seconds, limit)
        summary = analyze_candles(result)
        return {
            "source": data_source_label(),
            "market_type": result[-1].get("market_type", "provider-specific market") if result else "provider-specific market",
            "symbol": asset,
            "timeframe_seconds": timeframe_seconds,
            "count": len(result),
            "latest_candle": result[-1] if result else None,
            "recent_candles": result[-10:],
            "analysis": summary,
            "chart": build_chart_data(result),
            "disclaimer": "Heuristic educational summary, not financial advice or a guarantee. Standard forex data is not Quotex OTC pricing.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/api/watchlist")
def watchlist():
    """Configured multi-symbol watchlist and each symbol's cached status."""
    return get_watchlist()


@app.get("/api/latest")
def latest(asset: str | None = Query(None, min_length=3, max_length=40)):
    """Read a cached symbol snapshot without spending a provider API credit."""
    return get_snapshot(asset)


@app.post("/api/refresh")
async def refresh(asset: str | None = Query(None, min_length=3, max_length=40)):
    """Force one provider request for a selected configured symbol."""
    try:
        result = await asyncio.to_thread(refresh_snapshot, asset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except RuntimeError as exc:
        # Provider connection / candle-stream failures are expected operational
        # errors; return a useful 502 instead of an opaque HTTP 500 traceback.
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from None
    if not result.get("available"):
        raise HTTPException(status_code=502, detail=result.get("message", "Market refresh failed"))
    return result


@app.get("/api/history")
def history(limit: int = Query(50, ge=1, le=200)):
    if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa":
        raise HTTPException(status_code=404, detail="Signal history is disabled for A11KSA candle-only mode.")
    return {
        "summary": history_summary(),
        "records": get_history(limit),
        "market_type": "standard forex, not Quotex OTC",
        "note": "Outcomes compare a signal's entry close with the close after five candles; they are not actual trading returns. SQLite history on Render free storage can be lost on restart/redeploy.",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    if os.getenv("MARKET_DATA_PROVIDER", "").strip().lower() == "a11ksa":
        return RedirectResponse(url="/market", status_code=307)
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Quotex Demo Live Data & Signal Bot</title><script src='https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'></script><style>
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;max-width:1180px;margin:28px auto;padding:0 16px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:20px;margin:14px 0;overflow:hidden}small,.muted{color:#b6c0d1}.warn{color:#ffcc80}.signal{font-size:1.5rem;font-weight:750}button{background:#7c9cff;color:#10131a;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}button:disabled{opacity:.55}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.88rem}th,td{text-align:right;padding:8px;border-bottom:1px solid #3a4355;white-space:nowrap}th:first-child,td:first-child{text-align:left}.tablewrap{overflow-x:auto}.chart{height:340px;width:100%}.macdchart{height:170px;width:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.metric{background:#121722;border-radius:10px;padding:12px}.metric strong{display:block;font-size:1.05rem;margin-top:4px}.pill{display:inline-block;background:#303b52;padding:4px 8px;border-radius:999px;font-size:.8rem}.history-good{color:#73d6ae}.history-bad{color:#ff8c8c}@media(max-width:600px){.chart{height:290px}section{padding:14px}}
</style></head><body>
<h1>Quotex Live Data &amp; Signal Bot</h1><p>1-minute candles · Chart time: IST · 1m/2m expiry hint · Read-only signals · No automatic trades</p>
<section><h2>Data provider</h2><p id='providerInfo'>ChipaDevTeam QuotexAPI · Quotex account selected in Render</p><small>Data is read from the selected Quotex account session through the unofficial ChipaDevTeam QuotexAPI library. Only verified OHLC events are analyzed; no orders are placed.</small></section>
<section><h2>Connection &amp; schedule</h2><p id='botStatus' class='pill'>Bot status: checking…</p><p><button id='botToggle'>Turn bot ON</button></p><p class='muted'>OFF pauses automatic provider refreshes. Manual refresh still uses an API request.</p><p id='status'>Checking API key…</p><p id='updated' class='muted'>Waiting for first scheduled refresh…</p><p id='telegram' class='muted'>Telegram setup status will appear after refresh.</p><label for='assetSelect'>Watchlist pair</label> <select id='assetSelect' style='margin:8px;background:#121722;color:#f3f4f6;border:1px solid #46516a;border-radius:8px;padding:8px'><option>Loading watchlist…</option></select><p id='watchlistInfo' class='muted'>One symbol is scanned per interval to protect the free API quota.</p><span class='pill'>Scheduled refresh: minimum 5 minutes</span></section>
<section><h2>Signal summary</h2><p id='signal' class='signal'>WAIT · Waiting for data</p><p id='reason' class='muted'>Waiting for first scheduled refresh.</p><p id='expiry' class='pill'>Expiry suggestion: waiting for data</p><p id='candleWindow' class='muted'>Candle status: waiting for data</p><div class='grid'><div class='metric'>RSI (14)<strong id='rsi'>—</strong></div><div class='metric'>MACD histogram<strong id='macd'>—</strong></div><div class='metric'>Bollinger upper<strong id='bbupper'>—</strong></div><div class='metric'>Bollinger middle<strong id='bbmiddle'>—</strong></div><div class='metric'>Bollinger lower<strong id='bblower'>—</strong></div><div class='metric'>Support / resistance (20)<strong id='sr'>—</strong></div></div><p style='margin-top:14px'><button id='refresh'>Refresh selected pair (uses 1 request)</button></p><p class='warn'>CALL / PUT / WAIT are heuristic labels, not validated predictions, financial advice, or guarantees.</p></section>
<section><h2>Live candlestick chart</h2><p class='muted'>Selected pair · 1-minute · Chart times shown in India Standard Time (IST). Candles with EMA(9), EMA(21), Bollinger Bands; MACD below. Data source follows MARKET_DATA_PROVIDER.</p><div id='priceChart' class='chart'></div><h3>MACD (12, 26, 9)</h3><div id='macdChart' class='macdchart'></div></section>
<section><h2>Latest OHLC candles</h2><p id='candlestatus' class='muted'>Waiting for data.</p><div class='tablewrap'><table><thead><tr><th>Time (IST)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody id='candles'><tr><td colspan='5'>No data returned yet.</td></tr></tbody></table></div></section>
<section><h2>Signal history &amp; outcome comparison</h2><p id='historySummary' class='muted'>Waiting for history…</p><small>Outcomes compare entry close with the close after five candles. This is a simplified historical comparison, not actual trading results. History on Render free ephemeral storage can be lost after restart/redeploy.</small><div class='tablewrap' style='margin-top:12px'><table><thead><tr><th>Signal time (UTC)</th><th>Signal</th><th>Entry</th><th>Exit</th><th>Outcome</th><th>Change %</th></tr></thead><tbody id='historyRows'><tr><td colspan='6'>No history yet.</td></tr></tbody></table></div></section>
<script>
const fmt=n=>n===null||n===undefined||!Number.isFinite(Number(n))?'—':Number(n).toFixed(5);
let priceChart=null,macdChart=null,series={};
function initCharts(){if(!window.LightweightCharts){document.getElementById('priceChart').textContent='Chart library could not load. Check internet access and refresh.';return;}const LC=window.LightweightCharts;const common={layout:{background:{color:'#1c2230'},textColor:'#d6deeb'},grid:{vertLines:{color:'#30384a'},horzLines:{color:'#30384a'}},rightPriceScale:{borderColor:'#46516a'},timeScale:{borderColor:'#46516a',timeVisible:true,secondsVisible:false,tickMarkFormatter:(time)=>{if(typeof time==='number')return new Date(time*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hour12:false});return String(time)}},crosshair:{mode:LC.CrosshairMode.Normal}};priceChart=LC.createChart(document.getElementById('priceChart'),{...common,height:340});series.candle=priceChart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});series.ema9=priceChart.addLineSeries({color:'#f7c948',lineWidth:2,title:'EMA 9'});series.ema21=priceChart.addLineSeries({color:'#8b9cff',lineWidth:2,title:'EMA 21'});series.bbUpper=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,title:'BB Upper'});series.bbMiddle=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,lineStyle:2,title:'BB Middle'});series.bbLower=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,title:'BB Lower'});series.support20=priceChart.addLineSeries({color:'#26a69a',lineWidth:1,lineStyle:2,title:'Support 20'});series.resistance20=priceChart.addLineSeries({color:'#ef5350',lineWidth:1,lineStyle:2,title:'Resistance 20'});macdChart=LC.createChart(document.getElementById('macdChart'),{...common,height:170});series.macdHist=macdChart.addHistogramSeries({base:0,priceFormat:{type:'price',precision:6,minMove:0.000001},title:'Histogram'});series.macd=macdChart.addLineSeries({color:'#5aa9ff',lineWidth:2,title:'MACD'});series.macdSignal=macdChart.addLineSeries({color:'#ffb454',lineWidth:2,title:'Signal'});window.addEventListener('resize',()=>{priceChart.applyOptions({width:document.getElementById('priceChart').clientWidth});macdChart.applyOptions({width:document.getElementById('macdChart').clientWidth})});}
function setLine(s,arr){if(s)s.setData(arr||[]);}
function updateSnapshot(d){if(!d||!d.available){document.getElementById('candlestatus').textContent=(d&&d.message)||'Waiting for first scheduled candle refresh.';return;}const a=d.analysis,c=d.chart;document.getElementById('signal').textContent=a.signal;document.getElementById('reason').textContent=a.reason;document.getElementById('expiry').textContent='Expiry suggestion: '+(a.expiry_recommendation_minutes?a.expiry_recommendation_minutes+' minute(s)':'WAIT / no expiry')+' · Strength: '+(a.signal_strength||'N/A')+' · '+(a.expiry_reason||'');document.getElementById('candleWindow').textContent='Candle status: '+(d.candle_status||'provider-update-dependent')+' · Candle age: '+(d.candle_age_seconds??'—')+'s. REST refresh is not tick-by-tick.';document.getElementById('rsi').textContent=a.rsi_14??'N/A';document.getElementById('macd').textContent=a.macd_histogram??'N/A';document.getElementById('bbupper').textContent=fmt(a.bollinger_upper);document.getElementById('bbmiddle').textContent=fmt(a.bollinger_middle);document.getElementById('bblower').textContent=fmt(a.bollinger_lower);document.getElementById('sr').textContent=fmt(a.support_20)+' / '+fmt(a.resistance_20);document.getElementById('updated').textContent='Last provider refresh: '+(d.updated_at||'unknown')+' · Next refresh interval: '+Math.round((d.refresh_interval_seconds||300)/60)+' min';document.getElementById('telegram').textContent=d.telegram_configured?'Telegram credentials configured; alerts send on initial signal and signal changes.':'Telegram alerts not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Render Environment.';document.getElementById('candlestatus').textContent='Received '+d.count+' candles for '+(d.symbol||'selected pair')+' from '+(d.source||'configured provider')+'.';const rows=[...(d.recent_candles||[])].reverse().map(x=>'<tr><td>'+new Date(x.time*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+'</td><td>'+fmt(x.open)+'</td><td>'+fmt(x.high)+'</td><td>'+fmt(x.low)+'</td><td>'+fmt(x.close)+'</td></tr>').join('');document.getElementById('candles').innerHTML=rows||'<tr><td colspan="5">No candles returned.</td></tr>';if(priceChart&&c){setLine(series.candle,c.candles);setLine(series.ema9,c.ema9);setLine(series.ema21,c.ema21);setLine(series.bbUpper,c.bbUpper);setLine(series.bbMiddle,c.bbMiddle);setLine(series.bbLower,c.bbLower);setLine(series.support20,c.support20);setLine(series.resistance20,c.resistance20);setLine(series.macd,c.macd);setLine(series.macdSignal,c.macdSignal);setLine(series.macdHist,c.macdHistogram);priceChart.timeScale().fitContent();macdChart.timeScale().fitContent();}}
let watchlistSymbols=[];
async function loadWatchlist(){try{const r=await fetch('/api/watchlist',{cache:'no-store'});const d=await r.json();watchlistSymbols=d.symbols||[];const select=document.getElementById('assetSelect');const current=select.value;select.innerHTML=watchlistSymbols.map(s=>'<option value="'+s+'">'+s+'</option>').join('');if(watchlistSymbols.includes(current))select.value=current;else if(watchlistSymbols.length)select.value=watchlistSymbols[0];document.getElementById('watchlistInfo').textContent='Configured pairs: '+watchlistSymbols.length+' · Approx refresh per pair: '+d.estimated_minutes_per_symbol+' minutes. Pair names depend on the selected provider.';await pollLatest();}catch(e){document.getElementById('watchlistInfo').textContent='Could not load watchlist: '+e.message;}}
async function pollLatest(){try{const symbol=document.getElementById('assetSelect').value;const url='/api/latest'+(symbol?'?asset='+encodeURIComponent(symbol):'');const r=await fetch(url,{cache:'no-store'});const d=await r.json();updateSnapshot(d);}catch(e){document.getElementById('candlestatus').textContent='Could not read cached data: '+e.message;}}
async function pollHistory(){try{const r=await fetch('/api/history?limit=20',{cache:'no-store'});const d=await r.json();const s=d.summary;document.getElementById('historySummary').textContent='Recorded: '+s.total+' · Wins: '+s.wins+' · Losses: '+s.losses+' · Flat: '+s.flat+' · Skipped WAIT: '+s.skipped+' · Pending: '+s.pending+' · Scored win rate: '+(s.scored_win_rate_pct===null?'N/A':s.scored_win_rate_pct+'%');document.getElementById('historyRows').innerHTML=(d.records||[]).map(x=>'<tr><td>'+new Date(x.signal_time*1000).toISOString().replace('T',' ').slice(0,19)+'</td><td>'+x.signal+'</td><td>'+fmt(x.entry_price)+'</td><td>'+fmt(x.exit_price)+'</td><td class="'+(x.outcome==='WIN'?'history-good':x.outcome==='LOSS'?'history-bad':'')+'">'+x.outcome+'</td><td>'+(x.price_change_pct===null?'—':Number(x.price_change_pct).toFixed(5)+'%')+'</td></tr>').join('')||'<tr><td colspan="6">No history yet; it will populate after scheduled refresh.</td></tr>';}catch(e){document.getElementById('historySummary').textContent='History unavailable: '+e.message;}}
async function refreshSelectedPair(silent=false){const b=document.getElementById('refresh');if(b.disabled&&!silent)return;if(!silent){b.disabled=true;b.textContent='Refreshing…';}try{const symbol=document.getElementById('assetSelect').value;const url='/api/refresh'+(symbol?'?asset='+encodeURIComponent(symbol):'');const r=await fetch(url,{method:'POST',cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Refresh failed');updateSnapshot(d);await pollHistory();}catch(e){document.getElementById('candlestatus').textContent='Selected-pair refresh failed: '+e.message;}finally{if(!silent){b.disabled=false;b.textContent='Refresh selected pair (uses 1 request)';}}}
async function manualRefresh(){return refreshSelectedPair(false);}
let selectedRefreshTimer=null;
let botIsOn=false;
let manualRefreshOnly=false;
async function syncBotState(){try{const r=await fetch('/api/bot',{cache:'no-store'});const d=await r.json();botIsOn=!!d.enabled;document.getElementById('botStatus').textContent='Bot status: '+(botIsOn?'ON':'OFF');document.getElementById('botToggle').textContent=botIsOn?'Turn bot OFF':'Turn bot ON';}catch(e){document.getElementById('botStatus').textContent='Bot status unavailable';}}
async function toggleBot(){const action=botIsOn?'off':'on';const r=await fetch('/api/bot/'+action,{method:'POST'});const d=await r.json();botIsOn=!!d.enabled;document.getElementById('botStatus').textContent='Bot status: '+(botIsOn?'ON':'OFF');document.getElementById('botToggle').textContent=botIsOn?'Turn bot OFF':'Turn bot ON';if(botIsOn&&!manualRefreshOnly)await refreshSelectedPair(true);}
function startSelectedPairRefresh(){if(selectedRefreshTimer)clearInterval(selectedRefreshTimer);selectedRefreshTimer=setInterval(()=>{if(botIsOn&&!manualRefreshOnly)refreshSelectedPair(true)},60000);if(!manualRefreshOnly)document.getElementById('watchlistInfo').textContent='Selected pair auto-refresh: every 1 minute while bot is ON; background watchlist pauses when OFF.';}
async function statusCheck(){try{const r=await fetch('/api/status');const d=await r.json();manualRefreshOnly=!!d.manual_refresh_only;document.getElementById('status').textContent=d.message;document.getElementById('providerInfo').textContent='Selected provider: '+(d.source||'unknown')+' · Market: '+(d.market_type||'provider-specific market')+(d.affiliation?' · '+d.affiliation:'');if(manualRefreshOnly){document.getElementById('watchlistInfo').textContent='OTCharts free tier: automatic refresh is disabled to preserve the 200-request first-month allowance. Use manual refresh for one pair at a time.';document.getElementById('botToggle').disabled=true;document.getElementById('botStatus').textContent='Manual refresh only (free API tier)';}}catch(e){document.getElementById('status').textContent='API status unavailable';}}
initCharts();statusCheck();syncBotState();loadWatchlist();pollHistory();document.getElementById('botToggle').addEventListener('click',toggleBot);document.getElementById('refresh').addEventListener('click',manualRefresh);document.getElementById('assetSelect').addEventListener('change',async()=>{await pollLatest();if(botIsOn&&!manualRefreshOnly)await refreshSelectedPair(true);});startSelectedPairRefresh();setInterval(pollLatest,30000);setInterval(pollHistory,60000);
</script></body></html>"""
