import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const currentDir = dirname(fileURLToPath(import.meta.url));

// Absolute project root used by helpers that need stable paths from any cwd.
export const projectRoot = resolve(currentDir, '..', '..');
