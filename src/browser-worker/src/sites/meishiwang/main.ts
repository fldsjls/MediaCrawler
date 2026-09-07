import { Dataset } from 'crawlee';

import { settings, useCrawlerStorage } from '../../config/settings.js';
import { createSinglePageCrawler, prepareBrowserStorage } from '../../browser/browser.js';
import type { DownloadEngine } from '../../downloader/m3u8.js';
import type { M3u8CrawlerOptions, SiteDownloadSettings } from '../../types/items.js';
import { createMeishiwangCrawlPipeline } from './pipeline/crawlPipeline.js';
import { createMeishiwangDownloadSettings, meishiwangSettings } from './settings.js';
import { createMeishiwangOutputPayloads, writeJsonFileWithSnapshot } from './export/jsonOutputs.js';

function downloadSettings(options: M3u8CrawlerOptions): SiteDownloadSettings {
    options.download ??= {};
    return options.download;
}

function appendDownloadRenameFields(options: M3u8CrawlerOptions, fields: string[], replace = false): void {
    const cleaned = fields.map((field) => field.trim()).filter(Boolean);
    if (!cleaned.length) return;

    const download = downloadSettings(options);
    download.rename ??= {};
    download.rename.fields = replace ? cleaned : [...(download.rename.fields ?? []), ...cleaned];
}

function positiveInteger(value: number | undefined, name: string): void {
    if (value !== undefined && (!Number.isInteger(value) || value < 1)) {
        throw new Error(`${name} must be a positive integer.`);
    }
}

// Parse site-specific flags, including login state and output path controls.
function parseArgs(argv: string[]): M3u8CrawlerOptions {
    const options: M3u8CrawlerOptions = {
        authMode: meishiwangSettings.authMode,
        download: createMeishiwangDownloadSettings(),
        forceManualLogin: meishiwangSettings.forceManualLogin,
        headless: meishiwangSettings.headless,
        loadStorage: meishiwangSettings.loadStorage,
        manualLogin: meishiwangSettings.manualLogin,
        maxLessons: meishiwangSettings.maxLessons,
        output: meishiwangSettings.output,
        processedOutput: meishiwangSettings.processedOutput,
        rawOutput: meishiwangSettings.rawOutput,
        saveStorage: meishiwangSettings.saveStorage,
        startLesson: meishiwangSettings.startLesson,
        url: meishiwangSettings.url,
        userDataDir: meishiwangSettings.userDataDir,
        waitMs: meishiwangSettings.waitMs,
    };
    let downloadRenameFieldsOverridden = false;

    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--url') options.url = argv[++index];
        else if (arg.startsWith('--url=')) options.url = arg.slice('--url='.length);
        else if (arg === '--auth-mode') options.authMode = argv[++index] as M3u8CrawlerOptions['authMode'];
        else if (arg.startsWith('--auth-mode=')) options.authMode = arg.slice('--auth-mode='.length) as M3u8CrawlerOptions['authMode'];
        else if (arg === '--load-storage') options.loadStorage = argv[++index];
        else if (arg.startsWith('--load-storage=')) options.loadStorage = arg.slice('--load-storage='.length);
        else if (arg === '--save-storage') options.saveStorage = argv[++index];
        else if (arg.startsWith('--save-storage=')) options.saveStorage = arg.slice('--save-storage='.length);
        else if (arg === '--no-storage') {
            options.loadStorage = undefined;
            options.saveStorage = undefined;
        } else if (arg === '--manual-login') options.manualLogin = true;
        else if (arg === '--force-manual-login') {
            options.manualLogin = true;
            options.forceManualLogin = true;
        }
        else if (arg === '--user-data-dir') options.userDataDir = argv[++index];
        else if (arg.startsWith('--user-data-dir=')) options.userDataDir = arg.slice('--user-data-dir='.length);
        else if (arg === '--limit') options.limit = Number(argv[++index]);
        else if (arg.startsWith('--limit=')) options.limit = Number(arg.slice('--limit='.length));
        else if (arg === '--start-lesson') options.startLesson = Number(argv[++index]);
        else if (arg.startsWith('--start-lesson=')) options.startLesson = Number(arg.slice('--start-lesson='.length));
        else if (arg === '--max-lessons') options.maxLessons = Number(argv[++index]);
        else if (arg.startsWith('--max-lessons=')) options.maxLessons = Number(arg.slice('--max-lessons='.length));
        else if (arg === '--wait-ms') options.waitMs = Number(argv[++index]);
        else if (arg.startsWith('--wait-ms=')) options.waitMs = Number(arg.slice('--wait-ms='.length));
        else if (arg === '--output') options.output = argv[++index];
        else if (arg.startsWith('--output=')) options.output = arg.slice('--output='.length);
        else if (arg === '--raw-output') options.rawOutput = argv[++index];
        else if (arg.startsWith('--raw-output=')) options.rawOutput = arg.slice('--raw-output='.length);
        else if (arg === '--processed-output') options.processedOutput = argv[++index];
        else if (arg.startsWith('--processed-output=')) options.processedOutput = arg.slice('--processed-output='.length);
        else if (arg === '--download-during-crawl') {
            const download = downloadSettings(options);
            download.duringCrawl = true;
            download.mode = 'during-crawl';
        } else if (arg === '--download-batch-size') {
            const download = downloadSettings(options);
            download.batchSize = Number(argv[++index]);
            download.duringCrawl = true;
            download.mode = 'during-crawl';
        } else if (arg.startsWith('--download-batch-size=')) {
            const download = downloadSettings(options);
            download.batchSize = Number(arg.slice('--download-batch-size='.length));
            download.duringCrawl = true;
            download.mode = 'during-crawl';
        } else if (arg === '--download-engine') downloadSettings(options).engine = argv[++index] as DownloadEngine;
        else if (arg.startsWith('--download-engine=')) downloadSettings(options).engine = arg.slice('--download-engine='.length) as DownloadEngine;
        else if (arg === '--downloader') downloadSettings(options).downloader = argv[++index];
        else if (arg.startsWith('--downloader=')) downloadSettings(options).downloader = arg.slice('--downloader='.length);
        else if (arg === '--download-output-dir') downloadSettings(options).outputDir = argv[++index];
        else if (arg.startsWith('--download-output-dir=')) downloadSettings(options).outputDir = arg.slice('--download-output-dir='.length);
        else if (arg === '--download-referer') downloadSettings(options).referer = argv[++index];
        else if (arg.startsWith('--download-referer=')) downloadSettings(options).referer = arg.slice('--download-referer='.length);
        else if (arg === '--download-user-agent') downloadSettings(options).userAgent = argv[++index];
        else if (arg.startsWith('--download-user-agent=')) downloadSettings(options).userAgent = arg.slice('--download-user-agent='.length);
        else if (arg === '--download-start-index') {
            const val = argv[++index];
            if (val?.startsWith('s/')) {
                downloadSettings(options).regexRename = val;
            } else {
                downloadSettings(options).startIndex = Number(val);
            }
        }
        else if (arg.startsWith('--download-start-index=')) {
            const val = arg.slice('--download-start-index='.length);
            if (val?.startsWith('s/')) {
                downloadSettings(options).regexRename = val;
            } else {
                downloadSettings(options).startIndex = Number(val);
            }
        }
        else if (arg === '--download-max-items') downloadSettings(options).maxItems = Number(argv[++index]);
        else if (arg.startsWith('--download-max-items=')) downloadSettings(options).maxItems = Number(arg.slice('--download-max-items='.length));
        else if (arg === '--download-rename-field') {
            appendDownloadRenameFields(options, [argv[++index]], !downloadRenameFieldsOverridden);
            downloadRenameFieldsOverridden = true;
        } else if (arg.startsWith('--download-rename-field=')) {
            appendDownloadRenameFields(options, [arg.slice('--download-rename-field='.length)], !downloadRenameFieldsOverridden);
            downloadRenameFieldsOverridden = true;
        } else if (arg === '--download-rename-fields') {
            appendDownloadRenameFields(options, argv[++index].split(','), true);
            downloadRenameFieldsOverridden = true;
        } else if (arg.startsWith('--download-rename-fields=')) {
            appendDownloadRenameFields(options, arg.slice('--download-rename-fields='.length).split(','), true);
            downloadRenameFieldsOverridden = true;
        }
        else if (arg === '--download-rename-fallback') (downloadSettings(options).rename ??= {}).fallback = argv[++index];
        else if (arg.startsWith('--download-rename-fallback=')) (downloadSettings(options).rename ??= {}).fallback = arg.slice('--download-rename-fallback='.length);
        else if (arg === '--download-no-rename-index') (downloadSettings(options).rename ??= {}).includeIndex = false;
        else if (arg === '--download-rename-index') (downloadSettings(options).rename ??= {}).includeIndex = true;
        else if (arg === '--download-continue-on-error') downloadSettings(options).continueOnError = true;
        else if (arg === '--download-dry-run') downloadSettings(options).dryRun = true;
        else if (arg === '--download-use-temp') downloadSettings(options).useTemp = true;
        else if (arg === '--headful') options.headless = false;
        else if (arg === '--headless') options.headless = true;
        else if (arg === '--help' || arg === '-h') options.help = true;
        else throw new Error(`Unknown argument: ${arg}`);
    }

    if (!['storage-state', 'persistent-context'].includes(options.authMode ?? '')) {
        throw new Error(`Unsupported --auth-mode: ${options.authMode}`);
    }

    positiveInteger(options.limit, '--limit');
    positiveInteger(options.startLesson, '--start-lesson');
    positiveInteger(options.maxLessons, '--max-lessons');

    const download = options.download;
    positiveInteger(download?.batchSize, '--download-batch-size');
    // startIndex is optional if regexRename is provided
    if (download?.startIndex !== undefined && !download?.regexRename) {
        positiveInteger(download.startIndex, '--download-start-index');
    }
    positiveInteger(download?.maxItems, '--download-max-items');

    if (download?.engine && !['n-m3u8dl', 'ffmpeg'].includes(download.engine)) {
        throw new Error(`Unsupported --download-engine: ${download.engine}. Use n-m3u8dl or ffmpeg.`);
    }
    if (download?.mode && !['capture-only', 'during-crawl'].includes(download.mode)) {
        throw new Error(`Unsupported download mode: ${download.mode}. Use capture-only or during-crawl.`);
    }
    if (download?.rename?.fields?.some((field) => !field.trim())) {
        throw new Error('--download-rename-field values must be non-empty strings.');
    }

    // If manual login is enabled, force headless=false to show the browser window
    if (options.manualLogin) {
        options.headless = false;
    }

    return options;
}

function usage(): string {
    return `
Usage:
  npm run crawl:meishiwang -- --url <course-page-url> [options]

Options:
  --auth-mode <mode>       storage-state or persistent-context. Default: storage-state.
  --load-storage <path>    Storage state JSON to load. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/auth/storage_state/login.json.
  --save-storage <path>    Storage state JSON to save after crawl. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/auth/storage_state/login.json.
  --no-storage             Do not load or save storage_state.
  --user-data-dir <path>   Persistent browser profile dir. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/auth/persistent_context/edge-profile.
  --manual-login           Wait for Enter when login is required, then reopen --url if the site redirects elsewhere.
  --force-manual-login     Always wait for Enter before crawling lessons.
  --limit <number>         Maximum videos to click. Default: all videos in the right-side catalog.
  --start-lesson <number>  1-based lesson row to start clicking. Default: 1.
  --max-lessons <number>   Maximum lesson rows to click after --start-lesson. Overrides --limit when set.
  --wait-ms <number>       Wait time after each lesson click. Default: 5000.
  --raw-output <path>      Raw JSON output. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/raw/meishiwang-m3u8-results.json.
  --processed-output <path> Processed JSON output. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/processed/meishiwang-m3u8-results.json.
  --output <path>          Export JSON output. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/export/meishiwang-m3u8-results.json.
  --download-during-crawl  Download captured m3u8 batches before clicking later lessons.
  --download-batch-size <n> Captured m3u8 count per in-crawl download batch. Implies --download-during-crawl. Default: 1.
  --download-engine <name> In-crawl download engine: n-m3u8dl or ffmpeg. Default: n-m3u8dl.
  --downloader <path>      In-crawl downloader executable path.
  --download-output-dir <path> In-crawl download output dir. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/downloads.
  --download-referer <url> Override in-crawl download Referer header.
  --download-user-agent <text> Override in-crawl download User-Agent header.
  --download-start-index <n|regex> In-crawl download numbering start or sed-style regex (e.g., 's/第(.*)章/Chapter $1/g'). Empty default uses lessonTitle.
  --download-max-items <n> Stop in-crawl downloading after N captured m3u8 items.
  --download-rename-field <field> Use a captured item field for output names. Default: lessonTitle.
  --download-rename-fields <list> Comma-separated captured item fields for output names.
  --download-rename-fallback <text> Fallback name when no configured field exists.
  --download-no-rename-index Do not prefix output names with the numeric index.
  --download-continue-on-error Continue lesson clicks if one in-crawl download fails.
  --download-dry-run       Print in-crawl download commands without running them.
  --download-use-temp      Download to the configured project temp dir, then move to output dir.
  --headful                Show browser window for login/debugging.
  --headless               Run without browser window.
  --help                   Show this help.

Examples:
  npm run crawl:meishiwang -- --url "http://edu.meishiwang100.com/v2/study/4423" --headful
  npm run crawl:meishiwang -- --url "http://edu.meishiwang100.com/v2/study/4423" --headful --auth-mode persistent-context --manual-login
`;
}

const options = parseArgs(process.argv.slice(2));
if (options.help || !options.url) {
    console.log(usage().trim());
    process.exit(options.help ? 0 : 1);
}

await prepareBrowserStorage(options);
useCrawlerStorage();

const datasetName = 'meishiwang-m3u8';
await (await Dataset.open(datasetName)).drop();

// The Meishiwang route needs a single logged-in page, so the shared browser wrapper fits here.
const crawler = createSinglePageCrawler({
    authMode: options.authMode,
    headless: options.headless,
    loadStorage: options.loadStorage,
    saveStorage: options.saveStorage,
    userDataDir: options.userDataDir,
    requestHandlerTimeoutSecs: Math.max(settings.requestHandlerTimeoutSecs, 180),
    requestHandler: createMeishiwangCrawlPipeline(options),
});

await crawler.run([options.url]);

// Crawlee keeps raw route pushes in storage; these files are the user-facing outputs.
const dataset = await Dataset.open(datasetName);
const { items } = await dataset.getData();
const generatedAt = new Date().toISOString();
const { exportPayload, processedPayload, rawPayload } = createMeishiwangOutputPayloads(items, generatedAt);

const rawWrite = await writeJsonFileWithSnapshot(options.rawOutput ?? meishiwangSettings.rawOutput, rawPayload, generatedAt);
const processedWrite = await writeJsonFileWithSnapshot(options.processedOutput ?? meishiwangSettings.processedOutput, processedPayload, generatedAt);
const exportWrite = await writeJsonFileWithSnapshot(options.output ?? meishiwangSettings.output, exportPayload, generatedAt);

console.log(`Saved ${rawPayload.count} raw, ${processedPayload.count} processed, and ${exportPayload.count} export Meishiwang m3u8 item(s).`);
console.log(`Raw: ${rawWrite.latestPath}`);
console.log(`Raw snapshot: ${rawWrite.snapshotPath}`);
console.log(`Processed: ${processedWrite.latestPath}`);
console.log(`Processed snapshot: ${processedWrite.snapshotPath}`);
console.log(`Export: ${exportWrite.latestPath}`);
console.log(`Export snapshot: ${exportWrite.snapshotPath}`);
