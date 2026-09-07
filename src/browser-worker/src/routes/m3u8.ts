import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

import { createPlaywrightRouter, Dataset } from 'crawlee';
import { captured, drainDownloads } from '../workbench/runtime.js';
import type { Locator, Page, Response } from 'playwright';

import { settings } from '../config/settings.js';
import type { M3u8CrawlerOptions, M3u8Item } from '../types/items.js';

// Broad defaults make the generic crawler useful before a site-specific route exists.
const DEFAULT_LESSON_SELECTOR = [
    '[class*="catalog" i] li',
    '[class*="chapter" i] li',
    '[class*="lesson" i] li',
    '[class*="course" i] li',
    '[class*="video" i] li',
    '[class*="list" i] li',
    'a[href*="study" i]',
    'a[href*="video" i]',
    'a[href*="lesson" i]',
].join(', ');

const PLAY_SELECTORS = [
    'button:has-text("Play")',
    'button:has-text("\u64ad\u653e")',
    '[role="button"]:has-text("Play")',
    '[role="button"]:has-text("\u64ad\u653e")',
    '[aria-label*="play" i]',
    '[title*="play" i]',
    '.vjs-big-play-button',
    '.plyr__control--overlaid',
    '.xgplayer-start',
    '.dplayer-video-wrap',
    '.prism-big-play-btn',
    'video',
];

const TEXT_CONTENT_TYPES = [
    'application/javascript',
    'application/json',
    'application/vnd.apple.mpegurl',
    'application/x-mpegurl',
    'application/xml',
    'text/',
    'mpegurl',
];

// Match both direct playlist URLs and playlist references embedded in text bodies.
const M3U8_URL_RE = /\.m3u8(?:$|[?#])/i;
const M3U8_TOKEN_RE = /((?:https?:)?\/\/[^\s"'<>\\)]+?\.m3u8(?:\?[^\s"'<>\\)]*)?|(?:\/|\.\.?\/)[^\s"'<>\\)]*?\.m3u8(?:\?[^\s"'<>\\)]*)?|[A-Za-z0-9_.~!$&'()*+,;=:@%/-]+\.m3u8(?:\?[^\s"'<>\\)]*)?)/gi;

interface CollectorMeta {
    kind: M3u8Item['kind'];
    pageUrl: string;
    sourceUrl?: string;
    clicked?: string;
    status?: number;
    baseUrl?: string;
}

interface ClickTarget {
    index: number;
    text: string;
    href: string | null;
}

function safeScreenshotName(name: string): string {
    // Windows-safe step names keep screenshots readable without breaking file creation.
    return name
        .replace(/[^\p{L}\p{N}._-]+/gu, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80) || 'step';
}


async function clearRedBoxes(page: Page, options: M3u8CrawlerOptions): Promise<void> {
    if (!options.redBoxes) return;

    await page.evaluate(() => {
        document.querySelectorAll('[data-crawlee-red-box]').forEach((element) => element.remove());
    }).catch(() => undefined);
}

async function showRedBox(locator: Locator, options: M3u8CrawlerOptions, label: string): Promise<void> {
    if (!options.redBoxes) return;

    // Draw the overlay in the page so recordings and screenshots show the exact click target.
    await locator.evaluate((element, boxLabel) => {
        document.querySelectorAll('[data-crawlee-red-box]').forEach((item) => item.remove());

        const rect = element.getBoundingClientRect();
        const box = document.createElement('div');
        const tag = document.createElement('div');
        const left = Math.max(0, rect.left);
        const top = Math.max(0, rect.top);

        box.setAttribute('data-crawlee-red-box', 'true');
        tag.setAttribute('data-crawlee-red-box', 'true');

        Object.assign(box.style, {
            position: 'fixed',
            left: `${left}px`,
            top: `${top}px`,
            width: `${Math.max(1, rect.width)}px`,
            height: `${Math.max(1, rect.height)}px`,
            border: '4px solid #ff1f1f',
            background: 'rgba(255, 31, 31, 0.08)',
            boxSizing: 'border-box',
            pointerEvents: 'none',
            zIndex: '2147483647',
        });

        tag.textContent = String(boxLabel).slice(0, 80);
        Object.assign(tag.style, {
            position: 'fixed',
            left: `${left}px`,
            top: `${Math.max(0, top - 28)}px`,
            maxWidth: '520px',
            padding: '3px 8px',
            borderRadius: '4px',
            background: '#ff1f1f',
            color: '#fff',
            font: '12px/18px Arial, sans-serif',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            zIndex: '2147483647',
        });

        document.body.append(box, tag);
    }, label).catch(() => undefined);
}

async function saveStepScreenshot(page: Page, options: M3u8CrawlerOptions, step: string): Promise<void> {
    if (!options.screenshots) return;

    const dir = options.screenshotDir ?? `${settings.screenshotsDir}/m3u8`;
    await mkdir(dir, { recursive: true });
    const fileName = `${new Date().toISOString().replace(/[:.]/g, '-')}-${safeScreenshotName(step)}.png`;
    await page.screenshot({ path: join(dir, fileName), fullPage: true });
}

function normalizeCandidate(raw: string | undefined, baseUrl: string): string | null {
    if (!raw) return null;

    // Response bodies often contain escaped or relative playlist URLs.
    const cleaned = raw
        .replace(/\\u0026/g, '&')
        .replace(/\\\//g, '/')
        .replace(/^["'(<]+|[>"')]+$/g, '');

    try {
        return new URL(cleaned, baseUrl).href;
    } catch {
        return null;
    }
}

function isTextLike(response: Response): boolean {
    // Binary media bodies are intentionally skipped; only small text-like responses are scanned.
    const contentType = (response.headers()['content-type'] ?? '').toLowerCase();
    return TEXT_CONTENT_TYPES.some((type) => contentType.includes(type));
}

function canReadBody(response: Response): boolean {
    // Cap body reads to avoid loading large media segments into memory.
    const contentLength = Number(response.headers()['content-length'] ?? 0);
    return !contentLength || contentLength <= 2_000_000;
}

function createCollector() {
    // De-duplicate by final URL while preserving hit counts from different discovery paths.
    const items = new Map<string, M3u8Item>();
    const pending = new Set<Promise<void>>();

    function add(rawUrl: string | undefined, meta: CollectorMeta): void {
        const baseUrl = meta.baseUrl ?? meta.sourceUrl ?? meta.pageUrl;
        const url = normalizeCandidate(rawUrl, baseUrl);
        if (!url || !M3U8_URL_RE.test(url)) return;

        const existing = items.get(url);
        if (existing) {
            existing.hits += 1;
            return;
        }

        items.set(url, {
            url,
            pageUrl: meta.pageUrl,
            sourceUrl: meta.sourceUrl,
            clicked: meta.clicked,
            status: meta.status,
            kind: meta.kind,
            hits: 1,
            foundAt: new Date().toISOString(),
        });
        captured({ ...items.get(url)! });
    }

    function track(task: Promise<void>): void {
        pending.add(task);
        task.finally(() => pending.delete(task)).catch(() => undefined);
    }

    async function flush(): Promise<void> {
        while (pending.size > 0) {
            await Promise.allSettled([...pending]);
        }
    }

    return {
        add,
        flush,
        results: () => [...items.values()],
        track,
    };
}

async function collectFromPerformance(page: Page, add: (url: string, meta: CollectorMeta) => void, clicked?: string): Promise<void> {
    // Performance entries catch resources that fired before the request listeners were attached.
    const urls = await page.evaluate(() => performance.getEntriesByType('resource').map((entry) => entry.name));
    for (const url of urls) {
        add(url, {
            kind: 'performance',
            pageUrl: page.url(),
            sourceUrl: url,
            clicked,
            baseUrl: page.url(),
        });
    }
}

function installNetworkCollector(page: Page, collector: ReturnType<typeof createCollector>, clickedLabel: () => string | undefined): void {
    // Capture direct playlist requests as soon as the browser emits them.
    page.on('request', (request) => {
        collector.add(request.url(), {
            kind: 'request',
            pageUrl: page.url(),
            sourceUrl: request.url(),
            clicked: clickedLabel(),
            baseUrl: page.url(),
        });
    });

    // Some pages hide m3u8 links inside JSON or JavaScript responses, so scan small text bodies too.
    page.on('response', (response) => {
        collector.track((async () => {
            const responseUrl = response.url();
            collector.add(responseUrl, {
                kind: 'response-url',
                pageUrl: page.url(),
                sourceUrl: responseUrl,
                clicked: clickedLabel(),
                status: response.status(),
                baseUrl: responseUrl,
            });

            if (!isTextLike(response) || !canReadBody(response)) return;

            let text = '';
            try {
                text = await response.text();
            } catch {
                return;
            }

            for (const match of text.matchAll(M3U8_TOKEN_RE)) {
                collector.add(match[1], {
                    kind: 'response-body',
                    pageUrl: page.url(),
                    sourceUrl: responseUrl,
                    clicked: clickedLabel(),
                    status: response.status(),
                    baseUrl: responseUrl,
                });
            }
        })());
    });
}

async function clickPossiblePlayButton(page: Page, options: M3u8CrawlerOptions): Promise<string | null> {
    // Try common player controls before assuming the lesson click already started playback.
    for (const selector of PLAY_SELECTORS) {
        const locator = page.locator(selector).first();
        const count = await locator.count().catch(() => 0);
        if (!count) continue;

        try {
            await showRedBox(locator, options, selector);
            await page.waitForTimeout(options.redBoxes ? 400 : 0);
            await locator.click({ timeout: 3000, force: selector === 'video' });
            return selector;
        } catch {
            // Try the next common player selector.
        }
    }

    return null;
}

async function collectClickTargets(page: Page, selector: string, limit: number): Promise<ClickTarget[]> {
    // Snapshot target labels before clicking; navigation may detach the original elements later.
    const locator = page.locator(selector);
    const count = Math.min(await locator.count().catch(() => 0), limit);
    const targets: ClickTarget[] = [];

    for (let index = 0; index < count; index += 1) {
        const item = locator.nth(index);
        const text = (await item.innerText({ timeout: 1000 }).catch(() => '')).trim().replace(/\s+/g, ' ');
        const href = await item.getAttribute('href').catch(() => null);
        targets.push({
            index,
            href,
            text: text || href || `target-${index + 1}`,
        });
    }

    return targets;
}

export function createM3u8Router(options: M3u8CrawlerOptions) {
    const router = createPlaywrightRouter();

    router.addDefaultHandler(async ({ page, request, log }) => {
        // One collector follows the whole page session so every click can be tied to a label.
        const collector = createCollector();
        let clickedLabel: string | undefined;
        installNetworkCollector(page, collector, () => clickedLabel);

        await page.waitForLoadState('domcontentloaded');
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
        await collectFromPerformance(page, collector.add, clickedLabel);
        await saveStepScreenshot(page, options, '01-initial-page');

        clickedLabel = 'initial-play-button';
        const initialPlaySelector = await clickPossiblePlayButton(page, options);
        if (initialPlaySelector) log.info(`Clicked initial play control: ${initialPlaySelector}`);
        await page.waitForTimeout(options.waitMs ?? 5000);
        await collectFromPerformance(page, collector.add, clickedLabel);
        await saveStepScreenshot(page, options, '02-after-initial-play');
        await drainDownloads();

        const selector = options.selector ?? DEFAULT_LESSON_SELECTOR;
        const targets = await collectClickTargets(page, selector, options.limit ?? 20);
        log.info(`Found ${targets.length} candidate lesson/video target(s).`);
        await saveStepScreenshot(page, options, '03-candidate-list');

        for (let index = 0; index < targets.length; index += 1) {
            const target = targets[index];
            clickedLabel = `${index + 1}. ${target.text}`;
            log.info(`Clicking target: ${clickedLabel}`);

            const targetLocator = page.locator(selector).nth(target.index);
            try {
                await targetLocator.scrollIntoViewIfNeeded({ timeout: 3000 });
                await targetLocator.click({ timeout: 5000 });
            } catch (error) {
                if (target.href) {
                    // Some lesson entries navigate better via href than by synthetic click.
                    await page.goto(new URL(target.href, request.loadedUrl ?? request.url).href, { waitUntil: 'domcontentloaded' });
                } else {
                    log.warning(`Could not click target ${clickedLabel}: ${(error as Error).message}`);
                    continue;
                }
            }

            await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
            await clickPossiblePlayButton(page, options);
            await page.waitForTimeout(options.waitMs ?? 5000);
            await collectFromPerformance(page, collector.add, clickedLabel);
            await saveStepScreenshot(page, options, `${String(index + 4).padStart(2, '0')}-after-click-${target.text}`);
            await drainDownloads();
        }

        await collector.flush();
        const results = collector.results();
        const dataset = await Dataset.open('m3u8');
        if (results.length > 0) {
            await dataset.pushData(results);
        }

        log.info(`Collected ${results.length} unique m3u8 URL(s).`);
    });

    return router;
}
