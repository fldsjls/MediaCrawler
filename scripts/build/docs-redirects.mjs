import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = path.join(root, '.build/docs');
const redirects = JSON.parse(await readFile(path.join(root, 'docs/.vitepress/redirects.json'), 'utf8'));
for (const [from, to] of Object.entries(redirects)) {
  const destination = path.resolve(output, from.replace(/\.md$/, '.html'));
  if (!destination.startsWith(output + path.sep)) throw new Error(`Invalid redirect path: ${from}`);
  const relative = path.posix.relative(path.posix.dirname(from), to).replace(/\.md$/, '.html');
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>文档已迁移</title><meta http-equiv="refresh" content="0;url=${relative}"><script>location.replace(${JSON.stringify(relative)}+location.search+location.hash)</script><a href="${relative}">打开新页面</a></html>`, 'utf8');
}
console.log(`Generated ${Object.keys(redirects).length} legacy URL redirects.`);
