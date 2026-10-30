"""Read-only Quotex Demo adapter for ChipaDevTeam/QuotexAPI.

Uses a user-supplied browser SSID. It never calls any order/trading methods.
Only explicit OHLC events are accepted; no candles are fabricated.
"""
from __future__ import annotations
import asyncio, os, re, time
from collections import defaultdict
from typing import Any

SOURCE = "ChipaDevTeam QuotexAPI WebSocket (unofficial)"
_api = None
_loop: asyncio.AbstractEventLoop | None = None
_connected = False
_error = "Quotex Demo SSID is not configured."
_events = 0
_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
_callbacks = []
_seen: set[tuple[str, int]] = set()


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
    await api.login_with_ssid(_get_ssid(),is_demo=True)
    # Attach handlers directly to the package's Socket.IO event router.
    api.connection.subscribe("depth",_on_event)
    api.connection.subscribe("tick",_on_event)
    api.connection.subscribe("candles",_on_event)
    api.connection.subscribe("candle",_on_event)
    await api.data.subscribe_candles(_symbols()[0],timeframe=60)
    for symbol in _symbols()[1:]:
        await api.data.subscribe_candles(symbol,timeframe=60)
    _api=api; _connected=True
    _error="Quotex Demo SSID authenticated; waiting for validated candle events."


def connection_status() -> dict[str,Any]:
    global _error
    if not _connected:
        try:
            asyncio.get_running_loop()
            return {"connected":False,"live_data":False,"credentials_configured":bool(os.getenv("QUOTEX_SSID")),
                    "message":_error,"source":SOURCE,"market_type":"Quotex Demo","read_only":True}
        except RuntimeError:
            async def run():
                global _error
                try: await _start()
                except Exception as exc: _error=f"QuotexAPI connection failed: {type(exc).__name__}: {str(exc)[:200]}"
            asyncio.run(run())
    return {"connected":_connected,"live_data":any(_rows.values()),
            "credentials_configured":bool(os.getenv("QUOTEX_SSID")),
            "message":("Authenticated; verified OHLC events are arriving." if any(_rows.values()) else _error),
            "source":SOURCE,"market_type":"Quotex Demo","events_received":_events,
            "read_only":True,"affiliation":"Unofficial community API; not operated by Quotex."}


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
        connection_status()
    rows=list(_rows.get(symbol,[]))
    if len(rows)<30:
        raise RuntimeError(f"No verified OHLC stream yet for {symbol}; received {len(rows)} candle bars.")
    return rows[-limit:]


def shutdown() -> None:
    global _api,_connected
    if _api is not None and _loop is not None and _loop.is_running():
        asyncio.run_coroutine_threadsafe(_api.disconnect(),_loop)
    _api=None; _connected=False
