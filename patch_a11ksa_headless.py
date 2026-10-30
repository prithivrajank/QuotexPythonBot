"""Make the pinned A11ksa Playwright login usable on a headless Render worker.

This patches only the upstream browser launch options, then performs a real
Chromium launch smoke test during the Render build so missing browser/runtime
dependencies fail visibly before the web service starts.
"""
from pathlib import Path
import asyncio
import re

import api_quotex.login as login
from playwright.async_api import async_playwright


path = Path(login.__file__)
source = path.read_text(encoding="utf-8")

# Persist login diagnostics to stdout so they appear in Render runtime logs.
anchor = 'logger.add(log_filename, level="INFO", encoding="utf-8", backtrace=True, diagnose=True)\\n'
persistent = anchor + 'logger.add(lambda message: print(message, end=""), level="INFO")\\n'
if anchor in source:
    source = source.replace(anchor, persistent, 1)
elif 'logger.add(lambda message: print(message, end=""), level="INFO")' not in source:
    raise SystemExit("A11ksa patch failed: logger setup anchor not found.")

# Playwright URL patterns are globs or regexes; parentheses in the old glob
# were treated literally and could never match the intended redirect.
old_wait = 'page.wait_for_url("**/(trade|demo-trade|cabinet)**", timeout=60_000)'
new_wait = 'page.wait_for_url(re.compile(r".*/(?:trade|demo-trade|cabinet)(?:/.*)?$"), timeout=60_000)'
if old_wait in source:
    source = source.replace(old_wait, new_wait, 1)
elif new_wait not in source:
    raise SystemExit("A11ksa patch failed: expected login redirect wait was not found.")

if "headless=False" in source:
    source = source.replace("headless=False", "headless=True")
elif "headless=True" not in source:
    raise SystemExit("A11ksa patch failed: expected headless browser option not found.")

marker = 'args=[\n                "--disable-blink-features=AutomationControlled",'
patched_marker = '''args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-blink-features=AutomationControlled",'''

if marker in source:
    source = source.replace(marker, patched_marker, 1)
elif all(flag in source for flag in (
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"
)):
    pass
else:
    raise SystemExit("A11ksa patch failed: browser launch args did not match the pinned source.")

path.write_text(source, encoding="utf-8")
print(f"Patched A11ksa login for headless Chromium: {path}")

async def smoke_test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
            ],
        )
        await browser.close()

asyncio.run(smoke_test())
print("Playwright Chromium launch smoke test: OK")
