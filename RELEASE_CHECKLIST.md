# Release Readiness Checklist — v1.0.1

> Status: **NOT APPROVED FOR PRODUCTION RELEASE** until all blocking items below are closed.
> Reviewed against branch `release/v1.0.1` on 2026-11-09. This is a source/configuration review, not a live Render or database verification.

## Review summary

### Blocking issues

- [ ] **CI test suite is failing.** GitHub Actions run [Tests and coverage](https://github.com/prithivrajank/QuotexPythonBot/actions/runs/42639448195) completed with `failure`. Dependency installation passed; the pytest/coverage step failed. Inspect the job output, fix failures, and rerun before release.
- [ ] **Release branch has no published GitHub Release or v1.0.1 tag.** The branch exists; the repository Releases API returned no releases at review time.
- [ ] **Open draft PR #6 is explicitly WIP.** Its body says live authentication/feed is not verified and no merge/deployment is authorized. Do not treat A11KSA as production-ready until that separate verification and approval are complete.
- [ ] **Open PR #2 is a revert of PR #1.** Resolve its intended outcome before merging/releasing the A11KSA-related changes.
- [ ] **Render environment is not verified.** `render.yaml` defaults `MARKET_DATA_PROVIDER=quotexapi` and declares `QUOTEX_SSID` as a secret environment entry. Confirm the actual staging/production service configuration and approved provider/account mode without exposing credentials. Never copy session values into Git or logs.
- [ ] **Persistent database storage is not established by the checked-in Render blueprint.** `DATABASE_PATH=/tmp/forex_signal_history.db` is ephemeral on Render unless a supported persistent disk is explicitly configured. Signal history and weekly health snapshots may be lost on restart/redeploy.

### Warnings

- [ ] `/health` is a simple liveness response; it does not prove provider, database, Telegram, or strategy readiness.
- [ ] `/api/health` and most operational counters are process-local. Multiple workers/instances can report different values; counters reset on restart.
- [ ] `/api/metrics` memory and request-duration data are process-local best-effort metrics, not host-wide telemetry.
- [ ] `/api/resilience` executes in-memory fault simulations; its success rate is not real-world recovery SLO or uptime.
- [ ] Dashboard rankings cache is process-local with a 60-second TTL. Other dashboards/endpoints should be checked for independent cache policy.
- [ ] The backtester uses historical candle closes and heuristic signal evaluation. Its profit factor is not broker payout-adjusted and does not model slippage, spread, execution latency, or fills.
- [ ] SQLite schema evolution is implemented additively at application startup, not as a versioned migration framework. Concurrent worker startup/migration behavior has not been load-tested.
- [ ] `render.yaml` includes several provider credentials as unsynchronized environment variables. Set only the selected provider's required secrets in Render; do not paste secrets into documentation or source control.
- [ ] The README describes unofficial provider integrations and account-mode settings. Verify provider terms, credentials, supported symbols, and demo/real separation before enabling any provider.

### Recommendations

- [ ] Require the test-and-coverage workflow to pass before merge; retain XML/HTML coverage artifacts.
- [ ] Add dedicated tests for API route contracts, startup/shutdown, SQLite migration from older schemas, cache expiration, and provider outage isolation.
- [ ] Add an explicit migration version table and backup-before-migrate procedure before introducing destructive schema changes.
- [ ] Add persistent storage or an external managed database before relying on signal history/weekly reports across Render restarts.
- [ ] Define readiness semantics separately from liveness; keep `/health` cheap and add dependency readiness checks with bounded timeouts.
- [ ] Add structured logs with request IDs, symbol/provider context, and secret redaction.
- [ ] Define alert thresholds and retention for memory, request latency, provider errors, DB errors, WebSocket disconnects, and Telegram failures.
- [ ] Verify all dashboard pages and API endpoints using an automated smoke-test suite against a staging deployment.
- [ ] Review open TODO/FIXME/HACK markers manually. GitHub code search returned no indexed TODO matches at review time, but its response was marked incomplete; this is **not** proof that the repository contains none.

## Pre-release

- [ ] Confirm release commit and branch protection/review approvals.
- [ ] Review every open PR and issue; resolve #6 and #2 deliberately.
- [ ] Search repository and dependencies for TODO, FIXME, HACK, XXX, and temporary debug code; record owner and disposition.
- [ ] Confirm environment variables and provider selection with the service owner.
- [ ] Confirm persistent database strategy and backup/restore procedure.
- [ ] Confirm the release is demo/read-only where required; no unapproved trading or account actions.
- [ ] Confirm secrets are stored only in Render Environment and are redacted from logs.

## Testing

- [ ] Install development dependencies: `pip install -r requirements-dev.txt`.
- [ ] Run: `pytest --cov --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html:htmlcov`.
- [ ] Confirm tests cover `strategies.py`, `backtester.py`, `signal_history.py`, and `pair_performance.py`.
- [ ] Fix the currently failing GitHub Actions run and rerun until green.
- [ ] Test old SQLite schema migration against a copy of a production-like database.
- [ ] Smoke-test every API and dashboard route listed in DEPLOYMENT_RUNBOOK.md.
- [ ] Test provider timeout, malformed candle, one-symbol failure, DB locked, Telegram timeout, WebSocket reconnect, and graceful shutdown.
- [ ] Verify A11KSA mode remains fail-closed, demo-only, read-only, and does not send signal notifications.

## Deployment

- [ ] Deploy to staging first using the reviewed release commit.
- [ ] Confirm Render build succeeds and service binds to `0.0.0.0:$PORT`.
- [ ] Confirm `/health` returns HTTP 200.
- [ ] Confirm `/api/health`, `/api/metrics`, `/api/system/audit`, and selected-provider endpoints behave as expected.
- [ ] Confirm dashboard loads and no critical browser-console/network errors occur.
- [ ] Verify database persistence and schema compatibility after a staging restart.
- [ ] Obtain explicit release approval before production deployment.

## Rollback

- [ ] Record the currently deployed commit SHA and Render deployment ID before release.
- [ ] Keep the previous known-good Render deployment available for rollback.
- [ ] If health checks fail, provider errors spike, or DB errors occur, stop rollout and redeploy the previous known-good commit.
- [ ] Do not roll back by deleting or overwriting database files. Restore from a verified backup if data recovery is required.
- [ ] If a schema change is not backward-compatible, use a documented forward-fix or restore plan; do not assume code rollback reverses a migration.
- [ ] Verify `/health`, `/api/health`, dashboard, and DB access after rollback.

## Monitoring

- [ ] Monitor Render deploy/build logs and application logs.
- [ ] Monitor `/health` for process liveness.
- [ ] Monitor `/api/health` for component state and health score.
- [ ] Monitor `/api/metrics` for request count, average/max request duration, and peak RSS.
- [ ] Monitor `/api/system/audit` for startup/integration audit warnings.
- [ ] Monitor provider freshness, candle timestamps, and per-symbol error messages.
- [ ] Monitor WebSocket client connections/reconnects.
- [ ] Monitor Telegram delivery failures only when Telegram is configured and expected.
- [ ] Treat resilience-suite output as simulated test results, not production recovery telemetry.

## Post-release verification

- [ ] Confirm deployed commit SHA matches approved release commit.
- [ ] Confirm Render reports deployment live and no repeated restart/crash loop.
- [ ] Verify liveness, dependency health, metrics, and dashboard pages.
- [ ] Verify database schema and that history survives a restart when persistence is expected.
- [ ] Verify selected provider returns real, correctly labelled candles for an approved demo symbol.
- [ ] Verify a failed symbol does not stop refresh of other symbols.
- [ ] Verify graceful shutdown does not leave background tasks running.
- [ ] Verify no secrets appear in logs, API responses, dashboard HTML, or reports.
- [ ] Record final test run URL, coverage artifact, deployment ID, smoke-test results, and release approver.
