import process from 'node:process';
import { createInterface } from 'node:readline/promises';

import type { Page } from 'playwright';
import { enabled, waitForLogin } from '../../../workbench/runtime.js';

export async function looksLikeLoginPage(page: Page): Promise<boolean> {
    // Only detect whether manual login is needed; captcha solving stays manual.
    const url = page.url().toLowerCase();
    if (url.includes('/login')) return true;

    const passwordInputs = await page.locator('input[type="password"]').count().catch(() => 0);
    if (passwordInputs > 0) return true;

    const namedInputs = await page.locator('input[name*=password i], input[name*=captcha i], input[name*=mobile i], input[name*=phone i], input[id*=password i], input[id*=captcha i], input[id*=mobile i], input[id*=phone i]').count().catch(() => 0);
    return namedInputs > 0;
}

// Pause for manual captcha/login work, then let the caller reopen the course page if needed.
export async function waitForManualLogin(page: Page, targetUrl: string): Promise<void> {
    if (enabled) {
        await waitForLogin();
        return;
    }
    console.log('\n[manual-login] Browser is waiting for you.');
    console.log(`[manual-login] Current page: ${page.url()}`);
    console.log(`[manual-login] Target page: ${targetUrl}`);
    console.log('[manual-login] Please finish login and captcha in the opened Edge window.');
    console.log('[manual-login] If the site redirects to its home page after login, just press Enter; the script will reopen the target page.');

    const readline = createInterface({ input: process.stdin, output: process.stdout });
    try {
        await readline.question('[manual-login] Press Enter to continue...');
    } finally {
        readline.close();
    }

    await page.waitForLoadState('domcontentloaded').catch(() => undefined);
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
}
