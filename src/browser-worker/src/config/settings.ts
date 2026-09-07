import { workerData, workerLogs } from '../paths.js';
// Project-wide defaults shared by CLI entrypoints and route helpers.
export const settings = {
    maxRequestsPerCrawl: 20,
    maxConcurrency: 5,
    requestHandlerTimeoutSecs: 60,
    navigationTimeoutSecs: 30,
    logsDir: workerLogs(''),
    crawleeStorageDir: workerData('crawlee'),
    screenshotsDir: workerLogs('screenshots'),
    tempDir: undefined as string | undefined,
} as const;

// Keep Crawlee datasets, queues, and key-value stores in the project storage folder.
export function useCrawlerStorage(): void {
    process.env.CRAWLEE_STORAGE_DIR ??= settings.crawleeStorageDir;
}
