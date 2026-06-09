import { defineConfig, loadEnv } from 'vite';
import preact from '@preact/preset-vite';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  const env = {
    ...loadEnv(mode, resolve(__dirname, '..'), ''),
    ...loadEnv(mode, process.cwd(), ''),
    ...process.env,
  };
  const apiHost = env.POLYDATA_API_HOST || '127.0.0.1';
  const apiPort = env.POLYDATA_API_PORT || '5000';
  const apiBase = env.VITE_POLYDATA_API_BASE_URL || '';
  const target = env.VITE_POLYDATA_PROXY_TARGET
    || (apiBase.startsWith('http') ? apiBase : `http://${apiHost}:${apiPort}`);

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
