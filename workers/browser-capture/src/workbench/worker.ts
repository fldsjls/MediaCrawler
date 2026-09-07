import { join } from 'node:path';
import { chromium } from 'playwright';
import { Request, log } from 'crawlee';
import { createMeishiwangCrawlPipeline } from '../sites/meishiwang/pipeline/crawlPipeline.js';
import { createM3u8Router } from '../routes/m3u8.js';
import { looksLikeLoginPage } from '../sites/meishiwang/auth/login.js';
import { emit, guarded, initialize, waitForLogin } from './runtime.js';
import { isInternalPreviewUrl } from './internalPreview.js';

const cfg = JSON.parse(process.env.MC_TASK_CONFIG!);
const directory = process.env.MC_TASK_DIR!;
process.env.CRAWLEE_STORAGE_DIR = join(directory, 'crawlee');
process.env.CRAWLEE_PURGE_ON_START = 'false';
let browser;
try {
    browser = await chromium.connectOverCDP(process.env.MC_BROWSER_ENDPOINT!);
    const context = browser.contexts()[0];
    const rawPage = context.pages().find(page => !isInternalPreviewUrl(page.url())) ?? await context.newPage();
    const returnUrl = cfg.target;
    initialize(async () => {
        if (rawPage.isClosed()) throw new Error('采集页面已关闭，请新建任务');
        if (await looksLikeLoginPage(rawPage)) return false;
        if (rawPage.url() !== returnUrl) await rawPage.goto(returnUrl, { waitUntil: 'domcontentloaded' });
        return !await looksLikeLoginPage(rawPage);
    });
    const page = guarded(rawPage);
    emit('state', { state: 'running' });
    emit('phase', { phase: 'discovering', message: '发现目标并即时登记媒体下载' });
    if (rawPage.url() !== cfg.target) await page.goto(cfg.target, { waitUntil: 'domcontentloaded' });
    if (cfg.platform === 'generic' && await looksLikeLoginPage(page)) await waitForLogin();
    const options = { url: cfg.target, maxLessons: cfg.max_items, limit: cfg.max_items, startLesson: cfg.start,
        waitMs: cfg.wait_ms, selector: cfg.selector || undefined, manualLogin: true,
        output: join(directory, 'course-export.json'), processedOutput: join(directory, 'course-processed.json'),
        rawOutput: join(directory, 'course-raw.json') };
    const router = cfg.platform === 'meishiwang' ? createMeishiwangCrawlPipeline(options) : createM3u8Router(options);
    // The migrated handlers only require these Crawlee context fields. Browser ownership
    // stays with FastAPI; no second crawler or Node web server is launched here.
    const handlerContext = { page, request: new Request({ url: cfg.target }), log };
    await router(handlerContext as Parameters<typeof router>[0]);
    emit('done');
} catch (error) {
    emit('failure', { message: String(error) });
    process.exitCode = 1;
} finally {
    await browser?.close(); // CDP client disconnect; API retains ownership of Chromium.
    process.exit(process.exitCode || 0);
}
