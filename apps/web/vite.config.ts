/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Dev server on :5173 proxies /api to the local API (INSPECTOR_API_PORT, default 3000). No CDN at runtime.
const apiPort = process.env.INSPECTOR_API_PORT ?? '3000';
const apiHost = process.env.INSPECTOR_API_HOST ?? '127.0.0.1';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.INSPECTOR_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: {
      '/api': { target: `http://${apiHost}:${apiPort}`, changeOrigin: false },
      // Prometheus scrape endpoint (module 11) is served outside the /api prefix.
      '/metrics': { target: `http://${apiHost}:${apiPort}`, changeOrigin: false },
    },
  },
  preview: { host: '127.0.0.1', port: 4173 },
  build: { outDir: 'dist', sourcemap: true, chunkSizeWarningLimit: 2000 },
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'test/**/*.test.{ts,tsx}'],
    css: false,
    testTimeout: 20_000,
  },
});
