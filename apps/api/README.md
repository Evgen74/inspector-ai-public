# apps/api — REST API (owner: AG-08)

NestJS 11 on Fastify 5, Drizzle ORM + PostgreSQL 17, pino JSON logs. Local-only runtime: no Docker, no network
calls. The web product **imports** `inspector-batch` run directories (97 §2.14); it never writes back into a
submission.

## Run locally

```bash
# once: PostgreSQL database + schema
pnpm --filter @inspector/api db:create        # = make db-create (database `inspector`)
pnpm --filter @inspector/api db:migrate       # apply drizzle/*.sql (idempotent)

pnpm --filter @inspector/api dev              # http://127.0.0.1:3000/api/v1 (watch mode)
pnpm --filter @inspector/api build && pnpm --filter @inspector/api start   # compiled (dist/)

# import a run directory (relative to runs/ or absolute inside it)
curl -X POST http://127.0.0.1:3000/api/v1/admin/batch-runs/import \
  -H 'content-type: application/json' -d '{"run_dir": "<run_id>"}'
```

`make inventory OBJECT=…` (AG-01) writes `runs/<run_id>/run_manifest.json`. When the real inventory is not
available, `pnpm --filter @inspector/api fixture:inventory [-- --object OBJ-… --run-id …]` writes a contract-valid
stand-in from the organizer manifest (existence check only, no hashing, no content).

## Endpoints (contract: `packages/contracts/openapi/openapi.yaml`, OAS 3.0.3; owner AG-00, edits by request)

| Method | Path | |
|---|---|---|
| GET | `/api/v1/health` | 200 `ok` / 503 `degraded` with the DB check |
| GET | `/api/v1/objects` | objects with file counts per `ManifestStage`; `page`, `page_size ≤ 200`, `q` |
| GET | `/api/v1/objects/{object_id}` | object card |
| GET | `/api/v1/objects/{object_id}/files` | file registry; `stage`, `local_status`, `q`, paging |
| GET | `/api/v1/admin/batch-runs` | imported runs, newest first |
| POST | `/api/v1/admin/batch-runs/import` | `{run_dir}` → 201 first import / 200 re-import |

- **Validation**: every request is validated against the OpenAPI document (openapi-backend, ajv 8, Russian
  messages via ajv-i18n); responses are validated too outside `INSPECTOR_APP_ENV=prod`
  (mismatch → 500 `RESPONSE_SCHEMA_VIOLATION`).
- **Errors**: `application/problem+json` per `packages/contracts/schemas/problem.schema.json`; codes, titles and
  details come from `packages/contracts/errors.yaml` (same renderer as `inspector_common.errors`).
- **Request id**: `X-Request-Id` is reused when well-formed, else a UUID v7; it is echoed in the response header,
  every log line (`request_id`) and every problem body.
- **Import**: validates `run_manifest.json` against `run_manifest.schema.json` + referential checks
  (422 `CONTRACT_VALIDATION_FAILED`); `run_dir` must resolve (symlinks included) inside `INSPECTOR_RUNS_ROOT`;
  descriptive file fields (path, section, size, object name) come from the organizer `document_manifest.jsonl`
  only when its sha256 equals the run's `inputs.manifest_sha256`; a changed sha256 for a known `file_id` → 409
  `FILE_ID_IMMUTABLE` (also enforced by a DB trigger). For `TEST_HIDDEN` objects only the inventory is imported and
  artifact paths are dropped (warning `HIDDEN_TEST_ACCESS_DENIED`).

## Data model (drizzle/)

`runs` (owner B00: one row per imported run), `objects` and `files` (owner B01; ТЗ §10 key fields + 97 §2.8
manifest fields + `local_status`). `0001_*.sql` adds owner comments and the file-identity trigger.
Schema: `src/db/schema.ts`; new migration: `pnpm --filter @inspector/api db:generate`.

## Configuration (`INSPECTOR_*`, see the root `.env.example`)

| Variable | Default |
|---|---|
| `INSPECTOR_API_HOST` / `INSPECTOR_API_PORT` | `127.0.0.1` / `3000` |
| `INSPECTOR_DATABASE_URL` | `postgresql://localhost:5432/inspector` |
| `INSPECTOR_RUNS_ROOT` | `<repo>/runs` |
| `INSPECTOR_DATA_ROOT` | `<repo>/data_utf8` (read-only) |
| `INSPECTOR_LOG_LEVEL` / `INSPECTOR_LOG_FORMAT` | `INFO` / `json` (`console` = pino-pretty) |
| `INSPECTOR_APP_ENV` | `local` (`test`, `demo`, `prod`) |
| `INSPECTOR_API_RESPONSE_VALIDATION` | on unless `prod` |
| `INSPECTOR_TEST_DATABASE_URL` | `postgresql://localhost:5432/inspector_test` (`test:db` only) |

## Tests

- `pnpm --filter @inspector/api test` — DB-free (in-memory repositories): health, objects, import, request ids,
  logs, problem bodies vs the contract schema, OpenAPI ↔ routes ↔ enums.yaml/errors.yaml conformance, hashing
  golden vectors shared with Python.
- `pnpm --filter @inspector/api test:db` — the same app on PostgreSQL (`inspector_test`, created and migrated
  automatically).

## D1 read side (AG-08): protocols, dashboard, page annotations

Contract additions live in `openapi/pending/m1-d1.openapi.yaml` until AG-00 merges them into
`packages/contracts/openapi/openapi.yaml`; the API serves the base document plus the overlay (an overlay only adds;
an identical entry is skipped once adopted, a different one keeps the base and fails `test/openapi-overlay.test.ts`).

| Method | Path | Permission | |
|---|---|---|---|
| GET | `/api/v1/dashboard` | `object.read` | objects with the strict colour rule (`src/modules/dashboard/indicator.ts`), tiles, filters `q`, `color`, `section`, `status`, `scenario`, `date_from`, `date_to` (comma lists), findings by section |
| GET | `/api/v1/objects/{object_id}/protocols` | `protocol.read` | protocol versions of the object (one per imported run with a `PROTOCOL_JSON`), newest first |
| GET | `/api/v1/objects/{object_id}/protocols/{run_id}` | `protocol.read` | the Protocol contract document + the run's finding groups (both validated; 422 on a violation) |
| GET | `/api/v1/objects/{object_id}/protocols/{run_id}/export?format=json\|docx\|pdf` | `protocol.export` | AG-04's export file, streamed with a UTF-8 `Content-Disposition` |
| GET | `/api/v1/files/{file_id}/annotations?page=N` | `evidence.read` | revision clouds and room labels of the page from the newest `layout/<file_id>.json` |

- Artifacts are located through `artifacts.json` (fallback: the `run_layout.yaml` template), must stay inside the runs
  root, are validated against their contract schema and cached by (path, mtime, size).
- Objects of the hidden split: 403 `HIDDEN_TEST_ACCESS_DENIED`; their artifacts are never read (dashboard: grey,
  «только инвентаризация»).
- Live decisions: the dashboard colour applies the inspector statuses of `checks` / `suspicions` (AG-00's import,
  updated by AG-05's verification) of the protocol's run, aggregated per finding group — a confirmation turns the
  object red immediately. Without those tables the protocol's own statuses are used.
- `pnpm --filter @inspector/api fixture:d1 [-- --from <inventory run> --run-id d1-fixture-tyumen]` writes the D1 demo run
  (`fixtures/d1`: Тюменская protocol, 4 gold finding groups, 10 atomic findings, F0202 layout with the «Изм. №3» cloud;
  real file hashes and registered markup zones; `ext.note` marks it as a demo) for import.

## Platform services (AG-00): auth, RBAC, audit, batch-run import v2, page viewer

Code: `src/modules/{auth,audit,import,render}` (AG-00), wired in `app.module.ts`; tables in `*.schema.ts` next to
each module, aggregated by `src/db/schema-all.ts`; migrations `0002_platform_auth_audit_import.sql` (tables) and
`0003_platform_audit_append_only_and_protocol_immutability.sql` (triggers, purge function, owner comments).

```bash
make db-migrate && make db-seed      # 1 demo user `inspector` (single role INSPECTOR), password Demo-Inspector-2026 (INSPECTOR_DEMO_PASSWORD)
make dev                             # API + web + ml-api (page renders)
curl -c jar -H 'content-type: application/json' -d '{"login":"inspector","password":"Demo-Inspector-2026"}' \
     http://127.0.0.1:3000/api/v1/auth/login            # → csrf_token; cookie ii_sid in `jar`
curl -b jar -H "X-CSRF-Token: <csrf_token>" -H 'content-type: application/json' \
     -d '{"run_dir":"<run_id>"}' http://127.0.0.1:3000/api/v1/admin/batch-runs/import
```

**Auth** (09 §3.3.1): login/password, argon2id (m=19456 KiB, t=2, p=1, ≈10 ms); opaque 256-bit session token in
the `ii_sid` cookie (HttpOnly, SameSite=Strict; `__Host-ii_sid` + Secure with `INSPECTOR_COOKIE_SECURE`), only
its sha256 is stored in Redis; idle 30 min, absolute 12 h, at most 3 sessions per user (oldest evicted);
`X-CSRF-Token` on POST/PUT/PATCH/DELETE; lockout after 5 failed passwords (15 min), IP block after 20 failures in
10 min (30 min); password policy (≥ 12 chars, not the login, not common, not one of the last 5); forced change
(`must_change_password`); step-up `POST /auth/reauth` → single-use 5-minute token that verification endpoints
consume with `AuthService.consumeReauthToken(token, principal)` (finalize/unfinalize: `reauth: true` in rbac.yaml).
`INSPECTOR_AUTH_MODE=required` (default in demo/prod) or `optional` (default in local/test: requests without a
session pass as anonymous, a present session is always enforced; refused in demo/prod).

**RBAC**: roles and permissions come from `packages/contracts/rbac.yaml` (one super-role INSPECTOR with every permission at scope ALL, product owner decision 29.09).
Each OpenAPI operation declares `x-permission`; the global `AuthGuard` checks it (401/403), and ASSIGNED scope also
checks the `object_id` path parameter against `object_assignments`. `GET /auth/me` returns the user's permissions
with scopes and `assigned_object_ids` for the UI; `GET /admin/users`, `GET /admin/roles` for the inspector. Inside a
handler: `contextOf(req).principal` / `.scope`, or `currentContext()` in services.

**Audit** (ТЗ §10 табл. 12, 09 §3.4): `audit_log` is append-only (UPDATE/DELETE/TRUNCATE raise; rows leave only
through `audit_purge_expired()`). Every POST/PUT/PATCH/DELETE matched to an operation is recorded by an `onSend`
hook before the response leaves — user, roles, IP, user agent, request id, session ref, route, status, duration,
object id, result SUCCESS/FAILURE/DENIED — with the operation's `x-audit-action` (or what the handler noted with
`noteAudit`); every 403 on a read is recorded as ACCESS_DENIED. Domain rows inside a transaction:
`AuditService.record(event, { executor: tx })` (then the generic row is skipped). Category and retention class come
from `enums.yaml` AuditAction. `GET /audit` with filters; OWN scope sees only its own rows.

**Batch-run import v2** (`POST /admin/batch-runs/import`, same endpoint): after the inventory (runs/objects/files), when
the run has `artifacts.json`, the train objects' artifacts are read strictly (path template, size, sha256, every
record against its schema) and saved in one transaction into `processes` (one per run × object, source
BATCH_IMPORT), `process_files`, `protocols` (versions; a new version only when the canonical content hash changes;
DB trigger keeps versions immutable), `protocol_exports`, `evidence_groups` (= finding groups), `checks` (atomic
findings; inspector columns kept on re-import; changed decided checks get `review_required_reason = VALUE_CHANGED`;
missing ones become SUPERSEDED), `evidence_fragments` (stable ids), `suspicions` (FREE_SEARCH groups, converted to
candidates), `submission_exports` (full/strict + sidecar) and `run_artifacts` (every index entry, e.g. layout and
tables). A finalized protocol is never replaced (423). Hidden-object artifacts are never opened.

**Page viewer** (`evidence.read`): `GET /files/{file_id}/pages/{page_no}` (OpenSeadragon tile source),
`…/image?width|dpi&bbox` (page or normalized crop) and `…/tiles/{level}/{x}/{y}`, rendered by the internal ml-api
(`services/ml/apps/ml_api`, `make ml-api-dev`, 127.0.0.1:8090) and cached on disk under
`.cache/render/v1/<file sha256>/p<page>/` (ETag + `Cache-Control: immutable`, 304). Train objects only.

Tests: `test/platform/*.test.ts` (DB-free, in-memory fakes in `test/platform-fakes.ts`) and
`test/db/platform.db.test.ts` (PostgreSQL + Redis db 15).
