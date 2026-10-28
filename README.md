# Quotex OTC Signal Bot (V2)

Experimental, signal-only dashboard for demo/paper testing. It does **not** place trades. Signal accuracy is **not validated**; signals are not guarantees.

## Deploy on Render

This repository includes `render.yaml` for a free Render web service. In Render, choose **New → Blueprint** and select this repository.

Before opening the dashboard, set these Environment variables in Render:
- `DASHBOARD_USERNAME`: choose a new dashboard username.
- `DASHBOARD_PASSWORD`: choose a long, unique dashboard password.

Render's `/health` check is public; the dashboard and API routes require HTTP Basic Authentication. Do not reuse your Quotex password as the dashboard password.

The service can run in **dashboard-only mode** when no Quotex credentials are configured and `ENABLE_COLLECTOR` is not true. No Quotex credentials are required for the first deployment.

## Optional data collector — read this first

The collector uses unofficial `pyquotex`. It can break, be blocked by anti-bot challenges, or behave inconsistently. Hosting on Render does not guarantee that the Quotex connection will succeed. Providing Quotex credentials to any cloud host carries account-security risk. Use demo credentials only if you knowingly accept this risk and have checked Quotex's applicable terms.

To enable the collector, set `ENABLE_COLLECTOR=true` **or** configure both `QUOTEX_EMAIL` and `QUOTEX_PASSWORD` as private Render environment variables. Configured credentials are treated as an opt-in even if an older service has a stale `ENABLE_COLLECTOR=false` setting. To force the collector off, set `DISABLE_COLLECTOR=true`. Never put credentials in code or GitHub. Do not upload `session.json`, cookies, tokens, OTPs, or `.env` files. Keep the account in demo mode. This app never places trades.

Optional variables:
- `OTC_PAIRS`: defaults to `EURUSD_otc,USDIDR_otc,USDJPY_otc,AUDCHF_otc`
- `POLL_SECONDS`: defaults to `60`
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: optional alerts; keep private.

## Endpoints

- `/`: authenticated dashboard
- `/api/status`, `/api/candles`, `/api/signals`: authenticated APIs
- `/health`: public Render health check

## Important Render free-tier limitations

Free web services may spin down after inactivity, and their local filesystem is ephemeral. CSV candle/signal files may be lost after a restart or redeploy, and this is not a reliable always-on recorder on the free tier. For long-running collection or durable historical data, use an appropriate persistent storage/service rather than relying on local CSV files.

## Local development

```bash
python -m venv .venv
# Windows CMD: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

For local use, set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`, then run:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
``

This is educational software, not financial advice. Use demo/paper testing only and do not infer profitability from signals or signal count.
