import swc from 'unplugin-swc';
import { defineConfig } from 'vitest/config';

// AG-05 verification on a real PostgreSQL and Redis. Own database (inspector_test_ag05, created on demand) and
// Redis db 14, so it never races the other test:db suites on the shared inspector_test / db 15. Applies migrations
// 0000–0003 (AG-00 global setup) and then src/modules/verification/sql/0004_verification.sql.
// Run from apps/api: pnpm exec vitest run --config test/verification/vitest.db.config.mts
process.env.INSPECTOR_TEST_DATABASE_URL ??= 'postgresql://localhost:5432/inspector_test_ag05';
process.env.INSPECTOR_TEST_REDIS_URL ??= 'redis://127.0.0.1:6379/14';
export default defineConfig({
  plugins: [swc.vite({ module: { type: 'es6' } })],
  test: {
    root: new URL('../..', import.meta.url).pathname,
    include: ['test/verification/**/*.db.spec.ts'],
    environment: 'node',
    globalSetup: ['test/db/global-setup.ts'],
    testTimeout: 60_000,
    hookTimeout: 60_000,
    fileParallelism: false,
  },
});
