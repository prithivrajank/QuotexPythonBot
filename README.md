# Standard Forex Chart, Signals & History

Read-only dashboard for Twelve Data standard forex OHLC. This project is not affiliated with Quotex and does not fetch Quotex OTC prices or place trades.

## Features

- Candlestick chart with EMA(9), EMA(21), and Bollinger Bands.
- MACD (12, 26, 9) histogram and signal line.
- RSI(14), 20-candle support and resistance.
- Scheduled market refresh every five minutes while the Render service is awake.
- Optional Telegram CALL/PUT/WAIT summaries; alerts are sent on the first signal and when the signal changes, to reduce spam.
- SQLite signal history and a simple five-candle later price comparison.

## Twelve Data setup

1. Create a free account at https://twelvedata.com and copy the API key.
2. In Render → your service → Environment, set `TWELVE_DATA_API_KEY`.
3. Deploy the latest commit.
4. Open `/api/status` to check the key and `/api/latest` to check the scheduled cache.

Twelve Data's free plan has a daily credit limit. The scheduler clamps the interval to at least 300 seconds, or about 288 candle requests per day if it runs continuously. Browser polling reads the cached snapshot and does not use provider credits. The manual **Refresh now** button makes one extra candle request. The API status check may also use a credit.

Free Render web services can spin down when idle. While the service is asleep, the scheduler cannot run; it refreshes again when the service wakes. The free Twelve Data REST API is polled, not a tick-by-tick WebSocket stream.

## Optional Telegram alerts

1. In Telegram, create a bot using the official `@BotFather` and copy its token.
2. Open a chat with your bot and send it a message; for a group, add the bot to the group and ensure it can send messages.
3. Obtain your chat ID using a trusted Telegram bot/API method.
4. In Render → Environment, set:
   - `TELEGRAM_BOT_TOKEN` = the bot token
   - `TELEGRAM_CHAT_ID` = your personal or group chat ID
5. Redeploy. Do not paste tokens into chat, source code, or GitHub. If these variables are absent, the dashboard and scheduled data still work without Telegram.

Telegram messages contain the current heuristic signal and indicator summary. To avoid alert spam, notifications are sent for the first generated signal and later signal changes, not every five-minute refresh.

## Environment variables

- `TWELVE_DATA_API_KEY` — required.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — optional, both required to send alerts.
- `REFRESH_INTERVAL_SECONDS` — defaults to 300 and cannot be set below 300.
- `FOREX_SYMBOL` — defaults to `EUR/USD`.
- `FOREX_TIMEFRAME_SECONDS` — defaults to 60.
- `DATABASE_PATH` — defaults to `/tmp/forex_signal_history.db`.

## Endpoints

- `/health`: service health.
- `/api/status`: Twelve Data key/usage check.
- `/api/assets`: current forex symbol list.
- `/api/candles?asset=EUR%2FUSD&timeframe_seconds=60&limit=100`: direct candle request.
- `/api/analysis?asset=EUR%2FUSD&timeframe_seconds=60&limit=100`: one-off analysis request.
- `/api/latest`: cached scheduled result; does not call Twelve Data.
- `POST /api/refresh`: force a fresh request; uses provider quota.
- `/api/history?limit=50`: signal history and summary.

## Signal history limitations

A signal is recorded once per candle timestamp. After five candles, CALL/PUT records are marked WIN/LOSS/FLAT based on whether the standard forex close moved in the indicated direction; WAIT records become SKIPPED. This is only a simplified price-direction comparison, not a backtest, trade execution, or verified return.

SQLite history defaults to `/tmp` and **can be lost on Render free service restart/redeploy**. Set `DATABASE_PATH` to a genuinely persistent mounted path or add an external database if durable history is needed. The current free Render filesystem should not be assumed persistent.

## Disclaimer

All market data is standard forex, not Quotex OTC/synthetic pricing. OTC prices can differ. CALL/PUT/WAIT labels are unvalidated heuristics, not financial advice, and do not guarantee future outcomes.
