import { defineConfig, loadEnv } from 'vite';
import preact from '@preact/preset-vite';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, resolve(__dirname, '..'), ''),
    ...loadEnv(mode, process.cwd(), ''),
  };
  const apiHost = env.POLYDATA_API_HOST || '127.0.0.1';
  const apiPort = env.POLYDATA_API_PORT || '5000';
  const configuredTarget = env.VITE_POLYDATA_PROXY_TARGET || env.VITE_POLYDATA_API_BASE_URL || '';
  const target = /^https?:\/\//.test(configuredTarget) ? configuredTarget : `http://${apiHost}:${apiPort}`;

  return {
    plugins: [preact()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 3000,
      proxy: {
        '/wm-api': {
          target,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/wm-api/, ''),
        },
      },
    },
  };
});
