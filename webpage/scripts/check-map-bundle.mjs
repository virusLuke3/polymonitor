import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';

const dist = resolve(process.cwd(), 'dist');
const assets = resolve(dist, 'assets');
const files = readdirSync(assets);
const required = ['maplibre-', 'maplibre-gl-worker-', 'deck-stack-', 'map-geo-'];
const missing = required.filter((prefix) => !files.some((file) => file.startsWith(prefix) && file.endsWith('.js')));
if (missing.length) throw new Error(`Missing lazy map chunks: ${missing.join(', ')}`);

const html = readFileSync(resolve(dist, 'index.html'), 'utf8');
const forbiddenPreloads = files.filter((file) => required.some((prefix) => file.startsWith(prefix)) && html.includes(file));
if (forbiddenPreloads.length) {
  throw new Error(`Lazy map chunks leaked into entry HTML preload: ${forbiddenPreloads.join(', ')}`);
}

const entry = files
  .filter((file) => /^index-.*\.js$/.test(file))
  .map((file) => ({ file, size: statSync(resolve(assets, file)).size }))
  .sort((left, right) => right.size - left.size)[0];
if (!entry) throw new Error('Unable to locate the frontend entry chunk.');
const maxEntryBytes = 2_200_000;
if (entry.size > maxEntryBytes) {
  throw new Error(`Entry chunk ${entry.file} is ${entry.size} bytes; map split gate is ${maxEntryBytes}.`);
}

// HTML preload tags alone miss static imports pulled into a manual vendor
// chunk (notably Vite's shared preload helper). Check the actual entry graph.
const inspectImports = (path, staticImports = new Set()) => {
  if (staticImports.has(path)) return staticImports;
  staticImports.add(path);
  const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement) && !ts.isExportDeclaration(statement)) continue;
    const specifier = statement.moduleSpecifier;
    if (specifier && ts.isStringLiteral(specifier) && specifier.text.startsWith('.')) {
      inspectImports(resolve(dirname(path), specifier.text), staticImports);
    }
  }
  return staticImports;
};
const staticImports = inspectImports(resolve(assets, entry.file));
const eagerMapImports = [...staticImports].filter(path => required.some(prefix => path.includes(`/assets/${prefix}`)));
if (eagerMapImports.length) throw new Error(`Lazy map engine is statically imported by the entry: ${eagerMapImports.join(', ')}`);
const lightweightRoots = files.filter(file => /^(?:WorldEventMap|SvgMapRenderer|globe\.gl)-.*\.js$/.test(file));
for (const file of lightweightRoots) {
  const heavy = [...inspectImports(resolve(assets, file))].filter(path => /\/(?:deck-stack|maplibre|map-tiles)-/.test(path));
  if (heavy.length) throw new Error(`${file} imports a WebGL engine before it is needed: ${heavy.join(', ')}`);
}

const sw = readFileSync(resolve(dist, 'sw.js'), 'utf8');
const lazyAssetsInPrecache = files.filter((file) => (
  /^(?:WorldEventMap|DeckMapRenderer|SvgMapRenderer|maplibre|deck-stack|map-tiles|map-geo|globe\.gl|hls)(?:[.-])/.test(file)
  && sw.includes(`/assets/${file}`)
));
if (lazyAssetsInPrecache.length) {
  throw new Error(`Service worker eagerly precaches lazy map assets: ${lazyAssetsInPrecache.join(', ')}`);
}

console.log(JSON.stringify({
  entry,
  lazyMapChunks: files.filter((file) => required.some((prefix) => file.startsWith(prefix))),
  preloadedLazyChunks: forbiddenPreloads.length,
  staticallyImportedLazyChunks: eagerMapImports.length,
  lightweightRootsChecked: lightweightRoots,
  precachedLazyChunks: lazyAssetsInPrecache.length,
}, null, 2));
