import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { defineConfig, type Plugin } from 'vite';
import preact from '@preact/preset-vite';
import { resolve } from 'path';

const LAZY_MAP_ASSET_RE = /(?:WorldEventMap|DeckMapRenderer|GlobeMapRenderer|SvgMapRenderer|maplibre|deck-stack|map-tiles|map-geo)-[A-Za-z0-9_-]+\.(?:js|css)$/;

function repositorySha() {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  } catch {
    return 'development';
  }
}

function pwaServiceWorker(buildId: string): Plugin {
  return {
    name: 'polydata-pwa-service-worker',
    apply: 'build',
    generateBundle(_options, bundle) {
      this.emitFile({ type: 'asset', fileName: 'release-sha', source: `${buildId}\n` });
      // Follow only static entry dependencies. Dynamic routes, video and 3D
      // engines remain demand-loaded, including during first SW installation.
      const shellAssets = new Set<string>();
      const visit = (name: string) => {
        if (shellAssets.has(name)) return;
        const asset = bundle[name];
        if (!asset || asset.type !== 'chunk') return;
        shellAssets.add(name);
        asset.imports.forEach(visit);
        const metadata = (asset as typeof asset & { viteMetadata?: { importedCss: Set<string> } }).viteMetadata;
        metadata?.importedCss.forEach((css) => shellAssets.add(css));
      };
      Object.values(bundle).forEach((asset) => { if (asset.type === 'chunk' && asset.isEntry) visit(asset.fileName); });
      const generatedAssets = [...shellAssets].map((name) => `/${name}`);
      const precache = [
        '/',
        '/offline.html',
        '/site.webmanifest',
        '/icons/polydata-monitor.svg',
        '/icons/polydata-monitor-192.png',
        '/icons/polydata-monitor-512.png',
        ...generatedAssets,
      ];
      const template = readFileSync(resolve(__dirname, 'src/pwa/sw-template.js'), 'utf8');
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source: template
          .replace("'__POLYDATA_BUILD_ID__'", JSON.stringify(buildId))
          .replace("'__POLYDATA_PRECACHE__'", JSON.stringify(precache)),
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const envPath = resolve(__dirname, mode === 'test' ? 'test-config/.env.test' : '../.env');
  const env = {
    ...(existsSync(envPath) ? parseEnv(readFileSync(envPath, 'utf8')) : {}),
    ...process.env,
  };
  const target = env.POLYDATA_DEV_PROXY_TARGET || '';
  const mapTilesTarget = env.POLYDATA_MAP_TILES_TARGET || '';
  const buildId = String(env.GITHUB_SHA || env.POLYDATA_BUILD_SHA || repositorySha()).slice(0, 40);
  const publicEnv = Object.entries(env).filter(([name]) => name.startsWith('VITE_PUBLIC_')
    || ['VITE_POLYDATA_API_BASE_URL', 'VITE_PMTILES_URL', 'VITE_WEATHER_RADAR_ENABLED'].includes(name));
  for (const [name, value] of publicEnv) {
    if (!value || name === 'VITE_WEATHER_RADAR_ENABLED') continue;
    try {
      const url = new URL(value, 'https://configuration.invalid');
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password
        || value.startsWith('//') || [...url.searchParams.keys()].some(key => /^(api_?key|token|secret|password|authorization)$/i.test(key))) throw new Error();
    } catch {
      throw new Error(`Invalid public source configuration: ${name}`);
    }
  }

  const mapTilesProxy = {
    target: mapTilesTarget,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/map-tiles/, ''),
  };

  return {
    envDir: false,
    envPrefix: 'VITE_PUBLIC_',
    // Prefresh retains historical vnodes for hot replacement. Browser tests
    // measure application ownership, so use production-like component lifetime.
    plugins: [preact({ prefreshEnabled: mode !== 'test' }), pwaServiceWorker(buildId), ...(env.POLYDATA_READONLY_PREVIEW === '1' ? [{
      name: 'anonymous-readonly-preview',
      apply: 'serve' as const,
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith('/wm-api')) return next();
          if (!['GET', 'HEAD'].includes(request.method || '')) {
            response.writeHead(405, { 'Content-Type': 'application/json', Allow: 'GET, HEAD' });
            response.end(JSON.stringify({ error: 'This local preview only reads public data.' }));
            return;
          }
          delete request.headers.cookie;
          delete request.headers.authorization;
          next();
        });
      },
    } satisfies Plugin] : [])],
    define: {
      __BUILD_ID__: JSON.stringify(buildId),
      ...Object.fromEntries(publicEnv
        .map(([name, value]) => [`import.meta.env.${name}`, JSON.stringify(value)])),
    },
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 3000,
      watch: { ignored: ['**/artifacts/**', '**/test-results/**', '**/playwright-report/**'] },
      proxy: {
        ...(target ? { '/wm-api': {
          target,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/wm-api/, ''),
        } } : {}),
        ...(mapTilesTarget ? { '/map-tiles': mapTilesProxy } : {}),
      },
    },
    preview: {
      proxy: {
        ...(target ? { '/wm-api': {
          target,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/wm-api/, ''),
        } } : {}),
        ...(mapTilesTarget ? { '/map-tiles': mapTilesProxy } : {}),
      },
    },
    build: {
      modulePreload: {
        resolveDependencies: (_filename, dependencies, context) => (
          context.hostType === 'html'
            ? dependencies.filter((dependency) => !LAZY_MAP_ASSET_RE.test(dependency))
            : dependencies
        ),
      },
      rollupOptions: {
        output: {
          manualChunks(id) {
            // Otherwise Rollup can put Vite's shared import helper in deck-stack,
            // making the entry import the whole WebGL engine before first paint.
            if (id === '\0vite/preload-helper.js') return 'module-preload';
            if (id.includes('commonjsHelpers.js')) return 'module-helpers';
            if (id.includes('/maplibre-gl/')) return 'maplibre';
            if (id.includes('/@deck.gl/')
              || id.includes('/deck.gl/')
              || id.includes('/@luma.gl/')
              || id.includes('/@loaders.gl/')
              || id.includes('/@math.gl/')) return 'deck-stack';
            if (id.includes('/pmtiles/') || id.includes('/@protomaps/basemaps/')) return 'map-tiles';
            if (id.includes('/supercluster/') || id.includes('/d3-geo/')) return 'map-geo';
            return undefined;
          },
        },
      },
    },
  };
});
