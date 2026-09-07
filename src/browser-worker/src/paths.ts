import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
export const localRoot = resolve(process.env.MC_LOCAL_DIR || join(projectRoot, '.local'));
export const workerData = (name = '') => join(localRoot, 'data', 'browser-worker', name);
export const workerLogs = (name = '') => join(localRoot, 'logs', 'browser-worker', name);
export const toolPath = (name: string) => join(localRoot, 'tools', name);
