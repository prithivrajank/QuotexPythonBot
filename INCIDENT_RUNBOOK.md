# Incident Runbook — QuotexPythonBot

## Incident handling principles

- Preserve demo/read-only boundaries. Do not place trades or change account mode while diagnosing an incident.
- Never request or disclose API keys, session IDs, cookies, bot tokens, or other credentials in chat, tickets, screenshots, or logs.
- Capture UTC timestamps, Render service/deployment ID, commit SHA, provider name, affected symbol(s), and sanitized error messages.
- A single symbol/provider failure should be isolated; do not restart the entire service unless the process is unhealthy or recovery steps require it.
- Distinguish process liveness (`/health`) from dependency health (`/api/health`).
- Process-local telemetry resets on restart and differs across multiple workers.

## Initial triage

1. Check Render service Events and logs for crashes, restarts, deploy changes, and resource exhaustion.
2. Request `/health`, then `/api/health` and `/api/metrics`.
3. Check `/api/system/audit` for subsystem-level findings.
4. Identify the affected component and time window.
5. Check whether the issue affects one symbol, all symbols, one worker, or the whole service.
6. Record evidence before restarting or rolling back.

## WebSocket failures

### Symptoms
- Dashboard shows disconnected/stale stream.
- WebSocket connection to `/ws/market` closes or repeatedly reconnects.
- Health monitor reports WebSocket degraded/disconnected.

### Response
1. Confirm `/health` is HTTP 200 and the dashboard REST endpoints still respond.
2. Inspect Render logs for connect/disconnect events and sanitized exception details.
3. Check the selected provider supports streaming for the configured symbol/account mode. Some provider modes are REST/manual-refresh only.
4. Refresh the browser page and reconnect once; verify client heartbeat behavior and browser network errors.
5. Check whether Render Free instance spin-down or restart explains the disconnect. A connected browser alone does not guarantee permanent uptime.
6. If only one symbol fails, remove/isolate that symbol from the staging watchlist and verify the remaining symbols continue.
7. If the service process is wedged, redeploy the last known-good commit using the deployment runbook.

### Recovery verification
- WebSocket client reconnects and health status updates.
- REST dashboard remains available.
- Candle/tick timestamps advance for supported provider modes.
- No repeated reconnect/error loop appears in logs.

## Database failures

### Symptoms
- `/api/health` reports database down/degraded.
- Logs show SQLite locked, I/O, schema, or write errors.
- Signal history or weekly report endpoints fail or stop updating.

### Response
1. Stop repeated write-triggering actions if lock contention is suspected.
2. Capture the sanitized SQLite exception, DB path, process count, and timestamp.
3. Confirm the configured `DATABASE_PATH` exists and the Render process has read/write permission.
4. Check whether the database is on ephemeral `/tmp` storage or persistent storage. Do not assume data survives a restart.
5. Avoid manually deleting the SQLite DB, WAL, or SHM files while the process is running.
6. If locked, allow the current transaction to finish; inspect concurrent workers/processes and connection lifetime. Do not repeatedly restart as a substitute for diagnosing lock contention.
7. Before migration or repair, stop writes and take a consistent backup/copy using a SQLite-safe backup method.
8. If the DB is corrupt or data is missing, restore only from a verified backup and obtain database-owner approval.
9. If a release introduced schema incompatibility, roll back application code only after confirming the old code can read the migrated schema; otherwise use a forward-fix/recovery plan.

### Recovery verification
- Database check passes in `/api/health`.
- `/api/history` and `/api/weekly-report` return expected data.
- New test record can be written in staging and read back.
- History persistence is verified after a controlled staging restart.

## Telegram failures

### Symptoms
- Telegram component becomes degraded.
- Logs show timeout, HTTP errors, or delivery failure.
- Telegram notifications are absent.

### Response
1. Confirm Telegram is expected for the selected provider/mode. Some modes intentionally suppress notifications.
2. Check that `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured in Render Environment without printing their values.
3. Use the production audit's Telegram `getMe` check, if configured; it validates bot identity and does not send a message.
4. Check Telegram API reachability, rate limits, bot membership/permissions, and destination chat configuration.
5. Distinguish a failed notification from a failed market-data refresh; the market-data path should continue independently where designed.
6. Do not retry indefinitely or flood a chat. Apply bounded retries/backoff and respect Telegram rate limits.
7. If credentials may have leaked, rotate them in Telegram/Render and redeploy; never paste the old/new token into incident records.

### Recovery verification
- Telegram check passes.
- A controlled, explicitly approved staging test message is delivered if message testing is permitted.
- Notification failures are no longer increasing; candle refresh remains operational.

## Provider outages

### Symptoms
- Candle refresh fails or returns stale data.
- Provider component is degraded/down.
- HTTP 401/403/429, timeout, malformed JSON, invalid OHLC, or empty candle responses.

### Response
1. Determine the selected `MARKET_DATA_PROVIDER` from Render Environment; do not assume the blueprint default matches the live service.
2. Inspect sanitized provider error code/message and affected symbols/timeframes.
3. Check provider status, quota, instrument availability, account mode, and API plan. Do not expose keys/session identifiers.
4. Verify the returned candle timestamp and OHLC consistency. Reject malformed candles; never substitute mock/fake candles into a production feed.
5. If one symbol fails, isolate it and allow other symbols to continue. Do not treat a single symbol error as a reason to stop the entire bot.
6. Respect provider-specific request limits and refresh cadence. Avoid rapid manual retry loops after 429/quota errors.
7. If the provider is down, keep the service in a safe unavailable state and display the source/freshness accurately. Do not silently switch to an unrelated feed while labelling it as the original provider.
8. A11KSA remains fail-closed unless its demo-only authorization and real M1 candle delivery are independently verified. Do not bypass TLS or access restrictions.
9. If outage began immediately after deployment, compare the current commit/configuration with the previous known-good deployment and roll back if appropriate.

### Recovery verification
- Provider connection/status check succeeds.
- Fresh candles arrive for a supported staging symbol.
- Market type/source labels are correct (standard forex vs OTC).
- Other symbols continue refreshing independently.
- No synthetic fallback data is presented as live market data.

## Severity and escalation

- **SEV-1:** service-wide outage, data integrity/security incident, credential exposure, or unexpected account/trading activity. Contain immediately, stop rollout, rotate exposed credentials, and escalate to service owner.
- **SEV-2:** database unavailable, all provider data stale, or sustained dashboard/API failure. Pause release and follow rollback/recovery steps.
- **SEV-3:** isolated symbol, Telegram, or WebSocket issue while core service remains available. Isolate component/symbol and monitor.
- **SEV-4:** cosmetic dashboard or non-critical reporting issue. Log and schedule a fix.

## Incident closure

Record start/end time, impact, affected symbols/components, root cause, mitigation, rollback status, data-loss assessment, recovery evidence, and follow-up actions with owners and due dates. Do not close an incident solely because `/health` returns HTTP 200.
