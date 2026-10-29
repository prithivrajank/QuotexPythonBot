from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from data_collector import MarketDataError, connection_status, get_assets, get_candles
from runtime import get_snapshot, refresh_interval_seconds, refresh_snapshot, scheduled_refresh_loop
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


app = FastAPI(title="Standard Forex Data & Signal Bot", version="0.5.0", lifespan=lifespan)


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
    """Direct one-off analysis; makes one provider candle request."""
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
            "chart": build_chart_data(result),
            "disclaimer": "Heuristic educational summary, not financial advice or a guarantee. Standard forex data is not Quotex OTC pricing.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@app.get("/api/latest")
def latest():
    """Read the scheduled cache; this endpoint does not spend a provider API credit."""
    return get_snapshot()


@app.post("/api/refresh")
async def refresh():
    """Force one provider request. Use sparingly on the free API plan."""
    result = await asyncio.to_thread(refresh_snapshot)
    if not result.get("available"):
        raise HTTPException(status_code=502, detail=result.get("message", "Market refresh failed"))
    return result


@app.get("/api/history")
def history(limit: int = Query(50, ge=1, le=200)):
    return {
        "summary": history_summary(),
        "records": get_history(limit),
        "market_type": "standard forex, not Quotex OTC",
        "note": "Outcomes compare a signal's entry close with the close after five candles; they are not actual trading returns. SQLite history on Render free storage can be lost on restart/redeploy.",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Forex Live Chart & Signal History</title><script src='https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js'></script><style>
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;max-width:1180px;margin:28px auto;padding:0 16px;background:#10131a;color:#f3f4f6}section{background:#1c2230;border-radius:14px;padding:20px;margin:14px 0;overflow:hidden}small,.muted{color:#b6c0d1}.warn{color:#ffcc80}.signal{font-size:1.5rem;font-weight:750}button{background:#7c9cff;color:#10131a;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}button:disabled{opacity:.55}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.88rem}th,td{text-align:right;padding:8px;border-bottom:1px solid #3a4355;white-space:nowrap}th:first-child,td:first-child{text-align:left}.tablewrap{overflow-x:auto}.chart{height:340px;width:100%}.macdchart{height:170px;width:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.metric{background:#121722;border-radius:10px;padding:12px}.metric strong{display:block;font-size:1.05rem;margin-top:4px}.pill{display:inline-block;background:#303b52;padding:4px 8px;border-radius:999px;font-size:.8rem}.history-good{color:#73d6ae}.history-bad{color:#ff8c8c}@media(max-width:600px){.chart{height:290px}section{padding:14px}}
</style></head><body>
<h1>Forex Live Data &amp; Signal Bot</h1><p>Scheduled read-only market data · No automatic trades</p>
<section><h2>Data provider</h2><p>Twelve Data — independent standard forex market-data API. Not affiliated with, endorsed by, or partnered with Quotex. <strong>This is not a Quotex OTC feed.</strong></p><small>Standard forex prices may differ from Quotex OTC/synthetic prices. The app requests one candle batch every five minutes while the service is awake; this is about 288 requests/day before manual requests.</small></section>
<section><h2>Connection &amp; schedule</h2><p id='status'>Checking API key…</p><p id='updated' class='muted'>Waiting for first scheduled refresh…</p><p id='telegram' class='muted'>Telegram setup status will appear after refresh.</p><span class='pill'>Scheduled refresh: minimum 5 minutes</span></section>
<section><h2>Signal summary</h2><p id='signal' class='signal'>WAIT · Waiting for data</p><p id='reason' class='muted'>Waiting for first scheduled refresh.</p><div class='grid'><div class='metric'>RSI (14)<strong id='rsi'>—</strong></div><div class='metric'>MACD histogram<strong id='macd'>—</strong></div><div class='metric'>Bollinger upper<strong id='bbupper'>—</strong></div><div class='metric'>Bollinger middle<strong id='bbmiddle'>—</strong></div><div class='metric'>Bollinger lower<strong id='bblower'>—</strong></div><div class='metric'>Support / resistance (20)<strong id='sr'>—</strong></div></div><p style='margin-top:14px'><button id='refresh'>Refresh now (uses 1 request)</button></p><p class='warn'>CALL / PUT / WAIT are heuristic labels, not validated predictions, financial advice, or guarantees.</p></section>
<section><h2>Live candlestick chart</h2><p class='muted'>EUR/USD · 1-minute · Candles with EMA(9), EMA(21), Bollinger Bands; MACD below. Auto-updates from cached data every 30 seconds and provider data every five minutes while service is awake.</p><div id='priceChart' class='chart'></div><h3>MACD (12, 26, 9)</h3><div id='macdChart' class='macdchart'></div></section>
<section><h2>Latest OHLC candles</h2><p id='candlestatus' class='muted'>Waiting for data.</p><div class='tablewrap'><table><thead><tr><th>Time (UTC)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th></tr></thead><tbody id='candles'><tr><td colspan='5'>No data returned yet.</td></tr></tbody></table></div></section>
<section><h2>Signal history &amp; outcome comparison</h2><p id='historySummary' class='muted'>Waiting for history…</p><small>Outcomes compare entry close with the close after five candles. This is a simplified historical comparison, not actual trading results. History on Render free ephemeral storage can be lost after restart/redeploy.</small><div class='tablewrap' style='margin-top:12px'><table><thead><tr><th>Signal time (UTC)</th><th>Signal</th><th>Entry</th><th>Exit</th><th>Outcome</th><th>Change %</th></tr></thead><tbody id='historyRows'><tr><td colspan='6'>No history yet.</td></tr></tbody></table></div></section>
<script>
const fmt=n=>n===null||n===undefined||!Number.isFinite(Number(n))?'—':Number(n).toFixed(5);
let priceChart=null,macdChart=null,series={};
function initCharts(){if(!window.LightweightCharts){document.getElementById('priceChart').textContent='Chart library could not load. Check internet access and refresh.';return;}const LC=window.LightweightCharts;const common={layout:{background:{color:'#1c2230'},textColor:'#d6deeb'},grid:{vertLines:{color:'#30384a'},horzLines:{color:'#30384a'}},rightPriceScale:{borderColor:'#46516a'},timeScale:{borderColor:'#46516a',timeVisible:true,secondsVisible:false},crosshair:{mode:LC.CrosshairMode.Normal}};priceChart=LC.createChart(document.getElementById('priceChart'),{...common,height:340});series.candle=priceChart.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});series.ema9=priceChart.addLineSeries({color:'#f7c948',lineWidth:2,title:'EMA 9'});series.ema21=priceChart.addLineSeries({color:'#8b9cff',lineWidth:2,title:'EMA 21'});series.bbUpper=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,title:'BB Upper'});series.bbMiddle=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,lineStyle:2,title:'BB Middle'});series.bbLower=priceChart.addLineSeries({color:'#b08cff',lineWidth:1,title:'BB Lower'});macdChart=LC.createChart(document.getElementById('macdChart'),{...common,height:170});series.macdHist=macdChart.addHistogramSeries({base:0,priceFormat:{type:'price',precision:6,minMove:0.000001},title:'Histogram'});series.macd=macdChart.addLineSeries({color:'#5aa9ff',lineWidth:2,title:'MACD'});series.macdSignal=macdChart.addLineSeries({color:'#ffb454',lineWidth:2,title:'Signal'});priceChart.timeScale().subscribeVisibleLogicalRangeChange(range=>{if(range)macdChart.timeScale().setVisibleLogicalRange(range)});macdChart.timeScale().subscribeVisibleLogicalRangeChange(range=>{if(range)priceChart.timeScale().setVisibleLogicalRange(range)});window.addEventListener('resize',()=>{priceChart.applyOptions({width:document.getElementById('priceChart').clientWidth});macdChart.applyOptions({width:document.getElementById('macdChart').clientWidth})});}
function setLine(s,arr){if(s)s.setData(arr||[]);}
function updateSnapshot(d){if(!d||!d.available){document.getElementById('candlestatus').textContent=(d&&d.message)||'Waiting for first scheduled candle refresh.';return;}const a=d.analysis,c=d.chart;document.getElementById('signal').textContent=a.signal;document.getElementById('reason').textContent=a.reason;document.getElementById('rsi').textContent=a.rsi_14??'N/A';document.getElementById('macd').textContent=a.macd_histogram??'N/A';document.getElementById('bbupper').textContent=fmt(a.bollinger_upper);document.getElementById('bbmiddle').textContent=fmt(a.bollinger_middle);document.getElementById('bblower').textContent=fmt(a.bollinger_lower);document.getElementById('sr').textContent=fmt(a.support_20)+' / '+fmt(a.resistance_20);document.getElementById('updated').textContent='Last provider refresh: '+(d.updated_at||'unknown')+' · Next refresh interval: '+Math.round((d.refresh_interval_seconds||300)/60)+' min';document.getElementById('telegram').textContent=d.telegram_configured?'Telegram credentials configured; alerts send on initial signal and signal changes.':'Telegram alerts not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Render Environment.';document.getElementById('candlestatus').textContent='Received '+d.count+' real standard-forex candles from Twelve Data.';const rows=[...(d.recent_candles||[])].reverse().map(x=>'<tr><td>'+new Date(x.time*1000).toISOString().replace('T',' ').slice(0,19)+'</td><td>'+fmt(x.open)+'</td><td>'+fmt(x.high)+'</td><td>'+fmt(x.low)+'</td><td>'+fmt(x.close)+'</td></tr>').join('');document.getElementById('candles').innerHTML=rows||'<tr><td colspan="5">No candles returned.</td></tr>';if(priceChart&&c){setLine(series.candle,c.candles);setLine(series.ema9,c.ema9);setLine(series.ema21,c.ema21);setLine(series.bbUpper,c.bbUpper);setLine(series.bbMiddle,c.bbMiddle);setLine(series.bbLower,c.bbLower);setLine(series.macd,c.macd);setLine(series.macdSignal,c.macdSignal);setLine(series.macdHist,c.macdHistogram);priceChart.timeScale().fitContent();macdChart.timeScale().fitContent();}}
async function pollLatest(){try{const r=await fetch('/api/latest',{cache:'no-store'});const d=await r.json();updateSnapshot(d);}catch(e){document.getElementById('candlestatus').textContent='Could not read cached data: '+e.message;}}
async function pollHistory(){try{const r=await fetch('/api/history?limit=20',{cache:'no-store'});const d=await r.json();const s=d.summary;document.getElementById('historySummary').textContent='Recorded: '+s.total+' · Wins: '+s.wins+' · Losses: '+s.losses+' · Flat: '+s.flat+' · Skipped WAIT: '+s.skipped+' · Pending: '+s.pending+' · Scored win rate: '+(s.scored_win_rate_pct===null?'N/A':s.scored_win_rate_pct+'%');document.getElementById('historyRows').innerHTML=(d.records||[]).map(x=>'<tr><td>'+new Date(x.signal_time*1000).toISOString().replace('T',' ').slice(0,19)+'</td><td>'+x.signal+'</td><td>'+fmt(x.entry_price)+'</td><td>'+fmt(x.exit_price)+'</td><td class="'+(x.outcome==='WIN'?'history-good':x.outcome==='LOSS'?'history-bad':'')+'">'+x.outcome+'</td><td>'+(x.price_change_pct===null?'—':Number(x.price_change_pct).toFixed(5)+'%')+'</td></tr>').join('')||'<tr><td colspan="6">No history yet; it will populate after scheduled refresh.</td></tr>';}catch(e){document.getElementById('historySummary').textContent='History unavailable: '+e.message;}}
async function manualRefresh(){const b=document.getElementById('refresh');b.disabled=true;b.textContent='Refreshing…';try{const r=await fetch('/api/refresh',{method:'POST'});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Refresh failed');updateSnapshot(d);await pollHistory();}catch(e){document.getElementById('candlestatus').textContent=e.message;}finally{b.disabled=false;b.textContent='Refresh now (uses 1 request)';}}
async function statusCheck(){try{const r=await fetch('/api/status');const d=await r.json();document.getElementById('status').textContent=d.message;}catch(e){document.getElementById('status').textContent='API status unavailable';}}
initCharts();statusCheck();pollLatest();pollHistory();document.getElementById('refresh').addEventListener('click',manualRefresh);setInterval(pollLatest,30000);setInterval(pollHistory,60000);
</script></body></html>"""
