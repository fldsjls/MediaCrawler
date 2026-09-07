import { workerData } from '../../paths.js';
import type { M3u8CrawlerOptions, SiteDownloadSettings } from '../../types/items.js';

const DATA_DIR = workerData('meishiwang');

type MeishiwangSettings = M3u8CrawlerOptions & {
    dataDir: string;
    download: SiteDownloadSettings;
};

// Edit this file to change Meishiwang defaults without rewriting CLI commands.
export const meishiwangSettings = {
    authMode: "persistent-context" as const,
    dataDir: DATA_DIR,
    forceManualLogin: false,
    headless: false,
    loadStorage: workerData('meishiwang/auth/storage_state/login.json'),
    manualLogin: true,
    maxLessons: undefined as number | undefined,
    output: workerData('meishiwang/export/meishiwang-m3u8-results.json'),
    processedOutput: workerData('meishiwang/processed/meishiwang-m3u8-results.json'),
    rawOutput: workerData('meishiwang/raw/meishiwang-m3u8-results.json'),
    saveStorage: workerData('meishiwang/auth/storage_state/login.json'),
    startLesson: 1,
    url: "http://edu.meishiwang100.com/course/package/4696",
    userDataDir: workerData('meishiwang/auth/persistent_context/edge-profile'),
    waitMs: 5000,
    download: {
        // Use during-crawl when playlist links may expire before a separate download step.
        mode: "during-crawl" as const,
        batchSize: 5,
        continueOnError: false,
        dryRun: false,
        engine: "n-m3u8dl" as const,
        maxItems: undefined as number | undefined,
        outputDir: workerData('meishiwang/downloads'),
        rename: {
            // Meishiwang exposes the lesson row text as lessonTitle in exported items.
            fields: ["lessonTitle"],
            fallback: "meishiwang-video",
            includeIndex: true,
        },
        startIndex: undefined as number | undefined,
        useTemp: false,
    } satisfies SiteDownloadSettings,
} satisfies MeishiwangSettings;

export function createMeishiwangDownloadSettings(): SiteDownloadSettings {
    return { ...meishiwangSettings.download };
}
