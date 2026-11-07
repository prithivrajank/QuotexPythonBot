# Isolated A11ksa installation and TLS verification

The GitHub Actions workflow in `.github/workflows/a11ksa-isolated-security.yml`
runs on pushes to this branch that touch the security-test files, or manually
through the Actions tab.

It installs exactly:
`A11ksa/API-Quotex@c678640a1ce06aea92aa2c823ef155ce4b8b8ab0`

The workflow then patches the installed package, asserts that hostname and
certificate validation are enabled, and performs a plain TLS handshake with
`ws2.quotex.com:443`. The handshake sends no SSID, cookies, credentials, or
WebSocket application messages.

A successful TLS handshake proves only that the server certificate chain and
hostname validate from that GitHub Actions runner. It does not prove Quotex
authentication, API compatibility, live candles, or availability from Render.

The workflow runs on a disposable GitHub-hosted runner. It does not use
repository secrets, does not access a Quotex account, and does not deploy.

The A11ksa adapter remains fail-closed. Do not enable candle retrieval until
the Actions run is green and a separate, explicitly authorized Demo-only
integration test has confirmed the exact candle API calls and event parsing.
