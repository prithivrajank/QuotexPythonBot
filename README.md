# Quotex Market-Data Analyzer (read-only)

This repository provides a dashboard for candle charts and heuristic CALL/PUT/WAIT analysis. It does **not** place trades.

## OTCharts setup (recommended for Quotex OTC data)

Quotex does not publish an official public API. OTCharts is an independent third-party, read-only market-data provider; it is not operated by, affiliated with, or endorsed by Quotex.

1. Create an account at https://otcharts.com/api-key and confirm your email.
2. Create an API key and select the **Quotex** book for that key. The key is shown only once; keep it private.
3. In Render → your `quotex-live-signal-bot` service → **Environment**, set:
   - `MARKET_DATA_PROVIDER=otcharts`
   - `OTCHARTS_API_KEY` = your key (secret; never put it in GitHub, a URL, frontend code, or this chat)
   - `FOREX_SYMBOLS` = up to five exact symbols allowed by your free key, copied from the OTCharts catalogue, e.g. `EURUSD_otc,GBPUSD_otc,USDJPY_otc,AUDUSD_otc,USDCAD_otc` only if those are included in your key's five free instruments.
   - `FOREX_TIMEFRAME_SECONDS=60`
4. Save the environment settings and redeploy.
5. Open `/api/status`, then use **Refresh selected pair (uses 1 request)** once to test candle access. A configured key is not considered validated until a candle request succeeds.

The API uses `GET https://otcharts.com/v1/symbols?venue=quotex` and `GET https://otcharts.com/v1/candles?venue=quotex&symbol=EURUSD_otc&tf=60&limit=100`. Symbols must match the API catalogue exactly. See https://otcharts.com/api and https://otcharts.com/quotex-api.

## Free-tier limitation — important

OTCharts' free tier currently provides one selected book, five instruments, **200 requests in the first month**, and **no live streaming**. For that reason, this repository disables automatic candle polling when `MARKET_DATA_PROVIDER=otcharts`; use manual refresh sparingly, one pair at a time. Each manual refresh uses an API request. The free tier cannot power continuous live signals or automatic Telegram alerts. Live streaming requires an eligible paid plan.

If your key returns an access/plan error, check that the key's selected book is Quotex and that the requested symbol is among the five instruments allowed by the free tier. Never paste the key into chat or commit it to the repository.

## Other providers

- `MARKET_DATA_PROVIDER=twelve_data`: uses `TWELVE_DATA_API_KEY` and standard forex prices, not Quotex OTC/synthetic prices.
- `MARKET_DATA_PROVIDER=quantex`: uses `QUANTEX_API_KEY` and `QUANTEX_BROKER=quotex`; candle access depends on the provider's plan.

Set provider-specific environment variables only in Render's Environment UI. Do not commit secret values to `render.yaml`.

## Dashboard endpoints

- `/health` — service health.
- `/api/status` — selected provider status and setup guidance.
- `/api/assets` — available instruments from the selected provider.
- `/api/watchlist` — configured symbols and refresh details.
- `/api/latest?asset=EURUSD_otc` — cached snapshot.
- `/api/candles?asset=EURUSD_otc&timeframe_seconds=60&limit=100` — candle request.
- `/api/analysis?asset=EURUSD_otc&timeframe_seconds=60&limit=100` — analysis request.
- `POST /api/refresh?asset=EURUSD_otc` — manual refresh; uses provider quota.
- `/api/history?limit=50` — signal-history summary.

## Signal limitations

CALL/PUT/WAIT labels, indicator summaries, and expiry suggestions are heuristic analysis, not validated probabilities, financial advice, or guaranteed predictions. OTC quotes are a broker-specific synthetic series and may differ from standard forex prices. Test against the source chart before relying on any result.

## Optional Telegram alerts

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in Render Environment. Do not store credentials in source code. With OTCharts' free tier, automatic polling is disabled, so the bot cannot provide continuous scheduled Telegram signals on that tier.


## A11ksa Quotex data provider (read-only)

This branch adds the unofficial A11ksa API-Quotex client as an optional market-data provider. Set `MARKET_DATA_PROVIDER=a11ksa` to use it. On Render, set `QUOTEX_EMAIL` and `QUOTEX_PASSWORD` as secret environment variables and choose `QUOTEX_DEMO=true` for demo access. Never commit credentials, SSID values, `config.json`, or session files.

The adapter only calls asset-list and candle-history methods. It does not place, modify, or close orders. A11ksa is an unofficial third-party project and may break when Quotex changes its service; it is not affiliated with or endorsed by Quotex. Use only where permitted by the broker's terms and applicable law.

Signals are heuristic research outputs, not guaranteed next-candle predictions. Measure results with timestamp-safe backtests and forward-testing before relying on them. A displayed confidence score, if enabled, must not be interpreted as a calibrated probability unless it has been validated on out-of-sample data.
