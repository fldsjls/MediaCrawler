"""Check imports and the installed browser without starting the application."""
from pathlib import Path

import aiosqlite
import fastapi
import httpx
import uvicorn
import aiortc
import av
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    executable = Path(playwright.chromium.executable_path)
    if not executable.is_file():
        raise SystemExit("Chromium missing; run scripts/install-workbench.ps1")
print("Python dependencies and Chromium: OK")
