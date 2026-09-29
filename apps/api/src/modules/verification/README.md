# Verification module (AG-05)

Decisions API for the inspector's verification workspace (ТЗ §9.3; 05 §3.6/§3.17/§3.18; 90 status machine): confirm
/ reject / clarify per atomic finding, dispute resolution, process claim/reopen, finalize/un-finalize, completeness,
usability telemetry, decision-code dictionaries and M4 GOLD draft capture.

**Fully implemented and tested** (`verification.controller.ts`, `.service.ts`, `.repository.ts`, `.schema.ts`,
`.views.ts`, `.memory.ts`, `domain/*`), including an end-to-end test against a real PostgreSQL + Redis
(`test/verification/verification.db.spec.ts`, own database) and a recording of the whole API surface a real
session exercises (`test/verification/web-fixture.test.ts` → `apps/web/src/features/verification/fixtures/
tyumen.api.json`, which the web feature's own tests render against). **Not yet reachable in the running app** —
see the two wiring gaps below, both outside this module's owned directory (CLAUDE.md), so this is a request, not a
change made here.

## Wiring requested from AG-00 (one line each)

1. **`apps/api/src/app.module.ts`** — spread this module's controllers and providers into the ones `AppModule`
   already assembles:
   ```ts
   import { VERIFICATION_CONTROLLERS, VERIFICATION_PROVIDERS } from './modules/verification';
   // controllers: [...existing, ...VERIFICATION_CONTROLLERS]
   // providers:   [...existing, ...VERIFICATION_PROVIDERS]
   ```
   Until this lands, every `/processes/*`, `/objects/:id/verification`, `/disputes/*`, `/dictionaries/
   decision-codes`, `/telemetry/ui-events` and `/ml/datasets/draft/items` route is absent from the real server
   (tests only see it because `test/verification/harness.ts` composes it manually — see its docstring).

2. **`apps/api/src/db/schema-all.ts`** — re-export this module's Drizzle tables so the rest of the app (and
   `drizzle-kit generate`) sees them:
   ```ts
   export * from '../modules/verification/verification.schema';
   ```

3. **OpenAPI** — merge `./openapi/verification.openapi.yaml` into `packages/contracts/openapi/openapi.yaml` (or, as
   an interim step, drop it into `apps/api/openapi/pending/`, which `OpenApiService` already merges — see
   `pendingOverlayFiles()` and how `test/verification/harness.ts`'s `OverlayOpenApiService` merges it for tests).

4. **Migration** — apply `./sql/0004_verification.sql` the way `apps/api/drizzle/*.sql` migrations are applied
   (plus a `apps/api/drizzle/meta/_journal.json` entry), so `pnpm db:migrate` / `db:create` create these tables on
   a fresh database exactly as `test/verification/verification.db.spec.ts` applies it for its own database.

## Wiring requested from AG-08 (`apps/web/src/App.tsx`)

`apps/web/src/features/verification/index.ts` documents the exact routes (`VerificationPage` handles all of them
by which URL param is present):
```tsx
<Route path="verification" element={<Lazy><VerificationPage /></Lazy>} />
<Route path="verification/:processId" element={<Lazy><VerificationPage /></Lazy>} />
<Route path="verification/:processId/:findingId" element={<Lazy><VerificationPage /></Lazy>} />
<Route path="objects/:objectId/verify" element={<Lazy><VerificationPage /></Lazy>} />
```
`App.tsx` still routes `path="verification"` to the M1 `SectionPlaceholder`. The feature is covered end to end by
`apps/web/src/features/verification/Workspace.test.tsx` (queue, evidence card, keyboard confirm, reject-by-chip,
the finalized state) against the real recorded fixture above, so this is routing only — no component work is
pending.

## Endpoints (see `openapi/verification.openapi.yaml` for the full contract)

`GET /objects/{object_id}/verification`, `GET /processes/{id}/verification`, `GET /processes/{id}/findings`,
`GET /processes/{id}/findings/{finding_id}[/history]`, `POST /processes/{id}/findings/{finding_id}/decisions
[/validate]`, `GET /processes/{id}/disputes`, `POST /disputes/{id}/resolve`, `POST /processes/{id}/verification/
claim|reopen`, `POST /processes/{id}/finalize|unfinalize`, `GET /processes/{id}/completeness|protocol|
rin-payload/preview|usability`, `GET /dictionaries/decision-codes`, `POST /telemetry/ui-events`,
`GET /ml/datasets/draft/items`.

Writes require `Idempotency-Key` (UUID, replayed on retry) and `If-Match` (row_version of the finding or the
process). Every write records its own audit event through `AuditService.record` inside the same transaction.
