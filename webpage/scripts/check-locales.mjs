import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..', 'src', 'locales');
const localeNames = ['en', 'zh'];

const readCatalog = async (name) => {
  const raw = await readFile(resolve(root, `${name}.json`), 'utf8');
  const value = JSON.parse(raw);
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${name}.json must contain one flat message object`);
  }
  for (const [key, message] of Object.entries(value)) {
    if (!/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)+$/.test(key)) {
      throw new Error(`${name}.json contains unstable message key: ${key}`);
    }
    if (typeof message !== 'string' || !message.trim()) {
      throw new Error(`${name}.json contains an empty or non-string message: ${key}`);
    }
  }
  return value;
};

const catalogs = Object.fromEntries(await Promise.all(localeNames.map(async (name) => [name, await readCatalog(name)])));
const reference = Object.keys(catalogs.en).sort();
let failed = false;
for (const name of localeNames.slice(1)) {
  const keys = Object.keys(catalogs[name]).sort();
  const missing = reference.filter((key) => !keys.includes(key));
  const extra = keys.filter((key) => !reference.includes(key));
  if (missing.length || extra.length) {
    failed = true;
    console.error(`${name}: missing=${missing.join(',') || 'none'} extra=${extra.join(',') || 'none'}`);
  }
}
if (failed) process.exit(1);
console.log(`Locale contract OK: ${localeNames.length} locales, ${reference.length} stable keys each.`);
