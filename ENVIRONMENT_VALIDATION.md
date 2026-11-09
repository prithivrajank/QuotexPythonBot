# Environment Validation — QuotexPythonBot

## Result

**Environment validation: INCOMPLETE — NOT READY for production.**

This review inspected the checked-in `release/v1.0.1` source and `render.yaml`. It did not have access to the Render service's private Environment page, so it cannot verify which values are actually present, whether secret values are valid, or whether the deployed service matches the blueprint. No secret values should be copied into this report.

Blueprint reviewed: `render.yaml` (service `quotex-live-signal-bot`), branch `release/v1.0.1`.

## Render blueprint values

| Variable | Blueprint value | Required / conditional | Validation |
|---|---|---|---|
| `PYTHON_VERSION` | `3.11.11` | Runtime pin | Defined in blueprint; deployed version not verified |
| `MARKET_DATA_PROVIDER` | `quotexapi` | Required; select exactly one provider | Defined; confirm actual Render value |
| `QUOTEX_SSID` | Secret, unset in Git | Required for `quotexapi` | Must be configured privately and validated; never expose it |
| `QUOTEX_ACCOUNT` | `demo` | Required operational mode for Quotex adapter | Blueprint says demo; verify actual service is demo |
| `QUOTEX_IS_DEMO` | Default `true` (legacy fallback) | Legacy fallback if account mode is not set | Prefer explicit `QUOTEX_ACCOUNT=demo`; do not set live |
| `QUOTEX_RETRY_COOLDOWN_SECONDS` | Default `300` (minimum 60) | Optional | App default applies |
| `TWELVE_DATA_API_KEY` | Secret, unset in Git | Required only for `twelve_data` | Not required for current `quotexapi` default |
| `QUANTEX_API_KEY` | Secret, unset in Git | Required only for `quantex` | Not required for current default |
| `QUANTEX_BROKER` | `quotex` | Required only for `quantex`; default `quotex` | Defined |
| `OTCHARTS_API_KEY` | Secret, unset in Git | Required only for `otcharts` | Not required for current default |
| `TELEGRAM_BOT_TOKEN` | Secret, unset in Git | Optional; needed with chat ID for Telegram | If enabled, validate privately |
| `TELEGRAM_CHAT_ID` | Secret/sensitive, unset in Git | Optional; needed with bot token | If enabled, validate privately |
| `REFRESH_INTERVAL_SECONDS` | `300` | Optional | App clamps to at least 300 seconds |
| `FOREX_SYMBOLS` | `EURUSD_otc,GBPUSD_otc,USDJPY_otc,EURUSD,GBPUSD,USDJPY` | Optional; provider-specific symbols | Verify every symbol is supported by selected provider |
| `FOREX_TIMEFRAME_SECONDS` | `60` | Optional | Blueprint specifies 60 seconds |
| `DATABASE_PATH` | `/tmp/forex_signal_history.db` | Required for predictable storage location | <badge color="danger">Unsafe for durable history</badge> Must be changed to persistent mount path |
| `QUOTEX_ACCOUNT` | `demo` | Required for Quotex API mode | Keep demo during staging |

## Additional application-supported variables

These are read by application modules but are not all declared in `render.yaml`. Set only when the corresponding feature is required.

| Variable | Default / purpose | Recommendation |
|---|---|---|
| `FOREX_SYMBOL` | Legacy single-symbol fallback | Prefer `FOREX_SYMBOLS`; do not set both inconsistently |
| `STRATEGY_NAME` | Strategy override; registry default applies | Optional; verify selected strategy in audit/strategy API |
| `AUTO_STRATEGY_SELECTION` | Automatic strategy management | Optional; confirm intended operating policy |
| `STRATEGY_PROMOTION_MIN_SIGNALS` | Minimum completed signals for measured promotion | Optional; default is applied by app |
| `WEEKLY_REPORT_DIR` | Defaults to `/tmp/weekly_reports` | Set under persistent mount if report exports must survive restarts |
| `AUDIT_REPORT_PATH` | Defaults to `/tmp/audit_report.json` | Set under persistent mount if exported audit file must persist |
| `RESILIENCE_REPORT_PATH` | Defaults to `/tmp/resilience_report.json` | Set under persistent mount if exported report must persist |

## Provider-specific configuration

Configure only the selected provider. Do not populate unrelated provider secrets just because the blueprint lists them.

### Current blueprint default: `quotexapi`

- `MARKET_DATA_PROVIDER=quotexapi`
- `QUOTEX_SSID` — required private credential
- `QUOTEX_ACCOUNT=demo` — explicit demo mode
- `FOREX_SYMBOLS` — only supported instruments
- `FOREX_TIMEFRAME_SECONDS=60` — intended candle timeframe
- Never use a real-account session for staging validation.

### Alternative standard forex provider

- `MARKET_DATA_PROVIDER=twelve_data`
- `TWELVE_DATA_API_KEY` required.
- Data must be labelled standard forex, not Quotex OTC.

### Alternative OTC providers

- `MARKET_DATA_PROVIDER=quantex` requires `QUANTEX_API_KEY`; `QUANTEX_BROKER` defaults to `quotex`.
- `MARKET_DATA_PROVIDER=otcharts` requires `OTCHARTS_API_KEY`; implementation is manual-refresh-only to protect provider quota.

### A11KSA isolated candle-only mode

- `MARKET_DATA_PROVIDER=a11ksa` selects a fail-closed adapter in the reviewed code.
- The adapter deliberately returns unavailable and does not open a session until live demo authorization and real 60-second candle delivery are independently verified.
- Do not create, request, paste, or configure an A11KSA session identifier to bypass this guard. The transport's `QUOTEX_DEMO_SSID` reference is not an approved production requirement; it must not be used as a workaround.

## Database path, /tmp, and Render persistence

The reviewed source uses SQLite:

- `signal_history.py`: `DATABASE_PATH`, default `/tmp/forex_signal_history.db`.
- `weekly_report.py`: shares `DATABASE_PATH`; default export directory `/tmp/weekly_reports`.
- `production_checklist.py`: audit export defaults to `/tmp/audit_report.json`.
- `resilience.py`: report export defaults to `/tmp/resilience_report.json`.

The checked-in Render blueprint explicitly sets `DATABASE_PATH=/tmp/forex_signal_history.db`. Render's ephemeral filesystem does not provide durable storage across service restarts/redeploys. This risks loss of signal history, weekly health snapshots, and generated reports.

**Required before production if SQLite history must persist:**

1. Attach a persistent Render disk to the production Web Service (Render persistent disks are a paid-plan feature; the free web-service filesystem is ephemeral).
2. Choose the disk mount path in Render, for example `/var/data`.
3. Set `DATABASE_PATH=/var/data/forex_signal_history.db`.
4. If exports must persist, also set:
   - `WEEKLY_REPORT_DIR=/var/data/weekly_reports`
   - `AUDIT_REPORT_PATH=/var/data/audit_report.json`
   - `RESILIENCE_REPORT_PATH=/var/data/resilience_report.json`
5. Ensure the service process can write to the mount; keep the SQLite DB on one service instance/worker unless concurrency and locking are designed and tested.
6. Back up the existing DB before changing paths or deploying. Copy/restore existing data deliberately; changing `DATABASE_PATH` creates/uses a different database file.

If a persistent disk is not acceptable, migrate history to a managed external database and update/verify the storage layer before production. Do not treat a free-tier `/tmp` database as persistent.

## Operator verification checklist

- [ ] Compare Render Environment variable *names* with this list; never paste values into tickets, chat, or Git.
- [ ] Confirm deployed branch and commit SHA match the intended release candidate.
- [ ] Confirm `MARKET_DATA_PROVIDER` is exactly the approved provider.
- [ ] Confirm only that provider's required secret is configured and accepted.
- [ ] Confirm `QUOTEX_ACCOUNT=demo` for Quotex staging.
- [ ] Confirm `FOREX_TIMEFRAME_SECONDS=60` and watchlist symbols.
- [ ] Confirm `REFRESH_INTERVAL_SECONDS` respects provider quota and the app's 300-second minimum.
- [ ] Confirm Telegram is intentionally configured or intentionally absent.
- [ ] Confirm `DATABASE_PATH` points to persistent disk or approved external database before production.
- [ ] Confirm report directories/paths are persistent if retention is required.
- [ ] Restart/redeploy staging and verify database records survive.
- [ ] Save a sanitized validation record with presence/absence and pass/fail only; do not record secret values.

## Final environment status

**NOT VERIFIED.** Blueprint defaults are documented, but live Render values, credential validity, persistent disk attachment, and deployed configuration were not accessible during this review.
