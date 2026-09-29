import { readFileSync, readdirSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import ts from 'typescript';
import postcss from 'postcss';
import { panelStyleOwner, panelStyleFiles } from './frontend-style-owners.mjs';

const root = resolve('src');
const failures = [];
function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  });
}
for (const file of files(root).filter((path) => /\.[cm]?tsx?$/.test(path) && !path.endsWith('.test.ts'))) {
  const path = relative(root, file).replaceAll('\\', '/');
  const text = readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const fail = (node, message) => failures.push(`${path}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}: ${message}`);
  const sourceReads = new Map();
  let definition;
  function walk(node) {
    if (path.startsWith('panels/modules/') && ts.isVariableDeclaration(node) && node.name.getText(source) === 'panel'
      && node.initializer && ts.isCallExpression(node.initializer)) {
      definition = node.initializer.arguments.find((arg) => ts.isObjectLiteralExpression(arg)
        && arg.properties.some((property) => property.name?.getText(source) === 'id'));
    }
    if (path.startsWith('panels/modules/') && ts.isElementAccessExpression(node)
      && ts.isStringLiteral(node.argumentExpression) && /\.runtimeData$/.test(node.expression.getText(source))) {
      sourceReads.set(node.argumentExpression.text, node);
    }
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const target = node.moduleSpecifier.text;
      const typeOnly = node.importClause?.isTypeOnly;
      if (path === 'App.tsx' && (/services\/(api|auth|product)$/.test(target) || /world-event-map\//.test(target))) {
        fail(node, 'Compose domain controllers through the map public entry; App does not own business requests.');
      }
      if (path === 'components/FocusedMarketStrip.tsx' && /services\/api$/.test(target)) {
        fail(node, 'The focused order-book controller owns requests.');
      }
      if (path === 'workspaces/market/MarketWorkspace.tsx' && /services\/api$/.test(target)) {
        fail(node, 'The market dossier controller owns its cancellable request chain.');
      }
      if (/features\/world-event-map\/(domain|adapters)\//.test(path) && !typeOnly
        && /(?:preact|services\/api|components\/|renderer\/|App(?:\.|$))/.test(target)) {
        fail(node, 'Map domain and adapters must remain pure.');
      }
      if (/^services\//.test(path) && !typeOnly && /(?:components\/|workspaces\/|\/App(?:\.|$))/.test(target)) {
        fail(node, 'Services must not depend on page components.');
      }
    }
    if (path.startsWith('panels/modules/') && ts.isPropertyAssignment(node)
      && node.name.getText(source) === 'fetchData' && ts.isArrowFunction(node.initializer)
      && ts.isCallExpression(node.initializer.body)
      && /^fetchRuntime/.test(node.initializer.body.expression.getText(source))
      && !node.initializer.body.arguments.some((arg) => /\??\.signal$/.test(arg.getText(source)))) {
      fail(node, 'Forward the Runtime AbortSignal to the source request.');
    }
    ts.forEachChild(node, walk);
  }
  walk(source);
  if (definition) {
    const property = (name) => definition.properties.find((entry) => ts.isPropertyAssignment(entry) && entry.name.getText(source) === name)?.initializer;
    const literals = (node) => !node ? [] : ts.isStringLiteral(node) ? [node.text]
      : ts.isArrayLiteralExpression(node) ? node.elements.filter(ts.isStringLiteral).map((entry) => entry.text) : [];
    const declared = new Set(['id', 'dataSourceId', 'dataDependencies'].flatMap((name) => literals(property(name))));
    for (const [id, node] of sourceReads) if (!declared.has(id)) {
      fail(node, `Declare shared source ${id} in dataSourceId or dataDependencies so hiding its own panel cannot stop this consumer.`);
    }
  }
}
for (const file of files(root).filter((path) => path.endsWith('.css'))) {
  const path = relative(root, file).replaceAll('\\', '/');
  const css = postcss.parse(readFileSync(file, 'utf8'), { from: file });
  const ownedRules = new Set();
  if (path === 'styles/panels.css' && css.nodes.some(node => node.type !== 'comment' && !(node.type === 'atrule' && node.name === 'import'))) {
    failures.push(`${path}: Keep the panel entry declarative; body rules belong to their owning family.`);
  }
  css.walkRules((rule) => {
    if (!(rule.parent.type === 'atrule' && /keyframes$/.test(rule.parent.name))) {
      const conditions = [];
      for (let parent = rule.parent; parent.type !== 'root'; parent = parent.parent) {
        conditions.push(`${parent.name} ${parent.params}`);
      }
      const key = `${conditions.join('/')}|${rule.selector}`;
      if (ownedRules.has(key)) failures.push(`${path}:${rule.source.start.line}: Merge this rule into its existing state/viewport owner instead of appending an override.`);
      ownedRules.add(key);
    }
    if (path === 'features/market-focus/styles.css') {
      rule.walkDecls((decl) => {
        if (decl.important && !(rule.selector === '.wm-focus-book-row:hover' && decl.prop === 'box-shadow')) {
          failures.push(`${path}:${decl.source.start.line}: Use the owning component/state rule; the only reviewed priority exception suppresses the book's animated hover shadow.`);
        }
      });
    }
    if (!(rule.parent.type === 'atrule' && /keyframes$/.test(rule.parent.name))
      && (Object.values(panelStyleFiles).includes(path) || ['styles/main.css', 'styles/panels.css', 'styles/panel-layout-stability.css'].includes(path))) {
      for (const selector of rule.selectors) {
        const owner = panelStyleOwner(selector);
        if (owner !== 'shell' && path !== panelStyleFiles[owner]) {
          failures.push(`${path}:${rule.source.start.line}: ${selector} belongs to ${panelStyleFiles[owner]}.`);
        }
      }
    }
    if (['styles/main.css', 'styles/panels.css', 'styles/panel-workspace.css'].includes(path)
      && /\.wm-(?:focus(?:ed)?-|live-price-tick|line-chart|underlying|probability)/.test(rule.selector)) {
      failures.push(`${path}:${rule.source.start.line}: Focused market styles belong to features/market-focus/styles.css.`);
    }
    if (/\.wm-panel-slot/.test(rule.selector)) rule.walkDecls(/^grid-(?:row|column)$/, (decl) => {
      if (path !== 'styles/panel-workspace.css' || !decl.value.includes('var(--wm-panel-')) {
        failures.push(`${path}:${decl.source.start.line}: Panel spans must use the effective layout variables.`);
      }
    });
  });
}
if (failures.length) throw new Error(`Frontend boundary violations:\n${failures.join('\n')}`);
console.log('Frontend ownership, request cancellation and layout/CSS boundaries passed.');
