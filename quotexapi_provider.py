"""Read-only Quotex Demo adapter for ChipaDevTeam/QuotexAPI.

Uses a user-supplied browser SSID. It never calls any order/trading methods.
Only explicit OHLC events are accepted; no candles are fabricated.
"""
from __future__ import annotations
import asyncio, os, re, threading
from collections import defaultdict
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any

SOURCE = "ChipaDevTeam QuotexAPI WebSocket (unofficial)"
_api = None
_loop: asyncio.AbstractEventLoop | None = None
_connected = False
_error = "Quotex Demo SSID is not configured."
_events = 0
_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
_seen: set[tuple[str, int]] = set()
_loop_thread: threading.Thread | None = None
_loop_ready = threading.Event()
_startup_future: Future | None = None


def _get_ssid() -> str:
    raw=os.getenv("QUOTEX_SSID","").strip()
    if not raw:
        raise ValueError("Set QUOTEX_SSID in Render Environment using your Quotex Demo browser session.")
    match=re.search(r'"session"\s*:\s*"([^"]+)"', raw)
    if match:
        return match.group(1)
    if raw.startswith("42["):
        raise ValueError("Could not parse QUOTEX_SSID frame. Set only the ssid cookie value.")
    return raw


def _symbols() -> list[str]:
    out=[]
    for item in os.getenv("FOREX_SYMBOLS","EURUSD_otc,GBPUSD_otc").split(","):
        s=item.strip().replace("/","").replace("-","").upper()
        if s and not s.endswith("_OTC"): s += "_otc"
        if s: out.append(s)
    return out


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
        return {"time":ts,"open":o,"high":h,"low":lo,"close":c,"symbol":symbol,
                "timeframe_seconds":60,"venue":"quotexapi","market_type":"Quotex Demo","source":SOURCE}
    return None


def _on_event(data: Any) -> None:
    global _events
    _events += 1
    # Upstream's published depth handler only forwards records with an asset field.
    # Match only configured asset symbols and explicit OHLC records.
    if not isinstance(data,dict): return
    asset=str(data.get("asset","")).lower()
    for symbol in _symbols():
        if asset and asset != symbol.lower(): continue
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
    api=QuotexAPI(ssid=_get_ssid(),is_demo=True,log_level="INFO")
    await api.connect()
    await api.login_with_ssid(_get_ssid())
    # Register through the library's documented DataService callback API.
    # DataService.initialize() is already called by api.connect().
    for symbol in _symbols():
        api.data.on_candle(symbol, _on_event)
        await api.data.subscribe_candles(symbol, timeframe=60)
    _api=api; _connected=True
    _error="Quotex Demo SSID authenticated; waiting for validated candle events."


def _loop_worker() -> None:
    global _loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop = loop
    _loop_ready.set()
    loop.run_forever()


def _ensure_connection() -> Future | None:
    """Start one persistent asyncio loop and one provider connection."""
    global _loop_thread, _startup_future, _error
    if _connected:
        return _startup_future
    if _loop_thread is None or not _loop_thread.is_alive():
        _loop_ready.clear()
        _loop_thread = threading.Thread(
            target=_loop_worker, name="quotex-websocket-loop", daemon=True
        )
        _loop_thread.start()
    if not _loop_ready.wait(timeout=5) or _loop is None:
        _error = "Timed out starting the Quotex WebSocket event loop."
        return None
    if _startup_future is None or _startup_future.done():
        _startup_future = asyncio.run_coroutine_threadsafe(_start(), _loop)

        def _record_start_error(future: Future) -> None:
            global _error
            try:
                future.result()
            except Exception as exc:
                _error = f"QuotexAPI connection failed: {type(exc).__name__}: {str(exc)[:200]}"

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
             ("Demo SSID is configured; connection has not been attempted while the bot is OFF."
              if os.getenv("QUOTEX_SSID", "").strip() else
              "Quotex Demo SSID is not configured."))
        ),
        "source": SOURCE,
        "market_type": "Quotex Demo",
        "events_received": _events,
        "read_only": True,
        "affiliation": "Unofficial community API; not operated by Quotex.",
    }

def get_assets() -> list[dict[str,Any]]:
    # The upstream get_assets() implementation currently returns mock items.
    # Do not represent those as verified broker catalogue data.
    return [{"symbol":s,"name":s,"market_type":"Quotex Demo subscription","source":SOURCE} for s in _symbols()]


def get_candles(asset: str,timeframe_seconds: int,limit: int=100) -> list[dict[str,Any]]:
    if timeframe_seconds!=60:
        raise ValueError("ChipaDevTeam integration currently supports only 60-second subscriptions.")
    symbol=asset.strip().replace("/","").replace("-","").upper()
    if not symbol.endswith("_OTC"): symbol+="_otc"
    if not _connected:
        future = _ensure_connection()
        if future is not None:
            try:
                future.result(timeout=20)
            except FutureTimeout:
                raise RuntimeError("Timed out waiting for the Quotex Demo WebSocket connection.")
            except Exception as exc:
                raise RuntimeError(f"Quotex Demo connection failed: {type(exc).__name__}: {str(exc)[:160]}") from exc
    rows=list(_rows.get(symbol,[]))
    if len(rows)<30:
        raise RuntimeError(f"No verified OHLC stream yet for {symbol}; received {len(rows)} candle bars.")
    return rows[-limit:]


def shutdown() -> None:
    global _api, _connected, _startup_future, _loop_thread, _loop
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
    _startup_future = None
    _loop_thread = None
    _loop = None
