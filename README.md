# Multi-Pair Standard Forex Chart, Signals & History

Read-only dashboard for Twelve Data standard forex OHLC. This project is not affiliated with Quotex and does not fetch Quotex OTC prices or place trades.

## Features

- Configurable multi-pair watchlist and rotating signal scans.
- Dashboard pair selector, cached chart data, and per-pair Telegram summaries.
- Candlestick chart with EMA(9), EMA(21), and Bollinger Bands.
- MACD (12, 26, 9), RSI(14), and rolling 20-candle support/resistance.
- SQLite signal history with a simple five-candle later price comparison.
- Heuristic 1-minute vs 2-minute expiry suggestion and a signal-strength label.
- Candle-window freshness label; updates remain dependent on scheduled REST polling, not tick-by-tick streaming.

## Important: Quotex assets versus Twelve Data

The `/api/assets` endpoint returns Twelve Data's standard forex pair catalogue. Twelve Data does **not** provide the full Quotex-specific asset catalogue, OTC suffixes, or guaranteed matching Quotex OTC/synthetic prices. Therefore, this bot cannot truthfully claim to scan every asset shown in Quotex or send exact Quotex OTC signals. The data and Telegram alerts are labelled **standard forex, not Quotex OTC**.

Official pair-catalogue docs: https://twelvedata.com/docs (see `/forex_pairs`).

## Configure the watchlist

In Render → your web service → Environment, set `FOREX_SYMBOLS` as a comma-separated list of pairs supported by your Twelve Data plan. Example:

```text
EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD,USD/CHF,NZD/USD,EUR/GBP,EUR/JPY,GBP/JPY
```

The dashboard selector and scheduled Telegram alerts use this configured watchlist. You can add or remove pairs there and redeploy. A pair must be supported by your Twelve Data plan; not every catalogue symbol is necessarily available on the free plan. The `/api/assets` endpoint can list the full Twelve Data catalogue, but it does not mean every symbol is available for candle data under your plan.

## Free quota and rotation

The scheduler makes **one candle request per refresh interval** and rotates to the next configured symbol. The minimum interval is 300 seconds (five minutes). With 10 pairs, each pair is scanned about every 50 minutes while the service remains awake. With N pairs, the approximate per-pair scan interval is N × 5 minutes.

At five minutes, total usage is about 288 candle requests/day if the service runs continuously, regardless of watchlist size. This leaves some of the stated 800 daily credits for status checks and manual requests, though each API endpoint may have its own credit cost and limits can change. Avoid repeated manual refreshes.

The free Render service can spin down while idle; the scheduler pauses during sleep and resumes after the service wakes. This is scheduled REST polling, not a tick-by-tick stream. The current five-minute minimum means a configured pair may only be revisited every N × 5 minutes (N = watchlist size), so it cannot guarantee an actionable signal during every 1-minute candle. True live updates require a suitable real-time feed/plan and a quota budget that supports the desired polling frequency.

The expiry hint compares EMA trend, MACD histogram, and the last three candle directions. It is a simple heuristic, not a trained model, tested probability, or guarantee; use demo testing before relying on it. A 1-minute/2-minute expiry is not equivalent to a 1-minute/2-minute candle.

## Twelve Data setup

1. Create a free account at https://twelvedata.com and copy your API key.
2. In Render → Environment, set `TWELVE_DATA_API_KEY`.
3. Deploy the latest commit.
4. Open `/api/status` to check the key and `/api/watchlist` to view configured pairs and scan intervals.

## Optional Telegram alerts

1. Create a bot with Telegram's official `@BotFather` and copy its token.
2. Open the bot chat and send it a message; for a group, add the bot to the group and ensure it can send messages.
3. Obtain your chat ID using a trusted Telegram bot/API method.
4. In Render → Environment, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
5. Redeploy. Never put tokens in source code, GitHub, or chat.

Alerts contain the symbol, CALL/PUT/WAIT heuristic, RSI, MACD histogram, and support/resistance. Each symbol is tracked independently; the first signal is sent, then notifications are sent only when that symbol's signal changes.

## Environment variables

- `TWELVE_DATA_API_KEY` — required.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — optional, both needed for alerts.
- `FOREX_SYMBOLS` — comma-separated watchlist; defaults to 10 major/minor pairs in `render.yaml`.
- `REFRESH_INTERVAL_SECONDS` — defaults to 300 and cannot be set below 300.
- `FOREX_TIMEFRAME_SECONDS` — defaults to 60.
- `DATABASE_PATH` — defaults to `/tmp/forex_signal_history.db`.

## Endpoints

- `/health`: service health.
- `/api/status`: Twelve Data key/usage check.
- `/api/assets`: Twelve Data's available standard forex catalogue (one provider request).
- `/api/watchlist`: configured pairs, cached statuses, and estimated scan interval per pair.
- `/api/latest?asset=EUR%2FUSD`: read a cached pair snapshot; no Twelve Data candle request.
- `/api/candles?asset=EUR%2FUSD&timeframe_seconds=60&limit=100`: direct candle request.
- `/api/analysis?asset=EUR%2FUSD&timeframe_seconds=60&limit=100`: one-off analysis request.
- `POST /api/refresh?asset=EUR%2FUSD`: force a fresh request for a configured pair; uses quota.
- `/api/history?limit=50`: cross-pair signal history and summary.

## Signal history limitations

A signal is recorded once per candle timestamp. After five candles, CALL/PUT records are marked WIN/LOSS/FLAT based on whether the standard forex close moved in the indicated direction; WAIT records become SKIPPED. This is a simplified price-direction comparison, not actual trading results or a backtest.

SQLite history defaults to `/tmp` and **can be lost on Render free service restart/redeploy**. Use persistent storage or an external database if durable history is needed.

## Disclaimer

All market data is standard forex, not Quotex OTC/synthetic pricing. OTC prices can differ. CALL/PUT/WAIT labels are unvalidated heuristics, not financial advice, and do not guarantee future outcomes.
