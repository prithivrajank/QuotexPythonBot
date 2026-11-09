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

## Adaptive pair performance filtering

The adaptive pair filter reads completed outcomes from `signal_history.py` and caches per-symbol statistics for five minutes.

- `GET /api/pair-performance` returns each pair's win rate, total signal count, scored trade count, recent-20 completed-trade win rate, average signal score, and classification.
- Classifications: `PRIORITY` requires at least 20 scored trades and a win rate of at least 65%; `NORMAL` is at least 55% when the PRIORITY condition is not met; `WATCHLIST` is 45% to below 55% or an insufficient sample; `DISABLED` requires at least 15 scored trades and a win rate below 45%.
- The signal runtime and `/api/analysis` return WAIT for DISABLED pairs with reason `Pair temporarily disabled due to low performance`. The runtime also suppresses Telegram candle notifications for those pairs.
- The main dashboard shows Top Performing Pairs, Worst Performing Pairs, Disabled Pairs, and Priority Pairs. Dashboard polling reads the cached endpoint; the underlying statistics refresh every 300 seconds.
- Win rate and recent win rate use completed WIN/LOSS outcomes only. Pending, WAIT/skipped, and flat records do not count as scored trades. Symbols with insufficient completed history remain WATCHLIST rather than being disabled based on a small sample.

## Historical backtesting

- Open `/backtest` for the historical backtesting dashboard.
- Call `GET /api/backtest?symbol=EUR%2FUSD&timeframe=1m&expiry=1&candle_count=500`.
- Parameters: `symbol` is the provider's exact instrument identifier; `timeframe` accepts supported values such as `1m`, `5m`, `15m`, `30m`, `45m`, `1h`, `2h`, `4h`, `8h`, `1d`, `1w`, or `1mo`; `expiry` is 1, 2, or 3 candles; `candle_count` is 34–5000.
- The backtester calls the existing `strategies.analyze_candles()` and uses only candles available up to each decision candle. Entry is the decision candle close and exit is the close after the selected expiry. It also compares 1-, 2-, and 3-candle expiries to report `best_expiry`.
- Response includes `total_signals`, `wins`, `losses`, `win_rate`, `profit_factor`, `best_asset`, `best_expiry`, `strategy_version`, and an `expiry_comparison` array. WAIT and flat outcomes are not counted as wins or losses; WAIT is reported separately.
- Profit factor is calculated from summed directional percentage price moves, not binary-options payout, spread, fees, slippage, or executable fills. Results are research estimates, not a prediction or guarantee.
- Backtesting is unavailable when `MARKET_DATA_PROVIDER=a11ksa`, because that provider mode is intentionally limited to candle display only.



## Production health monitoring

- `GET /api/health` reports process-local `health_score`, `status`, `websocket`, `database`, `provider`, `telegram`, and `uptime_seconds`, plus strategy status, component details, last signal/candle timestamps, and exception counters.
- Health starts at 100. The monitor deducts 15 for a disconnected market WebSocket, 30 for a failed database check, 15 for Telegram delivery failures, 20 when no candles have been received since process start, and 20 when no CALL/PUT signals have been generated since process start. Provider-down state deducts another 20; a strategy failure deducts 10. The score is clamped between 0 and 100.
- Status is `HEALTHY` at 70 or above, `WARNING` below 70, and `CRITICAL` below 50. The dashboard polls the endpoint every 15 seconds and displays a warning or critical message automatically.
- Uptime is measured with a monotonic process clock and resets when the application process restarts. Counters and timestamps are process-local and are not durable across restarts or shared between multiple Render workers/instances.
- WebSocket health means at least one client is connected to `/ws/market`; it does not claim that a provider supplies live ticks. Telegram being unconfigured or intentionally suppressed is reported as `unknown`, not as a delivery failure. The database check performs a lightweight read against the existing signal-history SQLite store.
- Existing `GET /health` remains unchanged for compatibility. This monitor is operational telemetry, not an uptime SLA or a guarantee of provider availability.

## Walk-forward validation

- Run the dashboard widget on the main page or call `GET /api/walkforward?symbol=EUR%2FUSD&timeframe=1m&expiry=1&candle_count=500`.
- Parameters match the backtest endpoint: provider-exact `symbol`, supported `timeframe`, `expiry` of 1, 2, or 3 candles, and `candle_count` from 110 to 5000.
- Candles are sorted chronologically and split into the first 70% (training) and final 30% (validation). The existing `backtester.run_backtest()` is run independently on each segment, which in turn calls the existing `strategies.analyze_candles()` using prefix-only history for each decision candle.
- Response fields include `training_win_rate`, `validation_win_rate`, `overfit_score` (absolute difference in percentage points), and `strategy_health` / `status`. A difference of 5 percentage points or less is `HEALTHY`; above 5 through 15 is `WARNING`; above 15 is `OVERFIT`. If either segment has no scored outcomes, the result is `INSUFFICIENT_DATA` and the score is null.
- Each 70/30 segment must contain at least 33 candles to support the existing 1/2/3-candle expiry comparison, so at least 110 total chronological candles are required. WAIT and flat outcomes are excluded from win-rate denominators.
- This is a historical robustness check, not a guarantee of future performance. It uses directional close-to-close movement rather than binary-options payouts, and the overfit score is a percentage-point gap, not a probability.
- Walk-forward validation is unavailable in `MARKET_DATA_PROVIDER=a11ksa` candle-only mode.






## Resilience and recovery suite

- `GET /api/resilience` runs five isolated fault-injection scenarios: WebSocket disconnect, Telegram timeout, database locked, provider unavailable, and invalid candle data.
- Each scenario uses an in-memory test operation with bounded retries. It does not disconnect a real browser WebSocket, send Telegram messages, lock the production database, contact a market-data provider, or insert synthetic market candles into signal history.
- The response includes per-scenario recovery status, attempts, recovery success rate, cumulative `recovery_attempts`, `successful_recoveries`, and `unrecoverable_failures`, plus per-run counters.
- `GET /api/resilience/report` runs the suite and downloads `resilience_report.json`. The report is also written to `RESILIENCE_REPORT_PATH`, default `/tmp/resilience_report.json`.
- The main dashboard's Production System Health card displays Recovery Success Rate and refreshes it every 60 seconds. This dashboard check runs isolated simulations only.
- Retry attempts are bounded and no retry is performed against real provider/Telegram/DB operations by this diagnostic suite. Production request retry policies remain unchanged for backwards compatibility.
- Metrics are process-local and reset when the application process restarts. They are diagnostic test counters, not measured real-world service recovery rates.

## Production readiness suite

- Open `/system-audit` from the main dashboard for PASS/WARNING/FAIL status for database connectivity, market WebSocket client connectivity, Telegram Bot API connectivity, strategy registry, pair ranking service, health monitor, backtester, and walk-forward validator.
- `GET /api/system/audit` runs a fresh audit and returns `overall_status`, `passed_checks`, `failed_checks`, `warnings`, `uptime`, `version`, and per-subsystem `checks`.
- `GET /api/system/audit/export` downloads the report as `audit_report.json`. The report is also written to `AUDIT_REPORT_PATH`, default `/tmp/audit_report.json`.
- A startup audit runs during application lifespan startup. Results are logged; failed optional checks do not prevent the existing service from starting.
- Database validation performs a read through the existing signal-history database. Strategy, pair-ranking, backtester, and walk-forward checks validate imports and callable interfaces; they do not run synthetic trades or fabricate candles.
- WebSocket status reflects actual connected dashboard clients. If no client is connected at startup, it is WARNING rather than a fabricated PASS.
- Telegram validation calls the Bot API `getMe` endpoint only when both Telegram settings are configured. It never sends a message and never logs credentials or request URLs. Missing configuration is WARNING.
- `MARKET_DATA_PROVIDER=a11ksa` continues to redirect the HTML dashboard to the read-only market page; the audit API remains available for operational checks. Audit results are diagnostic snapshots, not an uptime SLA.

## Signal validation dashboard

- Open `/validation` from the main dashboard to review the latest 500 signal-history records.
- `GET /api/validation-dashboard` returns the latest-500 summary, WIN/LOSS totals and win rate, STRONG/MODERATE/WEAK grade win rates, top 10 pairs, strategy rankings, recent 24-hour/7-day/30-day performance, and the last 500 signal rows.
- `GET /api/validation-dashboard/export.csv` downloads those same latest 500 signal rows as CSV.
- The dashboard also reads `/api/health` for process uptime and provider, Telegram, and database component status.
- Overall and grade win rates use completed WIN/LOSS outcomes only; pending, skipped, and flat rows remain included in total signal counts but not win-rate denominators. Pair and strategy rankings use the latest-500 sample. Recent windows use all stored records in their respective UTC time ranges.
- The existing `/api/history`, `/api/health`, weekly report, strategy, and pair-performance APIs are unchanged. Validation endpoints are unavailable in A11KSA candle-only mode, which continues to redirect to the read-only market page.

## Weekly performance and health report

- `GET /api/weekly-report` generates a rolling seven-day UTC report as JSON.
- `GET /api/weekly-report?format=html` renders the same report as a self-contained HTML page.
- Both formats are also exported to `WEEKLY_REPORT_DIR` (default `/tmp/weekly_reports`) as timestamped `weekly_report_*.json` and `weekly_report_*.html` files. The JSON response includes the generated export paths.
- The report includes total signals, wins/losses and overall win rate, strongest and weakest pair, strategy leaderboard, daily win-rate trend, and daily health-score trend.
- Pair and strategy win rates use completed WIN/LOSS outcomes only. Pending, skipped and flat signals are excluded.
- Health observations are recorded whenever `/api/health` is requested. They are not a continuous monitoring probe; daily averages/minimums/maximums are calculated from recorded observations only.
- Signal history and health snapshots share the configured `DATABASE_PATH`. Configure persistent storage if reports must retain history across Render restarts. The report covers the last seven rolling days in UTC.
- A11KSA candle-only mode continues to disable signal-based weekly reporting.


## Automatic strategy promotion and demotion

- `strategy_manager.py` automatically ranks registered strategies using the operator-provided baseline rates: `EMA_RSI_V1` 58%, `SCORE_ENGINE_V2` 64%, and `BREAKOUT_V3` 71%.
- With these baseline rates, `BREAKOUT_V3` is automatically PROMOTED and selected for live analysis; `EMA_RSI_V1` is DEMOTED; `SCORE_ENGINE_V2` is RETAINED.
- Once a strategy has at least `STRATEGY_PROMOTION_MIN_SIGNALS` completed WIN/LOSS outcomes (default 20), its measured history win rate replaces its baseline for ranking. Pending, skipped and flat outcomes do not count.
- `GET /api/strategy-manager` returns active, promoted and demoted strategy, each strategy's rate source and management status. `GET /api/strategies` includes active, promotion rate, and management status fields.
- Automatic selection is enabled by default. Set `AUTO_STRATEGY_SELECTION=false` to disable it and use `STRATEGY_NAME` as the manual strategy override. A11KSA candle-only mode does not run strategy management.
- Promotion changes which analysis strategy is selected; it does not place trades, change broker settings, or guarantee future performance. Validate historical results and monitor sample sizes before relying on rankings.

## Strategy version manager

- `strategy_registry.py` registers `EMA_RSI_V1` (1.0.0), `SCORE_ENGINE_V2` (2.0.0), and `BREAKOUT_V3` (3.0.0). Each analyzer returns `strategy_name` and `strategy_version` with the common CALL/PUT/WAIT analysis fields.
- Live analysis uses `STRATEGY_NAME` from the environment; the default is `SCORE_ENGINE_V2`. Existing deployments need no new environment variable.
- Signal-history SQLite schema is migrated additively with nullable strategy identity columns. New live signal rows store the active strategy name/version; old rows remain queryable and appear as `LEGACY` in strategy analytics.
- `GET /api/strategies` returns registered strategies, historical signal counts, wins, losses, win rates, and automatic rank. Ranking sorts by completed-outcome win rate, then completed sample size. Pending, WAIT/skipped, and flat outcomes do not count in win-rate denominators.
- `GET /api/strategy-comparison?symbol=EUR%2FUSD&timeframe=1m&expiry=1&candle_count=500` runs all registered strategies on the same historical candle sample and returns a ranked comparison.
- The main dashboard includes a Strategy Leaderboard with Strategy, Signals, Wins, Losses, and Win Rate columns, plus a control to compare all strategies for the selected pair.
- The existing `/api/backtest` remains backward-compatible and defaults to `SCORE_ENGINE_V2`; the Python `run_backtest()` function also accepts an optional `strategy_name`. Use `run_strategy_backtest()` for one strategy and `run_all_strategies()` / `run_strategy_comparison()` for all three.
- A11KSA candle-only mode continues to disable signal analytics and strategy comparison endpoints.
- Strategy comparison is a historical heuristic, not a guarantee. It uses prefix-only candle history and directional close-to-close outcomes, not binary-options payouts, spread, fees, slippage, or executable fills.

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


## Release v1.0.1 — repository quality and runtime resilience

This release candidate adds:
- Isolated unit tests for backtesting and adaptive pair classification.
- Pytest and branch-coverage configuration plus a GitHub Actions workflow that publishes terminal, XML, and HTML coverage artifacts.
- Process-local HTTP execution-time and peak resident-memory metrics at `GET /api/metrics`.
- A non-blocking startup audit so optional audit work no longer delays the ASGI application becoming ready.
- Graceful cancellation of the scheduled refresh and startup-audit tasks.
- A scheduler-level exception boundary so an unexpected symbol iteration error is logged and retried rather than terminating the background loop.
- Application version metadata set to `1.0.1`.

### Development checks

Install development dependencies and run the suite:

```bash
python -m pip install -r requirements-dev.txt
pytest --cov --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html:htmlcov
```

The coverage workflow uploads `coverage.xml` and `htmlcov/` as the `python-test-coverage` artifact. Coverage is not claimed until the workflow has completed successfully.

### Runtime metrics

`GET /api/metrics` reports process-local request count, average and maximum HTTP request duration, and best-effort peak RSS memory. Metrics reset on process restart and are independent per worker; they are operational diagnostics, not host-wide monitoring.
