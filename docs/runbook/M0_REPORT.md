# M0 integration report: contracts-lite and data hygiene

Integrator: AG-00, 2026-09-28, M2 Max (12 cores, 32 GB), macOS arm64, no Docker. Nothing is committed; the lead
commits after this phase. Every number below was produced by running the code on this machine during the
integration; the command that produced it is given next to it.

**Verdict: M0 is met on everything 97 §3.2 lists.** The one open recognition gate from report 96 (document codes
EM ≥ 0.95) is scheduled for M1 (AG-02B registry prior). `make setup`, `make test` and `make lint` are green, and
the batch CLI, the scorer, the OCR benchmark and the web import work end to end.

## 1. What works

### 1.1 Baseline

| Command | Result |
|---|---|
| `make setup` | uv sync (78 packages), pnpm install (frozen lockfile), quick model check: «Модели в порядке: 13 файлов (573 МБ)» |
| `make test` | **green, 54.9–55.5 s wall** (two runs): pytest 727 passed, 10 deselected (48.8–49.0 s); contracts «16 схем, 123 перечислений, 170 кодов ошибок»; hidden-test guard «чисто»; API 49 passed; web 10 passed |
| `make lint` | **green**: ruff check and format (145 files), contracts, guard, `tsc --noEmit` for api and web |
| `make test-slow` | **green, 10 passed in 286.5 s** (4 min 47 s): 5 docproc benchmark gates, full sha256 of both train objects, regex timing fuzz and 200 real train pages, full model sha256 |
| `make test-db` | 5 passed against the local PostgreSQL (`inspector_test`), 1.8 s |

Fast tests per package: inspector_common 317, inspector_registry 92, inspector_docproc 119, inspector_eval 163,
inspector_batch 21, tools 13, compare/hypothesis placeholders 1 + 1.

Before integration `make test` was red with 6 failures (stale stub expectations in `test_batch_cli.py`) and
`make bench-ocr` crashed; see §5.

### 1.2 Inventory (AG-01), all three objects

`cd services/ml && uv run --locked inspector-batch --run-id m0-int-inventory-all inventory --all --verify-sha256`
(also `make inventory-all`). Hidden object: inventory only, aggregate counts only (97 §2.17).

| Object | Split | Files | On disk | Recovered | Missing | sha256 verified | PDF pages | Archives (members) | Flags |
|---|---|---|---|---|---|---|---|---|---|
| OBJ-TYUMENSKAYA-5-GOLD-SEED | TRAIN_PUBLIC | 58 | 58 | 0 | 0 | 58 | 5 863 | 0 | 5 |
| OBJ-NOVOSLOBODSKAYA | TRAIN_PUBLIC | 145 | 126 | 19 | 0 | 145 | 4 279 | 0 | 0 |
| Hidden object | TEST_HIDDEN | 213 | 213 | 0 | 0 | 213 | 15 961 | 38 (793) | 47 |

- Тюменская stages: 47 PD, 10 RD_ID_MIXED, 1 UNKNOWN; the 10 mixed files resolve to F0195–F0200 → ID and
  F0201–F0204 → RD (93 §2.6), confirmed through the API as well.
- Timing: cold (empty cache directory) **10.0 s**, 416 files / 8 697 888 218 bytes hashed, max RSS 212 MB;
  warm **0.9 s**, 0 files hashed. `run_context.inventory.json` now lists all three objects for `--all`.
- `run_manifest.json` of both runs validates: `inspector-contracts validate run_manifest runs/m0-int-inventory-all/run_manifest.json` → «ок».

### 1.3 Scorer (AG-10) and the T-GOLD gate

`make score-selftest` (0.5 s): all 16 cases of 93 §2.3 / §4.10 match, e.g.

| Case | Uncapped → total | 93 |
|---|---|---|
| A perfect copy | 100.00 → 100.00 | 100.0 |
| B room 314 dropped (gate) | 93.84 → 59.00 | 59.0 |
| C warm floor under IOS4-077 | 64.00 → 64.00 | 64.0 |
| D 314 on its own RD page 20 | 99.25 → 99.25 | 99.25 |
| E IOS4-078 instead of 079 (gate) | 91.00 → 59.00 | 59.0 |
| F 012 hedged under both codes | 97.14 → 97.14 | 97.1 |
| G generic value texts | 95.00 → 95.00 | 95.0 |
| H8 wrong stage + excluded file, 8-rule set | 95.50 → 95.50 | 95.5 |
| J «12» instead of «012» (gate) | 91.00 → 59.00 | 59.0 |
| K empty prediction | 0.00 → 0.00 | — |

End to end through the batch CLI, on the T-GOLD fixture written as run artifacts
(`runs/m0-int-tgold-perfect/submission/`, `runs/m0-int-tgold-drop314/submission/`):

- `make score PRED=runs/m0-int-tgold-perfect/submission` → **100.00**; three schemas valid; F1 1.000 (TP 10);
  integrity 13 of 13 rules; gate 6 of 6 checkpoints found; no switch changes the total.
- `make score PRED=runs/m0-int-tgold-drop314/submission OBJECT=OBJ-TYUMENSKAYA-5-GOLD-SEED` → **59.00**
  (93.84 uncapped), «ПРОПУЩЕНА: IOS4-078 · 314»; exit code 3 = gate triggered (by design).
- `make score OBJECT=<hidden>` → refused, exit 5 («команда «score» запрещена для скрытой тестовой выборки»).
- `inspector-score validate --pred runs/m0-int-tgold-perfect/submission` → schemas valid, 13 of 13 rules;
  R9 not evaluated until AG-01 emits the superseded list.

### 1.4 Recognition benchmark (AG-02A, R-01)

`make bench-ocr` (suite `ocr`, pipeline `docproc-2.2.0+coreml`, CoreML detector + CPU recogniser), idle machine,
**271.3 s** (4 min 32 s wall). A second full run gave identical accuracy in 274.3 s.

| Measure | Result | Gate (97 §3.6) |
|---|---|---|
| Group A, 17 vector pages / 30 regions / 32 263 chars, CA strict | **0.971** [0.957–0.980]; relaxed 0.976 | ≥ 0.965, CI low ≥ 0.95: met |
| Scans + outlined text, 6 pages / 7 316 chars, CA strict | **0.974** [0.967–0.986]; after corrector 0.976 | ≥ 0.965: met |
| Scan key fields (n = 42), EM strict / relaxed | 0.905 / **0.952** | relaxed ≥ 0.93: met |
| Orientation, 12 pages × 4 turns | **48/48** (min margin 0.261), 0.31 s/case | 100 %: met |
| Document codes (n = 11), EM raw → corrected | 0.091 → **0.909** | ≥ 0.95: not met (M1, AG-02B registry prior) |
| Room/number tokens by OCR (n = 507) | 0.917 | ≥ 0.95: pending (text layer covers most; gate definition to settle) |
| Text-layer gap lines on the gold RD sheets | **2 640 / 2 718 = 0.971** | ≥ 0.90: met |
| Gold rooms on their cited pages | 9/10 (314 is drawn on p20, cited on p18) | M1 room index |
| Outlined RD stamps (n = 19), EM strict / relaxed | 0.947 / 1.000 (miss: D04 stage «Р») | — |
| Page routing | 11/11 | — |
| Speed: vector region / scan page | 1.76 s / 1.9 s (5.95 CPU-s) | — |
| 100-page ИД scan, `recognize F0006 --pages 1-100 --no-cache` (10 workers, CoreML) | **77.0 s** (77.9 pages/min; 57 OCR pages; 0 failures; 100/100 PageTokens valid against the contract; recogniser = 77 % of stage time) | ≤ 180 s: met |

### 1.5 Web product (AG-08): API + UI smoke

`make db-create && make db-migrate`, then `make api-dev` and `make web-dev` (both started from the session, see
§5 for Postgres.app), all calls through the Vite proxy on :5173:

- `GET /api/v1/health` → 200 `{"status":"ok", … "database":{"status":"up","latency_ms":1}}`.
- `POST /api/v1/admin/batch-runs/import {"run_dir":"m0-int-inventory-all"}` → **201 in 0.147 s** (3 objects,
  416 files); repeat → 200 in 0.09–0.13 s.
- `GET /objects` → total 3; per-stage counts PD/RD/ID/RD_ID_MIXED/UNKNOWN: Тюменская 47/0/0/10/1,
  Новослободская 36/10/99/0/0, hidden 89/93/31/0/0 (manifest-level only).
- Тюменская files `?stage=RD_ID_MIXED` → 10 (F0195–F0200 ID, F0201–F0204 RD); Новослободская
  `?local_status=RECOVERED` → 19; bad stage → 400 with a Russian message; unknown object → 404 problem+json;
  `run_dir` outside `runs/` → 400; HEAD `/objects` → 200; `GET /admin/batch-runs` → 2 runs.
- Headless Chrome (argent, CDP): the object card renders the new contract labels in the «Раздел» column
  («КР», «Прочее» instead of raw `KR`, `OTHER`); the РД filter shows 10 files.

## 2. M0 acceptance against 97 §3.2

| 97 §3.2 item | Status | Evidence |
|---|---|---|
| Pinned schema | Met | `submission.organizer.schema.json` byte-identical, sha256 pinned in `vendored.yaml`; `inspector-contracts check` fails on drift |
| JSON Schemas: PageTokens, ExtractedValue, Finding, EvidenceRef, Protocol | Met | `packages/contracts/schemas/*` (Protocol as `protocol_lite`), valid/invalid examples, pydantic mirrors with drift tests |
| The new enums (97 §2.7) | Met | ViolationLabel, ProtocolParamStatus, CriticalityLevel, ParameterMappingStatus, ComparisonResult, LocationType, MatrixScope, ManifestStage, LocalFileStatus, TextSource, ArchiveMemberRole in `enums.yaml` (123 enums in all) |
| Params seeded from the catalog | Met | `packages/contracts/seed/params.json`: 132 params, catalog codes canonical, aliases, 214 atomic rules, 145 guarded regexes; `make seed-check` and `python -m inspector_common.params check` pass |
| Manifest loader + sha256 resolver incl. the 19 recovered files | Met | §1.2: 416/416 verified, Новослободская 19 RECOVERED, 0 missing |
| inspector-score v0 reproducing 93 §2.3 | Met | §1.3: 16/16 cases |
| T-GOLD fixture test | Met | pytest data tests (27) + `make score-selftest` + perfect submission = 100.00 end to end |
| R-01 (recognition benchmark) | Met: benchmark wired, `make bench-ocr` works; 6 of the 8 AG-02A gates green | §1.4. Green: vector CA, scans CA, orientation, key fields, text-gap lines, 100-page speed. Open: codes EM 0.909 and room tokens 0.917 (M1, AG-02B). The other 97 §3.6 gates (sheet = stamp, explication rows, ИД doc type, F0001 p1) belong to AG-02B/02C in M1–M2 |
| CI guards | Met (local) | hidden-test guard in `make test`/`make lint`; batch CLI refuses `score` on the hidden object, `recognize`/`compare`/`export` need `--hidden-run`. No remote CI: the user asked for local only |

Not in M0 by design: the 132-row emission, comparators, exporter, protocol renderer, verification UX (M1/M2).

## 3. Integration changes made (shared files only)

- **Batch CLI tests** (`apps/inspector_batch/tests/test_batch_cli.py`): stub expectations only for `compare` and
  `export`; implemented commands must write `run_context` and never exit 69; hidden-policy tests updated
  (`recognize --hidden-run` on the fake root → 6, `inventory` on hidden → 0); new tests for `--all` and for the
  console entry point. This was the only cause of the red `make test`.
- **`--all` is a common CLI option** (`cli.py`, `guards.py`), as AG-01 asked: `run_context` now lists every object;
  the hidden policy still applies (`score --all` and `recognize --all` are refused). The duplicate option was
  removed from AG-01's hook (one `add_argument` block, AG-01's tests unchanged and green).
- **Shared logger hardening** (`inspector_common/jsonlog.py`): `extra=` keys that collide with LogRecord
  attributes (`msg`, `name`, `args`, …) are emitted as `msg_` etc. instead of raising `KeyError`. This crash
  stopped `make bench-ocr` before its first result. Test added.
- **Console entry point** (`inspector_batch.cli:entrypoint`): after `main()` it flushes logs and streams and exits
  with `os._exit`, so the ONNX Runtime/CoreML teardown race cannot turn a finished run into exit 134 (§5). Falls
  back to a normal exit when child processes are alive. Subprocess test added.
- **Makefile**: `test-py`, `test-js`, `test-registry-slow`, `test-docproc-slow`, `test-params`, `seed`,
  `seed-check`, `inventory-all`, `score-selftest`, `api-dev`, `web-dev`, `db-migrate`, `test-db`; a real `dev`
  (API + web in parallel); pass-through `ARGS=`, `SUITE=`, `PRED=`; `contracts-check` also runs the seed checks.
  Root `package.json` `dev` script likewise. `.env.example`: `INSPECTOR_APP_ENV`, `INSPECTOR_API_HOST`,
  `INSPECTOR_API_PORT`, `INSPECTOR_TEST_DATABASE_URL`.
- **Dependency**: `jsonschema>=4.23` declared by `inspector-registry` (`uv add`; `uv.lock` gains two lines).
- **Contracts** (`make contracts` regenerated `enums.schema.json` and `enums.py`):
  - AG-03's rule-language vocabularies as enums: RuleDirection, RuleOperator, DetectKind, AbstainReason,
    OrdinalScale, ParamExtractionStrategy, ThresholdSource, FeasibilityTier (03 §3.7 definitions), HedgeKind,
    TextOrigin. A new test pins the seed schemas' copies equal to `enums.yaml`.
  - `codes.yaml` `hedge_pairs`: all 10 groups of the seed (was 3); the test pins equality. `make score-selftest`
    is unchanged at 16/16.
  - `ManifestSection` gets Russian labels (АР, КР, …), `FileSource` gets `BATCH_IMPORT`, `GoldStatus` gets
    `TEAM_LABEL_FROZEN` (for frozen N-GOLD rows).
  - RunManifest (schema + pydantic): optional `stage_config_hashes`, `objects[].name`,
    `objects[].artifacts.inventory`, `files[].relative_path/section/size_bytes`.
  - Error codes (proposed): PAGE_COUNT_MISMATCH, NEAR_DUPLICATE, STAGE_UNRESOLVED, DWG_TWIN_NOT_FOUND,
    ARCHIVE_MEMBER_UNSAFE_PATH, HIDDEN_TEST_ARTIFACTS_DROPPED, PREDICTION_NOT_FOUND, GOLD_NOT_FOUND,
    HIDDEN_FINAL_NOT_FROZEN; CONTRACT_VALIDATION_FAILED now has `http: 422`.
  - The contract code parser applies the known organizer typo fix by (Latin prefix, number), like AG-03's resolver:
    «АР-14» and «AR-014» → AR-040 too. Tests added.
- **AG-08 web test**: one assertion updated because `ManifestSection` now has labels (unknown values still raw).
- **Docs**: CLAUDE.md (common CLI options, logging and seed conventions, targets), README, contracts README,
  inspector_batch README.

Not applied, with the reason:

- `LocalFileStatus.ALTERED_ON_DISK`: needs AG-01 (emit) and AG-08 (OpenAPI enum lists) in the same change → M1.
- Adopting `inventory_report.schema.json` into `packages/contracts`: needs examples and a single copy (AG-01 loads its
  own) → M1 with AG-01.
- Health vocabulary as enums (`ok/degraded`, `up/down` are lowercase in the API) and moving OpenAPI to
  `packages/contracts/openapi`: AG-08 code changes → M1.
- `docs/analysis/matrix_enriched.json` regex fields are superseded by the seed; left untouched (analysis archive).

## 4. Hidden-test integrity

- On the hidden object only inventory ran (twice, plus one cold run); only aggregate counts were looked at. The web
  import stored manifest-level inventory, as designed (artifact paths dropped).
- No rule, threshold, dictionary or mapping was changed because of it. `make guard` is clean; the new tests use
  synthetic object ids only.

## 5. Open issues per agent

**AG-00 (integration, environment)**
- `make test` takes 54.9 s of the 60 s budget; docproc fast tests alone take ~38 s. Next step: `pytest-xdist`
  as a dev dependency (check the docproc supervision tests under xdist) or a docproc trim.
- PostgreSQL on :5432 is **Postgres.app** (`~/Library/Application Support/Postgres/var-17`, `trust`), not Homebrew.
  Postgres.app asks the user to allow each new client app; a `make api-dev` launched detached (reparented to
  launchd) hung in the «authentication» state and `/health` returned 503 after 3 002 ms. Started from a terminal
  or the session it works. The user may see pending Postgres.app permission prompts from these attempts;
  approving `make`/`node` in Postgres.app → Settings avoids it.
- Decide per-stage config hashes in the writer (contract field exists now); freeze runbook for M3 (git tag
  `hidden-run-freeze` + `freeze_tag` in the sidecar, AG-10 guard requires both).
- Argent has an update available (0.25.2 → 0.26.0); apply only on the user's request.

**AG-01 (registry)**
- `--no-cache` hashes every file twice: `RegistryCache(None)` is a no-op, so `resolve_many(verify=True)` precomputes
  the digests and `resolve()` recomputes them via `sha256_of` (832 files / 17.4 GB, 14.5 s instead of 416 / 8.7 GB,
  10.0 s). Keep an in-memory map in the no-op cache.
- Emit the new RunManifest fields (`relative_path`, `section`, `size_bytes`, `name`, `artifacts.inventory`) so the
  web import no longer needs the data root; use the new error codes instead of the reused ones
  (PAGE_COUNT_MISMATCH, ARCHIVE_MEMBER_UNSAFE_PATH, …).
- For M1: revision resolver and the R9 `superseded` artifact for the scorer; stage per logical document;
  near-duplicate detector by text Jaccard validated on train pairs; twin confidence only on synthetic/train data.

**AG-02A (recognition)**
- Rename `extra={"msg": …}` in `inspector_docproc/batch.py` (bench `log()`) to `step`; the shared logger now emits
  it as `msg_` instead of crashing.
- Root-cause the exit abort: after a full `bench --suite ocr` the process aborted once in two runs with
  «libc++abi: … recursive_mutex lock failed: Invalid argument» (exit 134) after the report was written; 0 of 4
  single-suite runs. The CLI entry point now skips native teardown, but in-process callers (pytest slow gates,
  a future ml-api) are still exposed. Release ONNX Runtime sessions explicitly (a `close()` on the recognizer /
  engine) and pin `--providers` in the frozen run.
- Codes gate (0.909 < 0.95) with AG-02B's registry prior; stage homoglyph «P» → «Р» (D04); zones (R-10);
  human re-check of the 6 hand-GT pages (96 Q3) before quoting accuracy to the jury.

**AG-03 (matrix)**
- Expert review of the drafts (105 short names, 126 work types, 121 recommendations, 22 ANALOGY routes) and
  ODI-117 (D-04) — needs the user's domain expert.
- The rule vocabularies are now contract enums; the seed schemas may `$ref` them later (the equality test guards
  drift meanwhile). Criticality ruling confirmed: `criticality` = exact catalog string, `criticality_level` =
  enum code, as `enums.yaml` specifies.

**AG-08 (web)**
- Set `files.source = BATCH_IMPORT`, use HIDDEN_TEST_ARTIFACTS_DROPPED instead of HIDDEN_TEST_ACCESS_DENIED for the
  dropped-paths warning, read the new RunManifest fields when present.
- Single 1.34 MB JS chunk (route splitting later); no auth yet (AG-00, M1); OpenAPI location and Orval codegen.

**AG-10 (evaluation)**
- Set `gold_status = TEAM_LABEL_FROZEN` on frozen N-GOLD rows; use PREDICTION_NOT_FOUND / GOLD_NOT_FOUND /
  HIDDEN_FINAL_NOT_FROZEN for the plain CLI messages.
- N-GOLD waits for the user's ~110 labels (95 §5.3); `inspector-eval` (ТЗ §14) and the RT-01…RT-10 regression
  set are M1.

## 6. Recommended M1 task list (Train-E2E-0, 97 §3.2–3.3)

Target: `inspector-batch` on Тюменская produces a schema-valid submission with 10/10 keys, the gold pages under the
anchor rule, the gate OK, ≤ 5 extra keys, RT-01…RT-10 green, runtime logged; demo D1 in parallel.

1. **AG-02A:** run `recognize` on all 57 citable Тюменская PDFs (5 863 pages) and publish PageTokens + runtime;
   fix the teardown abort and the `msg` key; zones R-10; keep the scorecard current (`make bench-ocr`).
2. **AG-02B (start now, critical path):** R-07 title block + QR + sheet↔page map (sheet = stamp ≥ 0.95 on
   F0201/F0202); R-15 room index + tag grammar (rooms 012, 140, 142, 147, 198, 314, 267–272 located, 314 on RD p20);
   registry prior for codes (EM ≥ 0.95); revision-cloud OCG zones.
3. **AG-02C:** PD element–room assertions and absence proof for the ventilation and warm-floor fixtures; EXPLICATION
   typed table (116 rows ≥ 0.98); start ИД binder typing for M2.
4. **AG-04 (start now, critical path):** `inspector_compare`: per-room multiset and presence/absence comparators with
   directional triggers, group → atomic split, anchor-page rule; exporter (full, strict, sidecar) gated by
   `inspector-score validate`; implement `compare`/`export` batch commands; Приложение 2 renderer skeleton for D1.
5. **AG-07:** FREE-HEATING-001 path, evidence-bound only, numbering per finding group.
6. **AG-10:** RT-01…RT-10 on the Тюменская run; `make score` on the first real export; N-GOLD labelling mode for
   the user; `inspector-eval` skeleton.
7. **AG-01:** revision resolver + R9 artifact; new RunManifest fields; `--no-cache` double hashing; stage per logical
   document; ALTERED_ON_DISK decision with AG-00/AG-08.
8. **AG-08 + AG-05:** D1 screens: import of findings/submission artifacts, Приложение 2 protocol view, verification
   of the 10 Тюменская findings, dashboard.
9. **AG-00:** auth/RBAC stub and audit for D1; keep `make test` under 60 s (xdist); adopt the inventory report
   schema and move OpenAPI into `packages/contracts`; stage config hashes in the RunManifest writer.

## 7. Commands to reproduce

```bash
cd /Users/evgen/pl/hackaton
make setup && make test && make lint
make test-slow                       # ≈ 5 min: docproc benchmark gates, sha256 of the train objects, regex fuzz
make inventory-all                   # or: cd services/ml && uv run --locked inspector-batch inventory --all --verify-sha256
make score-selftest
make score PRED=runs/m0-int-tgold-perfect/submission
make bench-ocr                       # ≈ 4.5 min on an idle machine
cd services/ml && uv run --locked inspector-batch recognize --object OBJ-NOVOSLOBODSKAYA --file F0006 --pages 1-100 --no-cache
cd /Users/evgen/pl/hackaton && make db-create && make db-migrate && make test-db
make dev                             # then: curl -X POST http://127.0.0.1:5173/api/v1/admin/batch-runs/import \
                                     #   -H 'content-type: application/json' -d '{"run_dir":"m0-int-inventory-all"}'
```
