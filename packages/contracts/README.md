# packages/contracts — contracts-lite (owner: AG-00)

Contracts are law: no enum value, schema field or error code exists outside this folder.
To change one, ask AG-00 (return it under `open_issues`); AG-00 edits, runs `make contracts`, commits.

| File | Content |
|---|---|
| `enums.yaml` | Canonical enums (90 §3.2.1 + 97 §2.7) with owners, Russian labels, and cross-enum `mappings` (status mapping 97 §2.6, DiscrepancyType → ComparisonResult, missing-stage precedence). `open: true` marks organizer vocabularies (keep unknown values raw). |
| `codes.yaml` | Parameter code grammar (97 §2.9): canonical catalog codes, aliases, prefix ↔ id ranges, FREE-<TOPIC>-<NNN>, hedge pairs, known alias fixes (AR-14 → AR-040). |
| `errors.yaml` | RFC 9457 error catalogue seeded from report 10 (+ batch-mode codes marked `status: proposed`). |
| `schemas/*.schema.json` | JSON Schema 2020-12 (see the table below). `enums.schema.json` is generated. |
| `run_layout.yaml` | Layout of `runs/<run_id>/`: per ArtifactKind the path template, scope, format, schema and producer. Python: `inspector_common.runlayout` (`RunLayout`, `write_artifacts_index`); the index `artifacts.json` follows `schemas/run_artifacts.schema.json`. |
| `openapi/openapi.yaml` | REST API contract (OAS 3.0.3), moved here from `apps/api/openapi` in M1. AG-08 (and AG-05 for verification) request edits; the API loads it through the `@inspector/contracts/openapi/*` export. Each operation names its owner (`x-owner`), error codes (`x-error-codes`), permission (`x-permission`, from rbac.yaml; `security: []` = public) and, for mutations, its audit action (`x-audit-action`, enums.yaml AuditAction). |
| `rbac.yaml` | Role → permission → scope matrix (90 §3.10): permissions with Russian labels, `grants: {Role: ALL \| ASSIGNED \| OWN}` and `reauth: true` for step-up actions. Enforced by the API guard; the web mirrors it through `GET /auth/me`. `inspector-contracts check` validates roles, scopes and every `x-permission` of the OpenAPI document. |
| `vendored.yaml` | sha256 pins of vendored organizer files (`submission.organizer.schema.json` must stay byte-identical). |
| `examples/<schema>/{valid,invalid}/` | Example documents; every invalid one fails for the reason in its name. |
| `vectors/` | Golden vectors shared by Python and TS: `geometry.json` (02 §3.14), `hashing.json`. |
| `seed/` | Reference seed data (owner: AG-03). Its schema vocabularies (RuleOperator, AbstainReason, HedgeKind, …) must equal `enums.yaml`, and `codes.yaml` `hedge_pairs` must equal the seed `hedge_groups`; `tests/test_contracts_seed_vocabularies.py` pins both. |

Python access: `inspector_common.contracts` (loader, validators, generated `enums.py`, pydantic `models.py`,
`codes.py`, `status.py`). CLI: `inspector-contracts check | gen | validate <schema> <files…> | list`.

Schema ids live under `https://contracts.inspector-ai.local/schemas/`; they are identifiers only and are resolved
from local files (no network).

## Schemas and who writes them

| Schema | Written to (run_layout.yaml) | Writer | Notes |
|---|---|---|---|
| `run_manifest` | `run_manifest.json` | AG-01 (`inventory`), AG-00 | `objects[].artifacts` points at per-object files |
| `run_artifacts` | `artifacts.json` | AG-00 (CLI, after every command) | index of every file; page tokens summarised per file |
| `page_tokens` / `tokens_index` | `tokens/<file_id>/p<NNNNN>.json.gz`, `tokens/index.json` | AG-02A (`recognize`) | |
| `layout_artifacts` | `layout/<file_id>.json` | AG-02B (`layout`) | TitleBlock (+ Изм. rows), SheetPageMap, RoomIndex, TagInstance, CadLayer, RevisionCloud, QrLink |
| `table_artifacts` | `tables/<file_id>.json` | AG-02C (`tables`) | typed tables; cell keys per TableType pinned from `enums.yaml` `columns` |
| `extracted_value` | `values/<object_id>.jsonl` | AG-02C | |
| `finding_group` | `findings/<object_id>.groups.jsonl` | AG-04 (`compare`), AG-07 (FREE-*) | one anchor page per stage; `finding_ids` = atomic children |
| `finding` | `findings/<object_id>.jsonl` | AG-04, AG-07 | atomic (one parameter × one location) |
| `protocol` | `protocol/<object_id>.json` (+ .docx/.pdf) | AG-04 (`export`) | Приложение 2 sections 1–7 verbatim + Приложения А/Б/В; replaces `protocol_lite` |
| `submission.extended` / `submission.strict` | `submission/<object_id>.json`, `submission-strict/<object_id>.json` | AG-04 | both also satisfy `submission.organizer` |
| `submission_sidecar` | `submission/<object_id>.sidecar.json` | AG-04 | a RunManifest scoped to one object; carries `freeze_tag` for the hidden run |
| `decision` | web DB only (never in a run) | AG-05 | inspector verdicts with reason / basis / clarify codes (05 §3.6) |

New vocabularies of M1 (`enums.yaml`): ArtifactKind, ArtifactFormat, ArtifactScope (AG-00); TagKind, TagRoomLink,
SheetMapBasis, RoomSource, RevisionCloudSource (AG-02B, proposed); TableType (with `columns`), TableRowKind,
TableCheckKind (AG-02C, proposed); ProtocolSummaryRow, DeviationDirection (AG-04); DecisionRejectReason (with
`requires`), DecisionConfirmBasis, DecisionClarifyBasis, RevisionBasis, SuspicionDismissReason, UnfinalizeReason,
CommentSource, GoldEffect (AG-05, from 05 §3.6). `status: proposed` values are ratified by their owner; ask AG-00
for changes.
