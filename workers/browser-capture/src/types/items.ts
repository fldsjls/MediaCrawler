// Shared CLI options for generic and site-specific m3u8 crawlers.
import type { DownloadEngine, DownloadRenameOptions } from '../downloader/m3u8.js';

export type DownloadMode = 'capture-only' | 'during-crawl';

// Site-level download policy used when crawling and downloading are coupled.
export interface SiteDownloadSettings {
    batchSize?: number;
    continueOnError?: boolean;
    downloader?: string;
    dryRun?: boolean;
    duringCrawl?: boolean;
    engine?: DownloadEngine;
    ffmpegPath?: string;
    maxItems?: number;
    mode?: DownloadMode;
    outputDir?: string;
    referer?: string;
    regexRename?: string;  // Optional regex replacement pattern like "s/pattern/replacement/g"
    rename?: DownloadRenameOptions;
    startIndex?: number;
    userAgent?: string;
    useTemp?: boolean;
}

export interface M3u8CrawlerOptions {
    url?: string;
    selector?: string;
    limit?: number;
    waitMs?: number;
    output?: string;
    processedOutput?: string;
    rawOutput?: string;
    screenshots?: boolean;
    redBoxes?: boolean;
    recordVideo?: boolean;
    videoDir?: string;
    screenshotDir?: string;
    authMode?: 'storage-state' | 'persistent-context';
    loadStorage?: string;
    saveStorage?: string;
    userDataDir?: string;
    manualLogin?: boolean;
    forceManualLogin?: boolean;
    download?: SiteDownloadSettings;
    maxLessons?: number;
    startLesson?: number;
    headless?: boolean;
    help?: boolean;
}

// Generic m3u8 discovery item. Site-specific crawlers can extend this with lesson metadata.
export interface M3u8Item {
    url: string;
    pageUrl: string;
    sourceUrl?: string;
    clicked?: string;
    status?: number;
    kind: 'request' | 'response-url' | 'response-body' | 'performance';
    hits: number;
    foundAt: string;
}
