import asyncio
import base64
import csv
import html
import hmac
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse

try:
    from pyquotex.stable_api import Quotex
except ImportError:
    Quotex = None

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")
PAIRS = [x.strip() for x in os.getenv(
    "OTC_PAIRS", "EURUSD_otc,USDIDR_otc,USDJPY_otc,AUDCHF_otc"
).split(",") if x.strip()]
POLL_SECONDS = max(30, int(os.getenv("POLL_SECONDS", "60")))
MAX_DAILY_SIGNALS = max(1, int(os.getenv("MAX_DAILY_SIGNALS", "15")))
MAX_CANDLE_AGE_SECONDS = 180
CANDLE_SECONDS = 60
EXPIRY_MINUTES = 1
CANDLES_CSV = ROOT / "candles.csv"
SIGNALS_CSV = ROOT / "signals.csv"

state = {
    "status": "Starting", "connected": False, "candle_feed_verified": False,
    "last_poll": None, "last_error": None, "pairs": PAIRS,
    "latest": {}, "signals": [], "strategy": "EMA trend + engulfing + volatility filter",
}
stop_event = asyncio.Event()
client = None
saved_candle_keys = set()
analyzed_keys = set()


def utc_now():
    return datetime.now(timezone.utc)


def ist_now():
    return datetime.now(IST)


def append_csv(path, headers, row):
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        if not exists or path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)


def normalize_candle(raw):
    if not isinstance(raw, dict):
        return None
    stamp = raw.get("time", raw.get("timestamp", raw.get("at")))
    try:
        stamp = float(stamp)
        if stamp > 10_000_000_000:
            stamp /= 1000
        dt = datetime.fromtimestamp(stamp, tz=timezone.utc)
        op = float(raw.get("open", raw.get("open_price")))
        hi = float(raw.get("high", raw.get("high_price")))
        lo = float(raw.get("low", raw.get("low_price")))
        cl = float(raw.get("close", raw.get("close_price")))
    except (TypeError, ValueError, OSError):
        return None
    if not all(map(lambda x: x == x and abs(x) != float("inf"), (op, hi, lo, cl))):
        return None
    if min(op, hi, lo, cl) <= 0 or hi < max(op, cl) or lo > min(op, cl) or hi < lo:
        return None
    return {"time": int(stamp), "time_utc": dt.isoformat(timespec="seconds"),
            "open": op, "high": hi, "low": lo, "close": cl}


def parse_candles(response):
    if isinstance(response, dict):
        response = response.get("candles", response.get("data", []))
    if not isinstance(response, (list, tuple)):
        return []
    by_time = {}
    for raw in response:
        item = normalize_candle(raw)
        if item:
            by_time[item["time"]] = item
    return [by_time[t] for t in sorted(by_time)]


def candle_color(c):
    if c["close"] > c["open"]:
        return "GREEN"
    if c["close"] < c["open"]:
        return "RED"
    return "DOJI"


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def analyze_strategy(candles):
    """Conservative, experimental filter. Not a proven predictive model."""
    if len(candles) < 20:
        return {"signal": "WAIT", "reason": "Need at least 20 closed candles for trend context."}

    # Caller supplies only closed candles.
    closes = [c["close"] for c in candles]
    fast = ema(closes[-20:], 5)
    slow = ema(closes[-20:], 13)
    if fast is None or slow is None:
        return {"signal": "WAIT", "reason": "Not enough candles for EMA calculation."}

    previous, last = candles[-2], candles[-1]
    colors = (candle_color(previous), candle_color(last))
    if "DOJI" in colors:
        return {"signal": "WAIT", "reason": "Doji detected; candle direction is unclear."}

    # Require a real body-over-body engulfing pattern.
    bullish_engulf = (
        colors[0] == "RED" and colors[1] == "GREEN"
        and last["open"] <= previous["close"]
        and last["close"] >= previous["open"]
    )
    bearish_engulf = (
        colors[0] == "GREEN" and colors[1] == "RED"
        and last["open"] >= previous["close"]
        and last["close"] <= previous["open"]
    )

    ranges = [c["high"] - c["low"] for c in candles[-14:]]
    avg_range = sum(ranges[:-1]) / max(1, len(ranges) - 1)
    current_range = ranges[-1]
    if avg_range <= 0 or current_range < avg_range * 0.5:
        return {"signal": "WAIT", "reason": "Low-range candle; volatility filter not met."}
    if current_range > avg_range * 2.5:
        return {"signal": "WAIT", "reason": "Abnormally large candle; avoid chasing a spike."}

    if bullish_engulf and fast > slow and last["close"] > fast:
        return {
            "signal": "CALL", "pattern": "Bullish engulfing + EMA trend",
            "reason": "Bullish engulfing, fast EMA above slow EMA, close above fast EMA.",
            "score": 3,
        }
    if bearish_engulf and fast < slow and last["close"] < fast:
        return {
            "signal": "PUT", "pattern": "Bearish engulfing + EMA trend",
            "reason": "Bearish engulfing, fast EMA below slow EMA, close below fast EMA.",
            "score": 3,
        }
    return {"signal": "WAIT", "reason": "Trend, engulfing pattern, and close did not agree."}


def save_candle(pair, c):
    append_csv(CANDLES_CSV,
        ["pair", "time_utc", "time_unix", "open", "high", "low", "close"],
        {"pair": pair, "time_utc": c["time_utc"], "time_unix": c["time"],
         "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]})


def save_signal(s):
    append_csv(SIGNALS_CSV,
        ["created_at_ist", "pair", "direction", "expiry_minutes", "pattern",
         "reason", "score", "candle_time_utc", "status"],
        {"created_at_ist": s["created_at"], "pair": s["pair"],
         "direction": s["direction"], "expiry_minutes": s["expiry_minutes"],
         "pattern": s["pattern"], "reason": s["reason"], "score": s["score"],
         "candle_time_utc": s["candle_time_utc"], "status": "UNVALIDATED"})


def count_today():
    today = ist_now().date().isoformat()
    return sum(1 for s in state["signals"] if s["created_at"].startswith(today))


def telegram_send(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message}, timeout=10
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        state["last_error"] = f"Telegram: {exc}"


async def collector():
    global client
    if Quotex is None:
        state["status"] = "pyquotex package is unavailable"
        state["last_error"] = "Run: python -m pip install -r requirements.txt"
        return
    email = os.getenv("QUOTEX_EMAIL")
    password = os.getenv("QUOTEX_PASSWORD")
    if not email or not password:
        state["status"] = "Credentials not configured"
        state["last_error"] = "Set QUOTEX_EMAIL and QUOTEX_PASSWORD in CMD."
        return

    client = Quotex(email=email, password=password, lang="en",
                    host=os.getenv("QUOTEX_HOST", "quotex.com"))
    client.account_is_demo = 1
    try:
        state["status"] = "Connecting to demo account"
        ok, detail = await client.connect()
        if not ok:
            state["status"] = "Connection failed"
            state["last_error"] = str(detail)
            return
        state["connected"] = True

        while not stop_event.is_set():
            state["last_poll"] = ist_now().isoformat(timespec="seconds")
            for pair in PAIRS:
                try:
                    raw = await client.get_candles(pair, time.time(), 3600, CANDLE_SECONDS)
                    candles = parse_candles(raw)
                    if not candles:
                        state["latest"][pair] = {"status": "NO_CANDLES", "count": 0}
                        continue

                    now_ts = utc_now().timestamp()
                    latest = candles[-1]
                    age = now_ts - latest["time"]
                    if age < -60:
                        freshness = "FUTURE_TIMESTAMP"
                    elif age < 0 or age > MAX_CANDLE_AGE_SECONDS:
                        freshness = "STALE"
                    else:
                        freshness = "FRESH"

                    # Do not analyse the currently forming candle. A 60-second
                    # candle is considered closed only after its start + 60 sec.
                    closed = [c for c in candles if c["time"] + CANDLE_SECONDS <= now_ts]
                    state["latest"][pair] = {
                        "status": freshness, "count": len(candles),
                        "closed_count": len(closed),
                        "latest_candle_utc": latest["time_utc"],
                        "age_seconds": round(age, 1), "close": latest["close"],
                        "analysis_status": "WAITING_FOR_CLOSED_CANDLE",
                    }

                    for c in candles:
                        key = (pair, c["time"])
                        if key not in saved_candle_keys:
                            save_candle(pair, c)
                            saved_candle_keys.add(key)

                    if freshness != "FRESH" or len(closed) < 20:
                        state["latest"][pair]["analysis_status"] = (
                            "STALE_FEED" if freshness != "FRESH" else "NEED_20_CLOSED_CANDLES"
                        )
                        continue

                    signal_candle = closed[-1]
                    signal_key = (pair, signal_candle["time"])
                    if signal_key in analyzed_keys:
                        continue
                    analyzed_keys.add(signal_key)

                    if count_today() >= MAX_DAILY_SIGNALS:
                        state["latest"][pair]["analysis_status"] = "DAILY_SIGNAL_LIMIT"
                        continue

                    result = analyze_strategy(closed[-30:])
                    state["latest"][pair]["analysis_status"] = result["signal"]
                    state["latest"][pair]["analysis_reason"] = result["reason"]
                    if result["signal"] == "WAIT":
                        continue

                    signal = {
                        "created_at": ist_now().isoformat(timespec="seconds"),
                        "pair": pair, "direction": result["signal"],
                        "expiry_minutes": EXPIRY_MINUTES,
                        "pattern": result["pattern"], "reason": result["reason"],
                        "score": result["score"], "candle_time_utc": signal_candle["time_utc"],
                        "accuracy": "NOT VALIDATED", "status": "PENDING_REVIEW",
                    }
                    state["signals"].insert(0, signal)
                    state["signals"] = state["signals"][:100]
                    save_signal(signal)
                    telegram_send(
                        "EXPERIMENTAL OTC PAPER SIGNAL\n"
                        f"Pair: {pair}\nDirection: {signal['direction']}\n"
                        f"Expiry assumption: {EXPIRY_MINUTES} minute(s)\n"
                        f"Pattern: {signal['pattern']}\nReason: {signal['reason']}\n"
                        f"Closed candle UTC: {signal['candle_time_utc']}\n"
                        "Not a win probability. Accuracy not validated; paper testing only."
                    )
                except Exception as exc:
                    state["latest"][pair] = {"status": "FETCH_ERROR", "error": f"{type(exc).__name__}: {exc}"}
            state["candle_feed_verified"] = any(
                x.get("status") == "FRESH" for x in state["latest"].values()
            )
            state["status"] = (
                "Collecting candles" if state["candle_feed_verified"]
                else "Connected; no fresh candles verified"
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
    except Exception as exc:
        state["status"] = "Connection error"
        state["last_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        state["connected"] = False
        try:
            if client:
                await client.close()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app):
    stop_event.clear()
    task = None
    true_values = {"1", "true", "yes", "on"}
    collector_requested = os.getenv("ENABLE_COLLECTOR", "false").strip().lower() in true_values
    disable_collector = os.getenv("DISABLE_COLLECTOR", "false").strip().lower() in true_values
    credentials_present = bool(
        os.getenv("QUOTEX_EMAIL", "").strip()
        and os.getenv("QUOTEX_PASSWORD", "").strip()
    )

    # A configured Quotex email/password pair is also treated as an explicit
    # opt-in. This helps when a manually-created Render service still has a
    # stale ENABLE_COLLECTOR=false value that was not synced from render.yaml.
    # DISABLE_COLLECTOR=true always takes precedence as the emergency off switch.
    enabled = not disable_collector and (collector_requested or credentials_present)

    if enabled:
        task = asyncio.create_task(collector())
    else:
        state["status"] = "Collector disabled; dashboard-only mode"
        state["last_error"] = None
    try:
        yield
    finally:
        stop_event.set()
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:
                pass


app = FastAPI(title="Quotex OTC Signal Bot", lifespan=lifespan)


@app.middleware("http")
async def dashboard_auth(request, call_next):
    # Render's health check stays public; dashboard and API endpoints require Basic Auth.
    if request.url.path == "/health":
        return await call_next(request)
    username = os.getenv("DASHBOARD_USERNAME")
    password = os.getenv("DASHBOARD_PASSWORD")
    if not username or not password:
        return PlainTextResponse(
            "Dashboard authentication is not configured. Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD.",
            status_code=503,
        )
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            supplied_user, separator, supplied_password = decoded.partition(":")
            if separator and hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password):
                return await call_next(request)
        except (ValueError, UnicodeDecodeError):
            pass
    return PlainTextResponse(
        "Authentication required.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Quotex OTC Dashboard"'},
    )


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OTC Signal Bot</title><style>
:root{color-scheme:dark}body{font-family:Arial,sans-serif;background:#101522;color:#f4f6fc;margin:0;padding:20px}
main{max-width:1200px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:#1b2435;border:1px solid #2d3950;border-radius:12px;padding:16px;margin:14px 0}
.metric{font-size:25px;font-weight:700}.muted{color:#b6c2d7}button{padding:10px 14px;background:#6578f5;border:0;border-radius:7px;color:white;cursor:pointer}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px;border-bottom:1px solid #3b465b;text-align:left;overflow-wrap:anywhere}
.good{color:#83e0a0}.bad{color:#ff9b9b}.warn{color:#ffd27d}.signal{font-weight:700}.small{font-size:12px}
</style></head><body><main>
<h1>Quotex OTC Signal Bot</h1><p class="muted">Experimental · Demo/paper mode · No automatic trading · Signals are not guaranteed</p>
<div class="grid">
<div class="card"><div class="muted">Connection</div><div id="conn" class="metric">Loading…</div></div>
<div class="card"><div class="muted">Fresh pairs</div><div id="fresh" class="metric">—</div></div>
<div class="card"><div class="muted">Signals today</div><div id="limit" class="metric">—</div></div>
<div class="card"><div class="muted">Strategy</div><div id="strategy" class="small">EMA + engulfing + volatility</div></div>
</div>
<div class="card"><h2>Status</h2><div id="status">Loading…</div><p id="poll" class="muted"></p><p id="error" class="bad"></p><button onclick="refresh()">Refresh now</button></div>
<div class="card"><h2>Candle feed</h2><div id="pairs" class="tablewrap">Loading…</div></div>
<div class="card"><h2>Recent signals</h2><div id="signals" class="tablewrap">No signals yet.</div></div>
<div class="card"><h2>Safety and testing</h2><ul>
<li>Only fully closed candles are analysed.</li><li>WAIT is normal when filters disagree or data is insufficient.</li>
<li>Signal score is a count of conditions, not a win probability.</li><li>Strategy is experimental and not validated.</li>
<li>CSV history is not yet a verified backtest; do not infer profitability from signal count.</li>
<li>Unofficial pyquotex may be unreliable. Public hosting is protected by dashboard login; keep credentials private.</li>
</ul></div>
</main><script>
function el(id,text){document.getElementById(id).textContent=text}
function td(value){const e=document.createElement('td');e.textContent=value??'';return e}
function table(headers, rows){
 const t=document.createElement('table'), h=document.createElement('tr');
 headers.forEach(x=>{const th=document.createElement('th');th.textContent=x;h.appendChild(th)});t.appendChild(h);
 rows.forEach(row=>{const tr=document.createElement('tr');row.forEach(x=>tr.appendChild(td(x)));t.appendChild(tr)});return t
}
async function refresh(){try{
 const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);
 const s=await r.json();
 el('conn',s.connected?'CONNECTED':'DISCONNECTED');
 el('fresh',Object.values(s.latest||{}).filter(x=>x.status==='FRESH').length+' / '+s.pairs.length);
 el('limit',s.signals_today+' / '+s.daily_limit);el('strategy',s.strategy||'Experimental');
 el('status',s.status+' | fresh feed verified='+s.candle_feed_verified);
 el('poll','Last poll: '+(s.last_poll||'not yet')+' | Pairs: '+s.pairs.join(', '));
 el('error',s.last_error||'');
 const entries=Object.entries(s.latest||{});
 const pr=entries.map(([p,d])=>[p,d.status,d.count??'',d.closed_count??'',d.latest_candle_utc||'',d.age_seconds??'',d.close??'',d.analysis_status||'',d.analysis_reason||d.error||'']);
 const p=document.getElementById('pairs');p.replaceChildren(table(['Pair','Feed','Rows','Closed','Latest UTC','Age sec','Close','Analysis','Reason / error'],pr));
 const sig=(s.signals||[]).slice(0,30).map(x=>[x.created_at,x.pair,x.direction,x.pattern,x.score??'',x.reason||'',x.candle_time_utc,x.status||'UNVALIDATED']);
 const q=document.getElementById('signals');q.replaceChildren(sig.length?table(['Created IST','Pair','Direction','Pattern','Conditions','Reason','Candle UTC','Status'],sig):document.createTextNode('No signals yet. WAIT/no signal is normal.'));
 }catch(e){el('error',String(e))}}
refresh();setInterval(refresh,10000);
</script></body></html>""")


@app.get("/api/status")
def api_status():
    return {**state, "signals_today": count_today(), "daily_limit": MAX_DAILY_SIGNALS,
            "poll_seconds": POLL_SECONDS, "timezone": "Asia/Kolkata"}


@app.get("/api/candles")
def api_candles():
    if not CANDLES_CSV.exists():
        return {"count": 0, "candles": []}
    with CANDLES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"count": len(rows), "candles": rows[-300:]}


@app.get("/api/signals")
def api_signals():
    return {"count": len(state["signals"]), "signals": state["signals"]}


@app.get("/health")
def health():
    return {"status": state["status"], "connected": state["connected"],
            "candle_feed_verified": state["candle_feed_verified"],
            "last_poll": state["last_poll"], "last_error": state["last_error"]}