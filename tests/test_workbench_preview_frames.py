import asyncio
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.browser.preview.frames import FrameHub


@pytest.mark.asyncio
async def test_closed_target_never_falls_back_to_internal_sender():
    closed = SimpleNamespace(is_closed=lambda: True)
    helper = SimpleNamespace(is_closed=lambda: False)
    session = SimpleNamespace(page=closed, browser=SimpleNamespace(is_connected=lambda: True),
                              context=SimpleNamespace(pages=[helper]), public_pages=lambda: [])
    hub = FrameHub(session)
    sub = await hub.subscribe(1)
    try:
        with pytest.raises(ValueError, match='没有可预览页面'):
            await asyncio.wait_for(sub.recv(), 1)
        assert session.page is closed
        assert hub.capture_count == 0
    finally:
        await hub.close()
