import { createInterface } from 'node:readline';
import { createHash } from 'node:crypto';

const output = process.stdout.write.bind(process.stdout);
export const enabled = Boolean(process.env.MC_TASK_CONFIG);
export function emit(type: string, payload: Record<string, unknown> = {}) {
    if (enabled) output(`${JSON.stringify({ type, ...payload })}\n`);
}
let paused = false;
let active = 0;
let acknowledged = false;
let reason = 'paused';
let resumeWaiters: (() => void)[] = [];
let validate: (() => Promise<boolean>) | undefined;
let resuming = false;
let pauseGeneration = 0;
const drains = new Map<number, () => void>();
let nextDrain = 0;
export async function drainDownloads() {
    if (!enabled) return;
    const request_id = ++nextDrain;
    await new Promise<void>(resolve => { drains.set(request_id, resolve); emit('drain', { request_id }); });
    await checkpoint();
}
function acknowledge() {
    if (paused && active === 0 && !acknowledged) {
        acknowledged = true;
        emit('state', { state: reason });
    }
}
export async function checkpoint() {
    while (paused) await new Promise<void>(resolve => resumeWaiters.push(resolve));
}
export async function waitForLogin() {
    pauseGeneration++;
    paused = true;
    reason = 'waiting_login';
    acknowledged = false;
    acknowledge();
    await checkpoint();
}
export function initialize(check: () => Promise<boolean>) {
    validate = check;
    for (const name of ['log', 'info', 'warn', 'error'] as const) {
        console[name] = (...args: unknown[]) => emit('log', { level: name, message: args.map(String).join(' ') });
    }
    createInterface({ input: process.stdin }).on('line', async line => {
        try {
            const message = JSON.parse(line);
            if (message.action === 'drained') {
                drains.get(message.request_id)?.(); drains.delete(message.request_id);
            } else if (message.action === 'pause' || message.action === 'takeover') {
                pauseGeneration++;
                paused = true; acknowledged = false; reason = 'paused'; acknowledge();
            } else if (message.action === 'resume' && paused && !resuming) {
                resuming = true;
                const generation = pauseGeneration;
                active++;
                try {
                    const valid = !validate || await validate();
                    if (generation !== pauseGeneration) return;
                    if (!valid) {
                        emit('state', { state: 'waiting_login' });
                        return;
                    }
                    paused = false;
                    emit('state', { state: 'running' });
                    for (const resolve of resumeWaiters.splice(0)) resolve();
                } finally { active--; resuming = false; acknowledge(); }
            }
        } catch (error) { emit('log', { level: 'error', message: String(error) }); emit('state', { state: 'paused' }); }
    });
}

// Only this worker's Page/Locator objects are wrapped. Each awaited operation must settle
// before a pause is acknowledged; the API's independent preview connection is unaffected.
const factories = new Set(['locator', 'getByText', 'getByRole', 'getByLabel', 'getByPlaceholder', 'nth', 'first', 'last', 'filter', 'frameLocator', 'contentFrame']);
const operations = new Set(['goto', 'reload', 'evaluate', 'evaluateAll', 'waitForLoadState', 'waitForTimeout', 'waitForSelector',
    'click', 'dblclick', 'fill', 'press', 'type', 'scrollIntoViewIfNeeded', 'count', 'innerText', 'textContent',
    'getAttribute', 'isVisible', 'isEnabled', 'screenshot', 'title', 'allTextContents', 'waitFor', 'boundingBox']);
export function guarded<T extends object>(object: T): T {
    return new Proxy(object, {
        get(target, key) {
            const value = Reflect.get(target, key);
            if (typeof value !== 'function') return value;
            if (factories.has(String(key))) return (...args: unknown[]) => guarded(value.apply(target, args));
            if (!operations.has(String(key))) return value.bind(target);
            return async (...args: unknown[]) => {
                await checkpoint(); active++;
                try { return await value.apply(target, args); }
                finally { active--; acknowledge(); }
            };
        },
    });
}

const seen = new Set<string>();
export function captured(item: Record<string, unknown>) {
    if (!enabled) return;
    const cfg = JSON.parse(process.env.MC_TASK_CONFIG!);
    const url = String(item.url || '');
    if (!url) return;
    const stableUrl = new URL(url);
    const transient = new Set(['token', 'expires', 'expire', 'sign', 'signature', 'auth_key', 'wssecret', 'wstime', 'deadline', 'upsig']);
    for (const key of [...stableUrl.searchParams.keys()]) {
        if (transient.has(key.toLowerCase()) || key.toLowerCase().startsWith('x-amz-')) stableUrl.searchParams.delete(key);
    }
    stableUrl.hash = '';
    const identity = cfg.platform === 'meishiwang' ? `${item.courseUrl}:${cfg.start}:${item.lessonIndex}` : stableUrl.href;
    if (seen.has(identity) || seen.size >= cfg.max_items) return;
    seen.add(identity);
    const id = 'content:' + createHash('sha256').update(identity).digest('hex').slice(0, 24);
    const title = String(item.lessonTitle || item.clicked || `媒体 ${seen.size}`);
    const kind = item.kind === 'image' ? 'image' : 'video';
    emit('record', { record: { id, source: cfg.platform, title, kind: 'content', parent_id: item.courseUrl || null,
        fields: { ...item, video_status: kind === 'video' ? 'available' : 'none' } } });
    const selected = kind === 'video' ? (cfg.download_video ?? cfg.media) : (cfg.download_images ?? cfg.media);
    if (selected && cfg.max_downloads > 0) emit('resource', { resource: {
        url, kind, parent_id: id, title, key: `${cfg.platform}:${id}:${kind}:0`, source: cfg.platform,
        origin: 'adapter', page_url: item.pageUrl || cfg.target,
        format: /\.m3u8$/i.test(stableUrl.pathname) ? 'hls' : 'direct',
        headers: { Referer: item.pageUrl || cfg.target },
    } });
}
