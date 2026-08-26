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
const screenshotOption = option('--screenshot', '');
const screenshotOutput = screenshotOption ? resolve(screenshotOption) : '';
const strict = args.includes('--strict');
const verbose = args.includes('--verbose');
const requireDynamic = args.includes('--require-dynamic');
const requireEvents = args.includes('--require-events');
const requireHazards = args.includes('--require-hazards');
const openEvents = args.includes('--open-events');
const viewportWidth = Math.max(320, Number(option('--width', '1440')));
const viewportHeight = Math.max(480, Number(option('--height', '900')));
const budgets = {
  jsBuildP95Ms: Number(option('--max-js-build-p95', '20')),
  deckCommitP95Ms: Number(option('--max-deck-commit-p95', '20')),
  longTaskMaxMs: Number(option('--max-long-task', '150')),
};

function summarizeDataSamples(samples = []) {
  const byPhase = {};
  for (const sample of samples) {
    const bucket = byPhase[sample.phase] || { count: 0, maxMs: 0, durations: [], eventCount: 0 };
    bucket.count += 1;
    bucket.maxMs = Math.max(bucket.maxMs, Number(sample.durationMs) || 0);
    bucket.durations.push(Number(sample.durationMs) || 0);
    bucket.eventCount = Math.max(bucket.eventCount, Number(sample.eventCount) || 0);
    byPhase[sample.phase] = bucket;
  }
  for (const bucket of Object.values(byPhase)) {
    bucket.durations.sort((left, right) => left - right);
    const index = Math.max(0, Math.ceil(bucket.durations.length * 0.95) - 1);
    bucket.p95Ms = bucket.durations[index] || 0;
    delete bucket.durations;
  }
  const firstPublishAtMs = samples
    .filter((sample) => sample.phase === 'publish')
    .reduce((earliest, sample) => Math.min(earliest, Number(sample.at) || Infinity), Infinity);
  return {
    samples,
    phases: byPhase,
    firstPublishAtMs: Number.isFinite(firstPublishAtMs) ? firstPublishAtMs : null,
  };
}
const isLoopbackTarget = ['127.0.0.1', 'localhost', '::1'].includes(target.hostname);
const proxyServer = option('--proxy', isLoopbackTarget
  ? ''
  : process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy || '');
const useAngle = option('--use-angle', '');
const progress = (message) => {
  if (verbose) process.stderr.write(`[map-perf] ${message}\n`);
};
const port = 19000 + (process.pid % 1000);
const profile = mkdtempSync(resolve(tmpdir(), 'polymonitor-map-perf-'));
const chrome = spawn('/usr/bin/google-chrome', [
  '--headless=new',
  '--disable-gpu-sandbox',
  '--no-sandbox',
  '--disable-extensions',
  '--disable-background-networking',
  '--disable-sync',
  ...(proxyServer ? [`--proxy-server=${proxyServer}`] : ['--no-proxy-server']),
  ...(useAngle ? [`--use-angle=${useAngle}`, '--ignore-gpu-blocklist'] : []),
  ...(useAngle === 'vulkan' ? ['--enable-features=Vulkan'] : []),
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  `--window-size=${viewportWidth},${viewportHeight}`,
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
    // Install the dispatcher before awaiting `open`. On a loopback DevTools
    // socket the connection can already be OPEN when ready() runs; the old
    // early return then left every CDP command waiting forever.
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        this.pending.delete(message.id);
        clearTimeout(pending?.timeout);
        if (message.error) pending?.reject(new Error(message.error.message));
        else pending?.resolve(message.result);
        return;
      }
      for (const listener of this.listeners.get(message.method) || []) listener(message.params);
    });
  }
  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolveReady, reject) => {
      this.socket.addEventListener('open', resolveReady, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
  }
  send(method, params = {}, timeoutMs = 15000) {
    const id = this.nextId++;
    return new Promise((resolveSend, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolveSend, reject, timeout });
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

async function waitForMappedEvents(client, hazardsRequired, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastState = { count: 0, hazardsReady: false, legend: '' };
  while (Date.now() < deadline) {
    const result = await client.send('Runtime.evaluate', {
      expression: `(() => {
        const value = document.querySelector('.wm-world-event-list-toggle strong')?.textContent || '0';
        const count = Number(value.replace(/[^0-9]/g, '')) || 0;
        const legend = document.querySelector('.wm-weather-deck-legend')?.textContent || '';
        const hazardsReady = /STORMS|QUAKES|VOLCANOES|WILDFIRES|EXTREME|ANOMAL/i.test(legend);
        return { count, hazardsReady, legend, ready: count > 0 && (${hazardsRequired ? 'true' : 'false'} ? hazardsReady : true) };
      })()`,
      returnByValue: true,
    });
    if (result.result?.value) lastState = result.result.value;
    if (lastState.ready) return lastState;
    await sleep(150);
  }
  return lastState;
}

let client;
try {
  progress('waiting for Chrome DevTools');
  await waitForEndpoint('/json/version');
  progress('creating page target');
  const page = await waitForEndpoint('/json/new?about%3Ablank');
  if (!page?.webSocketDebuggerUrl) throw new Error('Chrome page target was unavailable.');
  client = new CdpClient(page.webSocketDebuggerUrl);
  await client.ready();
  progress('connected to page target');
  await Promise.all([
    client.send('Page.enable'),
    client.send('Runtime.enable'),
    client.send('Performance.enable'),
    client.send('Network.enable'),
    client.send('Log.enable'),
  ]);
  await client.send('Emulation.setDeviceMetricsOverride', {
    width: viewportWidth,
    height: viewportHeight,
    deviceScaleFactor: 1,
    mobile: viewportWidth <= 860,
  });
  await client.send('Network.setBypassServiceWorker', { bypass: true });
  const loadFailures = [];
  const runtimeErrors = [];
  const responseByRequest = new Map();
  const networkBodies = [];
  const networkBodyTasks = [];
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
  client.on('Network.responseReceived', ({ requestId, response, type }) => {
    const url = String(response?.url || '');
    if (!url.includes('/natural-hazards/map') && !url.includes('.pmtiles')) return;
    responseByRequest.set(requestId, {
      requestId,
      url,
      type,
      status: response.status,
      headers: response.headers || {},
      mimeType: response.mimeType,
      encodedBytes: 0,
      bodyBytes: null,
      geometryBytes: null,
    });
  });
  client.on('Network.loadingFinished', ({ requestId, encodedDataLength }) => {
    const record = responseByRequest.get(requestId);
    if (!record) return;
    record.encodedBytes = Number(encodedDataLength) || 0;
    networkBodies.push(record);
    if (!record.url.includes('/natural-hazards/map')) return;
    networkBodyTasks.push(client.send('Network.getResponseBody', { requestId }).then(({ body, base64Encoded }) => {
      const decoded = base64Encoded ? Buffer.from(body, 'base64').toString('utf8') : String(body || '');
      record.bodyBytes = Buffer.byteLength(decoded);
      try {
        const payload = JSON.parse(decoded);
        const geometryPayload = (payload.events || []).map((event) => ({
          geometry: event.geometry,
          geometries: event.properties?.geometries,
        }));
        record.geometryBytes = Buffer.byteLength(JSON.stringify(geometryPayload));
      } catch {
        record.geometryBytes = null;
      }
    }).catch(() => undefined));
  });
  const traceEvents = [];
  client.on('Tracing.dataCollected', ({ value }) => traceEvents.push(...value));
  await client.send('Tracing.start', {
    categories: 'devtools.timeline,blink.user_timing,v8,disabled-by-default-devtools.timeline',
    options: 'sampling-frequency=10000',
    transferMode: 'ReportEvents',
  });
  progress(`navigating to ${target.href}`);
  try {
    await client.send('Page.navigate', { url: target.href });
  } catch (error) {
    // Some headless GPU stacks commit the navigation but do not acknowledge
    // Page.navigate until the first renderer frame. Continue with the bounded
    // readiness probe; a genuinely failed navigation is reported with DOM and
    // network diagnostics below.
    if (!(error instanceof Error) || !error.message.startsWith('CDP Page.navigate timed out')) throw error;
    progress('Page.navigate acknowledgement timed out; probing the committed target');
  }
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
  progress('renderer ready');
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
  progress('renderer performance samples ready');
  const mappedEventState = await waitForMappedEvents(client, requireHazards);
  const mappedEventCount = mappedEventState.count;
  if ((requireEvents && mappedEventCount === 0) || (requireHazards && !mappedEventState.hazardsReady)) {
    const diagnostics = await client.send('Runtime.evaluate', {
      expression: `({
        sourceStates: Array.from(document.querySelectorAll('[data-source-state]')).map((node) => ({
          source: node.getAttribute('data-source-state'),
          text: node.textContent,
        })),
        bodyText: document.body?.innerText?.slice(0, 900) || '',
      })`,
      returnByValue: true,
    });
    throw new Error(`No mapped events became available before measurement: ${JSON.stringify({
      page: diagnostics.result?.value,
      loadFailures,
      runtimeErrors,
    })}`);
  }
  progress(`mapped events ready count=${mappedEventCount}`);
  if (openEvents) {
    await client.send('Runtime.evaluate', {
      expression: `document.querySelector('.wm-world-event-list-toggle')?.click()`,
    });
    await sleep(500);
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
    // Exercise the same frame pacing as a physical drag. Sending press, a
    // 90px jump and release back-to-back creates a synthetic burst that Chrome
    // never has an opportunity to coalesce or hand to movestart.
    await sleep(34);
    for (let step = 1; step <= 6; step += 1) {
      await client.send('Input.dispatchMouseEvent', {
        type: 'mouseMoved',
        x: x + 15 * step,
        y: y + (20 / 6) * step,
        button: 'left',
      });
      await sleep(17);
    }
    await client.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x + 90, y: y + 20, button: 'left', clickCount: 1 });
    await sleep(1200);
  }
  if (screenshotOutput) {
    const screenshot = await client.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
      fromSurface: true,
    });
    mkdirSync(dirname(screenshotOutput), { recursive: true });
    writeFileSync(screenshotOutput, Buffer.from(screenshot.data, 'base64'));
  }
  const snapshotResult = await client.send('Runtime.evaluate', {
    expression: 'window.__POLYMONITOR_MAP_PERF__?.snapshot() || null',
    returnByValue: true,
  });
  const dataSnapshotResult = await client.send('Runtime.evaluate', {
    expression: 'window.__POLYMONITOR_MAP_DATA_PERF__?.snapshot() || []',
    returnByValue: true,
  });
  await Promise.allSettled(networkBodyTasks);
  const lifecycleResult = await client.send('Runtime.evaluate', {
    expression: `(() => ({
      marks: Object.fromEntries(performance.getEntriesByType('mark')
        .filter((entry) => entry.name.startsWith('polymonitor:map:first-'))
        .map((entry) => [entry.name, entry.startTime])),
      canvases: document.querySelectorAll('.wm-weather-deck-basemap canvas').length,
      aviationCanvases: document.querySelectorAll('.wm-weather-deck-basemap .deck-canvas').length,
    }))()`,
    returnByValue: true,
  });
  const metrics = await client.send('Performance.getMetrics');
  const completed = client.once('Tracing.tracingComplete');
  await client.send('Tracing.end');
  await completed;
  progress('trace collected');
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, JSON.stringify({ traceEvents }));
  const snapshot = snapshotResult.result?.value;
  const dataSnapshot = dataSnapshotResult.result?.value || [];
  const hazardResponses = networkBodies.filter((record) => record.url.includes('/natural-hazards/map'));
  const pmtilesResponses = networkBodies.filter((record) => record.url.includes('.pmtiles'));
  const lifecycle = lifecycleResult.result?.value || { marks: {}, canvases: 0, aviationCanvases: 0 };
  const publishTimes = dataSnapshot.filter((sample) => sample.phase === 'publish').map((sample) => Number(sample.at) || 0);
  const summary = {
    url: target.href,
    trace: output,
    traceEvents: traceEvents.length,
    screenshot: screenshotOutput || null,
    mappedEventCount,
    mappedHazardsReady: mappedEventState.hazardsReady,
    viewport: { width: viewportWidth, height: viewportHeight },
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
    mapData: summarizeDataSamples(dataSnapshot),
    lifecycle: {
      firstMapShellMs: lifecycle.marks?.['polymonitor:map:first-shell'] ?? null,
      firstBasemapMs: lifecycle.marks?.['polymonitor:map:first-basemap'] ?? null,
      firstHazardMs: lifecycle.marks?.['polymonitor:map:first-hazard'] ?? null,
      completeVisibleHazardsMs: publishTimes.length ? Math.max(...publishTimes) : null,
    },
    network: {
      initialHazardPayloadBytes: hazardResponses.reduce((sum, response) => sum + (response.bodyBytes ?? response.encodedBytes ?? 0), 0),
      initialHazardGeometryBytes: hazardResponses.reduce((sum, response) => sum + (response.geometryBytes || 0), 0),
      hazardResponses: hazardResponses.map(({ url, status, encodedBytes, bodyBytes, geometryBytes }) => ({
        url, status, encodedBytes, bodyBytes, geometryBytes,
      })),
      pmtilesRangeResponses: pmtilesResponses.map(({ url, status, encodedBytes, headers }) => ({
        url, status, encodedBytes,
        contentRange: headers['content-range'] || headers['Content-Range'] || null,
      })),
    },
    canvas: {
      total: lifecycle.canvases,
      deck: lifecycle.aviationCanvases,
    },
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
    if (requireHazards && !dataSnapshot.some((sample) => (
      sample.phase === 'publish' && sample.eventCount > 0
    ))) {
      failures.push('hazard source data produced no measured publish sample');
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
