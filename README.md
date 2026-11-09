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

## Historical backtesting

- Open `/backtest` for the historical backtesting dashboard.
- Call `GET /api/backtest?symbol=EUR%2FUSD&timeframe=1m&expiry=1&candle_count=500`.
- Parameters: `symbol` is the provider's exact instrument identifier; `timeframe` accepts supported values such as `1m`, `5m`, `15m`, `30m`, `45m`, `1h`, `2h`, `4h`, `8h`, `1d`, `1w`, or `1mo`; `expiry` is 1, 2, or 3 candles; `candle_count` is 34–5000.
- The backtester calls the existing `strategies.analyze_candles()` and uses only candles available up to each decision candle. Entry is the decision candle close and exit is the close after the selected expiry. It also compares 1-, 2-, and 3-candle expiries to report `best_expiry`.
- Response includes `total_signals`, `wins`, `losses`, `win_rate`, `profit_factor`, `best_asset`, `best_expiry`, `strategy_version`, and an `expiry_comparison` array. WAIT and flat outcomes are not counted as wins or losses; WAIT is reported separately.
- Profit factor is calculated from summed directional percentage price moves, not binary-options payout, spread, fees, slippage, or executable fills. Results are research estimates, not a prediction or guarantee.
- Backtesting is unavailable when `MARKET_DATA_PROVIDER=a11ksa`, because that provider mode is intentionally limited to candle display only.

## Signal limitations

CALL/PUT/WAIT labels, indicator summaries, and expiry suggestions are heuristic analysis, not validated probabilities, financial advice, or guaranteed predictions. OTC quotes are a broker-specific synthetic series and may differ from standard forex prices. Test against the source chart before relying on any result.

## Telegram market-data notifications (read-only)

Set these two environment variables in Render → your service → Environment:

- `TELEGRAM_BOT_TOKEN`: create a bot with Telegram's official `@BotFather` and copy its token directly into Render.
- `TELEGRAM_CHAT_ID`: the destination chat ID. Start the bot and send it a message first; obtain the chat ID using a trusted Telegram bot-management method.

Never paste either value into GitHub, source code, screenshots, logs, or this chat. Save the variables and redeploy the Render service.

After configuration, each successfully fetched **new candle timestamp** can generate one Telegram message containing the symbol, market type, provider, timeframe, candle time, and OHLC values. Repeated refreshes of the same candle are suppressed in the running process. Telegram messages contain market data only—no CALL/PUT/WAIT analysis and no trade instructions.

Manual refreshes can send a notification too. Scheduled notifications require the provider's scheduled refresh to be enabled; OTCharts' free tier remains manual-refresh-only, so it will not send continuous scheduled updates. Telegram delivery requires a successful provider candle fetch and a reachable Telegram API.


## ChipaDevTeam QuotexAPI connection (read-only)

The selected integration uses the unofficial [ChipaDevTeam QuotexAPI](https://github.com/ChipaDevTeam/QuotexAPI) Python library. Set `MARKET_DATA_PROVIDER=quotexapi`, `QUOTEX_ACCOUNT=demo` or `QUOTEX_ACCOUNT=real`, and `QUOTEX_SSID` in Render Environment. The SSID must belong to the selected account mode. One authenticated account is supported per running Render process; switching between Demo and Real requires changing `QUOTEX_ACCOUNT`, supplying that account's own session value, and redeploying. Demo and Real are not connected simultaneously.

Set `FOREX_SYMBOLS` to a comma-separated list. Symbols ending in `_otc` are treated as Quotex OTC instruments; symbols without that suffix are treated as live forex, for example `EURUSD_otc,GBPUSD_otc,EURUSD,GBPUSD`. Confirm exact symbol identifiers and availability in the selected Quotex account.

The adapter is intentionally read-only: it connects, authenticates the selected session, subscribes to configured 60-second candle events, and accepts only payloads containing explicit, internally consistent OHLC values. It does not call order placement, cancellation, deposit, withdrawal, or account-switching methods.

**Important limitations:** this is an unofficial community library, not an official Quotex API. Its README marks some features as placeholders/mock implementations, and live candle event payloads and authentication must be verified against the broker session before treating them as working market data. A successful WebSocket/authentication response alone does not prove that real candles are arriving. Use Demo for initial connection testing. Real-account session use carries account risk. Use only where permitted by Quotex's terms and applicable law.

The library may change or stop working when Quotex changes its service. Signals remain heuristic research outputs, not guaranteed next-candle predictions. Validate with timestamp-safe backtests and forward-testing; confidence scores are not calibrated probabilities unless tested on out-of-sample data.


## Live tick + candle stream (read-only)

The `quotexapi` adapter now also registers the community library's quote callbacks and subscribes to quotes for each configured symbol, alongside its existing 60-second candle subscriptions. This uses the same single selected Quotex account session for OTC symbols ending in `_otc` and plain symbols. Whether the broker actually streams each requested symbol must be verified with the account and pair catalogue; no data is synthesized.

- `GET /api/ticks` returns the latest observed tick per symbol.
- `WS /ws/market` pushes tick snapshots to connected browser clients. Clients should send a small text heartbeat at least every 10 seconds; the server closes inactive clients after 12 seconds.
- Candle history remains available through the existing `/api/candles` endpoint and the existing 60-second subscription.

The WebSocket integration is based on the upstream library's documented `on_quote` / `subscribe_quotes` and `on_candle` / `subscribe_candles` interfaces. It is unofficial and has not been validated against every Quotex account or symbol. If a symbol produces no ticks, check the Render logs and confirm that the symbol identifier is supported. Never share the SSID.

For Render Free, a connected browser must keep sending heartbeat messages: free services spin down after 15 minutes without inbound HTTP requests or WebSocket messages. A free instance can still restart or disconnect, so this is best-effort hobby streaming, not guaranteed 24/7 uptime. See https://render.com/docs/free and https://render.com/docs/websocket.
