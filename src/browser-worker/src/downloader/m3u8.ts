import { toolPath, workerData, workerLogs } from '../paths.js';
import { spawn } from 'node:child_process';
import { createWriteStream, existsSync } from 'node:fs';
import { mkdir, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { TextDecoder } from 'node:util';

const DEFAULT_INPUT = workerData('meishiwang/export/meishiwang-m3u8-results.json');
const DEFAULT_OUTPUT_DIR = workerData('meishiwang/downloads');
const DEFAULT_LOG_DIR = workerLogs('downloads');
const DEFAULT_N_M3U8DL = process.platform === 'win32' ? toolPath('n-m3u8dl-re/N_m3u8DL-RE.exe') : 'N_m3u8DL-RE';
const DEFAULT_FFMPEG = process.platform === 'win32' ? toolPath('ffmpeg/ffmpeg.exe') : 'ffmpeg';
const DOWNLOADER_OUTPUT_ENCODING = process.platform === 'win32' ? 'gb18030' : 'utf-8';

// CLI options are normalized once so command builders stay small.
export type DownloadEngine = 'n-m3u8dl' | 'ffmpeg';

export interface DownloadRenameOptions {
    fallback?: string;
    fields?: string[];
    includeIndex?: boolean;
}

export interface DownloadOptions {
    continueOnError?: boolean;
    downloader: string;
    dryRun?: boolean;
    engine: DownloadEngine;
    ffmpegPath?: string;
    logDir: string;
    outputDir: string;
    referer?: string;
    rename?: DownloadRenameOptions;
    startIndex?: number;
    regexRename?: string;  // Optional regex replacement like "s/pattern/replacement/g"
    tempDir?: string;
    userAgent?: string;
    useTemp?: boolean;
}

interface DownloadArgs extends DownloadOptions {
    help?: boolean;
    input: string;
    limit?: number;
}

// The downloader accepts both generic and site-specific crawler export records.
export interface M3u8DownloadItem {
    raw: Record<string, unknown>;
    referer?: string;
    title?: string;
    url: string;
    userAgent?: string;
}

const DEFAULT_RENAME_FIELDS = ['lessonTitle', 'clicked', 'title'];

export function defaultDownloaderForEngine(engine: DownloadEngine): string {
    return engine === 'ffmpeg' ? DEFAULT_FFMPEG : DEFAULT_N_M3U8DL;
}

function cloneRenameOptions(rename?: DownloadRenameOptions): DownloadRenameOptions | undefined {
    return rename
        ? { ...rename, fields: rename.fields ? [...rename.fields] : undefined }
        : undefined;
}

export function createDownloadOptions(options: Partial<DownloadOptions> = {}): DownloadOptions {
    const engine = options.engine ?? 'n-m3u8dl';
    return {
        continueOnError: options.continueOnError,
        downloader: options.downloader ?? defaultDownloaderForEngine(engine),
        dryRun: options.dryRun,
        engine,
        ffmpegPath: options.ffmpegPath ?? DEFAULT_FFMPEG,
        logDir: options.logDir ?? DEFAULT_LOG_DIR,
        outputDir: options.outputDir ?? DEFAULT_OUTPUT_DIR,
        referer: options.referer,
        regexRename: options.regexRename,
        rename: cloneRenameOptions(options.rename),
        startIndex: options.startIndex,
        tempDir: options.tempDir,
        userAgent: options.userAgent,
        useTemp: options.useTemp,
    };
}

function appendRenameFields(args: Partial<DownloadOptions>, fields: string[]): void {
    const cleaned = fields.map((field) => field.trim()).filter(Boolean);
    if (!cleaned.length) return;

    args.rename ??= {};
    args.rename.fields = [...(args.rename.fields ?? []), ...cleaned];
}

// Parse downloader flags and choose the default executable for the selected engine.
function parseArgs(argv: string[]): DownloadArgs {
    const args: Omit<DownloadArgs, 'downloader'> & { downloader?: string } = {
        input: DEFAULT_INPUT,
        ...createDownloadOptions(),
    };

    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--input') args.input = argv[++index];
        else if (arg.startsWith('--input=')) args.input = arg.slice('--input='.length);
        else if (arg === '--engine') args.engine = argv[++index] as DownloadEngine;
        else if (arg.startsWith('--engine=')) args.engine = arg.slice('--engine='.length) as DownloadEngine;
        else if (arg === '--downloader') args.downloader = argv[++index];
        else if (arg.startsWith('--downloader=')) args.downloader = arg.slice('--downloader='.length);
        else if (arg === '--ffmpeg-path') args.ffmpegPath = argv[++index];
        else if (arg.startsWith('--ffmpeg-path=')) args.ffmpegPath = arg.slice('--ffmpeg-path='.length);
        else if (arg === '--output-dir') args.outputDir = argv[++index];
        else if (arg.startsWith('--output-dir=')) args.outputDir = arg.slice('--output-dir='.length);
        else if (arg === '--temp-dir') args.tempDir = argv[++index];
        else if (arg.startsWith('--temp-dir=')) args.tempDir = arg.slice('--temp-dir='.length);
        else if (arg === '--log-dir') args.logDir = argv[++index];
        else if (arg.startsWith('--log-dir=')) args.logDir = arg.slice('--log-dir='.length);
        else if (arg === '--referer') args.referer = argv[++index];
        else if (arg.startsWith('--referer=')) args.referer = arg.slice('--referer='.length);
        else if (arg === '--user-agent') args.userAgent = argv[++index];
        else if (arg.startsWith('--user-agent=')) args.userAgent = arg.slice('--user-agent='.length);
        else if (arg === '--limit') args.limit = Number(argv[++index]);
        else if (arg.startsWith('--limit=')) args.limit = Number(arg.slice('--limit='.length));
        else if (arg === '--start-index') {
            const value = argv[++index];
            if (/^s\//.test(value)) {
                args.regexRename = value;
            } else {
                args.startIndex = Number(value);
            }
        }
        else if (arg.startsWith('--start-index=')) {
            const value = arg.slice('--start-index='.length);
            if (/^s\//.test(value)) {
                args.regexRename = value;
            } else {
                args.startIndex = Number(value);
            }
        }
        else if (arg === '--rename-field') appendRenameFields(args, [argv[++index]]);
        else if (arg.startsWith('--rename-field=')) appendRenameFields(args, [arg.slice('--rename-field='.length)]);
        else if (arg === '--rename-fields') appendRenameFields(args, argv[++index].split(','));
        else if (arg.startsWith('--rename-fields=')) appendRenameFields(args, arg.slice('--rename-fields='.length).split(','));
        else if (arg === '--rename-fallback') (args.rename ??= {}).fallback = argv[++index];
        else if (arg.startsWith('--rename-fallback=')) (args.rename ??= {}).fallback = arg.slice('--rename-fallback='.length);
        else if (arg === '--no-rename-index') (args.rename ??= {}).includeIndex = false;
        else if (arg === '--rename-index') (args.rename ??= {}).includeIndex = true;
        else if (arg === '--continue-on-error') args.continueOnError = true;
        else if (arg === '--dry-run') args.dryRun = true;
        else if (arg === '--use-temp') args.useTemp = true;
        else if (arg === '--help' || arg === '-h') args.help = true;
        else throw new Error(`Unknown argument: ${arg}`);
    }

    if (!['n-m3u8dl', 'ffmpeg'].includes(args.engine)) {
        throw new Error(`Unsupported --engine: ${args.engine}. Use n-m3u8dl or ffmpeg.`);
    }

    if (args.startIndex !== undefined && (!Number.isFinite(args.startIndex) || args.startIndex < 1)) {
        throw new Error('--start-index must be a positive number.');
    }

    if (args.limit !== undefined && (!Number.isFinite(args.limit) || args.limit < 1)) {
        throw new Error('--limit must be a positive number.');
    }

    if (args.useTemp && !args.tempDir) {
        throw new Error('--use-temp requires --temp-dir.');
    }

    if (args.rename?.fields?.some((field) => !field.trim())) {
        throw new Error('--rename-field values must be non-empty strings.');
    }

    const downloader = args.downloader ?? defaultDownloaderForEngine(args.engine);
    return { ...args, downloader };
}

function usage(): string {
    return `
Usage:
  npm run download:m3u8 -- [options]

Options:
  --engine <name>          Download engine: n-m3u8dl or ffmpeg. Default: n-m3u8dl.
  --input <path>           Crawlee m3u8 result JSON. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/export/meishiwang-m3u8-results.json.
  --downloader <path>      Downloader executable path.
  --ffmpeg-path <path>     FFmpeg path passed to N_m3u8DL-RE. Default under MC_LOCAL_DIR: tools/ffmpeg/ffmpeg.exe.
  --output-dir <path>      Download output directory. Default under MC_LOCAL_DIR: data/browser-worker/meishiwang/downloads.
  --temp-dir <path>        Optional downloader cache/temp directory. Empty by default.
  --log-dir <path>         Download log directory. Default under MC_LOCAL_DIR: logs/browser-worker/downloads.
  --referer <url>          Override Referer header. Defaults to each item's pageUrl/courseUrl.
  --user-agent <text>      Override User-Agent header.
  --limit <number>         Download only the first N items.
  --start-index <num|regex> Numbering start or sed-style regex. Empty default uses the title only.
  --rename-field <field>   Use an item field for output names. Repeatable. Default: lessonTitle, clicked, title.
  --rename-fields <list>   Comma-separated item fields for output names.
  --rename-fallback <text> Fallback name when no configured field exists. Default: video.
  --no-rename-index        Do not prefix output names with the numeric index.
  --continue-on-error      Continue with the next item if one download fails.
  --use-temp               Download to --temp-dir, move to output-dir when complete. Requires --temp-dir.
  --dry-run                Print commands without running them.
  --help                   Show this help.

Examples:
  npm run download:m3u8 -- --dry-run
  npm run download:m3u8 -- --limit 3 --use-temp --temp-dir ../../.local/temp
  npm run download:m3u8 -- --engine ffmpeg --input ../../.local/data/browser-worker/meishiwang/export/meishiwang-m3u8-results.json
`;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, unknown>
        : undefined;
}

function stringField(record: Record<string, unknown>, names: string[]): string | undefined {
    for (const name of names) {
        const value = record[name];
        if (typeof value === 'string' && value.trim()) return value.trim();
    }

    return undefined;
}

function flattenItems(payload: unknown): unknown[] {
    // Accept either an array payload or the common { items: [...] } export shape.
    if (Array.isArray(payload)) return payload.flatMap((item) => Array.isArray(item) ? item : [item]);

    const record = asRecord(payload);
    if (!record) return [];

    const items = record.items;
    return Array.isArray(items) ? items.flatMap((item) => Array.isArray(item) ? item : [item]) : [];
}

function normalizeItem(value: unknown): M3u8DownloadItem | undefined {
    // Different crawlers may name the playlist URL differently, so check known aliases.
    const record = asRecord(value);
    if (!record) return undefined;

    const url = stringField(record, ['url', 'm3u8Url', 'sourceUrl']);
    if (!url || !url.includes('.m3u8')) return undefined;

    return {
        raw: record,
        referer: stringField(record, ['referer', 'pageUrl', 'courseUrl']),
        title: stringField(record, DEFAULT_RENAME_FIELDS),
        url,
        userAgent: stringField(record, ['userAgent']),
    };
}

export function readDownloadItems(payload: unknown): M3u8DownloadItem[] {
    return flattenItems(payload)
        .map(normalizeItem)
        .filter((item): item is M3u8DownloadItem => Boolean(item));
}

function safeFileName(text: string): string {
    // Strip characters that are invalid or awkward on Windows filesystems.
    const cleaned = text
        .replace(/[<>:"/\\|?*\x00-\x1F]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/[. ]+$/g, '');
    return (cleaned || 'video').slice(0, 120);
}

function applyRegexRename(text: string, regexPattern?: string): string {
    if (!regexPattern) return text;
    
    // Parse sed-style regex: s/pattern/replacement/flags
    const match = regexPattern.match(/^s\/(.*)\/(.*)\/([gimuy]*)$/);
    if (!match) {
        console.warn(`Invalid regex pattern: ${regexPattern}`);
        return text;
    }
    
    try {
        const [, pattern, replacement, flags] = match;
        const regex = new RegExp(pattern, flags || 'g');
        return text.replace(regex, replacement);
    } catch (error) {
        console.warn(`Regex replacement failed: ${(error as Error).message}`);
        return text;
    }
}

function saveNameForItem(args: DownloadOptions, item: M3u8DownloadItem, index: number, extension = ''): string {
    const ordinal = String((args.startIndex ?? 1) + index);
    const fields = args.rename?.fields?.length ? args.rename.fields : DEFAULT_RENAME_FIELDS;
    const fallback = args.rename?.fallback?.trim() || 'video';
    const includeIndex = args.startIndex !== undefined || args.rename?.includeIndex === true;
    
    // Try to get title from configured fields
    let title = stringField(item.raw, fields) ?? item.title;
    
    // If title is empty, try container name or use fallback
    if (!title) {
        const containerName = stringField(item.raw, ['courseTitle']);
        if (containerName) {
            const baseName = safeFileName(containerName);
            const renamed = applyRegexRename(baseName, args.regexRename);
            return `${renamed}${extension}`;
        }
        title = `${fallback}-${ordinal}`;
    }
    
    const safeTitle = safeFileName(title);
    const prefix = includeIndex ? `${ordinal}-` : '';
    let fileName = `${prefix}${safeTitle}`;
    fileName = applyRegexRename(fileName, args.regexRename);
    return `${fileName}${extension}`;
}

function effectiveReferer(args: DownloadOptions, item: M3u8DownloadItem): string | undefined {
    return args.referer ?? item.referer;
}

function effectiveUserAgent(args: DownloadOptions, item: M3u8DownloadItem): string | undefined {
    return args.userAgent ?? item.userAgent;
}

function getEffectiveOutputDir(args: DownloadOptions): string {
    // Default to the final output directory; temp mode is opt-in from GUI/CLI.
    if (!args.useTemp || !args.tempDir) return args.outputDir;
    return args.tempDir;
}

function getEffectiveDownloaderTempDir(args: DownloadOptions): string | undefined {
    return args.tempDir ? path.join(args.tempDir, 'n-m3u8dl') : undefined;
}

function buildNm3u8dlCommand(args: DownloadOptions, item: M3u8DownloadItem, index: number): string[] {
    // N_m3u8DL-RE accepts repeated -H headers for referer and user-agent.
    const effectiveDir = getEffectiveOutputDir(args);
    const command = [
        item.url,
        '--save-dir',
        effectiveDir,
        '--save-name',
        saveNameForItem(args, item, index),
    ];
    const tempDir = getEffectiveDownloaderTempDir(args);
    const referer = effectiveReferer(args, item);
    const userAgent = effectiveUserAgent(args, item);

    if (tempDir) command.push('--tmp-dir', tempDir);
    if (referer) command.push('-H', `Referer: ${referer}`);
    if (userAgent) command.push('-H', `User-Agent: ${userAgent}`);
    if (args.ffmpegPath) command.push('--ffmpeg-binary-path', args.ffmpegPath);
    command.push('--no-ansi-color', '--no-log');

    return command;
}

function buildFfmpegCommand(args: DownloadOptions, item: M3u8DownloadItem, index: number): string[] {
    // FFmpeg expects HTTP headers as one CRLF-delimited string.
    const effectiveDir = getEffectiveOutputDir(args);
    const outputPath = path.join(effectiveDir, saveNameForItem(args, item, index, '.mp4'));
    const command = ['-y'];
    const headers: string[] = [];
    const referer = effectiveReferer(args, item);
    const userAgent = effectiveUserAgent(args, item);

    if (referer) headers.push(`Referer: ${referer}`);
    if (userAgent) headers.push(`User-Agent: ${userAgent}`);
    if (headers.length) command.push('-headers', `${headers.join('\r\n')}\r\n`);

    command.push('-i', item.url, '-c', 'copy', outputPath);
    return command;
}

function buildCommand(args: DownloadOptions, item: M3u8DownloadItem, index: number): string[] {
    return args.engine === 'ffmpeg'
        ? buildFfmpegCommand(args, item, index)
        : buildNm3u8dlCommand(args, item, index);
}

function logTimestamp(): string {
    return new Date().toISOString()
        .replace(/[-:]/g, '')
        .replace(/\.\d{3}Z$/, '')
        .replace('T', '-');
}

function logPathForItem(args: DownloadOptions, item: M3u8DownloadItem, index: number): string {
    const ordinal = String(index + 1).padStart(3, '0');
    const saveName = safeFileName(saveNameForItem(args, item, index));
    return path.join(args.logDir, `${logTimestamp()}-${ordinal}-${saveName}.log`);
}

async function ensureDirectory(dir: string, label: string): Promise<void> {
    const resolved = path.resolve(dir);
    const root = path.parse(resolved).root;
    if (root && !existsSync(root)) {
        throw new Error(`${label} root is not available: ${root} (configured path: ${dir})`);
    }

    try {
        await mkdir(dir, { recursive: true });
    } catch (error) {
        throw new Error(`Cannot create ${label}: ${dir}. ${(error as Error).message}`);
    }
}

function createDownloaderOutputDecoder(): TextDecoder {
    try {
        return new TextDecoder(DOWNLOADER_OUTPUT_ENCODING);
    } catch {
        return new TextDecoder();
    }
}

function writeDecodedChunk(
    chunk: Buffer,
    decoder: TextDecoder,
    terminal: NodeJS.WriteStream,
    logStream: NodeJS.WritableStream,
): void {
    const text = decoder.decode(chunk, { stream: true });
    if (!text) return;
    terminal.write(text);
    logStream.write(text);
}

function runDownloader(executable: string, command: string[], logPath: string, printable: string): Promise<void> {
    // Tee downloader output to both the terminal/GUI and a durable run log.
    return new Promise((resolvePromise, reject) => {
        const logStream = createWriteStream(logPath, { flags: 'a' });
        const stdoutDecoder = createDownloaderOutputDecoder();
        const stderrDecoder = createDownloaderOutputDecoder();
        let settled = false;
        const finish = (error?: Error) => {
            if (settled) return;
            settled = true;
            const stdoutText = stdoutDecoder.decode();
            if (stdoutText) {
                process.stdout.write(stdoutText);
                logStream.write(stdoutText);
            }
            const stderrText = stderrDecoder.decode();
            if (stderrText) {
                process.stderr.write(stderrText);
                logStream.write(stderrText);
            }
            logStream.end(() => {
                if (error) reject(error);
                else resolvePromise();
            });
        };

        logStream.write(`[started] ${new Date().toISOString()}\n`);
        logStream.write(`[command] ${printable}\n\n`);

        const child = spawn(executable, command, { stdio: ['ignore', 'pipe', 'pipe'], shell: false });
        child.stdout.on('data', (chunk: Buffer) => {
            writeDecodedChunk(chunk, stdoutDecoder, process.stdout, logStream);
        });
        child.stderr.on('data', (chunk: Buffer) => {
            writeDecodedChunk(chunk, stderrDecoder, process.stderr, logStream);
        });
        child.on('error', (error) => {
            logStream.write(`\n[error] ${error.stack ?? error.message}\n`);
            finish(error);
        });
        child.on('close', (code) => {
            logStream.write(`\n[finished] ${new Date().toISOString()}\n`);
            logStream.write(`[exit-code] ${code ?? 'unknown'}\n`);
            if (code === 0) finish();
            else finish(new Error(`Downloader exited with code ${code}`));
        });
    });
}

export async function downloadM3u8Items(items: M3u8DownloadItem[], options: DownloadOptions): Promise<void> {
    if (!options.dryRun && options.downloader && !existsSync(options.downloader)) {
        throw new Error(`Downloader executable not found: ${options.downloader}\nPut it there or pass --downloader <path>.`);
    }

    if (!items.length) return;

    if (options.useTemp && !options.tempDir) {
        throw new Error('useTemp requires tempDir.');
    }

    const workDir = options.useTemp && options.tempDir ? options.tempDir : options.outputDir;
    if (!options.dryRun) {
        await ensureDirectory(workDir, options.useTemp ? 'temporary download directory' : 'download output directory');
        const downloaderTempDir = getEffectiveDownloaderTempDir(options);
        if (options.engine === 'n-m3u8dl' && downloaderTempDir) {
            await ensureDirectory(downloaderTempDir, 'download cache directory');
        }
        await ensureDirectory(options.logDir, 'download log directory');
    }

    for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        const command = buildCommand(options, item, index);
        const printable = [options.downloader, ...command].map((part) => JSON.stringify(part)).join(' ');
        console.log(`[download ${index + 1}/${items.length}] ${printable}`);

        if (options.dryRun) continue;

        const logPath = logPathForItem(options, item, index);
        console.log(`[download ${index + 1}/${items.length}] log: ${logPath}`);

        try {
            await runDownloader(options.downloader, command, logPath, printable);
        } catch (error) {
            if (!options.continueOnError) throw error;
            console.warn(`[download ${index + 1}/${items.length}] ${(error as Error).message}`);
        }
    }

    // Temp mode is only for workflows that need a separate staging area.
    if (options.useTemp && options.tempDir && !options.dryRun) {
        const tempDir = options.tempDir;
        const finalDir = options.outputDir;
        
        // If both directories resolve to the same place, the downloader already finalized there.
        if (path.resolve(tempDir) !== path.resolve(finalDir)) {
            await mkdir(finalDir, { recursive: true });
            
            console.log(`[finalizing] Moving files from ${tempDir} to ${finalDir}`);
            
            const fs = await import('node:fs/promises');
            const files = await fs.readdir(tempDir);
            const downloaderTempDir = getEffectiveDownloaderTempDir(options);
            const resolvedDownloaderTempDir = downloaderTempDir ? path.resolve(downloaderTempDir) : undefined;
            
            for (const file of files) {
                const tempPath = path.join(tempDir, file);
                if (resolvedDownloaderTempDir && path.resolve(tempPath) === resolvedDownloaderTempDir) continue;

                const stats = await fs.stat(tempPath);
                if (!stats.isFile()) continue;

                const finalPath = path.join(finalDir, file);
                try {
                    await rename(tempPath, finalPath);
                    console.log(`[finalizing] Moved: ${file}`);
                } catch (error) {
                    console.warn(`[finalizing] Failed to move ${file}: ${(error as Error).message}`);
                }
            }
            
            try {
                await rm(tempDir, { recursive: true });
                console.log(`[finalizing] Removed temp directory: ${tempDir}`);
            } catch (error) {
                console.warn(`[finalizing] Failed to remove temp directory: ${(error as Error).message}`);
            }
        }
    }
}

async function main(argv: string[]): Promise<void> {
    const args = parseArgs(argv);
    if (args.help) {
        console.log(usage().trim());
        return;
    }

    const inputPath = path.resolve(args.input);
    // Read crawler output only after validating the requested downloader executable.
    if (!args.dryRun && args.downloader && !existsSync(args.downloader)) {
        throw new Error(`Downloader executable not found: ${args.downloader}\nPut it there or pass --downloader <path>.`);
    }

    const payload = JSON.parse(await readFile(inputPath, 'utf8')) as unknown;
    let items = readDownloadItems(payload);
    if (args.limit) items = items.slice(0, args.limit);

    if (!items.length) {
        throw new Error(`No m3u8 items found in ${inputPath}`);
    }

    await downloadM3u8Items(items, args);
}

const isCli = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isCli) {
    await main(process.argv.slice(2)).catch((error) => {
        console.error((error as Error).stack || (error as Error).message);
        process.exit(1);
    });
}
