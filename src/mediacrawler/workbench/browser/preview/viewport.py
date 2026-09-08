"""Keep native tab pixels and Playwright input in the same fixed coordinate space."""
import asyncio


async def fit_native_viewport(session, page):
    """Size the real content area after Chromium's capture infobar appears.

    CDP emulation alone reports 1280x720 DOM dimensions while tab capture can
    receive a shorter physical widget. Clear an override owned by this channel,
    then compensate for measured browser chrome; never stretch captured pixels.
    """
    target = await session.context.new_cdp_session(page)
    browser = None
    try:
        browser = await session.browser.new_browser_cdp_session()
        target_id = (await target.send('Target.getTargetInfo'))['targetInfo']['targetId']
        await page.bring_to_front()
        await target.send('Emulation.setDeviceMetricsOverride', {
            'width': 1280, 'height': 720, 'deviceScaleFactor': 1, 'mobile': False})
        await target.send('Emulation.clearDeviceMetricsOverride')
        for _ in range(5):
            size = await page.evaluate('({width:innerWidth,height:innerHeight})')
            if size == {'width': 1280, 'height': 720}:
                return
            window = await browser.send('Browser.getWindowForTarget', {'targetId': target_id})
            bounds = window['bounds']
            if bounds.get('windowState', 'normal') != 'normal':
                await browser.send('Browser.setWindowBounds', {
                    'windowId': window['windowId'], 'bounds': {'windowState': 'normal'}})
                await asyncio.sleep(.05)
                continue
            await browser.send('Browser.setWindowBounds', {
                'windowId': window['windowId'],
                'bounds': {'width': bounds['width'] + 1280 - size['width'],
                           'height': bounds['height'] + 720 - size['height']}})
            await asyncio.sleep(.1)
        if await page.evaluate('innerWidth === 1280 && innerHeight === 720'):
            return
        raise RuntimeError('无法固定浏览器可见区域，请使用低刷新预览')
    finally:
        await asyncio.gather(target.detach(), *([browser.detach()] if browser else []), return_exceptions=True)
