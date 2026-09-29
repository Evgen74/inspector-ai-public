import swc from 'unplugin-swc';
import { defineConfig } from 'vitest/config';

// Integration tests against a real PostgreSQL database (INSPECTOR_TEST_DATABASE_URL, default …/inspector_test).
// Run with `pnpm --filter @inspector/api test:db` (creates the database if needed).
export default defineConfig({
  plugins: [swc.vite({ module: { type: 'es6' } })],
  test: {
    include: ['test/db/**/*.db.test.ts'],
    environment: 'node',
    globalSetup: ['test/db/global-setup.ts'],
    testTimeout: 30_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
});
