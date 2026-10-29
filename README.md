# Quotex Live Data & Signal Bot

This is a signal-only project. Automatic trade execution is not implemented.

## Data source

Candles are fetched from OTCharts, an independent third-party market-data provider. OTCharts is not affiliated with, endorsed by, or partnered with Quotex. This is not an official Quotex API. The integration is read-only and does not place orders or use your Quotex login/session.

OTC prices are the venue's own quoted series and can differ from standard forex market prices. No sample candles are generated if the provider is unavailable.

## Setup on Render

1. Create an account at https://otcharts.com, verify it, and create an API key.
2. Check that your OTCharts plan enables the Quotex venue. The free trial has usage limits and may not include streaming.
3. In Render, open the service's Environment settings and add `OTCHARTS_API_KEY` with the key as its value. Keep the key out of GitHub and source files.
4. Redeploy the service.
5. Check `/health` for web-service health and `/api/status` for OTCharts API authentication. `/health` alone does not mean candle data is connected.

## Python usage

```python
from data_collector import get_assets, get_candles

assets = get_assets()  # Current symbol catalogue from OTCharts
print(assets[:5])

# Use an exact symbol returned by get_assets(), if enabled for your plan.
candles = get_candles("EURUSD_otc", timeframe_seconds=60, limit=100)
for candle in candles:
    print(candle["time"], candle["open"], candle["high"], candle["low"], candle["close"])
```

Supported timeframes are 5, 15, 30, 60, 120, 180, 300, 600, 900, 1800, 3600, 14400, and 86400 seconds. Results are returned oldest-first and include source/venue labels. Confirm a symbol exists with `get_assets()` rather than assuming it is available.

The collector uses HTTPS, sends the key as a Bearer token, applies a timeout, validates OHLC fields, and raises errors instead of returning fake data.

## Endpoints

- `/health`: web-service health only.
- `/api/status`: checks OTCharts authentication. `live_data` stays false until candle data itself has been verified.
- `get_assets()`: returns the current Quotex symbol catalogue from OTCharts.
- `get_candles(symbol, timeframe_seconds, limit)`: fetches real OHLC candles.

## Strategy and limitations

`strategies.py` contains a preliminary EMA(9)/EMA(21), candle direction, and RSI(14) heuristic. It requires testing on timestamped historical data. Signals do not guarantee future results, and OTC prices are not the same as underlying interbank market prices.
