import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, parse, resolve } from 'node:path';

function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : undefined;
}

function itemUrl(item: Record<string, unknown>): string | undefined {
    const url = item.url ?? item.m3u8Url ?? item.sourceUrl;
    return typeof url === 'string' && url.trim() ? url.trim() : undefined;
}

function stringValue(record: Record<string, unknown>, name: string): string | undefined {
    const value = record[name];
    return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function numberValue(record: Record<string, unknown>, name: string): number | undefined {
    const value = record[name];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function rawIndexFor(record: Record<string, unknown>, fallback: number): number {
    return numberValue(record, 'rawIndex') ?? fallback;
}

function lessonIndexFor(record: Record<string, unknown>): number {
    return numberValue(record, 'lessonIndex') ?? Number.POSITIVE_INFINITY;
}

function processedKey(record: Record<string, unknown>, url: string, fallback: number): string {
    return `${lessonIndexFor(record)}:${url || fallback}`;
}

function snapshotPathFor(path: string, generatedAt: string): string {
    const outputPath = resolve(path);
    const parsed = parse(outputPath);
    const timestamp = generatedAt
        .replace(/[-:]/g, '')
        .replace(/\.\d{3}Z$/, 'Z')
        .replace('T', '-')
        .replace('Z', '');
    const extension = parsed.ext || '.json';

    return join(parsed.dir, `${parsed.name}.${timestamp}${extension}`);
}

// Collapse duplicate playlist hits per lesson while preserving raw traceability.
export function processExportItems(items: unknown[]): Record<string, unknown>[] {
    const byKey = new Map<string, {
        duplicateHits: number;
        firstFoundAt?: string;
        item: Record<string, unknown>;
        lastFoundAt?: string;
        rawIndexes: number[];
    }>();

    for (const [index, item] of items.entries()) {
        const record = asRecord(item);
        if (!record) continue;

        const url = itemUrl(record);
        if (!url) continue;

        const key = processedKey(record, url, index);
        const rawIndex = rawIndexFor(record, index + 1);
        const foundAt = stringValue(record, 'foundAt');
        const existing = byKey.get(key);

        if (existing) {
            existing.duplicateHits += 1;
            existing.rawIndexes.push(rawIndex);
            existing.lastFoundAt = foundAt ?? existing.lastFoundAt;
            continue;
        }

        byKey.set(key, {
            duplicateHits: 1,
            firstFoundAt: foundAt,
            item: { ...record, url, m3u8Url: stringValue(record, 'm3u8Url') ?? url, sourceUrl: stringValue(record, 'sourceUrl') ?? url },
            lastFoundAt: foundAt,
            rawIndexes: [rawIndex],
        });
    }

    return [...byKey.values()]
        .map((group) => ({
            ...group.item,
            duplicateHits: group.duplicateHits,
            firstFoundAt: group.firstFoundAt,
            lastFoundAt: group.lastFoundAt,
            rawIndexes: group.rawIndexes,
        }))
        .sort((left, right) => lessonIndexFor(left) - lessonIndexFor(right));
}

// Export only downloader-facing fields so the final file stays stable and compact.
export function createDownloadExportItems(items: unknown[]): Record<string, unknown>[] {
    return items
        .map(asRecord)
        .filter((item): item is Record<string, unknown> => Boolean(item))
        .map((item) => {
            const url = itemUrl(item);
            return {
                site: stringValue(item, 'site') ?? 'meishiwang',
                courseUrl: stringValue(item, 'courseUrl'),
                pageUrl: stringValue(item, 'pageUrl'),
                courseTitle: stringValue(item, 'courseTitle'),
                lessonIndex: numberValue(item, 'lessonIndex'),
                lessonTitle: stringValue(item, 'lessonTitle'),
                duration: stringValue(item, 'duration'),
                chapter: stringValue(item, 'chapter'),
                m3u8Url: url,
                url,
                sourceUrl: stringValue(item, 'sourceUrl') ?? url,
                cdnHost: stringValue(item, 'cdnHost'),
                foundAt: stringValue(item, 'firstFoundAt') ?? stringValue(item, 'foundAt'),
            };
        })
        .filter((item) => item.url);
}

export function createMeishiwangOutputPayloads(items: unknown[], generatedAt: string): {
    exportPayload: Record<string, unknown>;
    processedPayload: Record<string, unknown>;
    rawPayload: Record<string, unknown>;
} {
    const processedItems = processExportItems(items);
    const exportItems = createDownloadExportItems(processedItems);

    return {
        rawPayload: { stage: 'raw', generatedAt, count: items.length, items },
        processedPayload: { stage: 'processed', generatedAt, count: processedItems.length, items: processedItems },
        exportPayload: { stage: 'export', generatedAt, count: exportItems.length, items: exportItems },
    };
}

// Keep raw, processed, and export writes using the same JSON formatting.
export async function writeJsonFile(path: string, payload: unknown): Promise<string> {
    const outputPath = resolve(path);
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    return outputPath;
}

export async function writeLatestMeishiwangOutputs(paths: {
    exportOutput: string;
    processedOutput: string;
    rawOutput: string;
}, items: unknown[], generatedAt: string): Promise<void> {
    const { exportPayload, processedPayload, rawPayload } = createMeishiwangOutputPayloads(items, generatedAt);
    await writeJsonFile(paths.rawOutput, rawPayload);
    await writeJsonFile(paths.processedOutput, processedPayload);
    await writeJsonFile(paths.exportOutput, exportPayload);
}

export async function writeJsonFileWithSnapshot(path: string, payload: unknown, generatedAt: string): Promise<{ latestPath: string; snapshotPath: string }> {
    const latestPath = await writeJsonFile(path, payload);
    const snapshotPath = snapshotPathFor(path, generatedAt);
    await writeJsonFile(snapshotPath, payload);
    return { latestPath, snapshotPath };
}
