"""Make the pinned A11ksa Playwright login usable on a headless Render worker.

This patches only the upstream browser launch options, then performs a real
Chromium launch smoke test during the Render build so missing browser/runtime
dependencies fail visibly before the web service starts.
"""
from pathlib import Path
import asyncio

import api_quotex.login as login
from playwright.async_api import async_playwright

path = Path(login.__file__)
source = path.read_text(encoding="utf-8")

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
