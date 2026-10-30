"""Patch the upstream A11ksa login browser for headless cloud hosting.

The upstream package launches Chromium with headless=False, which requires a
display server and causes BrowserType.launch to close on a headless Render
service. Keep this patch narrow and fail the build if the expected code changes.
"""
from pathlib import Path
import api_quotex.login as login

path = Path(login.__file__)
source = path.read_text(encoding="utf-8")
old = "headless=False"
new = "headless=True"

if new in source and old not in source:
    print(f"A11ksa login already uses headless Chromium: {path}")
elif old in source:
    patched = source.replace(old, new)
    if patched == source:
        raise SystemExit("A11ksa headless patch made no change.")
    path.write_text(patched, encoding="utf-8")
    print(f"Patched A11ksa login to use headless Chromium: {path}")
else:
    raise SystemExit(
        "Could not safely patch A11ksa login: expected headless=False was not found."
    )
