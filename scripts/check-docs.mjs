import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { nav, sections, sidebar } from '../docs/.vitepress/site-map.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../docs');
const errors = [];
const markdown = new Map();
async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
    const name = path.join(directory, entry.name);
    if (entry.isDirectory()) await walk(name);
    else if (name.endsWith('.md')) markdown.set(path.relative(root, name).replaceAll('\\', '/'), await readFile(name, 'utf8'));
  }
}
await walk(root);
async function exists(name) {
  try { return (await stat(name)).isFile(); } catch { return false; }
}
function links(text) {
  const prose = text.replace(/^```[^\n]*\n[\s\S]*?^```\s*$/gm, '');
  const found = [...prose.matchAll(/\]\((<[^>]+>|[^)\n]+)\)/g)].map(match => match[1].replace(/^<|>$/g, '').replace(/\s+["'][^"']*["']$/, ''));
  found.push(...[...prose.matchAll(/(?:href|src)=["']([^"']+)["']/g)].map(match => match[1]));
  found.push(...[...prose.matchAll(/^\s+link:\s*(\S+)\s*$/gm)].map(match => match[1]));
  return found;
}
async function resolveLink(from, raw) {
  if (!raw || /^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(raw)) return null;
  let link;
  try { link = decodeURIComponent(raw.split(/[?#]/)[0]); } catch { errors.push(`${from}: invalid URL ${raw}`); return null; }
  if (!link) return null;
  if (link.startsWith('/MediaCrawler/')) link = link.slice('/MediaCrawler'.length);
  const relative = path.posix.normalize(link.startsWith('/') ? link.slice(1) : path.posix.join(path.posix.dirname(from), link));
  const full = path.resolve(root, relative);
  if (!full.startsWith(root + path.sep) && full !== root) {
    errors.push(`${from}: link leaves docs: ${raw}`); return null;
  }
  const candidates = path.extname(relative) ? [relative] : [relative, relative + '.md', path.posix.join(relative, 'index.md')];
  if (relative.endsWith('.html')) candidates.unshift(relative.slice(0, -5) + '.md');
  for (const candidate of candidates) {
    if (await exists(path.join(root, candidate))) return candidate;
  }
  errors.push(`${from}: missing local target ${raw}`);
  return null;
}
const graph = new Map();
for (const [name, body] of markdown) {
  const targets = [];
  for (const link of links(body)) {
    const target = await resolveLink(name, link);
    if (target?.endsWith('.md')) targets.push(target);
  }
  graph.set(name, targets);
}
const required = ['getting-started', 'guides', 'architecture', 'development', 'operations', 'history', 'adr', 'about'];
for (const directory of required) {
  const index = `${directory}/index.md`;
  if (!markdown.has(index)) errors.push(`Missing section index: ${index}`);
  for (const name of markdown.keys()) {
    if (path.posix.dirname(name) === directory && name !== index && !graph.get(index)?.includes(name)) errors.push(`${index}: direct page not indexed: ${name}`);
  }
}
for (const name of ['index.md', 'documentation-map.md', 'roadmap.md']) if (!markdown.has(name)) errors.push(`Missing root page: ${name}`);
const reached = new Set();
function visit(name) {
  if (reached.has(name)) return;
  reached.add(name);
  for (const target of graph.get(name) || []) visit(target);
}
visit('index.md');
const migrations = JSON.parse(await readFile(path.join(root, '.vitepress/migrations.json'), 'utf8'));
for (const [old, target] of Object.entries(migrations)) {
  if (!markdown.has(old) || !markdown.has(target)) errors.push(`Invalid migration: ${old} -> ${target}`);
  else if (!graph.get(old)?.includes(target) || !/迁移|归类/.test(markdown.get(old))) errors.push(`Missing migration notice/link: ${old}`);
}
for (const name of markdown.keys()) {
  if (!Object.hasOwn(migrations, name) && !reached.has(name)) errors.push(`Page is not reachable from homepage: ${name}`);
}
async function checkNavigation(items, top = false) {
  for (const item of items) {
    if (item.link) {
      await resolveLink('.navigation.md', item.link);
      if (top && /作者|付费|订阅|捐赠|赞助/.test(item.text)) errors.push(`Promotion in primary navigation: ${item.text}`);
    }
    if (item.items) await checkNavigation(item.items, top);
  }
}
await checkNavigation(nav, true);
await checkNavigation(sidebar);
for (const section of sections) if (!required.includes(section.dir)) errors.push(`Unexpected section: ${section.dir}`);
const config = await readFile(path.join(root, '.vitepress/config.mjs'), 'utf8');
if (/googletagmanager|google-analytics|gtag\s*\(|editLink|ignoreDeadLinks\s*:\s*true/.test(config)) errors.push('Tracking, wrong edit link or ignored dead links found in site config');
const ids = new Set();
for (const [name, body] of markdown) {
  if (!name.startsWith('adr/') || name.endsWith('/index.md')) continue;
  const id = name.match(/\/([0-9]{4})-/)?.[1];
  if (!id || ids.has(id)) errors.push(`Invalid or duplicate ADR number: ${name}`);
  if (!/> 状态：(?:已接受|已取代|已废弃)/.test(body)) errors.push(`ADR requires explicit status: ${name}`);
  ids.add(id);
}
if (errors.length) {
  process.stderr.write(errors.join('\n') + `\nDocumentation structure failed: ${errors.length} issue(s).\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`Documentation structure passed: ${markdown.size} pages, ${required.length} sections, ${Object.keys(migrations).length} legacy routes, ${ids.size} ADRs.\n`);
}
