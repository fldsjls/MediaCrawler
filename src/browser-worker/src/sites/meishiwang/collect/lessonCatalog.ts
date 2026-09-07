import type { Locator, Page } from 'playwright';

import type { M3u8CrawlerOptions } from '../../../types/items.js';
import { parseLessonText } from '../parse/lessonText.js';
import type { MeishiwangLesson } from '../types.js';

// Meishiwang's video catalog uses the misspelled "lession" class in its lesson rows.
export const lessonSelectors = [
    '.fa_children .fa_Item_lession',
    '.fa_children [class*="Item_lession" i]',
    '.fa_children [class*="lession" i]',
    '.fa_children > div:has(.bar_press)',
    '[class*="catalog" i] [class*="lession" i]',
    '[class*="lesson" i] [class*="lession" i]',
].join(', ');

export const lessonClickSelectors = [
    '.name',
    '.it_less_left',
    '[class*="it_less_left" i]',
    '[class*="name" i]',
    'button',
    'a',
    '.bar_press',
    '[class*="bar_press" i]',
];

export function selectedLessons(lessons: MeishiwangLesson[], options: M3u8CrawlerOptions): MeishiwangLesson[] {
    const startIndex = Math.max((options.startLesson ?? 1) - 1, 0);
    const maxCount = options.maxLessons ?? options.limit;
    const selected = lessons.slice(startIndex);
    return maxCount ? selected.slice(0, maxCount) : selected;
}

export async function collectLessons(page: Page, limit?: number): Promise<MeishiwangLesson[]> {
    // Some course pages lazy-render rows only after the catalog is scrolled to the bottom.
    console.log('[collectLessons] Starting lesson collection...');
    
    const scrollableCatalogs = [
        '.fa_children',
        '[class*="catalog" i]',
        '[class*="lesson" i]',
        '[role="list"]',
    ];

    for (const catalogSelector of scrollableCatalogs) {
        try {
            const container = await page.$(catalogSelector);
            if (container) {
                console.log(`[collectLessons] Found scrollable container: ${catalogSelector}`);
                // Await each scroll instead of leaving a timer running inside the page.
                // This gives the workbench a real pause boundary before manual takeover.
                let lastHeight = -1;
                for (let attempt = 0; attempt < 10; attempt++) {
                    const height = await page.evaluate((selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return 0;
                        el.scrollTop = el.scrollHeight;
                        return el.scrollHeight;
                    }, catalogSelector);
                    if (height === lastHeight) break;
                    lastHeight = height;
                    await page.waitForTimeout(300);
                }
                await page.waitForTimeout(2000);
                break;
            }
        } catch (error) {
            // Continue to the next likely catalog selector.
        }
    }

    // Build a stable lesson snapshot before clicks can change the DOM.
    const maxCount = limit && limit > 0 ? limit : Number.POSITIVE_INFINITY;
    const locator = page.locator(lessonSelectors);
    const totalCount = await locator.count().catch(() => 0);
    console.log(`[collectLessons] Found ${totalCount} lesson elements total`);
    
    const lessons: MeishiwangLesson[] = [];
    let skipped = 0;

    for (let index = 0; index < totalCount && lessons.length < maxCount; index += 1) {
        const item = locator.nth(index);
        const visible = await item.isVisible().catch(() => false);
        
        if (!visible) {
            skipped++;
            continue;
        }

        const text = await item.innerText({ timeout: 1000 }).catch(() => '');
        const lessonText = parseLessonText(text);
        
        if (!lessonText) {
            console.log(`[collectLessons] Element ${index}: Unparseable text: "${text.substring(0, 50)}..."`);
            continue;
        }

        console.log(`[collectLessons] Element ${index}: ${lessonText.title} (${lessonText.duration})`);
        lessons.push({
            index,
            title: lessonText.title,
            duration: lessonText.duration,
        });
    }

    console.log(`[collectLessons] Complete: ${lessons.length} lessons collected, ${skipped} skipped (invisible)`);
    return lessons;
}

export function lessonLocator(page: Page, lesson: MeishiwangLesson): Locator {
    return page.locator(lessonSelectors).nth(lesson.index);
}

// Click the most specific inner control first, then fall back to the whole row.
export async function clickLesson(target: Locator): Promise<void> {
    let lastError: Error | undefined;

    for (const selector of lessonClickSelectors) {
        const locator = target.locator(selector).first();
        const count = await locator.count().catch(() => 0);
        if (!count) continue;

        await locator.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined);
        try {
            await locator.click({ timeout: 5000 });
            return;
        } catch (error) {
            lastError = error as Error;
        }
    }

    await target.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => undefined);
    try {
        await target.click({ timeout: 5000 });
    } catch (error) {
        throw lastError ?? error;
    }
}
