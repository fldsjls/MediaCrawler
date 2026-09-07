import type { Page } from 'playwright';

export const playSelectors = [
    'button:has-text("\u64ad\u653e")',
    'button:has-text("Play")',
    '[role="button"]:has-text("\u64ad\u653e")',
    '[role="button"]:has-text("Play")',
    '[aria-label*="play" i]',
    '.xgplayer-start',
    '.dplayer-video-wrap',
    '.vjs-big-play-button',
    'video',
];

export const iframePlaySelectors = [
    '[id^="playercontainer_component_"]',
    '#playercontainer',
    '.xgplayer-start',
    '.dplayer-video-wrap',
    '.vjs-big-play-button',
    'video',
    'body',
];

// Try top-level player controls first, then controls inside the embedded player iframe.
export async function clickPlay(page: Page): Promise<void> {
    for (const selector of playSelectors) {
        const locator = page.locator(selector).first();
        const count = await locator.count().catch(() => 0);
        if (!count) continue;
        await locator.click({ timeout: 3000, force: selector === 'video' }).catch(() => undefined);
        return;
    }

    const videoFrame = page.locator('#video').first();
    const frameCount = await videoFrame.count().catch(() => 0);
    if (!frameCount) return;

    await videoFrame.waitFor({ state: 'attached', timeout: 3000 }).catch(() => undefined);
    const frame = videoFrame.contentFrame();
    for (const selector of iframePlaySelectors) {
        const locator = frame.locator(selector).first();
        const count = await locator.count().catch(() => 0);
        if (!count) continue;
        await locator.click({ timeout: 3000, force: selector === 'video' || selector === 'body' }).catch(() => undefined);
        return;
    }
}
