import type { MeishiwangLesson, MeishiwangM3u8Item } from '../types.js';

// The current site emits playable lessons through this CDN playlist pattern.
export function isMeishiwangM3u8(url: string): boolean {
    return url.includes('chaosw.com') && url.includes('play.m3u8');
}

// Store the CDN host separately so repeated or failing hosts are easy to inspect later.
function cdnHost(url: string): string | undefined {
    try {
        return new URL(url).host;
    } catch {
        return undefined;
    }
}

// Convert route context and collected container metadata into the export shape used by the downloader.
export function createM3u8Item(params: {
    url: string;
    courseUrl: string;
    pageUrl: string;
    courseTitle?: string;
    lesson: MeishiwangLesson;
}): MeishiwangM3u8Item {
    return {
        site: 'meishiwang',
        courseUrl: params.courseUrl,
        pageUrl: params.pageUrl,
        courseTitle: params.courseTitle,
        lessonIndex: params.lesson.index + 1,
        lessonTitle: params.lesson.title,
        duration: params.lesson.duration,
        chapter: params.lesson.chapter,
        url: params.url,
        m3u8Url: params.url,
        cdnHost: cdnHost(params.url),
        sourceUrl: params.url,
        foundAt: new Date().toISOString(),
    };
}
