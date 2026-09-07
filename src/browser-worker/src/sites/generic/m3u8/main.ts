import { workerLogs } from '../../../paths.js';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

import { Dataset, PlaywrightCrawler } from 'crawlee';

import { settings, useCrawlerStorage } from '../../../config/settings.js';
import { createProxyConfiguration } from '../../../config/proxies.js';
import { createM3u8Router } from '../../../routes/m3u8.js';
import type { M3u8CrawlerOptions } from '../../../types/items.js';
import { genericM3u8Settings } from './settings.js';

// Parse the generic m3u8 crawler flags without adding site-specific assumptions.
function parseArgs(argv: string[]): M3u8CrawlerOptions {
    // Defaults favor safe interactive debugging; wrapper scripts can override them.
    const options: M3u8CrawlerOptions = {
        ...genericM3u8Settings,
    };

    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--url') {
            options.url = argv[++index];
        } else if (arg.startsWith('--url=')) {
            options.url = arg.slice('--url='.length);
        } else if (arg === '--selector') {
            options.selector = argv[++index];
        } else if (arg.startsWith('--selector=')) {
            options.selector = arg.slice('--selector='.length);
        } else if (arg === '--limit') {
            options.limit = Number(argv[++index]);
        } else if (arg.startsWith('--limit=')) {
            options.limit = Number(arg.slice('--limit='.length));
        } else if (arg === '--wait-ms') {
            options.waitMs = Number(argv[++index]);
        } else if (arg.startsWith('--wait-ms=')) {
            options.waitMs = Number(arg.slice('--wait-ms='.length));
        } else if (arg === '--output') {
            options.output = argv[++index];
        } else if (arg.startsWith('--output=')) {
            options.output = arg.slice('--output='.length);
        } else if (arg === '--screenshots') {
            options.screenshots = true;
        } else if (arg === '--red-boxes') {
            options.redBoxes = true;
        } else if (arg === '--no-red-boxes') {
            options.redBoxes = false;
        } else if (arg === '--record-video') {
            options.recordVideo = true;
        } else if (arg === '--no-record-video') {
            options.recordVideo = false;
        } else if (arg === '--video-dir') {
            options.videoDir = argv[++index];
        } else if (arg.startsWith('--video-dir=')) {
            options.videoDir = arg.slice('--video-dir='.length);
        } else if (arg === '--screenshot-dir') {
            options.screenshotDir = argv[++index];
        } else if (arg.startsWith('--screenshot-dir=')) {
            options.screenshotDir = arg.slice('--screenshot-dir='.length);
        } else if (arg === '--headful') {
            options.headless = false;
        } else if (arg === '--headless') {
            options.headless = true;
        } else if (arg === '--help' || arg === '-h') {
            options.help = true;
        } else {
            throw new Error(`Unknown argument: ${arg}`);
        }
    }

    return options;
}

function usage(): string {
    return `
Usage:
  npm run crawl:m3u8 -- --url <course-page-url> [options]

Options:
  --selector <css>     Selector for lesson/video items. Optional.
  --limit <number>    Maximum lesson/video items to click. Default: 20.
  --wait-ms <number>  Wait time after each click. Default: 5000.
  --output <path>     JSON summary output. Default under MC_LOCAL_DIR: logs/browser-worker/m3u8-results.json.
  --screenshots       Save visual debug screenshots after each major step.
  --red-boxes         Draw a red box around the element before each click.
  --record-video      Record browser video to disk.
  --no-record-video   Disable video recording if enabled by a wrapper script.
  --video-dir <path>  Video output directory. Default under MC_LOCAL_DIR: logs/browser-worker/videos/m3u8.
  --no-red-boxes      Disable red boxes if enabled by a wrapper script.
  --screenshot-dir    Screenshot output directory. Default under MC_LOCAL_DIR: logs/browser-worker/screenshots/m3u8.
  --headful           Show browser window for login/debugging.
  --headless          Run without browser window.
  --help              Show this help.

Example:
  npm run crawl:m3u8 -- --url "http://edu.meishiwang100.com/v2/study/4423" --headful
`;
}

const options = parseArgs(process.argv.slice(2));

if (options.help || !options.url) {
    console.log(usage().trim());
    process.exit(options.help ? 0 : 1);
}

// Generic crawls still use Crawlee storage, while visual debug artifacts go to logs.
useCrawlerStorage();

const router = createM3u8Router(options);
const crawler = new PlaywrightCrawler({
    headless: options.headless,
    maxConcurrency: 1,
    maxRequestsPerCrawl: 1,
    navigationTimeoutSecs: settings.navigationTimeoutSecs,
    requestHandlerTimeoutSecs: Math.max(settings.requestHandlerTimeoutSecs, 180),
    proxyConfiguration: createProxyConfiguration(),
    requestHandler: router,
    // Video recording has to be attached before Playwright creates the page.
    browserPoolOptions: options.recordVideo ? {
        prePageCreateHooks: [(_pageId, _browserController, pageOptions) => {
            if (!pageOptions) return;
            pageOptions.recordVideo = {
                dir: options.videoDir ?? `${settings.logsDir}/videos/m3u8`,
                size: { width: 1280, height: 720 },
            };
        }],
    } : undefined,
    failedRequestHandler({ request, log }) {
        log.error(`M3U8 crawl failed: ${request.url}`);
    },
});

await crawler.run([options.url]);

// Export a flat JSON summary in addition to Crawlee's Dataset storage.
const dataset = await Dataset.open('m3u8');
const { items } = await dataset.getData();
const outputPath = resolve(options.output ?? genericM3u8Settings.output ?? workerLogs('m3u8-results.json'));

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify({ count: items.length, items }, null, 2)}\n`, 'utf8');

console.log(`Saved ${items.length} m3u8 item(s) to ${outputPath}`);
