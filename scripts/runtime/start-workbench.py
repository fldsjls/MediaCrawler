"""Local Windows entry point; deliberately use Proactor without reload/workers."""
import asyncio
import os
from pathlib import Path
import sys
import socket

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
os.chdir(PROJECT)


def main():
    import uvicorn

    # Fail before app startup can open/recover SQLite when another server owns the port.
    try:
        with socket.socket() as probe:
            if sys.platform == 'win32':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', 8080))
    except OSError:
        raise SystemExit('Port 8080 is already in use. Open the existing workbench or stop it before starting another instance.')

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Uvicorn's reload/multiple-worker loop setup can select Windows Selector,
    # which cannot spawn the Playwright driver. Keep one process and our policy.
    uvicorn.run("mediacrawler.api.main:app", host="127.0.0.1", port=8080, loop="none")


if __name__ == "__main__":
    main()
