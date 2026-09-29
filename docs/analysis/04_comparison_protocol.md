# B04 — Comparison and Preliminary Protocol (Module 2, priority High)

Owner block: **B04-comparison-protocol**. Requirement prefix: **CMP-NN**.
Sources used: `01_TZ_text.txt` (full ТЗ), `02_matrix_all_sheets.txt` (МАТРИЦА, СХЕМА GOLD, МЕТРИКИ, ПРИМЕРЫ РАЗМЕТКИ), `03_perechen_ID_registry_rules.txt`, `05_razmetka_poyasn_6p_text.txt`, the 24-page pilot PDF (inspected with PyMuPDF: page boxes, text blocks, Ink annotations, captions), page previews `img_razmetka/*`, `img_perechen/image1.png`.

---

## 0. Executive summary (read this first)

1. **The protocol JSON is the scoring artefact.** Hidden-test metrics (§14.3) are computed "по evidence_group" with "правильный параметр/тип расхождения и корректное доказательство" (file_id + page exact, bbox IoU ≥ 0,50). So every atomic finding in our JSON must be a strict **superset of the СХЕМА GOLD fields with the same names** (`evidence_group_id`, `finding_id`, `object_id`, `matrix_code`, `expected_value`, `actual_value`, `source_expected_file_id`, `…_sha256`, `…_stage/code/revision/approval`, `…_page`, `…_bbox_polygon`, `approved_change_ref`, `completeness_status`, `finding_status`, `review_priority`, `dataset_version`, `matrix_version`, `model_version`), plus a `discrepancy_type`. We also export in the ПРИМЕРЫ РАЗМЕТКИ notation (`PD:ALT79B-000015:стр.19:bbox [0.7800,0.1000,0.9100,0.3500]`).
2. **Bbox convention is confirmed from the pilot.** `[x0, y0, x1, y1]`, normalised to [0;1] of the *visible* page (after CropBox/Rotate), **origin top-left, y downward**. Checked: ALT79B PD p.19 bbox `[0.78,0.10,0.91,0.35]` coincides with the red frame around «Спецификация помещений 1-го этажа» on pilot page 2; UNDMS RD p.4 bbox `[0.2352,0.2019,0.7728,0.2554]` coincides with the change-log row «Металлический бронированный лист … исключён» (pilot p.8, text block `[0.252,0.211,0.611,0.239]`).
3. **Five of nine pilot groups are room-explication / area comparisons** (ALT79B, POL16, DOO25, SOSH25, POL17-negative). A robust *explication-table extractor + room alignment (renumbering-tolerant) + per-room diff* is the single highest-yield capability for the demo and very likely for the hidden test. Two more (UNDMS, LOS3A) are corroborated by the RD «Лист/Ведомость регистрации изменений», so **change-log mining** is the second highest-yield capability.
4. **Pilot contradicts pure matrix-trigger logic.** ALT79B floor totals changed 2797,27 → 2811,07 м² (+0,49 %) and 2513,43 → 2515,70 м² (+0,09 %), below the M-002 trigger «> 1%», yet the experts marked it CANDIDATE because room *functions* changed («Помещение» → «Комната отдыха», «Помещение» → «Раздевалка женская») and areas of rooms 18–21 changed. SOSH25: +18,2 м² (+0,29 %) from an added room 1.109. So the experts' notion of a candidate is *any unapproved deviation of the design decision*, while matrix thresholds govern *priority*. We propose a per-parameter `candidate_policy` (default `DEVIATION`) with the trigger used for risk level. **This is decision D1 for the user.**
5. **Stale-revision safety is explicitly scored** (FPR ≤ 0,10 "на NEGATIVE_VERIFIED и на случаях с устаревшей редакцией"). POL17 is the negative pair, and its PD is «Корректировка №2, 02.2025». The engine must always compare against the latest applicable approved revision and never raise a candidate from a superseded one.
6. **Приложение № 2 (sample protocol) is missing but mandatory.** We propose a layout that copies the visual language of the organisers' own «Графическая фиксация нарушений на чертежах» (6-page pilot): a summary table «№ / Объект сравнения / ПД / РД / Выявленное расхождение», side-by-side ПД (blue frame, «проектное решение, база сравнения») and РД/ИД (red frame, «зона отсутствующего или изменённого решения») crops, a «Вывод» box, and the disclaimer «Все выводы относятся к указанным листам и зонам. Рамка вокруг помещения не означает нарушение всего листа.» We wrap it in the mandatory §9.2 sections. Rendering is template-driven, so the layout can be swapped once Приложение 2 arrives.

---

## 1. Scope

### 1.1 ТЗ clauses covered (owned by B04)

| Clause | Quote / essence | Ownership |
|---|---|---|
| §7, module 2 (High) | «Связка актуальных редакций ПД/РД/ИД; раздельные статусы комплектности и findings; обязательные карточки доказательств» | full |
| §9.2 Назначение | «формирование доказательной группы «объект + параметр/правило + актуальные ПД/РД/ИД», сопоставление значений и геометрии, фиксация предварительного расхождения и его источников. Единицей результата является доказательная группа, а не отдельная страница или файл.» | full |
| §9.2 Приложение № 2 | «Требования к содержанию и оформлению выходного автопротокола … определяются образцом … в Приложении № 2 … и являются обязательными» | full (layout), blocked by missing data |
| §9.2 alg. 1 | «загрузка версии Матрицы из 132 параметров, реестра файлов и цепочек редакций. Версии Матрицы, набора данных и модели фиксируются в каждом запуске и в протоколе.» | full |
| §9.2 alg. 2 | scenarios FULL / PD_RD_ONLY / PD_ID_ONLY / RD_ID_ONLY / SINGLE_ONLY / PARTIALLY_LOADED | full |
| §9.2 alg. 3 | «Сначала проверяются применимость параметра, комплектность доказательств, актуальность и сопоставимость редакций; только после … предметное сравнение»; expected_value/actual_value/delta; CANDIDATE либо NEGATIVE_VERIFIED; CONFIRMED_VIOLATION only by inspector; pairwise + NOT_APPLICABLE; MISSING_EVIDENCE; NOT_COMPARABLE / CLARIFICATION_REQUIRED «не являются нарушением» | full |
| §9.2 alg. 4 | JSON/PDF; «Статус загрузки документов»; «Тип проверки»; tables (1)…(5); evidence card fields | full |
| §9.2 alg. 5 | «Протокол сохраняется в БД (таблица Protocols) с присвоением версии. Статус процесса устанавливается в READY. Инспектор получает уведомление» | full (notification: emits event, delivery by B07) |
| §9.2 Инкрементальное обновление | «не перезапускает всю проверку … только по тем параметрам, для которых появились новые данные. Предыдущая версия протокола сохраняется в истории.» | full |
| §9.2 Статусы параметров | table NEGATIVE_VERIFIED / CANDIDATE / CONFIRMED_VIOLATION / MISSING_EVIDENCE / NOT_APPLICABLE / NOT_COMPARABLE / CLARIFICATION_REQUIRED / SUSPICION + «Уровень риска … только для очередности экспертной проверки … не является автоматическим основанием для предписания» | full |
| §7, module 7 | «экспорт протоколов в PDF, DOCX, XML» | renderers owned by B04; buttons by B07 |

### 1.2 Related clauses (consumed or co-owned)

- §9.1 «Выбор актуальной редакции» (object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, sheet/page, file_hash, predecessor/successor; «Сравнивается последняя применимая утверждённая редакция… CLARIFICATION_REQUIRED… Устаревшая редакция не может использоваться как эталон»). B01 builds the registry; B04 *applies* the selection inside the pipeline (step 3).
- §9.1 p.4 bbox normalisation (CropBox/MediaBox/Rotate). B01 produces; B04 validates and renders.
- §9.1 «Статусы загрузки документов» (PD_/RD_/ID_ UPLOADED/PARTIAL/MISSING) and «Статусы процесса проверки» (PENDING…FINALIZED). B01 owns; B04 prints and sets READY.
- `03_…registry_rules`: mandatory registry; «без него пакет принимается со статусом CLARIFICATION_REQUIRED»; source-selection table; «Перезапись файла под тем же file_id запрещена. Повторная загрузка создаёт новую запись и новую версию протокола.»
- §9.3: evidence card viewing, atomic split («Составной кандидат не получает единый учебный статус PARTIALLY_CONFIRMED»), finalisation rules, «MISSING_EVIDENCE выводится отдельным перечнем», un-finalisation → VERIFICATION_COMPLETED. B03 owns decisions; B04 owns the data model they write into and the protocol snapshots.
- §9.5 SUSPICION structure → table (5). B05 owns.
- §9.6 transfer «только подтверждённые инспектором записи вместе с версиями протокола, Матрицы, модели и реестром входных файлов»; blocking auto re-upload after finalisation. B06 owns; B04 provides the payload.
- §10 tables: **Checks** (#2), **Protocols** (#5), **Evidence_Fragments** (#14) are owned by B04; Params (#1), Files (#4), Objects (#3), Suspicions (#8), Audit_Log (#12), Model_Versions (#16), Dataset_Items (#15) are read.
- §11 NFR #4 (132 params ≤ 2 min), #5 (protocol ≤ 30 s), #7 (NLP per param ≤ 500 ms), #9 (incremental ≤ 1 min), #10 (API p95 ≤ 200 ms for protocol reads).
- §13 structured logs and metrics for comparison/protocol stages; §13 #8 daily hash check covers protocol artefacts.
- §14.1–14.3 evidence_group as labelling unit, versioning, metrics.
- СХЕМА GOLD sheet (field names), МЕТРИКИ sheet («Без полного доказательства finding не засчитывается»), ПРИМЕРЫ РАЗМЕТКИ (9 pilot groups).

### 1.3 Statuses this block emits or prints

- Completeness (group and slot level): `COMPLETE`, `MISSING_EVIDENCE`, `NOT_APPLICABLE`, `NOT_COMPARABLE`, `CLARIFICATION_REQUIRED` (exact enum from СХЕМА GOLD `completeness_status`).
- Finding: `CANDIDATE`, `NEGATIVE_VERIFIED` (system); `CONFIRMED_VIOLATION`, `NEGATIVE_VERIFIED` (inspector, written by B03); `SUSPICION` (B05). The exact enum comes from СХЕМА GOLD `finding_status`.
- Inspector decision (written by B03): `PENDING`, `CONFIRMED_VIOLATION`, `NEGATIVE_VERIFIED`, `CLARIFICATION_REQUIRED`.
- Scenario: `FULL`, `PD_RD_ONLY`, `PD_ID_ONLY`, `RD_ID_ONLY`, `SINGLE_ONLY`, `PARTIALLY_LOADED`.
- Risk: `HIGH` / `MEDIUM` / `LOW` («высокий/средний/низкий»).
- Protocol version status: `GENERATING`, `READY`, `VERIFYING`, `VERIFICATION_COMPLETED`, `PROTOCOL_FINALIZED`, `SUPERSEDED`.

---

## 2. Requirements checklist

Legend: priority = importance for winning (MUST / SHOULD / NICE); MVP = FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

### A. Unit of result, identity, versions

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-01 | The unit of result is the evidence group «объект + параметр/правило + актуальные ПД/РД/ИД», not a page or file | §9.2 Назначение; §14.1 | MUST | FULL | Core of the data model (§3.2) |
| CMP-02 | Stable, deterministic `evidence_group_id` and `finding_id`, identical across protocol versions for the same object/param/scope/element | СХЕМА GOLD «Стабильный идентификатор атомарного finding» | MUST | FULL | Content-derived IDs (§3.6) |
| CMP-03 | At run start, load the Matrix version (132 params + comparison specs), the file registry and the revision chains | §9.2 alg.1 | MUST | FULL | Snapshot loader |
| CMP-04 | Record matrix_version, dataset_version, model_version (plus rules_version and parser_version) in **every run** | §9.2 alg.1; §9.4 | MUST | FULL | `Comparison_Runs` table |
| CMP-05 | Record the same versions in **every protocol** | §9.2 alg.1; §10 Protocols | MUST | FULL | Protocol header and table columns |
| CMP-06 | Each result carries dataset_version, matrix_version, model_version and input_manifest_hash | §14.2 «Версионность» | MUST | FULL | Per-finding fields in JSON |
| CMP-07 | Define and compute `input_manifest_hash` deterministically | §10 Protocols; §14.2 | MUST | FULL | SHA-256 over RFC 8785 canonical registry (§3.6) |

### B. Scenario detection

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-08 | PD+RD+ID → `FULL` | §9.2 alg.2 | MUST | FULL | Truth table (§3.3) |
| CMP-09 | PD+RD, no ID → `PD_RD_ONLY` | §9.2 alg.2 | MUST | FULL | " |
| CMP-10 | PD+ID, no RD → `PD_ID_ONLY` | §9.2 alg.2 | MUST | FULL | " |
| CMP-11 | RD+ID, no PD → `RD_ID_ONLY` | §9.2 alg.2 | MUST | FULL | " |
| CMP-12 | One stage only → `SINGLE_ONLY`; only normative/tolerance rules run | §9.2 alg.2 | MUST | FULL | Axis N only |
| CMP-13 | Partial upload (e.g. 5 of 15 ID files) → `PARTIALLY_LOADED`, with a base scenario retained | §9.2 alg.2 | MUST | FULL | `scenario` + `scenario_base` |
| CMP-14 | The rule set adapts to the scenario: sufficient stage sets per rule | §7 module 1 «адаптация под сценарий загрузки»; §9.2 | MUST | FULL | `sufficient_stage_sets` in the spec |

### C. Per-parameter pipeline and comparison semantics

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-15 | Strict order: applicability → evidence completeness → revision currency and comparability → subject comparison | §9.2 alg.3 | MUST | FULL | Pipeline with a decision trace |
| CMP-16 | NOT_APPLICABLE with a mandatory basis (object attribute, stage phase, document statement) | §9.2 table; 03 «NOT_APPLICABLE с обязательным основанием» | MUST | SIMPLIFIED | Rule-based on the object passport; the inspector confirms |
| CMP-17 | MISSING_EVIDENCE at document level and fragment level; never a violation | §9.2 alg.3; 03 | MUST | FULL | Slot states |
| CMP-18 | Only the latest applicable approved revision is the reference; an outdated revision is never the reference | §9.1; 03 | MUST | FULL | Revision resolver |
| CMP-19 | Revision conflict, missing approval sign or ambiguous predecessor/successor → CLARIFICATION_REQUIRED, and the violation conclusion is blocked | §9.1; 03 | MUST | FULL | " |
| CMP-20 | A superseded revision is kept for audit and excluded from the reference comparison | 03 | MUST | FULL | Shown in table (1) and the registry appendix |
| CMP-21 | No registry → the package is CLARIFICATION_REQUIRED | 03 | MUST | FULL | Package-level flag |
| CMP-22 | Unreadable file, unmatched sheets, non-convertible units or scope mismatch → NOT_COMPARABLE | 03; §9.2 alg.3 | MUST | FULL | Comparability checks |
| CMP-23 | Pairwise comparison when two stages suffice; an absent stage that the rule does not need is NOT_APPLICABLE | §9.2 alg.3 | MUST | FULL | Stage slots |
| CMP-24 | expected_value, actual_value and delta are produced for comparable sources | §9.2 alg.3 | MUST | FULL | Typed values |
| CMP-25 | `number`: unit normalisation, abs/rel tolerance, rounding epsilon, direction | §8.1 data_type | MUST | FULL | §3.5.1 |
| CMP-26 | `enum`: ordinal scales (B35>B30, I>II, КМ0<КМ3 in hazard, EI60>EI30…) | §8.1; matrix triggers | MUST | FULL | §3.5.2 |
| CMP-27 | `string`: normalisation, fuzzy match and semantic equivalence (multilingual Sentence-BERT analogue) | §8.1; §9.1 p.2 | MUST | FULL | §3.5.3 |
| CMP-28 | `boolean`: presence/absence of elements | §8.1 | MUST | FULL | §3.5.4 |
| CMP-29 | `coordinate`: CRS check and distance threshold | §8.1; M-034 «> 0.5 м» | SHOULD | FULL | §3.5.5 |
| CMP-30 | Multi-value parameters (per room, door, window mark, axis, system) → alignment → atomic findings | GOLD «атомарный finding»; §9.3 | MUST | FULL | §3.5.6 |
| CMP-31 | Configuration/graphic diffs (rooms, doors, vent branches, warm floor) represented as findings | §9.2 «сопоставление … геометрии»; pilot | MUST | SIMPLIFIED | Text-layer symbol sets, axis-grid registration, raster fallback (§3.5.7) |
| CMP-32 | Thresholds (min_value/max_value) read from Params at runtime and editable without recoding; every edit bumps matrix_version | §7 module 8; §8.1 | MUST | FULL | Spec references Params columns |
| CMP-91 | Machine-readable comparison spec for all 132 parameters | §8; Appendix A | MUST | SIMPLIFIED | Tier T1 deep (30), T2 generic, T3 simplified or mocked |
| CMP-92 | Params that need external systems (АИС ОСИГ, ГЛОНАСС/РНИС, «Мобильный КПТС»: M-098…M-100) | matrix | NICE | MOCKED | No access; represented as ID-document presence checks |

### D. Status assignment rules

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-33 | The system assigns only CANDIDATE or NEGATIVE_VERIFIED as preliminary finding statuses | §9.2 alg.3 | MUST | FULL | Enforced in code and in the DB check constraint |
| CMP-34 | CONFIRMED_VIOLATION is assigned only by an inspector, after the evidence check and a check that no approved change cancels the requirement | §9.2 alg.3; §9.3 | MUST | FULL | Invariant; B03 writes it |
| CMP-35 | Separate `completeness_status` and `finding_status` («раздельные статусы комплектности и findings») | §7 module 2; СХЕМА GOLD | MUST | FULL | Two columns; finding_status is NULL unless COMPLETE |
| CMP-36 | MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE and CLARIFICATION_REQUIRED are never counted as violations | §9.2 table | MUST | FULL | Summary counter logic |
| CMP-37 | SUSPICION is kept separate: not in the violation count, not GOLD, table (5) only | §9.2; §9.5 | MUST | FULL | Consumes B05 |
| CMP-38 | «Число нарушений» = CONFIRMED_VIOLATION only | §9.2 table «Включение в число нарушений» | MUST | FULL | " |
| CMP-39 | Risk level is used only to order review; printed disclaimer | §9.2 | MUST | FULL | §3.8 |
| CMP-40 | Checks.review_priority is copied from Params (HIGH/MEDIUM/LOW) | §8.1; §10 | MUST | FULL | " |
| CMP-41 | System NEGATIVE_VERIFIED is stored with full evidence as a negative example; optional random sample review | §9.2 table «обязательный отрицательный пример … Просмотр по выборке» | SHOULD | FULL | Sampling flag |
| CMP-42 | Composite candidate → atomic findings; the system atomises when possible and supports inspector split; no PARTIALLY_CONFIRMED | §9.3 p.2 | MUST | FULL | parent/child findings |
| CMP-43 | Evidence card shows the approved change reference (`approved_change_ref` / NONE) | §9.3 p.1; СХЕМА GOLD | MUST | SIMPLIFIED | Registry doc type APPROVED_CHANGE plus auto-hint; the inspector sets the final value |
| CMP-44 | Precision safeguards: FPR ≤ 0,10 on negatives and on stale-revision cases | §14.3 | MUST | FULL | Rounding epsilon, synonym folding, revision resolver, localisation invariant |

### E. Protocol content and formats

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-45 | Structured JSON protocol | §9.2 alg.4 | MUST | FULL | JSON Schema in OpenAPI 3.0 components |
| CMP-46 | PDF protocol | §9.2 alg.4 | MUST | FULL | HTML template → Chromium (Playwright) |
| CMP-47 | DOCX export | §7 module 7 | SHOULD | FULL | docx-templates, Word template |
| CMP-48 | XML export with XSD | §7 module 7 | SHOULD | FULL | xmlbuilder2 + XSD validation |
| CMP-49 | Content/layout per Приложение № 2 | §9.2 | MUST | SIMPLIFIED | Proposed layout (§3.10); template swap once received |
| CMP-50 | Section «Статус загрузки документов» | §9.2 alg.4 | MUST | FULL | |
| CMP-51 | Section «Тип проверки» (scenario) | §9.2 alg.4 | MUST | FULL | |
| CMP-52 | Table (1) комплектность и сопоставимость | §9.2 alg.4 | MUST | FULL | |
| CMP-53 | Table (2) предварительные кандидаты | §9.2 alg.4 | MUST | FULL | |
| CMP-54 | Table (3) подтверждённые инспектором нарушения | §9.2 alg.4 | MUST | FULL | |
| CMP-55 | Table (4) проверенные отрицательные результаты | §9.2 alg.4 | MUST | FULL | |
| CMP-56 | Table (5) гипотезы свободного поиска | §9.2 alg.4 | MUST | FULL | |
| CMP-57 | Evidence card for every candidate: finding_id, param/rule code, expected/actual, file_id and SHA-256 of each source, stage, шифр, редакция, approval status, sheet/page, bbox/polygon, обоснование, risk level, inspector decision and reason | §9.2 alg.4 | MUST | FULL | Card validator (a candidate cannot be emitted without a complete card) |
| CMP-58 | bbox/polygon normalised [0;1] after CropBox/MediaBox/Rotate; thumbnails with highlighted zones (blue = expected, red = actual) | §9.1 p.4; §9.3 p.1 | MUST | FULL | |
| CMP-59 | Both «лист» (sheet no. from the title block) and «страница» (PDF page index) | §9.2; 03 sheet_page_range | MUST | FULL | |
| CMP-60 | Обоснование: deterministic Russian text per discrepancy type | §9.2 alg.4 | MUST | FULL | Templates, no LLM needed |
| CMP-61 | Header: object, address, permit number, supervision case no., process_id, protocol no./version, input_manifest_hash, versions; signature block | §9.2; §10 Objects/Protocols | MUST | FULL | |
| CMP-62 | Input-file registry appendix (file_id, name, stage, discipline, шифр, редакция, approval, date, pages, SHA-256, used/superseded) | §9.3 p.4; §9.6; 03 | MUST | FULL | |
| CMP-63 | УКЭП signature of the finalised protocol | §12 #10 (for РиН), module 9 | NICE | MOCKED | Visual e-signature stamp plus detached signature with a test key |
| CMP-64 | Protocol content hash (SHA-256 of canonical JSON) printed and verified | §12 #7 (integrity), §13 #8 | SHOULD | FULL | |
| CMP-65 | GOLD-format export (СХЕМА GOLD columns + ПРИМЕРЫ notation), CSV/XLSX | §14; matrix sheets | SHOULD | FULL | Direct comparability with the organisers' labels |
| CMP-66 | Coverage/abstention summary and breakdown by section and discrepancy type | §14.3 | SHOULD | FULL | |

### F. Persistence, versions, lifecycle

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-67 | Protocols table with version numbers | §9.2 alg.5; §10 #5 | MUST | FULL | |
| CMP-68 | Checks table with the §10 fields | §10 #2 | MUST | FULL | + extension fields |
| CMP-69 | Evidence_Fragments table with the §10 fields | §10 #14 | MUST | FULL | + extension fields |
| CMP-70 | Process status → READY after the first protocol | §9.2 alg.5 | MUST | FULL | |
| CMP-71 | Inspector notified of protocol readiness | §9.2 alg.5 | MUST | SIMPLIFIED | `protocol.ready` event → in-app and e-mail (dev SMTP) via B07 |
| CMP-72 | Incremental update: recompute only parameters with new data | §9.2 | MUST | FULL | Dependency index (§3.9) |
| CMP-73 | Previous protocol version kept in history; version diff | §9.2; module 9 | MUST | FULL | Immutable snapshots |
| CMP-74 | Re-upload during verification does not reset decisions; decisions are carried over when the evidence fingerprint is unchanged | §9.3 p.3 | MUST | FULL | |
| CMP-75 | Re-upload creates a new file record and a new protocol version; no overwrite under the same file_id | 03 | MUST | FULL | |
| CMP-76 | After finalisation no re-upload or status changes; the snapshot is immutable | §9.3 p.5 | MUST | FULL | |
| CMP-77 | Un-finalisation → VERIFICATION_COMPLETED, audited, new version on re-finalisation | §9.3 | SHOULD | FULL | |
| CMP-78 | Auto re-upload from РиН on a finalised protocol → no re-check, only a notification | §9.6 | SHOULD | FULL | Guard in the incremental trigger |
| CMP-79 | РиН payload = confirmed records + protocol/matrix/model versions + input registry | §9.3 p.4; §9.6 | MUST | FULL | `GET …/rin-payload` for B06 |

### G. NFR and integration

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| CMP-80 | Comparison of 132 params ≤ 2 min (±30 s) with fully loaded, parsed documents | §11 #4 | MUST | FULL | Expected < 15 s |
| CMP-81 | Protocol generation (JSON/PDF) ≤ 30 s (±10 s) | §11 #5 | MUST | FULL | Pre-rendered page images; JSON < 1 s, PDF ≈ 5–10 s |
| CMP-82 | Incremental protocol update ≤ 1 min (±15 s) | §11 #9 | MUST | FULL | Affected groups only; the new file's parse time is B01's |
| CMP-83 | NLP analysis per parameter ≤ 500 ms | §11 #7 | SHOULD | FULL | Embedding cache |
| CMP-84 | JSON validated against the OpenAPI 3.0 schema | §1.3 | MUST | FULL | |
| CMP-85 | Asynchronous pull model: protocol and exports fetched on request; exports generated asynchronously (202 + poll) | §1.4 | MUST | FULL | |
| CMP-86 | RabbitMQ contracts between modules | §1.5 | MUST | FULL | §3.7 |
| CMP-87 | Structured JSON logs (timestamp, level, service, message, request_id, user_id) and stage metrics | §13 | SHOULD | FULL | |
| CMP-88 | Audit events for protocol version creation, export and finalisation snapshots | module 9; §12 #4 | SHOULD | FULL | Emits to B09 |
| CMP-89 | Scanned-ID requisites (signatures, stamps, dates, reg. numbers) and RD stamps «В производство работ» / «Выполнено согласно проекту» shown in table (1) | §5 notes 2–3 | SHOULD | SIMPLIFIED | B01 detects; B04 prints |
| CMP-90 | All hidden-test classes representable: confirmed violations, verified negatives, missing evidence, not applicable, revision conflict | §14.2 «Состав классов» | MUST | FULL | |

**Totals: 92 requirements. FULL 83, SIMPLIFIED 7 (CMP-16, 31, 43, 49, 71, 89, 91), MOCKED 2 (CMP-63, 92), OUT_OF_SCOPE 0.**

---

## 3. Proposed design

### 3.1 Components

```
                 parsing.completed / files.reuploaded (B01)
                                   │
┌──────────────────────────────────┼─────────────────────────────────────────────┐
│ Node API (backend-core)          ▼                                             │
│  comparison-orchestrator ── publishes comparison.run ──┐                       │
│  protocol-service (REST, persistence of Protocols,     │                       │
│    snapshots, versions, diff, rin-payload)             │                       │
│  report-worker (queue protocol.render):                │                       │
│    JSON (canonical) · PDF (Playwright/Chromium) ·      │                       │
│    DOCX (docx-templates) · XML (xmlbuilder2 + XSD)     │                       │
└────────────────────────────────────────────────────────┼───────────────────────┘
                                                         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Python comparison-worker (ML side, CPU-only)                                 │
│  1 SnapshotLoader  (matrix_version, rules, registry, extractions, object)    │
│  2 ScenarioDetector                                                          │
│  3 RevisionResolver (latest applicable approved; conflicts)                  │
│  4 Pipeline per param: Applicability → Completeness → Currency/Comparability │
│                        → Comparator(data_type, shape) → Atomiser            │
│  5 Aligners: explication rooms, keyed lists, ordered layers, axis grid       │
│  6 ConfigDiff: symbol sets per region, sheet registration, raster fallback   │
│  7 ChangeLogMiner (RD «Лист/Ведомость регистрации изменений»)               │
│  8 Risk scorer · Rationale generator (RU templates) · Card validator         │
│  9 Result writer → Checks / Evidence_Groups / Evidence_Fragments (+run row)  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Where the engine runs (decision D3).** We recommend the **Python** worker. It shares normalisation code, units and embeddings with the B01 parser, and it needs `shapely`, `scipy` (Hungarian assignment), `rapidfuzz` and `sentence-transformers`. The Python worker writes result rows directly to Postgres through a narrow repository layer (SQLAlchemy Core; the schema and migrations are owned by Node). Rendering stays in Node (Chromium, templates). Node alone owns the Protocols snapshots, so versioning/finalisation logic lives in one place.

### 3.2 Data model (owned tables; names aligned with §10)

Tables listed in §10 keep **exactly** the ТЗ key fields. Extension fields are marked `+`.

**Checks** (§10 #2): one row per atomic check result. There is one row per evidence group when the group is not COMPLETE, and one row per atomic finding when it is COMPLETE.

| Field | Type | Notes |
|---|---|---|
| id | BIGSERIAL PK | |
| param_id | INT FK Params NULL | NULL when a rule (non-matrix) is the basis |
| object_id | FK Objects | |
| expected_value | JSONB | typed value `{type, value, unit, display}` |
| actual_value | JSONB | same shape |
| completeness_status | ENUM | COMPLETE / MISSING_EVIDENCE / NOT_APPLICABLE / NOT_COMPARABLE / CLARIFICATION_REQUIRED |
| finding_status | ENUM NULL | CANDIDATE / NEGATIVE_VERIFIED / CONFIRMED_VIOLATION / SUSPICION; NULL unless COMPLETE; CHECK: the system writer cannot insert CONFIRMED_VIOLATION |
| review_priority | ENUM | copied from Params |
| evidence_group_id | TEXT FK Evidence_Groups | |
| + finding_id | TEXT UNIQUE per protocol version | stable (§3.6) |
| + process_id, run_id, protocol_version_first_seen | | |
| + rule_id | FK Logical_Rules NULL | atomic rule instead of a matrix param (e.g. converted SUSPICION) |
| + axis | ENUM | PD_RD, RD_ID, PD_ID, NORM_PD, NORM_RD, NORM_ID |
| + element_key | JSONB | `{kind: ROOM, floor:"1", number_expected:"23", number_actual:"22"}` |
| + discrepancy_type | ENUM | §3.4.4 |
| + delta | JSONB | `{abs, rel, unit, display:"+0,21 м² (+1,1 %)"}` or textual |
| + trigger_exceeded | BOOL | matrix trigger / normative bound breached |
| + risk_level, risk_score | ENUM, NUMERIC | ordering only |
| + confidence | NUMERIC | min(extraction, alignment, comparison) |
| + rationale | TEXT | «обоснование» |
| + approved_change_ref | TEXT | `NONE` or a reference |
| + decision_trace | JSONB | pipeline step results (§3.4) |
| + parent_finding_id, is_composite, split_into[] | | atomic split |
| + inspector_decision, decision_reason_code, decision_comment, decided_by, decided_at | | written by B03; history in Audit_Log |
| + decision_state | ENUM | CURRENT / OUTDATED (evidence changed after re-upload) |
| + input_fingerprint | TEXT | SHA-256 of the sources and values that produced the result |
| + sampled_for_review | BOOL | random sample of system negatives |

**Evidence_Groups** (+ new; §10 has only the FK):
`evidence_group_id PK, object_id, param_id|rule_id, scope_key ("OBJ", "K7", "S1"), group_completeness_status, group_finding_status (derived), stage_slots JSONB {PD:{role, state, file_ids, reason}, RD:…, ID:…}, selected_sources JSONB (file_id, sha256, revision per stage), excluded_sources JSONB (superseded/draft with reason), sources_fingerprint, first_protocol_version, last_recomputed_run_id`.

**Evidence_Fragments** (§10 #14): `id, evidence_group_id, file_id, stage, sheet_page, bbox_polygon_norm, extracted_value, role_expected_actual` + `finding_id, sha256, document_code, revision, approval_status, sheet_no (лист), page_index (страница PDF), polygon_norm (optional float[][]), anchor_text, extraction_id (B01 ref), method (TEXT_LAYER / OCR / TABLE / CV), confidence, quality_flag (OK / LOW_QUALITY / ABSTAIN), thumbnail_ref`.
`role_expected_actual` enum: `EXPECTED`, `ACTUAL`, `SUPPORTING_EXPECTED`, `SUPPORTING_ACTUAL` (e.g. a change-log row, legend or TEP cross-check), `APPROVED_CHANGE`, `NORMATIVE` (a tolerance note on the sheet).

**Protocols** (§10 #5): `id, object_id, version, matrix_version, dataset_version, model_version, input_manifest_hash, status, created_at, finalized_at` + `process_id, protocol_no, version_reason (INITIAL / INCREMENTAL_UPDATE / FULL_RERUN / VERIFICATION_SNAPSHOT / FINALIZATION / UNFINALIZATION), previous_version_id, rules_version, parser_version, scenario, scenario_base, upload_status JSONB, summary JSONB, content JSONB (full canonical protocol), content_hash, run_id, affected_param_codes[], created_by, finalized_by`.

**Protocol_Artifacts** (+): `id, protocol_id, format (JSON/PDF/DOCX/XML/GOLD_CSV/GOLD_XLSX), storage_path, sha256, size, status (PENDING/READY/FAILED), generated_at, duration_ms`.

**Comparison_Runs** (+): `run_id, process_id, trigger (INITIAL / INCREMENTAL / RERUN), changed_file_ids[], affected_params[], matrix_version, rules_version, model_version, dataset_version, parser_version, input_manifest_hash, started_at, finished_at, duration_ms, status, stats JSONB`.

**Param_Rules** (+, co-owned with B08; could be a JSONB column `comparison_spec` on Params). The spec is versioned together with matrix_version (§3.5, Appendix A).

**Reference dictionaries** (+, read-only seeds, versioned in rules_version): `Enum_Scales` (ordinal scales), `Unit_Conversions`, `Term_Synonyms` (room names, abbreviations, homoglyph map), `Discrepancy_Types`, `Reason_Codes` (shared with B03).

Tables read: Params, Objects (+ `object_type, floors_above, has_underground, has_parking_underground, has_gas, is_demolition, budget_funded, supervision_case_no`), Files (+ registry fields from 03: `sheet_page_range, successor_id, signature_status, doc_type`), Processes (B01: `process_id, object_id, status, stage_upload_status`), Suspicions (B05), Model_Versions/Dataset versions (retraining block).

### 3.3 Scenario detection

Input: B01's per-stage upload status `PD_UPLOADED|PD_PARTIAL|PD_MISSING` (the same for RD and ID). This status is computed against the expected composition: registry `sheet_page_range`, PD «Состав проектной документации», RD «Ведомость рабочих чертежей основного комплекта» / «Ведомость основных комплектов» (ГОСТ Р 21.101), and the ID list (Приложение 19 «Примерный перечень»).

```
present(S)  = status(S) ∈ {UPLOADED, PARTIAL}
base = FULL        if present(PD)∧present(RD)∧present(ID)
       PD_RD_ONLY  if PD∧RD∧¬ID
       PD_ID_ONLY  if PD∧ID∧¬RD
       RD_ID_ONLY  if RD∧ID∧¬PD
       SINGLE_ONLY if exactly one present
       (none present → the process cannot start; B01 rejects)
scenario = PARTIALLY_LOADED if ∃S present(S) ∧ status(S)=PARTIAL else base
```

The protocol prints both: «Тип проверки: PARTIALLY_LOADED (базовый сценарий: FULL; ИД загружена частично — 5 из 15 ожидаемых файлов по реестру)». Each scenario gets a Russian explanatory paragraph listing which comparison axes were executable.

| Scenario | Axes executed | Typical outcome for the absent stage |
|---|---|---|
| FULL | PD_RD, RD_ID, (PD_ID only as fallback), NORM_* | — |
| PD_RD_ONLY | PD_RD, NORM_PD, NORM_RD | a rule needing ID only (e.g. tolerance in ID, «по факту заливки») → MISSING_EVIDENCE; PD↔RD rules → ID slot NOT_APPLICABLE |
| PD_ID_ONLY | PD_ID, NORM_PD, NORM_ID | RD-only rules → MISSING_EVIDENCE |
| RD_ID_ONLY | RD_ID, NORM_RD, NORM_ID | PD↔RD rules → MISSING_EVIDENCE (PD absent) |
| SINGLE_ONLY | NORM_<stage> only (thresholds from Params, tolerances declared on the ID sheet) | all cross-stage rules → MISSING_EVIDENCE, aggregated by stage |
| PARTIALLY_LOADED | as base; missing files → fragment/document-level MISSING_EVIDENCE | |

To avoid flooding table (1), MISSING_EVIDENCE rows caused by an entirely absent stage are **aggregated** in the PDF («ИД не загружена — 97 параметров не могут быть проверены по оси РД↔ИД», expandable list). JSON keeps every row.

### 3.4 Per-parameter pipeline (§9.2 alg.3)

For each active parameter *p* in the matrix snapshot (and each scope *s* of the object):

**Step 1 — Applicability.** Evaluate `spec.applies_if` against the object passport (`object_type ∈ {residential, public, production, linear}`, `has_underground`, `has_gas`, `is_demolition`, `budget_funded`, …). The passport comes from the PD ПЗ/ТЭП extraction (B01) or is entered by the inspector at process creation.
- false → group `NOT_APPLICABLE`, with mandatory `na_basis` («Объект нежилого назначения (Objects.object_type=public; источник: ПЗ, ТЭП, стр. 3)»).
- Unknown attribute → **do not assume N/A**; continue and add a hint «подтвердите применимость».
- Stage applicability: `spec.stages[S].role ∈ {REQUIRED, OPTIONAL, UNUSED}`. Plus `sufficient_stage_sets` (e.g. M-055: `[[PD,RD],[RD,ID],[PD,ID]]`; M-002: `[[PD,RD],[PD,ID]]`; OKT103-type tolerance: `[[ID]]`).

**Step 2 — Evidence completeness** (per stage slot):
- The document class required by `source_pd/source_rd/source_id` (mapped to discipline and doc types in the spec) is absent from the package → slot `MISSING` (doc-level).
- The document is present, but no extraction for *p* is found in it → slot `NOT_FOUND` (fragment-level MISSING_EVIDENCE: «доказательный фрагмент отсутствует»).
- The needed zone is marked LOW_QUALITY/ABSTAIN by OCR → slot `UNREADABLE` (→ NOT_COMPARABLE in step 3).
- A slot that no sufficient set needs, given what is present → `NOT_APPLICABLE` («стадия не требуется правилом при парном сравнении»).
- If no sufficient set can be formed from present slots → group `MISSING_EVIDENCE`, with the action «Запросить/дозагрузить: РД, марка КЖ — Спецификация элементов (источник по Матрице)».

**Step 3 — Revision currency and comparability.**
- *Currency* (per stage, per document_code): candidate files = same object_id, doc_stage, discipline and document_code. Selection rules (03 table 1):
  - exactly one APPROVED/FOR_CONSTRUCTION revision that is not superseded → use it;
  - an explicit successor chain → take the head; predecessors go to `excluded_sources` («сохранена для аудита, исключена из эталонного сравнения»);
  - several heads without an unambiguous status, a missing approval_status/approval_date, a cycle or a dangling successor, or a head that is DRAFT/CANCELLED → `CLARIFICATION_REQUIRED` (conclusion blocked; list the conflicting revisions and the metadata that conflicts);
  - package without a registry → `CLARIFICATION_REQUIRED` («реестр файлов не представлен»).
- *Comparability*: units convertible; scope compatible (same building/section/floor coverage; a whole-building PD value against RD per-section values is comparable only if all sections are present); same CRS/elevation system for coordinates; sheets mapped (registry `sheet_page_range` or title-block sheet number resolved); no UNREADABLE slot in the chosen sufficient set; no internal contradiction between equally-ranked sources of the same stage (a lower-ranked contradiction is kept as `SUPPORTING_*` and noted). Failure → `NOT_COMPARABLE` with the reason.

**Step 4 — Subject comparison.** Run the comparator for the data_type and value_shape on each executable axis. The Atomiser emits atomic findings (CANDIDATE) or one group-level NEGATIVE_VERIFIED check with the compared values. Then run the card validator:
- every CANDIDATE must have ≥ 1 EXPECTED and ≥ 1 ACTUAL fragment with file_id, sha256, page, sheet, bbox and the registry metadata;
- for NORM axes, the EXPECTED side is either a document fragment (tolerance note, PD value) or a `NORMATIVE` reference (Normative_Base id + version + Params.min/max).
- A candidate that fails validation is downgraded to `NOT_COMPARABLE` («не удалось локализовать доказательство»). This is a precision-favouring invariant consistent with «Без полного доказательства finding не засчитывается».

**Precedence** when several problems coexist (ТЗ order): NOT_APPLICABLE > MISSING_EVIDENCE > CLARIFICATION_REQUIRED > NOT_COMPARABLE > comparison. All detected issues are still listed in `decision_trace`.

#### 3.4.1 Decision trace (explainability)

Each group stores:

```json
[{"step":"APPLICABILITY","result":"PASS","basis":"object_type=residential"},
 {"step":"COMPLETENESS","result":"PASS","slots":{"PD":"OK","RD":"OK","ID":"NOT_APPLICABLE"}},
 {"step":"CURRENCY","result":"PASS","selected":{"PD":"POL17-000031 rev «Корр.2» APPROVED 2025-02"},"excluded":[{"file_id":"POL17-000012","reason":"SUPERSEDED by POL17-000031"}]},
 {"step":"COMPARABILITY","result":"PASS"},
 {"step":"COMPARE","axis":"PD_RD","result":"NO_DISCREPANCY","n_elements":64,"max_abs_delta":0.0}]
```

The card and UI show it as a vertical checklist (✓/✗ per step) that the inspector can read at a glance. This is a strong jury point.

#### 3.4.2 Status assignment rules (normative)

| Condition | completeness_status | finding_status | Counted as violation | Protocol table |
|---|---|---|---|---|
| Parameter or rule not applicable to the object | NOT_APPLICABLE | — | no | (1) |
| No sufficient stage set: required document or fragment absent | MISSING_EVIDENCE | — | no | (1), separate list |
| Current revision undetermined / conflicting metadata / no registry | CLARIFICATION_REQUIRED | — | no | (1) |
| Sources present but not comparable / unreadable / unlocalisable | NOT_COMPARABLE | — | no | (1) |
| Comparable current sources, no discrepancy on any executed axis | COMPLETE | NEGATIVE_VERIFIED (origin SYSTEM) | no | (4) |
| Comparable current sources, ≥ 1 discrepancy under the candidate policy | COMPLETE | CANDIDATE | no | (2) |
| Inspector confirms an atomic candidate | COMPLETE | CONFIRMED_VIOLATION (origin INSPECTOR) | **yes** | (3) |
| Inspector rejects with reason_code + comment | COMPLETE | NEGATIVE_VERIFIED (origin INSPECTOR) | no | (4) |
| Inspector «Требует уточнения» | COMPLETE | CANDIDATE, inspector_decision = CLARIFICATION_REQUIRED | no | (2), marked |
| Free-search hypothesis (B05) | — | SUSPICION | no | (5) |

The group-level finding status is derived: CONFIRMED_VIOLATION if any child is confirmed, else CANDIDATE if any child is a candidate, else NEGATIVE_VERIFIED. Group status only drives dashboard colour. Counts and GOLD always use atomic findings.

#### 3.4.3 Candidate policy per parameter (addresses the pilot vs trigger conflict — decision D1)

`spec.candidate_policy`:
- `DEVIATION` (default for design-decision params: explications, configurations, layers, classes, counts). Any deviation of the actual from the expected current approved source beyond the rounding epsilon, in the adverse direction for directional params and in any direction for non-directional ones, is a CANDIDATE. `trigger_exceeded` is set when the matrix trigger fires and only raises risk.
- `TRIGGER` (for pure normative thresholds such as «< 0.9 м»): a CANDIDATE only if the trigger or normative bound is breached. An adverse deviation that still satisfies the norm becomes a LOW-risk CANDIDATE only if `spec.report_adverse_within_norm=true`.
- An improvement (B30 → B35, width 0.9 → 1.2) is never a candidate. It is recorded in the group as `info: IMPROVEMENT` and shown in table (4).

With these policies, ALT79B, POL16, DOO25 and SOSH25 come out as candidates (matching the experts), and POL17 comes out negative.

#### 3.4.4 Discrepancy types (needed for «правильный параметр/тип расхождения»)

`VALUE_DECREASED`, `VALUE_INCREASED`, `VALUE_CHANGED`, `THRESHOLD_BELOW_MIN`, `THRESHOLD_ABOVE_MAX`, `TOLERANCE_EXCEEDED`, `CLASS_DOWNGRADED`, `MATERIAL_SUBSTITUTED`, `ELEMENT_MISSING` (present in expected, absent in actual), `ELEMENT_ADDED` (absent in expected, present in actual), `FUNCTION_CHANGED` (room/element purpose), `LAYER_REMOVED`, `LAYER_CHANGED`, `POSITION_SHIFTED`, `CONFIGURATION_CHANGED`, `COUNT_CHANGED`, `TOTAL_CHANGED` (aggregate), `UNDOCUMENTED_WORK` (the ID contains work absent from RD, as in IZM12).

### 3.5 Comparison semantics

#### 3.5.1 `number`

- **Parsing/normalisation:** handle the decimal comma («6234,1»), thin/regular spaces as thousand separators («6 252,3»), signs («+491/+552» → a two-component deviation vector), «±12», ranges «1.5–1.8» (use the bound named by the spec), and dimension expressions «400×600» → area, «Ø110» → diameter. Units come from `Unit_Conversions` (м, мм, м², м2, кв.м, м³, кВт, Гкал/ч, ‰, %, °…). All values are converted to the param's canonical unit before comparison.
- **Rounding epsilon:** `eps = max(spec.abs_tol, spec.rel_tol·|e|, 0.5·10^(−d))`, where *d* is the smaller count of displayed decimals of the two values. For example, 11,68 vs 11,7 are equal; 1012,26 vs 1012,49 differ by 0,23 > 0,005 → changed.
- **Delta:** `Δ = a − e`, `Δrel = Δ/|e|` (undefined if e = 0 → textual).
- **Kinds** (from the trigger text, see Appendix A):
  - `ANY` (|Δ| > eps);
  - `DEC` (Δ < −eps); `INC` (Δ > eps);
  - `REL>x%` (|Δrel| > x); `INC_REL>x%`;
  - `ABS>x`;
  - `MIN v` / `MAX v`: normative bound on any single stage, where v = Params.min_value/max_value;
  - `LIMIT_FROM_EXPECTED`: actual must not exceed the PD value, e.g. power against the ТУ limit (M-014), КЗ (M-019);
  - `TOL`: measured deviation compared with a declared tolerance. OKT103: tolerances 15 мм, ±12 мм, 20 мм against facts +491/+552, +980/+537, +201/+349 мм → `TOLERANCE_EXCEEDED`, with Δ = fact − tolerance.
- **Derived values:** thickness from top/bottom elevations (M-058 ID «нивелировка верха/низа»); stage duration from journal dates (M-082); floor total from the sum of explication rows (used as a cross-check SUPPORTING fragment).

#### 3.5.2 `enum` with ordinal scales (`Enum_Scales`, better → worse)

| Scale | Order (better → worse) | Downgrade example (candidate) |
|---|---|---|
| Concrete class (M-055) | B100 > … > B60 > B55 > B50 > B45 > B40 > B35 > B30 > B25 > B22,5 > B20 > B15 > B12,5 > B10 > B7,5 > B5 > B3,5 | B35 → B30 |
| Steel grade (M-056) | С590 > С440 > С390 > С355 > С345 > С255 > С245 > С235 | С345 → С245 |
| Rebar class (M-057) | А1000 > А800 > А600 > А500С ≥ А500 > А400 > А240 | А500С → А400 |
| Fire resistance degree (M-022) | I > II > III > IV > V | I → II |
| Constructive fire hazard class (M-023) | С0 > С1 > С2 > С3 | С0 → С1 |
| Finishing material hazard class (M-050, M-107) | КМ0 > КМ1 > КМ2 > КМ3 > КМ4 > КМ5 | КМ1 → КМ3 |
| Energy efficiency class (M-021, M-124) | A++ > A+ > A > B > C > D > E > F > G | A → B |
| Power reliability category (M-015) | особая группа I > I > II > III | I → II |
| Fire door/valve limits (M-103, M-111) | EI150 > EI120 > EI90 > EI60 > EI45 > EI30 > EI15 (numeric minutes; REI/EI/E prefixes compared per letter set) | EI60 → EI30 |
| Cable fire performance (M-069, M-109) | нг(А)-FRLS / FRHF > нг(А)-LS / HF > нг(А) > нг > without index | FRLS → LS |
| Waste hazard class (M-094) | the adverse direction is "claimed less hazardous": I (most hazardous) … V; a change of IV → V without a basis is a candidate | IV → V |

- **Homoglyph folding** before lookup: Cyrillic В/С/А/Е/К/М/Н/О/Р/Т/Х vs their Latin twins («В35» ≡ «B35», «С0» ≡ «C0»); strip spaces and «класс», «марка».
- An unknown token → NOT_COMPARABLE («значение вне справочника шкалы»), and the token is logged for dictionary extension.
- Non-ordinal enums (door opening direction, pipe material family) are compared for equality, with an adverse-transition table (e.g. «чугун» → «ПВХ» adverse for M-075).

#### 3.5.3 `string` (semantic)

Four stages. Stop at the first decisive stage.

1. **Normalise:** Unicode NFC, lower-case (not for codes), ё→е, quotes/dashes/spaces unified, homoglyph folding in codes; abbreviation dictionary («с/у», «СУ» → «санузел»; «ПУИ» → «помещение уборочного инвентаря»; «тех.помещение» → «техническое помещение»; «ИТП», «МОП», «ЛК»…).
2. **Exact after normalisation** → EQUIVALENT.
3. **Typo tolerance:** `rapidfuzz` ratio ≥ 0.90 with the same token count → EQUIVALENT (e.g. «Комтана отдыха» ≡ «Комната отдыха»; RD ALT79B 2nd floor really contains the typo «Комтана»).
4. **Semantic:** a multilingual Sentence-BERT analogue of all-MiniLM-L6-v2, `paraphrase-multilingual-MiniLM-L12-v2` (384-dim, same family, handles Russian). Cosine ≥ 0.88 → EQUIVALENT; 0.70–0.88 → `UNCERTAIN` (a candidate only if the spec is `DEVIATION`, with confidence ×0.6 and risk capped at MEDIUM); < 0.70 → DIFFERENT.
5. **Domain function classes** for room names (`Term_Synonyms.function_class`: MAIN / AUXILIARY / TECHNICAL / SERVICE_STAFF / RESIDENTIAL / COMMON / SANITARY / STORAGE / UNSPECIFIED). «Помещение» (unspecified) → «Комната отдыха» is a `FUNCTION_CHANGED` even though the similarity is moderate. For M-003 the trigger direction «в пользу технических зон» sets `trigger_exceeded` when USEFUL → TECHNICAL.

Embeddings are cached in Redis under `emb:{model}:{sha1(text)}`. Batch per run. Latency is ≈ 5–20 ms per 100 strings on M2 CPU, well within ≤ 500 ms per param.

#### 3.5.4 `boolean` (presence)

Presence is established by an extraction flag or by a set membership test on a region descriptor (§3.5.7).
- expected = present, actual = absent → `ELEMENT_MISSING` (CANDIDATE);
- expected = absent, actual = present → `ELEMENT_ADDED` (CANDIDATE only if `spec.added_is_candidate`, e.g. an added room, UNDOCUMENTED_WORK in ID);
- equal → negative.

#### 3.5.5 `coordinate`

- Points `(X, Y[, Z])` with CRS tag (МСК-Москва, local, БСВ elevations). A CRS mismatch without a known transform → NOT_COMPARABLE.
- Distance: Euclidean in metres. Candidate when > the spec threshold (M-034: 0,5 м).
- M-009 is 1-D (elevation, eps 0,005 м).

#### 3.5.6 Multi-value parameters → atomic findings

`value_shape` ∈ `SCALAR | KEYED_LIST | ORDERED_LIST | SET | GEOMETRY_CONFIG`. The ТЗ `data_type` of each attribute stays within the §8.1 enum.

- **KEYED_LIST** (explication rooms, doors by mark, windows by mark, columns by mark, axes, systems П1/В2, apartments):
  1. Primary key match (room number, mark). The key is normalised: «1.109» ≡ «1,109», leading zeros dropped.
  2. Unmatched residue is aligned by the **Hungarian assignment** (`scipy.optimize.linear_sum_assignment`) on the cost `w1·(1−name_sim) + w2·|Δarea|/max(area) + w3·dist(position after sheet registration) + w4·key_edit_distance`. The assignment is accepted if the cost is < τ. This handles ALT79B, where PD №23 «Помещение» 19,41 м² became RD №22 «Комната отдыха» 19,62 м² (renumbered).
  3. Remaining unmatched rows are `ELEMENT_MISSING` (expected only) or `ELEMENT_ADDED` (actual only). SOSH25 room 1.109 «Зона ожидания…» 18,2 м² is ELEMENT_ADDED.
  4. Matched pairs are compared per attribute (name → FUNCTION_CHANGED / equivalent; area → VALUE_CHANGED with eps; category → CLASS change).
  5. Aggregates (floor/section totals «Итого по этажу», «Общая площадь этажа») are compared as a `TOTAL_CHANGED` atomic finding carrying the trigger (M-002 «> 1%»).
- **Atomisation:** one atomic finding per changed element and per changed aggregate, grouped under one evidence group per (object, param, scope). For readability the PDF shows the group row with nested atomic rows. When more than `N_max=25` atomic changes occur in one group, the rest are listed in the card appendix and the group row shows «и ещё 37 изменений».
- **ORDERED_LIST** (roof pie M-044, pavement layers M-032): sequence alignment (Needleman–Wunsch over layers, similarity = material semantic sim + thickness closeness) → `LAYER_REMOVED` / `LAYER_ADDED` / `LAYER_CHANGED` (material substitution or thickness DEC). UNDMS: «бронированный стальной лист 6 мм» present in PD, absent between «пароизоляция» and «бетон 200 мм» in RD → LAYER_REMOVED, corroborated by the RD change-log row (SUPPORTING_ACTUAL).
- **SET** (drainage systems, МАФ positions, tactile indicators, meters): set difference plus per-item quantity comparison.
- **Apartment labels (POL16):** the label triple «21,34 / 31,31 / 34,06» (жилая / общая / с летними, per the legend «Тип квартиры») is parsed as a keyed record per apartment id (Ст.1.1.1). Extra rule: `same_type_same_geometry` → identical apartment types in PD must keep their areas in RD.

#### 3.5.7 Configuration / graphic diffs (vent chamber, warm floor, local exhaust branches, moved door)

Representation `GEOMETRY_CONFIG`:

```json
{"scope":{"kind":"ROOM","number":"142","sheet":"10","stage":"PD"},
 "region_norm":[0.41,0.32,0.55,0.47],
 "elements":[{"kind":"VENT_BRANCH","label":"В2.4","bbox":[…]},
             {"kind":"VENT_BRANCH","label":"В2.5","bbox":[…]},
             {"kind":"LOCAL_EXHAUST","count":3}],
 "tokens":["В2.4","В2.5","В2.6","МО"],
 "registration":{"method":"AXIS_GRID","matched_axes":["1","2","Б","В"],"rmse_norm":0.004}}
```

Algorithm (SIMPLIFIED):
1. **Regions.** A room region is the Voronoi cell of the room-number label, clipped by walls when vector wall polylines can be polygonised (`shapely.polygonize`), else by radius = 0.6 × the median distance to neighbouring labels.
2. **Sheet registration PD ↔ RD.** Detect axis bubble labels (digits/letters at grid ends) in the text layer and fit an affine or similarity transform with RANSAC (≥ 3 matched axes). With fewer than 3 matches, positional comparisons are NOT_COMPARABLE and only set comparisons run.
3. **Element sets per region.** Use text-layer tokens (system codes `В2.10`, `П2`, `ВЕ`, equipment marks, legend-linked phrases such as «теплый пол», «Multibox E/RTL») and simple vector symbol detectors: door leaf arc + line, serpentine polyline density for warm-floor loops.
4. **Diff.** Missing tokens/elements → ELEMENT_MISSING; different token set in the same region → CONFIGURATION_CHANGED; the same element with a shifted registered position > tol → POSITION_SHIFTED (LOS3A door).
5. **Raster fallback** (scanned pages). Register via ORB features/ECC, compute a thresholded absolute difference, take connected components → change regions. Emit a composite CANDIDATE with low confidence (risk ≤ MEDIUM), discrepancy CONFIGURATION_CHANGED and bbox = union of the change components. The inspector splits it.
6. **Evidence.** EXPECTED bbox = PD region (blue), ACTUAL bbox = RD region (red). This is exactly the pilot legend.

**Change-log mining** (high yield). Parse the RD «Лист регистрации изменений» / «Ведомость изменений» tables (columns Изм. / Лист / Содержание изменения / Код / Примечание). Classify each entry to param codes by keyword → param rules («бронированный лист … покрытия исключён» → M-044, LAYER_REMOVED; «подвинулась дверь в помещении СУ» → planning change; «Изменилось значение λ утеплителя» → M-126). Resolve the referenced sheet and element in RD and the corresponding PD sheet. Outcome:
- if located in both → attach as `SUPPORTING_ACTUAL` to an existing candidate, or create a CANDIDATE if the param is in the matrix;
- if not mappable to a matrix param → hand over to B05 as SUSPICION with evidence (`discovery_method: CHANGE_LOG`).

A change-log entry is **not** an `approved_change_ref`. It proves the change is intentional, not that it was approved against PD (the pilot calls it «прямое подтверждение» of the discrepancy, still CANDIDATE).

#### 3.5.8 Approved change reference

`approved_change_ref` is set to a reference when a registry document of `doc_type ∈ {PD_CORRECTION, EXPERTISE_CONCLUSION, CHANGE_CONFIRMATION}` references the same document_code/sheet/element. Examples are a later approved PD revision («Корректировка №2») or the designer's confirmation of changes under ст. 49 ГрК РФ. Otherwise the value is `NONE`.
- The engine never auto-negates because of it; it only hints («возможно согласованное изменение: …»), lowers risk one step and shows it in the card.
- A PD revision that already contains the RD solution is handled earlier, by currency: the newer PD is the reference, so there is no discrepancy (POL17).
- Final `approved_change_ref` is recorded by the inspector (B03). A rejection with reason `APPROVED_CHANGE` must fill it.

### 3.6 Identity, hashing, determinism

- `evidence_group_id = "EG-{object_code}-{param_or_rule_code}-{scope_key}"`, e.g. `EG-ALT79B-M003-OBJ`. It is stable across versions; source changes are tracked by `sources_fingerprint`.
- `finding_id = "{object_code}-{code}-{axis}-{element_slug}"`, e.g. `ALT79B-M003-PDRD-F1R23`, `OKT103-M054-NORMID-AXB`. When the element key is long, `element_slug = base32(sha1(canonical(element_key)))[:8]`. Children created by an inspector split: `{parent}.1`, `{parent}.2`.
- `input_manifest_hash = SHA-256(JCS(sorted_by_file_id([{file_id, sha256, object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, predecessor_id, successor_id, sheet_page_range, used_as_reference}])))`, where JCS is RFC 8785. It covers all files in the process at run time, including excluded ones (marked).
- `content_hash = SHA-256(JCS(protocol_json without {generated_at, content_hash, signatures, artifacts}))`. Same inputs + same versions ⇒ same content_hash. This determinism test is in the acceptance suite.
- matrix_version: `"{edition}+{hash8}"`, e.g. `1.1+3fa9c2d1`, where edition «1.1» comes from `Матрица_параметров_редакция1.1.xlsx` and the hash covers the Params rows + comparison specs. Every admin edit creates a new immutable snapshot (B08 contract).
- model_version: the id of the published bundle (OCR engine + embedding model + CV thresholds) from Model_Versions. dataset_version: the GOLD dataset version used for calibration (initially `DS-0.1-pilot9`, «не используется для обучения — пилот»).

### 3.7 REST API (OpenAPI 3.0, JSON; all responses schema-validated)

| Method & path | Purpose | Request → Response (sketch) |
|---|---|---|
| POST `/api/v1/processes/{process_id}/comparison-runs` | manual full re-run (admin/inspector; normally auto) | `{reason}` → `202 {run_id, status:"QUEUED"}` |
| GET `/api/v1/comparison-runs/{run_id}` | run status and timings | `{run_id, status, started_at, finished_at, duration_ms, versions{…}, affected_params[]}` |
| GET `/api/v1/processes/{process_id}/protocol` | current protocol (pull) | `?version=N&view=full|summary` → `200 Protocol` / `404` / `409 {status:"PARSING"}` |
| GET `/api/v1/processes/{process_id}/protocols` | version history | `[{protocol_id, version, version_reason, status, created_at, content_hash, input_manifest_hash, summary}]` |
| GET `/api/v1/protocols/{protocol_id}` | a specific snapshot | `Protocol` |
| GET `/api/v1/protocols/{protocol_id}/diff?base={protocol_id}` | changes between versions | `{added[], removed[], changed[{finding_id, field, from, to}], decisions_outdated[]}` |
| POST `/api/v1/protocols/{protocol_id}/exports` | request an export | `{format:"pdf"|"docx"|"xml"|"json"|"gold_csv"|"gold_xlsx"}` → `202 {artifact_id, status}` (or `200` if cached) |
| GET `/api/v1/protocols/{protocol_id}/exports/{artifact_id}` | poll/download | `200 file` (Content-Type, `X-Content-SHA256`) / `202 {status:"PENDING"}` |
| GET `/api/v1/processes/{process_id}/evidence-groups` | filterable list | `?completeness_status=&finding_status=&section=&risk_level=&param=&page=&page_size=` → `{items[], total}` |
| GET `/api/v1/evidence-groups/{evidence_group_id}` | full group: slots, trace, findings, fragments | `EvidenceGroup` |
| GET `/api/v1/findings/{finding_id}` | evidence card | `EvidenceCard` |
| GET `/api/v1/evidence-fragments/{id}/thumbnail` | crop with highlight | `?w=800&context=0.15&highlight=true` → `image/jpeg` |
| GET `/api/v1/processes/{process_id}/rin-payload` | for B06 (only if PROTOCOL_FINALIZED) | `{protocol{…versions}, confirmed_findings[], input_registry[]}` / `409` |

Mandated elsewhere and consumed: `POST /api/v1/documents/upload` (B01 → process_id); status endpoint (B01, extended with `stage: PARSING|COMPARING|RENDERING`, `progress`, `protocol_version`); `POST /api/v1/inspection/{process_id}` (B06). Decision endpoints (B03) write into Checks and trigger `protocol.snapshot`.

Protocol reads come from `Protocols.content` (pre-assembled JSONB) with an ETag = content_hash, to meet the p95 ≤ 200 ms target.

### 3.8 Risk level (ordering only)

```
P = {HIGH:1.0, MEDIUM:0.6, LOW:0.3}[Params.review_priority]
S = 1.0 if trigger_exceeded or normative bound breached
    0.6 if adverse deviation (DEVIATION policy) not breaching the trigger
    0.4 if non-directional change / UNCERTAIN semantic
C = confidence ∈ [0,1] (min of extraction, alignment, comparison)
score = P · (0.4 + 0.6·S) · (0.5 + 0.5·C)
     −0.15 if a possible approved change is hinted
risk = HIGH if score ≥ 0.65; MEDIUM if ≥ 0.35; else LOW
floor rule: sections ППМ, КР, ОДИ → at least MEDIUM when S = 1.0
```

Weights are config (`rules_version`). The card shows «Почему этот уровень риска: приоритет HIGH по Матрице; триггер «> 1%» не превышен (+0,49 %); уверенность 0,93». The protocol footer repeats: «Уровень риска используется только для очередности экспертной проверки, не равен статусу нарушения и не является основанием для предписания или приостановки работ.»

### 3.9 Incremental update (≤ 1 min)

1. The trigger is `files.added` (B01) after parsing of the new or replacement files finishes. If the protocol is PROTOCOL_FINALIZED → **no run**: emit `inspector.notify {type: NEW_DOCS_AFTER_FINALIZATION, propose: NEW_PROCESS}` (§9.6). A new file never overwrites an existing file_id (03). A replacement is a new revision with `predecessor_id`.
2. **Dependency index** (built per run): `param → {(stage, discipline, doc_type)}` from the spec, plus `group → set(file_id)` actually used or excluded, plus `group → MISSING/NOT_FOUND slots`.
3. **Affected groups** are those whose spec matches the new file's (stage, discipline, doc_type), or that referenced a file now superseded by the new one, or whose slot was MISSING/NOT_FOUND/UNREADABLE for that stage/discipline, or any group if the registry itself changed the currency resolution for a document_code it uses. If the new file changes the upload status of a stage, the scenario is recomputed; a scenario change widens the affected set to the params whose sufficient sets change.
4. Recompute only the affected groups. Unaffected groups and findings are copied by reference (the same finding_id and the same decision).
5. **Decision carry-over:** for each recomputed atomic finding with a prior decision:
   - `input_fingerprint` unchanged → keep the decision;
   - changed → keep the decision in history, set `decision_state=OUTDATED`, set inspector_decision back to `PENDING`, and mark «доказательства изменились после дозагрузки».
   - Findings that disappeared are listed in the diff as `resolved_by_new_data` (their decision is kept in history). Because verification is not reset (§9.3 p.3), the process status returns to its previous verification state: READY stays READY; VERIFYING/COMPLETED → VERIFYING if new pending candidates exist.
6. Create a new Protocols version (`version_reason=INCREMENTAL_UPDATE`, `affected_param_codes`, `previous_version_id`). The previous version becomes `SUPERSEDED` and stays readable. Render the PDF asynchronously.
7. Budget (excluding the new file's OCR, which is B01's §11 #2/#3 budget): affected recompute ≤ 10 s, snapshot ≤ 2 s, PDF ≤ 20 s.

### 3.10 Protocol document (proposed layout replacing the missing Приложение № 2)

Format: A4 landscape (wide tables; matches the organisers' 6-page «Графическая фиксация»). The font is **PT Astra Serif / PT Astra Sans** (free, metric-compatible with Times New Roman, intended for Russian official documents), embedded. The watermark «ПРЕДВАРИТЕЛЬНЫЙ ПРОТОКОЛ — не является актом проверки» is shown until PROTOCOL_FINALIZED. Running footer: «Протокол № … · версия N · стр. X из Y · SHA-256: 3fa9…c2d1 · статус».

**Title page**
- «Инспектор ИИ» · «ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ КАМЕРАЛЬНОЙ ПРОВЕРКИ проектной, рабочей и исполнительной документации» · «№ ИИ-{object_code}-{yyyymmdd}-{seq}, версия N от {date}» · version reason.
- Header table:
  - Объект капитального строительства (наименование), адрес, надзорное дело №, разрешение на строительство №;
  - застройщик/технический заказчик, лицо, осуществляющее строительство;
  - process_id, дата и время формирования;
  - статус процесса / статус верификации;
  - ответственный инспектор;
  - версии: matrix_version, model_version, dataset_version, rules_version, parser_version;
  - input_manifest_hash, content_hash, предыдущая версия (ссылка/хеш).

**Section 1 «Статус загрузки документов»**: per stage PD/RD/ID the status code and Russian label (e.g. `RD_PARTIAL — Рабочая документация загружена частично`), files received/expected, registry status (представлен / валиден / отсутствует → CLARIFICATION_REQUIRED), rejected files with reason (format, size > 50 МБ, damaged PDF, package > 200 МБ).

**Section 2 «Тип проверки»**: scenario code, base scenario, what was compared (axes) and what could not be.

**Section 3 «Сводка»**: 132 params → COMPLETE n (CANDIDATE a / NEGATIVE_VERIFIED b), MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE, CLARIFICATION_REQUIRED; atomic candidates count; **«Подтверждённые нарушения: k»** (the only violation count); suspicions s; coverage and abstention %; breakdown by section (ПЗ, СПЗУ, АР, КР, ИОС1–5, ПОС, ПОД, ООС, ППМ, ОДИ, ЗУ, СМ) and by discrepancy type. The text states: «Статусы MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE, CLARIFICATION_REQUIRED отражают качество входных данных и не являются нарушением.»

**Table (1) «Комплектность и сопоставимость»**: № · Код (M-0xx / алиас) · Параметр · Раздел · Статус · Стадия и документ (шифр, ред.) · Причина / основание · Требуемое действие (запросить, дозагрузить, выбрать редакцию). Sub-blocks: 1а MISSING_EVIDENCE (separate list, per §9.3 p.4); 1б CLARIFICATION_REQUIRED (with the conflicting revisions); 1в NOT_COMPARABLE; 1г NOT_APPLICABLE (with basis); 1д excluded superseded revisions; 1е requisites/stamps check for scanned ID (from B01).

**Table (2) «Предварительные кандидаты»** (sorted by risk, then priority): № · finding_id · Код · Параметр · Объект сравнения (помещение/элемент) · Ожидаемое (стадия, лист) · Фактическое (стадия, лист) · Δ · Тип расхождения · Уровень риска · Решение инспектора (ожидает / требует уточнения) · Карточка (стр.). The pilot-style header row «№ / Объект сравнения / ПД / РД / Выявленное расхождение» is reproduced as the first five columns.

**Table (3) «Подтверждённые инспектором нарушения»**: finding_id · Код · Суть · Ожидаемое / фактическое · Нормативная ссылка (СП/ГОСТ/ФЗ from Params) · Инспектор (ФИО, user_id) · Дата-время · Комментарий. Empty state: «Подтверждённые нарушения отсутствуют (верификация не проводилась / не завершена)».

**Table (4) «Проверенные отрицательные результаты»**: group/finding · Код · Параметр · Сопоставленные значения · Источники · Происхождение (система / инспектор) · reason_code · Комментарий. System negatives are compact rows; full detail is in JSON.

**Table (5) «Гипотезы свободного поиска»**: suspicion_id · Метод (LOGICAL_ANALYSIS / SEMANTIC_DISSONANCE / NORMATIVE_ANALYSIS / ML_PATTERN / CHANGE_LOG) · Описание · Ссылки ПД/РД · Уверенность · Нормативная база · Статус инспектора. Banner: «Не являются нарушениями, не входят в сводное число нарушений и не используются как учебные метки.»

**Приложение А «Карточки доказательств»**: one page per candidate/confirmed finding, and per inspector-rejected finding:
- Title «Кандидат №n. {Объект сравнения}» + one-line summary (like the pilot «Нарушение 2. Помещения МГН 267, 270, 271 и 272 / Проектные контуры теплого пола отсутствуют в рабочей документации»).
- Two thumbnails side by side: «ПД — лист 21» (blue frame on the EXPECTED bbox) and «РД ОВ2.1 — лист 4» (red frame on the ACTUAL bbox), with captions from the anchor text. For three-stage evidence a third thumbnail «ИД — …».
- Field grid (all mandatory CMP-57 fields): finding_id; evidence_group_id; код параметра/правила; ожидаемое/фактическое/Δ; per source: стадия, file_id, SHA-256, шифр, редакция, статус утверждения, дата утверждения, лист / страница, bbox; approved_change_ref; тип расхождения; триггер Матрицы and whether exceeded; нормативные ссылки; уровень риска + why; confidence; решение инспектора, причина (reason_code), комментарий, user, time.
- «Обоснование» box (pilot «Вывод» style, red frame).
- Supporting fragments (change-log row, TEP cross-check) as smaller thumbnails.
- Decision trace checklist.

**Приложение Б «Реестр входных файлов»**: every file: file_id · имя · стадия · марка · шифр · редакция · статус утверждения · дата · листы/страницы · SHA-256 · подпись (signature_status) · использован как эталон / исключён (причина); input_manifest_hash.

**Приложение В «Легенда и оговорки»**:
- «ПД — проектное решение, база сравнения» (blue) / «РД, ИД — зона отсутствующего или изменённого решения» (red);
- «Все выводы относятся к указанным листам и зонам. Рамка вокруг помещения не означает нарушение всего листа.»;
- the risk disclaimer;
- «CONFIRMED_VIOLATION присваивается исключительно инспектором.»

**Signature block** (last page):
- «Сформировано автоматически: ИИ-сервис «Инспектор ИИ», model_version …, {timestamp}».
- «Верификацию провёл: {должность} {ФИО} ____ {дата}».
- After finalisation: «Протокол финализирован {timestamp} ({user})» + an e-signature visual stamp «ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ · Сертификат … · Владелец … · Действителен с … по …». This is MOCKED with a test certificate; a detached `.sig` of the PDF/XML is provided.

**Renderers**
- JSON: canonical, validated with Ajv against `components/schemas/Protocol`.
- PDF: Handlebars HTML + CSS paged media → Playwright Chromium.
- DOCX: `docx-templates` with `protocol_template.docx` (styles editable in Word, so a quick adaptation to Приложение 2 is possible).
- XML: `xmlbuilder2` with `inspector-protocol-1.0.xsd`, validated by `libxmljs2` (or `xmllint`).
- GOLD CSV/XLSX: `exceljs`.

**Thumbnails.** Crops of B01 page renders (150 dpi PNG or WebP per page, produced once at parse time), made with `sharp`. The crop is the bbox plus a 15 % context margin, max 1400 px; the overlay is an SVG composite; the output is JPEG q80, cached by `(file_sha256, page, bbox, style)`.

### 3.11 Protocol JSON (sketch)

```json
{
 "schema_version": "1.0",
 "protocol": {"protocol_id":"…","protocol_no":"ИИ-ALT79B-20260927-01","version":2,"version_reason":"INCREMENTAL_UPDATE",
   "previous_version_id":"…","status":"READY","process_id":"…","process_status":"READY","verification_status":null,
   "generated_at":"2026-09-27T12:00:00+03:00","finalized_at":null,
   "versions":{"matrix_version":"1.1+3fa9c2d1","model_version":"IAI-0.3.0","dataset_version":"DS-0.1-pilot9","rules_version":"R-1.0.0","parser_version":"P-0.4.2"},
   "input_manifest_hash":"sha256:…","content_hash":"sha256:…"},
 "object": {"object_id":"ALT79B","name":"Реконструкция. Торговое здание","address":"г. Москва, Алтуфьевское ш., д.79Б, стр.1","permit_number":"…","supervision_case_no":"…","customer":"…","contractor":"…"},
 "upload_status": {"PD":{"code":"PD_UPLOADED","files":3,"expected":3},"RD":{"code":"RD_UPLOADED","files":2,"expected":2},"ID":{"code":"ID_MISSING","files":0,"expected":null},"registry":{"present":true,"valid":true},"rejected_files":[]},
 "scenario": {"code":"PD_RD_ONLY","base":"PD_RD_ONLY","axes":["PD_RD","NORM_PD","NORM_RD"],"explanation":"…"},
 "summary": {"params_total":132,"complete":41,"candidate_groups":3,"candidate_findings":9,"negative_verified":38,"missing_evidence":71,"not_applicable":14,"not_comparable":4,"clarification_required":2,"confirmed_violations":0,"suspicions":1,"coverage":0.31,"abstention":0.03,"by_section":{…},"by_discrepancy_type":{…}},
 "tables": {"completeness":["EG-…"],"candidates":["ALT79B-M003-PDRD-F1R23","…"],"confirmed":[],"negative":["EG-…"],"suspicions":[2001]},
 "evidence_groups": [ { "evidence_group_id":"EG-ALT79B-M003-OBJ","matrix_code":"M-003","matrix_alias":"PZ-03","scope_key":"OBJ",
     "completeness_status":"COMPLETE","finding_status":"CANDIDATE","review_priority":"MEDIUM",
     "stage_slots":{"PD":{"state":"OK","file_ids":["ALT79B-000015"]},"RD":{"state":"OK","file_ids":["ALT79B-000077"]},"ID":{"state":"NOT_APPLICABLE","reason":"достаточно ПД↔РД"}},
     "decision_trace":[…],
     "findings":[ {
       "finding_id":"ALT79B-M003-PDRD-F1R23","axis":"PD_RD","element_key":{"kind":"ROOM","floor":"1","number_expected":"23","number_actual":"22"},
       "discrepancy_type":"FUNCTION_CHANGED",
       "expected_value":{"name":"Помещение","area":{"value":19.41,"unit":"м²"}},
       "actual_value":{"name":"Комната отдыха","area":{"value":19.62,"unit":"м²"}},
       "delta":{"area_abs":0.21,"area_rel":0.0108,"display":"назначение изменено; +0,21 м² (+1,1 %)"},
       "source_expected":{"file_id":"ALT79B-000015","sha256":"…","stage":"PD","document_code":"П-2025-04.266-АР","revision":"0","approval_status":"APPROVED","approval_date":"…","sheet":"3","page":19,"bbox_polygon":[[0.78,0.10,0.91,0.35],[0.36,0.10,0.64,0.25]]},
       "source_actual":{"file_id":"ALT79B-000077","sha256":"…","stage":"RD","document_code":"…","revision":"…","approval_status":"FOR_CONSTRUCTION","sheet":"…","page":4,"bbox_polygon":[[0.80,0.03,0.93,0.27],[0.30,0.09,0.58,0.26]]},
       "supporting":[],
       "approved_change_ref":"NONE","completeness_status":"COMPLETE","finding_status":"CANDIDATE",
       "review_priority":"MEDIUM","risk_level":"MEDIUM","risk_explanation":"…","confidence":0.91,
       "trigger_logic":"Сокращение полезной площади в РД в пользу технических зон.","trigger_exceeded":false,
       "normative_refs":{"sp":null,"gost":null,"fz":null,"other":null},
       "rationale":"В ПД (…, ред. 0, лист 3, стр. 19) помещение №23 «Помещение» 19,41 м²; в РД (…, лист …, стр. 4) на его месте помещение №22 «Комната отдыха» 19,62 м². Изменено назначение помещения; согласованное изменение не найдено.",
       "inspector":{"decision":"PENDING","reason_code":null,"comment":null,"user_id":null,"timestamp":null,"decision_state":"CURRENT"},
       "dataset_version":"DS-0.1-pilot9","matrix_version":"1.1+3fa9c2d1","model_version":"IAI-0.3.0","input_manifest_hash":"sha256:…" } ] } ],
 "suspicions": [ {"suspicion_id":2001,"discovery_method":"CHANGE_LOG","confidence":0.74,"description":"…","pd_reference":"…","rd_reference":"…","review_priority":"MEDIUM","normative_base":null,"finding_status":"SUSPICION","inspector_status":"PENDING"} ],
 "input_registry": [ {"file_id":"ALT79B-000015","file_name":"…","sha256":"…","doc_stage":"PD","discipline":"АР","document_code":"…","revision":"0","approval_status":"APPROVED","approval_date":"…","sheet_page_range":"…","predecessor_id":null,"successor_id":null,"signature_status":"…","used_as_reference":true} ],
 "signatures": []
}
```

In the demo example above the bboxes are the pilot ones. In production they come from extraction.

### 3.12 RabbitMQ contracts

Exchange `inspector.events` (topic, durable). Queues are quorum queues with DLX `inspector.dlx`. Payloads carry `message_id`, `correlation_id=request_id`, `occurred_at`, `schema_version`.

| Routing key / queue | Producer → consumer | Payload |
|---|---|---|
| `parsing.completed` | B01 → orchestrator | `{process_id, object_id, file_ids[], stage_upload_status{PD,RD,ID}, registry_status, parser_version}` |
| `files.added` | B01 → orchestrator | `{process_id, new_file_ids[], replaced{new_id: predecessor_id}}` |
| `comparison.run` → queue `comparison.requests` | orchestrator → Python worker | `{run_id, process_id, object_id, trigger, changed_file_ids[], affected_params[]?, versions{matrix, rules, model, dataset, parser}, input_manifest_hash, deadline_ms}` |
| `comparison.progress` | worker → API (status endpoint) | `{run_id, done, total, current_param}` |
| `comparison.completed` / `comparison.failed` | worker → protocol-service | `{run_id, process_id, status, groups_written, affected_groups[], duration_ms, error?}` |
| `protocol.render` → queue `protocol.render` | protocol-service → report-worker | `{protocol_id, formats[], priority}` |
| `protocol.ready` | protocol-service → B07 notifications, B09 audit, B11 metrics | `{process_id, protocol_id, version, version_reason, summary, pdf_artifact_id}` |
| `protocol.finalized` | protocol-service → B06 РиН, B04-retraining (GOLD) | `{process_id, protocol_id, version, content_hash}` |

Idempotency: the worker skips a `run_id` already completed. Monotonic `run_seq` per process: if a newer run starts, older results are discarded. Retries: ×2 with backoff on worker crash or timeout (consistent with the §9.1 timeout rule), then admin notification (B12).

### 3.13 UI surfaces (data contracts; screens owned by B03/B07)

- **Protocol view.** Header (object, scenario, versions, hash); upload-status badges; summary counters with the «Нарушений: k» emphasis; five tabs = five tables; version selector with «Сравнить с версией…» (diff); export buttons PDF / DOCX / XML / JSON / GOLD.
- **Evidence card component** (shared with verification): side-by-side page viewer (pdf.js, or pre-rendered images with SVG overlays; blue = expected, red = actual), field grid, decision trace, «Разделить на атомарные» action, and the 3-click decision bar (B03).
- **Table (1) actions**: «Дозагрузить» (opens upload with the pre-selected stage/discipline) and «Выбрать авторитетную редакцию» (for CLARIFICATION_REQUIRED; writes the decision via B03 and triggers an incremental run).

### 3.14 Libraries (major versions current as of 2026; pin in lockfiles)

- **Python ≥ 3.11:** pydantic 2 (schemas), SQLAlchemy 2 Core + psycopg 3, aio-pika 9 (RabbitMQ), redis-py 5, numpy 2, scipy 1.1x (linear_sum_assignment), shapely 2 (regions, polygonize), rapidfuzz 3 (typo tolerance), sentence-transformers (model `paraphrase-multilingual-MiniLM-L12-v2`, CPU, ONNX/int8 optional), opencv-python-headless 4 (raster fallback registration/diff), `rfc8785` (JCS). pint is optional; we recommend an own compact unit table because it is deterministic and dependency-free.
- **Node 22 LTS:** the web framework is chosen by backend-core (Fastify 5 recommended for native JSON-schema validation); ajv 8 + ajv-formats; amqplib/amqp-connection-manager; playwright-core 1.x (**not** Puppeteer's bundled Chrome for Testing, which has no linux-arm64 build; the Playwright image and Debian `chromium` work on Apple Silicon Docker); handlebars 4; docx-templates 4; xmlbuilder2 3; libxmljs2 (or xmllint in the image); sharp 0.3x; exceljs 4; `canonicalize` (RFC 8785).
- **Fonts:** PT Astra Serif/Sans (OFL) bundled in the image.

---

## 4. Interfaces with other blocks

| Block | B04 consumes | B04 produces | Contract notes |
|---|---|---|---|
| B01 Upload/parsing/OCR/CV | registry rows (Files + 03 fields), stage upload statuses, per-file extractions: `Extraction{extraction_id, file_id, sha256, stage, discipline, document_code, revision, approval_status, sheet_no, page_index, param_code?, table_type?, element_key?, attrs{}, value_raw, value_norm, unit, bbox_norm, polygon_norm?, anchor_text, method, confidence, quality_flag}`; structured tables `{table_type: EXPLICATION / SPECIFICATION / TEP / CHANGE_LOG / DOOR_SCHEDULE / FINISH_SCHEDULE / LAYERS, rows[{cells, bbox}], page, scope}`; region descriptors (GEOMETRY_CONFIG); axis-bubble detections; page renders (150 dpi); requisites/stamp checks; LOW_QUALITY/ABSTAIN zones | `comparison.run` consumption; the dependency index for "what to extract" (param → doc types) | Bbox convention: [x0,y0,x1,y1], top-left origin, after CropBox/Rotate. B01 must keep `sheet_no` (title-block «Лист») separate from `page_index`. |
| B03 Verification | inspector decisions written to Checks (atomic), split requests, the authoritative revision choice for CLARIFICATION_REQUIRED, approved_change_ref | cards (`GET /findings/{id}`), snapshots on VERIFICATION_COMPLETED/FINALIZED, OUTDATED flags after re-upload | Finalisation precondition check (all CANDIDATE decided or CLARIFICATION_REQUIRED) is computed by B04 and exposed as `can_finalize`. |
| B04-retraining (GOLD) | model_version / dataset_version (Model_Versions) | `protocol.finalized`; GOLD-format export; atomic findings with complete cards | Only CONFIRMED_VIOLATION and inspector NEGATIVE_VERIFIED with complete cards are GOLD-eligible. |
| B05 Free search | Suspicions (→ table 5); SUSPICION→CANDIDATE conversions with rule_id + evidence | change-log entries not mappable to the matrix, as seeds | Dedup is B05's; B04 only prints. |
| B06 РиН | — | `rin-payload` (confirmed only + versions + registry) | Only when PROTOCOL_FINALIZED. |
| B07 Dashboard | — | group statuses for colour (green: no candidates/confirmed; yellow: candidates or clarification; red: confirmed), filters by section/status/date, export endpoints | Colour mapping proposed; B07 decides. |
| B08 Normative base / Params admin | Params snapshot incl. min/max, is_active, data_type, sp/gost/fz refs, comparison_spec, matrix_version | — | Any Params edit ⇒ new matrix_version; running processes keep their snapshot. |
| B09 Audit | — | audit events: protocol version created, export generated (user, IP), snapshot/finalisation/un-finalisation | |
| B11 Monitoring | — | metrics `comparison_duration_seconds`, `protocol_render_seconds{format}`, `incremental_update_seconds`, `candidates_total{section}`, queue depths | |
| B12 Errors/negative scenarios | — | failure events: worker timeout, render failure, schema-validation failure → retry/alert | |

---

## 5. Too complex / risky items and the simplification that still satisfies the letter of the ТЗ

| # | Item | Why it is hard | Simplification (letter of the ТЗ kept) |
|---|---|---|---|
| 1 | Graphic/configuration diffs on drawings (vent branches, warm floor, door position, compartment walls) | Real CV on heterogeneous vector/raster drawings with different framing and scale; the pilot is dominated by such findings | Text-layer token sets per room region + axis-grid registration (RANSAC affine) + simple vector symbol detectors. Raster pages fall back to aligned image difference → composite low-confidence CANDIDATE with the change bbox; the inspector splits it. The pilot vent case is covered at the "labels/branches missing" level. |
| 2 | Deep rule coverage for all 132 params | Each needs specific extraction; many sources are drawings | Tiering: T1 (30 params, deep, demo-critical: TEP, explications, classes, thicknesses, widths, doors, layers, tolerances), T2 generic comparator (works as soon as B01 extracts a value/table), T3 simplified or mocked (spatial ПОС/ПОД zones, external systems M-098…M-100). Every param still gets a group with a definite status, so there are never silent gaps. |
| 3 | Room alignment under renumbering and function changes | Numbers shift (ALT79B №23 → №22) and names have typos | Key match → Hungarian assignment on name/area/position cost → residue as ADDED/MISSING; typo tolerance via rapidfuzz. |
| 4 | Приложение № 2 unknown | A mandatory format may differ from ours | Proposed layout mirroring the organisers' pilot visual language + template-driven renderers (HTML/DOCX templates), so a swap is roughly one day of work. Flagged as data need #1. |
| 5 | «approved change» determination | Requires PD-correction registry and expert conclusions, legal nuance (ст. 49 ГрК РФ) | Registry doc types (PD_CORRECTION / EXPERTISE_CONCLUSION / CHANGE_CONFIRMATION) → hint only; currency resolution handles newer PD revisions; the inspector sets the final approved_change_ref. |
| 6 | Pilot vs trigger semantics | Experts flag sub-threshold changes; the matrix says «> 1%» | Per-param `candidate_policy` (DEVIATION vs TRIGGER), with the trigger feeding risk (decision D1). |
| 7 | Incremental ≤ 1 min with large new files | OCR of a 500-page file takes up to 10 min (§11 #3) | Measure the §11 #9 budget from "new file parsed" to "new protocol version ready" (B04 part ≤ 30 s). Documented interpretation; the comparison + snapshot part alone is ~10–15 s. |
| 8 | УКЭП signing | CryptoPro / ГОСТ Р 34.10-2012 infrastructure not available | Mocked visual stamp + detached signature with a test key + SHA-256 content hash; an adapter interface is left for CryptoPro. |
| 9 | Multi-building objects (корпуса, секции) | Values per section vs per building | `scope_key` from sheet titles («Секция 1», «корпус 7»); aggregates are compared only when coverage is complete, else NOT_COMPARABLE. |
| 10 | Matrix duplicates (M-021/M-124, M-040/M-104, M-041/M-105, M-043/M-106, M-050/M-107, M-080/M-108) | The same fact may be reported twice | Shared extraction; separate groups (codes differ per the matrix) cross-linked with «см. также» in the card. They count separately as candidates; the violation count is per confirmed atomic finding. |
| 11 | Non-matrix pilot findings (IZM12 pile repair in ID, LOS3A door move) | No exact matrix parameter | Map to the closest param only if section and topic match; otherwise SUSPICION (B05) with evidence → CANDIDATE after binding. The inspector can correct the param code during verification (`corrected_param_code`). Decision D5. |
| 12 | Determinism with ML components | Embeddings/CV can drift across library versions | Pin model artefacts by hash in model_version; round similarity to 3 decimals; canonical ordering; the content_hash test in CI. |

---

## 6. ТЗ contradictions and ambiguities (this block)

| # | Issue | Where | Recommended interpretation |
|---|---|---|---|
| 1 | Process statuses (PENDING/PARSING/READY/VERIFYING/COMPLETED/FINALIZED) vs verification statuses (VERIFICATION_COMPLETED/PROTOCOL_FINALIZED) | §9.1 vs §9.3, §9.6 | Treat as aliases: COMPLETED ≡ VERIFICATION_COMPLETED, FINALIZED ≡ PROTOCOL_FINALIZED. The protocol JSON carries both `process_status` and `verification_status`. РиН checks `PROTOCOL_FINALIZED`. |
| 2 | There is no «COMPARING» process status, although comparison is a distinct stage | §9.1 table | Keep the public status PARSING during comparison and rendering; expose sub-stage `stage: COMPARING|RENDERING` + progress on the status endpoint. |
| 3 | PARTIALLY_LOADED overlaps with FULL/PD_RD_ONLY/… | §9.2 alg.2 | PARTIALLY_LOADED wins as the reported scenario; `scenario_base` keeps the composition. |
| 4 | §9.2 says «JSON/PDF», module 7 says «PDF, DOCX, XML» | §9.2 vs §7 | Produce all four (plus GOLD CSV/XLSX). |
| 5 | §9.3 carries the title of §9.2 | §9.3 | Content is verification (B03); B04 references it as «§9.3 (верификация)». |
| 6 | CLARIFICATION_REQUIRED means both "system: revision undetermined" and "inspector: needs clarification" | §9.2 table vs §9.3 | Two fields: `completeness_status=CLARIFICATION_REQUIRED` (system, table 1) vs `inspector_decision=CLARIFICATION_REQUIRED` on a CANDIDATE (table 2, marked). |
| 7 | NEGATIVE_VERIFIED is both a system preliminary status and an inspector GOLD negative | §9.2 alg.3 vs §9.3/§9.4 | `origin: SYSTEM|INSPECTOR`. Only INSPECTOR (or a system negative confirmed by sampling review) is GOLD-eligible. Both appear in table (4) with the origin column. |
| 8 | The GOLD schema has singular expected/actual sources, while a group may span PD, RD and ID | СХЕМА GOLD vs §9.2 | One group per (object, param, scope). Atomic findings carry one axis each (one expected source + one actual source, each possibly with several pages/bboxes). |
| 9 | Matrix triggers (e.g. «> 1%») vs pilot candidates below the threshold | МАТРИЦА vs ПРИМЕРЫ РАЗМЕТКИ (ALT79B +0,49 %, SOSH25 +0,29 %) | `candidate_policy` per param; the trigger drives risk. Decision D1. |
| 10 | «Уровень риска (высокий/средний/низкий)» vs Params.review_priority HIGH/MEDIUM/LOW | §9.2 vs §8.1 | review_priority is the static prior from the matrix; risk_level is computed per finding (§3.8). Both are stored. |
| 11 | No Processes table in §10, although process_id is central (§1.4) | §10 | Add Processes (owned by B01); Protocols gets `process_id`. |
| 12 | Protocols.status enum not defined | §10 #5 | Protocol-version lifecycle (GENERATING / READY / VERIFYING / VERIFICATION_COMPLETED / PROTOCOL_FINALIZED / SUPERSEDED). |
| 13 | Module 1 output is «таблица Checks» while module 2 also fills Checks | §9.1 «Выход» vs §9.2 | B01 persists extractions (staging, cached in Redis by file hash); B04 writes Checks rows (the pipeline includes completeness control). Checks = «Результаты извлечения и сопоставления» as in §10. |
| 14 | Matrix codes M-001…M-132 vs ТЗ examples PZ-01 / KR-55 / AR-41 | §8.1–8.2 vs xlsx | Store `code` (M-055) + `alias_code` (KR-55); section→Latin prefix map ПЗ→PZ, АР→AR, КР→KR (others proposed: SPZU, IOS1…5, POS, POD, OOS, PPM, ODI, ZU, SM); display «M-055 (KR-55)». Confirm with the organisers. |
| 15 | SINGLE_ONLY: what is compared? | §9.2 alg.2 | Only single-stage rules: normative thresholds (Params min/max) and declared tolerances in ID (OKT103-type). Cross-stage rules → MISSING_EVIDENCE, aggregated by stage. |
| 16 | After an incremental update «Статус процесса устанавливается в READY»? | §9.2 alg.5 vs §9.3 p.3 «без сброса верификации» | READY only for the first protocol. Afterwards restore the verification state (VERIFYING if pending candidates exist). |
| 17 | «Сравнение 132 параметров ≤ 2 мин» and «Инкрементальное обновление ≤ 1 мин»: start point undefined | §11 #4, #9 | Measure from "all required files parsed" to "protocol version READY". OCR time is budgeted separately (§11 #2/#3). Report both in metrics. |
| 18 | Evidence card mandatory «для каждого кандидата»; what about negatives and confirmed findings? | §9.2 alg.4 | Full cards for CANDIDATE, CONFIRMED and inspector-rejected findings; compact cards (sources + values) for system negatives in the PDF, full detail in JSON. |
| 19 | NOT_APPLICABLE needs an «обязательное основание», but the ТЗ gives no source of object attributes | 03; §9.2 | An object passport (from the ПЗ/ТЭП extraction or inspector input); an unknown attribute never yields N/A automatically. |
| 20 | Some matrix thresholds look normatively inaccurate: M-117 «Ширина полотна двери в свету < 1.5 м (СП 59.13330)» (СП 59 requires ≥ 0,9 м clear width for doors); M-031 «< 10-12 м»; M-047 «1.5-1.8 м»; M-116 «1.5-1.8 м» (ranges, not single thresholds) | МАТРИЦА | Thresholds live in Params.min/max (B08-editable). Seed conservative values from the trigger text; flag M-117 for normative review; for ranges use the lower bound with a note. Never hard-code. |
| 21 | Evidence group identity includes «актуальные источники», which change on re-upload | §14.1 | Keep the group ID stable per (object, param, scope) and version the sources via `sources_fingerprint`; otherwise history and decisions could not be tracked. |
| 22 | §11 #8 «CV-анализ одного чертежа (DWG)» although inputs are PDF/DOCX/XML | §11 vs §9.1 | Interpret as "one drawing sheet (PDF page)". Not a B04 metric. |

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | What makes a CANDIDATE: any unapproved deviation, or only matrix-trigger breaches? | (a) strict trigger only; (b) any deviation; (c) per-param policy: DEVIATION for design decisions, TRIGGER for pure normative thresholds; the trigger drives risk | **(c)**. It reproduces all 9 pilot labels (ALT79B/SOSH25 are sub-threshold candidates; POL17 negative) while keeping precision on normative params. Configurable per param by the admin. |
| D2 | Protocol layout while Приложение № 2 is missing | (a) wait; (b) proposed layout mirroring the pilot «Графическая фиксация» + §9.2 sections, template-driven | **(b)** now, and request Приложение 2 from the organisers immediately (swap ≈ 1 day). |
| D3 | Where does the comparison engine run? | (a) Python worker (shares ML/normalisation; writes result rows); (b) Node service (rules in TS, calls Python only for embeddings/CV) | **(a)** Python. Rendering and snapshots stay in Node. |
| D4 | PDF rendering engine | (a) HTML → Chromium (Playwright); (b) DOCX template → LibreOffice → PDF; (c) pdfmake | **(a)**. Best control of thumbnails/overlays, fast (≈ 5–10 s), arm64-compatible via Playwright images. DOCX is rendered separately from a Word template. |
| D5 | Non-matrix pilot findings (IZM12 pile repair in ID, LOS3A door move) and weak mappings (vent → M-078/M-079, warm floor → M-077) | (a) map to the closest matrix param; (b) SUSPICION until the inspector binds and converts; (c) hybrid: map when section and topic match, else SUSPICION | **(c)**, plus an inspector-editable `corrected_param_code`. Ask the organisers how the hidden test encodes these (param code? rule?). |
| D6 | A stage absent from the package: MISSING_EVIDENCE or NOT_APPLICABLE? | (a) MISSING_EVIDENCE for rules that need it, NOT_APPLICABLE for rules that don't (pairwise); (b) NOT_APPLICABLE for everything outside the scenario | **(a)**. This is the literal §9.2 reading. The PDF aggregates by stage to stay readable. |
| D7 | Protocol version granularity | (a) snapshot on every decision; (b) snapshots on data changes (initial, re-upload, re-run) + VERIFICATION_COMPLETED + FINALIZED/UN-FINALIZED | **(b)**. Decisions are fully traced in Audit_Log; exports during verification render the current working state labelled «рабочее состояние версии N на {time}». |
| D8 | Show all system NEGATIVE_VERIFIED rows in the PDF? | (a) full; (b) compact table in the PDF, full in JSON/XML | **(b)** |
| D9 | Random sample review of system negatives (§9.2 «Просмотр по выборке») | off / 5 % / 10 % | **10 %** (min 3 per protocol), toggleable. It feeds GOLD negatives. |
| D10 | E-signature | (a) mock stamp + test-key detached signature; (b) CryptoPro integration | **(a)** for the MVP; keep the adapter. |
| D11 | External/cloud LLM for rationale texts | (a) none (deterministic RU templates); (b) local LLM polish; (c) cloud | **(a)**. It is reproducible, needs no 152-ФЗ data-transfer question and is fast. (The global LLM question stays open for other blocks.) |

---

## 8. Data needed

| # | What | Why | Fallback if never received |
|---|---|---|---|
| 1 | **Приложение № 2** (sample output protocol) | Declared mandatory in §9.2 | Proposed layout (§3.10) + template swap path; explicitly state the assumption in the demo. |
| 2 | Full original files behind the pilot ids (ALT79B-000015/000077, UNDMS-000214/000252, IZM12-000064/000007, LOS3A-000009/000069, OKT103-000099, POL16-000035/000136, DOO25-000875/001733, SOSH25-003562/003642, POL17-000031/000096) + their registries | End-to-end testing; page numbers in ПРИМЕРЫ refer to the originals (e.g. PD p.19/20), our excerpt PDF renumbers them | Split the 24-page pilot PDF into per-object synthetic packages. Map the pages to the original page numbers via a lookup (fixture `pilot_page_map.json`) so that GOLD bboxes/pages stay comparable. Write registries by hand. |
| 3 | A sample machine-readable registry (CSV/XLSX/JSON) as the organisers will provide it | Exact column names and value formats (approval_status spelling, sheet_page_range syntax) | Our template following the 03 fields verbatim; tolerant importer (synonyms, RU/EN headers). |
| 4 | Hidden-test output contract: how the jury will score (field names, one row per finding or per group, param-code convention, bbox format) | Metrics are computed "по evidence_group" | Emit GOLD-schema field names exactly + ПРИМЕРЫ notation export; group-level and finding-level views. |
| 5 | Matrix enrichment: data_type, min_value, max_value, regex_pattern, sp/gost/fz references, is_active; alias codes (PZ-01 style) | §8.1 fields are missing in the xlsx | Our derived Appendix A (data_type/shape/kind/threshold) + B08 seeds; alias prefixes per §6 #14. |
| 6 | Examples of approved changes (PD corrections, confirmation letters under ст. 49 ГрК, repeated expertise conclusions) | approved_change_ref semantics and detection | Registry doc types + inspector input; demo with a synthetic «Корректировка» PD revision (POL17 pattern). |
| 7 | Object passport attributes (type, floors, underground, gas, demolition, budget) per test object | NOT_APPLICABLE basis | Extract from ПЗ/ТЭП when present, else an inspector form at process creation; unknown → no auto-N/A. |
| 8 | Reason codes list for rejection (shared with B03) | Table (4), GOLD | ТЗ examples: WRONG_REVISION («актуальная редакция выбрана неверно»), APPROVED_CHANGE, OCR_ERROR, LINKING_ERROR («ошибка привязки»), NOT_APPLICABLE; plus EXTRACTION_ERROR, WITHIN_TOLERANCE, DUPLICATE, OTHER. |
| 9 | Mosgosstroynadzor document conventions (protocol numbering, signatory positions, requisites) | Title page and signature block authenticity | Proposed neutral format; no real organisation branding (a policy constraint as well). |
| 10 | Confirmation of ordinal scales and normative thresholds (M-117 etc.) | Correct CLASS_DOWNGRADED / THRESHOLD results | Built-in scales from СП/ГОСТ knowledge (§3.5.2); thresholds editable in admin. |
| 11 | The number of expected ID files per object (to tell PARTIAL from complete) | PARTIALLY_LOADED detection | Registry `sheet_page_range` + Приложение 19 list + RD ведомости; if nothing is declared, a stage with ≥ 1 file = UPLOADED (documented assumption). |

---

## 9. Jury demo scenario and acceptance criteria

### 9.1 Demo script (≈ 7 minutes, all on pilot-derived packages)

1. **ALT79B (PD_RD_ONLY).** Upload PD АР sheets (pages → orig. p.19, p.20) + RD АР (orig. p.4, p.5) + registry. The status endpoint shows PARSING → COMPARING → READY; the inspector gets the «Протокол готов» notification. The protocol v1 shows:
   - «Статус загрузки»: PD_UPLOADED / RD_UPLOADED / ID_MISSING; «Тип проверки: PD_RD_ONLY».
   - Table (2): group **M-003** with atomic findings:
     - 1 fl.: №23 «Помещение» 19,41 → №22 «Комната отдыха» 19,62 (FUNCTION_CHANGED, renumbering resolved);
     - rooms 18–21 areas changed (VALUE_CHANGED);
     - floor total 2797,27 → 2811,07 (+0,49 %, TOTAL_CHANGED, trigger «> 1%» not exceeded → risk MEDIUM);
     - 2 fl.: №4 «Помещение» → «Раздевалка женская», №6 «Помещение» → «Комната отдыха» (typo «Комтана» recognised as equivalent to «Комната»), total 2513,43 → 2515,70.
   - Group M-002 → NEGATIVE_VERIFIED under TRIGGER policy (or LOW-risk candidate, depending on D1).
   - Card: side-by-side thumbnails with blue/red frames; the bbox IoU against the ПРИМЕРЫ bboxes is shown in a dev overlay (≥ 0,5).
2. **POL17 (negative + stale revision).** The package contains the original PD revision (SUPERSEDED) and «Корректировка №2» (APPROVED) + RD. The result is NEGATIVE_VERIFIED; table (1д) lists the superseded file «исключена из эталонного сравнения». Switch the registry so that both PD revisions lack approval status → CLARIFICATION_REQUIRED, with the conflict shown and no conclusion made.
3. **UNDMS (layers + change log).** PD roof pie vs RD → M-044 LAYER_REMOVED «бронированный стальной лист 6 мм». The RD change-log row (orig. RD p.4) is attached as SUPPORTING_ACTUAL; approved_change_ref = NONE.
4. **OKT103 (SINGLE_ONLY, ID only).** Tolerance check: 15 мм / ±12 мм / 20 мм vs +491/+552, +980/+537, +201/+349 мм → M-054 TOLERANCE_EXCEEDED, risk HIGH. The inspector confirms in ≤ 3 clicks → table (3); «Подтверждённые нарушения: 1».
5. **Incremental update.** For ALT79B, re-upload a corrected RD revision (successor) that fixes the room 4 name. v2 appears in < 1 min, recomputing only M-002/M-003. The diff shows the finding «resolved_by_new_data»; other decisions are kept; v1 stays in history.
6. **Vent (АНО/150321).** PD ИОС5.4.2 vs RD ОВ1/ОВ2.1: missing branches В2.4–В2.9 in rooms 140/142 (ELEMENT_MISSING), a changed configuration in 147/198/314, warm-floor loops missing in 267/270/271/272. The inspector splits the composite candidate into atomic findings.
7. **Exports.** PDF / DOCX / XML / JSON / GOLD-CSV. JSON validates against OpenAPI (show Ajv OK); the XML validates against the XSD; the content_hash printed in the PDF footer equals the hash of the JSON.

### 9.2 Acceptance criteria and tests (automated)

| # | Test | Proves | Pass criterion |
|---|---|---|---|
| T1 | Scenario truth table: 3 stages × {UPLOADED, PARTIAL, MISSING} = 27 cases | CMP-08…13 | Exact expected scenario and base for all 27 |
| T2 | Pipeline precedence matrix (N/A, missing, conflict, unreadable, OK combinations) | CMP-15…23 | Status equals the precedence table; decision_trace lists all issues |
| T3 | Invariants (property-based, Hypothesis): the system never writes CONFIRMED_VIOLATION; finding_status is NULL iff completeness ≠ COMPLETE; SUSPICION is never counted; violation count = confirmed atomic count | CMP-33…38 | 10 000 random inputs, 0 violations |
| T4 | Comparator unit tests per data_type: rounding epsilon, direction, homoglyphs («В35» vs «B35»), ordinal downgrades/upgrades, typo tolerance, CRS mismatch | CMP-25…29 | 100 % of cases |
| T5 | Alignment: ALT79B renumbering (№23 → №22), SOSH25 added 1.109, DOO25 changed areas 13,7 → 11,0 and 5,4 → 6,0 | CMP-30 | Correct pairs and types |
| T6 | Revision resolver: single approved, explicit successor, two heads, missing approval, cycle, superseded only, no registry | CMP-18…21 | Expected status + excluded list |
| T7 | Pilot regression on all 9 ПРИМЕРЫ groups (+ vent) | CMP-01, 44, 57 | Statuses match the labels (per D1 policy); file_id + page exact; bbox IoU ≥ 0,50 for ≥ 95 % of fragments with GOLD bboxes; POL17 negative |
| T8 | Card validator: every CANDIDATE has the complete CMP-57 field set; an unlocalisable one is downgraded to NOT_COMPARABLE | CMP-57, 44 | 0 incomplete cards |
| T9 | Protocol JSON validates against the OpenAPI 3.0 schema; XML against the XSD; the PDF contains the 5 table headings and 2 sections (text extraction check) | CMP-45…56, 84 | Pass |
| T10 | Determinism: same inputs + versions → identical content_hash (run twice, different worker processes) | CMP-06, 07, 64 | Equal |
| T11 | Versioning: re-upload → v2 created, v1 intact and readable, diff correct, decisions carried or OUTDATED per fingerprint | CMP-72…75 | Pass |
| T12 | Finalisation guard: after PROTOCOL_FINALIZED, re-upload/auto-fetch triggers no run and only notifies; the snapshot is unchanged | CMP-76, 78 | Pass |
| T13 | Performance: synthetic object with all 132 params extracted (≈ 5 000 extraction rows, 400 explication rows) | CMP-80 | Comparison ≤ 30 s on 4 vCPU (target), hard limit ≤ 120 s |
| T14 | Protocol generation: 60 candidate cards with thumbnails | CMP-81 | JSON ≤ 1 s; PDF ≤ 20 s; hard limit 30 s |
| T15 | Incremental: one new RD file affecting 3 params | CMP-82 | New version READY ≤ 30 s after `files.added` (hard limit 60 s) |
| T16 | NLP latency: semantic comparison per param with 200 strings, warm cache and cold | CMP-83 | p95 ≤ 500 ms |
| T17 | GOLD export round-trip: our export for the pilot parses into the СХЕМА GOLD columns; the ПРИМЕРЫ notation string matches the source format | CMP-65 | Pass |

---

## 10. Work breakdown

Sizes: S ≤ 0,5 day, M ≤ 1,5 days, L ≤ 3 days.

| ID | Task | Size | Depends on | Owner agent |
|---|---|---|---|---|
| B04-T01 | DB schema & migrations: Checks, Evidence_Groups, Evidence_Fragments, Protocols, Protocol_Artifacts, Comparison_Runs, dictionaries; check constraints (no system CONFIRMED_VIOLATION) | M | platform skeleton (Node, Postgres) | backend-core (Node) |
| B04-T02 | OpenAPI 3.0 components: Protocol, EvidenceGroup, EvidenceCard, Run, Export; the endpoints of §3.7; Ajv validation | M | T01 | backend-core (Node) |
| B04-T03 | Comparison spec DSL (pydantic) + seed of all 132 specs (Appendix A) + Enum_Scales, Unit_Conversions, Term_Synonyms, Discrepancy_Types | M | B08 Params import | comparison-engine (Python) |
| B04-T04 | SnapshotLoader + ScenarioDetector + RevisionResolver (+ manifest hash, versions capture, Comparison_Runs) | M | T01, B01 registry contract | comparison-engine (Python) |
| B04-T05 | Pipeline core: applicability, stage slots, completeness, comparability, precedence, decision_trace, card validator, result writer | L | T03, T04 | comparison-engine (Python) |
| B04-T06 | Comparators: number/enum/string (with embeddings cache)/boolean/coordinate + tolerance/direction/policy logic | M | T03 | comparison-engine (Python) |
| B04-T07 | Aligners: explication rooms (Hungarian), keyed lists, ordered layers (NW), apartment label triples, aggregates; atomiser | L | T06, B01 table extraction | comparison-engine (Python) |
| B04-T08 | ConfigDiff: regions, axis-grid registration, token/symbol sets, raster fallback; change-log miner | L | T07, B01 page renders & text layer | comparison-engine (Python) with the CV agent (B01) |
| B04-T09 | Risk scorer, discrepancy typing, RU rationale templates, approved-change hints | S | T05 | comparison-engine (Python) |
| B04-T10 | RabbitMQ wiring: orchestrator (parsing.completed / files.added → comparison.run), worker consumer, progress, completed/failed, idempotency, retries/DLX | M | T02, T05 | backend-core (Node) + comparison-engine |
| B04-T11 | Protocol assembly & versioning (Node): snapshot builder, content_hash, version reasons, diff endpoint, rin-payload, can_finalize, status transitions (READY / restore after incremental) | M | T02, T10 | protocol/report (Node) |
| B04-T12 | Incremental update: dependency index, affected-set computation, decision carry-over by fingerprint, finalised-protocol guard | M | T05, T11 | comparison-engine + protocol/report |
| B04-T13 | Renderers: HTML/CSS template + Playwright PDF (thumbnails with overlays via sharp), DOCX template, XML + XSD, GOLD CSV/XLSX; artefact cache; fonts in the image | L | T11, B01 page renders | protocol/report (Node) |
| B04-T14 | Pilot demo dataset: split the pilot PDF into per-object packages, registries, page map to original numbering, synthetic variants (superseded, conflict, missing, re-upload successor), expected-results fixtures | M | — (can start now) | data/demo agent |
| B04-T15 | Test suite T1–T17 (unit, property-based, pilot regression with IoU, schema, determinism, performance) + CI job | M | T05–T13 | QA agent |
| B04-T16 | Metrics/logs/audit events for runs, renders, versions | S | T10, T11 | backend-core (Node) |

Critical path: T03 → T04 → T05 → T06/T07 → T11 → T13 → T15. **The explication aligner (T07) and the renderer (T13) are the demo-critical items.** Start T14 immediately; it unblocks everyone's testing.

---

## Appendix A — Comparison spec for all 132 parameters (seed for Param_Rules)

Column legend:
- **dt** = ТЗ data_type (n = number, e = enum, s = string, b = boolean, c = coordinate).
- **shape** = SC scalar, KL keyed list (key in brackets), OL ordered list, SET, GEO.
- **rule**: ANY / DEC / INC / REL>x% / INC_REL>x% / ABS>x / LIM (actual must not exceed the PD value) / MIN v / MAX v (Params bounds; seed from the trigger) / ORD↓ (ordinal downgrade) / SEM (substitution) / PRES (presence) / LAYERS / TOL (ID deviation vs declared tolerance) / DIST>x / GEO.
- **axes**: DC = PD↔RD, EX = RD↔ID (PD↔ID if RD absent), N = single-stage normative check.
- **pol** = candidate policy (D = DEVIATION, T = TRIGGER).
- **tier**: T1 deep, T2 generic, T3 simplified/mocked.

Applicability is "all" unless noted.

| Code | Parameter (short) | dt | shape | rule | axes | pol | tier | applicability / note |
|---|---|---|---|---|---|---|---|---|
| M-001 | Площадь застройки | n | SC | ANY | DC, EX | D | T1 | ID = техплан БТИ |
| M-002 | Общая площадь здания | n | SC (+Σ экспликации) | REL>1% (trigger → risk) | DC, EX | D | T1 | cross-check with explication totals |
| M-003 | Полезная/расчётная площадь | n+s | KL [room] + SC totals | per-room ANY (function, area), DEC useful → technical = trigger | DC, EX | D | T1 | pilot ALT79B, POL16, DOO25, SOSH25, POL17 |
| M-004 | Строительный объём общий | n | SC | ANY | DC, EX | D | T2 | |
| M-005 | Строительный объём подземный | n | SC | ANY | DC, EX | D | T2 | has_underground |
| M-006 | Строительный объём надземный | n | SC | ANY (+ floors link M-007) | DC, EX | D | T2 | |
| M-007 | Этажность | n | SC | ANY | DC, EX | D | T1 | |
| M-008 | Высота здания | n | SC | INC | DC, EX | D | T1 | |
| M-009 | Абсолютная отметка 0.000 | c (1-D, БСВ) | SC | ANY (eps 0,005 м) | DC, EX | D | T1 | elevation system must match |
| M-010 | Количество квартир | n | SC | ANY | DC, EX | D | T1 | residential |
| M-011 | Квартирография | n | KL [apt type] | ANY per type | DC, EX | D | T2 | residential |
| M-012 | Машино-места подземные | n | SC | DEC | DC, EX | D | T2 | underground parking |
| M-013 | Мощность / вместимость | n | SC | DEC | DC, EX | D | T2 | production/social |
| M-014 | Расчётная электрическая мощность | n | SC | LIM (actual > PD/ТУ) | DC, EX | T | T2 | |
| M-015 | Категория надёжности электроснабжения | e | KL [consumer] | ORD↓ | DC, EX | D | T2 | |
| M-016 | Суточное водопотребление | n | SC | LIM | DC, EX | T | T2 | |
| M-017 | Тепловая нагрузка | n | SC | LIM | DC, EX | T | T2 | |
| M-018 | Расход газа | n | SC | LIM | DC, EX | T | T2 | has_gas |
| M-019 | КЗ | n | SC | LIM | DC, EX | T | T2 | |
| M-020 | КИТ | n | SC | LIM | DC, EX | T | T2 | |
| M-021 | Класс энергоэффективности | e | SC | ORD↓ | DC, EX | D | T1 | = M-124 |
| M-022 | Степень огнестойкости | e | SC | ORD↓ | DC, EX | D | T1 | |
| M-023 | Класс конструктивной пожарной опасности | e | SC | ORD↓ | DC, EX | D | T1 | |
| M-024 | Объём грунта (выемка/насыпь) | n | KL [kind] | REL>5% | DC, EX | T | T2 | |
| M-025 | Площадь асфальтобетона | n | SC | REL>5% | DC, EX | T | T2 | |
| M-026 | Площадь плиточного покрытия | n | SC | REL>5% (seed; trigger textual) | DC, EX | T | T2 | threshold to confirm |
| M-027 | Площадь озеленения | n | SC | DEC; MIN (ГПЗУ) | DC, EX, N | D | T2 | |
| M-028 | Площадь детских/спортивных площадок | n | SC | DEC | DC, EX | D | T2 | residential/social |
| M-029 | Спецификация МАФ | n+s | KL [position] | SET (missing, qty DEC, SEM) | DC, EX | D | T2 | |
| M-030 | Ширина проездов | n | KL [driveway] | MIN 4.2 (fire driveways); DEC | DC, EX, N | T | T2 | |
| M-031 | Радиусы поворота | n | KL [curve] | MIN 10 (trigger «10–12»); DEC | DC, EX, N | T | T2 | range → lower bound |
| M-032 | Конструкция дорожной одежды | n+s | OL [layers] | LAYERS | DC, EX | D | T2 | |
| M-033 | Уклоны дорог | n | KL [segment] | ANY; MIN/MAX | DC, EX, N | D | T2 | |
| M-034 | Точки подключения сетей | c | KL [network] | DIST>0.5 м | DC, EX | T | T2 | CRS МСК |
| M-035 | Охранные зоны | b | GEO | PRES (encroachment) | DC, EX | D | T3 | spatial |
| M-036 | Ограждение: тип, высота | s+n | SC composite | SEM(type); DEC(height) | DC, EX | D | T2 | |
| M-037 | Парковочные места на участке | n | SC | DEC | DC, EX | D | T2 | |
| M-038 | Места МГН на участке | n | SC | DEC; MIN 10 % of M-037 | DC, EX, N | D | T2 | derived bound |
| M-039 | Дренажи | b | SET [system] | PRES | DC, EX | D | T2 | |
| M-040 | Ширина эвакуационных коридоров | n | KL [corridor] | MIN 1.2; DEC | DC, EX, N | T | T1 | = M-104 |
| M-041 | Ширина эвакуационных дверей | n | KL [door mark] | MIN 0.9; DEC | DC, EX, N | T | T1 | door schedules |
| M-042 | Высота путей эвакуации и проёмов | n | KL [element] | MIN 2.0 (corridor) / 1.9 (door); DEC | DC, EX, N | T | T2 | |
| M-043 | Открывание эвакуационных дверей | e | KL [door] | ANY → adverse «против хода эвакуации» | DC, EX | D | T3 | GEO symbol |
| M-044 | Пирог кровли | s+n | OL [layers] | LAYERS (removed, substitution, DEC) | DC, EX | D | T1 | pilot UNDMS |
| M-045 | Уклоны кровли, водосток | n | SC composite | DEC (slope, funnels) | DC, EX | D | T2 | |
| M-046 | Окна: количество, габариты | n | KL [window mark] | DEC (qty, area) | DC, EX | D | T1 | |
| M-047 | Тамбуры | n | KL [entrance] | MIN 1.5 (trigger «1.5–1.8»); DEC | DC, EX, N | T | T2 | |
| M-048 | Лестничные марши | n | KL [stair] | ANY(steps); MAX 150 мм riser; MIN 300 мм tread | DC, EX, N | T | T2 | |
| M-049 | Ограждения лестниц/балконов/кровли | n+s | KL [element] | MIN 1.2; DEC; SEM type | DC, EX, N | T | T2 | |
| M-050 | Отделка: класс КМ | e | KL [room] | ORD↓ (evacuation routes) | DC, EX | D | T1 | = M-107 |
| M-051 | КЕО | n | KL [room] | DEC; MIN | DC, EX, N | T | T3 | calc document |
| M-052 | Фасады: цвет/материал | s | KL [facade element] | ANY (normalised RAL/артикул) | DC, EX | D | T2 | |
| M-053 | Шумозащита | b | SET | PRES | DC, EX | D | T2 | |
| M-054 | Шаг и привязка осей | n | KL [axis pair] | ANY (spacing); TOL (ID) | DC, EX, N | D | T1 | pilot OKT103 |
| M-055 | Класс бетона | e | KL [element] | ORD↓ | DC, EX | D | T1 | |
| M-056 | Марка стали | e | KL [element] | ORD↓ | DC, EX | D | T1 | |
| M-057 | Класс арматуры | e | KL [element] | ORD↓ | DC, EX | D | T1 | |
| M-058 | Толщина фундаментной плиты | n | SC/KL | DEC (ID derived from elevations) | DC, EX | D | T1 | |
| M-059 | Толщина плит перекрытий | n | KL [floor] | DEC | DC, EX | D | T1 | |
| M-060 | Сечения колонн | n (b×h → mm²) | KL [mark] | DEC | DC, EX | D | T1 | |
| M-061 | Толщина несущих стен | n | KL [wall] | DEC | DC, EX | D | T1 | |
| M-062 | Диаметр арматуры | n | KL [element] | DEC | DC, EX | D | T2 | |
| M-063 | Деформационные швы | b | SET [joint] | PRES; GEO | DC, EX | D | T2 | |
| M-064 | Лифтовые шахты | n+c | KL [shaft] | DEC(dims); DIST(position) | DC, EX | D | T2 | has lifts |
| M-065 | Технологические проёмы | n | KL [opening] | DEC / PRES | DC, EX | D | T2 | |
| M-066 | Огнезащита | s+n+e | SC composite | SEM(material); DEC(thickness); ORD↓(R/REI) | DC, EX | D | T2 | |
| M-067 | Расход материалов | n | KL [material] | REL>2% | DC, EX | T | T2 | |
| M-068 | Номиналы автоматов ВРУ | n | KL [breaker] | ANY | DC, EX | D | T2 | |
| M-069 | Сечение и марка кабелей | n+e | KL [line] | DEC(section); ORD↓(fire index) | DC, EX | D | T2 | |
| M-070 | Заземление, молниезащита | n | SC composite | DEC(electrodes); INC/MAX(R) | DC, EX, N | D | T2 | |
| M-071 | Диаметры стояков В1/Т3 | n | KL [riser] | DEC | DC, EX | D | T2 | |
| M-072 | Материал труб В1/Т3 | s | KL [system] | SEM | DC, EX | D | T2 | |
| M-073 | Насосные станции | n | KL [station] (Q,H,P) | DEC | DC, EX | D | T2 | |
| M-074 | Выпуски К1/К2 | n | KL [outlet] | DEC | DC, EX | D | T2 | |
| M-075 | Материал канализационных труб | s | KL [system] | SEM (adverse table) | DC, EX | D | T2 | |
| M-076 | Диаметры Т1/Т2 | n | KL [segment] | ANY | DC, EX | D | T2 | |
| M-077 | Отопительные приборы | n+b | KL [room/device] | DEC(W, qty); PRES (warm-floor loops) | DC, EX | D | T2 | vent pilot #2 (warm floor), weak mapping (D5) |
| M-078 | Сечения воздуховодов | n | KL [system/segment] | DEC; GEO (branches) | DC, EX | D | T1 | vent pilot #3 (local exhaust branches), mapping D5 |
| M-079 | Вентиляторы | n | KL [system] (L,P,N) | DEC; GEO (unit configuration) | DC, EX | D | T1 | vent pilot #1 (венткамера 012) |
| M-080 | АПС состав | n | KL [zone] | DEC | DC, EX | D | T2 | = M-108 |
| M-081 | Опасные зоны кранов | n+GEO | KL [crane] | INC radius; GEO boundary | DC, EX | D | T3 | |
| M-082 | Продолжительность этапов | n | KL [stage] | INC_REL>10% | DC, EX | T | T2 | ID derived from journal dates |
| M-083 | Временные здания | c+n | KL | GEO | DC, EX | D | T3 | |
| M-084 | Ширина временных дорог | n | KL [road] | MIN 3.5 (trigger «3.5–4.5»); DEC | DC, EX, N | T | T2 | |
| M-085 | Площадки складирования | GEO | GEO | GEO | DC, EX | D | T3 | |
| M-086 | Максимальная численность | n | SC | LIM | DC, EX | T | T2 | |
| M-087 | Технологическая последовательность | s | SC | SEM | DC, EX | D | T3 | |
| M-088 | Временные ресурсы | n | KL [resource] | LIM | DC, EX | T | T2 | |
| M-089 | Мойка колёс | b | SET [exit] | PRES | DC, EX | D | T2 | |
| M-090 | Зоны развала | n+GEO | KL | INC; GEO | DC | D | T3 | demolition |
| M-091 | Методы демонтажа | s | SC | SEM | DC, EX | D | T3 | demolition |
| M-092 | Защита коммуникаций | b | SET | PRES | DC, EX | D | T2 | demolition |
| M-093 | Объёмы демонтажа | n | KL [type] | REL>5% | DC, EX | T | T2 | demolition |
| M-094 | Отходы: масса, класс | n+e | KL [waste code] | INC(mass); ORD adverse (claimed less hazardous) | DC, EX | D | T2 | demolition/earthworks |
| M-095 | Пылеподавление | b | SET | PRES | DC, EX | D | T2 | demolition |
| M-096 | Узлы расчленения | n+b | KL [node] | DEC; PRES | DC, EX | D | T2 | demolition |
| M-097 | Площадки лома | n+GEO | KL | GEO | DC, EX | D | T3 | demolition |
| M-098 | Регистрация в АИС ОСИГ | b | SC | PRES (e-passport in ID) | N(ID) | T | T3 | MOCKED external |
| M-099 | ГЛОНАСС | b | SC | PRES (logs in ID) | N(ID) | T | T3 | MOCKED external |
| M-100 | Мобильный КПТС | b | SC | PRES (logs in ID) | N(ID) | T | T3 | MOCKED external |
| M-101 | Легитимность утилизации | s | SET | membership (полигон ∈ ТРПО) | EX | T | T3 | |
| M-102 | Пожарные отсеки | n+GEO | KL [compartment] | INC(area); GEO continuity | DC, EX | D | T2 | |
| M-103 | EI дверей и ворот | e | KL [door] | ORD↓ | DC, EX | D | T1 | |
| M-104 | Ширина/высота эвакуационных проходов | n | KL | MIN 1.2; DEC | DC, EX, N | T | T1 | = M-040 |
| M-105 | Двери наружных эвакуационных выходов | n | KL [door] | MIN 0.9; DEC | DC, EX, N | T | T1 | |
| M-106 | Открывание дверей (ППМ) | e | KL [door] | as M-043 | DC, EX | D | T3 | = M-043 |
| M-107 | Класс КМ отделки (ППМ) | e | KL [room] | ORD↓ | DC, EX | D | T1 | = M-050 |
| M-108 | Извещатели АПС | n | KL [room/zone] | DEC(count); MAX spacing | DC, EX, N | D | T2 | = M-080 |
| M-109 | Маркировка кабелей СПЗ | e | KL [line] | ORD↓ (FRLS/FRHF required) | DC, EX, N | D | T2 | |
| M-110 | Оповещатели СОУЭ | n+b | KL [floor] | DEC; PRES («Выход») | DC, EX | D | T2 | |
| M-111 | ОЗК | b+e | KL [crossing] | PRES; ORD↓ EI | DC, EX | D | T2 | |
| M-112 | Вентиляторы ДУ/подпора | n | KL [system] | DEC | DC, EX | D | T2 | |
| M-113 | ВПВ | n | SC composite | DEC (flow, jets, ring Ø, hydrants) | DC, EX | D | T2 | if ВПВ required |
| M-114 | НПВ | n+GEO | SC | DEC; GEO coverage | DC, EX | D | T2/T3 | |
| M-115 | Подъёмники МГН | b+s | SET [lift] | PRES; SEM type | DC, EX | D | T2 | if in PD |
| M-116 | Коридоры МГН | n | KL | MIN 1.5 (trigger «1.5–1.8»); DEC | DC, EX, N | T | T2 | |
| M-117 | Двери МГН | n | KL [door] | MIN (seed 0.9 per СП 59; matrix says 1.5, flagged); DEC | DC, EX, N | T | T2 | normative review |
| M-118 | Пороги МГН | n | KL [door] | MAX 0.014; INC | DC, EX, N | T | T2 | |
| M-119 | Санузлы МГН | n | KL [room] | MIN (matrix 1.5); DEC | DC, EX, N | T | T2 | |
| M-120 | Поручни | n | KL [sanitary room] | DEC / PRES | DC, EX | D | T2 | |
| M-121 | Места для инвалидов: количество, габариты | n | SC composite | DEC(count); MIN width 3.5 | DC, EX, N | D | T2 | |
| M-122 | Тактильные указатели | b | SET [location] | PRES | DC, EX | D | T2 | |
| M-123 | Связь / вызов помощника | b | SET [location] | PRES | DC, EX | D | T2 | |
| M-124 | Класс энергоэффективности (ЗУ) | e | SC | ORD↓ | DC, EX | D | T1 | = M-021 |
| M-125 | Толщина утеплителя стен | n | KL [wall type] | DEC | DC, EX | D | T2 | |
| M-126 | λ утеплителя | n | KL [material] | INC | DC, EX | D | T2 | LOS3A change log mentions λ |
| M-127 | Ro окон | n | KL [window type] | DEC | DC, EX | D | T2 | |
| M-128 | Утеплитель кровли | n | SC/KL | DEC | DC, EX | D | T2 | |
| M-129 | Приборы учёта | n | KL [resource] | DEC / PRES | DC, EX | D | T2 | |
| M-130 | Энергосберегающее освещение | s | KL [fixture type] | SEM (LED → non-LED adverse) | DC, EX | D | T2 | |
| M-131 | Удельный расход тепла | n | SC | INC / LIM | DC, EX | T | T2 | |
| M-132 | Стоимость ССР | n | SC | INC_REL>5% | DC, EX | T | T2 | budget_funded / СМ present |

Tier counts: T1 = 30, T2 = 86 (+ M-114 marked T2/T3), T3 = 15 (incl. 3 mocked external systems M-098…M-100).

---

## Appendix B — Pilot groups mapped to this design (demo fixtures)

| finding_id (pilot) | Label | Proposed code (D5) | Axis | Shape / discrepancy types | Evidence roles | Expected system output |
|---|---|---|---|---|---|---|
| ALT79B-V01 | CANDIDATE | M-003 (+ M-002 total) | PD_RD | KL rooms: FUNCTION_CHANGED (№23 → №22 «Комната отдыха»; №4 → «Раздевалка женская»; №6 → «Комната отдыха»), VALUE_CHANGED (rooms 18–21; «Склад» 1012,26 → 1012,49 etc.), TOTAL_CHANGED (+0,49 % / +0,09 %) | EXPECTED PD p.19/20 explication + plan zones; ACTUAL RD p.4/5 | CANDIDATE, risk MEDIUM (trigger not exceeded) |
| UNDMS-V01 | CANDIDATE | M-044 | PD_RD | OL layers: LAYER_REMOVED «бронированный стальной лист 6 мм» | EXPECTED PD p.16; ACTUAL RD p.10; SUPPORTING_ACTUAL RD p.4 (change log) | CANDIDATE, risk HIGH (security object; approved_change_ref NONE) |
| IZM12-V01 | CANDIDATE | rule / SUSPICION → CANDIDATE (closest M-058) | RD_ID | UNDOCUMENTED_WORK (pile repair scheme present in ID, absent in RD КЖ02.1) | EXPECTED RD p.4; ACTUAL ID p.15 (2 bboxes) | CANDIDATE via B05 conversion (D5) |
| LOS3A-V01 | CANDIDATE | rule / closest M-011 (planning) | PD_RD | POSITION_SHIFTED (door of СУ, apt 2.4.1) | EXPECTED PD p.41; ACTUAL RD p.15; SUPPORTING_ACTUAL RD p.8 (ведомость изменений) | CANDIDATE (change-log-driven), D5 |
| OKT103-V01 | CONFIRMED_VIOLATION | M-054 | NORM_ID | TOL: TOLERANCE_EXCEEDED (15 / ±12 / 20 мм vs +491/+552, +980/+537, +201/+349 мм) | NORMATIVE (tolerance note) + ACTUAL deviations, ID p.1 (2 bboxes) | CANDIDATE, risk HIGH → inspector CONFIRMED_VIOLATION |
| POL16-V01 | CANDIDATE | M-003 | PD_RD | KL apartments: VALUE_CHANGED of the triples жилая/общая/с летними; rule same_type_same_geometry | EXPECTED PD p.62; ACTUAL RD p.21 | CANDIDATE |
| DOO25-V01 | CANDIDATE | M-003 | PD_RD | KL rooms 135–150: VALUE_CHANGED (13,7 → 11,0; 5,4 → 6,0 …), CONFIGURATION_CHANGED; TOTAL 1115,8 → 1112,6 | EXPECTED PD p.27; ACTUAL RD p.12 | CANDIDATE |
| SOSH25-V01 | CANDIDATE | M-003 (+ M-002) | PD_RD | ELEMENT_ADDED room 1.109 (18,2 м²); TOTAL_CHANGED 6234,1 → 6252,3 (+0,29 %) | EXPECTED PD p.49; ACTUAL RD p.34 | CANDIDATE |
| POL17-N01 | NEGATIVE_VERIFIED | M-003 / M-002 | PD_RD | no discrepancy; PD = «Корректировка №2, 02.2025» | PD p.26/27; RD p.7/8 | NEGATIVE_VERIFIED; superseded PD excluded (if present) |
| АНО/150321 #1 | (expert list) | M-079 | PD_RD | GEO: CONFIGURATION_CHANGED (венткамера 012, supply units) | PD sheet 26; RD ОВ1 sheet 3 | CANDIDATE (composite) |
| АНО/150321 #2 | (expert list) | M-077 | PD_RD | PRES: ELEMENT_MISSING warm-floor loops in МГН rooms 267/270/271/272 | PD sheet 21; RD ОВ2.1 sheet 4 | CANDIDATE, 2 atomic (267/270, 271/272) or 4 per room |
| АНО/150321 #3 | (expert list) | M-078 | PD_RD | GEO: ELEMENT_MISSING В2.4–В2.6 (142), В2.7–В2.9 (140); CONFIGURATION_CHANGED (147: В2.10 vs В2.2–В2.4; 198: В2.2–В2.3 vs В2.8–В2.10; 314: В3.1–В3.2 vs other В3) | PD sheet 10; RD ОВ1 sheets 4, 6 | CANDIDATE with 5 atomic findings; the inspector may split further |

Page numbers above are the **original** file pages from ПРИМЕРЫ РАЗМЕТКИ; the fixture maps them to the 24-page excerpt (e.g. ALT79B PD p.19 → excerpt p.2, RD p.4 → excerpt p.3).
