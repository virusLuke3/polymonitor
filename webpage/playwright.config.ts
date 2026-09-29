import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.POLYMONITOR_E2E_PORT || 4174);
const serverURL = `http://127.0.0.1:${port}`;
const preview = process.env.POLYMONITOR_E2E_PREVIEW === '1';
// Keep user-visible URLs fixed even when another task owns the default port.
const baseURL = 'http://127.0.0.1:4174';

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'artifacts/world-event-map-e2e/results.json' }]],
  use: {
    baseURL,
    // Preview registers the production service worker; keep intercepted API
    // fixtures authoritative instead of letting it bypass Playwright routes.
    serviceWorkers: preview ? 'block' : 'allow',
    timezoneId: 'Asia/Shanghai',
    locale: 'en-US',
    colorScheme: 'light',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{
    name: 'desktop-chrome',
    use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 1440, height: 900 },
      launchOptions: {
        ...(process.env.POLYMONITOR_CHROME_PATH ? { executablePath: process.env.POLYMONITOR_CHROME_PATH } : {}),
        // Keep raster output independent of which tiles were invalidated by
        // asynchronous data/scrolling. Baselines were calibrated against the
        // pre-migration CSS with this setting, at zero pixel tolerance.
        args: ['--disable-partial-raster', ...(process.env.POLYMONITOR_E2E_HARDWARE_WEBGL === '1'
          ? ['--use-angle=vulkan', '--enable-features=Vulkan'] : [])],
      },
    },
  }],
  webServer: {
    command: `npm run ${preview ? 'preview' : 'dev'} -- --host 127.0.0.1 --port ${port} --strictPort${preview ? '' : ' --mode test'}`,
    url: serverURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
