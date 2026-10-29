# Standard Forex Data & Signal Bot

Signal-only project for Render. Automatic trade execution is not implemented.

## Data source and important limitation

This version uses Twelve Data's free Basic REST API to retrieve standard forex OHLC candles. Twelve Data is an independent market-data provider and is not affiliated with Quotex. **This is not a Quotex API and these candles are not Quotex OTC/synthetic prices.** Prices and resulting signals can differ from what the Quotex platform displays.

Twelve Data currently lists its Basic plan at $0/month, with 800 API credits per day and no credit card required. The free plan provides REST data; WebSocket streaming is a paid-plan feature. Confirm current limits on the official pricing page: https://twelvedata.com/pricing.

## Set up the free API key

1. Create an account at https://twelvedata.com and copy your API key from the dashboard.
2. In Render, open your web service → Environment.
3. Add `TWELVE_DATA_API_KEY` with your API key as the value. Never put it in code, `render.yaml`, screenshots, or GitHub.
4. Save and redeploy the latest commit.
5. Open `/api/status`. A successful status means the key was accepted by the usage endpoint; request `/api/candles` to confirm your chosen pair/interval is available.

## Read-only endpoints

- `/health`: web-service health only.
- `/api/status`: checks the API key through Twelve Data's `/api_usage` endpoint (uses one API credit).
- `/api/assets`: retrieves the current forex-pair catalogue from Twelve Data.
- `/api/candles?asset=EUR%2FUSD&timeframe_seconds=60&limit=100`: returns standard forex OHLC candles if your plan supports the requested pair.

Example Python usage:

```python
from data_collector import get_assets, get_candles

pairs = get_assets()
print(pairs[:5])

candles = get_candles("EUR/USD", timeframe_seconds=60, limit=100)
for candle in candles:
    print(candle["time"], candle["open"], candle["high"], candle["low"], candle["close"])
```

Supported timeframe seconds: 60, 300, 900, 1800, 2700, 3600, 7200, 14400, 28800, 86400, 604800, and 2592000. The API uses REST requests; do not poll rapidly or waste your daily quota. Candle records are validated and sorted oldest-first. No fake candles are returned if the provider fails.

## Render environment variable

`render.yaml` declares `TWELVE_DATA_API_KEY` with `sync: false`; enter the actual secret through Render's Environment settings. If an older `OTCHARTS_API_KEY` exists, you can remove it after confirming the new version works.

## Strategy and limitations

`strategies.py` contains a preliminary EMA(9)/EMA(21), candle direction, and RSI(14) heuristic. It must be tested on timestamped historical data. Standard forex candles are only reference data and should not be represented as exact Quotex OTC prices. Signals do not guarantee future results.
