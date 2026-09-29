# «Инспектор ИИ» — rules for every agent

Hackathon task №10 (Мосстройнадзор): cross-check ПД/РД/ИД over the 132-parameter matrix. Plan v2, milestone-driven.

## Read first
- `docs/PLAN.md` — plan v2, entry point.
- `docs/analysis/97_plan_delta_real_data.md` — **authoritative**; it overrides older reports.
- `docs/analysis/90_consistency_and_canonical_model.md` — canonical model where 97 is silent.
- Your block report (`docs/analysis/00`…`10`), plus 93 (scoring/submission), 95 (train fixtures), 96 (recognition).

## Non-negotiable rules
1. **Contracts are law.** Enums, schemas, codes and error codes live only in `packages/contracts` (see its README).
   Never invent a value or field in code; ask AG-00 (put it under `open_issues`). After AG-00 edits
   `enums.yaml`/`errors.yaml`: `make contracts`. Python access: `inspector_common.contracts`.
2. **Stay in your directories** (table below). For a shared file, write a note in your return instead of editing it.
3. **Data is read-only**: `data/`, `data_utf8/`, `ТЗ/`. Never modify, move or delete anything there. Write only to
   `.cache/` and `runs/` (git-ignored). Organizer data and models are never committed.
4. **Hidden-test integrity** (OBJ-RECHNIKOV-7-7, split `TEST_HIDDEN`): only inventory, format and speed checks.
   Never inspect its content, extracted values or findings to tune rules, thresholds, dictionaries, mappings or
   templates; nobody reads its outputs before the frozen submission is sent. Never hard-code its identifiers
   (read `split_policy.json`); `make guard` fails on mentions in code/config. `inspector-batch` refuses `score` on it
   and runs `recognize`/`compare`/`export` on it only with `--hidden-run` (the single frozen run, M4).
5. **Archives**: never call `/opt/homebrew/bin/unrar` (Gatekeeper kills it). Use bsdtar / libarchive-c.
6. **Local-only runtime**: no network calls in product code, no cloud LLM/OCR on organizer documents. Models come
   from `.models/`, pinned by `tools/models/manifest.json` (`make verify-models`).
7. **Do not `git commit`** — the lead commits after each phase. No `brew install` or other system changes: list
   them under `open_issues`. Python packages: `uv add` inside `services/ml`; npm packages: pnpm.
8. **Language**: Russian for user-facing strings (UI, protocol, CLI messages, error texts); English for code,
   comments, logs' event names and docs in `docs/analysis`.
9. **Tests are required** (pytest / vitest), fast: < 60 s per package; `make test` runs pytest on 4 xdist workers
   (`PYTEST_WORKERS=0` = serial), so tests must not share writable state (use `tmp_path`, never a fixed file under
   `runs/` or `.cache/`). Mark heavy tests `@pytest.mark.slow` (`make test-slow`, serial) and organizer-data tests
   `@pytest.mark.data` (they skip without data). Every number you report must come from running code.

## Directory ownership
| Agent | Owns |
|---|---|
| AG-01 Ingestion, Registry & Integrity | `services/ml/packages/inspector_registry` |
| AG-02A Recognition Core (lead of AG-02A/B/C) | `services/ml/packages/inspector_docproc` |
| AG-02B Drawings & Layout | `services/ml/packages/inspector_layout` |
| AG-02C Tables, ИД & NLP | `services/ml/packages/inspector_tables` |
| AG-03 Matrix & Domain | `packages/contracts/seed`, `services/ml/packages/inspector_common/src/inspector_common/params.py` |
| AG-04 Comparison, Submission & Protocol | `services/ml/packages/inspector_compare` (comparators, atomic split, anchor pages, exporter, protocol builder and renderer) |
| AG-05 Verification & Learning Loop | `apps/api/src/modules/verification`, `apps/web/src/features/verification` |
| AG-07 Hypotheses & FREE findings | `services/ml/packages/inspector_hypothesis` |
| AG-08 Web & Admin | `apps/api` and `apps/web`, except the modules of AG-05 (above) and AG-00 (`apps/api/src/modules/{auth,audit,import,render}`) |
| AG-10 Evaluation, QA & Dev data | `services/ml/packages/inspector_eval` |
| AG-00 Platform & Contracts | everything else: `packages/contracts` (incl. `openapi/openapi.yaml`, `run_layout.yaml`, `rbac.yaml`), `inspector_common` (except `params.py`), `apps/inspector_batch`, `services/ml/apps/ml_api`, `apps/api/src/modules/{auth,audit,import,render}` + the API core wiring (`app.module.ts`, `bootstrap.ts`, `common/request-context.ts`, `db/schema-all.ts`), `tools/`, Makefile, root configs |

**Batch commands.** `inspector-batch` subcommands dispatch to `<owner package>/batch.py` (`add_<cmd>_arguments`,
`run_<cmd>`); the table in `services/ml/apps/inspector_batch/src/inspector_batch/commands.py` is AG-00's. The CLI
owns the common options `--object`, `--all` (every split_policy object; the hidden policy still applies) and
`--hidden-run`; do not redefine them in a hook. Status at M1 start: `inventory` (AG-01), `recognize`/`bench`
(AG-02A) and `score` (AG-10) are implemented; `layout` (AG-02B), `tables` (AG-02C), `compare`/`export` (AG-04) are
stubs (exit 69) — whoever lands one removes it from `STUB_COMMANDS` in `apps/inspector_batch/tests/test_batch_cli.py`.
`run` (AG-00) chains inventory → recognize → layout → tables → compare → export → score in one run directory for train objects
(`make run-train OBJECT=…`), stops at the first failing or unimplemented step and names its owner; it is refused on
the hidden object. FREE-* findings (AG-07) have no command of their own: they flow through `compare`/`export`.

**Run artifacts (M1).** Every file a run writes has a kind, a path template, a schema and a producer in
`packages/contracts/run_layout.yaml`. Resolve paths with `inspector_common.runlayout.RunLayout(ctx.run_dir).path(kind,
…)` — never hard-code them; consumers read `runs/<run_id>/artifacts.json` (rebuilt by the CLI after every command)
instead of globbing. Contracts per artifact: `page_tokens`, `tokens_index` (AG-02A); `layout_artifacts` (AG-02B);
`table_artifacts`, `extracted_value` (AG-02C); `finding_group`, `finding`, `protocol`, `submission.*`,
`submission_sidecar` (AG-04; AG-07 for FREE-*); `decision` (AG-05, web only, never exported). Pydantic mirrors:
`inspector_common.contracts.models`. M0 status: `docs/runbook/M0_REPORT.md`. The web imports a run directory with
`POST /api/v1/admin/batch-runs/import` (inventory + every artifact listed in `artifacts.json`, into processes,
protocols, checks, evidence_fragments, suspicions, submission_exports; see `apps/api/README.md`).

**API platform rules (M1, AG-00).** Every OpenAPI operation declares `x-permission` (a `packages/contracts/rbac.yaml`
code; `security: []` only for public ones) and every mutation an `x-audit-action` (enums.yaml AuditAction): the
global guard enforces the permission, and every POST/PUT/PATCH/DELETE is written to the append-only `audit_log`.
Write your own domain audit rows inside your transaction with `AuditService.record(event, { executor: tx })`; read
the user with `contextOf(req).principal`. Step-up actions (`reauth: true`) consume `AuthService.consumeReauthToken`.
Page images for the viewer: `GET /api/v1/files/{file_id}/pages/{page_no}[/image|/tiles/{level}/{x}/{y}]`
(ml-api: `make ml-api-dev`). Demo accounts: `make db-seed`.

## Conventions that bit us at M0
- **Logging**: `log.info("event.name", extra={...})`. Never use LogRecord attribute names as `extra` keys (`msg`,
  `name`, `args`, `module`, `filename`, `process`, …): `inspector_common.jsonlog` renames them to `msg_` etc.
  instead of crashing, but the field name then changes. Use `step`, `detail`, `file_name`, … instead.
- **Seed vocabularies**: enums in `packages/contracts/seed/schemas/*` must equal `enums.yaml` (RuleOperator,
  AbstainReason, …), and `codes.yaml` `hedge_pairs` must equal the seed `hedge_groups` (a test pins both).
- **Native libraries (ONNX Runtime/CoreML)**: release sessions before the process exits; a teardown race at
  interpreter exit turns a finished run into exit 134.

## Environment (macOS arm64, no Docker)
- `make setup && make test` — the baseline must stay green. `make help` lists every target (`test-py`, `test-js`,
  `test-slow`, per-package slow targets, `inventory-all`, `bench-ocr SUITE=…`, `score PRED=…`, `score-selftest`,
  `seed-check`, `dev`/`api-dev`/`web-dev`, `db-create`/`db-migrate`/`test-db`).
- Python 3.12 via uv workspace in `services/ml` (`uv` is a pyenv shim here: do **not** add `.python-version`;
  the Makefile sets `UV_PYTHON`). Run tools with `cd services/ml && uv run --locked …`.
- Node 22 + pnpm via corepack (`packageManager` pinned in `package.json`).
- **Linux** (Ubuntu 22.04/24.04, with or without an NVIDIA GPU) is supported: `docs/runbook/LINUX.md`, CI in `.github/workflows/ci.yml`.
  Recognition picks its executor by itself (`--providers auto`: CoreML → CUDA that really works → CPU; `make gpu-check`).
  Models: `make fetch-models` (one-off, network) then `make verify-models-ocr`.
- PostgreSQL 17 on localhost:5432 (database `inspector`), Redis 8 on localhost:6379. RabbitMQ is not installed.
- Organizer data: `data_utf8/ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0/` (package) and
  `data_utf8/ХАКАТОН_УЧАСТНИКАМ_ГОТОВО_К_ПЕРЕДАЧЕ/01_ДОКУМЕНТАЦИЯ/` (manifest `relative_path` base).
- Analysis-phase prototypes: `tools/prototypes/` (reference only, not imported by product code).
