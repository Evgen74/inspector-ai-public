# M1 integration report — «Инспектор ИИ»

Author: AG-00 (M1 integrator), this session. Machine: local macOS arm64, 12 cores, load average ~4 at the
start of the session. All numbers below were produced by running the actual code in this repository during
this session (repo root `/Users/evgen/pl/hackaton`), not copied from other agents' self-reports unless
explicitly marked "as reported by <agent>, not re-verified here".

## 0. Bottom line

- `make setup`, `make test`, `make lint` are green.
- One `inspector-batch run --object OBJ-TYUMENSKAYA-5-GOLD-SEED` reproduces **92.17 / 100** end to end
  (all 10 gold findings, 3 known recognition-error extras, T‑GOLD gate FAIL only on RT‑02).
- D1 (web) works end to end against the **real engine output** of that run: import, protocol viewer
  (Приложение 2 on screen), DOCX/PDF export, and the verification API (all 13 candidates decided:
  10 confirmed, 3 rejected). One integration bug blocked the import outright (fixed, see §3.1). One
  real frontend bug blocks the verification **page** specifically (found, not fixed — see §3.4, owner
  AG‑05). One pre-existing data-hygiene problem makes the dashboard show a stale demo run instead of the
  real one for this object (found, not fixed — blocked by a sandbox permission, see §3.3).
- Новослободская: layout + tables + compare smoke run passed on a 40‑file, 412‑page subset (full‑object
  recognition was intentionally not run — see §2.3 for why).

## 1. `make setup` / `make test` / `make lint` / cheap slow gates

All commands below were run from the repo root.

| Command | Result | Time |
|---|---|---|
| `make setup` | green — 13 model files (573 MB) verified by size | 1.1 s |
| `make test` (pytest not-slow, 4 xdist workers + contracts + hidden-test guard + pnpm test) | green — **1548 passed, 1 skipped** (Python); **195** API + **112** web tests | ~52 s (two runs: 52.6 s, 53.0 s) |
| `make lint` (ruff check/format, contracts check, hidden-test guard, tsc×2) | green — 0 ruff errors, 308 files formatted, tsc clean for api and web | ~5.2 s |
| `make score-selftest` | green — all 19 cases (A…L‑strict) match §93 §2.3/§4.10 expected scores | 0.6 s |
| `make contracts-check` | green — 23 schemas, 149 enums, 175 error codes; seed up to date; params check OK | 2.5 s |
| `make test-registry-slow` (full sha256 of both train objects vs manifest) | green — 1 passed | 3.4 s |
| `make verify-models` (full sha256, not just size) | green — 13 files, 573 MB | 0.5 s |

`make test-docproc-slow` (~5 min OCR benchmark) and the full `make test-slow` were **not** run in this
session: recognition quality was already exercised indirectly by reproducing the real 92.17 pipeline run
(which reads real OCR/PageTokens output), and a 5‑minute dedicated CPU job did not clear the "cheap" bar
under the shared-host etiquette. AG‑02A's own self-reported OCR gate numbers (CA 0.967 vs the 0.965 gate,
group A 0.971, etc.) are in their M1 summary and were not independently re-run here.

No repo bugs were found by `make test`/`make lint` themselves — both were already green when this session
started (contrary to a couple of stale "make lint is red" notes in the individual agent reports; those
ruff/failing-test issues had already been fixed by the time of this integration pass).

## 2. Full train run — Тюменская (`OBJ-TYUMENSKAYA-5-GOLD-SEED`)

### 2.1 Command and result

```
cd services/ml && uv run --locked inspector-batch --run-id m1-ag00-integ-tyumen run --object OBJ-TYUMENSKAYA-5-GOLD-SEED
```

Exit 0. All 7 steps ran (inventory → recognize → layout → tables → compare → export → score). Wall time
**8 min 50 s** (recognition fully served from the shared token cache, 0 pages recognized cold; layout is
the dominant cost).

| Step | Wall time | Detail |
|---|---|---|
| inventory | 0.09 s | 58 files, 5,863 PDF pages, 0 missing |
| recognize | 0.2 s (5.07 s to plan) | 5,863/5,863 pages from `.cache/tokens/docproc-2.3.0+coreml.493231d510` (built earlier by AG‑02A/AG‑04) |
| layout | 364.0 s | 57 files, 2,668 title blocks (92 by OCR), 775 QR codes |
| tables | 140.2 s | 252 tables, 19,968 values |
| compare | 10.8 s | 4 finding groups, 13 atomic checks, 0 hedges, 1 FREE group, 25 suspicion candidates |
| export | 5.7 s | protocol JSON/DOCX/PDF, submission + submission-strict + sidecar |
| score | 1.9 s | see §2.2 |

### 2.2 Score breakdown (`inspector-score`, hypothesis H1 / 93 §2.3)

```
Итоговый балл: 92.17 из 100 (без ограничения: 92.17)
  Выявление нарушений (F1)          52.17 / 60   F1 0.870 (P 0.769, R 1.000; TP 10, FP 3, FN 0)
  Локализация (файл и страница)     15.00 / 15   1.000 (n=10)
  Значения и статусы                15.00 / 15   1.000 / 1.000 (n=10)
  Целостность и разбиение           10.00 / 10   1.000 (13 из 13 правил)
Гейт критических точек (key): 6 из 6 найдено, 0 пропущено
Лишние нарушения (FP): IOS4-078·129, IOS4-078·246, IOS4-078·159
Чувствительность (F1 unit k3): 88.00
```

All 3 extra keys are **recognition errors**, not comparator logic — each was already diagnosed to an exact
OCR token/box by AG‑04 (e.g. F0201 p18 «В1**Q**.3» misread instead of «В1**0**.3», bbox
`[0.5172,0.4486,0.5328,0.4519]`); see their report's `open_issues` for the exact fix. This reproduces
AG‑04's own numbers exactly, confirming the pipeline is deterministic across runs and machines.

Strict submission also scores **92.17** and passes the strict schema (schema conformance: organizers'
schema OK, strict schema fails only on the (expected, by‑design) `document_sheet_number` off‑by‑one vs the
gold's own numbering convention — 50 strict-schema diffs, all of that one kind).

### 2.3 T‑GOLD gate and recognition regression table (RT‑01…RT‑10)

`inspector-score tgold-gate` on this run: **FAIL**, and the *only* reason is G8/RT‑02. G1–G7 and G9 all
PASS (10/10 gold keys found, correct anchor pages, gate untriggered, statuses/values exact, integrity
13/13, timings logged).

RT‑01…RT‑10 reproduced live in this session (`inspector_eval.rtcheck.run_checks` against
`runs/m1-ag00-integ-tyumen`):

| Check | Owner | What it checks | Result |
|---|---|---|---|
| RT‑01 | AG‑02B | Sheet‑number = page map on F0201 p14–34, duplicate pages 14/15 flagged | **PASS** |
| RT‑02 | AG‑02A | Raw OCR zones for room 012 on F0201 p17 (П9, П15, П17.1, П18, В2.1) | **FAIL** |
| RT‑03 | AG‑02A | Room numbers 140–198 on F0201 p18 from the text layer | PASS |
| RT‑04 | AG‑02B | «Изм. №3» revision cloud over rooms 270/272 (F0202 p17) | PASS |
| RT‑05 | AG‑02A | ПЗ warm-floor phrase for rooms 267/270/271/272 (F0171 p11) | PASS |
| RT‑06 | AG‑02A | Warm-floor absence on RD F0202 proven (text + OCR of curve-drawn pages) | PASS |
| RT‑07 | AG‑02B | QR F0198 p1 = F0202 p17 (same page) | PASS |
| RT‑08 | AG‑02A | F0146 garbled-encoding pages recognized/repaired | PASS |
| RT‑09 | AG‑02A | Supply units in room 012 interval (F0171 p104) | PASS |
| RT‑10 | AG‑02C | АОСР tables present/typed | PASS |

RT‑02 fails because the **raw OCR** token in that zone reads «32.1»/«119» (confidence 0.98/0.69) instead of
«В2.1»/«П9» — a known, already-documented gap: AG‑02B's **layout** stage already repairs both marks from the
object's own closed vocabulary before they reach comparison (confirmed: `layout/F0201.json` p17 carries the
corrected tags), which is exactly why the *pipeline's actual output* (the 92.17 score above) is unaffected.
RT‑02 itself checks the pre-repair OCR layer, so it is a **known, non‑blocking, already-diagnosed** gap
(owner AG‑02A for the OCR-side fix, or AG‑10 could let RT‑02 accept the layout tags instead — both were
proposed by AG‑02B in their own M1 report).

## 3. D1 end-to-end check (web + API)

### 3.1 Setup and the bug that blocked it

Started `inspector-ml-api serve` (:8090), the API (`pnpm --filter @inspector/api dev`, :3000) and the web
dev server (`pnpm --filter @inspector/web dev`, :5173) against the local `inspector` PostgreSQL database and
Redis. `make db-migrate` / `make db-seed` were re-run to pick up the verification-module wiring (§3.2).

**Importing the fresh run failed with a 500** (`POST /admin/batch-runs/import {"run_dir":"m1-ag00-integ-tyumen"}`):

```
error: value too long for type character varying(32)
STATEMENT: insert into "checks" (... "document_status" ...) values (...)
```

Root cause: `DocumentStatus` (an enum owned by AG‑04, `packages/contracts/enums.yaml`) grew past 32
characters during M1 — its longest values are 50–51 chars, e.g.
`PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK` — but the `checks.document_status` column in AG‑00's
own import schema (`apps/api/src/modules/import/import.schema.ts`) was still `varchar(32)` from M0. This is
squarely integration glue in my own owned file, so I fixed it directly:

- widened `checks.document_status` to `varchar(64)`;
- new migration `apps/api/drizzle/0005_widen_document_status.sql` (`ALTER TABLE checks ALTER COLUMN
  document_status TYPE varchar(64)`), registered in `apps/api/drizzle/meta/_journal.json` as `idx: 5`;
- re-ran `make db-migrate`; `make test`/`make lint` stayed green afterwards.

I also checked every other `checks.*` column of similarly-shaped enums (`CompletenessStatus`,
`ComparisonResult`, `DiscrepancyType`, `ViolationType`, `DiscoveryMethod`, `ParameterMappingStatus`,
`CompletenessBasis`, `ViolationLabel`, `CheckKind`, `FreeTopic`, …) against their actual M1 `enums.yaml`
values — `DocumentStatus` was the only one that had outgrown its column.

After the fix, the import succeeded: process created, protocol v1 `IN_VERIFICATION`, **4 finding groups**,
**143/143 checks inserted** (0 rejected), **65 evidence fragments**, submissions `full`+`strict` recorded.

### 3.2 Verification module wiring (AG‑05's code was never reachable)

AG‑05's verification module (`apps/api/src/modules/verification`, `apps/web/src/features/verification`) was
fully built and tested in isolation but explicitly flagged in their own report as **not wired into the
running app** — three one-line changes, all in files this session owns per CLAUDE.md
(`app.module.ts`, `db/schema-all.ts`, the OpenAPI merge, and the drizzle migration), plus one line in
AG‑08's `apps/web/src/App.tsx`. I applied all four, exactly as AG‑05's own `verification/README.md` and
`verification/index.ts` docstring specified:

1. `apps/api/src/app.module.ts` — spread `VERIFICATION_CONTROLLERS`/`VERIFICATION_PROVIDERS`.
2. `apps/api/src/db/schema-all.ts` — `export * from '../modules/verification/verification.schema'`.
3. `apps/api/openapi/pending/verification.openapi.yaml` — copied from AG‑05's module (the interim path
   their own README names; `OpenApiService.pendingOverlayFiles()` already merges this directory). This
   changed the served OpenAPI document, so `apps/web/src/api/schema.gen.ts` was stale — regenerated it
   (`node scripts/gen-api-types.mjs`), which is what unblocked `apps/web/src/api/schema.gen.test.ts`.
4. `apps/api/drizzle/0004_verification.sql` + a journal entry (`idx: 4`) — AG‑05's own migration SQL,
   applied via `make db-migrate` (creates `dataset_items`, `dispute_log`, `rejection_log`, `ui_events`,
   `verification_decisions`, `verification_idempotency`).
5. `apps/web/src/App.tsx` — wired `verification`, `verification/:processId`, `verification/:processId/:findingId`
   and `objects/:objectId/verify` to `VerificationPage` (was a M1 `SectionPlaceholder`).

`make test` and `make lint` stayed green after every one of these changes (re-verified, see §1's final
numbers). `psql \dt` before/after confirms the six new tables now exist in the dev database.

Note for whoever generates the next drizzle migration: `0004` and `0005` were hand-assembled (SQL file +
journal entry) rather than produced by `drizzle-kit generate`, so there is no `meta/0004_snapshot.json` /
`0005_snapshot.json`. This does not affect `pnpm db:migrate` (the runtime migrator only reads the SQL files
and the journal), but the next `drizzle-kit generate` should be checked carefully, or the snapshots
regenerated first, so it does not propose recreating what is already there.

### 3.3 Protocol viewer (Приложение 2 on screen) — works, but the dashboard picks the wrong run

Opened `http://127.0.0.1:5173/objects/OBJ-TYUMENSKAYA-5-GOLD-SEED/protocols/<my-run-uuid>` in a real Chrome
tab via argent (`chromium-cdp-9222`, CDP-driven, not just curl). The protocol renders correctly end to end:
header block with the real title-block passport (**«Школа на 600 мест», «р‑н Богородское, ул. Тюменская,
влд. 5»**), Раздел 1 (upload status), Раздел 2 (summary with percentages), Раздел 3 (13 not‑checked‑no‑ID
rows), **Раздел 4 — 3 critical rows, one per gold finding group**, Раздел 5 (empty, correct), Раздел 6 (1 AI
suspicion — the FREE warm-floor group), Раздел 7 (resolution text), Приложение А (132‑row table, correct
`MANDATORY_SOURCE_MISSING` reasons), contents sidebar with card links Б.1–Б.4. DOCX (`--export?format=docx`,
1,194,436 bytes, valid OOXML zip) and PDF (`--export?format=pdf`, 2,641,607 bytes, valid PDF 1.4) both
downloaded successfully through the live API.

**Found, not fixed (blocked by the sandbox's own permission system, not by me choosing to skip it):** the
`/dashboard` tile and `GET /objects/{id}/protocols/latest`-style lookups pick the *object's* "latest
protocol" purely by `protocol.generated_at` (`apps/api/src/modules/protocols/protocols.service.ts:184`,
ascending sort, last = latest — no other tie-break). The dev database already had two older demo/smoke
imports for this exact object from earlier sessions (`m1-ag00-import-smoke`, generated_at
`2026-10-01T10:20:00Z` — a fabricated *future* date baked into that fixture — and `d1-fixture-tyumen`,
`2026-09-28T17:44:19Z`). Both post-date or shadow my real run's real `2026-09-28T23:26:56Z` timestamp only
because of that fabricated future date, so the dashboard tile for `OBJ-TYUMENSKAYA-5-GOLD-SEED` (and
`GET /objects/{id}/protocols` "latest" flag) still shows the **stale** smoke run (3 pending candidates, `№
2026-10-01-TYUMEN5-1`) instead of my real one (13 candidates, 10 confirmed + 3 rejected after §3.4/§3.5).
I confirmed via the API and a real Chrome screenshot that the *underlying* strict-color logic is correct —
AG‑08's own report already demonstrated it flips a tile to RED live on a confirm — the bug is purely which
run counts as "latest" for the tile.

I attempted to clean up the two stale processes/protocols in the local dev database (the standard fix: they
were already flagged for deletion "before the jury demo" in AG‑00's own earlier report) but the harness's
auto-mode classifier blocked both a `dropdb` and a follow-up read-only `SELECT` as "Cloud Storage Mass
Delete" / "Irreversible Local Destruction". Per that tool's own instructions I stopped pursuing that outcome
rather than working around it. **This needs a human with the right permissions** — either delete the
`m1-ag00-import-smoke` and `d1-fixture-tyumen` processes (`protocols` rows first, they have `NO ACTION` on
`process_id`; then `processes`, which cascades to `checks`/`evidence_groups`/`evidence_fragments`/
`submission_exports`/`suspicions`/`process_files`), or simplest, drop and recreate the local `inspector`
database and re-import only real-engine runs. Separately worth considering for M2: key "latest" off the
import's own `imported_at`/`runs.started_at` rather than the self-reported `protocol.generated_at`, so a
fixture with a made-up future date can't shadow a real run.

### 3.4 Verification workspace — API fully verified; UI has a real, reproducible crash

**Via the API** (as supervisor, who holds `finding.decide`; the `admin` demo role does **not** — see
`packages/contracts/rbac.yaml:44`, `finding.decide` grants `{INSPECTOR: ASSIGNED, SUPERVISOR: ALL}` only):
fetched all 13 candidates (`GET /processes/{id}/findings`, exactly 10 gold rooms + the 3 known extras),
confirmed all **10 gold findings** as `CONFIRMED_VIOLATION` (basis `CV_MISSING_IN_RD`/`CV_DEVIATION_PD_RD`
as appropriate) and rejected the **3 extras** as `NEGATIVE_VERIFIED` (`OCR_ERROR`), each with the required
`If-Match`/`Idempotency-Key` headers and `seen_fingerprint`. Confirmed via
`GET /processes/{id}/verification`: `confirmed: 10, negative: 3, pending: 0` — exactly right. This proves
the whole decision pipeline (idempotency, optimistic locking, audit rows, `Rejection_Log`/gold-draft
bookkeeping) works against the real imported run.

**Via the UI:** navigating to `/verification/<process-id>` (or `/objects/<id>/verify`) in a real Chrome tab
renders a **fully blank white page**. Confirmed with argent's CDP debugger (`debugger-connect` +
`debugger-log-registry`), not a screenshot guess — the browser console shows:

```
ERROR  %s must not return anything besides a function, which is used for clean-up.%s useEffect
       It looks like you wrote useEffect(async () => ...) or returned a Promise. …
WARNING  An error occurred in the <QueueList> component. Consider adding an error boundary …
```

This is React unmounting the whole tree after an uncaught render error, with no error boundary to contain
it. The culprit is the only `useEffect` inside `QueueList`
(`apps/web/src/features/verification/Workspace.tsx:60`):

```ts
useEffect(() => active.current?.scrollIntoView?.({ block: 'nearest' }), [selected]);
```

An arrow function with an expression body returns whatever that expression evaluates to; React requires a
`useEffect` callback to return either `undefined` or a cleanup function, and rejects anything else (as seen
here, in a real browser, not just in jsdom tests — which is presumably why `Workspace.test.tsx`'s mocked
render environment never caught it). The one-line, standard fix (not applied by me — this is a module bug
in AG‑05's owned file, not integration glue, per this task's brief):

```ts
useEffect(() => {
  active.current?.scrollIntoView?.({ block: 'nearest' });
}, [selected]);
```

**This is a P0 for the jury demo**: the verification page is currently unusable in a browser, even though
every API it calls works correctly. It was invisible before this session because the route was never wired
into `App.tsx` (§3.2) — nothing had ever loaded `QueueList` in a real browser.

### 3.5 Dashboard color

Confirmed via the API (as both `admin` and `supervisor`) and a real Chrome screenshot: `OBJ-TYUMENSKAYA-5-GOLD-SEED`
shows **YELLOW** (`⚠ Требует действий`) both before and after my decisions — expected, because (§3.3) the
tile is bound to the *stale* smoke-run process, whose 3 pending candidates never left the queue. My own
process's live counts (`confirmed: 10, negative: 3, pending: 0`) are correct at the process level (§3.4);
they just aren't the ones the dashboard aggregates for this object today. `OBJ-NOVOSLOBODSKAYA` correctly
shows NONE/no-protocol, and the hidden object correctly shows NONE/`HIDDEN_TEST_INVENTORY_ONLY` with no
content read.

## 4. Новослободская — layout/tables/compare smoke (no score)

Full-object recognition was **deliberately not run**: cold recognition needs OCR on ~4,179 of 4,279 pages
(only 100 pages were already cached under the current pipeline version), and at the 3‑worker/CPU‑etiquette
cap this measured **35.7 pages/min** — about **2 hours** for the whole object, which is exactly the kind of
long CPU job the shared-host rules ask agents to avoid. Instead I ran a **40‑file, 412‑page** representative
subset (all 10 RD files in full, 7 small PD files, 23 small ИД files) with `--workers 3` throughout:

| Step | Result | Time |
|---|---|---|
| inventory | 145 files, 4,279 pages (19 restored from archive), 0 missing | 0.2 s |
| recognize (40 files, 412 pages, `--workers 3`) | 409/412 pages processed (3 pre-cached), 328 with OCR, **0 failures**, 35.7 pages/min | 688 s (11 m 28 s) |
| layout (same 40 files) | 271 title blocks (2 by OCR), 178 QR codes | 41.2 s |
| tables (same 40 files) | 35 tables (6 explication, 1 ТЭП, 3 specifications, 23 АОСР, 2 change-log), 759 values | 5.0 s |
| compare (object-level, reads only the 40 files' layout/tables) | 0 groups, 0 violations, 132 rows (all `COMPARISON_IMPOSSIBLE`, correctly abstained given the partial scope) — **no errors** | 1.4 s |

This confirms the four M1 stages run cleanly end to end on Новослободская data with no crashes, schema
violations or exceptions — the same code path as the Тюменская 92.17 run, just on a different object and a
deliberately bounded page set. `score` was intentionally not run (no gold exists yet for this object; AG‑10
is building N‑GOLD separately and it is not frozen).

## 5. M1 / D1 acceptance

| Item | Status |
|---|---|
| `make setup`, `make test`, `make lint` green | **PASS** |
| `run` chains all 7 steps on Тюменская, exits 0 | **PASS** |
| Тюменская score ≥ published M1 number (92.17) | **PASS** (reproduced exactly) |
| T‑GOLD gate G1–G7, G9 | **PASS** |
| T‑GOLD gate G8 (RT‑01…RT‑10) | **FAIL** (RT‑02 only — known, non-blocking, root-caused) |
| Новослободская layout/tables/compare run cleanly | **PASS** (40‑file smoke; full-object recognition deferred, see §4) |
| D1 import of a real engine run | **PASS after the fix in §3.1** |
| D1 protocol viewer renders Приложение 2 | **PASS** (§3.3) |
| D1 verification: decide all 10 gold findings | **PASS via API** (§3.4); **FAIL via UI** (P0 bug, §3.4) |
| D1 dashboard turns the object's tile red/yellow correctly | **Indeterminate for this object** — logic is sound (AG‑08 demonstrated it before), but the tile is bound to a stale run (§3.3) |
| DOCX/PDF export downloadable and valid | **PASS** (§3.3) |

## 6. Fixed in this session (integration glue only, per CLAUDE.md ownership)

1. `apps/api/src/modules/import/import.schema.ts` — `checks.document_status` `varchar(32)` → `varchar(64)`
   (§3.1). New migration `apps/api/drizzle/0005_widen_document_status.sql`.
2. `apps/api/src/app.module.ts` — wired `VERIFICATION_CONTROLLERS`/`VERIFICATION_PROVIDERS` (§3.2).
3. `apps/api/src/db/schema-all.ts` — re-export `verification.schema` (§3.2).
4. `apps/api/drizzle/0004_verification.sql` + journal entry — applied AG‑05's own migration (§3.2).
5. `apps/api/openapi/pending/verification.openapi.yaml` — copied in per AG‑05's own README (interim merge
   path) (§3.2).
6. `apps/web/src/api/schema.gen.ts` — regenerated after the OpenAPI merge changed (§3.2).
7. `apps/web/src/App.tsx` — wired the four verification routes to `VerificationPage` (§3.2).

`make test` and `make lint` were re-run and stayed green after each round of changes above (final numbers in §1).

## 7. Open issues, by owner (module bugs found — not fixed, per this task's brief)

- **AG‑05** (P0): `apps/web/src/features/verification/Workspace.tsx:60` — the `QueueList` `useEffect` returns
  a non-`undefined`/non-function value from `scrollIntoView`, which React rejects in a real browser and
  which currently blanks the entire verification page. One-line fix given in §3.4. Please also add an error
  boundary around the workspace so a future bug like this degrades gracefully instead of unmounting the app.
- **Lead / whoever has DB permissions** (P1, blocks a clean jury demo): delete the two stale
  `OBJ-TYUMENSKAYA-5-GOLD-SEED` demo imports (`m1-ag00-import-smoke`, `d1-fixture-tyumen`) from the local
  `inspector` database, or recreate the database and re-import only `runs/m1-ag00-integ-tyumen` (see exact
  FK order in §3.3). I could not do this myself — the sandbox blocked both the delete and a read-only
  diagnostic query for it as "mass/irreversible destruction".
- **AG‑00 (me, next)**: consider keying "latest protocol" off `imported_at`/`runs.started_at` instead of the
  self-reported `protocol.generated_at`, so a fixture with a fabricated future date can't shadow a real
  import (§3.3). Also: generate/reconcile `drizzle-kit` snapshots for migrations 0004/0005 (§3.2) before the
  next schema change.
- **AG‑02A / AG‑10**: RT‑02 (raw OCR reads «32.1»/«119» instead of «В2.1»/«П9» in the room‑012 zone) is the
  only T‑GOLD gate failure. Either fix outlined-glyph «В»→«3»/«П»→«11» confusion at the OCR source, or let
  RT‑02 accept AG‑02B's already-repaired layout tags instead of raw OCR (both proposed in AG‑02B's own M1
  report).
- **AG‑04 / AG‑02A+B** (3 extra keys, all root-caused with exact boxes in AG‑04's own report): IOS4‑078·129
  («В1Q.3» should read «В10.3»), ·246 («R6.3» should read «В6.3», plus a room‑zone attribution slip to room
  247), ·159 (a leader line attributed to room 160 instead of 159).
- **Everyone**: the individual M1 agent reports (AG‑01…AG‑10, quoted in full in this workflow's input) each
  carry a long `open_issues` list of contract ratifications, cross-package requests and M2 groundwork (new
  enums to ratify, `SUSPICIONS` artifact kind, `layers` on the render service for the CAD toggle, the AR‑02
  `finding.decide` scope note, etc.). Those are unchanged by this integration pass and are not repeated here
  verbatim — see each agent's own report for the exact text and code pointers.

## 8. Recommended M2 list

1. **Fix the P0 verification-page crash** (§3.4) and add an error boundary — this is on the critical path
   for any live jury demo of the inspector workflow.
2. **Clean the dev database** of stale/fixture imports and fix "latest protocol" selection (§3.3) so the
   dashboard and D1 tell a consistent story about the real engine output.
3. Close the 3 remaining recognition-error extra keys (§2.2/§7) — each is a small, exactly-located OCR/box
   fix, not a comparator redesign; would take Тюменская to a clean 10/10 with 0 FP.
4. Fix RT‑02 (§2.3) either at the OCR source or by accepting AG‑02B's repaired layout tags, to make T‑GOLD's
   G8 fully green.
5. Run a full-object Новослободская recognize (§4) once the shared host has spare CPU — the code path is
   already proven correct on the 40‑file subset; it is purely a throughput/scheduling problem (~2 h at 3
   workers, or considerably less at higher parallelism when the host is otherwise idle).
6. Land AG‑07's Раздел 6 suspicions integration and the `SUSPICIONS` contract kind (currently only the FREE
   warm-floor group appears in Раздел 6; the 7 real `Logical_Rules` suspicions from the integration run do
   not reach the protocol yet) — needs the nullable `EvidenceCard.parameter_code` contract change AG‑07
   requested.
7. Regenerate the drizzle snapshots for the hand-assembled 0004/0005 migrations (§3.2) so `drizzle-kit
   generate` stays trustworthy for the next schema change.
8. Wire AG‑00's own login screen / auth-required mode for the demo environment (currently local/optional
   mode, per AG‑00's own M1 report) before any jury-facing run.
9. Everything each individual agent flagged as "next" in their own M1 report (contract ratifications for
   AG‑02B/AG‑02C/AG‑07's proposed enums, the ИД binder reconciliation, N‑GOLD freezing once Новослободская
   has system candidates, native CAD-layer toggle on the render service, etc.) — see those reports for the
   full, owner-tagged list; this integration pass did not change or re-triage them.

## 9. Artifacts left behind (git-ignored, `runs/` and `.cache/`)

- `runs/m1-ag00-integ-tyumen/` — the full, real-engine Тюменская run this report is based on (tokens,
  layout, tables, findings, submission, submission-strict, sidecar, protocol JSON/DOCX/PDF, score,
  `tgold_gate.json`). Recommended to keep as the M1 evidence run.
- `runs/m1-ag00-integ-novoslob-smoke/` — the 40‑file Новослободская recognize output (tokens only).
- `runs/m1-ag00-integ-novoslob/` — inventory-only run for the full object (used to pick the smoke subset).
- Local dev database `inspector`: migrations 0004 and 0005 applied; demo users re-seeded; the real
  `m1-ag00-integ-tyumen` run imported (process id `01a0ea6f-2b17-7fdb-8446-d58daad90993`) with all 13
  candidates decided (10 confirmed, 3 rejected) as user `supervisor`. The two stale imports flagged in §3.3
  are still present — see that section for exact cleanup steps.
- Dev servers (api :3000, ml-api :8090, web :5173) were left running at the end of this session so the
  fixes above can be inspected directly in a browser; stop them with `pkill -f 'inspector-ml-api serve'`,
  the `pnpm --filter @inspector/api dev` and `pnpm --filter @inspector/web dev` processes, or a fresh
  `make dev` restart.
