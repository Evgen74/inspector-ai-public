import { defineConfig } from 'drizzle-kit';

export default defineConfig({
  dialect: 'postgresql',
  schema: './src/db/schema-all.ts',
  out: './drizzle',
  dbCredentials: { url: process.env.INSPECTOR_DATABASE_URL ?? 'postgresql://localhost:5432/inspector' },
  strict: true,
  verbose: true,
});
