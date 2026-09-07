import { createDownloadOptions, downloadM3u8Items, readDownloadItems, type DownloadOptions } from '../../../downloader/m3u8.js';
import { settings as projectSettings } from '../../../config/settings.js';
import type { SiteDownloadSettings } from '../../../types/items.js';

interface BatchDownloadLogger {
    info(message: string): void;
}

export class InCrawlDownloadBatcher {
    private readonly batchSize: number;
    private downloadedCount = 0;
    private nextStartIndex?: number;
    private readonly maxItems?: number;
    private readonly options: DownloadOptions;
    private pending: unknown[] = [];

    constructor(download: SiteDownloadSettings) {
        const batchSize = download.batchSize ?? 1;
        if (!Number.isFinite(batchSize) || batchSize < 1) {
            throw new Error('--download-batch-size must be a positive number.');
        }

        this.batchSize = batchSize;
        this.maxItems = download.maxItems;
        this.nextStartIndex = download.startIndex;
        this.options = createDownloadOptions({
            continueOnError: download.continueOnError,
            downloader: download.downloader,
            dryRun: download.dryRun,
            engine: download.engine,
            ffmpegPath: download.ffmpegPath,
            outputDir: download.outputDir,
            referer: download.referer,
            regexRename: download.regexRename,
            rename: download.rename,
            startIndex: download.startIndex,
            tempDir: projectSettings.tempDir,
            useTemp: download.useTemp,
            userAgent: download.userAgent,
        });
    }

    enqueue(item: unknown): void {
        this.pending.push(item);
    }

    reachedLimit(): boolean {
        return Boolean(this.maxItems && this.downloadedCount >= this.maxItems);
    }

    limitLabel(): string | undefined {
        return this.maxItems === undefined ? undefined : String(this.maxItems);
    }

    async flush(log: BatchDownloadLogger, final = false): Promise<void> {
        // During crawl, keep each batch small so short-lived playlist URLs are consumed quickly.
        while (this.pending.length >= this.batchSize || (final && this.pending.length > 0)) {
            const remainingAllowed = this.maxItems === undefined
                ? Number.POSITIVE_INFINITY
                : this.maxItems - this.downloadedCount;
            if (remainingAllowed <= 0) {
                this.pending = [];
                return;
            }

            const takeCount = Math.min(this.batchSize, remainingAllowed);
            const batch = this.pending.splice(0, takeCount);
            const items = readDownloadItems(batch);
            if (!items.length) continue;

            const downloadOptions = {
                ...this.options,
                startIndex: this.nextStartIndex,
            };
            log.info(`Downloading ${items.length} captured m3u8 item(s) before continuing container clicks.`);
            await downloadM3u8Items(items, downloadOptions);
            this.downloadedCount += items.length;
            if (this.nextStartIndex !== undefined) this.nextStartIndex += items.length;
            log.info(`Finished downloading ${items.length} captured m3u8 item(s).`);
        }
    }
}

export function shouldDownloadDuringCrawl(download?: SiteDownloadSettings): boolean {
    return download?.mode === 'during-crawl' || download?.duringCrawl === true;
}

export function createInCrawlDownloadBatcher(download?: SiteDownloadSettings): InCrawlDownloadBatcher | undefined {
    return download && shouldDownloadDuringCrawl(download)
        ? new InCrawlDownloadBatcher(download)
        : undefined;
}
