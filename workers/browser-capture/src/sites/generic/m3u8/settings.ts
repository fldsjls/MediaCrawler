import { settings as projectSettings } from '../../../config/settings.js';
import type { M3u8CrawlerOptions } from '../../../types/items.js';

// Edit this file to change generic m3u8 crawler defaults without rewriting CLI commands.
export const genericM3u8Settings = {
    headless: true,
    limit: 20,
    output: 'logs/m3u8-results.json',
    recordVideo: false,
    redBoxes: false,
    screenshotDir: `${projectSettings.screenshotsDir}/m3u8`,
    screenshots: false,
    selector: undefined as string | undefined,
    url: undefined as string | undefined,
    videoDir: `${projectSettings.logsDir}/videos/m3u8`,
    waitMs: 5000,
} satisfies M3u8CrawlerOptions;
