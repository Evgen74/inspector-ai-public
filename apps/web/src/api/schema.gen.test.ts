// @vitest-environment node
/** Generated code is committed and must be fresh: regenerate in memory from the merged OpenAPI and compare. */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
// @ts-expect-error — plain ESM script without type declarations
import { generateApiTypes, OUT_FILE } from '../../scripts/gen-api-types.mjs';

describe('src/api/schema.gen.ts', () => {
  it('matches the contracts OpenAPI + pending overlay (run `pnpm --filter @inspector/web gen:api`)', async () => {
    const fresh = (await generateApiTypes()) as string;
    expect(readFileSync(OUT_FILE as string, 'utf8')).toBe(fresh);
  });
});
