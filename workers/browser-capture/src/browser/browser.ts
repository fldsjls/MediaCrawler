import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

import { PlaywrightCrawler } from 'crawlee';

import { createProxyConfiguration } from '../config/proxies.js';
import { settings } from '../config/settings.js';

type PlaywrightCrawlerConfig = NonNullable<ConstructorParameters<typeof PlaywrightCrawler>[0]>;

// Shared browser options used by generic and site-specific crawler entrypoints.
export interface BrowserCrawlerOptions {
    authMode?: 'storage-state' | 'persistent-context';
    headless?: boolean;
    loadStorage?: string;
    saveStorage?: string;
    userDataDir?: string;
    requestHandler: PlaywrightCrawlerConfig['requestHandler'];
    requestHandlerTimeoutSecs?: number;
}

// Create parent folders before Playwright tries to save storage state or browser profiles.
export async function prepareBrowserStorage(options: Pick<BrowserCrawlerOptions, 'saveStorage' | 'userDataDir'>): Promise<void> {
    if (options.saveStorage) await mkdir(dirname(resolve(options.saveStorage)), { recursive: true });
    if (options.userDataDir) await mkdir(resolve(options.userDataDir), { recursive: true });
}

// Build a one-page Edge crawler with optional storage_state or persistent profile auth.
export function createSinglePageCrawler(options: BrowserCrawlerOptions): PlaywrightCrawler {
    return new PlaywrightCrawler({
        headless: options.headless,
        launchContext: {
            launchOptions: {
                channel: 'msedge',
            },
            // Persistent contexts must own the browser profile, so they cannot use incognito pages.
            useIncognitoPages: options.authMode !== 'persistent-context',
            userDataDir: options.authMode === 'persistent-context' ? options.userDataDir : undefined,
        },
        browserPoolOptions: options.authMode === 'storage-state' ? {
            // Inject cookies/localStorage before the page is created.
            prePageCreateHooks: [(_pageId, _browserController, pageOptions) => {
                if (!pageOptions) return;
                if (options.loadStorage) pageOptions.storageState = options.loadStorage;
            }],
            // Persist the refreshed login state when the page closes.
            prePageCloseHooks: [async (page) => {
                if (!options.saveStorage) return;
                await page.context().storageState({ path: options.saveStorage });
            }],
        } : undefined,
        maxConcurrency: 1,
        maxRequestsPerCrawl: 1,
        maxRequestRetries: 0,
        navigationTimeoutSecs: settings.navigationTimeoutSecs,
        requestHandlerTimeoutSecs: options.requestHandlerTimeoutSecs ?? settings.requestHandlerTimeoutSecs,
        proxyConfiguration: createProxyConfiguration(),
        requestHandler: options.requestHandler,
        failedRequestHandler: async ({ request }, error) => {
            throw new Error(`Crawl failed for ${request.url}: ${(error as Error).message}`);
        },
    });
}
