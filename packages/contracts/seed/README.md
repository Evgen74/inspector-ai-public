# packages/contracts/seed — matrix seed (owner: AG-03)

The 132-parameter matrix as data, plus the routing dictionaries built on it. Loader and helpers:
`services/ml/packages/inspector_common/src/inspector_common/params.py`.

| File | Content |
|---|---|
| `params.json` | 132 parameters keyed by the catalog code (PZ-001 … SM-132): ТЗ §8.1 fields, 97 §2.8 extensions, the comparison-rule DSL, hardened regexes with examples, context gates, hedge groups, the sub-checks moved to Logical_Rules, the web-verified normative references and thresholds (`references`, `norm_verification`), and a change log (`seed_changes`). |
| `recommendation_templates.json` | Приложение 2 Раздел 7 texts for the 132 parameters and the 17 FREE topics: «Вид работ», «Вид нарушения», the recommendation, the «Отклонение» phrases of Разделы 4–5, delta formats, norm fill, edition rules and verified norm references; the deviation vocabularies and the norm edition registry. |
| `value_templates.json` | Submission-style formats and generic templates for `pd_value` / `rd_value` / `id_value` (93 §3.5), with an element-noun lexicon. |
| `change_matrix_map.json` | Element family × discrepancy type → parameter code with `parameter_mapping_status`, `emit`, hedge codes and value templates (97 §2.10). |
| `free_topics.json` | The fixed FREE-<TOPIC> vocabulary (equal to `enums.FreeTopic`), numbering and export policy. |
| `schemas/*.schema.json` | JSON Schema 2020-12 for the five files and the DSL (`comparison_rule.schema.json`); they `$ref` `../schemas/enums.schema.json` and `common.schema.json`. |
| `src/` | Build inputs: `regexes.yaml`, `texts.yaml`, `rules.yaml`, `change_matrix_map.yaml`, `free_topics.yaml`, `norms.yaml`, `value_templates.yaml`, `norms/*.json` (verified norms, adopted verbatim), `build_seed.py` and `build_templates.py`. |

The JSON files are generated. Edit the YAML sources, then rebuild:

```bash
cd services/ml
uv run --locked python ../../packages/contracts/seed/src/build_seed.py          # write the JSON files
uv run --locked python ../../packages/contracts/seed/src/build_seed.py --check  # exit 1 when they are stale
uv run --locked python -m inspector_common.params check                          # schemas + cross-file checks
```

The build needs the organizer catalog (`INSPECTOR_DATA_ROOT`), `docs/analysis/matrix_enriched.json`, the YAML sources
and `src/norms/`, and it is deterministic. The sha256 of every input is recorded in `sources`, and `content_sha256`
hashes the canonical JSON of the parameters and dictionaries (`matrix_version` 1.1.1, 90 §3.3.2: 1.1.0 was the M0
seed; 1.1.1 adds the verified norms and the templates). The data test `test_committed_seed_equals_a_fresh_build`
fails when a committed file is stale.

## Parameters (`params.json`)

- **Merge rule.** The organizer catalog wins on code, name, unit, sources, trigger and criticality. Everything
  else comes from `matrix_enriched.json` (B03), patched by `src/rules.yaml`. The build fails if the catalog and
  matrix_enriched disagree on any shared text.
- **ТЗ §8.1 mapping.** `id` → `param_id` (1…132, the join key). `code` is the catalog code (VARCHAR 20).
  `section` is the short section («КР», «ИОС4»; VARCHAR 50). The four reference columns are text renderings of
  `references` (each reference carries its confidence). `regex_pattern` is at most 255 characters
  (VARCHAR(255)); longer or alternative patterns go to `regex_aux`.
- **Codes (97 §2.9).** `alias_codes` = [M-xxx, ТЗ/Приложение 2 Latin short form, Cyrillic short form] (KR-55,
  КР-55); for ids ≥ 100 the short form equals the catalog code. The resolver accepts every alias as well as:
  - any zero padding, typographic dashes, «KR 55» and «KR55»;
  - prefixes typed in the wrong alphabet (KP-55 → KR-055, with a warning).

  The prefix must agree with the id range. The Приложение 2 typo «AR-14» resolves to AR-040 by name, with a
  warning. Any other disagreement is resolved by the parameter name when one is given; otherwise by the number,
  with a warning, or it raises in `strict` mode.
- **Criticality (97 §2.8).** `criticality` is the exact catalog string (106 «Критическое (приостановка работ)»,
  26 «Существенное (предписание)»). `criticality_level` is the enum, and `review_priority` is HIGH for critical
  parameters and MEDIUM otherwise.
- **DSL (03 §3.4 plus later rulings).**
  - Every atomic rule has a `direction` (ANY/DECREASE/INCREASE/DOWNGRADE) and a `candidate_policy`
    (TRIGGER/DEVIATION). Directional triggers are enforced: an improvement is not a violation (97 §2.10; 97 Q4b).
  - The four INTERNAL_CONSISTENCY sub-checks moved to Logical_Rules (listed in `moved_to_logical_rules`).
  - SUSPICION appears nowhere in the DSL: a low-confidence SEMANTIC_DIFF gives NOT_COMPARABLE
    (LOW_CONFIDENCE_SEMANTIC), and a missing geometry gives NOT_COMPARABLE (GEOMETRY_NOT_EXTRACTED) (90 C-53).
  - SET_DIFF separates `detect` (emitted) from `context_detect`: additions and relocations are context (97 §2.10).
  - Ventilation rules follow the organizers' gold. IOS4-078.b and IOS4-079.b are keyed by room: a room without
    exhaust in RD is MISSING, a changed branch set is CHANGED. Warm floors were removed from IOS4-077 and route
    to FREE-HEATING.
  - `sub_id` values use the catalog code, e.g. PZ-003.b.
- **Hedge groups (97 §2.10).** There are ten groups: the three named in 97 (IOS4-078/079, AR-040/PPM-104/ODI-116,
  AR-041/PPM-105) and the other duplicates from 03 §6 #5. They cover AG-00's `codes.yaml` `hedge_pairs`.
- **Texts (Приложение 2, 93 §5.4).**
  - `short_name` is shown as «{short_name} ({code})». 27 short names are verbatim from Приложение 2 (kept even where
    the verification proposed a more precise name, which becomes a name variant); the other 105 follow the verified
    templates (M0 drafts stay as `name_variants`).
  - `work_type`, `recommendation_template` and `deviation_verb` (keyed by DiscrepancyType, without the marker) are
    derived from `recommendation_templates.json`, so the protocol and the DB column read one source.
  - `text_sources` marks each text as APPENDIX2 (verbatim Приложение 2: 27 short names, 6 work types, 3
    recommendations — computed by rendering the template with the sample row) or AG03_DRAFT (awaits expert review,
    97 Q3; `python -m inspector_common.params review` prints the checklist).

## Verified norms (M1, `src/norms`, `src/norms.yaml`)

Two review-phase files verified all 132 parameters against the editions in force on 27.09.2026 (294 references,
42 additional ones, thresholds with conditions). They are adopted verbatim into `src/norms/` (the sha256 equals the
staging files in `docs/analysis/norms_staging`); every AG-03 decision is in `norms.yaml`.

- **References.** `references.{sp,gost,fz,other}` hold the verified records: `ref` (ТЗ §8.1 display «СП 1.13130.2020,
  п. 4.2.1»), `status` (NormRefStatus: CONFIRMED 232, CORRECTED 31, OUTDATED 30 — the replacement is cited, the
  Matrix citation stays in `matrix_cited` — ADDED 42), `confidence` (HIGH 258, MEDIUM 72, LOW 5), `designation`,
  `clause`, `edition`, `condition`, `value`, `url`, `quote`. The ТЗ text columns are rendered from them. The one
  NOT_FOUND reference (SPZU-031, «радиус поворота 10–12 м») is never cited: `norm_verification.references_not_found`.
- **`norm_verification`** per parameter: the verified threshold (`status` in NormThresholdStatus, min/max, unit,
  condition), notes, the edition rules that concern it, regime changes and the AG-03 threshold decision.
- **Thresholds.** The matrix literal is the customer's trigger (Приложение 1). It is overridden only when the norm
  shows it is wrong in a way that matters: ODI-117 0,9 м (D-04 closed, HIGH), ODI-121 3,5 → 3,6 м, ODI-119 1,5 → 1,7 м
  (1,5 м for reconstruction), PPM-104 gets the 1,0 м condition for ≤ 50 people. A softer or conditional literal
  stays (ODI-116, PPM-105, SPZU-031) and the verified norm is recorded next to it. Every change is in `seed_changes`.
- **Editions (90 C-50).** `norms.yaml documents` is the edition registry (22 replacements, 4 expiring documents).
  Design norms follow the PD approval date; process, as-built and waste norms the date of the event. The renderer
  cites the previous edition for an older PD (template `edition_rules` for `{norm_ref}`, and inline citations are
  rewritten to the previous designation without clause numbers). `params.norm_edition()` walks successive
  replacements (ГОСТ Р 51261-2025 → -2022 → -2017).
- **Moscow waste control from 01.07.2026** (regime MOSCOW_OSSIG_2026_07, by the date of the trip or the start of work):
  OOS-098 checks the object in the АИС «ОССиГ» registry and the per-trip permits (the «open permit» service was
  abolished); OOS-100 accepts the «Мобильный КПТС» QR code only for trips before 01.07.2026, later trips need the
  АИС «ОССиГ» record; OOS-099 checks registration in the Moscow РНИС. The regexes recognise «ОССиГ» (the Matrix
  spells «ОСИГ») and «разрешение на рейс».

## Recommendation templates (`recommendation_templates.json`)

- 132 parameter templates in catalog order and one per FREE topic (the staging «GENERIC» is the contract OTHER).
  Field names follow the protocol contract: `work_type` (7.1), `violation_kind` + `violation_kind_variants` (7.2),
  `recommendation` + `recommendation_variants`, `deviation_phrases` (Разделы 4–5, with the Приложение 2 marker),
  `delta_format` (ABS, PCT, COUNT, NONE; per kind), `count_noun`, `norm_fill`, `edition_rules`, `norm_refs`.
- Variants are keyed by DeviationKind (DECREASE, INCREASE, CLASS_DOWNGRADE, ABSENCE, SUBSTITUTION,
  CONFIGURATION_CHANGE, NORM_VIOLATION, TOLERANCE_EXCEEDED, ZONE_INTRUSION; «DECREASE:бетон» narrows by element).
  `vocabularies` maps every DiscrepancyType, ComparisonResult and ViolationType to a kind (BY_SIGN: the numbers
  decide) and every marker to a DeviationDirection.
- `app2_sample` keeps the Приложение 2 row verbatim with the documented differences; `text_origin` is APPENDIX2 only
  when the template filled with that row reproduces the docx text (6 work types, 3 violation kinds,
  3 recommendations). The nine other sample recommendations differ on purpose: verified norms replace the sample's
  unverified ones (e.g. «радиус поворота не менее 12 м» — no such norm; «согласовать с МЧС» — no such procedure).
- **Numbers policy:** every number in a text comes from a HIGH-confidence verified record of the parameter or of a
  cited record; the build fails otherwise (`params.unverified_numbers`), and a test re-checks 88 quantities.

Renderer rules (R1–R9 in `conventions`): parts of a parenthesised group are separated by «; » and dropped when their
placeholder has no value; {delta}/{element} outside parentheses drop with their connector; «Отсутствуют 1 узел» →
«Отсутствует»; «на 1 квартиру»; « ({code})» is appended in 7.1/7.2; preliminary texts get «Проект рекомендации (до
подтверждения инспектором): ». PCT deltas use one decimal half-up without «,0» (the sample prints 15,9 % as «16%» but
12,5 % as «12,5%»; one rule is kept).

## Value templates (`value_templates.json`)

`params.stage_values()` returns `{pd_value, rd_value, id_value}`: the change-map route template when the family ×
discrepancy has one (the gold phrasing, all 10 Тюменская checks reproduced), otherwise the generic template of the
ComparisonResult with the element noun and agreement («Тёплый пол предусмотрен», «Вытяжная вентиляция отсутствует»,
«Тактильные указатели предусмотрены»); a stage outside the check is null. `params.format_value()` writes values in
submission style: decimal comma with the written scale («1,0 м»), «4×95 мм²», «850 м²», «16%», concrete class «B35»
and fire resistance «EI-60» as in the Приложение 2 sample (normative texts keep «EI 60»). Missing sheet or plan
marks fall back to «по ПД» / «в РД». `params.protocol_cell()` prints «—» for a stage outside the check and «нет
данных» for a missing value.

## Regex policy (97 §2.14)

Every seed pattern is Python `re`, runs on text normalised by `params.normalize_regex_input`, and runs only
through `params.compile_guarded`:

1. **Static analysis (`regex_safety_problems`).** It rejects:
   - back-references;
   - nested quantifiers over overlapping characters;
   - quantified groups that can match the same text in several ways (`(a|aa)*`, `(\d\d?)+`);
   - adjacent elastic quantifiers that can absorb the same characters (`\s*,?\s*`);
   - an unbounded repeat followed by an overlapping filler (`слово\w*[^\n]{0,60}?\d`);
   - a leading unbounded quantifier;
   - bounds above 1000.

   The original matrix patterns fail these checks in 85 of 141 cases, and the seed passes in all 145.
2. **Windows.** Each regex call sees at most 20 000 characters. Windows overlap by 512 characters and end at line
   breaks where possible; matches cut by an artificial boundary are dropped and found whole in the neighbouring
   window.
3. **Time budget.** The limit is 0.5 s per window. It is hard in the main thread: an `ITIMER_REAL` alarm
   interrupts the regex engine and raises `RegexTimeout`. Elsewhere, or when another SIGALRM user is active, the
   limit is soft and only logged.
4. **Pattern style.** Russian word suffixes are `[а-яё]*+`: letters only and possessive, never `\w*`, which also
   matches digits and made «слово12345» ambiguous. Numbers are anchored with `(?<![\d.,])`. Optional captures
   carry their own filler, so the captures are actually filled (M-078, M-060, M-073, M-079 used to lose them).
5. **Named groups.** The primary value is the first non-empty group among `v`, `v2`, `v3`; other groups are
   attributes (`sys`, `mark`, `layer`, …).
6. **Context gates** (`context_gates`, applied by `ParamRegistry.extract`):

   | Gate | Decides |
   |---|---|
   | CONCRETE_CLASS / VENT_SYSTEM_TAG | «В20» is a concrete class or an exhaust system |
   | KM_FIRE_CLASS | «КМ1» is a material fire class or the steel-structures mark |
   | WATER_SYSTEM_TAG, SEWER_SYSTEM_TAG, HEATING_SYSTEM_TAG | «В1», «К1», «Т1» are system tags, not a flammability class, a column mark or a toxicity class |
   | STAIR, STRUCTURAL_SECTION, VENT_DUCT | «150х300», «500х600», «400х200» belong to a stair, a column or a duct |
   | ROOF_LAYER | a line is part of a roof or floor assembly |
   | ID_AS_SOURCE_DATA / ID_AS_BUILT | «ИД» means «исходные данные» (П-ИД) or the as-built stage |

   A gate uses capture groups, a discipline hint (КЖ, ОВ1 …) and require/reject words within a window; when
   both kinds of word are present, the nearest one wins. `params.classify_b_token` and
   `params.classify_id_abbreviation` expose the two classifications for other agents.
7. **Examples.** Every parameter has positive and negative `regex_examples`: 132 parameters, 358 examples, all
   run through the gates.

Measured on this machine:
- Timing fuzz over all 145 patterns with 13 adversarial inputs each: the worst case is under 10 ms at 20 000
  characters. The original M-044 pattern did not finish in 5 s on a 10 500-character CAD line, and M-109 took
  0.46 s on 9 000 characters.
- 403 real train pages (794 000 characters, TRAIN_PUBLIC only), all 145 patterns with gates: median 6.5 ms per
  page, p95 31 ms, maximum 131 ms, 0 timeouts.

## Change map (`change_matrix_map.json`)

The policy is «learned from T» (97 §2.10):
- Map a change to the closest parameter of the same engineering system by element family
  (PROVISIONAL_DOMAIN_MAPPING).
- Use FREE-<TOPIC> only for a matrix gap (MATRIX_GAP_CONFIRMED).
- Directional triggers are enforced.
- Additions and relocations do not emit.

Each route names:
- its DiscrepancyTypes, all of which map to one ComparisonResult;
- the parameter code, a FREE topic, or `null`;
- `emit`, the sub-check that evaluates it, the hedge codes (a subset of the parameter's hedge group), and value
  templates that mirror the gold phrasing;
- a `basis`: GOLD:G-TR-00x (organizer gold), MATRIX (the trigger names the element), ANALOGY (a provisional
  analogy: review it), USER:Q4x (the user's answer to 97 Q4), or CONTEXT (non-emitting by policy).

The data tests reproduce all 10 Тюменская gold checks, including their pd_value and rd_value strings, from the
templates. Examples:
- WARM_FLOOR/ELEMENT_MISSING → FREE-HEATING (-001 per group), «Тёплый пол предусмотрен/отсутствует»;
- VENT_EXHAUST_BRANCH → IOS4-078, and VENT_SUPPLY_UNIT → IOS4-079, hedged with each other;
- CONCRETE_FW_MARK (F/W marks lowered while the B class is unchanged) → FREE-STRUCTURE (Q4a);
- FOUNDATION_SLAB/VALUE_INCREASED and STRUCTURE_ELEVATION/VALUE_INCREASED do not emit (Q4b, Q4c).

## Loader (`inspector_common.params`)

```python
from inspector_common import params
reg = params.load_params()                    # ParamRegistry (cached); reg.get("КР-55").code == "KR-055"
params.resolve_code("AR-14", name="Ширина эвакуационных коридоров")   # → AR-040, method known_fix, warning
params.criticality_level(55)                  # CriticalityLevel.CRITICAL_SUSPEND
reg.hedge_codes("IOS4-079")                   # ("IOS4-078",)
reg.extract("KR-055", params.normalize_regex_input(text), discipline="КЖ")   # gated RegexHit list
params.load_change_map().route("WARM_FLOOR", "ELEMENT_MISSING")               # Route(parameter_code="FREE-HEATING", …)
params.load_free_topics()["HEATING"].code(1)  # "FREE-HEATING-001"
params.load_catalog()                          # organizer rows (CatalogRow), read-only
params.compile_guarded(pattern)               # any other agent's regex: same safety analysis, windows and time limit
params.stage_values(family="VENT_SUPPLY_UNIT", discrepancy_type="CONFIGURATION_CHANGED",
                    pd_sheet=26, rd_plan_mark="ОВ1", location="012")   # gold pd/rd/id_value (id → None)
params.format_value((4, 95), "мм2")            # '4×95 мм²'
r = params.render_recommendation("AR-040", discrepancy_type="VALUE_DECREASED", pd_value="1,4 м",
                                 rd_value="1,1 м", expected=1.4, actual=1.1, unit="м",
                                 location=params.location_display(["1.05"]), pd_approved_on="2024-05-01")
r.work_type, r.violation_kind, r.recommendation, r.deviation_cell()    # Раздел 7 cells + «⬇️ Сужение на 0,3 м»
r.resolution_row(1)                            # protocol ResolutionCriticalRow / ResolutionSubstantialRow body
params.norm_edition("СП 42.13330.2026", on="2025-05-01")                # 'СП 42.13330.2016'
```

The same operations are available on the command line: `python -m inspector_common.params check | show <code> |
resolve <code> [--name …] [--strict] | render <code> [--discrepancy …] [--pd …] [--location …] [--pd-approved …] |
review [--priority 2]` (the expert checklist of 97 Q3).

## Tests

Tests live in `services/ml/packages/inspector_common/tests/test_params_*.py`:
- the default run covers structure, codes, regexes, gates, routing and the timing fuzz at 10 000 characters, and
  (M1) the norms merge (`test_params_norms.py`), the recommendation templates (`test_params_templates.py`: 132 codes,
  verified numbers, every placeholder subset renderable, editions, protocol-contract rows) and the value templates
  (`test_params_values.py`: gold values, formats, agreement);
- tests marked `data` compare against the catalog, Приложение 2 and the Тюменская gold, and check for build
  drift;
- tests marked `slow` run the fuzz at 60 000 characters and the scan of real train pages.
