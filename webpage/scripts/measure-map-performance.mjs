import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
};
const target = new URL(args.find((value) => !value.startsWith('--')) || 'http://127.0.0.1:4173/');
target.searchParams.set('view', '2d');
target.searchParams.set('mapPerf', '1');
const settleMs = Number(option('--settle', '6000'));
const warmupMs = Number(option('--warmup', '1000'));
const output = resolve(option('--out', 'artifacts/map-performance/chrome-trace.json'));
const strict = args.includes('--strict');
const requireDynamic = args.includes('--require-dynamic');
const budgets = {
  jsBuildP95Ms: Number(option('--max-js-build-p95', '20')),
  deckCommitP95Ms: Number(option('--max-deck-commit-p95', '20')),
  longTaskMaxMs: Number(option('--max-long-task', '150')),
};
const isLoopbackTarget = ['127.0.0.1', 'localhost', '::1'].includes(target.hostname);
const proxyServer = option('--proxy', isLoopbackTarget
  ? ''
  : process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy || '');
const useAngle = option('--use-angle', '');
const port = 19000 + (process.pid % 1000);
const profile = mkdtempSync(resolve(tmpdir(), 'polymonitor-map-perf-'));
const chrome = spawn('/usr/bin/google-chrome', [
  '--headless=new',
  '--disable-gpu-sandbox',
  '--no-sandbox',
  '--disable-extensions',
  '--disable-background-networking',
  '--disable-sync',
  ...(proxyServer ? [`--proxy-server=${proxyServer}`] : []),
  ...(useAngle ? [`--use-angle=${useAngle}`, '--ignore-gpu-blocklist'] : []),
  ...(useAngle === 'vulkan' ? ['--enable-features=Vulkan'] : []),
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  '--window-size=1440,900',
  'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
async function waitForEndpoint(path, attempts = 80) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}${path}`, { method: path.startsWith('/json/new') ? 'PUT' : 'GET' });
      if (response.ok) return response.json();
    } catch {}
    await sleep(100);
  }
  throw new Error('Chrome DevTools endpoint did not become ready.');
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }
  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolveReady, reject) => {
      this.socket.addEventListener('open', resolveReady, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) pending?.reject(new Error(message.error.message));
        else pending?.resolve(message.result);
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) listener(message.params);
    });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolveSend, reject) => {
      this.pending.set(id, { resolve: resolveSend, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }
  once(method) {
    return new Promise((resolveOnce) => {
      const listener = (params) => {
        const listeners = this.listeners.get(method) || [];
        this.listeners.set(method, listeners.filter((candidate) => candidate !== listener));
        resolveOnce(params);
      };
      this.on(method, listener);
    });
  }
  close() { this.socket.close(); }
}

async function waitForRenderer(client, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const result = await client.send('Runtime.evaluate', {
        expression: 'Boolean(document.querySelector("[data-map-renderer-ready]"))',
        returnByValue: true,
      });
      if (result.result?.value) return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!/Execution context was destroyed|Inspected target navigated/.test(message)) throw error;
    }
    await sleep(100);
  }
  return false;
}

async function waitForPerformanceSamples(client, dynamicRequired, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await client.send('Runtime.evaluate', {
      expression: `(() => {
        const snapshot = window.__POLYMONITOR_MAP_PERF__?.snapshot();
        if (!snapshot) return false;
        return snapshot.phases['js-build'].count > 0
          && snapshot.phases['deck-commit'].count > 0
          && (${dynamicRequired ? 'true' : 'false'} ? snapshot.phases['dynamic-commit'].count > 0 : true);
      })()`,
      returnByValue: true,
    });
    if (result.result?.value) return true;
    await sleep(100);
  }
  return false;
}

let client;
try {
  await waitForEndpoint('/json/version');
  const page = await waitForEndpoint('/json/new?about%3Ablank');
  if (!page?.webSocketDebuggerUrl) throw new Error('Chrome page target was unavailable.');
  client = new CdpClient(page.webSocketDebuggerUrl);
  await client.ready();
  await Promise.all([
    client.send('Page.enable'),
    client.send('Runtime.enable'),
    client.send('Performance.enable'),
    client.send('Network.enable'),
    client.send('Log.enable'),
  ]);
  await client.send('Network.setBypassServiceWorker', { bypass: true });
  const loadFailures = [];
  const runtimeErrors = [];
  client.on('Network.loadingFailed', ({ errorText, type, canceled }) => {
    if (!canceled && loadFailures.length < 12) loadFailures.push(`${type || 'Other'}: ${errorText}`);
  });
  client.on('Runtime.exceptionThrown', ({ exceptionDetails }) => {
    if (runtimeErrors.length < 12) {
      runtimeErrors.push(exceptionDetails?.exception?.description || exceptionDetails?.text || 'Runtime exception');
    }
  });
  client.on('Log.entryAdded', ({ entry }) => {
    if (entry?.level === 'error' && runtimeErrors.length < 12) runtimeErrors.push(entry.text);
  });
  const traceEvents = [];
  client.on('Tracing.dataCollected', ({ value }) => traceEvents.push(...value));
  await client.send('Tracing.start', {
    categories: 'devtools.timeline,blink.user_timing,v8,disabled-by-default-devtools.timeline',
    options: 'sampling-frequency=10000',
    transferMode: 'ReportEvents',
  });
  await client.send('Page.navigate', { url: target.href });
  const rendererReady = await waitForRenderer(client, 30000);
  if (!rendererReady) {
    const diagnostics = await client.send('Runtime.evaluate', {
      expression: `({
        href: location.href,
        title: document.title,
        readyState: document.readyState,
        bodyText: document.body?.innerText?.slice(0, 500) || '',
        scripts: Array.from(document.scripts).map((script) => script.src).filter(Boolean).slice(-8),
      })`,
      returnByValue: true,
    });
    throw new Error(`2D map renderer did not become ready: ${JSON.stringify({
      page: diagnostics.result?.value,
      loadFailures,
      runtimeErrors,
    })}`);
  }
  const samplesReady = await waitForPerformanceSamples(client, requireDynamic);
  if (!samplesReady) {
    const diagnostics = await client.send('Runtime.evaluate', {
      expression: `({
        renderer: document.querySelector('[data-map-renderer-ready]')?.getAttribute('data-map-renderer-ready') || null,
        performance: window.__POLYMONITOR_MAP_PERF__?.snapshot() || null,
        bodyText: document.body?.innerText?.slice(0, 500) || '',
      })`,
      returnByValue: true,
    });
    throw new Error(`Map performance phases did not become ready before measurement: ${JSON.stringify({
      page: diagnostics.result?.value,
      loadFailures,
      runtimeErrors,
    })}`);
  }
  await sleep(warmupMs);
  await client.send('Runtime.evaluate', {
    expression: 'window.__POLYMONITOR_MAP_PERF__?.resetLongTasks()',
  });
  await sleep(settleMs);
  const boundsResult = await client.send('Runtime.evaluate', {
    expression: `(() => {
      const rect = document.querySelector('.wm-weather-deck-basemap')?.getBoundingClientRect();
      return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null;
    })()`,
    returnByValue: true,
  });
  const bounds = boundsResult.result?.value;
  if (bounds) {
    const x = bounds.x + bounds.width * 0.56;
    const y = bounds.y + bounds.height * 0.52;
    await client.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await client.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await client.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x + 90, y: y + 20, button: 'left' });
    await client.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x + 90, y: y + 20, button: 'left', clickCount: 1 });
    await sleep(1200);
  }
  const snapshotResult = await client.send('Runtime.evaluate', {
    expression: 'window.__POLYMONITOR_MAP_PERF__?.snapshot() || null',
    returnByValue: true,
  });
  const metrics = await client.send('Performance.getMetrics');
  const completed = client.once('Tracing.tracingComplete');
  await client.send('Tracing.end');
  await completed;
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, JSON.stringify({ traceEvents }));
  const snapshot = snapshotResult.result?.value;
  const summary = {
    url: target.href,
    trace: output,
    traceEvents: traceEvents.length,
    renderer: await client.send('Runtime.evaluate', {
      expression: 'document.querySelector("[data-map-renderer-ready]")?.dataset.mapRendererReady || null',
      returnByValue: true,
    }).then((result) => result.result?.value),
    gpu: await client.send('Runtime.evaluate', {
      expression: `(() => {
        const gl = document.createElement('canvas').getContext('webgl2');
        const extension = gl?.getExtension('WEBGL_debug_renderer_info');
        return extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : null;
      })()`,
      returnByValue: true,
    }).then((result) => result.result?.value),
    map: snapshot,
    warmupMs,
    budgets,
    chromeMetrics: Object.fromEntries((metrics.metrics || []).map((metric) => [metric.name, metric.value])),
  };
  console.log(JSON.stringify(summary, null, 2));
  if (!snapshot) throw new Error('Map performance snapshot was unavailable.');
  if (strict) {
    const failures = [];
    if (snapshot.phases['js-build'].count === 0) failures.push('js-build produced no samples');
    if (snapshot.phases['deck-commit'].count === 0) failures.push('deck-commit produced no samples');
    if (snapshot.phases['js-build'].p95Ms > budgets.jsBuildP95Ms) {
      failures.push(`js-build p95 ${snapshot.phases['js-build'].p95Ms.toFixed(1)}ms > ${budgets.jsBuildP95Ms}ms`);
    }
    if (snapshot.phases['deck-commit'].p95Ms > budgets.deckCommitP95Ms) {
      failures.push(`deck-commit p95 ${snapshot.phases['deck-commit'].p95Ms.toFixed(1)}ms > ${budgets.deckCommitP95Ms}ms`);
    }
    if (snapshot.longTasks.maxMs > budgets.longTaskMaxMs) {
      failures.push(`long task max ${snapshot.longTasks.maxMs.toFixed(1)}ms > ${budgets.longTaskMaxMs}ms`);
    }
    if (requireDynamic && snapshot.phases['dynamic-commit'].count === 0) {
      failures.push('dynamic-commit produced no samples; run against a backend with aviation events');
    }
    if (failures.length) throw new Error(`Map performance gate failed: ${failures.join('; ')}`);
  }
} finally {
  client?.close();
  const chromeExited = new Promise((resolveExit) => chrome.once('exit', resolveExit));
  chrome.kill('SIGTERM');
  await Promise.race([chromeExited, sleep(2000)]);
  rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
