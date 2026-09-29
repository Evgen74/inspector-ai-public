# inspector_eval

Owner: **AG-10** (see CLAUDE.md).

- `inspector-score`: a local replica of the organizers' scoring (60/15/15/10 plus the critical-miss gate,
  report 93 §2–§4), the T-GOLD fixture and self-test, the dev-set registry (T-GOLD, N-GOLD) and the
  leave-object-out calibration.
- **M1:** the T-GOLD must-pass gate (`tgold-gate`, `tgold_gate.py`) with the recognition regression checks
  RT-01…RT-10 (`rtcheck.py`); the integrity checker R1–R15 + packaging rules P1–P6 for any submission and any
  manifest (`integrity`, `integrity.py`); N-GOLD labelling tooling (`ngold`, `ngold.py`,
  [LABELLING_PROTOCOL.md](LABELLING_PROTOCOL.md)); the `inspector-eval` harness skeleton for ТЗ §14.3
  (`harness.py`).

The organizers published only the weights and the gate sentence
(`scoring_summary_without_answers.json`), not the formulas. The scorer therefore implements the
primary hypothesis **H1** of 93 §2.2, exposes every assumption as a switch, and every run reports how
the total would change under each switch.

## Commands

```bash
cd services/ml
uv run --locked inspector-score run --pred runs/<run_id>/submission/ [--out DIR] [--json]   # score against train gold
uv run --locked inspector-score validate --pred FILE|DIR     # schemas + integrity rules only
uv run --locked inspector-score integrity --pred FILE|DIR|RUN_DIR [--require-packaging] [--superseded F] [--out DIR]
uv run --locked inspector-score tgold-gate --run-dir RUN_ID|DIR [--runtime-s S] [--json]   # T-GOLD must-pass gate
uv run --locked inspector-score selftest                     # T-GOLD fixture: 93 §2.3 / §4.10 cases
uv run --locked inspector-score devset list|show ID|freeze ID
uv run --locked inspector-score ngold init|status|packet ID|record|sample|import-spotcheck   # N-GOLD labelling
uv run --locked inspector-score sweep --pred-dir CANDIDATES/ [--devsets T-GOLD,N-GOLD]
uv run --locked inspector-batch score [--object …] [--pred …] [--selftest]   # writes runs/<run_id>/score/
uv run --locked inspector-eval ocr|detection|verdict …      # ТЗ §14.3 acceptance harness (skeleton)
```

`--pred` is a file, or a directory of `<object_id>.json` (a `submission/` sub-directory is found
automatically; `*.sidecar.json` is ignored). The gold defaults to the package's
`public_train_checks.jsonl`. Objects that have no gold rows are skipped and listed (GOLD_NOT_FOUND). A gold
object with no prediction file scores 0.

Exit codes (`inspector_common.exitcodes`): 0 OK · 1 error (and a failing self-test or T-GOLD gate) · 2 usage ·
3 gate triggered · 4 organizer schema invalid, or integrity failures in `validate`/`integrity` · 5 hidden test
refused · 6 data or prediction missing (PREDICTION_NOT_FOUND, GOLD_NOT_FOUND). 93 §4.1 proposed 2 for "schema
invalid"; the shared contract uses 4. `inspector-eval` follows 06 §3.10: 2 when a threshold fails or is not
evaluated.

Outputs (`--out`, and always in `inspector-batch score`) are `score.json` (everything below, plus the
config hash and the sha256 of every input), `per_check.csv`, `gate.csv` and `summary.txt` (the Russian
text report). When `inspector-batch score` scores the run's own T-GOLD submission (the last step of
`inspector-batch run`), it also writes `score/tgold_gate.json`.

## H1 formulas (defaults)

The key of a check is (object_id, normalised `parameter_code`, normalised `location`). The first
occurrence of a duplicate key wins; duplicates fail R10.

| Component (points) | H1 |
|---|---|
| `finding_detection_f1` (60) | TP/FP/FN over keys whose `violation_label` is `VIOLATION_PRESENT`; points = 60·F1 |
| `source_localization_exact_file_page` (15) | Mean over gold positives of \|gold ∩ pred\| / \|gold\| on (stage, file_id, pdf_page_number). The predicted check with the same key supplies the pages. An unmatched gold positive scores 0 |
| `normalized_value_and_status_accuracy` (15) | Mean over all gold checks of 0.5·status + 0.5·values. Status = 0.5·label + 0.25·protocol_status + 0.25·criticality. Each of pd/rd/id_value scores 1 when both are null, or numerically equal after unit normalisation, or when the normalised-text similarity is ≥ 0.85 (rapidfuzz Indel ratio). An unmatched gold check scores 0 |
| `document_integrity_and_split_handling` (10) | Share of passed counted integrity rules (below) |
| Gate | A missed approved critical checkpoint caps the total at 59. The cap value is parsed from the package sentence |

- An **approved critical checkpoint** is a gold check with `VIOLATION_PRESENT` whose criticality starts
  with «Критическое» and does not contain «требует утверждения», whose `gold_status` starts with
  `FINAL` (or is absent, as in team labels), and that is `score_eligible`. FREE-* findings are never
  checkpoints.
- A prediction that fails the **organizer schema** scores 0 on every component (93 §4.2).
- An **empty prediction** scores 0: vacuous integrity is not rewarded (93 §4.10).
- Several objects are pooled micro: summed TP/FP/FN, localisation and value means over the pooled gold
  rows, mean integrity, and a gate on any object. An object-cluster bootstrap CI of F1 needs ≥ 5
  objects (B = 2000, seed 20260927).

## Variant switches (`--key`, `--loc-metric`, …)

| Switch | Values (default first) | Meaning |
|---|---|---|
| `key` | k1, k3, k4 | k3: group-level F1 (group found per `group_rule`: any, majority or all; unmatched predictions are clustered by (code, comparison_result)). k4: a TP also needs ≥ 1 correct page; a key hit with wrong pages counts as FP + FN |
| `loc_metric`, `with_stage` | recall, jaccard, anyhit; true, false | Localisation metric; whether `stage` is part of the page key |
| `value_threshold` | 0.85 | Text similarity threshold |
| `value_norm`, `location_norm`, `code_norm`, `criticality_norm` | light, strict, relaxed | See normalisation |
| `gate` | key, strict, broad | strict: a checkpoint also needs ≥ 1 correct page. broad: every approved critical gold check, of any label, needs the right label |
| `integrity`, `integrity_rules` | share, hard; r1_r15, proto8 | hard: 0 on any failure. proto8: the 8 rules of the 93 prototype (reproduces 93 case H exactly) |

Also always reported: the multi-label F1 over (key, label), status-only and values-only accuracy,
breakdowns by section, criticality and comparison_result, and hedges. Hedges are several codes of one
`codes.yaml` hedge set at one location. The report gives the hedge share against the 20 % budget and
a what-if score without the hedges; it keeps the highest `confidence`, or the first check on a tie.

## Normalisation (version 1, `config.NORMALIZATION_VERSION`)

| Item | strict | light (default) | relaxed |
|---|---|---|---|
| parameter code | upper, trim | + alias resolution (M-xxx, KR-55, КР-55, known typo AR-14 → AR-040); a prefix that disagrees with the id is kept as is | + prefix-agnostic by id |
| location | trim | NFC, casefold, ё→е, unified dashes and spaces; strips «пом.», «помещение», «№»; collapses spaces around `, ; /`. **Leading zeros are kept** («12» ≠ «012») | + strips leading zeros and the «венткамера», «тех. помещение» nouns |
| values | exact equality | NFC, casefold, ё→е, punctuation, decimal comma, thousands spaces, units (м², м³, кв. м); numbers with units are compared in base units (1,0 м = 1000 мм) | + token-set similarity |
| criticality | exact | normalised text | first word (Критическое, Существенное) |

## Integrity rules (93 §4.6)

R1 organizer schema · R2 object in the expected split · R3 evidence file in the manifest ·
R4 same object · R5 not excluded (`excluded_file_ids`) and citable (not `GROUND_TRUTH_INDEX`) ·
R6 `.pdf` and page within `pdf_pages` · R7 stage matches the manifest (`RD_ID_MIXED` accepts RD and
ID; `UNKNOWN` never) · R8 duplicate groups (`duplicate_group` or equal sha256) are cited through their
representative (the lowest non-excluded file_id) · R9 no superseded revision; this needs a list from
the revision resolver (`--superseded`), otherwise it is `NOT_EVALUATED` and not counted · R10 no
duplicate keys · R11 code in the catalog or a valid FREE-<TOPIC>-<NNN>, after the code
normalisation · R12 criticality equals the catalog string (FREE uses the «— требует утверждения»
string) · R13 protocol_status consistent with the label, and CRITICAL or WARNING by criticality ·
R14 evidence files come from the same split as the object · R15 location grammar (93 §2.7): a warning,
never counted.

### The integrity checker (`inspector-score integrity`, `integrity.py`)

Runs R1–R15 on any answer — a file, a `submission/` directory or a run directory — against any
organizer-style manifest (`--manifest`, `--catalog`, `--split-policy`; the scoring weights are not needed), with
the expected split taken from the object's own split in split_policy.json. It adds packaging rules that the
organizers cannot see but our exporter must satisfy (never counted in the 10 points):

| Rule | Check | Input |
|---|---|---|
| P1 | the file is `<object_id>.json` | file name |
| P2 | the sidecar exists, validates (`submission_sidecar`) and describes exactly this object and its files | `submission/<object_id>.sidecar.json` |
| P3 | the sidecar's `input_manifest_hash` and `inputs.manifest_sha256` match the manifest used now | sidecar + manifest |
| P4 | the strict variant exists, validates and equals the organizer-field projection of the full answer | `submission-strict/<object_id>.json` |
| P5 | every cited file was readable in the run (not MISSING_ON_DISK) | sidecar `files[]` |
| P6 | `RD_ID_MIXED` files are cited with their resolved stage (R7 accepts both RD and ID) | sidecar `files[].stage_resolved`, then `inventory/<object_id>.json`, then the registry's name signals |

A P-rule without its input is NOT_EVALUATED; `--require-packaging` (the exporter's gate, and the T-GOLD gate)
turns a missing sidecar or strict variant into a failure. R9 needs `--superseded FILE` (a JSON list or
`{"superseded_file_ids": […]}`) until AG-01's revision resolver publishes one. In-process API for the exporter:
`integrity.check_document(document, ctx, sidecar=…, strict_document=…, require_packaging=True).ok`.

Hidden object: the checker runs only through the frozen-run guard (`--hidden-final` plus a RunManifest or the
sidecar with an existing `freeze_tag`), and its report is always redacted — rule ids, statuses and counts,
never codes, locations, values, file ids or pages.

## T-GOLD fixture and regression cases

`inspector-score selftest` and `tests/test_eval_tgold.py` build the perfect submission from
`public_train_checks.jsonl` and apply the 93 §2.3 perturbations. Measured totals must equal the
analytic expectation within 1e-6, and the figure printed in 93 within 0.05 (93 rounded).

| Case | Perturbation | F1 | Loc | Val | Integ | Gate | Uncapped | **Total** | 93 |
|---|---|---|---|---|---|---|---|---|---|
| A | perfect copy | 1.000 | 1.000 | 1.000 | 1.000 | – | 100.00 | **100.00** | 100.0 |
| B | room 314 dropped | 0.947 | 0.900 | 0.900 | 1.000 | IOS4-078/314 | 93.84 | **59.00** | 59.0 |
| C | warm floor → IOS4-077 | 0.600 | 0.600 | 0.600 | 1.000 | – | 64.00 | **64.00** | 64.0 |
| D | 314 on its own RD page 20 | 1.000 | 0.950 | 1.000 | 1.000 | – | 99.25 | **99.25** | 99.25 |
| E | 012 as IOS4-078 | 0.900 | 0.900 | 0.900 | 1.000 | IOS4-079/012 | 91.00 | **59.00** | 59.0 |
| F | 012 hedged under both codes | 0.952 | 1.000 | 1.000 | 1.000 | – | 97.14 | **97.14** | 97.1 |
| G | generic value texts | 1.000 | 1.000 | 0.667 | 1.000 | – | 95.00 | **95.00** | 95.0 |
| H | wrong stage + F0149 (R1–R14) | 1.000 | 0.950 | 1.000 | 0.769 | – | 96.94 | **96.94** | — |
| H8 | same, 8 prototype rules | 1.000 | 0.950 | 1.000 | 0.625 | – | 95.50 | **95.50** | 95.5 |
| I | «пом. 012» (light) | 1.000 | 1.000 | 1.000 | 1.000 | – | 100.00 | **100.00** | 100.0 |
| I-strict | «пом. 012», strict location | 0 | 0 | 0 | 1.000 | 6 missed | 10.00 | **10.00** | «0» |
| J | «12» for «012» (light) | 0.900 | 0.900 | 0.900 | 1.000 | IOS4-079/012 | 91.00 | **59.00** | 59.0 |
| J-relaxed | same, relaxed location | 1.000 | 1.000 | 1.000 | 1.000 | – | 100.00 | **100.00** | — |
| K | empty prediction | 0 | 0 | 0 | 0 | 6 missed | 0.00 | **0.00** | — |
| L | aliases ИОС4-79, M-078 (light) | 1.000 | 1.000 | 1.000 | 1.000 | – | 100.00 | **100.00** | — |
| L-strict | same, strict codes | 0.400 | 0.400 | 0.400 | 0.923 | 6 missed | 45.23 | **45.23** | — |

Hedging (F) is cheap insurance: removing the hedge (the what-if in the report) drops the total to 59.

## Hidden-test guard (93 §4.9, 97 §2.17)

Nothing about a TEST_HIDDEN object is scored or shown unless both of these hold:
- the caller passes `--hidden-final`;
- `--run-manifest` points to a RunManifest or sidecar that validates, lists the object, and has a
  non-empty `freeze_tag` that exists as a git tag (for example `hidden-run-freeze`).

The check runs on object ids only (`--objects`, the gold rows, each prediction's `object_id`), before
anything else is read or printed. Hidden ids are read from `split_policy.json`. `inspector-batch score`
refuses hidden objects in the CLI and again in this package; the frozen path exists only in
`inspector-score`. The dev-set registry and `sweep` refuse hidden objects outright.

## T-GOLD must-pass gate (`tgold-gate`, 95 §3.8, 97 M1)

`tgold_gate.evaluate(run_dir, …)` checks one run on OBJ-TYUMENSKAYA-5-GOLD-SEED:

| Id | Criterion | Hard |
|---|---|---|
| G1 | the answer exists and validates (organizer and extended schemas) | yes |
| G2 | all 10 gold keys are VIOLATION_PRESENT | yes |
| G3 | each key cites the gold PD and RD pages (anchor rule; localisation recall with stage = 1) | yes |
| G4 | the critical-miss gate does not trip (key variant and strict variant) | yes |
| G5 | label, protocol_status and criticality equal the gold; values below 1.0 are a warning | yes |
| G6 | ≤ 5 extra VIOLATION_PRESENT keys | yes |
| G7 | R1–R15 pass and P1–P6 pass with a sidecar and a strict variant | yes |
| G8 | RT-01…RT-10 have no FAIL; a check whose producing step ran (pipeline summary) but left no artifact fails | yes |
| G9 | the runtime is logged (measured wall time, sidecar/run-manifest timings, recognition summary) | warning |

Status: FAIL if any criterion fails, INCOMPLETE if a hard criterion is NOT_EVALUATED (e.g. RT checks whose
producer is still a stub), PASS otherwise. The report goes to `runs/<run_id>/score/tgold_gate.json`.

**RT-01…RT-10** (`rtcheck.py`) turn the prose assertions of `95_tyumen_dev_fixtures.json` into checks over the
run artifacts (PageTokens, `layout/`, `tables/`), with homoglyph folding (OCR «B2.1» = printed «В2.1») and the
fixture zones widened by 0.02. Each names its owner (AG-02A tokens, AG-02B layout, AG-02C tables) and is
NOT_EVALUATED while its artifact is absent.

**The must-pass test** is `tests/test_eval_tgold_e2e.py` (`slow` + `data`): it runs
`inspector-batch run --object OBJ-TYUMENSKAYA-5-GOLD-SEED --keep-going` (recognition workers default to 3 on the
shared host), then asserts G1–G7 pass, G8 has no failure and G9 passes. It skips while `recognize`, `compare`,
`export` or `score` is still a stub (`tgold_gate.pipeline_stubs()` reads the hooks), starts the pipeline only
under an explicit `-m slow` selection, and `INSPECTOR_TGOLD_RUN_ID=<run_id>` evaluates an existing run instead.

## Dev sets and calibration

`src/inspector_eval/devsets/registry.json` lists two sets:
- **T-GOLD**: organizer train gold. It is pinned by the file sha256 and the pin is verified on load.
- **N-GOLD**: team labels for Новослободская, `devsets/n_gold_novoslob_v1.json`, **format 2**
  (`devsets/n_gold_label_set.schema.json`), which extends `docs/analysis/95_novoslob_label_seed.json`: every
  seed field is kept; items gain `source`, `scorable`, `annotations` (one per labeller pass: labeller, kind
  AGENT/HUMAN, blind flag, label, corrected code/location/evidence/values, confidence, reasoning, pages viewed)
  and `adjudication`. `label` is a ViolationLabel or `UNSURE`; UNSURE, unlabeled and `scorable: false` items are
  listed but not scored. `protocol_status` and `criticality` are derived from the catalog; `MISSING_DOCUMENT`
  takes the missing stage from null values without evidence, or an explicit `protocol_status`.
- Labelling follows [LABELLING_PROTOCOL.md](LABELLING_PROTOCOL.md): blind packets (`ngold packet ID`: the
  question, page images and the pages' own text layer; system outputs are never written into a packet), agent
  and human annotations (`ngold record`), automatic adjudication (a human label beats a disagreeing agent label;
  labellers of one kind that disagree make the item UNSURE), a deterministic stratified spot-check sample for
  the user (`ngold sample --n 28`: `sheet.csv`, `index.html`, `key.json` kept apart), and the import of the
  filled sheet with agent/human agreement (`ngold import-spotcheck`: raw agreement and Cohen's κ).
- `inspector-score devset freeze N-GOLD` pins the canonical hash of the labelled items (`labels_sha256`) and the
  file's sha256 (`file_sha256`); it refuses while an item is UNRESOLVED. Frozen rows carry
  `gold_status = TEAM_LABEL_FROZEN` (the gate simulation treats them as approved, like FINAL* organizer gold);
  every `ngold` write is refused and any edit of the file fails with `TEST_SET_HASH_MISMATCH`.

**State (2026-09-28):** the 14 seed candidates of 95 §4.4 are labelled by the agent protocol (labeller AG-10,
`blind: false` — the labeller had read the seed hypotheses; every value was re-read from the pages): 10
NO_VIOLATION, 1 COMPARISON_IMPOSSIBLE (scorable), and 3 not scorable (NS-C09 elevation trap without a catalog
parameter, NS-C12 foreign ciphers in ТХ3, NS-C13 the 19 recovered АОСР). The set is **not frozen**: it has no
positives yet, waits for the system candidates of the Новослободская run (M2) and the user's spot-check.

`inspector-score sweep --pred-dir DIR` runs leave-one-out calibration (93 §4.8). Each candidate is a
sub-directory with an optional `params.json` and `[submission/]<object_id>.json` files. A fold is one
dev set, or one code-prefix group of it (N-GOLD folds A = KR and B = the rest, 95 §5.1). For every
held-out fold, the candidate that is best on the other folds is scored on it. The final choice is
tuned on all folds; its «seen» score is labelled as not a result. With fewer than two folds, the
status is `INSUFFICIENT_FOLDS`.

## `inspector-eval` (ТЗ §14.3, skeleton)

`harness.py` measures what a run produced, independently of the code under test (it imports neither
recognition nor comparison). `ocr` scores the run's PageTokens against the adjudicated line GT
`docs/analysis/gt_staging/ocr_gt_v2.json` (strict CA per GT line: minimum semi-global edit distance against the
overlapping run lines or their same-row concatenation; it reproduces AG-02A's `score_line_gt_v2` exactly on the
same input). `detection` computes P/R/F1 (a TP needs code, location and one correct page: the k4 key) and FPR on
the negatives of a dev set, with Wilson intervals. `verdict` lists all eight §14.3 thresholds; key fields,
linkage and bbox IoU are NOT_EVALUATED until their gold exists.

## Tests

`uv run --locked pytest -m "not slow" packages/inspector_eval/tests` runs 223 tests in about 4 s (organizer-data
tests are marked `data` and skip without the package). The only slow test is the T-GOLD end-to-end gate.
