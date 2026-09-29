# B93 — Scoring contract, Приложение № 2 and the ТЗ delta («Инспектор ИИ»)

Status: analysis, 2026-09-27. No application code. Scratch artefacts (prototype scorer, text dumps, diffs) are in the session scratchpad under `s93/`.

Inputs read in full: `ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0/data/*` (schema, scoring summary, split policy, 416-row manifest, 132-row catalog, 4 finding groups, 10 train checks), `evidence_pages/*.png`, `ХАКАТОН_УЧАСТНИКАМ_ГОТОВО_К_ПЕРЕДАЧЕ/assembly_report.json`, the `Перечень нарушений.txt` ground-truth index, all five documents in `ТЗ_И_ПРИЛОЖЕНИЯ/` (ТЗ docx, Приложение 1 xlsx, Приложение 2 docx, «Легенда к матрице», «ПОДРОБНЫЙ ПЕРЕЧЕНЬ…»), and our earlier sources (`ТЗ/10. Мосстройнадзор.pdf`, `ТЗ/Матрица_параметров_редакция1.1.xlsx`, `ТЗ/Перечень_исполнительной_документации_редакция1_1.docx`). I also used `docs/PLAN.md`, `90_consistency_and_canonical_model.md` (§0, §3.2, §3.12), `04_comparison_protocol.md` (§3.10–3.11) and `06_feedback_retraining_weekly_report.md` (§3.10).

---

## 0. Executive summary

1. **Two different vintages arrived together.** The package's ТЗ, Приложение 1, Приложение 2, Легенда and Перечень are the **v1.0 set** (authored 30 Jun – 27 Jul 2026; the ТЗ says «Версия документа: 1.0», «Дата утверждения: 15 июля 2026 года»). The PDF ТЗ we analysed was built on 12 Sep 2026, and the matrix «редакция 1.1» on 17 Aug 2026; together they are the **newer v1.1 set**. The scoring data (`data/`, package v2.0, assembled 11 Aug 2026) sits between them. It mixes v1.0 vocabulary (`pd_value/rd_value/id_value`, `criticality`, protocol statuses `OK/WARNING/CRITICAL/ID_MISSING/RD_MISSING/PD_MISSING/COMPARISON_IMPOSSIBLE`, `inspector_status: "CONFIRMED"`) with v1.1 ideas: object-level TRAIN/TEST split, page-level evidence, exact file+page localisation. **Ruling:** the internal model follows the PDF (v1.1). The external outputs follow the package: the submission JSON follows `submission_schema.json`, and the protocol document follows Приложение 2. Both ТЗ versions declare Приложение 2 mandatory.
2. **What is scored.** A submission is one JSON per object: `{object_id, checks[]}`. The best-supported hypothesis is that a check is keyed by **(object_id, parameter_code, location)**. The 10 train checks have 10 unique keys, and `location` is a room number such as `"012"` (leading zero kept). F1 (60 points) is most likely computed over `violation_label = VIOLATION_PRESENT`. Localisation (15) is an exact `(file_id, pdf_page_number)` match with no bbox, and `pdf_page_number` is the **1-based PDF page index**, not the sheet number (verified on all 6 gold pages). Values and statuses (15) cover `violation_label`, `protocol_status`, `criticality` and normalised values. Integrity and split handling (10) most plausibly checks that evidence cites real, non-excluded, same-object files with the right stage and a valid page, that the submission covers only the right split, and that composite findings are split into atomic per-location checks.
3. **The critical-miss gate is the dominant risk.** On train, 6 of 10 checks are «утверждённые критические контрольные точки» (IOS4-078 ×5 and IOS4-079 ×1; FREE-HEATING-001 is «Существенное — требует утверждения»). My prototype scorer shows that **one** missed room (314), a wrong code (IOS4-078 instead of IOS4-079), or a stripped leading zero («12» for «012») drops a 91–94-point run to **59**. Emitting both candidate codes for an ambiguous critical finding costs ~3 points of F1 and removes the gate risk (97.1). Recall on Критическое parameters, atomic per-room splitting, exact room tokens and code-mapping fidelity are therefore worth more than any other precision gain.
4. **Two routing facts from the organizers' gold contradict our canonical model.** Warm floors are `FREE-HEATING-001` with `MATRIX_GAP_CONFIRMED`, not M-077 (radiators). Routing them to IOS4-077 costs 36 points on train. Ventilation changes map to IOS4-078 (ducts, «PROVISIONAL_DOMAIN_MAPPING») and the vent-chamber supply-unit configuration maps to IOS4-079 (fans).
5. **Codes.** All three styles encode the same integer 1…132: matrix 1.1 `M-055`, catalog `KR-055`, Приложение 2 `KR-55`/`КР-67`. **Canonical external code = the catalog `parameter_code`** (`PZ-001 … SM-132`), keyed by `param_id`. `M-xxx` and the Приложение 2 short forms are aliases. Out-of-matrix findings use `FREE-<TOPIC>-<NNN>`, one code per finding group. Приложение 2 contains a code error: «AR-14 Ширина эвакуационных коридоров» should be AR-040 (id 14 is PZ-014 «Расчетная электрическая мощность»).
6. **The Приложение 2 form differs from our earlier protocol design** (`04 §3.10`: A4 landscape, PT Astra, 5 tables). The sample is A4 portrait with ГОСТ margins, Segoe UI, a 7-section body, emoji status markers and a резолютивная часть with a concrete recommendation per violation. The §9.2 п.4 five tables and evidence cards (v1.1) are **not** in Приложение 2. I propose: keep the 7 sections verbatim, add «Тип проверки» to the header, and add «Приложение А» (five §9.2 tables), «Приложение Б» (evidence cards) and «Приложение В» (input registry and versions).
7. **Integrity finding in our local data.** 19 Новослободская ИД files listed in the manifest are missing locally (16 in «Ограждение котлована. СВГ», 3 in «Форшахта»). The cause is the cp866 filenames: «А» decodes to «Ђ» and «Р» decodes to «ђ», which are case pairs. «АОСР №10АЗ» and «АОСР №10РЗ» therefore collided on the case-insensitive APFS volume. Two more files lost «Ш» (→ «_»); their sha256 still match. Речников (hidden test) and Тюменская are complete. File identity must be resolved by sha256, never by path.
8. **Recognition implications for the top-priority block.** Речников has RD only for ГП, АР, КР/КЖ, ЭОМ and ВК1, and no RD for ОВ, СС or ПБ. Its ИД is mostly 200–500-page scanned binders. Every DWG archive (38 archives, 662 DWG) has a PDF twin in the same folder, and evidence must cite that PDF. Gold evidence is **group-level**: one anchor page per stage per finding group, reused for every room. Room 314 is drawn on RD p.20, yet gold cites p.18. Sheet→page mapping from title blocks and room-label extraction are therefore scoring-critical.

---

## 1. What the organizers actually gave us

### 1.1 Package inventory and provenance

| Artefact | Content that matters | Notes |
|---|---|---|
| `submission_schema.json` | Draft 2020-12. Root `{object_id, checks[]}` (both required). Check required: `parameter_code, location, violation_label, evidence`. Optional: `pd_value, rd_value, id_value` (any type), `protocol_status` (enum 7), `criticality` (string or null). Evidence item required: `stage ∈ {PD,RD,ID}, file_id, pdf_page_number (int ≥ 1)` | No `additionalProperties:false`, so extra fields validate. No bbox. One object per file |
| `scoring_summary_without_answers.json` | `finding_detection_f1: 60`, `source_localization_exact_file_page: 15`, `normalized_value_and_status_accuracy: 15`, `document_integrity_and_split_handling: 10`; «При пропуске любой утверждённой критической контрольной точки итоговый балл ограничивается 59 из 100.» | No formulas |
| `split_policy.json` | TRAIN_PUBLIC = OBJ-TYUMENSKAYA-5-GOLD-SEED, OBJ-NOVOSLOBODSKAYA; TEST_HIDDEN = OBJ-RECHNIKOV-7-7; `do_not_release`: all_gold_checks.jsonl, review_queue.jsonl, evidence_index.jsonl for TEST_HIDDEN; `excluded_file_ids`: F0149, F0418 | Confirms there is a full gold file (all_gold_checks) and a review queue (unapproved items) |
| `document_manifest.jsonl` | 416 rows, schema 0.1.0. Fields: file_id, object_id, corpus, dataset_role (GOLD_SEED 58 / UNLABELED_POOL 358), split, relative_path, extension, size_bytes, sha256, stage (PD 172, ID 130, RD 103, **RD_ID_MIXED 10**, **UNKNOWN 1**), section (OTHER 214, KR 89, EOM 19, VK 18, AR 17, SS 17, OV 16, POS 10, GP 9, PB 7), pdf_pages, annotation_status (UNLABELED 412, POSITIVE_EVIDENCE_SOURCE 3 = F0171/F0201/F0202, GROUND_TRUTH_INDEX 1 = F0194), exclusion_reason (all null), duplicate_group (only F0165 → `f4a34324aaf6`), distribution_status (all INCLUDE), label_visibility | This is effectively the machine-readable registry. `section` is coarse (ИОС1 PD volumes are `OTHER`). F0149 is absent from the id sequence, and F0418 would follow F0417, so the excluded files were removed before distribution |
| `parameter_catalog_132.jsonl` | parameter_id 1…132, `parameter_code` (`PZ-001`… `SM-132`), pd_section, name, unit, source_pd/rd/id, trigger, criticality (106 «Критическое (приостановка работ)», 26 «Существенное (предписание)»), matrix_row, mapping_status = SOURCE_MATRIX (all) | Content identical to both matrix xlsx versions (§6.3) |
| `public_train_finding_groups.jsonl` | 4 groups (G-TR-001…004), all from «Перечень нарушений.txt» items 1–3. Item 3 is split into two groups by `difference_type` | Group fields: matrix_scope, parameter_id/code, parameter_mapping_status, title, difference_type, locations[], criticality, source_label, gold_status, evidence[] |
| `public_train_checks.jsonl` | 10 checks = groups exploded per location. Extra gold fields not in the schema: check_id, location_type (`ROOM`), comparison_result, document_status (`PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK`), inspector_status (`CONFIRMED`), gold_status (`FINAL_GOLD_EXISTENCE`), score_eligible (true), evidence[].document_sheet_number / rendered_image / localization (`PAGE_LEVEL_VISUALLY_VERIFIED`) | The only public labels |
| `evidence_pages/` | 6 page renders (no markup, no boxes) | Page-level truth only |
| `assembly_report.json` | `delivery_folder: C:\Users\Admin\Desktop\CODEX\outputs\…`, 416 files / 8.70 GB, NTFS hard links, `participant_hidden_answer_leakage: 0`, excluded F0149/F0418, spot hashes | The organizers assembled this with an AI coding agent. Expect a simple, literal, exact-match scorer in Python |

### 1.2 Train gold at a glance

| check | group | code (mapping status) | location | comparison_result | label / protocol_status | criticality | PD evidence (file, pdf page → sheet) | RD evidence |
|---|---|---|---|---|---|---|---|---|
| TRAIN-0001 | G-TR-001 | IOS4-079 (PROVISIONAL_DOMAIN_MAPPING) | 012 | CONFIGURATION_MISMATCH | VIOLATION_PRESENT / CRITICAL | Критическое (приостановка работ) | F0171 p104 → л.26 | F0201 p17 → л.3 |
| TRAIN-0002…0005 | G-TR-002 | FREE-HEATING-001 (MATRIX_GAP_CONFIRMED) | 267, 270, 271, 272 | MISSING_DESIGN_ELEMENT | VIOLATION_PRESENT / **WARNING** | Существенное (предписание) — требует утверждения | F0171 p99 → л.21 | F0202 p17 → л.4 |
| TRAIN-0006…0007 | G-TR-003 | IOS4-078 (PROVISIONAL_DOMAIN_MAPPING) | 140, 142 | MISSING_DESIGN_ELEMENT | VIOLATION_PRESENT / CRITICAL | Критическое (приостановка работ) | F0171 p88 → л.10 | F0201 p18 → л.4 |
| TRAIN-0008…0010 | G-TR-004 | IOS4-078 (PROVISIONAL_DOMAIN_MAPPING) | 147, 198, 314 | CONFIGURATION_MISMATCH | VIOLATION_PRESENT / CRITICAL | Критическое (приостановка работ) | F0171 p88 → л.10 | F0201 p18 → л.4 |

Values in gold (verbatim): «Конфигурация приточных установок по листу 26 ПД» / «Иная конфигурация на плане ОВ1, помещение 012»; «Тёплый пол предусмотрен» / «Тёплый пол отсутствует»; «Вытяжная вентиляция предусмотрена» / «Вытяжная вентиляция отсутствует»; «Конфигурация вентиляции по листу 10 ПД» / «Конфигурация вентиляции изменена». `id_value` is `null` everywhere.

Verification against the PDFs (PyMuPDF text layer):
- The pages are 1-based. F0171 p104 carries «012», and p99 carries 267/270/271/272. F0201 p17 carries «012» and p18 carries 140/142/147/198. F0202 p17 carries the four warm-floor rooms.
- **Room 314 is not on F0201 p18.** It appears on RD p20 and p25, and gold still cites p18 for TRAIN-0010. Gold evidence is therefore **group-level**: the pages named in the inspection report, copied to every location of the group.
- Page choice is semantic, not "first occurrence". «012» occurs on PD p85, 86, 88, 89, 94, 95, 99 and 104, and gold uses p104 («Принципиальная схема системы теплоснабжения приточных установок», л.26), the sheet that shows the supply units.

### 1.3 Local data completeness (integrity issue on our side)

| Object | Manifest files | Present locally (by path or size+sha) | Missing | Cause |
|---|---|---|---|---|
| Тюменская (GOLD_SEED) | 58 | 58 | 0 | — |
| Новослободская (UNLABELED) | 145 | 126 (+2 renamed, sha verified: F0070, F0072) | **19**: F0015, F0018, F0021, F0024, F0027, F0030, F0033, F0036, F0039, F0042, F0045, F0049, F0052, F0055, F0064, F0067 (СВГ, all «…РЗ…»), F0071, F0077, F0080 (Форшахта, «…РФ…») | The original zip used cp866 names. «А» (0x80) is shown as «Ђ» and «Р» (0x90) as «ђ». These are upper and lower case of one letter, so the case-insensitive APFS volume merged «…№10АЗ…» and «…№10РЗ…». «Ш» (0x98) has no cp1251 glyph → «_» |
| Речников (TEST_HIDDEN) | 213 | 213 | 0 | — |

Fix: re-extract the organizers' original archive with correct decoding (`unzip -O cp866`, or Python `zipfile` with cp866 names) or onto a case-sensitive volume (`hdiutil create -fs "Case-sensitive APFS"`). This needs the original archive, so it is a question for the user (§8). Until then, ingestion must resolve `file_id` **by sha256** and report manifest rows without a file as `MISSING`, not crash.

### 1.4 Hidden-test object profile (Речников ул. 7-7)

These numbers come from the manifest and file names only. No content was reviewed for answers.

- 15,961 pages / 6.95 GB. PD 89 PDFs cover all sections, with many revision pairs: `-кор2` vs `-кор3`, `ОПЗ Изм 2` vs `ОПЗ-кор3`, `ПБ2 (2)` vs `ПБ2-кор3`, and two different «ПОС-кор3» files (F0310 and F0312, 67 pages each).
- RD: 44 PDFs for ГП, АР (АР0–АР4), КР (КЖ0…КЖ7, two корпуса plus parking), ЭОМ (ЭМ, ЭО, ЭН, ЭГ, НС, ОЗДС) and ВК1. There is **no RD for ОВ, СС or ПБ**. There are also 38 archives (20 zip, 11 7z, 7 rar) holding 662 DWG, 17 DOCX and 6 PDF, 5 loose DWG, and 6 DOCX change notices («П_КЖ1_Изм.1.docx»…). **Every DWG archive has a PDF twin in the same folder.**
- ИД: 31 PDFs, mostly scanned binders of 200–507 pages. They cover КР by floor, кладка, НВФ/facade, ЭОМ, ВК/ПП, отделка and metal works.

Consequence: violations can only be found where at least two stages exist (ГП, АР, КР, ЭОМ, ВК; ИД for КР/ЭОМ/ВК). Parameters of ИОС4, ИОС5 and ППМ that need RD will be `MISSING_DOCUMENT/RD_MISSING`. The recognition block should put its depth budget on КЖ drawings, АР plans and АОСР scans.

---

## 2. The scoring contract, reverse-engineered

### 2.1 What a "finding" is: hypotheses tested on train

| # | Hypothesis for the F1 unit | Evidence for | Evidence against | Verdict |
|---|---|---|---|---|
| K1 | **Check = (object_id, parameter_code, location)**; positive iff `violation_label = VIOLATION_PRESENT` | 10 train checks → 10 unique keys. The schema has no other identifying field. Groups are exploded one check per location, and G-TR-003/004 share code and pages but have disjoint rooms | — | **Primary** |
| K2 | Key also includes `comparison_result` (difference type) | Item 3 is split into two groups by difference_type | `comparison_result` is **not** in the submission schema. On train, keys are already unique without it | Rejected as a key. Emit it as an optional extra (§3.9) |
| K3 | Group-level F1: a gold group is found if ≥ 1 (or a majority) of its locations match | `finding_groups` is published separately, and ТЗ §14.3 says «F1 по evidence_group» | The submission has no group id, so group membership must be inferred from code+location anyway | **Secondary**. Our scorer reports it as a variant |
| K4 | TP also requires correct evidence (ТЗ §14.3 «совпадение требует … корректного доказательства») | ТЗ v1.1 wording | The package scores localisation separately (15 points). Double-counting is unlikely | Variant «strict» in our scorer |

`location` normalisation must be assumed **exact, apart from whitespace and case**. The gold keeps «012» with a leading zero. Prefixes such as «пом.» or «Венткамера» may or may not be stripped, so we never emit them.

### 2.2 Likely component formulas (H1 = primary assumptions for our local scorer)

| Component (points) | H1 formula | Alternatives our scorer also reports |
|---|---|---|
| `finding_detection_f1` (60) | Per object: TP/FP/FN on K1 keys with label VIOLATION_PRESENT; P, R, F1; points = 60·F1. Pooled micro if several objects | K3 group-level F1; K4 strict F1; «multi-label» F1 over (key, label) for all labels, to measure the risk of emitting negatives |
| `source_localization_exact_file_page` (15) | Mean over **gold positives**: \|gold(stage,file_id,page) ∩ pred\| / \|gold\|; an unmatched gold positive scores 0; points = 15·mean | Jaccard per check (penalises extra pages); without `stage`; per-stage; «any-hit» (≥ 1 shared page) |
| `normalized_value_and_status_accuracy` (15) | Mean over **all gold checks** of: 0.5·status (label 0.5, protocol_status 0.25, criticality 0.25) + 0.5·values (pd/rd/id each 1 if both null, or numeric equal after unit normalisation, or normalised-text similarity ≥ 0.85); unmatched gold = 0 | Status-only; values-only; text threshold sweep 0.6–0.95; numeric-only |
| `document_integrity_and_split_handling` (10) | Share of passed integrity rules (§2.6) | Hard fail (0) on any violation; per-rule report |
| Gate | If any gold check with label VIOLATION_PRESENT, criticality starting «Критическое», without «требует утверждения», and gold_status FINAL has no predicted VIOLATION_PRESENT with the same key → total = min(total, 59) | Strict variant: the checkpoint also needs ≥ 1 correct evidence page. Broad variant: every approved critical gold check of any label must be present with the right label |

### 2.3 Sensitivity on train (prototype scorer, H1)

The prototype is in the scratchpad at `s93/score_proto.py`. It applies H1 to the 10 public checks.

| Case | F1 | Loc | Val+status | Integ. | Gate | **Total** |
|---|---|---|---|---|---|---|
| A. Perfect copy of gold | 1.000 | 1.00 | 1.000 | 1.000 | 6/6 found | **100.0** |
| B. Room 314 dropped (one critical room missed) | 0.947 | 0.90 | 0.900 | 1.000 | missed IOS4-078/314 | 93.8 → **59.0** |
| C. Warm floor routed to IOS4-077 (our old M-077 routing) | 0.600 | 0.60 | 0.600 | 1.000 | ok | **64.0** |
| D. Room 314 cited on its own RD page 20 instead of group page 18 | 1.000 | 0.95 | 1.000 | 1.000 | ok | **99.25** |
| E. Vent chamber 012 coded IOS4-078 instead of IOS4-079 | 0.900 | 0.90 | 0.900 | 1.000 | missed IOS4-079/012 | 91.0 → **59.0** |
| F. Hedge: 012 emitted under both IOS4-078 and IOS4-079 | 0.952 | 1.00 | 1.000 | 1.000 | ok | **97.1** |
| G. Generic value texts («Предусмотрено по ПД» / «Изменено в РД») | 1.000 | 1.00 | 0.667 | 1.000 | ok | **95.0** |
| H. One wrong stage + one excluded file (F0149) cited | 1.000 | 0.95 | 1.000 | 0.625 | ok | **95.5** |
| I. Location «пом. 012» (normalised by our scorer) | 1.000 | 1.00 | 1.000 | 1.000 | ok | 100 (**0 if their scorer does not normalise**) |
| J. Location «12» instead of «012» | 0.900 | 0.90 | 0.900 | 1.000 | missed | 91.0 → **59.0** |

Lessons:
- The gate dominates. B, E and J each lose ~32–35 points to a single miss.
- The routing taxonomy is the next biggest lever (C: −36).
- Localisation and value phrasing are second-order (−0.75 … −5).
- Hedging an ambiguous critical code is cheap insurance (F).

### 2.4 The critical-miss gate

- **Definition we adopt:** «утверждённая критическая контрольная точка» = gold check with `criticality = «Критическое (приостановка работ)»` (no «требует утверждения» suffix), `gold_status` starting with `FINAL`, and `score_eligible = true`. `review_queue.jsonl` (withheld) holds unapproved items, which is why FREE-HEATING carries «— требует утверждения». On train: TRAIN-0001 and TRAIN-0006…0010, 6 checkpoints.
- **What counts as «пропуск»:** most likely no submitted check with the same key and `VIOLATION_PRESENT`. Our scorer also reports the strict variant (key + ≥ 1 correct page).
- **Math of hedging.** Let L be the gate loss (S − 59, typically 25–40 points) and c the F1 cost of one extra FP (≈ 60·ΔF1 ≈ 2–4 points for 10–30 gold positives). For an ambiguous critical finding whose runner-up code has probability p of being the gold one, emitting both is worth it when p·L > c, i.e. **p > ~0.1**. Hedges add up, so cap them with an FP budget (below).
- **Policy (gate-aware emission).** Thresholds are tuned by leave-object-out on dev data, never on Речников.
  1. For Критическое parameters, emit a candidate at a lower confidence than for Существенное (e.g. 0.30 vs 0.50, to be tuned). Emit only on a real detected difference (value, config, presence), never on extraction failure alone.
  2. Split composite findings into **all** affected locations. The loss in case B came from one room.
  3. For code ambiguity inside one system (IOS4-078 vs IOS4-079, AR-040 vs PPM-104 vs ODI-116 for corridor width, AR-041 vs PPM-105 for evacuation doors), emit the top two codes when p(runner-up) ≥ 0.1. The matrix itself has 9 near-duplicate pairs (PLAN §8), so this situation is systematic.
  4. Hedge budget: at most 20 % of emitted critical checks per object may be hedges, plus an overall FP budget per object from dev calibration.
  5. FREE-* findings are not «утверждённые критические», so the gate never applies to them and they are emitted only when evidence-bound (§3.7).

### 2.5 Are negatives and missing documents scored?

- `violation_label` has four classes and `protocol_status` has `OK` and three `*_MISSING` values. ТЗ v1.1 §14.2 says the test must contain «подтверждённые нарушения, проверенные отрицательные группы, отсутствующие доказательства, неприменимые параметры и конфликт редакций». So `all_gold_checks.jsonl` very likely has NO_VIOLATION, MISSING_DOCUMENT and COMPARISON_IMPOSSIBLE rows.
- Those rows cannot enter F1 under K1, which is positives only. They most plausibly enter `normalized_value_and_status_accuracy` (a matched key with the right label and status) and possibly the broad gate variant.
- **Policy:** emit an explicit row for **every one of the 132 parameters** at object level (`location = "OBJECT"`, §2.7), plus atomic rows for every violation location. The expected gain on the status component outweighs the risk, which exists only if their F1 counted all labels. Our scorer's multi-label F1 variant quantifies that risk on dev. The exporter keeps a switch `--emit-negatives {all,none}`.
- MISSING_DOCUMENT is scored the same way. Get the missing stage right (`ID_MISSING` vs `RD_MISSING` vs `PD_MISSING`), because it is part of `protocol_status`.

### 2.6 `document_integrity_and_split_handling`: what it probably checks

Three readings fit the name, and the design must satisfy all of them:

| Reading | Rules our exporter enforces (and our scorer checks) |
|---|---|
| **Document integrity** | (a) every `evidence.file_id` exists in the manifest; (b) it belongs to the same `object_id`; (c) it is not in `excluded_file_ids` (F0149, F0418); (d) it is an `.pdf` row and `1 ≤ pdf_page_number ≤ pdf_pages`; (e) `evidence.stage` equals the manifest stage, and `RD_ID_MIXED` is resolved per file (F0201/F0202 full RD sections → `RD`; АОСР and «Исполнительный чертеж» → `ID`); (f) a `duplicate_group` is cited only through its kept representative (F0165); (g) the **current revision** is cited (`кор3` over `кор2`; «ИЗМ ПО ЗАМЕЧАНИЯМ»/`V2_` handled as revisions); (h) file identity is by sha256 |
| **Split handling (dataset split)** | The TEST submission contains only `OBJ-RECHNIKOV-7-7`. No TRAIN file ids appear anywhere in it. One file per object. No labels or rules derived from Речников (§4.9) |
| **Split handling (finding split)** | A composite finding is split into atomic checks, one per location, with no duplicate keys. Group-level evidence is copied to every atomic check (§2.8). Multi-volume documents are cited by the actual part file (Том 1.2 Книга 3, ИД binders by floor), and DWG or archive content is cited through its PDF twin |

### 2.7 Location conventions

| Location type | Canonical string we emit | Rationale |
|---|---|---|
| ROOM (incl. vent chambers, technical rooms) | Room number token **exactly as printed**: `012`, `267`, `1.109`, `-1.05`. No «пом.», «№», name or floor prefix | Matches gold. «12» and «пом. 012» are both at risk |
| FLOOR / BUILDING | `Корпус 1`, `Корпус 1, этаж 3`, `Этаж -1`, `Подземная автостоянка` | Unknown in gold, so we keep one stable grammar |
| AXES / structural element | `Корпус 1, этаж 5, оси 1-3/А-Б` | Unknown in gold, low match expectation |
| OBJECT (object-level parameters and all explicit negatives) | `OBJECT` | Mirrors the `location_type` enum style. Unknown in gold |

The exporter also writes `location_type ∈ {ROOM, FLOOR, BUILDING, AXES, ELEMENT, OBJECT}` as an optional extra field, using gold's name.

### 2.8 Evidence conventions

- `pdf_page_number` is the 1-based physical page index of the cited PDF. The sheet number from the title block goes into the optional `document_sheet_number` (the gold field name).
- **One anchor page per stage per finding group**, reused for all atomic checks. The anchor is the page that best depicts the changed element for the majority of the group's locations: majority rule for rooms, semantic priority for the element's sheet type (plan or schematic of that system). This reproduces all 10 train checks, including room 314 → p18. Optionally add the location's own page as a second item of the same stage only when it differs (case D shows the Jaccard/recall trade-off). Default: anchor only.
- Order: PD, RD, ID. Keep 1–2 items per stage. Never cite archives, DWG or DOCX when a PDF twin exists. Cite an ID page only when the ID actually confirms the discrepancy; gold `id_value` stays `null` for pairwise PD↔RD checks.

---

## 3. Mapping our canonical model to the submission

### 3.1 Field mapping

| Submission field | Source in our model (90 §3.2.4, 04 §3.11) | Rule |
|---|---|---|
| `object_id` | `objects.id` = manifest `object_id` | Echo verbatim |
| `parameter_code` | `params.code` = catalog code (new canonical, §3.6); `suspicions.free_code` for FREE | Never emit M-xxx or short aliases |
| `location` | `findings.element_key` → §2.7 grammar | Atomic: one check per location |
| `pd_value`, `rd_value`, `id_value` | `expected_value` / `actual_value` per stage slot, rendered by the value templates (§3.5) | `null` when that stage is not part of the check (gold style) |
| `violation_label` | §3.2 | |
| `protocol_status` | §3.2–3.4 | |
| `criticality` | `params.criticality_level` (restored, §7 plan change 10); FREE → «Существенное (предписание) — требует утверждения» | Exact catalog string |
| `evidence[]` | `evidence_fragments` of role EXPECTED/ACTUAL/SUPPORTING_* → `{stage, file_id, pdf_page_number}` after anchor selection (§2.8) | Deduplicated, current revisions only |
| optional extras | `comparison_result`, `location_type`, `document_status`, `matrix_scope` (MATRIX/FREE_SEARCH), `parameter_mapping_status`, `finding_id`, `confidence`, evidence `document_sheet_number` | Gold field names, allowed by the schema. A `--strict` export drops them |

### 3.2 Status mapping (completeness × finding × inspector → label, protocol status)

| completeness_status | finding_status / inspector_status | `violation_label` | `protocol_status` |
|---|---|---|---|
| COMPLETE | CANDIDATE, inspector PENDING or CLARIFICATION_REQUIRED | VIOLATION_PRESENT | CRITICAL if criticality Критическое, else WARNING |
| COMPLETE | CONFIRMED_VIOLATION | VIOLATION_PRESENT | same |
| COMPLETE | NEGATIVE_VERIFIED (system, or inspector reject) | NO_VIOLATION | OK (or `*_MISSING` per §3.3 when a required stage is absent) |
| MISSING_EVIDENCE, document-level (no file of the required stage/discipline) | — | MISSING_DOCUMENT | ID_MISSING / RD_MISSING / PD_MISSING (§3.3) |
| MISSING_EVIDENCE, fragment-level (document present, value not extracted) | — | COMPARISON_IMPOSSIBLE | COMPARISON_IMPOSSIBLE |
| NOT_COMPARABLE (unreadable, sheets not matched, technical error) | — | COMPARISON_IMPOSSIBLE | COMPARISON_IMPOSSIBLE |
| CLARIFICATION_REQUIRED (revision conflict, missing approval mark) | — | COMPARISON_IMPOSSIBLE | COMPARISON_IMPOSSIBLE |
| NOT_APPLICABLE | — | NO_VIOLATION | OK |
| SUSPICION (evidence gate passed, confidence ≥ threshold) | converted or pending | VIOLATION_PRESENT with `FREE-*` | WARNING |
| SUSPICION (not evidence-bound) | — | not exported | — |

In batch/evaluation mode there are no inspector decisions, so every CANDIDATE is exported as VIOLATION_PRESENT. The system cannot confirm, and the train gold labels are confirmed findings. `PARTIALLY_LOADED` (docx §9.2) is not in the schema enum, so it is applied per parameter as `*_MISSING` or a comparison result.

### 3.3 Stage-availability precedence per parameter

Let R(p) be the stages required by parameter p for this object (B03 PHASE_BASED policy; pairwise rules need only two). Let A be the stages with a relevant, readable current document.

1. If |A ∩ R| ≤ 1: `COMPARISON_IMPOSSIBLE` («Если доступен только один тип или ни одного → проверка невозможна», docx §9.2).
2. Compare every available pair. Any violation → `VIOLATION_PRESENT`, `CRITICAL`/`WARNING`. The comparison result wins over a missing third stage (gold: `PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK` → CRITICAL).
3. Otherwise, if a required stage is missing: `MISSING_DOCUMENT` with the missing stage (`RD_MISSING` > `PD_MISSING` > `ID_MISSING` if two are missing, but that case is rule 1). This reproduces Приложение 2 «Не проверено (отсутствует ИД)».
4. Otherwise `NO_VIOLATION` / `OK`.

### 3.4 Criticality, protocol status and colours (from docx v1.0 §9.2, verbatim)

| Статус | Описание | Отображение | Действие инспектора |
|---|---|---|---|
| OK | Нарушений нет | Зелёный | Не требует действий |
| WARNING | Существенное нарушение | Жёлтый | Выдать предписание |
| CRITICAL | Критическое нарушение | Красный | Приостановить работы |
| ID_MISSING | Отсутствует ИД | Оранжевый | Дозагрузить ИД |
| RD_MISSING | Отсутствует РД | Красный | Приостановить работы |
| PD_MISSING | Отсутствует ПД | Красный | Приостановить работы |
| PARTIALLY_LOADED | ИД загружена частично | Жёлтый | Дозагрузить недостающие файлы |
| COMPARISON_IMPOSSIBLE | Проверка невозможна | Красный | Загрузить документы |

These go into `enums.yaml` as `ProtocolParamStatus` next to `ViolationLabel`. The dashboard colour can use them (orange folds into yellow on the 3-colour indicator). ТЗ v1.1 adds that «Уровень риска … не является автоматическим основанием для предписания или приостановки работ». So the protocol wording keeps «рекомендация / требует решения инспектора» until confirmation.

### 3.5 Value templates (mirror the gold phrasing)

| comparison_result (our DiscrepancyType) | pd_value | rd_value (id_value analogous) |
|---|---|---|
| MISSING_DESIGN_ELEMENT (ELEMENT_MISSING) | «{Элемент} предусмотрен(а/о)» | «{Элемент} отсутствует» |
| CONFIGURATION_MISMATCH (CONFIGURATION_CHANGED) | «Конфигурация {системы/элемента} по листу {sheet} ПД» | «Конфигурация {…} изменена» or «Иная конфигурация на плане {марка}, помещение {room}» |
| VALUE_MISMATCH (VALUE_DECREASED/INCREASED/CHANGED) | «{value} {unit}» in Russian number format («1,0 м», «4×95 мм²», «B35») | «{value} {unit}» |
| MATERIAL_SUBSTITUTION | «{марка/класс ПД}» | «{марка/класс РД}» |
| EXTRA_ELEMENT (ELEMENT_ADDED) | «{Элемент} не предусмотрен» | «{Элемент} предусмотрен» |

Element nouns come from a dictionary per parameter or system (e.g. «Тёплый пол», «Вытяжная вентиляция», «Приточная установка»). Keep the ё as printed in gold. Our scorer normalises ё→е, but theirs may not.

### 3.6 Code styles: one canonical, two aliases

| Style | Source | Example | Role |
|---|---|---|---|
| `param_id` | catalog/matrix row id | 55 | **Join key** everywhere |
| Catalog code | `parameter_catalog_132.jsonl` | `KR-055` | **Canonical external code**: submission, API, protocol, DB `params.code` |
| Matrix 1.1 code | `Матрица_параметров_редакция1.1.xlsx` | `M-055` | Alias (`alias_codes[]`) |
| ТЗ / Приложение 2 short | ТЗ §8.2 (`PZ-01`, `KR-55`, `AR-41`), Приложение 2 (`KR-55`, `КР-67`, `СПЗУ-30`, `ИОС1-69`, `ППМ-103`) | `KR-55`, `КР-55` | Alias (display and parse) |

Prefix map (Latin ↔ Cyrillic; ids): PZ↔ПЗ 1–23; SPZU↔СПЗУ 24–39; AR↔АР 40–53; KR↔КР 54–67; IOS1↔ИОС1 68–70; IOS2↔ИОС2 71–73; IOS3↔ИОС3 74–75; IOS4↔ИОС4 76–79; IOS5↔ИОС5 80; POS↔ПОС 81–89; POD↔ПОД 90–97; OOS↔ООС 98–101; PPM↔ППМ 102–114; ODI↔ОДИ 115–123; ZU↔ЗУ 124–131; SM↔СМ 132.

Parser: `^(M|PZ|SPZU|AR|KR|IOS[1-5]|POS|POD|OOS|PPM|ODI|ZU|SM|ПЗ|СПЗУ|АР|КР|ИОС[1-5]|ПОС|ПОД|ООС|ППМ|ОДИ|ЗУ|СМ)-0*(\d{1,3})$` → id. The prefix must agree with the id's section (M is exempt). On disagreement, warn and resolve by parameter name.

Every Приложение 2 code resolves to the same parameter as the catalog id, with **one exception**: «Ширина эвакуационных коридоров (AR-14)» is id 40 (AR-040); id 14 is PZ-014 «Расчетная электрическая мощность». Приложение 2 also mixes Latin and Cyrillic prefixes (KR-55 but КР-67).

This supersedes 90 §3.3.3 / T-13 (`code` = M-xxx). The ruling becomes: `code` = catalog code, `alias_codes` = [M-xxx, ТЗ short Latin, ТЗ short Cyrillic], and APIs accept all of them.

### 3.7 FREE-* codes (free-search findings)

- Format `FREE-<TOPIC>-<NNN>`. TOPIC comes from a fixed vocabulary seeded by gold: HEATING, VENTILATION, WATER, SEWER, ELECTRICAL, LIGHTING, FIRE, EVACUATION, ACCESSIBILITY, ARCHITECTURE, STRUCTURE, SITE, ROOF, FACADE, LIFT, ENERGY, OTHER. It is derived from the discipline and the element dictionary.
- NNN is numbered **per finding group** (not per room) within object and topic, starting at 001, ordered by (PD file_id, page, first location). A single heating finding in an object therefore gets exactly `FREE-HEATING-001`, as in gold.
- Criticality is «Существенное (предписание) — требует утверждения» and protocol_status is WARNING, so the gate never applies.
- Export only suspicions that passed the B07 evidence gate (bound PD and RD pages plus location). Keep at most ~5 groups per object until dev calibration says otherwise.

### 3.8 Parameter-mapping policy learned from the organizers

| Change type (discipline ОВ) | Organizers' code | Our current routing (90 §3.12) | Action |
|---|---|---|---|
| Supply-unit configuration in a vent chamber | IOS4-079 «Характеристики вентиляторов…» (PROVISIONAL_DOMAIN_MAPPING) | M-079 ✔ | keep |
| Exhaust ventilation absent in rooms; ventilation configuration changed | IOS4-078 «Сечения и геометрия воздуховодов…» (PROVISIONAL_DOMAIN_MAPPING) | M-078 ✔ | keep |
| Warm floors (floor heating) absent | **FREE-HEATING-001** (MATRIX_GAP_CONFIRMED) | M-077 ✘ | **change**: route to FREE-HEATING; case C costs 36 points |

General rule mirrored in `change_matrix_map`:
- Map a change to the closest matrix parameter **of the same engineering system** when one covers that element family, even loosely («provisional domain mapping»).
- Use FREE-* only when no parameter of the system covers the element type (a «matrix gap»).
- Keep `parameter_mapping_status ∈ {SOURCE_MATRIX, PROVISIONAL_DOMAIN_MAPPING, MATRIX_GAP_CONFIRMED}` on each mapping row and export it as an extra field.

### 3.9 Export artefacts

- `submission/<object_id>.json`: schema-valid, validated with `jsonschema` (Draft 2020-12) before writing. It includes the optional gold-named extras.
- `submission-strict/<object_id>.json`: schema fields only.
- `submission/<object_id>.sidecar.json`, a separate file that is not submitted inside the answer: `input_manifest_hash` (sha256 of the object's manifest rows), `config_hash`, `matrix_version`, `model_version`, `dataset_version`, code version, run time, per-file processing status, and a list of files not found locally.

Minimal example (Тюменская, three rows):

```json
{"object_id": "OBJ-TYUMENSKAYA-5-GOLD-SEED",
 "checks": [
  {"parameter_code": "IOS4-078", "location": "314",
   "pd_value": "Конфигурация вентиляции по листу 10 ПД", "rd_value": "Конфигурация вентиляции изменена", "id_value": null,
   "violation_label": "VIOLATION_PRESENT", "protocol_status": "CRITICAL", "criticality": "Критическое (приостановка работ)",
   "evidence": [{"stage": "PD", "file_id": "F0171", "pdf_page_number": 88, "document_sheet_number": 10},
                {"stage": "RD", "file_id": "F0201", "pdf_page_number": 18, "document_sheet_number": 4}],
   "comparison_result": "CONFIGURATION_MISMATCH", "location_type": "ROOM", "matrix_scope": "MATRIX"},
  {"parameter_code": "PZ-001", "location": "OBJECT", "pd_value": "… м²", "rd_value": "… м²", "id_value": null,
   "violation_label": "NO_VIOLATION", "protocol_status": "OK", "criticality": "Критическое (приостановка работ)",
   "evidence": [{"stage": "PD", "file_id": "F0155", "pdf_page_number": 3}], "location_type": "OBJECT"},
  {"parameter_code": "IOS2-071", "location": "OBJECT", "pd_value": "… мм", "rd_value": "… мм", "id_value": null,
   "violation_label": "MISSING_DOCUMENT", "protocol_status": "ID_MISSING", "criticality": "Критическое (приостановка работ)",
   "evidence": [{"stage": "PD", "file_id": "F0163", "pdf_page_number": 5}, {"stage": "RD", "file_id": "F0204", "pdf_page_number": 5}],
   "location_type": "OBJECT", "document_status": "PD_RD_AVAILABLE_ID_MISSING"}]}
```

The PZ-001 and IOS2-071 page numbers above are placeholders, not verified evidence pages. The third row shows rule 3 of §3.3: PD↔RD agree, but the as-built ИД required for this parameter is absent. A parameter with only one available stage (e.g. KR-058 on Тюменская, which has no КР RD or ИД) would instead be `COMPARISON_IMPOSSIBLE` (rule 1).

---

## 4. Local scorer spec: `inspector-score`

`inspector-eval` (06 §3.10) stays as the ТЗ v1.1 §14.3 harness (OCR CA, EM, linkage, IoU, FPR). `inspector-score` is a separate, smaller tool that replicates **the package's** 60/15/15/10 + gate contract. Both live in the offline eval image.

### 4.1 CLI

```
inspector-score run   --gold CHECKS.jsonl [--groups GROUPS.jsonl] --pred DIR|FILE.json
                      --manifest document_manifest.jsonl --catalog parameter_catalog_132.jsonl
                      --split-policy split_policy.json --weights scoring_summary_without_answers.json
                      --split TRAIN_PUBLIC|DEV|SYNTH [--objects OBJ,...]
                      [--key k1|k3] [--loc-metric recall|jaccard|anyhit] [--with-stage true|false]
                      [--value-threshold 0.85] [--location-norm strict|light|relaxed]
                      [--gate key|strict|broad] [--out DIR]
inspector-score validate --pred FILE.json      # JSON Schema 2020-12 + integrity rules only
inspector-score sweep  --gold … --pred-dir RUNS/ --grid thresholds.yaml   # dev calibration only
```

Exit codes: 0 ok; 2 schema-invalid prediction; 3 gate triggered; 1 error. `run` refuses `--split TEST_HIDDEN`, and refuses any `--objects` value listed as TEST_HIDDEN in `split_policy.json` (hard-coded guard, §4.9).

### 4.2 Inputs and validation

- The prediction is validated against `submission_schema.json` (a local copy with checksum pinned to the package `sha256sums.txt`). An invalid file scores 0 on all components, and the error is reported.
- Gold rows are filtered to `score_eligible = true` and the requested objects. Groups are optional (needed for K3).

### 4.3 Normalisation (versioned and published in the README)

| Item | `strict` | `light` (default) | `relaxed` |
|---|---|---|---|
| parameter_code | upper, trim | + alias resolution to catalog code | + prefix-agnostic by id |
| location | trim | NFC, casefold, ё→е, collapse spaces, strip «пом.», «помещение», «№» prefixes; **keep leading zeros** | + strip leading zeros, strip «венткамера/тех. помещение» nouns |
| values | exact | NFC, casefold, ё→е, strip punctuation «»"().,;:, collapse spaces; numbers: comma→dot, thin spaces, units to canonical (м², м³, мм, м) | + token-set similarity |
| criticality | exact | normalised text | prefix («Критическое»/«Существенное») |

### 4.4 Metrics

- F1 (K1 primary; K3 group, K4 strict, and multi-label variants), P, R, TP/FP/FN lists.
- Localisation (recall primary; Jaccard, any-hit, with and without stage).
- Value+status (status-only, values-only, combined).
- Integrity (per rule).
- Total, and the gate with the list of missed checkpoints.
- Breakdowns by section (catalog `pd_section`, FREE → «СВОБОДНЫЙ ПОИСК»), by criticality, by comparison_result, by object.
- Uncertainty: Wilson 95 % CI for P/R, and an object-cluster bootstrap when ≥ 5 objects (dev plus synthetic), as in 06 §3.10.

### 4.5 Gate report

Lists every approved critical checkpoint (key, group, evidence) as FOUND, FOUND_WRONG_EVIDENCE or MISSED. Adds a what-if (score if hedges were removed) and a hedge count and budget check. `sweep` plots F1 against critical-emission threshold alongside P(no gate) on dev.

### 4.6 Integrity rules (the §2.6 list, as machine checks)

`R1` schema valid · `R2` object_id in the requested split · `R3` evidence file in manifest · `R4` same object · `R5` not excluded · `R6` `.pdf` and page in range · `R7` stage consistent (RD_ID_MIXED accepts RD/ID; UNKNOWN never) · `R8` duplicate_group representative only · `R9` no superseded revision cited when a newer revision of the same `document_code` exists (from our revision resolver) · `R10` no duplicate keys · `R11` codes ∈ catalog ∪ FREE-* · `R12` criticality equals the catalog for matrix codes · `R13` `protocol_status` consistent with label and criticality (§3.2) · `R14` no TRAIN file_id in a TEST file · `R15` locations follow the §2.7 grammar (warning only).

### 4.7 Outputs

`score.json` (all numbers, variants, versions, gold and pred sha256), `per_check.csv`, `gate.csv`, `summary.txt`. The HTML report is optional; I recommend reusing the `inspector-eval` template.

### 4.8 Dev data and the leave-object-out discipline

| Dev object | Labels | Origin | Use |
|---|---|---|---|
| Тюменская (T) | 10 organizer checks (positives only) | package gold | calibration of mapping, page anchoring, gate |
| Pilot 9 objects from «Комплект предметной разметки» (P1…P9) | 1 CONFIRMED + 7 CANDIDATE + 1 NEGATIVE evidence groups, converted by us to the submission format with our own file ids (`PIL-…`) | organizer pilot, our conversion (badged) | positives and a negative, room-level explications |
| Новослободская-dev (N) | ~20–30 checks labelled by the user or a teammate: MISSING_DOCUMENT, NO_VIOLATION, COMPARISON_IMPOSSIBLE and any real discrepancies. Mostly ИД котлована + КР | **our labels, badged «разметка команды»** | negatives, ИД scans, status accuracy |
| Synthetic S1…Sk | generated | ours, badged | stress: gate, hedging, revisions, archives |

Rules:
1. For every tunable (critical and substantial emission thresholds, hedge rule, anchor-page rule, value templates, FREE thresholds, location grammar), report leave-one-object-out: tune on all dev objects but o, score o, and average over o.
2. Tuning on T and then scoring T is reported as «seen», never as a result.
3. The final config is tuned on all dev objects, then **frozen**: `config_hash` recorded and git tag `hidden-run-freeze`.
4. The mapping rules seeded from T (§3.8) are declared in the report as learned from T.

### 4.9 Hidden-test integrity rules (Речников)

1. **No tuning on Речников.** Thresholds, dictionaries, mapping tables, value templates, prompts and page-anchoring rules are frozen before the first Речников run. `inspector-score` refuses TEST_HIDDEN, and CI greps code and config for Речников-specific constants: file ids F0205–F0417, room numbers, and strings from its documents.
2. **No manual answers.** Nobody reads Речников documents to create, correct or remove findings, and no human-in-the-loop decisions go into the submission. OCR and extraction review sessions (U-24) use TRAIN, pilot and synthetic data only.
3. **Robustness fixes only.** A rerun on Речников is allowed only after a crash or timeout fix that is content-agnostic (format, memory, archive handling, the 658 MB PDF). Each rerun is logged with a diff and reason, with no threshold or dictionary change.
4. **Registry discipline.** The manifest is the only registry. Never read or cite F0149 or F0418. Resolve by sha256. Evidence comes only from OBJ-RECHNIKOV-7-7 files.
5. **One object per answer file.** The TEST file contains only `OBJ-RECHNIKOV-7-7` and no TRAIN evidence.
6. **Versioning.** The sidecar records `input_manifest_hash`, `config_hash`, versions and run timestamps (ТЗ v1.1 §14.2 «Версионность»).
7. **Data handling.** Organizer documents never leave the machine: no cloud LLM or OCR on Речников content unless the user explicitly approves (LLM usage is still open, U-01). Any LLM step must be part of the frozen pipeline, not ad-hoc prompting on hidden content.

### 4.10 Scorer acceptance tests

- Gold copied as the prediction gives 100.
- Empty prediction gives 0 plus the gate report.
- Cases B–J of §2.3 reproduce the listed numbers under H1 defaults.
- A prediction citing F0149 fails R5; one with a TRAIN file in a TEST file fails R14.
- Alias inputs (`KR-55`, `КР-55`, `M-055`) score like `KR-055` in `light` mode and fail in `strict`.
- Room «12» vs «012» fails in `light` and passes in `relaxed`.

---

## 5. Приложение № 2: exact form and renderer contract

### 5.1 Verbatim structure (text as in the docx; `{…}` are our bindings)

```
ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № {protocol_no}                 ← sample: «2026-07-01-ОКС»
Объект: {object.name}
Адрес: {object.address}
Номер надзорного дела: {object.supervision_case_no}
Застройщик: {object.customer}
Подрядчик: {object.contractor}
Дата формирования: {generated_at: «1 июля 2026 г.»}
Версия протокола: {version} ({«предварительная» | «окончательная»})
Статус: {status_line}                                             ← sample: «⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)»
[added] Тип проверки: {scenario} ({scenario_ru})                  ← required by ТЗ §9.2 п.4, absent in the sample

РАЗДЕЛ 1. СТАТУС ЗАГРУЗКИ ДОКУМЕНТОВ
| Тип документа | Статус | Загружено файлов | Ожидается | Комментарий |
| ПД | ✅ Полностью | 8 | 8 | Все файлы загружены |
| РД | ✅ Полностью | 3 | 3 | Все файлы загружены |
| ИД | 🟡 Частично | 8 из 15 | 15 | Отсутствуют 7 файлов |

РАЗДЕЛ 2. СВОДНАЯ СТАТИСТИКА (С ПРОЦЕНТАМИ)
| Показатель | Количество | % от общего |
| Всего параметров в Матрице | 132 | 100% |
| Проверено успешно (есть ПД, РД, ИД) | 112 | 84,8% |
| Не проверено (отсутствует ИД) | 18 | 13,6% |
| Не загружены документы (технические ошибки) | 2 | 1,6% |
| Выявлено нарушений (всего) | 12 | 9,1% |
| ─ Критических (приостановка) | 6 | 4,5% |
| ─ Существенных (предписание) | 6 | 4,5% |
| Подозрений ИИ (свободный поиск) | 3 | 2,3% |

РАЗДЕЛ 3. ПАРАМЕТРЫ, НЕ ПРОВЕРЕННЫЕ ИЗ-ЗА ОТСУТСТВИЯ ИД — {n}
| № | Код | Раздел | Параметр | Отсутствующий файл |
| 1 | KR-58 | КР | Толщина фундаментной плиты | Акт_АОСР_фундамент.pdf |  … 18 rows

РАЗДЕЛ 4. КРИТИЧЕСКИЕ НАРУШЕНИЯ — {n}
| № | Раздел | Параметр (код) | ПД | РД | ИД | Отклонение | Решение инспектора |
| 1 | КР | Класс бетона (KR-55) | B35 | B25 | B25 | ⬇️ Понижение класса | ✅ Подтверждено |

РАЗДЕЛ 5. СУЩЕСТВЕННЫЕ НАРУШЕНИЯ — {n}
| № | Раздел | Параметр (код) | ПД | РД | ИД | Отклонение | Решение инспектора |
| 7 | СПЗУ | Площадь асфальтобетонного покрытия (СПЗУ-25) | 850 м² | 720 м² | 715 м² | ⬇️ Уменьшение на 16% | ✅ Подтверждено |

РАЗДЕЛ 6. ПОДОЗРЕНИЯ ИИ — {n}
| № | Метод | Описание | ПД | РД | ИД | Решение инспектора | Причина отклонения | Комментарий ИИ |
| 1 | Логический анализ | Отсутствует лифт при 15 этажах | Предусмотрен | Отсутствует | Отсутствует | ⏳ Ожидает | — | — |
| 2 | Семантический диссонанс | Техническое → Склад ГСМ | … | ❌ Отклонено | Помещение действительно является складом ГСМ, … | 🤖 ИИ СОГЛАСЕН (94%). Причина обоснована. Рекомендуется обновить словарь терминов. Отправлено в дообучение. |

РАЗДЕЛ 7. РЕЗОЛЮТИВНАЯ ЧАСТЬ
7.1. По критическим нарушениям
| № | Вид работ | Конкретная рекомендация |
| 1 | Бетонирование несущих конструкций (KR-55) | Представить перерасчёт несущей способности … подтверждённый испытаниями. |
7.2. По существенным нарушениям
| № | Вид нарушения | Конкретная рекомендация |
| 1 | Уменьшение площади асфальтобетонного покрытия на 16% (СПЗУ-25) | Представить корректировку проекта благоустройства … |
```

The full sample rows are in the scratchpad dump `s93/app2.txt`. The renderer golden test reproduces the sample byte for byte in text (§5.6).

### 5.2 Formatting spec (measured from the docx)

- A4 **portrait** (11906×16838 twips). Margins: top 20 mm, bottom 20 mm, left 30 mm, right 15 mm (ГОСТ).
- Font **Segoe UI**, colour #0F1115. Title and «РАЗДЕЛ N…» headings 16.5 pt bold. «7.1./7.2.» subheadings 15 pt bold. Header block 12 pt with bold labels («Объект:», «Адрес:»…). Tables 11.5 pt.
- Heading paragraphs have 12 pt space after, and there is 24 pt spacing between sections.
- Tables use single 0.5 pt borders on all edges and inside, white fill, no header shading. Header row bold only in sections 4–5 (inconsistent in the sample; we bold every header row).
- The header block is two paragraphs with soft line breaks.
- For PDF: embed **Selawik** (SIL OFL, metric-compatible Segoe UI substitute) and **Noto Color Emoji**. The DOCX keeps «Segoe UI» as the declared font. The emoji set to support is: ⚠️ ✅ 🟡 ❌ ⬇️ ⬆️ ⏳ 🤖, plus our additions ❓ 🔄 🔒 ☑️.

### 5.3 Anomalies in the sample (handle deliberately, do not copy)

1. **Not all percentages are plain rounding.** 2/132 = 1.52 % is printed as «1,6%» so that 84,8 + 13,6 + 1,6 = 100,0. The other percentages (9,1; 4,5; 2,3) are plain rounding. Rule: the partition rows (checked / not checked / technical errors / our added rows) use largest-remainder rounding to sum to 100,0 %. Other rows use half-up rounding to one decimal, with a decimal comma and «%» without a space.
2. The status is «ОЖИДАЕТ ВЕРИФИКАЦИИ», yet every violation shows «✅ Подтверждено». Our renderer shows the true decision.
3. Codes mix Latin and Cyrillic prefixes, and AR-14 is wrong (§3.6).
4. Section 3 lists hypothetical file names. We print the **expected document type** from `id_completeness_checklist.json` (e.g. «АОСР на устройство фундаментной плиты — не представлен»), because expected file names are unknowable.
5. Numbering in sections 4→5 is continuous (1…6, 7…12). Sections 6, 7.1 and 7.2 restart at 1. We keep this.
6. The label «Проверено успешно (есть ПД, РД, ИД)» is misleading in PD_RD scenarios. Keep the label and add the footnote «с учётом сценария {scenario}: сравнение выполнено по доступным стадиям».

### 5.4 Data binding per section

| Section | Rows come from | Rules |
|---|---|---|
| Header | `objects` (name, address, supervision_case_no, customer, contractor), protocol row | `protocol_no = {YYYY-MM-DD}-{object_code}-{seq}`. Status line by process/protocol status: READY → «⚠️ ОЖИДАЕТ ВЕРИФИКАЦИИ (дозагрузка возможна)» (verbatim); VERIFYING → «🔄 ВЕРИФИКАЦИЯ В ПРОЦЕССЕ (дозагрузка возможна)»; COMPLETED → «☑️ ВЕРИФИКАЦИЯ ЗАВЕРШЕНА, ПРОТОКОЛ НЕ ФИНАЛИЗИРОВАН (дозагрузка возможна)»; FINALIZED → «🔒 ПРОТОКОЛ ФИНАЛИЗИРОВАН (дозагрузка невозможна)»; recheck running → suffix «· выполняется инкрементальная проверка». «Версия протокола: N (предварительная)» becomes «(окончательная)» only for PROTOCOL_FINALIZED |
| 1 | `upload_status` per stage, registry counts, completeness checklist | Status ✅ Полностью (X_UPLOADED) / 🟡 Частично (X_PARTIAL) / ❌ Отсутствует (X_MISSING, our addition). «Загружено файлов» = accepted files, or «k из n» when partial. «Ожидается» = registry-declared plus checklist-expected count. «Комментарий»: «Все файлы загружены» / «Отсутствуют N файлов» / rejected files with reason. The line «Тип проверки: …» is repeated under the table |
| 2 | param-level statuses (§3.2–3.3) | Rows 1–4 verbatim. Then our rows, shown only when non-zero: «Не проверено (отсутствует ПД/РД)», «Не проверено (конфликт редакций, требуется уточнение)», «Неприменимо к объекту». Rows 1–4 plus these partition 132. «Выявлено нарушений (всего)» = CANDIDATE (pending or clarification) + CONFIRMED, excluding rejected. After «─ Существенных» we add «─ из них подтверждено инспектором \| k \| x%». Footnote: «До подтверждения инспектором расхождения являются кандидатами и не являются основанием для приостановки работ или выдачи предписания (п. 9.2 ТЗ)». «Подозрений ИИ» = all suspicions of the version |
| 3 | params with `ID_MISSING` | Code = catalog code; Раздел = short section; Параметр = short name (new `short_name` column, e.g. «Толщина фундаментной плиты»); «Отсутствующий файл» = expected ИД document type |
| 4 / 5 | VIOLATION_PRESENT matrix findings (atomic rows aggregated per parameter and location set), split by criticality | «Параметр (код)» = «{short_name} ({code})» plus «, пом. 140, 142» when location-level, plus «[карточка Б.n]». ПД/РД/ИД values in Russian format, «—» when not applicable, «нет данных» when missing. «Отклонение» = arrow + verb + magnitude (⬇️ Понижение класса / Снижение на Δ / Сужение на Δ / Уменьшение на X% / Занижение сечения / Экономия X%; ⬆️ Превышение X%; ❌ Полное отсутствие / Отсутствуют N {ед}; 🔄 Изменена конфигурация). Percent relative to ПД. «Решение инспектора» ∈ ⏳ Ожидает / ✅ Подтверждено / ❌ Отклонено / ❓ Требует уточнения. Converted FREE findings appear here with «(свободный поиск)» |
| 6 | `suspicions` | «Метод» ∈ Логический анализ / Семантический диссонанс / Нормативный анализ / ML-паттерн-анализ / Графическое сравнение (our 5th method, B07). «Комментарий ИИ» from the Module 4 verdict: «🤖 ИИ СОГЛАСЕН (NN%). …» / «🤖 ИИ НЕ СОГЛАСЕН (NN%). …» / «🤖 ИИ НЕ УВЕРЕН (NN%). …». «Отправлено в дообучение» is rendered as «Отправлено в дообучение (черновик набора, после проверки куратором)», which keeps the sample wording and satisfies ТЗ v1.1 §9.4 |
| 7.1 / 7.2 | Rows of sections 4 and 5 | 7.1 «Вид работ» = `params.work_type` + «({code})». 7.2 «Вид нарушения» = «{Отклонение text} {short_name} ({code})». «Конкретная рекомендация» = `params.recommendation_template`, filled with PD value, normative minimum and required ИД («Представить …»). In a preliminary version every recommendation carries the prefix «Проект рекомендации (до подтверждения инспектором): ». This needs **132 work_type + recommendation templates plus a FREE fallback**, drafted once and expert-reviewed (U-18). Deterministic at runtime |

### 5.5 How the §9.2 п.4 five tables and the 7 sections coexist

ТЗ v1.1 §9.2 п.4 requires «Статус загрузки документов», «Тип проверки», five separate tables ((1) комплектность и сопоставимость; (2) предварительные кандидаты; (3) подтверждённые инспектором нарушения; (4) проверенные отрицательные результаты; (5) гипотезы свободного поиска), and an evidence card per candidate with finding_id, код, expected/actual, file_id and SHA-256 of each source, стадия, шифр, редакция, статус утверждения, лист/страница, bbox/polygon, обоснование, уровень риска, решение инспектора and причина решения. Both ТЗ versions also make Приложение 2 mandatory for «содержание и оформление».

Layout that satisfies both literally:

1. **Body = Приложение 2's 7 sections**, same titles, column sets and order. Two additions only: the «Тип проверки» line (header plus under Раздел 1) and the added rows and footnote of Раздел 2. Each row of sections 4–6 carries its card reference «[карточка Б.n]».
2. **ПРИЛОЖЕНИЕ А. РАЗДЕЛЬНЫЕ ТАБЛИЦЫ (п. 9.2 ТЗ)**:
   - А.1 Комплектность и сопоставимость: every non-COMPLETE parameter with status, stage, document, reason and action. This is a superset of Раздел 3.
   - А.2 Предварительные кандидаты: CANDIDATE pending or clarification.
   - А.3 Подтверждённые инспектором нарушения.
   - А.4 Проверенные отрицательные результаты: system and inspector NEGATIVE_VERIFIED with reason_code and «Комментарий ИИ». Rejected matrix findings get their reason and AI comment here, because sections 4–5 have no such columns.
   - А.5 Гипотезы свободного поиска: a superset of Раздел 6 with confidence and normative base.
   - Banner on А.2 and А.5: «Не являются нарушениями до решения инспектора».
3. **ПРИЛОЖЕНИЕ Б. КАРТОЧКИ ДОКАЗАТЕЛЬСТВ**: one card per candidate, confirmed and rejected finding. All mandatory fields, plus PD/RD/ID thumbnails with blue (expected) and red (actual) frames, per 04 §3.10. Cards may use landscape section breaks.
4. **ПРИЛОЖЕНИЕ В. РЕЕСТР ВХОДНЫХ ФАЙЛОВ И ВЕРСИИ**: file_id, name, stage, discipline, шифр, редакция, approval status, pages, SHA-256, used or excluded (reason); matrix, model, dataset and parser versions; `input_manifest_hash`, `content_sha256`.
5. Signature block (04 §3.10), then the finalisation stamp.

### 5.6 Format parity and tests

- One canonical protocol JSON with blocks `appendix2` (sections 1–7), `tz92_tables` (1–5), `evidence_cards`, `input_registry` and `submission_checks`. PDF, DOCX and XML are views of it, and the submission is derived from the same run.
- Golden test: feeding the sample's numbers as fixture data must reproduce every Приложение 2 string (titles, column headers, row labels, emoji, «─» indents, number formats), except the documented deviations of §5.3.
- DOCX via a `protocol_template.docx` authored from the sample itself (styles copied), so a reviewer who opens both sees the same document.

---

## 6. ТЗ delta: package v1.0 vs the PDF we analysed (v1.1)

### 6.1 Chronology and governing text

| Date (docProps / PDF metadata) | Document | Set |
|---|---|---|
| 2026-06-30 | «Легенда к матрице.docx» | v1.0 package |
| 2026-07-01 | «ПРИЛОЖЕНИЕ 2. ПРИМЕР ПРОТОКОЛА СРАВНЕНИЯ.docx» | v1.0 package |
| 2026-07-08 | ТЗ docx («Версия документа: 1.0», «Дата утверждения: 15 июля 2026 года»); «ПРИЛОЖЕНИЕ 1. Матрица сравнения 132 параматеров.xlsx» | v1.0 package |
| 2026-07-27 | «ПОДРОБНЫЙ ПЕРЕЧЕНЬ СИПОЛНИТЕЛЬНОЙ ДОКУМЕНТАЦИИ.docx» (4 images only) | v1.0 package |
| 2026-08-11 | package v2.0 assembled (`assembly_report.json`) | scoring data |
| 2026-08-17 | «Матрица_параметров_редакция1.1.xlsx», «Перечень_исполнительной_документации_редакция1_1.docx» | v1.1 |
| 2026-09-12 | «10. Мосстройнадзор.pdf» (PDFMaker from Word) | v1.1 |

Ruling:
- Requirements come from **v1.1**, the latest. The v1.0 texts remain binding where v1.1 is silent: Приложение 2 is mandatory in both, and the protocol status table and colours exist only in v1.0.
- Scoring follows the package.
- 91_tz_traceability gets a «v1.0 delta» column.

### 6.2 Substantive differences, section by section (word-level diff; typographic changes ignored)

| § | v1.0 docx (package) | v1.1 PDF (ours) | Impact |
|---|---|---|---|
| Title | «ТЕХНИЧЕСКОЕ ЗАДАНИЕ НА РАЗРАБОТКУ СЕРВИСА «ИИ-ИНСПЕКТОР»», Заказчик Мосгосстройнадзор, «Разработчик: Определяется по конкурсу», date 15.07.2026, «Версия документа: 1.0» | Cover «ИИ-сервис отслеживания и анализа изменений между стадиями проектирования, а также контроля исполнительной документации / Техническое задание 2026»; no version block | Cite both in docs |
| 1.2 | Extra functions: «формирование протоколов проверки с юридически значимым содержанием»; «самообучение на основе решений инспектора (дообучение моделей ИИ)» | Both removed | v1.1 softens legal significance and self-learning (controlled retraining) |
| 2–6 | Normative base, ПД sections, RD and ИД composition, matrix↔docs table | **Identical** | none |
| 7 (modules 2–5) | 2 «Автоматическое сопоставление значений из ПД, РД, ИД; расчёт дельт; формирование предварительного протокола с адресацией (лист, страница)»; 3 «… обязательное поле «Причина отклонения»; статусы: «Подтверждено», «Отклонено», «Требует уточнения»»; 4 «Обратная связь ИИ (вердикт + дообучение) … формирование вердикта (согласен/не согласен); аргументация; автоматическое дообучение»; 5 «Модуль свободного поиска нарушений … (4 подхода …)» | 2 «Связка актуальных редакций ПД/РД/ИД; раздельные статусы комплектности и findings; обязательные карточки доказательств»; 3 «… присвоение CONFIRMED_VIOLATION, NEGATIVE_VERIFIED или CLARIFICATION_REQUIRED; атомарные решения»; 4 «Обратная связь и управляемое дообучение: Версионированный GOLD …; объектное разбиение; публикация модели только после приёмки»; 5 «Модуль свободного поиска гипотез: Формирование SUSPICION вне Матрицы; без включения в число нарушений и GOLD до доказательной привязки и решения инспектора» | Our design already follows v1.1. The Приложение 2 vocabulary (Подтверждено/Отклонено, ИИ СОГЛАСЕН) is v1.0 and is used for display |
| 8.1 | `criticality_level VARCHAR(50)` «Критическое (приостановка)» или «Существенное (предписание)» | `review_priority` «HIGH / MEDIUM / LOW — только очерёдность экспертной проверки; не юридическое действие» | **Keep both**: `criticality_level` drives the submission, Приложение 2 sections 4/5 and 7; `review_priority` drives ordering. Mapping 1:1: Критическое ↔ HIGH, Существенное ↔ MEDIUM (106/26) |
| 8.2 | Last column «Критичность: Критическое» | «Приоритет проверки: HIGH» | same |
| 9.1 purpose | «Загрузка файлов ПД, РД, ИД; извлечение данных по 132 параметрам; контроль наличия документов; адаптация под сценарий загрузки» | Adds identification of стадия, шифр, раздел, редакция, статус утверждения; «построение связок сопоставимых актуальных документов»; «извлечение значений и координат доказательных фрагментов»; «отдельный контроль комплектности» | — |
| 9.1 OCR | «Tesseract или Amazon Textract … кеше (Redis) … не менее 95%» at ≥ 300 DPI | «технология распознавания выбирается исполнителем»; hidden fixed sample; CA = 1 − CER ≥ 0,95; EM key fields (шифр, стадия, редакция, лист/страница, номер помещения или элемента) ≥ 0,90; NFC plus whitespace normalisation; handwriting → LOW_QUALITY/ABSTAIN | Our OCR choice (RapidOCR PP-OCRv5) is legitimate under v1.1. Under v1.0, «Tesseract или Amazon Textract» reads as prescriptive, so keep the Tesseract fallback (already in the stack) and say so |
| 9.1 storage | «Запись в таблицу Checks с указанием ссылок на файлы и страницы» | Full provenance per value plus normalised bbox in [0;1] after CropBox/MediaBox/Rotate | — |
| 9.1 revisions | — | New «Выбор актуальной редакции» paragraph (mandatory registry fields; latest approved revision; conflicts → CLARIFICATION_REQUIRED; superseded never a reference) | Present only in v1.1 and Перечень 1.1. The package supplies the manifest instead, with **no revision or approval fields** (§7 plan change 6) |
| 9.2 purpose | «Автоматическое сопоставление значений из ПД, РД, ИД; выявление расхождений; формирование предварительного протокола с учётом фактически загруженных документов и их статуса» | «формирование доказательной группы «объект + параметр/правило + актуальные ПД/РД/ИД» … Единицей результата является доказательная группа» | Internal unit = evidence group; submission unit = atomic check |
| 9.2 alg. п.1 | «Загрузка из БД всех 132 параметров (таблица Params) и статусов файлов (таблица Files)» | «загрузка версии Матрицы … реестра файлов и цепочек редакций. Версии … фиксируются в каждом запуске и в протоколе» | — |
| 9.2 alg. п.3 | «Если все три документа доступны → … статус: OK / WARNING / CRITICAL. Если доступны только два документа → парное сравнение, отсутствующий документ маркируется как MISSING. Если доступен только один тип или ни одного → проверка невозможна (COMPARISON_IMPOSSIBLE)» | Applicability → completeness → actuality → comparability first; CANDIDATE / NEGATIVE_VERIFIED; CONFIRMED_VIOLATION only by the inspector; pairwise with NOT_APPLICABLE for an unneeded stage; MISSING_EVIDENCE «без включения записи в число нарушений»; NOT_COMPARABLE / CLARIFICATION_REQUIRED | **The v1.0 rule is the submission's `protocol_status` logic** (§3.3). The v1.1 rule is our internal logic |
| 9.2 alg. п.4 | «Включается таблица нарушений с указанием кода, наименования, значений в ПД/РД/ИД, статуса и рекомендаций» | Five separate tables plus mandatory evidence card fields | §5.5 coexistence |
| 9.2 statuses table | OK / WARNING / CRITICAL / ID_MISSING / RD_MISSING / PD_MISSING / PARTIALLY_LOADED / COMPARISON_IMPOSSIBLE with colours and actions (§3.4) | NEGATIVE_VERIFIED / CANDIDATE / CONFIRMED_VIOLATION / MISSING_EVIDENCE / NOT_APPLICABLE / NOT_COMPARABLE / CLARIFICATION_REQUIRED / SUSPICION with «Включение в число нарушений»; plus the risk-level disclaimer | Both enums kept, with a fixed mapping |
| 9.3 statuses | PENDING, CONFIRMED («передаётся в ИАИС РИН»), REJECTED, CLARIFICATION_REQUIRED, **PARTIALLY_CONFIRMED**, VERIFICATION_COMPLETED, PROTOCOL_FINALIZED | PENDING, CONFIRMED_VIOLATION (positive GOLD), NEGATIVE_VERIFIED (negative GOLD), CLARIFICATION_REQUIRED, VERIFICATION_COMPLETED, PROTOCOL_FINALIZED; PARTIALLY_CONFIRMED replaced by splitting into atomic findings | Train gold uses `inspector_status: "CONFIRMED"` (v1.0). Our API maps CONFIRMED_VIOLATION ↔ CONFIRMED and NEGATIVE_VERIFIED ↔ REJECTED as aliases. The «Разделить» action covers PARTIALLY_CONFIRMED |
| 9.3 algorithm | «Система отображает таблицу нарушений. Параметры с отсутствующими документами подсвечены …»; finalise: «Система проверяет наличие параметров с ID_MISSING и выводит предупреждение. При подтверждении протокол финализируется и передаётся в ИАИС РИН» | Simultaneous expected/actual view with highlighted pages, шифры, редакции, approval status, approved-change link; completeness shown separately; decisions with user_id, timestamp, comment; reject needs reason_code plus comment; finalise only after all CANDIDATE are processed or explicitly moved to CLARIFICATION_REQUIRED; only confirmed records go to РиН, with versions and the input registry | Keep the v1.0 «ID_MISSING» warning at finalisation as a non-blocking warning (it already is in 90 §3.2.4) |
| 9.4 | «Модуль обратной связи ИИ (Вердикт + Дообучение)». Table of 4 scenarios with verdicts AGREE / DISAGREE / CLARIFICATION / CONFIRMED. ≥ 100 confirmed violations per iteration; 30 % test; automatic rollback when F1 drops > 5 %. Comment examples «ИИ СОГЛАСЕН (уверенность 92%). …» and «ИИ НЕ СОГЛАСЕН (уверенность 97%). …» | «Модуль обратной связи и управляемого дообучения». 3 scenarios (no DISAGREE row). Only CONFIRMED_VIOLATION/NEGATIVE_VERIFIED with full cards; object split; hidden test hashed and never used for thresholds; publish only after §14 thresholds, with ≤ 2 pp recall drop per category and ≤ 2 pp FPR rise; signed decision; rollback; full lineage. System comment examples («Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR …»). Leftover v1.0 headings remain | Приложение 2 «🤖 ИИ СОГЛАСЕН (94%)» follows v1.0. We keep the AI verdict (Rejection_Log.ai_verdict is in both) and render it in the Приложение 2 style |
| 9.5 | «Модуль свободного поиска нарушений … Автоматическое выявление нарушений, не включённых в Матрицу»; JSON example with `"criticality": "КРИТИЧЕСКОЕ"`; deduplication by embeddings («объединяются в одно с повышенной уверенностью … подтверждено несколькими методами») | «Модуль свободного поиска гипотез»; SUSPICION is not a violation; JSON uses `"review_priority": "HIGH"` and `"finding_status": "SUSPICION"`; the dedup text is replaced by «гипотезы объединяются только внутри одного объекта и сопоставимых редакций … для перевода в CANDIDATE требуются конкретные источники и координаты …» | Our suspicion export carries both `criticality` (display) and `review_priority`. The embedding dedup (v1.0) stays as the implementation of the v1.1 merge rule |
| 9.6 | «При критическом сбое (ИАИС РИН недоступна более 1 часа): протокол сохраняется в статусе PENDING_SYNC. Система продолжает попытки отправки каждый час. Протокол не считается финализированным до успешной отправки» | «локально финализированный протокол сохраняет статус PROTOCOL_FINALIZED, а статус синхронизации устанавливается PENDING_SYNC … сбой внешней передачи не отменяет и не изменяет подписанное решение инспектора» | We already follow v1.1 (separate `sync_status`). Document the v1.0 difference |
| 10 | 13 tables. Checks: `pd_value, rd_value, id_value, status, inspector_status, document_status`. Files: `doc_type, file_name, file_hash, file_path, status, version`. Protocols: `content_json, content_pdf`. ML_Retraining_Log: `model_type, training_date, training_data_size, … f1_score, roc_auc, retraining_reason` | 16 tables (+ Evidence_Fragments, Dataset_Items, Model_Versions). Checks: `expected_value, actual_value, completeness_status, finding_status, review_priority, evidence_group_id`. Files: `doc_stage, discipline, document_code, revision, approval_status, approval_date, predecessor_id…`. Protocols: `matrix_version, dataset_version, model_version, input_manifest_hash`. ML log: `model_version, dataset_version, split_hashes, … f1, false_positive_rate, per_category_metrics, approval_status, approved_by` | **Add the v1.0 Checks columns `pd_value, rd_value, id_value, document_status` as stored or generated columns.** They are exactly the submission and gold fields |
| 11–13 | NFR, security, monitoring | Identical except «ИАИС РИН» → «ИАИС «РиН»» | none |
| 14 | — (absent) | «Приёмка качества и требования к эталонному набору»: evidence_group unit, split rules, CA/EM/linkage/IoU/P/R/F1/FPR thresholds | The package scoring is a simplified, weighted variant of §14.3 (no IoU, no FPR threshold) plus the gate |

### 6.3 Приложение 1 (xlsx) vs matrix «редакция 1.1»

- The 132 rows are identical in all seven content columns: section, parameter, unit, source ПД/РД/ИД, trigger. I compared them cell by cell; there were 0 differences. The catalog JSONL equals v1.0 plus codes.
- v1.0 has **no code column**. v1.1 adds `Код параметра` M-001…M-132. The catalog adds `PZ-001…`.
- The column «Уровень критичности» (Критическое (приостановка работ) 106 / Существенное (предписание) 26) became «Приоритет экспертной проверки» (HIGH — обязательная экспертная проверка 106 / MEDIUM — экспертная проверка 26), row-for-row identical.
- v1.1 adds sheets «СХЕМА GOLD», «МЕТРИКИ» and «ПРИМЕРЫ РАЗМЕТКИ». These are not in the package.

### 6.4 «Легенда к матрице» (v1.0 only)

- **Criticality levels (verbatim):** «Критическое нарушение — … угрозу жизни и здоровью граждан (несущая способность, пожарная безопасность, доступность МГН) — Ст. 54 ГрК РФ → приостановка работ до устранения»; «Существенное нарушение — … не создаёт прямой угрозы, но нарушает утверждённый проект или нормативные требования (благоустройство, сроки, материалы) — Ст. 52 ГрК РФ → выдача предписания с ограничением работ»; «Информационное нарушение — … не требует немедленного вмешательства, но должен быть зафиксирован для анализа — Аналитический учёт → без выдачи предписания». The matrix uses only the first two. «Информационное» is a legitimate third level for suspicions and FREE findings displayed in reports. It is never used in the submission, which uses catalog strings.
- **Trigger operators:** `>`, `<`, `≥`, `≤`, `≠`, «Delta > 5%», «отсутствует», «замена», «снижение», «сокращение». These are the official vocabulary for parsing `trigger` text into the rule DSL (B03). Add them to the DSL's text-to-operator table.
- **«Источник» notation:** «25-01-КР-ОД» is a sheet code (объект-проект, раздел, лист «Общие данные»). «л. 4, стр. 2» means «Лист 4 (чертёж), страница 2 (если документ многостраничный)». So «лист» ≠ «страница». The submission uses the PDF page index (confirmed by gold), and the sheet stays as metadata.
- **Discrepancies:**
  - «ИАИС РИН — … «Реестр имущества и недвижимости» (г. Москва)». Both ТЗ versions and ПП Москвы № 397-ПП say «Разрешения и нарушения». The legend is wrong; use «Разрешения и нарушения».
  - «ОКР — Общий журнал работ (форма РД-11-05-2007)»: the abbreviation should be ОЖР, and РД-11-05-2007 is the superseded form.
  - Section numbering «Раздел 9. ППМ … 10. ОДИ … 11. ЗУ … 12. СМ» follows the matrix, not ПП № 87 as listed in ТЗ §3 (9 ППМ, 10 БЭ, 11 ОДИ, 12 СМ, 13 ИН; ТХ = 6). This is already recorded (PLAN §8), and we key by section code.
  - «ЗУ» in the legend means energy efficiency and metering, while ТЗ §3 has no «ЗУ» section.
  - Code «КМ» is used for two things: «Конструкции металлические» (РД марка) and «Класс пожарной опасности строительных материалов». Disambiguate by context (Приложение 2 «Класс отделки (КМ)» is the fire class).

### 6.5 «ПОДРОБНЫЙ ПЕРЕЧЕНЬ …» vs `id_completeness_checklist.json`

- The package docx consists only of **four images, byte-identical** (sha256) to `docs/spec/img_perechen/image1–4.png` (Приложение 19 «Примерный перечень ИД»). The checklist's 111 items were built from those same images plus ТЗ §5 (identical in both ТЗ versions). **The items need no change.**
- The v1.1 Перечень (17 Aug) added a text page: «ОБЯЗАТЕЛЬНЫЙ МАШИНОЧИТАЕМЫЙ РЕЕСТР ФАЙЛОВ», the 11 registry fields, and «ПРАВИЛА ВЫБОРА ИСТОЧНИКА ДЛЯ СРАВНЕНИЯ». This page is the source of the checklist's `PKG-REGISTRY` requirement («без него пакет принимается со статусом CLARIFICATION_REQUIRED»). **It is absent from the package**, and the package ships `document_manifest.jsonl` instead, which lacks document_code, revision, approval_status, approval_date, predecessor/successor and signature_status. `PKG-REGISTRY` must accept the manifest as a registry with status `VALID_WITH_WARNINGS` and derive the missing fields from file names and title blocks (`EXTRACTED_UNCONFIRMED`). Otherwise our own rule would mark every evidence group CLARIFICATION_REQUIRED and the submission would be all COMPARISON_IMPOSSIBLE.
- The docx title keeps the typo «СИПОЛНИТЕЛЬНОЙ». Quote the file name verbatim; do not «fix» it in references.

---

## 7. Plan changes

| # | Change | Why | Affects |
|---|---|---|---|
| 1 | Canonical `params.code` = catalog code (`PZ-001…SM-132`), join by `param_id`. `alias_codes` = [M-xxx, ТЗ/Приложение 2 short Latin and Cyrillic]. Parser per §3.6 | The organizers' scorer keys on catalog codes. All three styles share the id | 90 §3.3.3 / T-13, 03, 04, 08, contracts |
| 2 | New export `submission/<object_id>.json` (+ strict + sidecar). `inspector-batch` produces it. The СХЕМА GOLD export becomes secondary | This is the scored format | 04, 06, 92 |
| 3 | New `inspector-score` (§4), separate from `inspector-eval`; nightly on dev with LOO | Replicates 60/15/15/10 + gate | 06, 91 F-05, 92 |
| 4 | Warm floor → `FREE-HEATING-001` (MATRIX_GAP_CONFIRMED). Keep vent → IOS4-078/079. Add `parameter_mapping_status` to `change_matrix_map` | Organizer taxonomy (case C −36) | 90 §3.12, 03, 07 |
| 5 | Atomic per-location checks; exact room tokens; group anchor pages per stage; sheet→page mapping from title blocks | Gate cases B/J, localisation | 02, 04 |
| 6 | Manifest = registry (VALID_WITH_WARNINGS); file identity by sha256; revision and approval derived from names and title blocks (`кор3` > `кор2`; `Изм N`; `V2_`); near-duplicate detection by text hash (F0310/F0312) | No registry fields in the package; revision pairs in Речников | 01, 90 §3.2.7 |
| 7 | Resolve `RD_ID_MIXED` and `UNKNOWN` stages per file by content | Evidence stage integrity | 01, 02 |
| 8 | Protocol renderer = Приложение 2 form (A4 portrait, ГОСТ margins, Segoe UI / Selawik, emoji) with Приложения А/Б/В (§5.5). Replaces 04 §3.10 landscape/PT Astra | «обязательными для исполнения» | 04, 08 |
| 9 | Add enums `ViolationLabel`, `ProtocolParamStatus` (with colours) and the §3.2 mapping. Add generated Checks columns `pd_value, rd_value, id_value, document_status` | Submission and v1.0 table fields | 90 §3.2.1, 04, packages/contracts |
| 10 | Restore `params.criticality_level` (Критическое / Существенное; «Информационное» for display only) next to `review_priority` | Submission, sections 4/5/7, gate | 03, 90, 04, 08 |
| 11 | New matrix data: `short_name`, `work_type`, `recommendation_template` (132 + FREE fallback), deviation verb per parameter, element nouns for value templates | Sections 3–7, value accuracy | 03, 04 |
| 12 | Gate-aware emission (lower critical threshold, top-2 code hedging when p ≥ 0.1, hedge and FP budgets, FREE only evidence-bound) | §2.4 | 04, 07, 06 |
| 13 | Hidden-test integrity rules (§4.9): freeze tag, CI grep, no manual review of Речников, no cloud processing of it without approval | Fair play and §14.2 | 06, 10, 92 |
| 14 | Evidence only from top-level PDFs; DWG and archives cited through their PDF twins; DOCX change notices as APPROVED_CHANGE context only | Schema needs pdf_page_number | 02, 04 |
| 15 | Recognition priorities for Речников: КЖ (класс бетона, толщины, армирование), АР plans (rooms, doors, corridors), ГП, ЭОМ, ВК; АОСР scan OCR; title-block sheet numbers; room-label extraction | RD coverage (§1.4) and the top-priority block | 02 |
| 16 | Re-extract the organizers' archive (cp866, case-sensitive volume) to recover the 19 Новослободская files; ingestion reports manifest rows without a file | Integrity of the TRAIN pool | 10, 01 |
| 17 | 91_tz_traceability: add a «v1.0 delta» column; record that v1.1 governs and that Приложение 2 plus the v1.0 status table are binding display requirements | Two ТЗ versions | 91 |
| 18 | Status aliases for the API: CONFIRMED ↔ CONFIRMED_VIOLATION, REJECTED ↔ NEGATIVE_VERIFIED; the «Разделить» action covers v1.0 PARTIALLY_CONFIRMED | Gold and v1.0 vocabulary | 05, 90 |

---

## 8. Questions for the user

1. **Original archive.** Do you still have the organizers' original zip (or a download link)? 19 Новослободская files were lost when it was extracted on macOS (cp866 names collided on the case-insensitive disk). Recommendation: yes. We re-extract with `cp866` decoding into the scratch area and verify sha256 against the manifest.
2. **Gate risk appetite.** Should the hidden-test run be recall-first on Критическое parameters, emitting both codes when the mapping is ambiguous and accepting ~2–4 points of F1 per hedge? Recommendation: yes, with a hedge budget of ≤ 20 % of critical checks. One miss caps the whole score at 59.
3. **Dev labels.** Can you or a teammate label ~20–30 checks on Новослободская (negatives, missing documents, any real discrepancies) plus convert the 9 pilot groups, about 2–3 hours? Recommendation: yes. It is the only way to calibrate thresholds without touching Речников. These labels stay badged «разметка команды».
4. **Explicit negatives.** Should the submission contain a row for every parameter (NO_VIOLATION / MISSING_DOCUMENT / COMPARISON_IMPOSSIBLE with location «OBJECT»)? Recommendation: yes. It likely earns status-accuracy points and only hurts if their F1 counts all labels, which we will measure on dev.
5. **Recommendation texts.** May we draft the 132 «Вид работ / Конкретная рекомендация» templates offline with an LLM, then have you or an expert review ~40 of them (КР, АР, СПЗУ, ИОС1–2 first)? The runtime stays deterministic. Recommendation: yes. It is the only realistic way to fill section 7 with the quality Приложение 2 shows.
6. **Submission channel.** Does the hackathon portal state how answers are uploaded (file name, one file per object, zip)? Recommendation if unknown: `OBJ-RECHNIKOV-7-7.json` exactly per schema plus a strict variant, with the sidecar kept separately.

---

## 9. Install needs (none installed for this analysis)

| Package | Why | Where |
|---|---|---|
| `jsonschema` (pure Python) | Draft 2020-12 validation of submissions in exporter and scorer | eval image, ML image |
| `rapidfuzz` | Value-text similarity and token-set ratios in the scorer (already planned for `inspector-eval`) | eval image |
| Fonts: **Selawik** (SIL OFL, Segoe UI metrics), **Noto Color Emoji** | PDF rendering of the Приложение 2 look and emoji markers in Chromium | protocol renderer image |
| `python-docx` or Node `docx-templates` | DOCX from a template authored from Приложение 2 | renderer |
| `unzip` with `-O` (Info-ZIP) or Python `zipfile` with cp866 names | Correct re-extraction of the organizers' archive | dev machine, scratch only |

No Homebrew install was needed. Everything above is either pure Python or fonts inside Docker images.

---

## Appendix A — Scratch artefacts (session scratchpad, `s93/`)

- `score_proto.py`: prototype of the H1 scoring used for §2.3 (not application code).
- `app2.txt`, `legend.txt`, `tz_docx.txt`, `perechen11.txt`: text dumps of the package docx files and the v1.1 Перечень.
- `tzdiff_out.txt`, `tzdiff_sig.txt`: word-level diff of ТЗ docx v1.0 vs PDF v1.1 (210 significant hunks).
- `app2_x/`, `perechen_x/`, `p11/`: unzipped docx parts (formatting and image hashes).
