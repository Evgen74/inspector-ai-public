# B03 — Матрица 132 параметров и предметная область (Matrix & Domain Knowledge)

**Block:** B03-matrix-domain. It is the core of the system and feeds Module 1 (extraction), Module 2 (comparison) and Module 8 (normative-base admin). It also supplies Module 5 (Logical_Rules seed) and the ИД completeness control.

**Deliverables of this planning pass**

| # | Artifact | Path | Status |
|---|---|---|---|
| a | This report | `/Users/evgen/pl/hackaton/docs/analysis/03_matrix_132_domain.md` | done |
| b | Enriched matrix, 132 objects (validated with Python: 132 codes M-001…M-132, all regexes compile, `regex_pattern` ≤ 255 chars, all cross-refs resolve) | `/Users/evgen/pl/hackaton/docs/analysis/matrix_enriched.json` | done |
| d | ИД completeness checklist (Appendix 19 scans + ТЗ §5, 111 items: 94 leaves and 17 groups) | `/Users/evgen/pl/hackaton/docs/analysis/id_completeness_checklist.json` | done |
| c | Tier statistics, demo priorities, per-section extraction strategy, rule DSL, Logical_Rules seed (40 rules) | this report, §3.6–3.9 | done |

**Headline numbers**

- Feasibility tiers: **A = 38**, **B = 63**, **C = 27**, **D = 4**. Among the 106 HIGH-priority params: A 33, B 45, C 24, D 4.
- The 132 params break down into **218 atomic sub-checks**. By type: 90 pairwise-delta, 38 normative-bound, 16 ordinal, 16 set-diff, 14 presence, 10 enum-change, 8 zone, 5 tolerance, 5 external, 5 semantic, 4 internal-consistency, 4 layer-stack, 2 geometry-offset, 1 ratio.
- 294 normative references: HIGH 108, MEDIUM 144, LOW 42. No clause number is asserted with HIGH confidence unless it is well established. Uncertain ones are marked «требует проверки».
- 39 params can also run a single-stage check: normative bound, tolerance, ratio or external status. So they produce results even in the `SINGLE_ONLY` scenario.
- 22 params are not applicable by default. They need a positive fact, for example gas supply, demolition, underground parking or a budget-funded object.

**Key domain finding.** All three pilot area findings sit **below** the M-002 trigger of 1 %:

| Object | Floor total ПД → РД | Change |
|---|---|---|
| ALT79B | 2797,27 → 2811,07 м² | +0,49 % |
| SOSH25 | 6234,1 → 6252,3 м² | +0,29 % |
| DOO25 | 1115,8 → 1112,6 м² | −0,29 % |

The pilot still marks all three as candidates, so the real signal is **room-level** diffing of the explication tables under M-003. Those tables are in the vector text layer. A system that only compares ТЭП numbers against the matrix thresholds would miss all three. We put this contrast in the demo on purpose: M-002 gives NEGATIVE_VERIFIED while M-003 gives CANDIDATE.

---

## 1. Scope

### 1.1 ТЗ clauses covered

| Clause | Quote / content | What this block owns |
|---|---|---|
| §1.2 | «выявление нарушений и несоответствий … по 132 контролируемым параметрам»; «автоматический контроль наличия документов» | The 132 params as data and executable rules; the ИД completeness checklist |
| §2 | Normative base «действующими по состоянию на июль 2026 года» (ГрК, ПП 87, ПП 2078, ПП 2161, Приказ 344/пр, ГОСТ Р 21.101-2020, ГОСТ 21.110-2013, 123-ФЗ, 261-ФЗ, 397-ПП, 152-ФЗ, 187-ФЗ, 4802-1) | Normative references per param; Normative_Base seed; `effective_from/effective_to` |
| §3 | ПД sections per ПП 87 (ПЗ…ИН), ИОС1–5 subsections; «Разработка разделов 6, 11, 5 и 9 для объектов, финансируемых из бюджетов, обязательна в полном объёме» | Section dictionary, reconciled with the matrix numbering; Logical rule HR-LOG-017 |
| §4 | RD composition (основные комплекты, рабочие чертежи, СО по ГОСТ 21.110, ВО/ВС/ВР, ОД, СМ, ОЛ/ГЧ, РР, ПД) | Document-kind vocabulary (`doc_kind`) for `source_docs` |
| §5 | ИД composition (13 rows, Приказ 344/пр прил. 1) plus notes 1–4 (УКЭП/УНЭП, scan requisites, stamps «В производство работ» / «Выполнено согласно проекту», hidden-works list from ОД) | `id_completeness_checklist.json` |
| §6 | Mapping of matrix section → ПД section → RD component → ИД document | `source_docs.tz6_mapping` on every param |
| §7 #1, #2, #8 (High, High, Medium) | Module 1: «извлечение данных по 132 параметрам согласно Матрице контроля»; Module 2: «раздельные статусы комплектности и findings»; Module 8: «добавлять, редактировать и деактивировать нормативные ссылки, обновлять пороговые значения параметров (min_value, max_value) без перекодирования системы» | Params data and rule DSL; threshold references (`$min_value`) so admins change numbers without code changes |
| §8, §8.1, §8.2 | «Матрица контроля является ядром системы»; the Params table (21 fields); examples PZ-01, KR-55, AR-41 | Params seed with all §8.1 fields; alias-code scheme |
| §9.1 п.2 | «Поиск по 132 параметрам с использованием регулярных выражений (regex_pattern) и семантических якорей … Sentence-BERT (all-MiniLM-L6-v2) или её совместимые аналоги» | Regex drafts, aux regexes, Russian semantic anchors, the multilingual-model recommendation |
| §9.1 п.3 | «CV-анализ … масштабирование по размерной линейке, распознавание линий и измерение расстояний» | Which params need CV (tier C) and what simplified fallback applies |
| §9.2 п.1–3 | «загрузка версии Матрицы … Версии Матрицы … фиксируются в каждом запуске»; «Сначала проверяются применимость параметра, комплектность доказательств, актуальность и сопоставимость редакций; только после … предметное сравнение»; «Если по правилу достаточно двух стадий, выполняется парное сравнение; отсутствующая неприменимая стадия отмечается NOT_APPLICABLE» | Per-param `applicability_conditions`, `stages_required`, `comparison_rule`, abstention reasons |
| §9.2 statuses | NEGATIVE_VERIFIED / CANDIDATE / CONFIRMED_VIOLATION / MISSING_EVIDENCE / NOT_APPLICABLE / NOT_COMPARABLE / CLARIFICATION_REQUIRED / SUSPICION; «Уровень риска … только для очередности» | Rule outputs are limited to the statuses the system may assign. CONFIRMED_VIOLATION is never automatic |
| §9.3 п.2 | «Составной кандидат не получает единый учебный статус PARTIALLY_CONFIRMED: инспектор разделяет его на атомарные findings» | Composite params are pre-split into atomic sub-checks (`M-042.a/b/c`) |
| §9.5 | Four hypothesis approaches; Suspicion JSON (`normative_base`, `review_priority`) | Logical_Rules seed (40 rules), room-function taxonomy for semantic dissonance, normative bounds |
| §10 #1, #9, #10 | Params; Logical_Rules (id, rule_name, condition, expected, normative_base, is_active); Normative_Base (…, min_value, max_value, effective_from, effective_to) | Seeds and schemas for all three |
| §11 #4, #7 | Comparison of 132 params ≤ 2 min; «ML-анализ одного параметра (NLP) ≤ 500 мс» | Precompiled regexes, cached anchors, rule engine cost (ms) |
| §14.1–14.3 | Evidence group = «один объект, один параметр или атомарное правило»; metrics «отдельно по разделам и типам нарушения»; FPR ≤ 0,10 | `section`, `violation_type` taxonomy and `atomic_sub_checks`, used as metric dimensions; precision-first tolerances |
| Приложение 1 (xlsx) | Sheets МАТРИЦА, СХЕМА GOLD, МЕТРИКИ, ПРИМЕРЫ РАЗМЕТКИ | Verbatim import; pilot findings mapped to params |
| Перечень ИД (docx) + Прил. 19 scans | Expected ИД list; mandatory machine-readable registry; source-selection rules | Checklist `package_requirements` and items |

### 1.2 Related statuses, tables and NFRs

- **Statuses produced by this block's rules:** CANDIDATE, NEGATIVE_VERIFIED, MISSING_EVIDENCE, NOT_APPLICABLE (always with a basis), NOT_COMPARABLE (with an `abstain_if` reason), and SUSPICION (internal-consistency and low-confidence semantic sub-checks). CLARIFICATION_REQUIRED comes from the revision logic in B01/B04; the rules never emit it.
- **Tables owned or seeded:** `params` (+ extension columns), `matrix_versions` (+), `normative_base`, `param_normative` (+ link), `logical_rules`, `enum_scales` (+), `unit_conversions` (+), `term_synonyms` (+, room-function taxonomy and homoglyph map), `violation_types` (+), and `completeness_templates` (+, seeded here, run by B01).
- **NFRs touched:** §11 #4 and #7 (performance); §12 #4 (audit of admin changes to params); §14 (metric dimensions).

---

## 2. Requirements checklist (MTX-NN)

Priority for winning: **MUST** / **SHOULD** / **NICE**. MVP decision: **FULL** / **SIMPLIFIED** / **MOCKED** / **OUT_OF_SCOPE**.

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| MTX-01 | `params` has every §8.1 field: id, code, section, parameter_name, unit, source_pd, source_rd, source_id, trigger_logic, review_priority, sp_reference, gost_reference, fz_reference, other_normative, data_type, min_value, max_value, regex_pattern, is_active, created_at, updated_at | §8.1, §10 #1 | MUST | FULL | The JSON seed covers every field; extensions go in extra columns, never in place of ТЗ fields |
| MTX-02 | All 132 params loaded verbatim from Приложение 1 (name, unit, sources, trigger, priority) | §8 | MUST | FULL | `matrix_enriched.json` keeps the verbatim `source_pd/rd/id`, `trigger_logic` and `review_priority_matrix_text` |
| MTX-03 | Param code compatible with the ТЗ examples PZ-01 / KR-55 / AR-41 and with GOLD `matrix_code M-001…M-132` | §8.1, §8.2, СХЕМА GOLD | MUST | FULL | `code` = M-xxx; `alias_code` = {PREFIX}-{NN}: PZ-01, KR-55, AR-41, OOS-100, SM-132. The API accepts both |
| MTX-04 | `section` takes values from the §8.1 list (ПЗ, СПЗУ, АР, КР, ИОС1–5, ППМ, ОДИ, ЗУ, ПОС, ПОД, ООС, СМ) | §8.1 | MUST | FULL | Normalized from «Раздел N. X» |
| MTX-05 | `data_type` ∈ {number, string, boolean, coordinate, enum} | §8.1 | MUST | FULL | number 84, enum 24, string 13, boolean 10, coordinate 1. Multi-valued shapes are expressed in `comparison_rule`, not in data_type |
| MTX-06 | `review_priority` HIGH/MEDIUM/LOW is used only for review order, never as a legal action | §8.1, §9.2 | MUST | FULL | Copied from the matrix (106 HIGH, 26 MEDIUM, 0 LOW); `risk_level_default` derived from it; UI disclaimer |
| MTX-07 | Fill sp/gost/fz/other references, which are missing in the xlsx, each with a confidence level | §8.1, §10 #1 | MUST | SIMPLIFIED | 294 references with HIGH/MEDIUM/LOW. LOW and «требует проверки» items are shown with a badge until a norms reviewer verifies them (task T16) |
| MTX-08 | min/max thresholds wherever the trigger or a norm gives a number; editable without recoding | §7 #8, §8.1 | MUST | FULL | 18 params have explicit min/max; others reference `$object.*` (ГПЗУ), `$derived.*` (Normative_Base) or the PD value. Rules read `$min_value` at run time |
| MTX-09 | `regex_pattern` for every param (≤ 255 chars) plus semantic anchors | §9.1 п.2 | MUST | FULL | 132 main + aux regexes; 43/43 checks on real pilot strings pass (including negative cases such as «В 25 местах» and «REI 120»); 4–7 Russian anchors each |
| MTX-10 | Sentence-BERT all-MiniLM-L6-v2 «или совместимые аналоги» for the anchors | §9.1 п.2 | MUST | FULL | all-MiniLM-L6-v2 is English-only. Use `paraphrase-multilingual-MiniLM-L12-v2` (same MiniLM family, 384-dim, Russian), aligned with B04 |
| MTX-11 | `matrix_version` fixed in every run and every protocol | §9.2 п.1, §9.3 п.4, §14.2 | MUST | FULL | Immutable published versions with SHA-256 of the canonical JSON |
| MTX-12 | Applicability check per param before comparison; NOT_APPLICABLE with a mandatory basis | §9.2 п.3; registry rules «NOT_APPLICABLE с обязательным основанием» | MUST | FULL | `applicability_conditions` (JSONLogic + text + positive/negative anchors + `default_applicable`) |
| MTX-13 | Evidence completeness per param → MISSING_EVIDENCE, not a violation | §9.2 п.3, §9.3 п.4 | MUST | FULL | `stages_required` + `source_docs` + `missing_stage_policy` |
| MTX-14 | A pairwise comparison runs when two stages suffice; a missing stage that is not needed → NOT_APPLICABLE | §9.2 п.3 | MUST | FULL | `sufficient_sets` per param; scenario resolver (§3.4) |
| MTX-15 | Behaviour under each scenario (FULL / PD_RD_ONLY / PD_ID_ONLY / RD_ID_ONLY / SINGLE_ONLY / PARTIALLY_LOADED) | §9.2 п.2 | MUST | FULL | This block supplies the per-param stage map; B04 executes it |
| MTX-16 | Output expected_value, actual_value, delta; preliminary CANDIDATE or NEGATIVE_VERIFIED; never auto CONFIRMED_VIOLATION | §9.2 п.3 | MUST | FULL | `on_trigger` / `on_pass` limited to system statuses |
| MTX-17 | NOT_COMPARABLE when sources cannot be compared (unit, height system, price level, λ method, clear vs nominal door width, CRS) | §9.2 п.3 | MUST | FULL | `abstain_if` lists per rule |
| MTX-18 | Formalize `trigger_logic` text into executable rules | §8.1, §9.2 | MUST | FULL | `comparison_rule` DSL (§3.3); all 132 formalized |
| MTX-19 | Unit normalization (м², м³, мм, шт., Марка, Класс, Гкал/ч, ‰, …) | §8.1 unit | MUST | FULL | `unit_canonical` plus a Unit_Conversions dictionary |
| MTX-20 | Risk level (высокий/средний/низкий) per candidate, separate from status | §9.2 | MUST | FULL | `risk_level_default`; B04 adjusts it (e.g. lowered one step when an approved change is likely) |
| MTX-21 | Atomic findings: composite params split into sub-checks | §9.3 п.2, §14.1 | MUST | FULL | 76 composite params → 218 atomic sub-checks with stable `sub_id` |
| MTX-22 | Evidence group = object + param/atomic rule + current sources; element granularity defined | §9.2, §14.1 | MUST | FULL | `element_key` per param (room number, door mark, system+branch, …) |
| MTX-23 | Admin can add, edit and deactivate normative refs and change thresholds without recoding | §7 #8 | MUST | FULL | Cheap because thresholds are data; UI owned by B08 |
| MTX-24 | Normative_Base with effective_from / effective_to | §10 #10 | SHOULD | FULL | Norm effective at the PD approval/expertise date |
| MTX-25 | Logical_Rules seed (id, rule_name, condition, expected, normative_base, is_active) | §9.5, §10 #9 | MUST | FULL | 40 rules (§3.8), merged with B05's 12 |
| MTX-26 | Normative analysis (approach #3): single-stage checks against СП/ГОСТ/СанПиН | §9.5 | MUST | FULL | 39 params have a single-stage check; normative rules in Logical_Rules |
| MTX-27 | Semantic dissonance (approach #2): terminology and room-function taxonomy | §9.5 | MUST | SIMPLIFIED | `term_synonyms` taxonomy seed (function classes) plus embeddings; LLM only if D-01 allows |
| MTX-28 | ML pattern analysis (approach #4) baselines, e.g. «Расход бетона на 20% ниже среднего» | §9.5 | SHOULD | SIMPLIFIED | No historical data. Use in-object ratios (concrete m³ per m² of floor, steel kg per m³ of concrete) against reference ranges with LOW confidence → SUSPICION only |
| MTX-29 | Automatic ИД completeness control | §1.2, §5, Прил. 19 | MUST | FULL | 111-item checklist with applicability, final-check flags and detection anchors |
| MTX-30 | §5 прим. 2: visual check of mandatory requisites on scans (подписи, печати, даты, рег. номера) | §5 | MUST | SIMPLIFIED | Requirement defined here; detection (stamp/signature detector + OCR of dates/numbers) in B01 |
| MTX-31 | §5 прим. 3: stamps «В производство работ» and «Выполнено согласно проекту» on RD sheets in ИД | §5 | MUST | SIMPLIFIED | Anchors and OCR phrase match; item ID19-1 |
| MTX-32 | §5 прим. 4: the hidden-works list in ОД drives the expected АОСР set | §5 | MUST | SIMPLIFIED | PKG-HIDDEN-WORKS: parse the ОД list → dynamic expected items |
| MTX-33 | §5 прим. 1: electronic ИД signed with УКЭП/УНЭП | §5 | SHOULD | SIMPLIFIED | `signature_status` from the registry plus signature-block detection; cryptographic validation out of scope |
| MTX-34 | §6 mapping table encoded | §6 | MUST | FULL | `source_docs.tz6_mapping` |
| MTX-35 | §3: sections 5, 6, 9, 11 required in full for budget-funded objects | §3 note | MUST | FULL | HR-LOG-017 |
| MTX-36 | §4 RD composition vocabulary for document classification | §4 | MUST | FULL | `doc_kind` codes (TEP, GENERAL_DATA, EXPLICATION, SPECIFICATION, VEDOMOST, PLAN, SECTION, …) |
| MTX-37 | Registry `discipline` vocabulary (АР, КР, КЖ, КМ, КМД, ОВ, ВК, НВК, ЭОМ, СС, ГП, ТХ, ГСН, ППР, …) | Registry docx | MUST | FULL | From the normalizer; includes ГСН, which is missing from §3 |
| MTX-38 | The hidden test includes confirmed violations, verified negatives, missing evidence, non-applicable params and revision conflicts; the rules must emit the right status for each | §14.2 | MUST | FULL | Status discipline in the DSL; scenario tests (T17) |
| MTX-39 | Metrics by section and by violation type | §14.3 | MUST | FULL | `violation_type` taxonomy of 16 types on every atomic sub-check |
| MTX-40 | FPR ≤ 0,10 on NEGATIVE_VERIFIED and outdated revisions | §14.3 | MUST | FULL | Rounding-aware tolerance, strict numeric triggers, abstention, POL17 negative regression test |
| MTX-41 | Precision ≥ 0,90: abstain rather than guess | §14.3 | MUST | FULL | `abstain_if`; semantic sub-checks with confidence < 0,8 → SUSPICION |
| MTX-42 | Normative references current as of July 2026 | §2 | MUST | SIMPLIFIED | Edition notes (e.g. СП 4.13130.2013, СП 50.13330 «проверить действующую редакцию»); verification task T16 |
| MTX-43 | Approved change (`approved_change_ref`) surfaced; RD change-log entries mined but not treated as approval | §9.2 п.3, СХЕМА GOLD | MUST | SIMPLIFIED | Change-log mining maps entries to params (UNDMS, LOS3A); approval evidence only from PD corrections or expertise documents |
| MTX-44 | Performance: comparing 132 params ≤ 2 min; NLP per param ≤ 500 ms | §11 #4, #7 | MUST | FULL | The rule engine runs in ms; embeddings cached |
| MTX-45 | Incremental update recomputes only params with new data | §9.2 | MUST | FULL | Dependency index `doc_kind × discipline × stage → params` from `source_docs` |
| MTX-46 | Suspicion fields `normative_base` and `review_priority` come from the rules | §9.5 | MUST | FULL | Every Logical_Rules seed has both |
| MTX-47 | Matrix versioning: published versions are immutable; changes create a draft; audit | §9.4, §7 #9 | MUST | FULL | `matrix_versions` + `matrix.version.published` event |
| MTX-48 | Matrix section numbering reconciled with ПП 87 | §3, §6 | SHOULD | FULL | `pp87_section_no` column |
| MTX-49 | xlsx import/export in the Приложение 1 layout | §8 | SHOULD | FULL | Round-trip for customer experts; good for the demo |
| MTX-50 | Section dictionary for dashboard filters | §7 #7 | SHOULD | FULL | Shared enum |
| MTX-51 | Duplicate params linked and deduplicated (M-040/M-104, M-041/M-105, M-043/M-106, M-050/M-107, M-080/M-108, M-069/M-109, M-021/M-124, M-038/M-121, M-044/M-128) | §8, Приложение 1 | MUST | FULL | `linked_params`; summary count deduplicated by evidence fingerprint |
| MTX-52 | Tier D params (external systems) degrade honestly | §9.2 | MUST | FULL | EXTERNAL_STATUS → MISSING_EVIDENCE «требуются данные АИС ОСИГ / РНИС / КПТС / ГРОО» |
| MTX-53 | Room-level explication diff (the main source of pilot findings) | Pilot ALT79B, DOO25, SOSH25 | MUST | FULL | M-003.b SET_DIFF on `floor+room_number` |
| MTX-54 | Layer-stack comparator | Pilot UNDMS | MUST | FULL | M-044, M-032, M-125, M-128 |
| MTX-55 | ИД-internal tolerance check | Pilot OKT103 (the only CONFIRMED_VIOLATION) | MUST | FULL | M-054.b TOLERANCE_CHECK; sheet tolerance first, then СП 70 |
| MTX-56 | System-label set diff within rooms | Pilot «пояснения» (vent) | SHOULD | SIMPLIFIED | M-078.b, M-079.b, M-077.c; text-layer tokens inside the room region |
| MTX-57 | Every one of the 132 params gets a status in the protocol, including NOT_APPLICABLE | §9.2 п.3 «Для каждого параметра (i) из 132» | MUST | FULL | Coverage view (132 rows) |
| MTX-58 | CV analysis of drawings (scale by dimension line, line detection, distance measurement) for geometric params | §9.1 п.3 | MUST | SIMPLIFIED | 27 tier-C params listed; MVP reads dimension text from the vector layer and demos CV on 1–2 params; otherwise SUSPICION or NOT_COMPARABLE |
| MTX-59 | Linear objects use a different PD composition (ПП 87 п. 3²) | §3 note | SHOULD | SIMPLIFIED | Every param's applicability includes `!object.is_linear` → NOT_APPLICABLE with basis |
| MTX-60 | Out-of-matrix pilot findings (IZM12 pile repair, LOS3A moved door) represented | §9.5, СХЕМА GOLD «либо версия правила» | MUST | FULL | HR-LOG-007 and HR-LOG-038 → SUSPICION with evidence → inspector converts to CANDIDATE |

---

## 3. Proposed design

### 3.1 Components

```
                 ┌──────────────── Matrix Registry (Node API, owner B03 data / B08 UI) ───────────────┐
 xlsx Прил.1 ──► │ import → params (draft) → validate (ajv: comparison_rule, applicability schemas)  │
 matrix_enriched │ → publish matrix_version (canonical JSON + SHA-256, immutable) → event            │
 .json (seed)    │ normative_base / param_normative / logical_rules / dictionaries (scales, units,   │
                 │ term_synonyms, doc_kinds, violation_types) / completeness_templates                │
                 └───────────────┬────────────────────────────────────────────────────────────────────┘
                                 │ matrix.version.published (RabbitMQ)  + GET /matrix/versions/{v}
          ┌──────────────────────┼────────────────────────────┬────────────────────────────┐
          ▼                      ▼                            ▼                            ▼
  Extraction (B01, Python)  Comparison engine (B04, Py)  Hypotheses (B05, Py)        Completeness (B01)
  regex_pattern + anchors   Rule evaluator (this DSL):   Logical_Rules seed,         checklist → expected
  + doc_kind routing →      applicability → stages →     facts catalog,              items → ID_* statuses,
  facts & fragments         comparators → atomiser →     INTERNAL_CONSISTENCY        MISSING_EVIDENCE rows
                            Checks (per atomic sub-check) sub-checks → SUSPICION
```

The block ships **data plus a contract**. Code that executes the rules lives in B04 (comparators), B05 (logical rules) and B01 (completeness, extraction). This block defines what they execute, and owns the dictionaries and the rule evaluator semantics.

### 3.2 Data model

**`params`**: the ТЗ §8.1 fields, exact, plus extensions. Extensions are nullable except where noted and are filled from `matrix_enriched.json`.

| Column | Type | Source | Note |
|---|---|---|---|
| id … updated_at (21 ТЗ fields) | per §8.1 | seed | `code` = `M-001`…`M-132` (GOLD `matrix_code`); `sp_reference`, `gost_reference`, `fz_reference`, `other_normative` = the `references_text` rendering (TEXT) |
| alias_code | VARCHAR(20) UNIQUE | seed | PZ-01 … SM-132 (§3.3) |
| matrix_version | VARCHAR(32) | system | Version a row belongs to (rows are copied per version; see `matrix_versions`) |
| section_matrix_label, matrix_section_no, pp87_section_no | text/int/text | seed | Reconciliation with ПП 87 (§6 contradictions) |
| unit_canonical | VARCHAR(20) | seed | For Unit_Conversions |
| comparison_rule | JSONB NOT NULL | seed | DSL (§3.4); validated by JSON Schema |
| atomic_sub_checks | TEXT[] | derived | `M-042.a`… |
| threshold_source, threshold_note, matrix_trigger_value | text/text/JSONB | seed | Where min/max came from; M-117 keeps the literal matrix value 1,5 |
| stages_required | JSONB | seed | pairs, sufficient_sets, single_stage_check, missing_stage_policy |
| applicability_conditions | JSONB | seed | JSONLogic + text + default + anchors |
| element_key | VARCHAR(64) | seed | Granularity of evidence groups |
| source_docs | JSONB | seed | Normalized `{pd[], rd[], id[], id_checklist_refs[], tz6_mapping}` |
| extraction_method, extraction_methods_all | VARCHAR(20), TEXT[] | seed | TABLE_TEXT, FREE_TEXT_REGEX, SEMANTIC, DRAWING_GEOMETRY, SPEC_TABLE, EXTERNAL_SYSTEM, MANUAL |
| feasibility_tier, feasibility_note | CHAR(1), text | seed | A / B / C / D |
| regex_aux | TEXT[] | seed | Extra patterns: table rows, alternative phrasings |
| semantic_anchors | TEXT[] | seed | Russian anchors; embeddings cached per model |
| references_json | JSONB | seed | Structured references with confidence (the four ТЗ text columns are rendered from this) |
| reference_confidence_min | VARCHAR(8) | derived | Badge in the UI |
| risk_level_default | VARCHAR(16) | derived | высокий / средний |
| linked_params | TEXT[] | seed | Duplicates and related params |
| demo_priority | SMALLINT | seed | 1 = core demo |
| notes | TEXT | seed | Domain notes, ТЗ issues |

**`matrix_versions`** (+): `matrix_version PK` (e.g. `1.1-B03.1+<sha8>`), `base_source` (`Матрица_параметров_редакция1.1.xlsx`, SHA-256), `canonical_sha256` (JCS-canonicalised JSON of all 132 rows plus dictionaries), `status` (DRAFT/PUBLISHED/RETIRED), `created_by`, `published_by`, `published_at`, `change_summary JSONB` (changed codes and fields), `previous_version`. A published version is read-only. Admin edits always create or modify a DRAFT, and every run records the published version it used (MTX-11).

**`normative_base`** (§10 #10 exact + extensions): `id, document_name, document_number, section, parameter_name, min_value, max_value, effective_from, effective_to` + `doc_type` (СП/ГОСТ/ФЗ/СанПиН/ПП/ГПЗУ/МЕСТНЫЙ), `clause`, `unit`, `condition JSONB` (e.g. applies when `object.fire_height_m` is 13–46), `confidence` (HIGH/MEDIUM/LOW), `verified_by`, `verified_at`, `text_excerpt`, `is_active`. The engine resolves `$derived.*` threshold names through this table. For example, `$derived.km_max_for_location` is a lookup by room category and building class, and `$derived.vpv_norm` by purpose and floors. The table is seeded from the JSON references. Rows with numeric thresholds are added in T11.

**`param_normative`** (+): `param_id, normative_id, role` (THRESHOLD / BASIS / METHOD), `sub_id` (which atomic sub-check).

**`logical_rules`** (§10 #9 exact + extensions agreed with B05): `id, rule_name, condition, expected, normative_base, is_active` + `rule_code` (HR-LOG-NNN), `version`, `discovery_method` (LOGICAL_ANALYSIS / SEMANTIC_DISSONANCE / NORMATIVE_ANALYSIS / ML_PATTERN), `applicability`, `severity` (= review_priority), `base_confidence`, `overlaps_matrix_codes`, `message_template`, `normative_confidence`, `verified`.

**Dictionaries** (+, versioned with matrix_version):
- `enum_scales`: CONCRETE_B, STEEL_GRADE, REBAR_CLASS, FIRE_RESISTANCE_DEGREE, CONSTRUCTIVE_FIRE_HAZARD_CLASS, KM_CLASS, ENERGY_CLASS (both the Приказ 399/пр scale A++…G and the old СП 50 scale A++, A+, A, B+, B, C+, C, C-, D, E, with a mapping), RELIABILITY_CATEGORY, EI_LIMIT, FIRE_RESISTANCE_LIMIT_R, CABLE_FIRE_INDEX, WASTE_HAZARD_CLASS. Same order as B04 §3.5.2.
- `unit_conversions`: canonical unit, aliases (м2, кв.м, м²; м3, куб.м; Гкал/ч ↔ кВт ↔ МВт with factor 1 Гкал/ч = 1163 кВт; % ↔ ‰; мм ↔ м; тыс. руб. ↔ руб.).
- `term_synonyms`: room names → `function_class` (MAIN/USEFUL, AUXILIARY, TECHNICAL, SERVICE_STAFF, RESIDENTIAL, COMMON, SANITARY, STORAGE, STORAGE_HAZARDOUS, UNSPECIFIED); abbreviations («с/у», «ПУИ», «тех.помещение», «ИТП», «МОП», «ЛК»); the homoglyph map (В/B, С/C, А/A, Е/E, К/K, М/M, Н/H, О/O, Р/P, Т/T, Х/X), applied **only** to class and mark tokens.
- `vocabularies`: FENCE_TYPE, DOOR_SWING, PIPE_MATERIAL, SEWER_PIPE_MATERIAL, DEMOLITION_METHOD, LUMINAIRE_TECH (each with an adverse-transition table: «LED → люминесцентные» is adverse, the reverse is not; «чугун → ПВХ» is adverse).
- `doc_kinds`: the PD/RD kinds TEP, GENERAL_DATA, TEXT, EXPLICATION, SPECIFICATION, VEDOMOST, PLAN, PLAN_ANNOTATION, SECTION, FACADE, NODE, SCHEME, CALCULATION, CABLE_JOURNAL, ENERGY_PASSPORT, ESTIMATE, CALENDAR_PLAN, STROYGENPLAN, TECH_CARD, TRPO, DRAWING, TABLE. The ИД kinds AOSR, AKT_OSV, AKT_OSV_KONSTR, AKT_OSV_SETEY, AKT_ISPYTANIY, AKT_PRIEMKI, ISP_GEO_SCHEME, ISP_SCHEME, ISP_SCHEME_SETEY, ISP_DRAWINGS, JOURNAL_OZHR, JOURNAL_SPECIAL, QUALITY_DOCS, LAB_OR_MEASUREMENT, BTI_TECHPLAN, ZOS, RNV, TEP_SPRAVKA, ENERGY_PASSPORT_FACT, KS2, KS3, CONTRACT, TECH_CONNECTION_ACT, ADMISSION_ACT, EXPERT_CONCLUSION, WASTE_DOCS, WAYBILLS, PHOTO, EXTERNAL_SYSTEM, AKT_OBSLEDOVANIYA, AKT_PROVERKI, AKT_RAZBIVKI_OSEY.
- `violation_types` (§3.11).
- **`completeness_templates`** (+, schema owned by B01 W10): seeded 1:1 from `id_completeness_checklist.json` (item_code = `id`, parent_code = `parent`, applicability = JSONLogic, match = {doc_kind, detection_anchors}).

### 3.3 Alias-code and section scheme

The number part stays the matrix number, so the ТЗ examples match exactly (KR-55 = M-055, AR-41 = M-041, PZ-01 = M-001). The format is `{PREFIX}-{NN}`, zero-padded to 2 digits. Params ≥ 100 get 3 digits, e.g. OOS-100 and SM-132. Every alias fits VARCHAR(20).

| Matrix section | `section` | Prefix | ПП 87 section (ТЗ §3) | Params |
|---|---|---|---|---|
| Раздел 1. ПЗ | ПЗ | PZ | 1 | M-001…M-023 |
| Раздел 2. СПЗУ | СПЗУ | SPZU | 2 | M-024…M-039 |
| Раздел 3. АР | АР | AR | 3 | M-040…M-053 |
| Раздел 4. КР | КР | KR | 4 | M-054…M-067 |
| Раздел 5. ИОС1…ИОС5 | ИОС1…ИОС5 | IOS1…IOS5 | 5 | M-068…M-080 |
| Раздел 6. ПОС | ПОС | POS | 7 | M-081…M-089 |
| Раздел 7. ПОД | ПОД | POD | 7 (в составе ПОС, ТЗ §6) | M-090…M-097 |
| Раздел 8. ООС | ООС | OOS | 8 | M-098…M-101 |
| Раздел 9. ППМ | ППМ | PPM | 9 | M-102…M-114 |
| Раздел 10. ОДИ | ОДИ | ODI | 11 | M-115…M-123 |
| Раздел 11. ЗУ | ЗУ | ZU | — (not in the §3 table) | M-124…M-131 |
| Раздел 12. СМ | СМ | SM | 12 | M-132 |

The DB `code` stays M-xxx because it is the GOLD `matrix_code` and the Приложение 1 identifier. `alias_code` is shown next to it («AR-41 · M-041»). API lookups accept either form.

### 3.4 Comparison-rule DSL (for Module 2; admin-tunable for Module 8)

**Design goals.** One JSON document per param. It is machine-executable and human-renderable into Russian («Если в РД/ИД ширина двери в свету < 0,9 м → Кандидат»). Thresholds are **references**, never literals, wherever an admin should be able to change them. Composite params are pre-split into atomic sub-checks. Every rule states the conditions under which it must abstain.

#### 3.4.1 Shape (JSON Schema sketch)

```json
{
  "$id": "iai://schemas/comparison_rule.json",
  "oneOf": [ {"$ref": "#/$defs/atomic"}, {"$ref": "#/$defs/composite"} ],
  "$defs": {
    "composite": { "required": ["rule_type","combine","sub_checks"],
      "properties": { "rule_type": {"const": "COMPOSITE"}, "combine": {"const": "ATOMIC_FINDINGS"},
        "sub_checks": {"type":"array","items":{"allOf":[{"$ref":"#/$defs/atomic"},
                       {"required":["sub_id","title"]}]}} } },
    "atomic": { "required": ["rule_type","violation_type","on_trigger","on_pass"],
      "properties": {
        "rule_type": {"enum": ["PAIRWISE_DELTA","NORMATIVE_BOUND","ORDINAL_COMPARE","ENUM_CHANGE","SET_DIFF",
                               "LAYER_STACK","PRESENCE","TOLERANCE_CHECK","GEOMETRY_OFFSET","GEOMETRY_CONTAINMENT",
                               "RATIO_BOUND","INTERNAL_CONSISTENCY","EXTERNAL_STATUS","SEMANTIC_DIFF"]},
        "violation_type": {"$ref": "iai://dict/violation_types"},
        "compare": {"type":"array","items":{"properties":{"expected":{"enum":["PD","RD"]},"actual":{"enum":["RD","ID"]}}}},
        "evaluate_on": {"type":"array","items":{"enum":["PD","RD","ID"]}},
        "operator": {"enum": ["ABS_DELTA_GT","REL_DELTA_GT","OUTSIDE_BOUNDS","ORDINAL_LOWER","ORDINAL_NE","NE",
                              "SET_DIFF","LAYER_DIFF","PRESENT_IN_EXPECTED_ABSENT_IN_ACTUAL","ABS_DEVIATION_GT_TOLERANCE",
                              "DIST_GT","INTERSECTS_FORBIDDEN_ZONE","RATIO_LT","SUM_NE","FORMULA_NE","STATUS_NOT_OK",
                              "SEMANTIC_CONTRADICTION"]},
        "direction": {"enum": ["ANY","DECREASE","INCREASE","DOWNGRADE"]},
        "tolerance": {"properties":{"abs":{"type":["number","null"]},"rel":{"type":["number","null"]},
                                    "rounding":{"enum":["SOURCE_PRECISION","NONE"]}}},
        "bounds": {"properties":{"min":{"$ref":"#/$defs/thrRef"},"max":{"$ref":"#/$defs/thrRef"},
                   "conditional":{"type":"array","items":{"properties":{"if":{"$ref":"iai://jsonlogic"},
                                  "min":{"type":"number"},"max":{"type":"number"}}}}}},
        "scale": {"$ref": "iai://dict/enum_scales"}, "vocabulary": {"type":"string"},
        "element_key": {"type":["string","null"]}, "detect": {"type":"array"}, "compare_attributes": {"type":["array","null"]},
        "attribute_tolerance": {"type":["object","null"]},
        "numerator": {"type":"string"}, "denominator": {"type":"string"}, "min_ratio": {"type":"number"}, "min_abs": {"type":["number","null"]},
        "tolerance_source": {"enum":["SHEET_THEN_NORMATIVE","SHEET_ONLY","NORMATIVE_ONLY"]},
        "max_distance_m": {"type":"number"}, "external_system": {"type":"string"}, "degrade_to": {"const":"MISSING_EVIDENCE"},
        "min_confidence": {"type":"number"}, "low_confidence_status": {"const":"SUSPICION"},
        "abstain_if": {"type":"array","items":{"enum":["UNIT_MISMATCH","VALUE_NOT_FOUND","AMBIGUOUS_VALUE","UNKNOWN_SCALE_VALUE",
            "ELEMENT_KEY_UNRESOLVED","SHEETS_NOT_MATCHED","ASSEMBLY_NOT_MATCHED","TOLERANCE_NOT_FOUND","CRS_MISMATCH",
            "HEIGHT_SYSTEM_MISMATCH","PRICE_LEVEL_MISMATCH","VAT_BASIS_MISMATCH","METHOD_MISMATCH","GEOMETRY_NOT_EXTRACTED",
            "EXTERNAL_DATA_UNAVAILABLE","TEXT_NOT_FOUND"]}},
        "on_trigger": {"enum":["CANDIDATE","SUSPICION"]}, "on_pass": {"const":"NEGATIVE_VERIFIED"} } },
    "thrRef": {"oneOf":[ {"type":"number"}, {"type":"string","pattern":"^FR$"},
                          {"type":"string","pattern":"^\\$(min_value|max_value|object\\.[a-z_]+|derived\\.[a-z_]+)$"} ]}
  }
}
```

**Threshold references**
- `$min_value` / `$max_value`: read `params.min_value/max_value` of the **published version in use**. This is the Module 8 knob: an admin edits the number, publishes, and the next run uses it. No code change.
- `$object.<fact>`: an object-specific limit from the ИРД (ГПЗУ): `max_kz_gpzu`, `max_height_gpzu`, `min_greening_gpzu`, `max_density_gpzu`, `tu_power_limit_kw`. Entered on the object card or extracted from ГПЗУ/ТУ documents. When absent, the sub-check is NOT_APPLICABLE with the basis «предельное значение ГПЗУ/ТУ не предоставлено».
- `$derived.<name>`: a lookup in `normative_base` with its `condition` and effective dates, e.g. `km_max_for_location`, `vpv_norm`, `compartment_area_max`, `ro_windows_norm`, `keo_norm`, `ei_required_for_barrier`, `grounding_r_max`, `detector_spacing_max`, `playground_norm_area`. Without a matching active row → NOT_COMPARABLE («норматив не задан администратором»).
- `bounds.conditional`: JSONLogic conditions over object or element facts that override the default. Example M-030: min 3,5 / 4,2 / 6,0 м by `object.fire_height_m`, following СП 4.13130.2013 п. 8.6 (MEDIUM).

#### 3.4.2 Rule types → evaluation semantics

| rule_type | Needs | Trigger condition (→ `on_trigger`) | Pass (→ NEGATIVE_VERIFIED) | Typical params |
|---|---|---|---|---|
| PAIRWISE_DELTA | expected, actual (same element) | `ANY`: \|Δ\| > ε; `DECREASE`: Δ < −ε; `INCREASE`: Δ > ε; REL: \|Δ\|/\|e\| > rel | otherwise | M-001, M-002.a, M-024, M-058.a, M-132 |
| NORMATIVE_BOUND | one value per evaluated stage | value < min or > max (after conditional override); `FR` = the required index set | inside bounds | M-030.a, M-041.a, M-118, M-109.a |
| ORDINAL_COMPARE | scale tokens | rank(actual) worse than rank(expected) | equal or better | M-015, M-022, M-055, M-103.a |
| ENUM_CHANGE | vocabulary tokens | adverse transition per the vocabulary table (or any change for `free_text`) | same, or a non-adverse change | M-072.a, M-075, M-130 |
| SET_DIFF | keyed lists | missing / added / changed attributes, per `detect` | sets equal within attribute tolerance | M-003.b, M-011, M-052, M-078.b |
| LAYER_STACK | ordered layer lists per assembly | LAYER_REMOVED / THICKNESS_DECREASED / MATERIAL_CHANGED / LAYER_ADDED | identical within rounding | M-044, M-032, M-125, M-128 |
| PRESENCE | element flag per stage | present in expected, absent in actual | present in both, or absent in both | M-039, M-053, M-122, M-123 |
| TOLERANCE_CHECK | measured deviations + tolerance | \|deviation\| > tolerance (sheet first, then Normative_Base) | all within tolerance | M-054.b, M-058.b |
| GEOMETRY_OFFSET | coordinates in one CRS | distance > max | ≤ max | M-034, M-064.b |
| GEOMETRY_CONTAINMENT | geometries | intersects a forbidden zone | no intersection | M-035.a, M-081.a (fallback SUSPICION) |
| RATIO_BOUND | two params | num/den < min_ratio, or num < min_abs | otherwise | M-038.a (≥ 10 %, ≥ 1) |
| INTERNAL_CONSISTENCY | values of one stage | Σ ≠ total, or formula mismatch → **SUSPICION** | consistent | M-002.b, M-003.c, M-010.b, M-019.c |
| EXTERNAL_STATUS | adapter data | status not OK | OK | M-098…M-101; without data → MISSING_EVIDENCE |
| SEMANTIC_DIFF | texts or configurations | contradiction with confidence ≥ 0,8 → CANDIDATE; lower → SUSPICION | equivalent | M-087, M-051.c, M-063.b |

**ε (rounding-aware tolerance).** ε = max(abs_tol, rel_tol·|e|, 0,5·10^(−d)), where d is the smaller number of displayed decimals of the two values. This is the same formula as B04 §3.5.1. It makes «Расхождение > 0» (M-001) behave sensibly: 11,68 vs 11,7 counts as equal.

**Trigger policy.** A numeric trigger from the matrix is applied **strictly**: «> 1 %», «> 5 %», «> 2 %», «> 10 %», «> 0,5 м». Below the trigger the result is NEGATIVE_VERIFIED, and the delta is shown on the card. A qualitative trigger («изменение», «сокращение», «исключение», «снижение», «подмена») means any change beyond ε. This protects FPR (§14.3) and still catches ALT79B/SOSH25/DOO25 through the room-level sub-check. B04's draft uses a «DEVIATION» policy instead: a candidate on any deviation, with the risk lowered. That needs a decision; see D-02.

#### 3.4.3 Evaluation order (literally §9.2 п.3)

For each param (i) and each atomic sub-check (j):

1. **Applicability.** Evaluate `applicability_conditions.logic` with three-valued logic over object facts.
   - FALSE → `NOT_APPLICABLE`, basis = rule text plus the fact's source fragment, e.g. «Газоснабжение не предусмотрено — ПЗ, стр. 12, bbox…».
   - UNKNOWN and `default_applicable = false` → `NOT_APPLICABLE`, with basis «признаки применимости не выявлены в загруженных документах; подтвердить применимость». The §9.2 inspector action for NOT_APPLICABLE is exactly «Подтвердить применимость при необходимости».
   - UNKNOWN and `default_applicable = true` → treat as applicable.
2. **Evidence completeness.** For each pair in `stages_required.pairs`, check that the stage is present and that at least one source document of the required `doc_kind` exists.
   - A stage that is absent and not required by any `sufficient_set` usable in the scenario → that pair is `NOT_APPLICABLE`.
   - A required source that is absent → `MISSING_EVIDENCE`, following `missing_stage_policy = PHASE_BASED` (§3.5).
3. **Currency and comparability.** Revision selection and sheet matching are B01/B04 logic.
   - A revision conflict → `CLARIFICATION_REQUIRED`, and the rule is not run.
   - Sheets not matched → `NOT_COMPARABLE`.
4. **Subject comparison.** Run the comparator.
   - Any `abstain_if` condition hit → `NOT_COMPARABLE` with that reason code.
   - Otherwise → `on_trigger` or `on_pass`.
   - Every triggered element or attribute becomes one atomic finding, and the finding id carries `sub_id`.
5. **Linked params.** When a sub-check of a linked param (e.g. M-040 ↔ M-104) produces the same evidence fingerprint (same files, pages, bbox, element key), both codes get the finding with `linked_finding_id`. The summary «число нарушений» counts the fingerprint once.

**Mapping to B04's Appendix A notation** (so the two drafts merge without loss):

| This DSL | B04 notation |
|---|---|
| PAIRWISE_DELTA ANY | ANY |
| PAIRWISE_DELTA DECREASE | DEC |
| PAIRWISE_DELTA INCREASE | INC |
| PAIRWISE_DELTA REL | REL>x% |
| PAIRWISE_DELTA INCREASE with `max=$object/PD value` | LIM |
| NORMATIVE_BOUND | MIN v / MAX v, axis N |
| ORDINAL_COMPARE | ORD↓ |
| ENUM_CHANGE | SEM (substitution) |
| PRESENCE | PRES |
| LAYER_STACK | LAYERS |
| TOLERANCE_CHECK | TOL |
| GEOMETRY_OFFSET | DIST>x |
| SET_DIFF / GEOMETRY_CONTAINMENT / SEMANTIC_DIFF on configurations | KL / GEO |
| `compare` pairs PD→RD, RD→ID (PD→ID) | axes DC, EX |
| `evaluate_on` a single stage | axis N |

#### 3.4.4 Worked examples (verbatim from the JSON)

- **M-041 (AR-41)**, from the ТЗ example «< 0.9 м»:
  - `M-041.a`: NORMATIVE_BOUND min `$min_value` (0,9) on RD/ID per `door_mark`. NOT_COMPARABLE if only the nominal opening (door mark «ДН 21-10») is known, because the nominal size is not the clear width.
  - `M-041.b`: PAIRWISE_DELTA DECREASE PD→RD→ID.
- **M-055 (KR-55)**, «Понижение класса»: ORDINAL_COMPARE on CONCRETE_B per `structural_element`. The regex `(?<![А-ЯЁа-яёA-Za-z])[BВ](7[.,]5|10|…|100)(?![\d.,])|(?i:класс\w*\s+(?:бетона\s+)?)[BВ]\s(\d{2,3}…)` catches «B25» and «В25» (the pilot mixes Latin and Cyrillic on one sheet). It does **not** match «В 25 местах» or «в 2 этапа».
- **M-003**, the pilot workhorse:
  - `.a` DECREASE of the usable area total;
  - `.b` SET_DIFF on `floor+room_number` with attributes {function, area_m2} and flag USABLE_TO_TECHNICAL;
  - `.c` INTERNAL_CONSISTENCY Σ rooms = «Итого по этажу» → SUSPICION. B05 notes this fires on the ALT79B PD: Σ 2795,04 vs «Общий итог» 2797,27.
- **M-054**: `.a` SET_DIFF of axis spacing PD→RD; `.b` TOLERANCE_CHECK on ИД only (OKT103: tolerances 15 / ±12 / 20 мм, facts +491/+552, +980/+537, +201/+349 мм → CANDIDATE, which the expert confirmed).
- **M-030**: NORMATIVE_BOUND with `$min_value` = 4,2 plus a conditional override by `object.fire_height_m`, and DECREASE PD→RD.
- **M-038**: RATIO_BOUND M-038 / M-037 ≥ 0,10 and ≥ 1 place (181-ФЗ ст. 15, HIGH), plus DECREASE.

### 3.5 Stage and scenario resolution

`stages_required.pairs` lists the comparisons the param supports. `sufficient_sets` says which stage pairs are enough. `single_stage_check` says what can still be done with a single stage. Per scenario:

| Scenario (§9.2) | What runs for a param with pairs PD-RD, RD-ID, PD-ID | Missing-stage marking |
|---|---|---|
| FULL | All pairs: PD→RD (design change) and RD→ID (execution); PD→ID only when RD lacks the element | — |
| PD_RD_ONLY | PD→RD + single-stage checks on RD | RD-ID and PD-ID pairs: NOT_APPLICABLE when `object.phase = DESIGN`; MISSING_EVIDENCE when phase ∈ {CONSTRUCTION, COMPLETED} and the param has ИД sources (PHASE_BASED policy) |
| PD_ID_ONLY | PD→ID («фактически против утверждённого») + single-stage checks on ID | RD pairs: MISSING_EVIDENCE (RD always exists before construction) |
| RD_ID_ONLY | RD→ID + single-stage checks | PD pairs: MISSING_EVIDENCE |
| SINGLE_ONLY | Only `single_stage_check` sub-checks (39 params) and INTERNAL_CONSISTENCY / TOLERANCE_CHECK | All pairwise sub-checks: MISSING_EVIDENCE (or NOT_APPLICABLE by phase) |
| PARTIALLY_LOADED | Pairs whose source doc kinds are present; the rest per the rules above | MISSING_EVIDENCE for the absent doc kinds, listed in the completeness table (1) |

Pair sets across the 132 params: 113 use all three pairs. 7 are PD-RD only: M-024 (the ИД side needs a haul registry) and M-081, M-083, M-085, M-086, M-090, M-097 (ПОС/ПОД; the RD analogue is the ППР). 7 are PD-RD/RD-ID: M-054, M-058…M-062 (КР) and M-068. 3 are RD-ID only (M-099, M-100, M-101). 2 are PD-ID/RD-ID (M-094, M-098).

**PHASE_BASED policy.** `object.phase` (DESIGN / CONSTRUCTION / COMPLETED) comes from the object card or the РиН case and decides whether a missing ИД stage is «not applicable» or «missing evidence». Without this rule, a design-stage check would flood the protocol with MISSING_EVIDENCE and blur a hidden-test class.

### 3.6 Applicability and the object-profile facts catalog

These are the canonical fact names. They are shared with B01 (completeness templates) and B05 (logical rules). B05 uses `object.floors_above_ground`, and we adopt its names where they overlap.

| Fact | Type | Primary source (extraction) | Negative anchors (→ FALSE) |
|---|---|---|---|
| purpose | enum RESIDENTIAL/PUBLIC/INDUSTRIAL/MIXED | ПЗ «назначение», ТЭП, name («ДОО», «СОШ», «жилой дом») | — |
| functional_class | Ф1.1…Ф5.x | ПЗ/ППМ «класс функциональной пожарной опасности» | — |
| is_linear | bool | ПЗ, composition of PD (ПП 87 п. 3²) | — |
| works_type | NEW/RECONSTRUCTION/CAPITAL_REPAIR | Object card, ГПЗУ/permit | — |
| phase | DESIGN/CONSTRUCTION/COMPLETED | Object card / РиН | — |
| floors_above_ground, fire_height_m, height_m | number | ТЭП (M-007, M-008), ППМ | — |
| has_underground_part, has_underground_parking | bool | ТЭП, explication («подземная автостоянка»), sections | «подземная часть отсутствует» |
| has_gas_supply | bool | ПЗ «Газоснабжение», composition (ГСН) | «газоснабжение не предусмотрено», «электроплиты» |
| has_demolition, has_earthworks | bool | Composition (ПОД), ПОС | «снос не предусмотрен» |
| has_lifts, has_escalators, has_mgn_platforms | bool | Explication, spec, ТХ | — |
| has_cranes, has_temp_buildings | bool | ПОС | «без применения кранов» |
| has_steel_structures, has_monolithic_concrete, has_precast, has_timber, has_masonry, has_piles, foundation_type | bool/enum | КР ОД | — |
| has_smoke_control, has_internal_fire_water, has_fire_protection_systems, has_fire_protection_coating | bool | ППМ, ОВ, ВК | «ВПВ не требуется» |
| has_ventilation_mech, has_heating, has_water_supply, has_sewer, has_power, has_lowcurrent, ext networks … | bool | ИОС composition | — |
| has_site_works, has_roof_works, has_facade_works | bool | Composition, ПОС | — |
| budget_funded, estimate_required_by_contract | bool | Object card / РиН | — |
| max_kz_gpzu, max_height_gpzu, min_greening_gpzu, max_density_gpzu, tu_power_limit_kw, site_area | number | ГПЗУ/ТУ (ИРД) or manual entry | — |

Every fact carries `value, stage, sources[] {file_id, sha256, page, bbox}, confidence, set_by (SYSTEM/INSPECTOR)`. The inspector can override a fact; the override is audited and triggers an incremental re-run.

### 3.7 Tier statistics, demo priorities and per-section strategy

**Tier definitions**
- **A**: a reliable MVP from tables or text with regex.
- **B**: automatable with moderate effort: reconstructing tables from drawings, per-element matching, OCR of tables, layer stacks.
- **C**: needs drawing CV or semantic reasoning; partial result in MVP.
- **D**: external systems; honest degradation.

| Tier | Count | Params |
|---|---|---|
| A | 38 | 001 002 004 005 006 007 008 009 010 012 013 014 016 017 018 019 020 021 022 023 025 026 027 037 038 052 055 056 057 069 103 109 112 121 124 130 131 132 |
| B | 63 | 003 011 015 024 028 029 032 034 036 039 041 044 045 046 048 049 050 053 054 058 059 060 061 062 064 066 067 068 070 071 072 073 074 075 076 077 079 080 082 086 088 089 092 093 094 095 105 107 108 110 111 113 115 117 118 120 122 123 125 126 127 128 129 |
| C | 27 | 030 031 033 035 040 042 043 047 051 063 065 078 081 083 084 085 087 090 091 096 097 102 104 106 114 116 119 |
| D | 4 | 098 099 100 101 |

| Section | A | B | C | D | Total | Dominant extraction strategy |
|---|---|---|---|---|---|---|
| ПЗ | 20 | 3 | 0 | 0 | 23 | ТЭП tables (PD ПЗ/ПЗУ, RD ОД/ГП) with a table parser; free-text regex on ПЗ (ТУ, energy class, fire characteristics); XML техплан for ИД |
| СПЗУ | 5 | 7 | 4 | 0 | 16 | Ведомости (покрытия, МАФ, озеленение) as tables; coordinates tables; dimensions and radii from vector text on plans (C) |
| АР | 1 | 8 | 5 | 0 | 14 | Ведомость заполнения проёмов, ведомость отделки (ГОСТ 21.501 forms), layer callouts; widths and heights from dimension text plus geometry (C) |
| КР | 3 | 9 | 2 | 0 | 14 | ОД/спецификации (classes, grades), ВРС totals, section marks «К1 500×600»; ИД tolerance tables (OCR on scans) |
| ИОС1–5 | 1 | 11 | 1 | 0 | 13 | Specifications (ГОСТ 21.110), cable journals, «Характеристика систем» tables; per-room system tokens for configuration diffs |
| ПОС | 0 | 4 | 5 | 0 | 9 | Calendar plan/resources tables (B); stroygenplan geometry (C) → SUSPICION fallback |
| ПОД | 0 | 4 | 4 | 0 | 8 | Volume and waste tables; methods by semantic classification; zones by geometry |
| ООС | 0 | 0 | 0 | 4 | 4 | External adapters (АИС «ОСИГ», РНИС, Мобильный КПТС, ГРОО); documentary partial check (ТРПО list vs talons) |
| ППМ | 3 | 6 | 4 | 0 | 13 | EI/FR tokens (A), system tables ДУ/ПД (A), ВПВ calc (B); compartments and hydrant coverage by geometry (C) |
| ОДИ | 1 | 6 | 2 | 0 | 9 | Specifications (lifts, handrails, tactile, call systems) = presence; widths by geometry |
| ЗУ | 3 | 5 | 0 | 0 | 8 | Energy passport tables, λ/Ro tokens, insulation layer thickness, meter nodes |
| СМ | 1 | 0 | 0 | 0 | 1 | ССР total with a price-level and VAT guard |

**Demo priority 1 (16 params), the core of the jury demo**

| Param | Why it is in the demo |
|---|---|
| M-003 | Pilot ALT79B, DOO25, SOSH25, POL17 |
| M-002 | Shows the contrast with M-003 below the 1 % trigger |
| M-011 | Pilot POL16 |
| M-044 | Pilot UNDMS |
| M-054 | Pilot OKT103, the confirmed violation |
| M-041 (AR-41), M-055 (KR-55), M-001 (PZ-01) | The ТЗ §8.2 examples |
| M-007, M-009 | Easy wins, with the M-009 height-system guard |
| M-022, M-023, M-057 | Ordinal downgrades |
| M-069, M-109, M-103 | Fire-safety tokens that appear in the pilot text layer (EI 30/60, EIS 60) |

**Demo priority 2 (30 params):** M-004 M-008 M-010 M-012 M-013 M-014 M-019 M-021 M-030 M-037 M-038 M-040 M-050 M-052 M-056 M-058 M-062 M-071 M-077 M-078 M-079 M-098 M-111 M-112 M-113 M-118 M-125 M-126 M-129 M-132. The vent pilot maps to M-077/M-078/M-079. M-098 shows tier-D degradation. M-038 shows the cross-param ratio. M-126 is backed by a real RD change-log entry, «Изменилось значение λ утеплителя».

**Pilot → parameter mapping**

| Pilot finding | Status | Param / rule | Sub-check | Note |
|---|---|---|---|---|
| ALT79B-V01 | CANDIDATE | M-003 (+ M-002 context) | M-003.b | M-002.a gives NEGATIVE (+0,49 % < 1 %) |
| UNDMS-V01 | CANDIDATE | M-044 | LAYER_STACK: LAYER_REMOVED | RD «Лист изменений» records it: change-log mined, **not** an approved change |
| IZM12-V01 | CANDIDATE | HR-LOG-007 (out of matrix; related M-058) | SUSPICION → inspector converts | The pile-repair scheme exists in ИД but not in РД |
| LOS3A-V01 | CANDIDATE | HR-LOG-038 (change log) + configuration diff (door position) | SUSPICION → CANDIDATE | «В квартире 2.4.1 подвинулась дверь» appears in the RD change log |
| OKT103-V01 | CONFIRMED_VIOLATION | M-054 (links M-060, M-061) | M-054.b TOLERANCE_CHECK | Single-stage ИД check |
| POL16-V01 | CANDIDATE | M-011 (alt M-003) | M-011.b | Apartment triples «21,34 / 31,31 / 34,06»; B04 maps it to M-003 (D-12) |
| DOO25-V01 | CANDIDATE | M-003 (+ M-013 context) | M-003.b | Rooms 135–150 |
| SOSH25-V01 | CANDIDATE | M-003 (+ M-002) | M-003.b ELEMENT_ADDED | Room 1.109, 18,2 м² |
| POL17-N01 | NEGATIVE_VERIFIED | M-003, M-011 | all | FP regression guard |
| VENT-P01 | CANDIDATE | M-079 | M-079.b | Vent chamber 012 configuration |
| VENT-P02 | CANDIDATE | M-077 | M-077.c | Warm-floor loops missing in МГН rooms 267/270/271/272 |
| VENT-P03 | CANDIDATE | M-078 | M-078.b | Branches В2.4–В2.10 and В3.1–В3.2 missing or changed |

### 3.8 Normative references: policy and core list

**Policy**
- Every reference carries `confidence`:
  - **HIGH**: the document identity is certain and the clause is either not given or well known.
  - **MEDIUM**: the document is certain, the clause or edition is likely but should be checked.
  - **LOW**: the document or clause is uncertain; it carries «требует проверки».
- We never state a precise clause at HIGH unless we are sure.
- The UI shows a badge. Protocol text renders LOW references as «(требует проверки)».
- `normative_base.effective_from/effective_to` selects the edition in force at the PD approval date. When the approval date is unknown, the edition in force on the check date is used, and a note is added.

**Core documents** (identity HIGH): 123-ФЗ; 384-ФЗ; 261-ФЗ; 181-ФЗ; 89-ФЗ; ГрК РФ; ПП РФ № 87; Приказ Минстроя № 344/пр; ГОСТ Р 21.101-2020; ГОСТ 21.110-2013; ГОСТ 21.501-2018; СП 1.13130.2020; СП 2.13130.2020; СП 3.13130.2009; СП 6.13130.2021; СП 7.13130.2013; СП 8.13130.2020; СП 10.13130.2020; СП 484.1311500.2020; СП 486.1311500.2020; СП 17.13330.2017; СП 30.13330.2020; СП 42.13330.2016; СП 51.13330.2011; СП 52.13330.2016; СП 54.13330.2022; СП 59.13330.2020; СП 60.13330.2020; СП 63.13330.2018; СП 70.13330.2012; СП 126.13330.2017; СП 16.13330.2017; СП 28.13330.2017; СП 45.13330.2017; СП 48.13330.2019; СП 62.13330.2011; СП 82.13330.2016; СП 104.13330.2016; СП 113.13330.2016; СП 256.1325800.2016; ГОСТ 31565-2012; ГОСТ 26633-2015; ГОСТ 18105-2018; ГОСТ 34028-2016; ГОСТ 5781-82; ГОСТ Р 53307-2009; ГОСТ Р 53301-2013; ГОСТ Р 53295-2009; ПУЭ; СО 153-34.21.122-2003; СанПиН 1.2.3685-21; СанПиН 2.3/2.4.3590-20; СП 2.4.3648-20; ТР ТС 011/2011.

**Edition caveats** (MEDIUM, «проверить действующую редакцию на 07.2026»):
- СП 4.13130.2013: a new edition may have replaced it.
- СП 50.13330: 2012 or an actualized edition.
- ГОСТ 27772-2021 and ГОСТ 23166-2021: the edition year.
- СП 118.13330.2022: the edition year.
- ПП 87: point numbering after the 17.01.2025 edition.

**Clause-level items to verify first**, because they appear in demo params:

| Clause | Used by |
|---|---|
| СП 1.13130.2020 п. 4.2.5 (exits: 1,9 м height, 0,8 м width) | M-041, M-042, M-105 |
| СП 1.13130.2020 п. 4.3.4 (corridors 1,2 / 1,0 м, height 2,0 м) | M-040, M-104 |
| СП 4.13130.2013 п. 8.6 (fire passages 3,5 / 4,2 / 6,0 м) | M-030 |
| СП 70.13330.2012 табл. 5.10 (tolerances) | M-054 |
| 123-ФЗ ст. 87, 88, 89, 90, 134 (табл. 28) | Fire-safety params |
| 181-ФЗ ст. 15 (10 % МГН places) | M-038, M-121 |
| 261-ФЗ ст. 11 and 13 | M-021, M-124, M-129 |

### 3.9 Logical_Rules seed (Module 5, 40 rules)

The codes merge with B05's HR-LOG-001…012, which we keep, and continue with 013…040.

- `discovery_method`: L = LOGICAL_ANALYSIS, S = SEMANTIC_DISSONANCE, N = NORMATIVE_ANALYSIS.
- Every output is **SUSPICION** until evidence is bound and the inspector decides (§9.5).
- The «Conf.» column is the confidence of the normative basis.

| Code | M | Condition → Expected | Facts / sources | Normative basis (conf.) | Prio | Pilot / demo |
|---|---|---|---|---|---|---|
| HR-LOG-001 | L | floors_above_ground > 10 → a lift exists in RD (explication/spec/shaft) | M-007; element index | ТЗ §9.5 example; СП 54.13330.2022 lift requirements (the ТЗ's «п. 7.1.3» is LOW) | HIGH | Synthetic (reproduces the ТЗ JSON) |
| HR-LOG-002 | L | Upper residential floor level − first floor level ≥ 12 м → lift | Section elevations | СП 54.13330.2022, section 4 (MEDIUM; clause to verify) | HIGH | Synthetic |
| HR-LOG-003 | L | fire_height_m > 28 → lift for fire brigades | M-008; spec | СП 4.13130.2013 (LOW clause); ГОСТ Р 53296-2009 (MEDIUM) | HIGH | Synthetic |
| HR-LOG-004 | L | Underground parking → АУПТ and ДУ present in ВК/ОВ | has_underground_parking | СП 486.1311500.2020 (HIGH doc); СП 7.13130.2013 (HIGH doc) | HIGH | Synthetic |
| HR-LOG-005 | L | Σ explication rows = explication total (\|Δ\| ≤ max(0,05 м², 0,05 %)) | Explication table | Internal consistency (ГОСТ Р 21.101-2020, MEDIUM) | MEDIUM | **Fires on ALT79B PD** |
| HR-LOG-006 | L | Σ apartment areas = «Итого»; number of apartments = ТЭП | Spec of apartments; M-010 | Internal consistency | MEDIUM | POL16 / LOS3A tables |
| HR-LOG-007 | L | ИД has a scheme/act for repair/strengthening/defect correction → an RD document or approved_change_ref exists | ИД titles; RD ведомость | ГрК РФ ст. 52 (MEDIUM); Приказ 344/пр (HIGH doc) | HIGH | **IZM12-V01** |
| HR-LOG-008 | L | ИД executive scheme: \|deviation\| ≤ declared tolerance | ИД sheet | СП 70.13330.2012 (MEDIUM) | HIGH | **OKT103** (routed to M-054.b when mapped) |
| HR-LOG-009 | L | Every АОСР date ≥ approval date («В производство работ») of the referenced RD revision | Act dates; registry | Приказ 344/пр (LOW clause) | HIGH | Synthetic |
| HR-LOG-010 | L | An ИД act references an RD revision that is SUPERSEDED/CANCELLED | Act text; registry chain | ТЗ §9.1 «Устаревшая редакция не может использоваться как эталон» (HIGH) | HIGH | Synthetic |
| HR-LOG-011 | L | Cross-references («см. лист N») point to sheets absent from the ведомость/registry | Notes; ВР | ГОСТ Р 21.101-2020 (MEDIUM) | LOW | ALT79B RD notes |
| HR-LOG-012 | L | ТЭП plausibility: height / floors ∈ [2,7; 4,5] м (residential) | M-007, M-008 | Plausibility only (no norm) | LOW | Synthetic |
| HR-LOG-013 | L | Residential, top floor level > 28 м → ≥ 2 lifts, one with a cabin ≥ 2100 мм deep | Levels; spec | СП 54.13330.2022 (MEDIUM; clause to verify) | HIGH | Synthetic |
| HR-LOG-014 | N | Fire passage width ≥ 3,5 / 4,2 / 6,0 м by fire_height_m (≤ 13 / 13–46 / > 46) | M-008, M-030 | СП 4.13130.2013 п. 8.6 (MEDIUM) | HIGH | Conditional bound shown in the admin |
| HR-LOG-015 | L | fire_height_m > 28 → smoke-free stair cells (Н1/Н2/Н3) and smoke control | ППМ text; ОВ | СП 1.13130.2020 / СП 7.13130.2013 (MEDIUM docs; LOW clauses) | HIGH | Synthetic |
| HR-LOG-016 | L | Every ПД section/subsection (ИОС1–6, ТХ, ППМ) → matching main RD set in the ведомость основных комплектов | Composition ПД; ВО/ВС | ГОСТ Р 21.101-2020 (MEDIUM); ТЗ §4 (HIGH) | MEDIUM | Completeness of RD |
| HR-LOG-017 | L | budget_funded → ПД sections 5, 6, 9, 11 present in full | Object card; composition | ТЗ §3 note (HIGH); ПП РФ № 87 (MEDIUM) | HIGH | Direct ТЗ rule |
| HR-LOG-018 | L | budget_funded → section СМ present; M-132 applicable | Object card | ПП РФ № 87 (MEDIUM); ГрК ст. 8.3 (MEDIUM) | MEDIUM | — |
| HR-LOG-019 | L | Demolition in scope → section ПОД and ППР на демонтаж present; M-090…M-097 applicable | Composition; ПОС | ТЗ §6 row 7 (HIGH); ГрК ст. 55.30–55.31 (LOW) | HIGH | — |
| HR-LOG-020 | N | Public building (Ф2–Ф4) with sanitary rooms → ≥ 1 universal cabin for МГН | functional_class; explication | СП 59.13330.2020 (MEDIUM) | HIGH | — |
| HR-LOG-021 | N | Entrance level differs from the pavement by > 0,014 м → ramp or lift/platform | Sections; ОДИ | СП 59.13330.2020 (MEDIUM) | HIGH | — |
| HR-LOG-022 | N | Stairs on an МГН route → tactile warning indicators before the flight | Plans; spec | ГОСТ Р 52875-2018 (MEDIUM); СП 59.13330.2020 (MEDIUM) | MEDIUM | — |
| HR-LOG-023 | L | ДУ/ПД systems present → power by reliability category I and FR-rated cables | M-015, M-109, M-112 | СП 6.13130.2021 (MEDIUM); ГОСТ 31565-2012 (HIGH doc) | HIGH | — |
| HR-LOG-024 | L | Duct crosses a fire barrier (wall/slab with REI/EI) → ОЗК with EI ≥ required | ОВ plans; ППМ | СП 7.13130.2013 (MEDIUM) | HIGH | — |
| HR-LOG-025 | L | Load-bearing steel in a building of I–III degree → fire protection that ensures the required R | M-022, M-066 | 123-ФЗ ст. 87 (MEDIUM); СП 2.13130.2020 (HIGH doc) | HIGH | — |
| HR-LOG-026 | N | Residential rooms and kitchens: ceiling height ≥ 2,5 м | Sections; explication | СП 54.13330.2022 (MEDIUM); СанПиН 2.1.3684-21 (MEDIUM) | MEDIUM | **The ТЗ §9.5 example (2,4 vs 2,5)** |
| HR-LOG-027 | N | Living rooms and kitchens: КЕО ≥ norm (0,5 % for residential) | КЕО calc | СанПиН 1.2.3685-21 (MEDIUM) | MEDIUM | — |
| HR-LOG-028 | L | Absolute mark of 0.000 identical across all RD sets (АР, КР, ОВ, ВК …) | M-009 per set | Internal consistency | HIGH | Cheap, high value |
| HR-LOG-029 | L | Concrete class of one element identical across the sheets/sets of one stage (ОД vs spec vs node) | M-055 per sheet | Internal consistency | HIGH | UNDMS sheet has «B25» and «В25» |
| HR-LOG-030 | L | Floors in ТЭП = number of above-ground floor plans in АР | M-007; sheet titles | Internal consistency | MEDIUM | — |
| HR-LOG-031 | S | Room function changes to hazardous storage («Техническое» → «Склад ГСМ») → a category per СП 12.13130.2009 and matching fire measures must exist | term_synonyms STORAGE_HAZARDOUS | СП 12.13130.2009 (HIGH doc; MEDIUM content) | HIGH | **The ТЗ §9.5 semantic example** |
| HR-LOG-032 | L | ИД: the АОСР for concreting of an element is dated ≥ the АОСР for its reinforcement (and formwork) | АОСР dates, element | Приказ 344/пр (LOW clause) | MEDIUM | Synthetic |
| HR-LOG-033 | L | Lift in RD → ИД item 15 (technical inspection act, ТР ТС 011/2011 declaration, passport) | has_lifts | Appendix 19 п. 15 (HIGH); ТР ТС 011/2011 (HIGH) | HIGH | Checklist link |
| HR-LOG-034 | L | Platform for disabled people in RD → ИД item 16 (act per Приказ Ростехнадзора № 425) | has_mgn_platforms | Appendix 19 п. 16 (HIGH) | HIGH | Checklist link |
| HR-LOG-035 | L | ДОО/школа (Ф1.1/Ф4.1) → ИД item 13.5 (microclimate and illumination) | functional_class | Appendix 19 п. 13.5 (HIGH) | MEDIUM | DOO25, SOSH25 objects |
| HR-LOG-036 | L | Every position of «Перечень скрытых работ» in ОД РД → an АОСР exists in ИД | ОД list; ИД | ТЗ §5 прим. 4 (HIGH) | HIGH | — |
| HR-LOG-037 | L | RD sheets in ИД carry the stamps «В производство работ» and «Выполнено согласно проекту» | Stamp OCR | ТЗ §5 прим. 3 (HIGH) | HIGH | — |
| HR-LOG-038 | S | An entry in the RD «Лист регистрации изменений» → the changed sheets exist, and a basis (PD correction/approval) is referenced; otherwise SUSPICION mapped to params by keywords | Change-log table | ГОСТ Р 21.101-2020, section on making changes (MEDIUM) | HIGH | **LOS3A, UNDMS, λ entry** |
| HR-LOG-039 | L | Apartments of the same type and the same geometry keep the same areas | Apartment records | Internal consistency (same_type_same_geometry) | MEDIUM | **POL16** |
| HR-LOG-040 | L | Height > 100 м, span > 100 м, cantilever > 20 м, or underground depth > 15 м → a unique object (special requirements, СТУ) must be declared in ПД | M-008; sections | ГрК РФ ст. 48.1 ч. 2 (MEDIUM) | MEDIUM | Synthetic |

**Serialized form** (B05 AST, in the ТЗ columns `condition` / `expected` as JSON text), example HR-LOG-014:

```json
{"rule_code":"HR-LOG-014","version":1,"rule_name":"Ширина пожарного проезда по высоте здания",
 "discovery_method":"NORMATIVE_ANALYSIS",
 "condition":{"all":[{"fact":"object.fire_height_m","op":">","value":13},{"fact":"object.fire_height_m","op":"<=","value":46}]},
 "expected":{"all":[{"fact":"param.M-030.value","op":">=","value":4.2,"stage":["RD","ID"]}]},
 "normative_base":"СП 4.13130.2013, п. 8.6 (MEDIUM — проверить действующую редакцию)",
 "severity":"HIGH","base_confidence":0.8,"overlaps_matrix_codes":["M-030"],
 "message_template":"Ширина проезда {param.M-030.value} м меньше 4,2 м при пожарно-технической высоте {object.fire_height_m} м."}
```

### 3.10 ИД completeness checklist (summary of `id_completeness_checklist.json`)

- **Contents:** 111 items. There are 94 leaves and 17 groups. They come from Appendix 19 items 1–16 with all subitems. Item 15 was split into 15.1–15.3. TZ5-06 (замечания застройщика) and TZ5-13 / 13.1 / 13.2 (ОЖР, special journals) come from ТЗ §5 rows that are absent from Appendix 19.
- **Fields per item:** `pr344_item` (the §5 row number, 1–13), `doc_kind`, `applicability` (JSONLogic + text + `default_applicable`; 35 items default to not applicable, e.g. свайное поле, газ, лифты, ДОУ/школы, ЭМП, мусоропроводы), `check_phase` / `recommended_final_check` (37 items from the closing paragraph of Appendix 19), `detection_anchors`, `required_requisites` (scan: подписи, печати, даты, рег. номера; electronic: УКЭП/УНЭП; item 1 adds both stamps), `related_matrix_params`.
- **Package requirements:** PKG-REGISTRY (the mandatory machine-readable registry, 14 fields; without it → CLARIFICATION_REQUIRED), PKG-SIGNATURE, PKG-SCAN-REQUISITES, PKG-RD-STAMPS, PKG-HIDDEN-WORKS.
- **Status rules:**
  - Item: FOUND / FOUND_LOW_QUALITY / MISSING (→ MISSING_EVIDENCE) / NOT_APPLICABLE (with basis) / APPLICABILITY_UNKNOWN.
  - Group: all applicable children found.
  - Aggregate: ID_UPLOADED / ID_PARTIAL / ID_MISSING, using the phase rule and `check_type` INTERIM vs FINAL.
- **Cross-links:** every matrix param's `source_docs.id_checklist_refs` resolves to checklist ids. Validated: 0 unresolved.

### 3.11 Violation-type taxonomy (the §14.3 metric dimension «по типам нарушения»)

| Type | Meaning | Atomic sub-checks |
|---|---|---|
| NUMERIC_DECREASE | Value decreased (thickness, width, diameter, count of places) | 45 |
| NORM_BOUND_VIOLATION | Single-stage value outside a normative/matrix bound | 38 |
| NUMERIC_DEVIATION | Change in either direction beyond the trigger | 18 |
| CONFIG_CHANGE | Configuration or composition changed (rooms, branches, units, methods) | 18 |
| ELEMENT_REMOVED | Element present in expected, absent in actual | 18 |
| NUMERIC_INCREASE | Value increased beyond the limit (height, power, cost, λ) | 17 |
| CLASS_DOWNGRADE | Ordinal downgrade (B, С, A, EI, КМ, energy class, category) | 16 |
| COUNT_DECREASE | Number of items reduced | 10 |
| MATERIAL_SUBSTITUTION | Material or product substituted | 8 |
| ZONE_INTRUSION | Object inside a forbidden zone | 8 |
| EXTERNAL_NONCOMPLIANCE | External-system status not OK | 6 |
| TOLERANCE_EXCEEDED | ИД deviation beyond tolerance | 5 |
| INTERNAL_INCONSISTENCY | A document contradicts itself (→ SUSPICION) | 4 |
| LAYER_CHANGE | Assembly layer removed, thinned or changed | 4 |
| GEOMETRY_OFFSET | Point displaced beyond the limit | 2 |
| RATIO_VIOLATION | Share below the minimum | 1 |

B04's discrepancy codes (VALUE_CHANGED, FUNCTION_CHANGED, ELEMENT_ADDED/MISSING, TOTAL_CHANGED, LAYER_REMOVED, TOLERANCE_EXCEEDED, POSITION_SHIFTED, CONFIGURATION_CHANGED) are finer-grained **per atomic finding**. Our `violation_type` is the per-rule metric bucket. Both are stored.

### 3.12 REST endpoints (OpenAPI 3.0; `/api/v1`; the admin UI is B08, the data contract is here)

| Method | Path | Request | Response | Role |
|---|---|---|---|---|
| GET | /matrix | `?version=&section=&tier=&priority=&active=&q=` | `{matrix_version, sha256, params:[ParamSummary]}` | inspector, admin, ml |
| GET | /matrix/params/{code} | `code` = `M-041` or `AR-41` | full Param (all §8.1 fields + extensions) + `rule_ru` (human-readable rendering) | all |
| PATCH | /matrix/params/{code} | `{min_value?, max_value?, is_active?, references_json?, comparison_rule?, applicability_conditions?, regex_pattern?, semantic_anchors?, reason}` | updated DRAFT Param; 409 if no draft is open; 422 on schema errors (ajv) | admin |
| POST | /matrix/params/{code}/dry-run | `{process_id? , facts?: {...}, stage_values?: {...}}` | `{status, sub_results:[{sub_id,status,expected,actual,delta,epsilon,reason}], trace}` (RPC to Python) | admin, ml |
| GET | /matrix/versions | — | `[MatrixVersion]` | all |
| POST | /matrix/versions | `{from_version}` | new DRAFT | admin |
| GET | /matrix/versions/{v}/diff | `?against=` | field-level diff per code | admin |
| POST | /matrix/versions/{v}/publish | `{comment}` | PUBLISHED (immutable), emits event | admin |
| POST | /matrix/versions/{v}/retire | `{reason}` | RETIRED; runs keep the reference | admin |
| GET | /matrix/export | `?version=&format=xlsx\|json` | file (Приложение 1 columns + enrichment sheet) | admin |
| POST | /matrix/import | multipart xlsx | DRAFT with a validation report | admin |
| GET | /dictionaries/{name} | name ∈ enum_scales, units, term_synonyms, doc_kinds, violation_types, vocabularies | dictionary (versioned) | all |
| GET/POST/PATCH | /normative-base[/{id}] | NormativeBase | … | admin (write), all (read) |
| GET/POST/PATCH | /logical-rules[/{code}] | LogicalRule (B05 AST) | … | admin |
| POST | /logical-rules/{code}/test | `{process_id\|facts}` | evaluation trace | admin, ml |
| GET | /completeness/templates | `?version=` | checklist tree | all |
| GET | /processes/{id}/coverage | — | 132 rows `{code, alias, section, status, sub_statuses[], basis, evidence_group_id}` (B04 fills the data) | inspector |

Every PATCH or POST writes an `audit_log` entry: action, code, field, old → new, reason, user, ip, user_agent (§12 #4).

### 3.13 RabbitMQ messages

| Exchange / key | Producer → consumer | Payload |
|---|---|---|
| `iai.config` (topic) `matrix.version.published` | Node → comparison, extraction, hypotheses, protocol renderer | `{matrix_version, canonical_sha256, rules_version, changed_codes[], published_by, published_at}`. Consumers reload their caches; running jobs keep the version they started with |
| `iai.config` `normative.updated` | Node → comparison | `{normative_id, param_codes[], effective_from, effective_to, is_active}` |
| `iai.config` `logical_rules.updated` | Node → hypotheses | `{rule_code, version, is_active}` |
| `iai.config` `completeness.templates.published` | Node → ingestion | `{template_version, sha256}` |
| `iai.rpc` `matrix.dryrun.request` (reply_to + correlation_id) | Node → Python comparison worker | `{matrix_version or draft_payload, code, facts, stage_values}` → reply `{sub_results, trace}`; timeout 5 s |

### 3.14 UI screens (specified here, built by B08)

1. **«Матрица контроля (132)»**: a table with columns alias · code · section · parameter · unit · tier badge (A/B/C/D) · priority · rule (Russian rendering) · thresholds · references with confidence badges · active. Filters cover section, tier, priority and «требует проверки». It exports to xlsx.
2. **Param detail / edit**: the rule tree shows atomic sub-checks with their Russian renderings. The threshold editor writes to the draft. The dry-run panel takes test values or a pilot process. It also shows the references and the linked params.
3. **Versions**: the list of versions, a diff view, and publish / retire actions.
4. **Coverage view per protocol** (co-owned with B04/B07): 132 rows with status chips, and the basis of each NOT_APPLICABLE / MISSING_EVIDENCE / NOT_COMPARABLE status. This is the jury's «all 132 are handled» proof.
5. **ИД completeness**: the checklist tree with status per item (found / missing / n/a with reason) and links to the files.

### 3.15 Libraries

We give major versions only. Patch versions are pinned at scaffold time per the architecture.

| Where | Library | Purpose |
|---|---|---|
| Python | pydantic 2.x | DSL models; also generates the JSON Schema |
| Python | jsonschema 4.x | Seed validation in CI |
| Python | rapidfuzz 3.x | Typo-tolerant names |
| Python | shapely 2.x | Geometry for GEOMETRY_* rules |
| Python | sentence-transformers 3.x + `paraphrase-multilingual-MiniLM-L12-v2` | Anchors; the «совместимый аналог» of all-MiniLM-L6-v2 |
| Python | openpyxl 3.x | xlsx import/export |
| Python | in-house evaluators | JSONLogic subset (~150 LOC) and the B05 AST (~300 LOC). No `eval` |
| Node | ajv 8 | Validating `comparison_rule` / `applicability` in the API |
| Node | exceljs 4 | xlsx export |
| Node | json-logic-js 2.x | Admin preview only; Python is authoritative |

---

## 4. Interfaces with other blocks

The sibling reports in `docs/analysis/` were read for alignment. Some siblings (e.g. `00_architecture.md`) use the label **«B03» for the Verification block**. In this document, B03 means *matrix-domain*, and the orchestrator should normalize the numbering.

| Block | Consumes from B03 | Produces for B03 | Contract / notes |
|---|---|---|---|
| **Ingestion & registry (01)** | `source_docs.doc_kind` and `discipline` vocabularies (file classification); `id_completeness_checklist.json` → the `completeness_templates` seed (01's W10 already plans a JSONLogic `applicability` and a `match` object, which maps 1:1); `regex_pattern`, `regex_aux`, `semantic_anchors` for extraction routing; the object-profile facts catalog | Extracted facts with provenance (file_id, sha256, page, bbox); per-param extraction candidates as `evidence_fragments`; registry fields (`approval_status`, `signature_status`); `object.phase` | Fact names are those of §3.6. `doc_kind` codes are a frozen enum per matrix_version |
| **Comparison & protocol (04)** | `comparison_rule` (the seed for its `Param_Rules` / `comparison_spec` JSONB), `stages_required`, `applicability_conditions`, `element_key`, `linked_params`, dictionaries (`enum_scales`, `unit_conversions`, `term_synonyms`, vocabularies), `violation_type`, `risk_level_default` | `checks` per atomic sub-check; the coverage view | **Merge rule:** B04's Appendix A and our JSON describe the same 132 params. B03's JSON is the canonical *domain* seed (thresholds, applicability, norms, pilot mapping). B04 owns the *runtime* models (pydantic) and adds `value_shape` and the `DEVIATION/TRIGGER` policy. §3.4.3 gives the notation mapping. Open items R-1 to R-3 below |
| **Free hypothesis search (07)** | The Logical_Rules seed (40), facts catalog, `term_synonyms` function classes, INTERNAL_CONSISTENCY sub-checks (M-002.b, M-003.c, M-010.b, M-019.c emit SUSPICION) | Suspicions; `change_facts` from change-log mining | B05's AST is used for `logical_rules.condition/expected` (R-4) |
| **Verification (05)** | Reason-code needs: `PARAM_NOT_APPLICABLE` (with the applicability basis), `WITHIN_TOLERANCE`, `APPROVED_CHANGE`, `UNIT_MISMATCH`; the `linked_params` hint (a decision on M-040 suggests the same decision on M-104, never auto-applied) | Inspector overrides of object facts (e.g. «газоснабжение есть») → incremental re-run | Decisions stay atomic per `sub_id` |
| **Feedback / weekly ML report (06)** | `section`, `violation_type`, `feasibility_tier` as metric dimensions (recall per mandatory category, FPR per type); `matrix_version` | Weekly statistics of rejections per param and sub-check → tuning suggestions (thresholds, anchors) → a matrix DRAFT | A threshold change always goes through a matrix version, never through model retraining |
| **Frontend / dashboard / normative admin (08)** | The Params CRUD schema, the `rule_ru` renderer templates per `rule_type`, confidence badges, the `normative_base` schema with `condition` and effective dates, the version workflow | Admin edits → DRAFT → publish | 08 plans react-querybuilder → JSONLogic for Logical_Rules; see R-4 |
| **Platform / integration / audit (09)** | `matrix.version.published` and the other config events; audit events for admin changes | Audit log, monitoring of rule-evaluation latency | — |

**Reconciliation items for the orchestrator** (not decided unilaterally):

| # | Item | Drafts | Recommendation |
|---|---|---|---|
| R-1 | Candidate policy below a numeric trigger | B04: a DEVIATION candidate with lowered risk. B03: strict trigger, NEGATIVE_VERIFIED with the delta shown | B03's strict policy for numeric triggers (FPR ≤ 0,10) and DEVIATION for qualitative triggers. The pilot findings are still caught by M-003.b. See D-02 |
| R-2 | POL16 mapping | B04: M-003. B03: M-011 (apartment-level) | Primary M-011 with `alt_param_codes: ["M-003"]` on the card. See D-12 |
| R-3 | Tier vocabularies | B04 T1/T2/T3 (implementation depth). B03 A/B/C/D (feasibility) | Keep both: `demo_priority=1` ≈ T1; D maps to T3 (mocked) |
| R-4 | Expression language | JSONLogic (01, 08, and B03 applicability) vs B05's AST (`all/any/not`, `fact/op/value`, aggregates) | JSONLogic for applicability and threshold conditions over scalar facts; B05's AST for Logical_Rules, which need collections and aggregates. Both evaluators in Python, shared fact resolver. react-querybuilder can emit both through custom exporters |
| R-5 | Block numbering «B03» | 00_architecture uses B03 = Verification | The orchestrator normalizes the numbering |
| R-6 | Out-of-matrix pilot findings (IZM12, LOS3A) | B05: HR-LOG-007. B04: change-log mining | Keep them as rule codes (GOLD allows «версия правила свободного поиска»). See D-08 |

---

## 5. Too complex or risky: simplification that still meets the letter of the ТЗ

| # | Item | Why hard | Simplification (letter of the ТЗ preserved) |
|---|---|---|---|
| 1 | **27 tier-C params** (widths, radii, zones, door swing, compartments, hydrant coverage, crane zones) | Need drawing CV: scale detection, line recognition, room polygons, geometry of zones. Pilot pages vary (A4–A0, vector or raster) | (a) Read dimension **text** from the vector layer near the element (most widths are printed as «1500»). (b) GEOMETRY_CONFIG diff of tokens per room region (B04 §3.5.7). (c) A minimal CV demo on 1–2 params (e.g. corridor width via dimension text and scale), which satisfies §9.1 п.3 «масштабирование по размерной линейке, распознавание линий и измерение расстояний». (d) Otherwise SUSPICION or NOT_COMPARABLE with an honest reason. The result never becomes a false CANDIDATE |
| 2 | **Context-dependent thresholds** (fire height, functional class, number of evacuees, one- or two-way traffic, ГСОП) | The norm depends on facts that are often absent | Default = the matrix literal. `bounds.conditional` overrides it only when the fact is known. Unknown fact + borderline value → NOT_COMPARABLE instead of a guessed CANDIDATE |
| 3 | **Exact normative clause numbers** in front of an expert jury (Мосгосстройнадзор) | A wrong clause number undermines credibility | Confidence badges, «требует проверки», and effective-date versioning. One verification pass on the demo params (T16) upgrades them to HIGH |
| 4 | **Tier D** (АИС «ОСИГ», РНИС/ГЛОНАСС, Мобильный КПТС, ГРОО/licences, ККУД) | No access; systems not described | EXTERNAL_STATUS adapter interface plus a mock adapter for the demo (a JSON fixture). Without data → MISSING_EVIDENCE «требуются данные …». The document-based part is kept (M-101.a: ТРПО vs talons) |
| 5 | **Semantic comparisons** (construction methods, node details, fire-wall continuity) | No labelled data; an LLM may be disallowed (D-01) | Vocabulary classifiers (enum) + multilingual embeddings; confidence < 0,8 → SUSPICION; the inspector decides |
| 6 | **Area methodology differences** (design vs техплан / Росреестр measurement rules) | ИД areas follow the Росреестр rules (Приказ П/0393); design areas follow СП 54/118 appendices; a legitimate delta is expected | Compare like with like. When the method differs (detected by anchors) → NOT_COMPARABLE with the reason METHOD_MISMATCH, never a CANDIDATE |
| 7 | **Door clear width vs nominal opening** (M-041, M-105, M-117) | Door marks such as «ДН 21-10» give the opening size, not the clear width | Use the clear width only when printed; otherwise NOT_COMPARABLE. An optional deduction table (admin-configurable) comes later |
| 8 | **ИД aggregates** (soil by waybills, headcount by ККУД, material consumption from КС-2) | Summation across many documents | PD↔RD comparison in MVP; the ИД side → MISSING_EVIDENCE unless a summary document exists |
| 9 | **218 atomic sub-checks** | Scope | A generic comparator per rule_type (14 types), not per param. Extraction depth follows `demo_priority` and tier |
| 10 | **Change-log mining** (RD «Лист регистрации изменений») | Free-text entries | Keyword and anchor classifier → param codes; the output only attaches evidence or creates a SUSPICION. It is **never** treated as `approved_change_ref` |
| 11 | **ML pattern analysis** (§9.5 #4) | No history | In-object ratios against reference ranges (LOW confidence) → SUSPICION only; `Quantity_History` accumulates for later |

---

## 6. ТЗ contradictions and ambiguities for this block

| # | Issue | Reference | Recommended interpretation |
|---|---|---|---|
| 1 | The code format of the §8.1/§8.2 examples (PZ-01, KR-55, AR-41) differs from Приложение 1 and GOLD (M-001…M-132) | §8.1, §8.2, СХЕМА GOLD | `code` = M-xxx (GOLD `matrix_code`); `alias_code` in the ТЗ style; the API accepts both |
| 2 | Matrix section numbering ≠ ПП 87 numbering in §3: ПОС is ПД section 7 but matrix section 6; ОДИ is 11 vs 10; ЗУ (energy efficiency) is absent from the §3 table; БЭ, ТХ and ИН appear in §3 but not in the matrix; ПОД is a separate matrix section but «в составе ПОС» in §6 | §3, §6, Прил. 1 | Keep both numberings (`matrix_section_no`, `pp87_section_no`); the UI shows the matrix section names |
| 3 | «ЗУ» in the §8.1 section list usually means «земельный участок», but the matrix uses it for energy efficiency, and СПЗУ is separate | §8.1, §6 | Keep «ЗУ» as the code (letter of the ТЗ); the UI label reads «ЗУ — энергоэффективность и учёт» |
| 4 | M-006 «Строительный объём (надземный)» has the trigger «изменение общего числа этажей»; M-005 (volume) has a trigger about depth of foundation | Прил. 1 | Implement both aspects as atomic sub-checks (M-006.a/b, M-005.a/b) |
| 5 | Duplicated params: M-040/M-104, M-041/M-105, M-043/M-106, M-050/M-107, M-080/M-108, M-069/M-109 (partial), M-021/M-124, M-038/M-121 (partial), M-044/M-128 (partial) | Прил. 1 | `linked_params`; evaluate once; report under both codes; count once in the summary (D-07) |
| 6 | Thresholds that look normatively wrong or are ranges: M-117 «< 1.5 м» door width (СП 59 requires ≥ 0,9 м clear); M-048 riser ≤ 150 / tread ≥ 300 for all stairs (МГН-type values; general stairs are allowed about ≤ 220 / ≥ 250 by СП 1.13130, LOW); M-031 «10–12 м»; M-047 «1.5–1.8 м»; M-084 «3.5–4.5 м»; M-116 «1.5–1.8 м»; M-119 «< 1.5 м» (the 2020 cabin is larger, LOW); M-121 «< 3.5 м» (СП 59: 3,6 м) | Прил. 1 | Seed defaults per D-03…D-06; keep the literal matrix value in `matrix_trigger_value` or `threshold_note`; ask the organizers |
| 7 | M-018 (gas) needs discipline ГСВ/ГСН, which is absent from the §3 list ИОС1–5 (in ПП 87 gas supply is its own subsection) | §3, Прил. 1 | Add discipline «ГСН» to the registry vocabulary; M-018 applicability = `has_gas_supply` |
| 8 | ИОС5 = СС «включая АПС/СОУЭ» (§3), while M-080 (ИОС5) duplicates M-108 (ППМ) | §3, Прил. 1 | Linked params (item 5) |
| 9 | §8.1 `data_type` has no list, geometry or layered types, yet explications, layers and configurations are multi-valued | §8.1 | Keep the ТЗ `data_type` per param (the attribute's type); the shape lives in `comparison_rule` (SET_DIFF, LAYER_STACK) |
| 10 | §8.1 allows one min/max per param, but M-042 (2,0 м corridors / 1,9 м doors) and M-048 (150 / 300 мм) have two thresholds | §8.1 | `min_value`/`max_value` hold the primary; the secondary is stored as a literal in the sub-check or in `normative_base` (still admin-editable through the rule editor) |
| 11 | The matrix uses only HIGH/MEDIUM priorities; §8.1 also allows LOW | §8.1 | No action; LOW is kept for future params and Logical_Rules |
| 12 | «Технический план БТИ» is outdated terminology: техпланы are prepared by кадастровые инженеры under Росреестр rules | Прил. 1 (M-001…M-012) | doc_kind BTI_TECHPLAN matches «технический план» (XML/PDF) regardless of the author |
| 13 | §9.2 says «для каждого параметра (i) из 132», but §3 notes that линейные объекты have a different composition | §3 note, §9.2 | Applicability `!object.is_linear` → NOT_APPLICABLE with basis for linear objects |
| 14 | Appendix 19's closing paragraph references п. 11.2.8, which does not exist (the list ends at 11.2.7) | Прил. 19 | Recorded in `source_inconsistencies`; no item created |
| 15 | §14.3 requires metrics «по типам нарушения» but defines no taxonomy | §14.3 | Our `violation_type` taxonomy (16 types, §3.11), shared with B06 |
| 16 | Energy class scales differ: the old СП 50.13330 table (A++…E with B+, C+, C-) vs Приказ 399/пр (A++…G) | M-021, M-124 | ENERGY_CLASS scale with both variants and a mapping; an unknown token → NOT_COMPARABLE |
| 17 | The service is «сверка трёх массивов», yet the only CONFIRMED pilot violation (OKT103) is **ИД-internal**: deviation vs tolerance on one sheet | §1.1, Прил. 1 примеры | TOLERANCE_CHECK single-stage sub-checks (M-054.b, M-058.b …) are part of the matrix params |
| 18 | «АИС "ОСИГ"» is not expanded anywhere; Moscow systems for construction and demolition waste are usually referred to as «ОСС» | M-098, M-099, §6 | Keep the matrix name; ask the customer (data need #6) |
| 19 | Typo in M-099: «Верфикация» | Прил. 1 | Keep verbatim in `parameter_name` (import fidelity); corrected label in the UI |
| 20 | M-041/M-105 «< 0,9 м» vs the general СП 1.13130 minimum of 0,8 м | Прил. 1, СП 1.13130 | The matrix threshold is the customer's choice (stricter); keep 0,9 and explain it in `threshold_note` |
| 21 | §9.1 names all-MiniLM-L6-v2, which is English-only | §9.1 п.2 | Use `paraphrase-multilingual-MiniLM-L12-v2` as the «совместимый аналог» (MTX-10) |

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation | Impact |
|---|---|---|---|---|
| D-01 | Are external or cloud LLM APIs allowed (152-ФЗ / data localization)? | (a) Local models only; (b) a cloud LLM behind a flag for semantic diffs and explanations; (c) a Russian-hosted LLM (e.g. YandexGPT or GigaChat) | (a) by default, (b)/(c) optional behind a flag and never on the critical path | Tier-C semantic sub-checks (M-087, M-091, M-051.c, M-063.b, M-102.c, change-log classification). Without an LLM they fall back to vocabularies and embeddings, and more of them end as SUSPICION |
| D-02 | Candidate policy below a numeric matrix trigger (e.g. M-002 +0,49 % < 1 %) | (a) Strict: NEGATIVE_VERIFIED with the delta shown; (b) Deviation: CANDIDATE with lowered risk (B04 draft) | (a) for numeric triggers, «any change» for qualitative ones; the pilot is still caught by M-003.b | FPR on the hidden negatives (≤ 0,10) vs recall. Strict protects the mandatory FPR threshold |
| D-03 | Range thresholds (M-031 10–12, M-047 1,5–1,8, M-084 3,5–4,5, M-116 1,5–1,8) | Lower bound; upper bound; conditional | Conditional where the norm defines the condition (M-116 by traffic direction, M-030 by height); otherwise the lower bound | FP vs FN on geometric params |
| D-04 | M-117 door width for МГН «< 1,5 м» (likely an error) | (a) The matrix literal 1,5; (b) 0,9 м per СП 59 (1,2 м for entrances) | (b) by default, showing «порог Матрицы 1,5 м» in the admin and in `threshold_note`; ask the organizers | With 1,5 м almost every door is flagged: mass false positives |
| D-05 | M-048 riser ≤ 150 / tread ≥ 300 мм | (a) All stairs; (b) only МГН routes and external stairs; general stairs use СП 1.13130 values | (b), configurable | FP on ordinary stairs |
| D-06 | M-121 parking width «< 3,5 м» vs СП 59 3,6 м | 3,5 (matrix) / 3,6 (norm) | 3,5 (the matrix is lenient, so fewer FP); note the norm | Minor |
| D-07 | Counting duplicate params | (a) Report both and count twice; (b) report both, count once; (c) keep only one | (b); the primary code follows the evidence discipline (АР sheet → M-040; ППМ calculation → M-104) | Double-counted FPs if (a) |
| D-08 | Out-of-matrix pilot findings (IZM12 pile repair, LOS3A moved door) | (a) Rule codes (HR-LOG-007, HR-LOG-038) as SUSPICION → CANDIDATE; (b) force the nearest matrix code | (a), and ask how the hidden test labels such findings | Recall on the hidden test when it contains out-of-matrix groups |
| D-09 | Which code is primary in the UI and API | M-xxx or alias | Store M-xxx; display «AR-41 · M-041»; accept both | Cosmetic, but visible to the jury (§8.2) |
| D-10 | Who verifies the normative references (clause numbers) before the demo | (a) A domain expert from the team or a consultant with КонсультантПлюс/Техэксперт access; (b) ship with confidence badges only | (a) for the ~40 references used by demo params; (b) for the rest | Credibility with an expert jury |
| D-11 | Unify the expression language (R-4) | JSONLogic only; B05 AST only; both | Both, with clear scopes (applicability = JSONLogic, Logical_Rules = AST) | Admin UX and evaluator effort |
| D-12 | POL16 primary param | M-011 or M-003 | M-011, alt M-003 on the card | GOLD matching on the hidden test |
| D-13 | ГПЗУ-based limits (КЗ, height, greening, density) | (a) Manual entry on the object card; (b) extraction from an uploaded ГПЗУ PDF | (a) in MVP; (b) later | Four sub-checks are NOT_APPLICABLE without it |

---

## 8. Data needed

| # | What | Why | Fallback if never received |
|---|---|---|---|
| 1 | **Приложение № 2** (sample output protocol, «обязательно для исполнения») | Protocol field names and the order of sections, including how params and sub-checks are listed | Build from §9.2 п.4 (5 tables + evidence card fields) and the pilot legend; make the layout configurable |
| 2 | At least one **full ПД/РД/ИД set** (ТЭП tables, ОД, specifications, ведомости, cable journals) | 38 tier-A params have no source in the pilot excerpts, which are mostly plans and explications | **Synthetic fixtures** (T18): DOCX/PDF documents that mimic the standard forms (ТЭП table, ОД КЖ, спецификация по ГОСТ 21.110, ведомость проёмов, кабельный журнал, энергопаспорт, ССР) in PD/RD/ID variants with planted violations, negatives and a revision conflict |
| 3 | How hidden-test groups are labelled with param codes (primary code for duplicates; out-of-matrix groups; sub-check granularity) | Precision/recall «совпадение требует правильного параметра/типа расхождения» (§14.3) | `alt_param_codes` on the card; duplicates reported under both codes; rule codes for out-of-matrix findings |
| 4 | Customer confirmation of the suspicious thresholds (M-117, M-048, ranges) | FP control | Our defaults (D-03…D-06), flagged in the admin |
| 5 | ГПЗУ and ТУ values for the pilot objects | M-008.b, M-014.b, M-019.b, M-020.b, M-027.b | Manual entry; otherwise those sub-checks are NOT_APPLICABLE with basis |
| 6 | What «АИС "ОСИГ"» is; sample exports of АИС/РНИС/Мобильный КПТС/ГРОО | Tier D (M-098…M-101) | Mock adapter plus MISSING_EVIDENCE degradation |
| 7 | Access to a normative database (КонсультантПлюс, Техэксперт, docs.cntd.ru) | Verify clause numbers and editions as of 07.2026 | Confidence badges; LOW references marked «требует проверки» |
| 8 | Object profile of the pilot objects (purpose, functional class, phase, works type) | Applicability, phase-based MISSING/NOT_APPLICABLE | Infer from documents («ДОО 220 мест» → Ф1.1, «СОШ» → Ф4.1, «здание МВД» → Ф3.x); the inspector confirms on the card |
| 9 | The customer's preferred room-function taxonomy («полезная» vs «техническая») | M-003 «в пользу технических зон» | Our taxonomy (term_synonyms), based on the СП 118/СП 54 area-calculation appendices |
| 10 | Digitized tolerance tables (СП 70.13330.2012 табл. 5.10 etc.) | TOLERANCE_CHECK when the sheet does not state tolerances | Sheet-declared tolerances only (OKT103 has them on the sheet); otherwise NOT_COMPARABLE |
| 11 | The original vector PDFs of the ventilation comparison (the «пояснения» PDF contains raster crops) | Token diff of vent branches needs the text layer | Raster fallback (image registration and diff) → a low-confidence composite CANDIDATE; the inspector splits it |

---

## 9. Jury demo scenario for this block, plus acceptance tests

### 9.1 Demo storyline (≈ 6 min inside the overall demo)

1. **«Ядро системы — Матрица 132».**
   - Open «Матрица контроля» and filter HIGH plus section АР.
   - Open **AR-41 · M-041**. The rule reads in Russian: «Если ширина эвакуационной двери в свету в РД/ИД < 0,9 м → Кандидат; если в РД ширина уменьшена относительно ПД → Кандидат».
   - Show the normative reference with its confidence badge, the linked param M-105, and the tier badge B with the reason «номинал проёма ≠ ширина в свету».
2. **Module 8 without recoding.**
   - The admin changes `min_value` of M-041 from 0,9 to 1,0, runs a dry-run on a fixture door of 0,95 м, and publishes matrix_version 1.1-B03.2.
   - The re-run now marks that door as CANDIDATE, and the protocol header shows the new matrix_version.
   - The change appears in the audit log with the reason.
3. **The pilot run** (the pilot objects loaded as PD/RD/ID):
   - **ALT79B:** M-002 → NEGATIVE_VERIFIED (+0,49 % < 1 %). M-003 → CANDIDATE with atomic findings: №23 «Помещение» → «Комната отдыха», rooms 18–21 areas changed. Also a SUSPICION «Σ экспликации 2795,04 ≠ итог 2797,27» (HR-LOG-005 / M-003.c).
   - **SOSH25:** M-003.b ELEMENT_ADDED, room 1.109 «Зона ожидания» 18,2 м².
   - **UNDMS:** M-044 LAYER_REMOVED «Бронированный стальной лист 6 мм». The RD change-log entry is attached as supporting evidence, and the card explains why that entry is not an approved change.
   - **OKT103:** M-054.b TOLERANCE_EXCEEDED (tolerances 15 / ±12 / 20 мм, fact up to +980 мм). The inspector confirms it → CONFIRMED_VIOLATION.
   - **POL17:** zero candidates. NEGATIVE_VERIFIED across the compared params is the FP guard.
   - **Ventilation:** M-078.b missing branches В2.4–В2.9 in rooms 140/142; M-077.c missing warm-floor loops in МГН rooms.
4. **All 132 are accounted for.** The coverage view shows 132 rows:
   - CANDIDATE / NEGATIVE_VERIFIED;
   - NOT_APPLICABLE with a basis, e.g. «M-018: газоснабжение не предусмотрено — ПЗ стр. N» and «M-090…M-097: снос не предусмотрен»;
   - MISSING_EVIDENCE, e.g. «M-098: требуются данные АИС «ОСИГ»»;
   - NOT_COMPARABLE, e.g. «M-009: разные системы высот» on a fixture.
5. **Scenarios.** The same fixture object uploaded as PD+RD only → the scenario is PD_RD_ONLY. RD→ID sub-checks are NOT_APPLICABLE (object phase DESIGN), and single-stage normative checks on RD still run.
6. **ИД completeness.** On OKT103 the checklist shows 3.3.4 «поэтажные исполнительные схемы» as FOUND. 6.4.1–6.4.3 (АОСР опалубка/арматура/бетон) are MISSING → MISSING_EVIDENCE, and they are not counted as violations. 3.3.2 свайное поле is NOT_APPLICABLE with the reason «фундамент — плита».

### 9.2 Acceptance criteria and tests

| ID | Test | Pass criterion |
|---|---|---|
| AT-01 | Seed load | 132 params loaded; all §8.1 fields non-null where the ТЗ requires them; JSON Schema validation of every `comparison_rule` and `applicability` passes; `alias_code` unique |
| AT-02 | Regex suite | Every regex compiles; the 43 pilot-string tests (positive and negative) pass; ≥ 1 positive and 1 negative test per demo_priority 1–2 param |
| AT-03 | Pilot golden set | 9 pilot groups + 3 vent groups produce the expected statuses and param codes (§3.7 table); POL17 → 0 CANDIDATE |
| AT-04 | Scenario matrix | For each of the 6 scenarios × 132 params, every param and every sub-check has exactly one status from the allowed set; no pairwise sub-check runs without its stages |
| AT-05 | Module 8 without recoding | Changing `min_value` through the API and publishing changes the result of the next run with no deploy; the protocol shows the new `matrix_version`; audit entry present |
| AT-06 | NOT_APPLICABLE discipline | 100 % of NOT_APPLICABLE results carry a basis (rule text + fact source or «признаки не выявлены»); MISSING_EVIDENCE never counts as a violation |
| AT-07 | Duplicates | A linked finding on M-040/M-104 is reported under both codes and counted once in the summary |
| AT-08 | Normalization | Homoglyphs («В35» ≡ «B35», «С0» ≡ «C0»); decimal comma; thousands separators; units (Гкал/ч ↔ кВт; м ↔ мм; % ↔ коэффициент); the ε rounding tests from B04 §3.5.1 |
| AT-09 | Performance | Rule evaluation for 132 params on extracted facts ≤ 2 s (§11 #4 budget: 2 min); per-param NLP anchor search ≤ 500 ms with cached embeddings (§11 #7) |
| AT-10 | ИД checklist | With a given object profile, applicability produces the expected applicable set; the aggregate ID status is correct for full / partial / none; the phase rule works |
| AT-11 | FP guard | On negative fixtures (identical PD/RD) and on outdated-revision fixtures, the FPR of the rule engine is ≤ 0,05 (headroom to the 0,10 threshold) |
| AT-12 | Tier D degradation | M-098…M-100 without adapter data → MISSING_EVIDENCE with the reason text; with mock data → CANDIDATE or NEGATIVE_VERIFIED |

---

## 10. Work breakdown

Sizes: S ≤ 0,5 day, M ≤ 1,5 days, L ≤ 3 days. Owners are the proposed implementation agents.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| MTX-T01 | `params` schema (§8.1 + extensions), migrations, seed loader from `matrix_enriched.json` plus the original xlsx; ajv schemas for `comparison_rule` / `applicability` | M | Architecture DB baseline | Backend (Node) |
| MTX-T02 | `matrix_versions`: draft/publish/retire, canonical JSON + SHA-256, diff, `matrix.version.published` event, audit | M | T01 | Backend (Node) |
| MTX-T03 | Rule DSL pydantic models + JSON Schema generation; mapping to B04's Appendix A notation; validation CLI in CI | M | T01 | Comparison engine (Python) |
| MTX-T04 | Evaluator core: the 14 rule types, ε logic, conditional bounds, threshold references (`$min_value`, `$object.*`, `$derived.*`), abstention, atomisation, status mapping, linked-finding fingerprinting | L | T03, T05 | Comparison engine (Python) |
| MTX-T05 | Dictionaries: enum_scales (12 scales), unit_conversions, homoglyph map, vocabularies with adverse transitions, the number/dimension parser («6 252,3», «+491/+552», «500×600», «Ø25») | M | — | Comparison engine (Python) |
| MTX-T06 | Applicability engine (JSONLogic subset, three-valued) + object-profile fact extraction from ПЗ/ТЭП/ПД composition using positive/negative anchors; inspector override API | M | T05; B01 text extraction | ML/NLP (Python) |
| MTX-T07 | Regex and anchor hardening on the pilot text layers and synthetic fixtures; multilingual embedding index of anchors (Redis cache) | M | T18 | ML/NLP (Python) |
| MTX-T08 | Explication table reconstruction from vector text (rows: number, name, area; totals) + `term_synonyms` function classes; M-003/M-011 extraction | L | B01 page model | ML/parsing (Python), shared with B04 |
| MTX-T09 | Layer-stack parser (M-044, M-032, M-125, M-128) with material normalization | M | T05 | ML/parsing (Python) |
| MTX-T10 | ИД tolerance tables: OCR of scan tables, pairing of deviation vs tolerance (OKT103) → TOLERANCE_CHECK facts | M | B01 OCR | ML/OCR (Python) |
| MTX-T11 | `normative_base` seed from the JSON references + `param_normative` links; numeric `$derived.*` rows (КМ table 28, ВПВ table 7.1, fire passages, Ro, КЕО) with conditions and effective dates | M | T01 | Backend + domain |
| MTX-T12 | Logical_Rules seed (40) in B05's AST + unit tests per rule (positive, negative, unknown) | M | B05 evaluator | Hypotheses (Python) |
| MTX-T13 | ИД checklist → `completeness_templates`; classification anchors; aggregate ID_* statuses; phase rule | M | B01 W10 | Ingestion (Node/Python) |
| MTX-T14 | Stage/scenario resolver (`sufficient_sets`, PHASE_BASED policy) | S | T04 | Comparison engine (Python) |
| MTX-T15 | Summary dedup of linked params; `alt_param_codes` on cards | S | T04 | Comparison/protocol |
| MTX-T16 | Normative verification pass: the ~40 demo references → HIGH or corrected; edition check as of 07.2026 | M | D-10 | Domain expert (user or consultant) |
| MTX-T17 | Golden test suite: pilot 12 groups, scenario matrix, FP guard, performance | M | T04, T08–T10, T18 | QA |
| MTX-T18 | Synthetic fixture generator: ТЭП, ОД, specifications, ведомости, cable journals, energy passport, ССР in PD/RD/ID variants (positive, negative, revision conflict, missing stage) | M | — | QA / data |
| MTX-T19 | Matrix admin UI: list, detail, Russian rule renderer, threshold editor, dry-run, versions and diff | M | T02, T03 | Frontend (B08) |
| MTX-T20 | xlsx import/export round-trip in the Приложение 1 layout + an enrichment sheet | S | T01 | Backend (Node) |

**Critical path for the demo:** T05 → T03 → T04 → T08 / T09 / T10 → T17. Build T18 in parallel from day 1, because tier-A demo params have no real source documents otherwise.
