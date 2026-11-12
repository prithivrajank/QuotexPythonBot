"""Read-only Quotex adapter for ChipaDevTeam/QuotexAPI.

Uses a user-supplied browser SSID. It never calls any order/trading methods.
Only explicit quote and OHLC events are accepted; no prices or candles are fabricated.
"""
from __future__ import annotations
import asyncio, os, re, threading, time
from collections import defaultdict
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any

SOURCE = "ChipaDevTeam QuotexAPI WebSocket (unofficial)"
_api = None
_loop: asyncio.AbstractEventLoop | None = None
_connected = False
_error = "Quotex SSID is not configured."
_events = 0
_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
_ticks: dict[str, dict[str, Any]] = {}
_seen: set[tuple[str, int]] = set()
_loop_thread: threading.Thread | None = None
_loop_ready = threading.Event()
_startup_future: Future | None = None
_RETRY_COOLDOWN_SECONDS = max(60, int(os.getenv("QUOTEX_RETRY_COOLDOWN_SECONDS", "300")))
_retry_after = 0.0
_connection_lock = threading.Lock()


def _get_ssid() -> str:
    raw=os.getenv("QUOTEX_SSID","").strip()
    if not raw:
        raise ValueError("Set QUOTEX_SSID in Render Environment using the browser session for the selected QUOTEX_ACCOUNT.")
    match=re.search(r'"session"\s*:\s*"([^"]+)"', raw)
    if match:
        return match.group(1)
    if raw.startswith("42["):
        raise ValueError("Could not parse QUOTEX_SSID frame. Set only the ssid cookie value.")
    return raw


def _symbols() -> list[str]:
    """Return OTC instruments only; never silently mix standard forex."""
    out=[]
    for item in os.getenv("FOREX_SYMBOLS","EURUSD_otc,GBPUSD_otc").split(","):
        s=item.strip().replace("/","").replace("-","").upper()
        if not s:
            continue
        if not s.endswith("_OTC"):
            raise ValueError(
                "OTC-only mode: every FOREX_SYMBOLS entry must end with _otc."
            )
        normalized=s[:-4]+"_otc"
        if normalized not in out:
            out.append(normalized)
    if not out:
        raise ValueError("OTC-only mode requires at least one *_otc symbol.")
    return out


def _account_mode() -> tuple[bool, str]:
    """This bot is strictly read-only and Demo-account only."""
    raw=os.getenv("QUOTEX_ACCOUNT", "demo").strip().lower()
    legacy=os.getenv("QUOTEX_IS_DEMO", "true").strip().lower()
    if raw not in {"", "demo"} or legacy not in {"true", "1", "yes"}:
        raise ValueError(
            "Safety lock: QuotexPythonBot supports Demo account only. "
            "Set QUOTEX_ACCOUNT=demo and QUOTEX_IS_DEMO=true."
        )
    return True, "Demo"


def _candle_from_payload(data: Any, symbol: str) -> dict[str, Any] | None:
    candidates=[]
    if isinstance(data, dict):
        candidates.append(data)
        for key in ("candles","data","history","items"):
            v=data.get(key)
            if isinstance(v,list): candidates.extend(x for x in v if isinstance(x,dict))
    elif isinstance(data,list):
        candidates.extend(x for x in data if isinstance(x,dict))
    for x in candidates:
        try:
            o=float(x.get("open",x.get("o"))); h=float(x.get("high",x.get("h")))
            lo=float(x.get("low",x.get("l"))); c=float(x.get("close",x.get("c")))
            ts=int(x.get("time",x.get("timestamp",x.get("from",0))))
        except (TypeError,ValueError):
            continue
        if ts>10_000_000_000: ts//=1000
        if ts<=0 or h<max(o,lo,c) or lo>min(o,h,c): continue
        market_type = "Quotex OTC" if symbol.lower().endswith("_otc") else "Quotex live forex"
        return {"time":ts,"open":o,"high":h,"low":lo,"close":c,"symbol":symbol,
                "timeframe_seconds":60,"venue":"quotexapi","market_type":market_type,"source":SOURCE}
    return None


def _on_quote(data: Any) -> None:
    """Store only explicit, symbol-labelled quote/tick events."""
    if not isinstance(data, dict):
        return
    asset = str(data.get("asset", data.get("symbol", ""))).strip().lower()
    if not asset:
        return
    price_value = data.get("price", data.get("quote", data.get("close")))
    try:
        price = float(price_value)
        timestamp = float(data.get("time", data.get("timestamp", time.time())))
    except (TypeError, ValueError):
        return
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    if not (price > 0 and timestamp > 0):
        return
    for symbol in _symbols():
        if asset == symbol.lower():
            _ticks[symbol] = {
                "symbol": symbol, "price": price, "time": timestamp,
                "market_type": "Quotex OTC" if symbol.lower().endswith("_otc") else "Quotex live forex",
                "source": SOURCE,
            }
            return


def get_ticks() -> list[dict[str, Any]]:
    """Return latest observed ticks; this is a snapshot, not a fabricated stream."""
    return [dict(_ticks[s]) for s in _symbols() if s in _ticks]


def _on_event(data: Any) -> None:
    global _events
    _events += 1
    # Upstream's published depth handler only forwards records with an asset field.
    # Match only configured asset symbols and explicit OHLC records.
    if not isinstance(data,dict): return
    asset=str(data.get("asset", data.get("symbol", ""))).strip().lower()
    # Never guess which configured instrument an unlabelled event belongs to.
    if not asset: return
    for symbol in _symbols():
        if asset != symbol.lower(): continue
        candle=_candle_from_payload(data,symbol)
        if candle:
            key=(symbol,candle["time"])
            if key not in _seen:
                _rows[symbol].append(candle); _rows[symbol]=_rows[symbol][-500:]
                _seen.add(key)
            else:
                for i,row in enumerate(_rows[symbol]):
                    if row["time"]==candle["time"]:
                        _rows[symbol][i]=candle; break


async def _start() -> None:
    global _api,_connected,_error,_loop
    if _connected: return
    from QuotexAPI import QuotexAPI
    _loop=asyncio.get_running_loop()
    is_demo, account_label = _account_mode()
    ssid = _get_ssid()
    api=QuotexAPI(ssid=ssid,is_demo=is_demo,log_level="INFO")
    await api.connect()
    await api.login_with_ssid(ssid)
    # Register through the library's documented DataService callback API.
    # DataService.initialize() is already called by api.connect().
    for symbol in _symbols():
        api.data.on_candle(symbol, _on_event)
        await api.data.subscribe_candles(symbol, timeframe=60)
        api.data.on_quote(symbol, _on_quote)
        await api.data.subscribe_quotes(symbol)
    _api=api; _connected=True
    _error=f"Quotex {account_label} account authenticated; waiting for validated candle events."


def _loop_worker() -> None:
    global _loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    _loop_ready.set()
    loop.run_forever()


def _ensure_connection() -> Future | None:
    """Start one persistent loop; back off after failed handshakes."""
    global _loop_thread, _startup_future, _error, _retry_after
    with _connection_lock:
        if _connected:
            return _startup_future

        # Reuse a failed result during the cooldown rather than retrying a 429.
        if _startup_future is not None and _startup_future.done():
            if time.monotonic() < _retry_after:
                return _startup_future
            _startup_future = None
        if _startup_future is not None:
            return _startup_future

        if _loop_thread is None or not _loop_thread.is_alive():
            _loop_ready.clear()
            _loop_thread = threading.Thread(
                target=_loop_worker, name="quotex-websocket-loop", daemon=True
            )
            _loop_thread.start()
        if not _loop_ready.wait(timeout=5) or _loop is None:
            _error = "Timed out starting the Quotex WebSocket event loop."
            _retry_after = time.monotonic() + _RETRY_COOLDOWN_SECONDS
            return None

        _error = f"Connecting to Quotex {_account_mode()[1]} account..."
        _startup_future = asyncio.run_coroutine_threadsafe(_start(), _loop)

        def _record_start_error(future: Future) -> None:
            global _error, _retry_after
            try:
                future.result()
                _retry_after = 0.0
            except Exception as exc:
                _error = f"QuotexAPI connection failed: {type(exc).__name__}: {str(exc)[:200]}"
                _retry_after = time.monotonic() + _RETRY_COOLDOWN_SECONDS

        _startup_future.add_done_callback(_record_start_error)
        return _startup_future

def connection_status(start: bool = False) -> dict[str,Any]:
    # Dashboard status polling must be passive; do not open a broker connection
    # while the user has the bot OFF. Explicit candle refresh starts it instead.
    if start and not _connected:
        _ensure_connection()
    has_rows = any(_rows.values())
    return {
        "connected": _connected,
        "live_data": has_rows,
        "credentials_configured": bool(os.getenv("QUOTEX_SSID")),
        "message": (
            "Authenticated; verified OHLC events are arriving."
            if has_rows else
            ("Authenticated; waiting for validated candle events." if _connected else
             (_error if _error and _error != "Quotex Demo SSID is not configured." else
              ("Quotex SSID is configured; connection has not been attempted while the bot is OFF."
               if os.getenv("QUOTEX_SSID", "").strip() else
               "Quotex SSID is not configured.")))
        ),
        "source": SOURCE,
        "market_type": "Quotex OTC only",
        "account_mode": os.getenv("QUOTEX_ACCOUNT", "demo").strip().lower(),
        "events_received": _events,
        "ticks_received": len(_ticks),
        "tick_symbols": sorted(_ticks),
        "read_only": True,
        "affiliation": "Unofficial community API; not operated by Quotex.",
    }

def get_assets() -> list[dict[str,Any]]:
    # The upstream get_assets() implementation currently returns mock items.
    # Do not represent those as verified broker catalogue data.
    return [{"symbol":s,"name":s,"market_type":"Quotex OTC" if s.lower().endswith("_otc") else "Quotex live forex","source":SOURCE} for s in _symbols()]


def get_candles(asset: str,timeframe_seconds: int,limit: int=100) -> list[dict[str,Any]]:
    if timeframe_seconds!=60:
        raise ValueError("ChipaDevTeam integration currently supports only 60-second subscriptions.")
    symbol=asset.strip().replace("/","").replace("-","").upper()
    if symbol.endswith("_OTC"):
        symbol=symbol[:-4]+"_otc"
    if not _connected:
        future = _ensure_connection()
        if future is not None:
            try:
                future.result(timeout=20)
            except FutureTimeout:
                raise RuntimeError("Timed out waiting for the Quotex WebSocket connection.")
            except Exception as exc:
                raise RuntimeError(f"Quotex connection failed: {type(exc).__name__}: {str(exc)[:160]}") from exc
    rows=list(_rows.get(symbol,[]))
    if len(rows)<30:
        raise RuntimeError(f"No verified OHLC stream yet for {symbol}; received {len(rows)} candle bars.")
    return rows[-limit:]


def shutdown() -> None:
    global _api, _connected, _startup_future, _loop_thread, _loop, _retry_after
    if _api is not None and _loop is not None and _loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_api.disconnect(), _loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass
    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(_loop.stop)
    _api = None
    _connected = False
    _ticks.clear()
    _startup_future = None
    _retry_after = 0.0
    _loop_thread = None
    _loop = None
