import { readFile } from 'node:fs/promises';
import path from 'node:path';

import { createDownloadOptions, downloadM3u8Items, readDownloadItems } from '../../../downloader/m3u8.js';
import { settings as projectSettings } from '../../../config/settings.js';
import { createMeishiwangDownloadSettings, meishiwangSettings } from '../settings.js';

interface MeishiwangDownloadArgs {
    dryRun?: boolean;
    help?: boolean;
    input?: string;
}

function parseArgs(argv: string[]): MeishiwangDownloadArgs {
    const args: MeishiwangDownloadArgs = {};

    for (let index = 0; index < argv.length; index += 1) {
        const arg = argv[index];
        if (arg === '--input') args.input = argv[++index];
        else if (arg.startsWith('--input=')) args.input = arg.slice('--input='.length);
        else if (arg === '--dry-run') args.dryRun = true;
        else if (arg === '--help' || arg === '-h') args.help = true;
        else throw new Error(`Unknown argument: ${arg}`);
    }

    return args;
}

function usage(): string {
    return `
Usage:
  npm run download:meishiwang -- [options]

Options:
  --input <path>  Export JSON input. Default: src/sites/meishiwang/settings.ts output.
  --dry-run       Print download commands without running them.
  --help          Show this help.

Edit src/sites/meishiwang/settings.ts to change outputDir, startIndex, maxItems, engine, and rename fields.
`;
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
    console.log(usage().trim());
    process.exit(0);
}

const settings = createMeishiwangDownloadSettings();
if (args.dryRun) settings.dryRun = true;

const inputPath = path.resolve(args.input ?? meishiwangSettings.output);
const payload = JSON.parse(await readFile(inputPath, 'utf8')) as unknown;
const allItems = readDownloadItems(payload);
const items = settings.maxItems ? allItems.slice(0, settings.maxItems) : allItems;

if (!items.length) {
    throw new Error(`No m3u8 items found in ${inputPath}`);
}

await downloadM3u8Items(items, createDownloadOptions({
    continueOnError: settings.continueOnError,
    downloader: settings.downloader,
    dryRun: settings.dryRun,
    engine: settings.engine,
    ffmpegPath: settings.ffmpegPath,
    outputDir: settings.outputDir,
    referer: settings.referer,
    regexRename: settings.regexRename,
    rename: settings.rename,
    startIndex: settings.startIndex,
    tempDir: projectSettings.tempDir,
    useTemp: settings.useTemp,
    userAgent: settings.userAgent,
}));
