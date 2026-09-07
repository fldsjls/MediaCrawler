import type { Page } from 'playwright';

export interface RouteLog {
    info(message: string): void;
    warning(message: string): void;
}

function cleanText(text: string): string {
    return text.trim().replace(/\s+/g, ' ');
}

// Ignore trailing slashes when checking whether the browser returned to the target course.
function comparablePath(pathname: string): string {
    return pathname.replace(/\/+$/, '') || '/';
}

// Compare host, path, and requested query string while tolerating URL parsing failures.
function isTargetCoursePage(currentUrl: string, targetUrl: string): boolean {
    try {
        const current = new URL(currentUrl);
        const target = new URL(targetUrl);
        return current.host === target.host
            && comparablePath(current.pathname) === comparablePath(target.pathname)
            && (!target.search || current.search === target.search);
    } catch {
        return currentUrl === targetUrl;
    }
}

// Login flows can redirect to a dashboard, so reopen the requested course before crawling.
export async function returnToTargetCoursePage(page: Page, targetUrl: string, log: RouteLog): Promise<void> {
    if (isTargetCoursePage(page.url(), targetUrl)) return;

    log.info(`Current page is ${page.url()}, reopening target course page: ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);

    if (!isTargetCoursePage(page.url(), targetUrl)) {
        log.warning(`After reopening target URL, browser is still at ${page.url()}. Login may be incomplete or the site redirected again.`);
    }
}

// Prefer visible course title elements, then fall back to the browser title.
export async function getCourseTitle(page: Page): Promise<string | undefined> {
    const candidates = [
        '.course-title',
        '[class*="title" i]',
        'h1',
        'h2',
    ];

    for (const selector of candidates) {
        const text = await page.locator(selector).first().innerText({ timeout: 1000 }).catch(() => '');
        const cleaned = cleanText(text);
        if (cleaned) return cleaned;
    }

    const title = await page.title().catch(() => '');
    return title.trim() || undefined;
}
