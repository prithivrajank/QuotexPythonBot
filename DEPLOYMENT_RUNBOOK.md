# Deployment Runbook — QuotexPythonBot v1.0.1

## Scope and safety

This runbook describes deployment to Render. It does not authorize a production rollout. Use staging first and obtain approval before changing the primary service. Keep provider integrations within their approved read-only/demo scope. Never put API keys, session identifiers, cookies, or tokens in Git, chat, screenshots, or logs.

## Render deployment steps

1. Open the Render dashboard and select the intended **staging** Web Service.
2. Confirm the connected repository is `prithivrajank/QuotexPythonBot`.
3. Select the reviewed branch/commit. For this candidate, the branch is `release/v1.0.1`; record the exact commit SHA before deployment.
4. Confirm the build command is `pip install -r requirements.txt`.
5. Confirm the start command is `uvicorn main:app --host 0.0.0.0 --port $PORT`.
6. Confirm the health-check path is `/health`.
7. Review the environment variables below. Configure only the variables required by the selected provider and deployment. Enter secret values directly in Render's Environment UI.
8. Deploy staging. Watch build and runtime logs until the service reports Live.
9. Run the health and smoke checks below. Verify the dashboard, database persistence, and provider candle labels.
10. Obtain explicit approval before repeating the process against production. Do not change the primary service as part of a staging validation.

## Environment variables

The checked-in `render.yaml` currently declares these names/defaults. Actual service values must be verified in Render; this document does not imply that credentials are present or valid.

| Variable | Purpose | Handling |
|---|---|---|
| `PYTHON_VERSION` | Runtime version; blueprint specifies 3.11.11 | Non-secret |
| `MARKET_DATA_PROVIDER` | Provider selector; blueprint currently defaults to `quotexapi` | Choose only an approved provider |
| `QUOTEX_SSID` | Session credential for the unofficial QuotexAPI adapter | Secret; only if that integration is approved |
| `TWELVE_DATA_API_KEY` | Twelve Data API key | Secret; only for Twelve Data |
| `QUANTEX_API_KEY` | QUANTEX API key | Secret; only for QUANTEX |
| `OTCHARTS_API_KEY` | OTCharts API key | Secret; only for OTCharts |
| `QUANTEX_BROKER` | QUANTEX broker selector; blueprint says `quotex` | Non-secret |
| `TELEGRAM_BOT_TOKEN` | Telegram bot credential | Secret; optional |
| `TELEGRAM_CHAT_ID` | Telegram destination identifier | Treat as sensitive configuration |
| `REFRESH_INTERVAL_SECONDS` | Refresh interval; blueprint says 300 | Non-secret |
| `FOREX_SYMBOLS` | Comma-separated watchlist | Non-secret; verify supported symbols |
| `FOREX_TIMEFRAME_SECONDS` | Candle interval; blueprint says 60 | Non-secret |
| `DATABASE_PATH` | SQLite path; blueprint says `/tmp/forex_signal_history.db` | Must be on persistent storage if data must survive restarts |
| `QUOTEX_ACCOUNT` | Account mode; blueprint says `demo` | Keep demo for approved testing |

Do not configure all provider secrets merely because they appear in the blueprint. Set `MARKET_DATA_PROVIDER` to the single provider being used and only configure its required variables. Do not switch to real-account access as part of release validation. A11KSA's separate adapter remains fail-closed pending its own demo/read-only verification.

## Health checks

### Liveness

- `GET /health` — lightweight process liveness endpoint. Expected HTTP 200 and JSON status `ok`.
- Render's configured health-check path is `/health`. This endpoint does not prove provider or database readiness.

### Application and operational endpoints

- `GET /api/health` — component health snapshot (WebSocket, provider, Telegram, strategy, database).
- `GET /api/metrics` — process-local HTTP request count, average/max duration, and best-effort peak RSS memory.
- `GET /api/system/audit` — production checklist audit.
- `GET /api/system/audit/export` — audit JSON download.
- `GET /api/resilience` — isolated in-memory fault simulation; not a real provider/DB/Telegram probe.
- `GET /api/status`, `GET /api/bot` — bot/runtime state.
- `GET /api/assets`, `GET /api/candles`, `GET /api/latest`, `GET /api/watchlist` — market data and watchlist.
- `GET /api/analysis`, `GET /api/history`, `GET /api/rankings`, `GET /api/pair-performance` — analysis/history endpoints; provider mode may intentionally disable signal-oriented endpoints.
- `GET /api/backtest`, `GET /api/strategies`, `GET /api/strategy-manager`, `GET /api/strategy-comparison`, `GET /api/walkforward` — strategy/backtest endpoints.
- `GET /api/weekly-report`, `GET /api/validation-dashboard`, `GET /api/validation-dashboard/export.csv` — reporting/validation endpoints.
- `GET /api/ticks`, `WS /ws/market` — live tick/WebSocket interfaces when supported by selected provider.
- `POST /api/refresh`, `POST /api/bot/{action}` — state-changing refresh/control endpoints; use only in approved staging checks.

### Dashboard routes

- `/` — main dashboard
- `/market` — market/candles dashboard
- `/live` — live ticks page
- `/backtest` — backtesting dashboard
- `/validation` — validation dashboard
- `/system-audit` — system audit dashboard

Some routes/APIs redirect or are intentionally disabled for restricted provider modes. Check the selected provider mode before interpreting a 307/404 as a deployment defect.

### Database verification

Signal history uses SQLite and initializes/extends the `signal_history` schema with additive `ALTER TABLE ... ADD COLUMN` checks. Weekly health snapshots use an additional table. The reviewed Render blueprint points to `/tmp`, which is ephemeral. Configure a persistent Render disk/path or approved external database before relying on historical records. Back up the database before deploying schema changes.

## Rollback procedure

1. Stop further rollout. Record current deployment ID, commit SHA, logs, and incident time.
2. In Render, open the service's Events/Deploys history.
3. Select the last known-good deployment and use Render's rollback/redeploy-previous-version action where available; otherwise deploy the recorded previous commit.
4. Do not delete the database or restore an old database over newer data without a verified backup and explicit recovery plan.
5. If migration compatibility is uncertain, stop writes and involve the database owner before proceeding. Application rollback does not automatically reverse SQLite schema changes.
6. Verify `/health`, `/api/health`, `/api/metrics`, dashboard routes, and selected-provider candles.
7. Record the rollback commit/deployment ID and notify stakeholders.

## Deployment completion record

Record: service name, environment (staging/production), branch, commit SHA, Render deployment ID, deploy time, test workflow URL, coverage artifact, smoke-test results, database backup location, approver, and any warnings.
