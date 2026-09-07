import { Dataset, NonRetryableError, createPlaywrightRouter } from 'crawlee';
import { captured, checkpoint, drainDownloads } from '../../../workbench/runtime.js';

import type { M3u8CrawlerOptions } from '../../../types/items.js';
import { getCourseTitle, returnToTargetCoursePage } from '../collect/coursePage.js';
import { clickLesson, collectLessons, lessonLocator, selectedLessons } from '../collect/lessonCatalog.js';
import { looksLikeLoginPage, waitForManualLogin } from '../auth/login.js';
import { clickPlay } from '../collect/playerTrigger.js';
import { createInCrawlDownloadBatcher } from '../download/inCrawlBatcher.js';
import { writeLatestMeishiwangOutputs } from '../export/jsonOutputs.js';
import { createM3u8Item, isMeishiwangM3u8 } from '../parse/playlistItem.js';
import { meishiwangSettings } from '../settings.js';
import type { MeishiwangLesson, MeishiwangM3u8Item, MeishiwangRawM3u8Item } from '../types.js';

type CaptureSource = MeishiwangRawM3u8Item['captureSource'];

export function createMeishiwangCrawlPipeline(options: M3u8CrawlerOptions) {
    const router = createPlaywrightRouter();

    router.addDefaultHandler(async ({ page, request, log }) => {
        // Meishiwang may preload the next lesson's playlist while the current lesson is active.
        // Assign unique playlist requests by capture order instead of the currently clicked row.
        const courseUrl = options.url ?? request.url;
        const batchDownload = createInCrawlDownloadBatcher(options.download);
        const dataset = await Dataset.open('meishiwang-m3u8');
        const generatedAt = new Date().toISOString();
        const rawItems: MeishiwangRawM3u8Item[] = [];
        const found = new Map<string, MeishiwangM3u8Item>();
        const pendingPlaylistUrls = new Set<string>();
        const playlistLessonByUrl = new Map<string, MeishiwangLesson>();
        let downloadLessons: MeishiwangLesson[] = [];
        let currentLesson: MeishiwangLesson | undefined;
        let courseTitle: string | undefined;
        let nextPlaylistLessonIndex = 0;
        let persistError: Error | undefined;
        let persistQueue = Promise.resolve();
        let rawIndex = 0;
        const capturedPlaylistForLesson = (ordinal: number): MeishiwangM3u8Item | undefined => {
            const expectedLessonIndex = ordinal + 1;
            return [...found.values()].find((item) => item.lessonIndex === expectedLessonIndex);
        };
        const enqueuePersist = (rawItem: MeishiwangRawM3u8Item): void => {
            const itemsSnapshot = [...rawItems];
            persistQueue = persistQueue
                .then(async () => {
                    await dataset.pushData(rawItem);
                    await writeLatestMeishiwangOutputs({
                        exportOutput: options.output ?? meishiwangSettings.output,
                        processedOutput: options.processedOutput ?? meishiwangSettings.processedOutput,
                        rawOutput: options.rawOutput ?? meishiwangSettings.rawOutput,
                    }, itemsSnapshot, generatedAt);
                })
                .catch((error) => {
                    persistError = error as Error;
                    log.warning(`Could not persist captured m3u8 item: ${persistError.message}`);
                });
        };
        const capturePlaylistUrl = (url: string, captureSource: CaptureSource): boolean => {
            if (!isMeishiwangM3u8(url)) return false;
            if (!currentLesson) {
                // Early player traffic can arrive before the click loop assigns a lesson.
                pendingPlaylistUrls.add(url);
                return false;
            }

            let lesson = playlistLessonByUrl.get(url);
            let isFirstPlaylistUrl = false;
            if (!lesson) {
                lesson = downloadLessons[nextPlaylistLessonIndex] ?? currentLesson;
                playlistLessonByUrl.set(url, lesson);
                nextPlaylistLessonIndex += 1;
                isFirstPlaylistUrl = true;
            }

            const item = createM3u8Item({
                url,
                courseUrl,
                pageUrl: page.url(),
                courseTitle,
                lesson,
            });

            const rawItem: MeishiwangRawM3u8Item = {
                ...item,
                rawIndex: rawIndex += 1,
                captureSource,
            };
            rawItems.push(rawItem);
            enqueuePersist(rawItem);

            const processedKey = url;
            if (found.has(processedKey)) return true;
            found.set(processedKey, item);
            captured({ ...item });
            if (isFirstPlaylistUrl) {
                const sourceLabel = captureSource === 'page-scan' ? ' from loaded page resources' : '';
                log.info(`Captured m3u8 ${found.size}/${downloadLessons.length || '?'} as: ${item.lessonTitle}${sourceLabel}`);
            }
            batchDownload?.enqueue(item);
            return true;
        };
        const capturePendingPlaylistUrls = (): void => {
            for (const url of [...pendingPlaylistUrls]) {
                if (!found.has(url)) capturePlaylistUrl(url, 'request');
                pendingPlaylistUrls.delete(url);
            }
        };
        const captureLoadedPlaylistUrls = async (): Promise<void> => {
            // If the first video is already playing, no fresh request may fire after click.
            // Scanning loaded resources catches those already-present playlist URLs.
            const urls = await page.evaluate(() => {
                const foundUrls = new Set<string>();
                const add = (value: unknown): void => {
                    if (typeof value !== 'string' || !value.includes('.m3u8')) return;
                    foundUrls.add(value.replace(/&amp;/g, '&'));
                };

                for (const entry of performance.getEntriesByType('resource')) {
                    add(entry.name);
                }

                for (const element of document.querySelectorAll('video, audio, source, iframe, embed, object, script, a')) {
                    for (const attribute of ['src', 'href', 'data']) {
                        add(element.getAttribute(attribute));
                    }
                }

                const htmlMatches = document.documentElement.innerHTML.match(/https?:\/\/[^"'\\\s<>]+?\.m3u8[^"'\\\s<>]*/g) ?? [];
                for (const match of htmlMatches) add(match);

                return [...foundUrls];
            }).catch(() => []);

            for (const url of urls) {
                if (!found.has(url)) capturePlaylistUrl(url, 'page-scan');
            }
        };
        const flushDownloads = async (final = false): Promise<void> => {
            await drainDownloads();
            if (!batchDownload) return;

            try {
                await persistQueue;
                if (persistError) throw persistError;
                await batchDownload.flush(log, final);
            } catch (error) {
                throw new NonRetryableError(`In-crawl download failed: ${(error as Error).message}`);
            }
        };

        page.on('request', (networkRequest) => {
            capturePlaylistUrl(networkRequest.url(), 'request');
        });

        await page.waitForLoadState('domcontentloaded');
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);

        if (options.manualLogin) {
            // Manual login is optional unless the user explicitly forces the pause.
            const needsLogin = options.forceManualLogin || await looksLikeLoginPage(page);
            if (needsLogin) {
                await waitForManualLogin(page, courseUrl);
            } else {
                log.info('Manual login was requested, but the page does not look like a login page. Continuing.');
            }
        }

        await returnToTargetCoursePage(page, courseUrl, log);
        log.info(`Crawling page after login checks: ${page.url()}`);

        courseTitle = await getCourseTitle(page);
        const lessons = selectedLessons(await collectLessons(page), options);
        downloadLessons = lessons.map((lesson, index) => ({ ...lesson, index }));
        log.info(`Selected ${lessons.length} Meishiwang video candidate(s).`);
        if (lessons.length) {
            log.info(`Video candidates: ${lessons.map((lesson) => lesson.title).join(' | ')}`);
        }

        for (let ordinal = 0; ordinal < lessons.length; ordinal += 1) {
            await checkpoint();
            // Assign the lesson before clicking so early network requests get the right metadata.
            const lesson = lessons[ordinal];
            currentLesson = { ...lesson, index: ordinal };
            log.info(`Clicking video ${ordinal + 1}/${lessons.length}: ${lesson.title} ${lesson.duration ?? ''}`.trim());
            capturePendingPlaylistUrls();
            await captureLoadedPlaylistUrls();

            await clickLesson(lessonLocator(page, lesson)).catch((error) => {
                log.warning(`Could not click video ${ordinal + 1}: ${(error as Error).message}`);
            });
            await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
            await clickPlay(page);
            await page.waitForTimeout(options.waitMs ?? 5000);
            await captureLoadedPlaylistUrls();
            if (!capturedPlaylistForLesson(ordinal)) {
                // A clicked row that never yields a playlist is a crawl failure, not a skip.
                await persistQueue;
                if (persistError) {
                    throw new NonRetryableError(`Could not persist captured m3u8 item: ${persistError.message}`);
                }
                throw new NonRetryableError(`No m3u8 playlist captured for video ${ordinal + 1}/${lessons.length}: ${lesson.title}. The click did not produce a playable link within ${options.waitMs ?? 5000} ms.`);
            }
            await flushDownloads();
            if (batchDownload?.reachedLimit()) {
                log.info(`Reached in-crawl download limit (${batchDownload.limitLabel()}); stopping lesson clicks.`);
                break;
            }
        }

        await flushDownloads(true);
        await persistQueue;
        if (persistError) {
            throw new NonRetryableError(`Could not persist captured m3u8 item: ${persistError.message}`);
        }
        log.info(`Collected ${rawItems.length} raw Meishiwang m3u8 request(s), ${found.size} unique lesson playlist item(s).`);
    });

    return router;
}
