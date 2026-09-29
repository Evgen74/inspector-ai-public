import swc from 'unplugin-swc';
import { defineConfig } from 'vitest/config';

// SWC (not esbuild) so that Nest's decorator metadata is emitted in tests.
export default defineConfig({
  plugins: [swc.vite({ module: { type: 'es6' } })],
  test: {
    include: ['test/**/*.test.ts'],
    exclude: ['test/db/**', 'node_modules/**'],
    environment: 'node',
    testTimeout: 20_000,
    hookTimeout: 30_000,
    pool: 'threads',
  },
});
