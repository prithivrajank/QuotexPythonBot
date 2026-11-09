# Staging Smoke Test — QuotexPythonBot

## Validation status

**Result: NOT EXECUTED against the live staging service from this review.**

Target recorded for staging: `https://quotex-a11ksa-staging.onrender.com`

The staging host did not return an accessible response through the available validation channel. No HTTP status, response body, or Render deployment identity could be independently observed. The endpoint checks below are therefore an executable checklist and expected contract, not claimed test results.

Before testing, record the deployed branch/commit, Render deploy ID, selected `MARKET_DATA_PROVIDER`, and timestamp. Run only against staging.

## Endpoint checks

| Endpoint | Expected HTTP | Expected response / assertions |
|---|---:|---|
| `GET /api/health` | 200 | JSON object containing `health_score`, `status`, component statuses including `database` and `provider`, and `uptime_seconds`. Health score is process-local and may be WARNING/CRITICAL when optional services are not configured. |
| `GET /api/system/audit` | 200 | JSON object with `overall_status` (`PASS`, `WARNING`, or `FAIL`), `passed_checks`, `failed_checks`, `warnings`, `version`, and per-check `checks`. HTTP 200 means the audit executed; it does not mean the audit passed. Require `overall_status=PASS` for release sign-off, or explicitly accept documented warnings. |
| `GET /api/metrics` | 200 | JSON object with `request_count`, `average_request_seconds`, `max_request_seconds`, `memory.peak_rss_mb`, `memory.available`, and a process-local scope note. Values reset on process restart and are per worker. |
| `GET /api/backtest?symbol=EURUSD_otc&timeframe=1m&expiry=1&candle_count=500` | 200 on supported non-A11KSA provider; 404 in A11KSA candle-only mode | Successful JSON includes backtest metrics such as `total_signals`, `wins`, `losses`, `win_rate`, `profit_factor`, `best_asset`, `best_expiry`, `strategy_version`, `expiry_comparison`, `timeframe`, `timeframe_seconds`, `source`, and `market_type`. A11KSA deliberately disables this endpoint. Provider/data failures may return 502; invalid query values return 422. |
| `GET /api/walkforward?symbol=EURUSD_otc&timeframe=1m&expiry=1&candle_count=500` | 200 on supported non-A11KSA provider; 404 in A11KSA candle-only mode | Successful JSON includes `training_win_rate`, `validation_win_rate`, `overfit_score`, `strategy_health` / `status`, `timeframe`, `timeframe_seconds`, `source`, and `market_type`. A11KSA deliberately disables this endpoint. Requires at least 110 candles; invalid input returns 422 and provider/data failures may return 502. |

**Important provider-mode distinction:** The staging hostname is the A11KSA staging service. If its deployed `MARKET_DATA_PROVIDER=a11ksa`, 404 from backtest and walk-forward is the expected safety behavior, not a smoke-test failure. Do not switch providers or enable a different mode solely to force these two endpoints to return 200. If testing a non-A11KSA release candidate, use a separate staging deployment configured for the approved provider and its own valid data credentials.

## Commands (PowerShell)

```powershell
$base = "https://quotex-a11ksa-staging.onrender.com"

# Operational endpoints
Invoke-RestMethod "$base/api/health" | ConvertTo-Json -Depth 10
Invoke-RestMethod "$base/api/system/audit" | ConvertTo-Json -Depth 10
Invoke-RestMethod "$base/api/metrics" | ConvertTo-Json -Depth 10

# These are expected to return 404 when MARKET_DATA_PROVIDER=a11ksa.
# For a supported non-A11KSA staging provider, expect JSON 200 responses.
try {
  Invoke-RestMethod "$base/api/backtest?symbol=EURUSD_otc&timeframe=1m&expiry=1&candle_count=500" |
    ConvertTo-Json -Depth 10
} catch {
  $_.Exception.Response.StatusCode.value__
  $_.ErrorDetails.Message
}

try {
  Invoke-RestMethod "$base/api/walkforward?symbol=EURUSD_otc&timeframe=1m&expiry=1&candle_count=500" |
    ConvertTo-Json -Depth 10
} catch {
  $_.Exception.Response.StatusCode.value__
  $_.ErrorDetails.Message
}
```

## Pass/fail criteria

- [ ] Confirm deployment identity (branch, commit SHA, Render deploy ID).
- [ ] `/api/health` returns HTTP 200 and database status is healthy.
- [ ] `/api/system/audit` returns HTTP 200; inspect every failed check and warning. A non-PASS audit blocks production until accepted or fixed.
- [ ] `/api/metrics` returns HTTP 200 and structurally valid metrics.
- [ ] Confirm selected provider. For A11KSA, 404 on backtest and walk-forward is expected and confirms their deliberate disablement.
- [ ] For a separately approved non-A11KSA staging deployment, backtest and walk-forward return 200 with the documented response fields.
- [ ] Confirm persistence by writing a harmless test record only in an approved staging procedure, redeploying/restarting staging, and verifying the record survives. Do not perform this against production.
- [ ] Attach sanitized outputs (remove secrets, identifiers, and sensitive provider details) and timestamp to the release record.

## Limitations

- `/api/health` and `/api/metrics` are process-local observations, not a multi-instance readiness or uptime guarantee.
- `/api/system/audit` checks configured subsystems; it does not prove provider feed quality or durable storage.
- Backtest and walk-forward are historical research calculations using directional close-to-close outcomes, not executable fills or broker payout-adjusted returns.
- A11KSA mode intentionally disables signal, backtest, and walk-forward functionality and remains fail-closed pending independent live demo/read-only verification.
