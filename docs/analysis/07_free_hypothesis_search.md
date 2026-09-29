# B07 — Модуль свободного поиска гипотез (ТЗ Module 5, priority High)

Analysis/planning report. No application code. Language: English. Russian domain terms, statuses and ТЗ quotes are kept verbatim.

---

## 0. Executive summary (read this first)

1. **Module 5 matters more for scoring than its position in the ТЗ suggests.** 6 of the 9 pilot evidence groups (ALT79B, UNDMS, LOS3A, POL16, DOO25, SOSH25), plus all 3 findings in the ventilation markup, are changes at room or element level: a room renamed or re-purposed, a room added, room areas changed, a layer removed, a door moved, warm-floor contours missing, local exhaust branches missing or changed. One more (IZM12) is a document-level «works in ИД without a РД basis» case. The Matrix does not capture most of them. For the three area/function pilots, the floor totals change by **+0.49 % (ALT79B), +0.29 % (SOSH25) and −0.29 % (DOO25)**. That is below the M-002 trigger «Дельта общей площади между ПД и РД (или ИД) > 1%», so a pure matrix engine cannot flag them. They surface only through room-level analysis. I measured these values from the pilot PDFs (§3.9).
2. **The pilot contains no SUSPICION example.** All 8 non-negative groups are labelled `CANDIDATE` or `CONFIRMED_VIOLATION`. So the hidden test probably expects this type of change to come out as a scored `CANDIDATE`, not as an unscored `SUSPICION`. This forces two decisions (D1, D2 in §7):
   - a strict, auditable **auto-promotion gate** SUSPICION → CANDIDATE. It fires only when the system has bound concrete sources and coordinates, which is the only precondition the ТЗ states for this step («Для перевода в CANDIDATE требуются конкретные источники и координаты доказательств»);
   - a **change-fact router** that sends each atomic change either to a matrix parameter (Module 2) or to Module 5. No change is ever counted twice.
3. **Design: one change-detection engine, five detectors.** The engine is built on the vector text layer, not on pixels. Its core is a *room / element inventory* per sheet: explication rows, room labels, system tags and legend items. The five detectors are:
   - (1) `LOGICAL_ANALYSIS` — a JSON-AST rule engine with three-valued logic over `Logical_Rules`;
   - (2) `SEMANTIC_DISSONANCE` — room alignment across stages, a room-function taxonomy, pymorphy3, fuzzy matching and a multilingual MiniLM, plus an antonym and category-shift severity matrix;
   - (3) `NORMATIVE_ANALYSIS` — checks against `Normative_Base` min/max values, choosing the edition by `effective_from/to`;
   - (4) `ML_PATTERN_ANALYSIS` — robust intra-object statistics plus IsolationForest, and a cross-object history store that improves as data accumulates;
   - (5) `GRAPHIC_DIFF` — an extension beyond the 4 mandated approaches: sheet registration from matched labels, a tolerant raster/vector diff restricted to the plan viewport, and aggregation per room.
4. **Feasibility checked on the real pilot files (§3.9):**
   - explication tables extract exactly from the text layer, e.g. ALT79B 24 rows each for ПД and РД;
   - label-based sheet registration recovers scale and offset: 1.000 / −178.7 pt; 2.000 for SOSH25 overview vs fragment;
   - the prototype found **an arithmetic inconsistency the expert markup did not mention**. In the ALT79B ПД explication the rows sum to **2795.04 m²**, but «Общий итог по этажу» reads **2797.27 m²** (Δ 2.23 m²). This is a ready-made free-search demo;
   - raw page-level raster diff is **not** usable as a violation signal. On the NEGATIVE_VERIFIED pair (POL17) the РД still adds 13–19 % extra ink (marking tags, schedules). Graphic diff must therefore be viewport-scoped, directional (weighted toward "missing in РД") and aggregated per room.
5. **Offline by default.** Any LLM sits behind a pluggable interface with a `Noop` default. It never creates evidence or coordinates. A cloud LLM is used only if the user confirms that 152-ФЗ / data-localisation constraints allow it.

---

## 1. Scope

### 1.1 ТЗ clauses covered

| Clause | Quote (verbatim) | What it means for this block |
|---|---|---|
| §7, module 5 (priority **High**) | «Формирование SUSPICION вне Матрицы; без включения в число нарушений и GOLD до доказательной привязки и решения инспектора» | Core mandate |
| §9.5 Назначение | «автоматическое формирование гипотез о возможных расхождениях вне Матрицы. Результат имеет статус SUSPICION и не считается нарушением до формирования карточки доказательств и решения инспектора» | Status semantics |
| §9.5, table of approaches | 1 «Логический анализ … "Если A, то должно быть B"» (пример: «Если этажей > 10, должен быть лифт»); 2 «Семантический диссонанс … Поиск противоречий в терминологии между ПД и РД» («В ПД – «Техническое», в РД – «Склад ГСМ»»); 3 «Нормативный анализ … Проверка соответствия СП/ГОСТ/СанПиН» («Высота комнат 2.4 м вместо 2.5 м по СанПиН»); 4 «ML-паттерн-анализ … Обучение на исторических данных для поиска аномалий» («Расход бетона на 20% ниже среднего») | The 4 mandatory approaches |
| §9.5, «Структура подозрения (Suspicion)» | JSON with `suspicion_id, discovery_method, confidence, description, pd_reference, rd_reference, review_priority, normative_base, finding_status: "SUSPICION", inspector_status: "PENDING"` | Output contract |
| §9.5, «Дедупликация подозрений» | «гипотезы объединяются только внутри одного объекта и сопоставимых редакций. SUSPICION не считается нарушением, не входит в сводное число нарушений и не используется как положительная учебная метка. Для перевода в CANDIDATE требуются конкретные источники и координаты доказательств; для CONFIRMED_VIOLATION — решение инспектора.» | Dedup, exclusion from counts, conversion gate |
| §9.2 p.4 | protocol tables «… (5) гипотезы свободного поиска»; mandatory evidence card for every candidate: «finding_id, код параметра/правила, expected/actual, file_id и SHA-256 каждого источника, стадия, шифр, редакция, статус утверждения, лист/страница, bbox/polygon, обоснование, уровень риска, решение инспектора и причина решения» | Protocol section; evidence card needed on conversion |
| §9.2, status table, row SUSPICION | «Гипотеза свободного поиска вне Матрицы … Включение в число нарушений: Нет … Действие инспектора: Сначала привязать доказательства; затем при необходимости преобразовать в CANDIDATE» | Inspector workflow |
| §9.2 p.1 | «Версии Матрицы, набора данных и модели фиксируются в каждом запуске и в протоколе» | Run versioning (plus rules and taxonomy versions) |
| §9.2, incremental update | «выполняет инкрементальное обновление только по тем параметрам, для которых появились новые данные. Предыдущая версия протокола сохраняется в истории» | Incremental hypothesis runs |
| §9.1 p.2 | «Sentence-BERT (all-MiniLM-L6-v2) или её совместимые аналоги» | Embedding model choice |
| §9.1 p.3–4 | CV: «масштабирование по размерной линейке, распознавание линий и измерение расстояний»; coordinates «к диапазону [0;1] … после учёта CropBox, MediaBox и Rotate» | Graphic diff; evidence geometry |
| §9.1 «Выбор актуальной редакции» | «Устаревшая редакция не может использоваться как эталон»; conflict → «CLARIFICATION_REQUIRED и не формирует вывод о нарушении» | Hypotheses only on актуальные revisions |
| §9.3 p.2, p.4, p.5, «Отмена финализации» | atomic findings; «В ИАИС «РиН» передаются только подтверждённые инспектором записи»; «После финализации дозагрузка и изменения статусов становятся невозможными» | Freeze; no suspicions sent to РиН |
| §9.4 | «CANDIDATE, SUSPICION, MISSING_EVIDENCE и незавершённые решения в обучение не включаются»; object-level split; no auto-publication of models | Training exclusion |
| §10 tables #8, #9, #10 | Suspicions (id, object_id, discovery_method, confidence, description, inspector_status); Logical_Rules (id, rule_name, condition, expected, normative_base, is_active); Normative_Base (id, document_name, document_number, section, parameter_name, min_value, max_value, effective_from, effective_to) | Data model |
| Приложение 1, sheet «СХЕМА GOLD» | `matrix_code / rule_version`: «M-001…M-132 либо версия правила свободного поиска»; «CANDIDATE и SUSPICION не являются положительной GOLD-меткой» | Rule code and version on converted findings |
| §11 #4, #7, #8, #9, #10 | comparison ≤ 2 min; «ML-анализ одного параметра (NLP) Не более 500 мс»; «CV-анализ одного чертежа (DWG) Не более 30 секунд»; incremental ≤ 1 min; API p95 ≤ 200 ms | Performance budgets |
| §12 #2, #4, #6; §13 | roles; audit; 152-ФЗ; JSON logs; Prometheus | Cross-cutting NFRs |
| §14.3 | «False Positive Rate на NEGATIVE_VERIFIED … ≤ 0,10» | FP gate on the negative pair (POL17) |

### 1.2 Related statuses

- `finding_status`: always `SUSPICION` for records in `Suspicions`. After conversion, a new record in `Checks` carries `CANDIDATE`.
- `inspector_status` values. The ТЗ defines only `PENDING`; the rest is our proposal (§3.7): `PENDING`, `CLARIFICATION_REQUIRED`, `DISMISSED`, `CONVERTED_TO_CANDIDATE`, `AUTO_CONVERTED` (only if D1 = hybrid), `STALE`, and the frozen marker `NOT_REVIEWED_AT_FINALIZATION`.
- Process statuses we depend on: `PARSING` (no run), `READY`/`VERIFYING`/`COMPLETED` (actions allowed), `FINALIZED`/`PROTOCOL_FINALIZED` (frozen).

---

## 2. Requirements checklist

Legend. Priority for winning: MUST / SHOULD / NICE. MVP decision: FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

| ID | Requirement (atomic) | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| HYP-01 | Automatically generate hypotheses about discrepancies **outside** the Matrix for each process | §7 #5; §9.5 Назначение | MUST | FULL | Core of a High module |
| HYP-02 | Every hypothesis is created with status `SUSPICION` and is not a violation until an evidence card exists and the inspector has decided | §9.5 | MUST | FULL | Enforced by a DB CHECK constraint and service logic |
| HYP-03 | Approach 1: logical analysis «Если A, то должно быть B», including the ТЗ example (floors > 10 → lift) | §9.5 #1 | MUST | FULL | JSON-AST rule engine with 3-valued logic; ~12 seed rules |
| HYP-04 | `Logical_Rules` table with `id, rule_name, condition, expected, normative_base, is_active` (plus versioning) | §10 #9 | MUST | FULL | Rules are data, not code |
| HYP-05 | Approach 2: semantic dissonance between ПД and РД terminology (e.g. «Техническое» → «Склад ГСМ») | §9.5 #2 | MUST | FULL | Room alignment + taxonomy + morphology + embeddings |
| HYP-06 | Approach 3: normative analysis against СП/ГОСТ/СанПиН min/max values (e.g. height 2.4 vs 2.5 m) | §9.5 #3 | MUST | SIMPLIFIED | Engine is full. Facts are limited to what can be extracted reliably (room areas from explications; heights best-effort) |
| HYP-07 | Use `Normative_Base` (`min_value, max_value, effective_from, effective_to`) and pick the edition in force | §10 #10; §7 #8 | MUST | FULL | Consumed from the Module 8 admin; thresholds editable without code changes |
| HYP-08 | Approach 4: ML pattern / anomaly analysis (e.g. concrete consumption −20 % vs average) | §9.5 #4 | MUST | SIMPLIFIED | No history is available. Intra-object robust statistics + IsolationForest + reference priors now; the cross-object model comes later (HYP-56) |
| HYP-09 | Suspicion JSON contains exactly the ТЗ fields (names verbatim); extra fields are additive | §9.5 | MUST | FULL | Contract test against the ТЗ example |
| HYP-10 | Initial `finding_status="SUSPICION"`, `inspector_status="PENDING"` | §9.5 | MUST | FULL | — |
| HYP-11 | `pd_reference` / `rd_reference` in human form «<шифр>, л.<лист>, стр.<страница>» | §9.5 example | MUST | FULL | Generated from the Files registry and sheet metadata |
| HYP-12 | `review_priority` HIGH/MEDIUM/LOW, used only to order review; «не юридическое действие» | §9.5; §8.1; §9.2 | MUST | FULL | Derived from severity and confidence |
| HYP-13 | `normative_base` filled when a rule or norm exists; otherwise «—» | §9.5 | MUST | FULL | — |
| HYP-14 | `confidence` in [0;1] | §9.5 | MUST | FULL | Heuristic priors now; isotonic calibration later on legitimate GOLD only |
| HYP-15 | Defined `discovery_method` enum covering the 4 approaches (+ `GRAPHIC_DIFF` extension, D3) | §9.5 | MUST | FULL | The ТЗ shows only `LOGICAL_ANALYSIS`; the enum is ours |
| HYP-16 | Dedup **only** within one object and comparable revisions | §9.5 | MUST | FULL | Fingerprint includes object_id + revision fingerprint |
| HYP-17 | SUSPICION is excluded from «сводное число нарушений» and from all violation counters and dashboards | §9.5; §9.2 table | MUST | FULL | Counters read only `Checks.finding_status='CONFIRMED_VIOLATION'` |
| HYP-18 | SUSPICION is never a training label (neither positive nor negative); dismissed suspicions are not GOLD | §9.5; §9.4; СХЕМА GOLD | MUST | FULL | Dataset builder filters on source type |
| HYP-19 | Conversion to CANDIDATE only with concrete sources **and** coordinates bound (evidence gate) | §9.5 | MUST | FULL | Server-side gate; 409 lists what is missing |
| HYP-20 | `CONFIRMED_VIOLATION` only by inspector decision, after conversion | §9.5; §9.2 p.3 | MUST | FULL | Module 3 flow |
| HYP-21 | Inspector can bind evidence (pick a suggested fragment or draw a bbox) and then convert | §9.2 status table | MUST | FULL | UI + API |
| HYP-22 | `Suspicions` table with the ТЗ key fields (+ process, run, rule, references, evidence status, decision) | §10 #8 | MUST | FULL | §3.6 |
| HYP-23 | Protocol has a separate table (5) «гипотезы свободного поиска» | §9.2 p.4 | MUST | FULL | Layout is provisional until Приложение № 2 arrives |
| HYP-24 | Evidence coordinates normalised to [0;1] after CropBox/MediaBox/Rotate | §9.1 p.4 | MUST | FULL | Reuse the Module 1 normaliser |
| HYP-25 | A converted CANDIDATE carries the full evidence card (all §9.2 p.4 fields) | §9.2 p.4 | MUST | FULL | Gate checks every field |
| HYP-26 | Converted findings carry `rule_code` + `rule_version` (free-search analogue of `matrix_code`) | СХЕМА GOLD; §9.2 p.4 «код параметра/правила» | MUST | FULL | e.g. `HR-SEM-001@v2` |
| HYP-27 | Each run records matrix/dataset/model versions **and** the versions of the rules set, normative set and taxonomy | §9.2 p.1; §14.2 «Версионность» | MUST | FULL | `Hypothesis_Runs` table |
| HYP-28 | Only актуальные approved revisions are used as sources; revision conflicts produce no hypothesis | §9.1; registry rules | MUST | FULL | Consume the Module 1 revision chain |
| HYP-29 | Incremental re-run after dozagruzka covers only affected detectors and pairs; superseded suspicions are marked STALE; history is kept | §9.2 | MUST | FULL | — |
| HYP-30 | Freeze after finalization; «Отмена финализации» re-enables actions | §9.3 p.5 | MUST | FULL | — |
| HYP-31 | Suspicions are never sent to ИАИС «РиН» (only confirmed records are) | §9.3 p.4; §9.6 | MUST | FULL | Export filter + test |
| HYP-32 | Hypotheses are atomic (one subject: a room, element or document) so they convert into atomic findings | §9.3 p.2 | SHOULD | FULL | UI groups them visually |
| HYP-33 | Approaches run per load scenario (`FULL`, `PD_RD_ONLY`, `PD_ID_ONLY`, `RD_ID_ONLY`, `SINGLE_ONLY`, `PARTIALLY_LOADED`) | §9.2 p.2 | MUST | FULL | Applicability matrix in §3.1 |
| HYP-34 | Performance: NLP per item ≤ 500 ms; graphic diff per sheet ≤ 30 s; fits inside comparison ≤ 2 min and incremental ≤ 1 min; API p95 ≤ 200 ms | §11 #4, #7, #8, #9, #10 | MUST | FULL | Budgets and measurement in §3.10 |
| HYP-35 | Async via RabbitMQ; REST + OpenAPI 3.0 validation; pull model | §1.3–1.5 | MUST | FULL | §3.5 |
| HYP-36 | Redis cache for heavy intermediate results (registration, embeddings), keyed by file hash | §9.1 p.5 | SHOULD | FULL | — |
| HYP-37 | SBERT-compatible embedding model («совместимые аналоги») suitable for Russian | §9.1 p.2 | MUST | FULL | `paraphrase-multilingual-MiniLM-L12-v2` (multilingual sibling of all-MiniLM) |
| HYP-38 | Audit of every suspicion action (bind, convert, dismiss, clarify, reopen, rule edits) | §7 #9; §12 #4 | MUST | FULL | Via Module 9 |
| HYP-39 | RBAC: inspector acts on suspicions; admin manages rules; ML engineer sees statistics | §12 #2 | MUST | FULL | — |
| HYP-40 | Admin can create, edit, version and deactivate Logical_Rules and run a dry-run without code changes | §7 #8 by analogy; §10 #9 `is_active` | SHOULD | FULL | Strong jury demo |
| HYP-41 | Structured JSON logs (timestamp, level, service, message, request_id, user_id) and Prometheus metrics | §13 | SHOULD | FULL | — |
| HYP-42 | Negative scenarios: one failed detector does not fail the run; timeouts retried ≤ 2; partial results flagged | §7 #12; §9.1 errors | MUST | FULL | — |
| HYP-43 | Hypothesis statistics feed the weekly ML report (acceptance and dismissal per rule, reasons, recommendations) | §7 #10 | SHOULD | FULL | Stats endpoint |
| HYP-44 | Any ML model used (embeddings, anomaly models, future ranker) is registered in `Model_Versions`; no auto-publication; object-level split for any training | §9.4; §14.2 | SHOULD | SIMPLIFIED | Unsupervised models with fixed parameters are registered; no training loop in MVP |
| HYP-45 | Data stays local by default (152-ФЗ); no document content leaves the perimeter without explicit configuration | §12 #6 | MUST | FULL | LLM `Noop` default |
| HYP-46 | UI and protocol show clearly that SUSPICION ≠ нарушение (banner, separate tab and section) | §9.5; §9.3 p.1 | MUST | FULL | — |
| HYP-47 | Descriptions, reasons and UI in Russian | product | MUST | FULL | Template-based generation |
| HYP-48 | Graphic drawing diff for comparable ПД/РД sheets with room-level bbox evidence (extension of §9.1 p.3 CV) | §9.1 p.3 (supports); user brief | SHOULD | SIMPLIFIED | Vector plan sheets in the MVP; scans best-effort with lower confidence |
| HYP-49 | FP control: 0 HIGH-priority suspicions on the NEGATIVE_VERIFIED pilot pair; thresholds calibrated on negatives | §14.3 (by analogy) | SHOULD | FULL | Regression gate in CI |
| HYP-50 | Optional LLM behind a pluggable interface (local / cloud / none), offline default | user brief | NICE | SIMPLIFIED | Interface + `Noop` + Ollama adapter; cloud adapter is a stub until D4 is decided |
| HYP-51 | Cross-module dedup: a change already covered by a matrix finding is linked, not reported twice | §9.5 dedup spirit; §9.2 | SHOULD | FULL | Change-fact router (D2) |
| HYP-52 | Explainability: the card shows the rule condition, the facts with values, and each fact's source (page + bbox) | §9.3 p.1 | SHOULD | FULL | — |
| HYP-53 | Dismissal requires a coded reason and a comment (mirrors `reason_code` for NEGATIVE_VERIFIED) | §9.3 p.2 by analogy | SHOULD | FULL | Reason codes in §3.7 |
| HYP-54 | Finalization policy for pending suspicions: non-blocking with a warning; frozen as «не рассмотрено» | §9.3 p.4 (interpretation) | SHOULD | FULL | D6 |
| HYP-55 | Section (5) is included in protocol exports PDF/DOCX/XML/JSON | §7 #7; §9.2 p.4 | SHOULD | FULL | Via the Module 7 exporter |
| HYP-56 | Cross-object historical anomaly model (the «исторические данные» of approach 4) | §9.5 #4 | SHOULD | MOCKED | No history is provided. We ship a feature store + reference priors + a synthetic history for the demo; real training starts once finalized objects accumulate |

Totals: 56 requirements. FULL 50, SIMPLIFIED 5 (HYP-06, 08, 44, 48, 50), MOCKED 1 (HYP-56), OUT_OF_SCOPE 0.

---

## 3. Proposed design

### 3.1 Placement in the pipeline

```
Module 1 (parse, registry, revision chain)
   └─ event process.parsed ──────────────┬──────────────────────────────┐
                                         ▼                              ▼
                              Module 2 (Matrix comparison)   Module 5 hypothesis-worker (Python)
                                         │   ▲                          │
                                         │   └── change facts (router) ─┤  shared change-detection engine
                                         ▼                              ▼
                               comparison.completed           hypotheses.run.completed
                                         └──────────┬───────────────────┘
                                                    ▼
                                  Protocol builder (Module 2): sections (1)–(5), version N, READY
```

- The hypothesis run starts on `process.parsed`, i.e. once актуальные revisions are resolved. It runs in parallel with the Matrix comparison.
- The protocol builder waits for both completion events, up to a budget (default 120 s after `process.parsed`). Detectors still running at the deadline are reported in the section (5) header with status `NOT_RUN_TIMEOUT`. The inspector can click «Досчитать гипотезы», which creates a new protocol version. This keeps §11 #4/#5.

Per-scenario applicability (HYP-33):

| Detector | FULL | PD_RD_ONLY | PD_ID_ONLY | RD_ID_ONLY | SINGLE_ONLY | PARTIALLY_LOADED |
|---|---|---|---|---|---|---|
| LOGICAL (object/stage rules) | ✓ | ✓ | ✓ | ✓ | ✓ (single-stage rules only) | ✓. `exists`-type rules return UNKNOWN when the scope discipline is incomplete |
| LOGICAL (ИД ↔ РД rules, e.g. L09, L11, L12) | ✓ | — | ✓ (vs ПД) | ✓ | — | ✓ where both present |
| SEMANTIC (ПД↔РД) | ✓ | ✓ | — | — | — | ✓ on paired sheets only |
| SEMANTIC (РД/ПД↔ИД as-built plans) | ✓ | — | ✓ | ✓ | — | ✓ |
| NORMATIVE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ML_PATTERN (intra-stage units) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ML_PATTERN (cross-stage deltas) | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| GRAPHIC_DIFF | ✓ | ✓ | ✓ (РД-as-built sheets in ИД) | ✓ | — | ✓ on paired sheets |

### 3.2 Components (Python 3.11 service `hypothesis-worker`)

| Component | Responsibility |
|---|---|
| `runner` | Consumes `hypotheses.run.requested`, builds the run context (актуальные file set, versions), schedules detectors with per-detector time budgets, handles partial failure (HYP-42), publishes completion |
| `docmodel` adapter | Reads Module 1 parse output: words with bboxes, tables, sheet metadata (document_code, sheet no., title, stage, discipline, floor/level), page geometry (CropBox/Rotate). Falls back to direct PyMuPDF extraction for explication tables if Module 1 has not produced them |
| `inventory` | Builds a `SheetInventory` per plan sheet: rooms (number, name, area, category, label position, region polygon), element labels per room (system tags `В2.4`, `П2`, equipment names, legend-symbol hits), door arcs. Also `SectionInventory` (layer lists of roofs/floors in sections) and `SpecInventory` (spec lines) |
| `pairing` | Pairs comparable sheets ПД↔РД (and РД↔ИД as-built) by discipline family, floor/level, section and axis/room-label overlap; Hungarian assignment |
| `registration` | Similarity transform from matched labels (RANSAC), with quality gates; ORB/ECC fallback for scans |
| `align` | Room alignment across stages: number-first, then position after registration, then name/area similarity (Hungarian). Detects renumbering |
| `taxonomy` | Room-function / element-class ontology, abbreviation expansion, pymorphy3 lemmatisation, rapidfuzz, embedding fallback, antonym lexicon, category-shift severity matrix |
| `rules` | Logical rule engine (JSON AST, Kleene 3-valued logic), fact sheet builder |
| `normative` | Normative_Base evaluator with edition selection by date |
| `anomaly` | Robust z (median/MAD), identical-unit consistency, IsolationForest, reference priors, history feature store |
| `graphic` | Tolerant raster diff (and vector segment diff for vector PDFs) inside the plan viewport; per-room aggregation; overlay PNG generation |
| `scoring` | Confidence fusion, severity → `review_priority` |
| `dedup` / `router` | Fingerprinting, merging, cross-link with matrix findings, routing of change facts (D2) |
| `persist` | Upserts `Suspicions`, `Evidence_Fragments` (with `suspicion_id`), `Hypothesis_Runs`; idempotent by `run_id` + `suspicion_key` |
| `llm` (optional) | `HypothesisLLM` interface: `NoopLLM` (default), `OllamaLLM`, `CloudLLM` stub |
| `api_internal` (FastAPI) | `/health`, `/metrics`, `/internal/hypotheses/dry-run` (rule test from the admin UI) |

Libraries (pin exact versions at implementation time; the minimums below are known-good lines):

| Library | Min version | Why |
|---|---|---|
| PyMuPDF (`import pymupdf`) | 1.24 | Text layer words/bboxes, `get_drawings()` vectors, rendering with `annots=False`; already used in the venv. Note: AGPL — acceptable for a hackathon; flag for production licensing |
| numpy | 2.0 | — |
| opencv-python-headless | 4.10 | `estimateAffinePartial2D` RANSAC, warp, morphology, ORB/ECC fallback (tested: 5.0.0 works) |
| shapely | 2.0 | Room polygons, IoU for dedup/evidence |
| scipy | 1.13 | `linear_sum_assignment` (Hungarian) |
| scikit-learn | 1.5 | IsolationForest, isotonic calibration (later) |
| pymorphy3 + pymorphy3-dicts-ru | 2.0 | Russian morphology (lemmas, POS, negation) |
| rapidfuzz | 3.9 | Fuzzy/typo-tolerant matching (real case: «Комтана отдыха» in the ALT79B РД) |
| onnxruntime (+ `tokenizers`) | 1.18 | CPU inference of the embedding model in Docker (no GPU on Apple Silicon Docker); `sentence-transformers` ≥ 3.0 only for export/dev |
| Embedding model | — | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, Apache-2.0, multilingual MiniLM = the closest «совместимый аналог» of all-MiniLM-L6-v2), ONNX int8 baked into the image. Lightweight fallback: `cointegrated/rubert-tiny2` (312-d, MIT) |
| pydantic | 2.7 | Message and rule schemas |
| aio-pika | 9.4 | RabbitMQ |
| redis (redis-py) | 5.0 | Cache |
| SQLAlchemy 2 + psycopg 3 | 2.0 / 3.1 | DB writes to our result tables (see interface decision I-3) |
| structlog, prometheus-client | 24 / 0.20 | §13 |

### 3.3 Detector designs

#### 3.3.1 Approach 1 — LOGICAL_ANALYSIS (Logical_Rules)

**Fact sheet.** For each (object, stage) the engine builds a fact sheet from:
- (a) Module 1/2 matrix extractions — e.g. M-007 floors, M-008 height, M-022 fire-resistance degree, each fact with provenance;
- (b) our inventories — rooms by category, element-presence index, explication totals, ИД tolerance tables, act dates and referenced document codes;
- (c) the Files registry — document_code, revision, approval_status, approval_date, signature_status.

Every fact carries `value`, `unit`, `stage`, `sources[] {file_id, sha256, document_code, revision, approval_status, page, sheet_no, bbox_norm}` and `extraction_confidence`.

**Rule format.** Both `condition` and `expected` are stored as JSON text in the ТЗ-mandated columns. Example (the ТЗ example, verbatim semantics):

```json
{
  "rule_code": "HR-LOG-001", "version": 1,
  "rule_name": "Лифт при этажности более 10",
  "applicability": {"stages": ["PD","RD"], "object_classes": ["Ф1.3","Ф1.2","Ф3.*","Ф4.*"]},
  "condition": {"all": [{"fact": "object.floors_above_ground", "op": ">", "value": 10, "agg": "max", "stage": ["PD","RD"]}]},
  "expected":  {"exists": {"element": "LIFT", "stage": "RD",
                "scope": {"disciplines": ["АР","КЖ","КР"], "sources": ["explication","plan_labels","spec"]}}},
  "normative_base": "СП 54.13330.2022, п. 7.1.3 (ссылка из примера ТЗ; требует проверки нормоконтролёром)",
  "severity": "HIGH", "base_confidence": 0.85, "promotable": false,
  "message_template": "В РД отсутствует лифтовая шахта при {object.floors_above_ground} этажах.",
  "overlaps_matrix_codes": []
}
```

**Grammar.** `all | any | not`; comparisons `> >= < <= == != in between`; `exists`, `count`, `sum`, `min`, `max` over collections with filters (e.g. `rooms[category=="LIFT_HALL"]`); arithmetic `abs, diff, ratio, pct_delta`; tolerances `{"tol_abs": 0.05, "tol_rel": 0.0005}`; stage selectors. The evaluator is a small safe interpreter (≈ 300 LOC). It uses no `eval` and no general-purpose expression library, so admin-entered rules cannot execute code. Rules are validated against a JSON Schema on save.

**Three-valued semantics.**
- A missing fact gives `UNKNOWN`.
- `UNKNOWN` in `condition` means the rule is not applicable. There is no suspicion; the run stats log «недостаточно данных: object.floors_above_ground».
- `exists` returns `FALSE` only if every scope discipline is present and complete for that stage (Module 1 completeness statuses such as `RD_UPLOADED`). Otherwise it returns `UNKNOWN`. This avoids restating `MISSING_EVIDENCE`, which belongs to Module 2 (HYP-28, HYP-33).
- A suspicion is emitted iff `condition = TRUE` and `expected = FALSE`.

**Evidence of absence.** For «must exist» rules, the ACTUAL fragment is the bbox of the searched region: the explication table plus the plan viewport of the relevant floor sheet. `extracted_value` is «не найдено». The EXPECTED fragment is the fact that triggered the rule (e.g. floors in the ТЭП table). The ТЗ example shows exactly this pattern: an rd_reference to the sheet where the lift should be.

**Seed rules.** «проверить» means the reference must be verified by a нормоконтролёр before `verified=true`; it is shown with a badge in the UI. The references reflect my current knowledge; they are **not** asserted as exact clause numbers.

| Code | Rule (A → B) | Facts | Evidence source | Normative basis (to verify) | Severity | Pilot / demo |
|---|---|---|---|---|---|---|
| HR-LOG-001 | floors_above_ground > 10 → a lift exists in РД | M-007 value; element index | ТЭП; РД plans/explication | ТЗ example: СП 54.13330.2022 п. 7.1.3 (проверить; to our knowledge lift requirements are in section 4 of СП 54) | HIGH | Synthetic demo (reproduces the ТЗ JSON) |
| HR-LOG-002 | upper residential floor level − first floor level ≥ 12 m → lift | elevation marks from sections | Sections | СП 54.13330 (lift requirement by 12 m height; проверить пункт) | HIGH | Synthetic |
| HR-LOG-003 | fire-technical height > 28 m → «лифт для транспортирования пожарных подразделений» | M-008; element index | Plans, spec | СП 4.13130.2013 п. 7.14 (проверить) | HIGH | Synthetic |
| HR-LOG-004 | underground parking present → АУПТ/sprinkler and ДУ systems present (ВК/ОВ) | room categories PARKING; element index | Plans, spec | СП 506.1311500.2021 / СП 486.1311500.2020 / СП 7.13130.2013 (проверить) | HIGH | Synthetic |
| HR-LOG-005 | Σ areas of explication rows = explication total (|Δ| ≤ max(0.05 m², 0.05 %)) | explication rows + total | The table itself | Internal consistency of the document (ГОСТ Р 21.101-2020, general requirement of document consistency) | MEDIUM | **Fires on ALT79B ПД: Σ 2795.04 vs «Общий итог» 2797.27 m²** |
| HR-LOG-006 | Σ apartment areas in «Спецификация квартир» = its «Итого»; apartment count = ТЭП count | spec rows, totals, M-010 | Tables | Internal consistency | MEDIUM | POL16 / LOS3A tables |
| HR-LOG-007 | ИД contains a scheme or act for works of class {ремонт, усиление, исправление дефекта, замена конструкции} → an РД document or `approved_change_ref` for those works exists | ИД doc titles (registry/OCR); РД index | ИД title block; РД ведомость | ГрК РФ ст. 52 (обязанность соблюдать ПД — cited in ТЗ §2); Приказ Минстроя № 344/пр | HIGH | **IZM12-V01** |
| HR-LOG-008 | ИД executive scheme: |measured deviation| ≤ tolerance declared on the same scheme | ИД scheme values/tolerances | ИД sheet | Tolerances stated on the scheme; СП 70.13330.2012 (проверить) | HIGH | **OKT103-V01** (routed to Module 2 if mapped to M-054/M-058/M-059/M-060, else here) |
| HR-LOG-009 | Every АОСР/act date ≥ approval_date («В производство работ») of the РД revision it references | ИД act dates; registry | ИД act; РД stamp | Приказ Минстроя № 344/пр (проверить пункт) | HIGH | Synthetic |
| HR-LOG-010 | An ИД act references an РД document_code/revision that is `SUPERSEDED`/`CANCELLED` → «работы по устаревшей редакции» | ИД act text; registry chain | ИД act; registry | ТЗ §9.1 (устаревшая редакция не эталон) | HIGH | Synthetic |
| HR-LOG-011 | A cross-reference in sheet notes («см. лист N», «см. раздел X») points to a sheet or set that is absent from the РД ведомость/registry | notes text; ВР ведомость | Notes; ведомость | ГОСТ Р 21.101-2020 (состав и ведомости) | LOW | Pilot notes (e.g. «Смотреть совместно с листом 24» on ALT79B РД) |
| HR-LOG-012 | ТЭП plausibility: building_height / floors_above_ground ∈ [2.7; 4.5] m (residential) | M-007, M-008 | ТЭП | Internal plausibility (no norm) | LOW | Synthetic |

HR-LOG-006, 008 and 011 are also useful checks in `SINGLE_ONLY` scenarios.

#### 3.3.2 Approach 2 — SEMANTIC_DISSONANCE

**Pipeline.**

1. **Inventories.** Rooms are extracted from explication tables (number, name, area, «Кат. пом.» when present, e.g. В4/В3 on SOSH25/DOO25) and from room labels on plans (the number token at the label position). Joining the two gives name + area + position.
2. **Sheet pairing** (§3.3.5 shared step).
3. **Room alignment.**
   - Primary: equal normalised number on the same floor/section.
   - Secondary, after registration: map ПД label positions into the РД frame and solve a Hungarian assignment. Cost = w₁·distance/diag + w₂·(1 − name_sim) + w₃·|Δarea|/area.
   - This detects renumbering: ALT79B ПД room **23 «Помещение» 19.41 m²** sits at the position of РД room **22 «Комтана отдыха» [sic] 19.62 m²**.
4. **Name normalisation.**
   - lowercase; ё→е; punctuation;
   - abbreviation dictionary («сан.узел», «с/у» → «санузел»; «тех.» → «технический»; «ПУИ» → «помещение уборочного инвентаря»; «МГН»; «ИТП»; «ВРУ»; «ГРЩ»; «ЛК» …);
   - pymorphy3 lemmatisation;
   - rapidfuzz typo repair against the taxonomy lexicon (Damerau-type ratio ≥ 85, e.g. «комтана» → «комната»).
5. **Taxonomy mapping.**
   - Dictionary synonyms first, then the nearest category prototype by embedding cosine (≥ 0.55 → category; else `UNKNOWN`).
   - Categories (≈ 30): `UNASSIGNED` («помещение»), `LIVING`, `KITCHEN`, `SANITARY`, `SANITARY_MGN`, `CORRIDOR_EVAC`, `STAIR`, `LIFT_HALL`, `LIFT_SHAFT`, `TAMBOUR`, `TECHNICAL` (техническое, тех. помещение), `ELECTRICAL` (электрощитовая, ВРУ), `HEAT_POINT` (ИТП), `PUMP`, `VENT_CHAMBER`, `STORAGE_GENERAL` (кладовая), `STORAGE_HAZARDOUS` (склад ГСМ, ЛВЖ, баллонов), `FOOD_PREP` (цеха пищеблока), `FOOD_STORAGE`, `STAFF` (комната персонала, отдыха), `OFFICE`, `RETAIL`, `PUBLIC_HALL`, `EDU_CLASS`, `EDU_GROUP` (групповая), `SLEEP` (спальня ДОО), `MEDICAL`, `PARKING`, `WASTE`, `OUTDOOR` (лоджия, балкон).
   - Each category has attributes: typical fire-hazard category (А/Б/В1–В4/Г/Д), «мокрое помещение», «путь эвакуации», «МГН», «полезная/техническая площадь».
6. **Dissonance classification** for aligned pairs. Embeddings are used only to map names to categories, **not** as the dissonance score. Embeddings rate «Техническое» and «Склад ГСМ» as fairly similar, which would hide exactly the ТЗ example.
   - same lemma/synonym → no change;
   - same category, different wording → `LOW`, usually not emitted (configurable);
   - category shift → severity from a **shift matrix**:
     - `TECHNICAL→STORAGE_HAZARDOUS` = HIGH (the ТЗ example; fire category changes; normative_base «СП 12.13130.2009 (категории помещений по взрывопожарной и пожарной опасности); СП 4.13130.2013 (противопожарные преграды)»);
     - `SANITARY_MGN→SANITARY` = HIGH (accessibility lost);
     - `LIVING→TECHNICAL` = HIGH;
     - `UNASSIGNED→STAFF` = MEDIUM (ALT79B);
     - `FOOD_*` reconfigurations in ДОО/СОШ = HIGH (sanitary approval);
   - antonym / negation flip in aligned text slots (notes, spec lines, legend items), from a curated lexicon: негорючий↔горючий, отапливаемое↔неотапливаемое, приточная↔вытяжная, с подогревом↔без подогрева, наружный↔внутренний, подземный↔надземный. Negation is detected via pymorphy3 (частица «не», предлог «без»). Optional RuWordNet antonymy, subject to licence check.
7. **Set-level changes.**
   - room added in РД → `HR-SEM-002` (SOSH25: **1.109 «Зона ожидания начальной школы со стойкой для зарядки мобильных устройств», 18.2 m²**; floor total 6234.1 → 6252.3);
   - room removed → `HR-SEM-003`;
   - room split or merged: 1↔N alignment with area conservation.
8. **Element inventory diff per room** (`HR-SEM-005/006`). Text labels inside the room region are mapped to element classes by regex/dictionary:
   - `^[ПВК]\d+(\.\d+)*$` → vent/ventilation system branch;
   - «тепл(ый|ого) пол|Multibox» → `WARM_FLOOR`;
   - «PRADO|радиатор|конвектор» → `RADIATOR`;
   - «ОЗК|КПУ» → `FIRE_DAMPER`;
   - layer names in section callouts (e.g. «бронированный стальной лист») → `LAYER:*`.
   - An element class present in ПД but missing in РД is a suspicion. A changed designation set (В2.10 → В2.2–В2.4) is a configuration-change suspicion.
   - This covers all three ventilation findings (warm floor missing in 267/270/271/272; local exhausts В2.4–В2.9 missing in 140/142; branch sets changed in 147/198/314) **even though the ПД sheet is a schematic and the РД sheet is a plan**. Room numbers anchor both, so no raster registration is needed.

Semantic rule codes:

| Code | Emits | Example |
|---|---|---|
| HR-SEM-001 | Room function / category changed at the same position | ALT79B 23 «Помещение» → 22 «Комната отдыха»; ТЗ «Техническое» → «Склад ГСМ» |
| HR-SEM-002 | Room added in РД | SOSH25 1.109 |
| HR-SEM-003 | Room removed in РД | — |
| HR-SEM-004 | Room split or merged | DOO25 пищеблок 135–150 (if the split/merge shows) |
| HR-SEM-005 | Element class present in ПД room, absent in РД room | warm floor (vent markup #2); local exhausts (#3); UNDMS armored sheet layer (routed to M-044, see D2) |
| HR-SEM-006 | Element designation set/configuration changed in a room | В2.10 → В2.2–В2.4 (room 147); vent chamber 012 |
| HR-SEM-007 | Antonym/negation flip in aligned text slot | notes, legends |
| HR-SEM-008 | Material/product substitution in an aligned spec line, if not covered by a matrix parameter | spec tables |

#### 3.3.3 Approach 3 — NORMATIVE_ANALYSIS (Normative_Base)

**Contract with Module 8.** Module 8 owns CRUD of `Normative_Base`. We need these extra columns: `unit`, `fact_key` (binding to our extractor, e.g. `room.area_m2`, `room.clear_height_m`), `applicability` JSON (e.g. `{"room_category":["LIVING"],"object_class":["Ф1.3"],"apartment_rooms":[1]}`), `comparison` (`min_inclusive` by default), `severity`, `is_active`, `verified`, `version`.

**Edition selection (D7).**
- Evaluation date = the `approval_date` of the source revision being checked (ПД approval / expertise, or the РД «В производство работ» date), falling back to the process date.
- The edition applies iff `effective_from ≤ date ≤ coalesce(effective_to, +∞)`.
- If editions overlap or the date is unknown, evaluate all candidate editions. When they disagree, emit with confidence × 0.7 and the note «редакция нормы не определена однозначно».
- The applied edition is shown in `normative_base` («СП 54.13330.2022, п. …»).

**Seed rows.** These are for the hypothesis-relevant subset; they must not duplicate matrix-covered parameters such as corridor/door widths (M-040/M-041/M-104/M-116/M-117) or МГН sanitary cabins (M-119). All are flagged `verified=false` until expert review:

| Code | parameter_name | min / max | Applicability | Document (to verify) | Status in MVP |
|---|---|---|---|---|---|
| HR-NRM-001 | Высота (от пола до потолка) жилых комнат и кухни | min 2.5 m (2.7 m in climate zones IА/IБ/IГ/IД/IVА; Moscow = IIВ) | LIVING, KITCHEN; Ф1.3 | СП 54.13330.2022 (пункт проверить; ред. 2016 — п. 5.8). The ТЗ example attributes the 2.5 m to «СанПиН» | Best-effort: heights from sections/notes, else not evaluated (UNKNOWN) |
| HR-NRM-002 | Площадь общей жилой комнаты | min 14 m² (1-комн.), 16 m² (2+ комн.) | LIVING (общая) | СП 54.13330 (ред. 2016 — п. 5.7; проверить для ред. 2022) | FULL from explications |
| HR-NRM-003 | Площадь спальни | min 8 m² (10 m² на двоих) | LIVING (спальня) | СП 54.13330 (проверить) | FULL |
| HR-NRM-004 | Площадь кухни | min 8 m² (в 1-комн. — 5 m²) | KITCHEN | СП 54.13330 (проверить) | FULL |
| HR-NRM-005 | Площадь групповой ДОО на 1 ребёнка | min 2.5 m² (до 3 лет) / 2.0 m² (от 3 лет) | EDU_GROUP | СанПиН 2.4.3648-20 (проверить) | NICE: needs group capacity; else UNKNOWN |
| HR-NRM-006 | Площадь учебного кабинета на 1 обучающегося | min 2.5 m² (фронтальные занятия) | EDU_CLASS | СанПиН 2.4.3648-20 (проверить) | NICE: needs class size |

**Emission.** A suspicion is emitted when the fact violates the bound and the fact exists in the актуальные sources. EXPECTED fragment = the norm row (textual, no bbox) plus, when the norm itself is quoted in the ПД, that ПД fragment. ACTUAL fragment = the explication row bbox. For conversion to CANDIDATE, a normative-only suspicion needs at least the ACTUAL fragment with coordinates plus the norm reference; the gate treats `normative_base_id` as the «expected source» (see §6, item 8).

**Demo value.** The admin edits `min_value` in the Module 8 UI (e.g. HR-NRM-004 8 → 9 m²), re-runs hypotheses, and a new suspicion appears without any redeploy (HYP-07, HYP-40).

#### 3.3.4 Approach 4 — ML_PATTERN_ANALYSIS

**Available now (no history):**

| Code | Method | Data | Pilot evidence |
|---|---|---|---|
| HR-ML-001 | **Cross-stage delta outliers**: rel_delta_i = (A_RD − A_PD)/A_PD per aligned room; modified z = 0.6745·(x − median)/MAD; flag \|z\| > 3.5 (HIGH) / > 2.5 (MEDIUM). The median captures systematic re-measurement (e.g. areas remeasured to finish surfaces) so that it is **not** reported | aligned room pairs on a floor (n ≥ 8) | ALT79B: median shift **+1.17 %** across all rooms (systematic). Outliers: «Тех.помещение» 18 **+6.8 % (z = 4.0)**, «Электрощитовая» 17 +5.5 % (z = 3.0), ПУИ +5.1 % (z = 2.8). This matches the expert note «изменены площади техпомещений 18–21» (partially — 19–21 are within +1.7…+4.0 %) |
| HR-ML-002 | **Identical-unit consistency**: units of the same type (same apartment type code / same room set / same registered geometry) must have equal areas within a stage, and equal deltas across stages | apartment specs, typical floors, repeated room groups (ДОО 101–105 / 106–110 …) | POL16-V01 «В одинаковых квартирах изменены значения жилой/общей площади» |
| HR-ML-003 | **Quantity-ratio anomalies** (the ТЗ example): concrete m³ per m² of floor area per storey, rebar kg per m³ concrete per element type, against (a) the object's other storeys/elements (robust z) and (b) reference prior ranges (configurable «Reference_Stats», labelled «экспертная оценка, не норматив») | КЖ/КР specs, ВРС ведомости, ИД concrete journals | Synthetic demo (no КЖ specs in pilot); M-067 (> 2 % inter-stage) stays in Module 2 |
| HR-ML-004 | **Multivariate outliers**: IsolationForest (n_estimators=200, contamination='auto', fixed random_state; model version registered) over room features [log area, rel_delta, category one-hot, has_renumber, name_changed], only when n ≥ 50 rooms; used only as a *supporting* signal (raises confidence of other detectors; standalone emission only at LOW priority) | large floors (SOSH25 has 100+ rooms) | — |

**How it improves with data (HYP-56):**
1. A **feature store** `Quantity_History` holds object-level quantities (areas by category, ratios, counts). It is written **only from FINALIZED protocols**, and each value is tagged with building class, stage and region.
2. When there are ≥ 30 objects per class, per-class quantile references replace the literature priors. The approach then becomes the ТЗ's literal «на 20% ниже среднего», computed against historical objects.
3. When there are ≥ 200 objects, cross-object kNN / IsolationForest runs on the object vectors.
4. Once enough GOLD accumulates **from converted-and-decided findings** (legitimate `CONFIRMED_VIOLATION` / `NEGATIVE_VERIFIED` with `rule_version`), a supervised ranker re-weights hypothesis confidence.
5. All of it runs under the Module 4 gate: object-level split, no auto-publication, ≤ 2 pp regressions, signed approval, rollback. Dismissed SUSPICIONs are **never** used as labels (HYP-18). They appear only in weekly-report statistics.
6. Cold-start demo: a synthetic history of ~40 objects generated from the reference priors, clearly labelled «синтетические данные для демонстрации».

#### 3.3.5 GRAPHIC_DIFF (extension; D3)

**Scope.** Comparable plan-type sheets (floor plans / marking plans of АР, КЖ, ОВ, ВК) in vector PDF. Schematic-vs-plan pairs are handled by §3.3.2 element inventories, not by pixels. Scans are best-effort.

**Steps.**

1. **Sheet pairing.**
   - Candidate pairs share a discipline family (АР↔АР; ИОС4↔ОВ …).
   - Floor/level is parsed from the sheet title, e.g. «План 1-го этажа» ↔ «Маркировочный план первого этажа», «План на отм. 0.000», «Секция 1».
   - Pair score = w·title_sim + w·Jaccard(axis labels) + w·Jaccard(room numbers); Hungarian assignment; threshold 0.5.
   - An unpaired sheet produces no graphic suspicion. It is not an error either.
2. **Registration.**
   - Anchor tokens = unique labels present on both sheets: axis letters/numbers, room numbers, e.g. `^\d{1,3}(\.\d{1,3}){0,2}$|^[А-Я]\*?$`.
   - Fit `cv2.estimateAffinePartial2D` (RANSAC, reprojection threshold ≈ 8 pt) to get scale + rotation + translation.
   - **Quality gates:** ≥ 6 inliers; the inlier bounding box must span ≥ 30 % of the plan extent in **both** axes; median residual ≤ 0.3 % of the page diagonal; scale within the set of standard drawing-scale ratios {0.5, 1, 2, 2.5, 4, 5} ± 2 %.
   - When the gates fail, try the fallbacks in order: axis-grid detection (long dash-dot lines + axis labels) → ORB + RANSAC on renders → give up (no graphic hypothesis; logged).
3. **Plan viewport.** The convex hull of the inlier anchors, expanded to the axis grid. Explication tables, legends, notes, title block and schedules are excluded; the text detectors handle those.
4. **Diff.** Render with `annots=False` at 0.5–1.0 zoom. Mask baked-in coloured expert markup (pilot pages contain red/blue boxes as content — only relevant for the pilot). Warp ПД into the РД frame. Tolerant morphological diff (dilate 3 px):
   - `removed` = ПД ink absent in РД;
   - `added` = РД ink absent in ПД.
   - For vector PDFs the same step also runs as a segment-level diff on `get_drawings()` primitives (endpoint tolerance, angle < 2°), with layer weights by style: thick walls/hatches > doors (arcs) > dimensions/text.
5. **Room aggregation.** The room region is a flood-fill from the room-label point on a closed wall mask (morphological closing with a door-gap-size kernel), falling back to a Voronoi cell of room labels clipped to the viewport. Per room: `removed_ratio`, `added_ratio`, wall/door change counts.
6. **Directional scoring.** РД legitimately adds detail (marking tags, dimensions), so `added` is weighted low (0.3) and `removed` high (1.0). Threshold = max over negative-pair room scores × 1.5 (calibrated on POL17).
7. **Door detection** (vector): quarter-circle arcs of radius ≈ 600–1200 mm at the drawing scale. Door-set diff per room gives `HR-GRA-002` «дверь перенесена/удалена» (LOS3A-V01).
8. **Output.** Suspicion per room with EXPECTED bbox (ПД room region) and ACTUAL bbox (РД room region), both normalised to [0;1] via the Module 1 normaliser (CropBox/Rotate). An overlay PNG shows ПД (red) / РД (green) for the card.

Graphic rule codes:
- `HR-GRA-001` — room geometry changed;
- `HR-GRA-002` — door moved or removed;
- `HR-GRA-003` — symbol/hatch pattern missing in a room (e.g. warm-floor contour hatch), when the text inventory is silent.

### 3.4 Confidence, priority, dedup, routing

**Confidence.**
- Per detector: `c = base_rule_conf × q_extraction × q_alignment × q_edition`, where:
  - q_extraction = 1.0 for the text layer, else the OCR confidence from Module 1;
  - q_alignment = exp(−residual/τ) × matching margin;
  - q_edition = 1 or 0.7.
- When several detectors support the same subject: noisy-OR `1 − Π(1 − c_i)`, capped at 0.95. The supporting detectors are listed in `supporting_methods`.
- Later, isotonic calibration uses only legitimate GOLD from converted findings.

**review_priority.**

| Rule severity | confidence ≥ 0.6 | confidence < 0.6 |
|---|---|---|
| HIGH | HIGH | MEDIUM |
| MEDIUM | MEDIUM | LOW |
| LOW | LOW | LOW |

Severity is HIGH by default for fire safety, МГН, structural and sanitary categories.

**Dedup (HYP-16).**
- `revision_fingerprint = sha256(sorted(file_id:revision of the актуальные sources used))`.
- `suspicion_key = sha256(object_id | revision_fingerprint | rule_family | subject_key)`, where `subject_key` = e.g. `floor:1|room:23→22` or `object|LIFT`.
- Same key → merge: keep the max confidence, union the evidence, union `supporting_methods`.
- Spatial merge: same object + same page pair + same subject + evidence IoU ≥ 0.5 → merge.
- Never merged across objects. Never merged across non-comparable revisions: suspicions on superseded inputs become `STALE` and are regenerated.

**Router / cross-module dedup (HYP-51, D2).** Every atomic change fact (`ROOM_RENAMED`, `ROOM_CATEGORY_SHIFT`, `ROOM_ADDED`, `ROOM_REMOVED`, `ROOM_AREA_OUTLIER`, `ELEMENT_MISSING`, `ELEMENT_CONFIG_CHANGED`, `DOOR_MOVED`, `LAYER_REMOVED`, `ID_TOLERANCE_EXCEEDED`, `ID_WORKS_WITHOUT_RD` …) is looked up in `Change_Matrix_Map`, an admin-editable table of (change_type, subject category, discipline) → matrix code:
- **Mapped** (e.g. `LAYER_REMOVED` in a roof section → M-044; `DUCT_SECTION_REDUCED` → M-078; `DOOR_OPENING_REVERSED` on an evacuation path → M-043/M-106; `ID_TOLERANCE_EXCEEDED` for axes → M-054): the fact goes to Module 2 as extraction input for that parameter. Module 5 emits nothing. If Module 2 already produced a finding on the same fragment (IoU ≥ 0.3), any residual suspicion is linked through `related_check_ids` and hidden by default.
- **Unmapped**: the fact becomes a SUSPICION.

Pilot routing (expected owner):

| Pilot group | Change facts | Owner |
|---|---|---|
| ALT79B-V01 | ROOM_CATEGORY_SHIFT (23→22), ROOM_AREA_OUTLIER (tech rooms) | Module 5 (M-002 does not trigger: +0.49 %) |
| UNDMS-V01 | LAYER_REMOVED «бронированный стальной лист 6 мм» (section 1-1) | Module 2 via M-044 (Module 5 detector supplies the fact) |
| IZM12-V01 | ID_WORKS_WITHOUT_RD (ремонт свай) | Module 5 HR-LOG-007 |
| LOS3A-V01 | DOOR_MOVED in СУ кв. 2.4.1 (+ text «изменение записано в ведомости») | Module 5 HR-GRA-002 (+ HR-SEM text) |
| OKT103-V01 | ID_TOLERANCE_EXCEEDED (+980 mm vs 15/±12/20 mm) | Module 2 if mapped to M-054/M-058–M-060; otherwise Module 5 HR-LOG-008 |
| POL16-V01 | Identical apartments, different areas | Module 5 HR-ML-002 |
| DOO25-V01 | Room config/areas 135–150 changed (total −0.29 %) | Module 5 HR-SEM-004 / HR-ML-001 / HR-GRA-001 |
| SOSH25-V01 | ROOM_ADDED 1.109 (+0.29 %) | Module 5 HR-SEM-002 |
| POL17-N01 | none | Must produce no HIGH suspicion |
| Vent #1–#3 (АНО/150321) | ELEMENT_CONFIG_CHANGED (012), ELEMENT_MISSING warm floor (267/270/271/272), ELEMENT_MISSING / ELEMENT_CONFIG_CHANGED exhausts (140/142/147/198/314) | Module 5 HR-SEM-005/006 (atomic per room) |

### 3.5 Interfaces: REST and RabbitMQ

**REST (Node.js API; OpenAPI 3.0; ajv validation).** Paths are aligned with the ТЗ style `/api/v1/...`. Final names are to be agreed with the API owner.

| Method | Path | Role | Request | Response |
|---|---|---|---|---|
| GET | `/api/v1/processes/{process_id}/suspicions` | inspector+ | query: `method, priority, inspector_status, evidence_status, include_stale=false, page, page_size` | `{items:[Suspicion], total, counts_by_method, run:{run_id,status,detector_status}}` |
| GET | `/api/v1/suspicions/{suspicion_id}` | inspector+ | — | `Suspicion` + `evidence_fragments[]` + `explanation` + `related_check_ids` + `overlay_urls` |
| POST | `/api/v1/processes/{process_id}/hypotheses/runs` | inspector (own object), admin | `{mode:"FULL"\|"INCREMENTAL", reason}` | `202 {run_id}` (idempotency key header) |
| GET | `/api/v1/hypotheses/runs/{run_id}` | inspector+ | — | `{status, started_at, finished_at, detector_status, versions}` |
| POST | `/api/v1/suspicions/{id}/evidence` | inspector | `{fragment_id}` (pick a suggestion) or `{file_id, page, bbox_norm:[x0,y0,x1,y1], role:"EXPECTED"\|"ACTUAL"\|"CONTEXT", extracted_value?, note?}` | `201 {fragment}`, updated `evidence_status` |
| DELETE | `/api/v1/suspicions/{id}/evidence/{fragment_id}` | inspector | — | `204` |
| POST | `/api/v1/suspicions/{id}/convert` | inspector | `{expected_value?, actual_value?, comment?}` + `If-Match: <version>` | `201 {check_id, finding_id, evidence_group_id}`. `409 {missing:[...]}` if the evidence gate fails. `423` if the protocol is finalized |
| POST | `/api/v1/suspicions/{id}/dismiss` | inspector | `{reason_code, comment}` (both required) | `200` |
| POST | `/api/v1/suspicions/{id}/clarify` | inspector | `{comment}` | `200` |
| POST | `/api/v1/suspicions/{id}/reopen` | inspector | `{comment}` | `200` (only before finalization) |
| GET/POST | `/api/v1/logical-rules` | admin (GET: inspector read-only) | rule JSON (schema-validated) | list / `201` |
| GET/PUT | `/api/v1/logical-rules/{id}` | admin | full rule. PUT creates a **new version** row; the old one is kept | rule |
| PATCH | `/api/v1/logical-rules/{id}/active` | admin | `{is_active}` | rule |
| POST | `/api/v1/logical-rules/{id}/dry-run` | admin | `{process_id}` | `{applicable, condition_value, expected_value, facts_used[], would_emit, preview_description}` (proxied to the worker's internal endpoint) |
| GET | `/api/v1/hypotheses/stats` | ml_engineer, admin | `from, to, object_id?` | per rule/method: generated, converted (manual/auto), dismissed by reason, confirmed-after-conversion, negative-after-conversion, stale |

**RabbitMQ.** Topic exchange `inspector.events` plus a work exchange `inspector.tasks`.

| Queue / routing key | Direction | Payload (JSON, versioned `schema: "hyp.v1"`) |
|---|---|---|
| `process.parsed` (event) | Module 1 → us | `{process_id, object_id, input_manifest_hash, file_ids[], scenario, changed_file_ids[]?, correlation_id}` |
| `hypotheses.run.requested` → queue `hypotheses.requests` (DLQ `hypotheses.requests.dlq`) | orchestrator/API → worker | `{run_id, process_id, object_id, mode, file_ids[], changed_file_ids[], versions:{matrix, rules_set, normative_set, taxonomy, models}, requested_by, correlation_id, deadline_at}` |
| `hypotheses.run.completed` | worker → protocol builder, API | `{run_id, process_id, status:"OK"\|"PARTIAL"\|"FAILED", counts_by_method, counts_by_priority, detector_status:{LOGICAL:"OK",GRAPHIC_DIFF:"TIMEOUT",...}, stale_suspicion_ids[], new_suspicion_ids[], duration_ms}` |
| `hypotheses.change_facts` | worker → Module 2 | `{process_id, facts:[{change_type, subject_key, matrix_code, stage_pair, fragments[], values}]}` (router output for matrix-mapped facts) |
| `suspicion.converted` | API → Module 2 / protocol | `{suspicion_id, check_id, evidence_group_id, rule_code, rule_version, promoted_by:"INSPECTOR"\|"SYSTEM"}` |

Delivery: at-least-once, idempotent by `run_id` (and `suspicion_key` upsert). Retries: 2 with backoff on timeout (§9.1 table); then DLQ + admin notification through Module 11/12.

### 3.6 Data model

Table names align with ТЗ §10. **Bold** columns are the ТЗ key fields.

**Suspicions** (ТЗ #8):

| Column | Type | Notes |
|---|---|---|
| **id** | BIGSERIAL PK | = `suspicion_id` in JSON (the ТЗ example uses an integer, 2001) |
| suspicion_key | CHAR(64) | dedup fingerprint; unique (object_id, suspicion_key) WHERE NOT is_stale |
| **object_id** | FK Objects | — |
| process_id | FK | — |
| run_id | FK Hypothesis_Runs | — |
| first_protocol_id | FK Protocols | protocol version where it first appeared |
| **discovery_method** | VARCHAR(32) | `LOGICAL_ANALYSIS \| SEMANTIC_DISSONANCE \| NORMATIVE_ANALYSIS \| ML_PATTERN_ANALYSIS \| GRAPHIC_DIFF` |
| detector | VARCHAR(64) | e.g. `ROOM_ALIGNMENT`, `EXPLICATION_SUM`, `ROBUST_Z` |
| rule_code / rule_version | VARCHAR(32) / INT | e.g. `HR-SEM-001` / 2 |
| logical_rule_id / normative_base_id | FK nullable | — |
| **confidence** | NUMERIC(4,3) | CHECK 0..1 |
| **description** | TEXT | Russian |
| subject_type / subject_key | VARCHAR | ROOM / ELEMENT / DOCUMENT / OBJECT / SHEET |
| expected_value / actual_value | JSONB | typed values with units |
| pd_reference / rd_reference / id_reference | TEXT | «шифр, л.N, стр.M»; `id_reference` is our addition |
| review_priority | VARCHAR(10) | — |
| normative_base | TEXT | display string with edition |
| finding_status | VARCHAR(20) | DEFAULT 'SUSPICION', **CHECK (finding_status='SUSPICION')** |
| **inspector_status** | VARCHAR(32) | DEFAULT 'PENDING' (§3.7) |
| evidence_status | VARCHAR(10) | UNBOUND / PARTIAL / BOUND |
| revision_fingerprint | CHAR(64) | — |
| supporting_methods / explanation | JSONB | facts, features, scores, registration residuals |
| related_check_ids | BIGINT[] | cross-links to matrix findings |
| converted_check_id / converted_evidence_group_id / promoted_by | FK / VARCHAR / VARCHAR | — |
| is_stale / stale_reason | BOOL / TEXT | — |
| decided_by / decided_at / reason_code / inspector_comment | — | — |
| row_version / created_at / updated_at | INT / TIMESTAMPTZ | optimistic locking |

**Other tables:**
- **Logical_Rules** (ТЗ #9). ТЗ columns: **id, rule_name, condition** (JSON text), **expected** (JSON text), **normative_base, is_active**. Our additions: `rule_code, version, predecessor_id, description, applicability, severity, base_confidence, promotable, message_template, overlaps_matrix_codes, verified, verified_by, created_by, created_at, updated_at`. Editing inserts a new version; runs reference exact versions.
- **Normative_Base** (ТЗ #10, owned by Module 8). ТЗ columns: **id, document_name, document_number, section, parameter_name, min_value, max_value, effective_from, effective_to**. Extras requested by us: `unit, fact_key, applicability, comparison, severity, is_active, verified, version`.
- **Evidence_Fragments** (ТЗ #14, owned by Module 2). We need a nullable `suspicion_id` and `origin` (SYSTEM/INSPECTOR); `evidence_group_id` stays null until conversion. On conversion the fragments are **copied** into the new evidence group, so the suspicion's history stays immutable.
- **Checks** (ТЗ #2, owned by Module 2). For converted findings we need nullable `param_id` + `rule_code`, `rule_version`, `source_suspicion_id`.
- New tables:
  - **Hypothesis_Runs**: `id (uuid), process_id, mode, input_manifest_hash, matrix_version, rules_set_version (hash of active rule versions), normative_set_version, taxonomy_version, model_versions JSONB, status, detector_status JSONB, started_at, finished_at, error JSONB`.
  - **Change_Matrix_Map**: `change_type, subject_category, discipline, matrix_code, is_active`.
  - **Quantity_History**: `object_id, protocol_id, building_class, stage, feature_key, value, unit, created_at`.
- Seed data files (versioned in the repo, loaded by migration): `seed/logical_rules.json`, `seed/normative_base_hyp.json`, `seed/room_taxonomy.yaml`, `seed/element_classes.yaml`, `seed/antonyms.yaml`, `seed/category_shift_matrix.yaml`, `seed/reference_priors.yaml`, `seed/change_matrix_map.json`.

### 3.7 State machine (suspicion `inspector_status`)

```
            (run)           bind evidence (evidence_status UNBOUND→PARTIAL→BOUND; status unchanged)
   ┌────────► PENDING ──────────────────────────────────────────────┐
   │            │  │  \                                              │
   │   clarify  │  │   \ convert [gate OK, protocol ∈ {READY,VERIFYING,COMPLETED}, not stale]
   │            ▼  │    ▼
   │  CLARIFICATION_REQUIRED     CONVERTED_TO_CANDIDATE ──► (Checks: CANDIDATE → Module 3: CONFIRMED_VIOLATION / NEGATIVE_VERIFIED / CLARIFICATION_REQUIRED)
   │            │  │ dismiss [reason_code+comment]
   └── reopen ──┘  ▼
                DISMISSED
   AUTO_CONVERTED (only if D1=hybrid: system gate + confidence ≥ τ + rule.promotable) ──► Checks: CANDIDATE (promoted_by=SYSTEM)
   STALE (system: inputs superseded by dozagruzka)       — terminal, hidden by default, kept for audit
   At finalization: PENDING/CLARIFICATION_REQUIRED frozen and rendered «не рассмотрено»; no transitions until «Отмена финализации».
```

**Evidence gate for conversion (HYP-19/25).**
- At least one `EXPECTED` and at least one `ACTUAL` fragment. For single-document rules (HR-LOG-005/006/008) both roles may sit on the same document. For normative-only rules, `EXPECTED` = the `Normative_Base` row.
- Every fragment has `file_id, sha256, stage, document_code, revision, approval_status ∈ {APPROVED, FOR_CONSTRUCTION}, page, sheet_no, bbox_norm ⊂ [0,1]²`.
- All sources are the актуальные revisions (not `SUPERSEDED`/`CANCELLED`) and not under `CLARIFICATION_REQUIRED` in Module 1.
- `expected_value` and `actual_value` are non-empty; `rule_code@rule_version` is set.
- The suspicion is not stale. `approved_change_ref` is filled if known, else `NONE`.

**Dismiss reason codes:**
- `APPROVED_CHANGE` (согласованное изменение)
- `EXTRACTION_ERROR` (ошибка OCR/извлечения)
- `ALIGNMENT_ERROR` (ошибка привязки/сопоставления)
- `RULE_NOT_APPLICABLE`
- `NORM_EDITION_NOT_APPLICABLE`
- `DUPLICATE_OF_MATRIX_FINDING`
- `DETAILING_NOT_CHANGE` (РД детализация)
- `OTHER`

Every transition writes to `Audit_Log` with user_id, timestamp, IP, user agent, suspicion_id and before/after.

### 3.8 UI (React; shared evidence viewer with Module 3)

1. **Protocol → tab «Гипотезы свободного поиска».**
   - Persistent banner: «Гипотезы (SUSPICION) не являются нарушениями, не входят в сводное число нарушений и не используются как учебные метки (п. 9.5 ТЗ)».
   - Table columns: ID, method badge (Логический анализ / Семантический диссонанс / Нормативный анализ / ML-паттерн-анализ / Графическое сравнение), description, ПД / РД / ИД references, norm, confidence bar, priority, evidence status (Не привязаны / Частично / Привязаны), inspector status.
   - Filters by method, priority and status. Atomic suspicions are visually grouped (e.g. «Система В2 — 5 помещений»).
2. **Suspicion card.**
   - Side-by-side ПД | РД (| ИД) page viewers (pdf.js) with highlighted bboxes; optional overlay toggle for graphic diff.
   - «Почему система так считает» panel: rule condition rendered in Russian, facts with values and clickable sources.
   - Actions: «Привязать доказательство» (accept a suggested fragment in 1 click, or draw a bbox); «Преобразовать в CANDIDATE» (disabled with a tooltip listing the missing gate items); «Отклонить гипотезу» (reason + comment); «Требует уточнения».
   - With auto-bound evidence, conversion takes ≤ 2 clicks (matches the §9.3 «не более 3 кликов» spirit).
3. **Admin → «Логические правила»** (in the Module 8 admin shell): list with versions and verified badges; editor (JSON with schema hints + live Russian preview); activate/deactivate; «Проверить на процессе» (dry-run); version history.
4. **Dashboard (Module 7).** Suspicion counts are shown separately and never included in the red/yellow/green violation indicator (only as a neutral «гипотез: N» chip).

### 3.9 Feasibility evidence (measured on the pilot PDFs)

These are prototype scripts in the session scratchpad, not project code.

| Check | Result |
|---|---|
| Page structure | 24 pages; vector drawings with 5k–113k paths per page and a real text layer (up to 2 291 words); p9 and p14 are scans (≤ 26 words); expert markup is partly Ink annotations and partly baked into content (red/blue boxes) |
| Explication extraction | ALT79B ПД «Спецификация помещений 1-го этажа» and РД «Экспликация помещений 1-го этажа»: 24 rows each (number, name, area) extracted exactly by row clustering |
| Free-search finding not in the expert markup | ALT79B ПД: Σ rows = **2795.04 m²** vs «Общий итог по этажу» **2797.27 m²** (Δ 2.23 m²) → HR-LOG-005. РД: Σ 2811.06 vs 2811.07 (rounding, no hit) |
| Below-trigger totals | ALT79B +0.493 %, SOSH25 +0.292 %, DOO25 −0.287 % → M-002 (> 1 %) does not fire |
| Robust z on ALT79B deltas | median +1.17 %, MAD 0.96 → outliers «Тех.помещение» 18 z = 4.0, «Электрощитовая» 17 z = 3.0, ПУИ z = 2.8 |
| Typo in real data | РД «Комтана отдыха» → needs fuzzy normalisation |
| Label-based registration | ALT79B: scale 0.9991, offset −178.7 pt, residuals 2–3 pt on 6 anchors (out of 3370 pt width). SOSH25 overview vs fragment: scale **2.000** recovered. DOO25: 9/12 inliers, scale 1.006. ALT79B/LOS3A with RANSAC: inliers concentrated in one column → shows why the **anchor-spread quality gate** and fallbacks are required |
| Page-level raster diff (masked markup) | Negative POL17 pairs: removed 3.9–4.9 %, added 13–19 % of ink, with 4–9 / 18–21 blobs. Positive pairs: removed 20–45 %, but dominated by sheet-layout differences → page-level ratios are **not** a classifier; viewport scoping + per-room aggregation + directional weighting are required. Plan-zone only: DOO25 removed 24 % vs POL17 2.8–4.5 % |
| Vent example | Only raster crops are provided (ПД schematic vs РД plan) → text-anchored element inventories are the only viable approach; vector originals are requested (§8) |

### 3.10 Performance plan

| Step | Budget | Expected |
|---|---|---|
| Inventories (text layer) per sheet | < 1 s | PyMuPDF word extraction is ~ms per page |
| Embedding per room name (ONNX int8, CPU) | ≤ 20 ms (≪ 500 ms §11 #7) | batched; cached by text hash in Redis |
| Registration + diff per sheet pair | ≤ 10 s (≪ 30 s §11 #8) | render at 0.5 zoom (A0 ≈ 1685×1192 px); `get_drawings()` on 100k paths ≈ 1–3 s |
| Whole run for an object | ≤ 120 s (parallel to comparison ≤ 2 min) | process pool of 4 on 12 cores; graphic pairs in parallel |
| Incremental run | ≤ 45 s (≤ 1 min §11 #9) | only changed pairs + object-level rules |
| API list/detail p95 | ≤ 200 ms | indexed by process_id, inspector_status, priority |

---

## 4. Interfaces with other blocks

| Block (ТЗ module) | We consume | We produce | Contract items |
|---|---|---|---|
| M1 Upload / parsing | Words + bboxes, tables, sheet metadata (document_code, sheet no., title, stage, discipline, floor), page geometry, normaliser, file registry, revision chain, completeness statuses, OCR confidence | Optional request: explication table extractor as a shared function | I-1: the parse output schema must expose words with bboxes per page and detected tables. I-2: sheet → PDF-page mapping (`sheet_page_range`) |
| M2 Comparison / protocol | Matrix findings (for cross-links), Evidence_Fragments/Checks schema, protocol builder | Suspicions for section (5); `hypotheses.change_facts` for matrix-mapped changes; converted CANDIDATEs | I-3: DB write ownership. I-4: `Checks.param_id` nullable + `rule_code/version/source_suspicion_id`. I-5: `Evidence_Fragments.suspicion_id`. I-6: router table ownership |
| M3 Verification | Evidence viewer component, decision flow for converted candidates | Card actions (bind/convert/dismiss/clarify) | Shared bbox viewer; same reason-code style |
| M4 Feedback / retraining | Model registry, dataset builder | Guarantee: no SUSPICION rows in datasets; converted findings carry `rule_version` | Dataset builder filter test |
| M6 РиН integration | — | Nothing (suspicions are never exported) | Export filter test |
| M7 Dashboard / exports | — | Section (5) data; counts shown separately | Counters exclude SUSPICION |
| M8 Normative admin | Normative_Base (+ requested extra columns), rule-admin UI shell | Logical_Rules API + editor component | Columns `fact_key, applicability, unit, comparison, severity, verified` |
| M9 Audit | Audit API | Events: SUSPICION_* and LOGICAL_RULE_* | Event names |
| M10 Weekly ML report | — | `/hypotheses/stats` | Fields listed in §3.5 |
| M11 Monitoring | Prometheus scraping, JSON log shipping | Metrics: `hyp_run_duration_seconds{detector}`, `hyp_suspicions_total{method,priority}`, `hyp_detector_errors_total`, `hyp_registration_residual_pt`, `hyp_embedding_latency_ms`, `hyp_queue_lag` | — |
| M12 Error handling | Error envelope, retry policy | Detector-level statuses, DLQ | Error codes `HYP_*` |

---

## 5. Too complex / risky items and simplifications

| Item | Why risky | Simplification that still meets the letter |
|---|---|---|
| Generic graphic diff across arbitrary drawings | Different drawing types (schematic vs plan), scales, layouts; РД adds detailing (measured 13–19 % extra ink on a negative pair) | Restrict to paired plan-type vector sheets; label-based registration with quality gates; viewport-only; per-room directional scoring calibrated on negatives; LOW/MEDIUM priority unless corroborated by a text detector. Schematic-vs-plan goes through text inventories |
| Room polygon extraction | Walls with door gaps; hatches; missing closures | Flood fill on a closed wall mask, Voronoi fallback; evidence bbox = region bbox (IoU ≥ 0.5 is enough per §14.3) |
| Approach 4 «на исторических данных» without history | No historical objects provided | Intra-object robust statistics (real signal on the pilot) + reference priors + synthetic history for the demo; feature store ready for real accumulation |
| Normative facts (room heights) | Heights are rarely explicit on plans; sections need elevation parsing | Normative engine FULL; facts limited to robust ones (areas from explications). Heights only when explicit («h=2,50», notes, section marks), otherwise `UNKNOWN` (no suspicion) |
| Logical rules needing full-set facts (floors, lift, parking) | Pilot has only sheet excerpts, no full sets | Rules shipped and unit-tested; demonstrated on a synthetic object (clearly labelled); the rules that fire on real pilot data (HR-LOG-005/006/007/008) are emphasised |
| Correct normative clause numbers | A wrong citation in front of Мосгосстройнадзор experts is costly | Every seed reference has `verified=false` and a UI badge «требует проверки» until confirmed; the ТЗ's own example references are reproduced as-is and flagged |
| Embedding-based dissonance | Embeddings cannot tell category shifts or antonyms apart («Техническое» vs «Склад ГСМ») | Embeddings only map names to taxonomy categories; dissonance comes from the explicit shift matrix + antonym lexicon |
| Auto-promotion to CANDIDATE | Could be read as bypassing the inspector | Strict gate + per-rule `promotable` flag + `promoted_by=SYSTEM` visible; CONFIRMED still requires the inspector; configurable (D1) |
| LLM | Hallucination, data leakage, latency on CPU in Docker | Off by default; never a source of evidence; used only for wording and optional second opinions; PII scrubbing before any cloud call |
| Protocol format | Приложение № 2 missing | Implement a structured section (5); adapt the layout when the sample arrives |

---

## 6. ТЗ contradictions and ambiguities (block-specific)

1. **Who converts SUSPICION → CANDIDATE?** §9.5 gives only an evidence precondition; the §9.2 table lists it as an inspector action «при необходимости». *Interpretation:* the inspector always can; the system may auto-promote only when the full evidence gate passes and the rule is verified as promotable (D1).
2. **Boundary between «вне Матрицы» and matrix parameters.** Room-level changes relate to M-002/M-003/M-010/M-011 but fall below their triggers. *Interpretation:* the change-fact router (D2). A matrix-mapped change goes to Module 2; otherwise it becomes a suspicion; never both.
3. **`discovery_method` values are not enumerated** (only `LOGICAL_ANALYSIS` appears). *Proposal:* `LOGICAL_ANALYSIS, SEMANTIC_DISSONANCE, NORMATIVE_ANALYSIS, ML_PATTERN_ANALYSIS` + extension `GRAPHIC_DIFF` (D3).
4. **Only `pd_reference`/`rd_reference` exist**, yet ИД-based hypotheses exist (IZM12, OKT103). *Proposal:* add `id_reference` (additive; the ТЗ fields stay verbatim).
5. **`suspicion_id` is an integer in the example**, while `finding_id` is a string elsewhere. *Proposal:* keep an integer `suspicion_id` (as in the ТЗ) + `suspicion_key` for dedup; the converted finding gets a string `finding_id`.
6. **`inspector_status` values are not defined beyond `PENDING`.** *Proposal:* §3.7.
7. **Finalization with pending suspicions is not specified** (§9.3 p.4 only speaks of CANDIDATE). *Proposal:* non-blocking warning; frozen as «не рассмотрено» (D6).
8. **Normative suspicions have no «expected source document».** *Interpretation:* the `Normative_Base` row (document, пункт, edition) counts as the expected source; the ACTUAL fragment must have coordinates.
9. **Example normative attribution.** The ТЗ says «2.5 м по СанПиН»; to our knowledge the 2.5 m residential ceiling height is set by СП 54.13330. The ТЗ lift example cites «СП 54.13330.2022, п. 7.1.3», while lift requirements (to our knowledge) sit in section 4 of СП 54. *Interpretation:* keep the ТЗ strings in the demo rules and flag them for verification; correct them via the admin UI after expert review.
10. **«Сопоставимые редакции» is not defined for dedup.** *Interpretation:* the same актуальные revision set, i.e. the same `revision_fingerprint`.
11. **§11 «CV-анализ одного чертежа (DWG)»** although DWG is not an accepted input. *Interpretation:* one drawing sheet (PDF page/pair) ≤ 30 s.
12. **§9.4 forbids SUSPICION in training, but approach 4 is «обучение на исторических данных».** *Interpretation:* unsupervised models learn from quantities of finalized objects, not from suspicion labels; supervised re-ranking uses only legitimate GOLD from converted findings.
13. **Title of §9.3 duplicates §9.2** (verification module). No impact on our design.

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation | Impact |
|---|---|---|---|---|
| D1 | Auto-promotion SUSPICION → CANDIDATE | (a) inspector only; (b) hybrid: auto when the evidence gate passes + confidence ≥ 0.8 + rule `promotable`, marked `promoted_by=SYSTEM`; (c) always auto when evidence is complete | **(b)**, switchable globally and per rule; demo shows both paths | 6 of 8 pilot CANDIDATE-type groups + 3 vent items are Module 5 changes; with (a) they are unscored SUSPICIONs in any automated hidden-test run |
| D2 | Boundary with the Matrix | (a) Module 5 emits everything it finds; (b) change-fact router (mapped → Module 2, unmapped → SUSPICION); (c) Module 2 absorbs all room-level changes under M-002/M-003 | **(b)** with an admin-editable `Change_Matrix_Map` | Prevents double counting; keeps «вне Матрицы» literal; needs Module 2 to accept external change facts |
| D3 | `discovery_method` for graphic comparison | (a) 5th value `GRAPHIC_DIFF`; (b) fold into the 4 values with a `detector` sub-field | **(a)** — the ТЗ does not enumerate values; shows exceeding the spec | Protocol/UI labels |
| D4 | LLM usage | none / local (Ollama, e.g. a 7B instruct model; slow on CPU in Docker) / cloud (Russian-hosted: YandexGPT, GigaChat; or foreign if allowed) | **None by default**; optional local adapter; cloud only after confirming 152-ФЗ allowance | Offline guarantee; demo stability |
| D5 | Embedding model | paraphrase-multilingual-MiniLM-L12-v2 (ONNX int8 ≈ 120 MB) / rubert-tiny2 (≈ 30 MB) / multilingual-e5-small | **Multilingual MiniLM** (literal «совместимый аналог» of all-MiniLM), rubert-tiny2 as fallback | Image size; spec compliance argument |
| D6 | Finalization with PENDING suspicions | block / warn / silent | **Warn**, then freeze as «не рассмотрено» | UX; ТЗ only requires CANDIDATE processing |
| D7 | Date that selects the norm edition | document approval date / process date | **Approval date of the checked revision**, fallback to process date | Legally closer to how expertise works; transparent in `normative_base` |
| D8 | Normative references verification | accept «требует проверки» badges / find a domain expert | Ask a domain expert (even 1 hour) to confirm ~15 seed references | Credibility with the jury |
| D9 | Use of synthetic demo data (modified pilot PDFs: rename «Тех.помещение» → «Склад ГСМ», synthetic 15-floor object without lift) | yes, clearly labelled / no | **Yes, labelled «синтетический пример»** | The pilot lacks examples for approaches 1, 3 and 4 as stated in the ТЗ |
| D10 | Graphic-diff scope in the MVP | plans only (vector) / plans + sections / + scans | **Vector plans** (+ door arcs); scans best-effort, LOW priority | Effort L vs XL |

---

## 8. Data needed

| What | Why | Fallback if never received |
|---|---|---|
| Приложение № 2 (sample protocol) | Exact layout of table (5) and the evidence card | Structured section per §9.2 p.4; restyle later |
| Vector originals of АНО/150321/1-П-ИОС5.4.2 and 1-РД-ОВ1 / ОВ2.1 | The vent example exists only as raster crops; needed to test element inventories on real vectors | Recreate the three cases as a synthetic vector fixture from the crops (labelled) |
| Full (or larger) ПД/РД sets for 1–2 pilot objects | Sheet pairing across a set; object-level facts (floors, lift); realistic runtime | Synthetic object; pilot pages as isolated pairs |
| Organisers' rule on scoring free-search findings in the hidden test (do CANDIDATEs from free-search rules count? which «тип расхождения» taxonomy?) | Decides D1/D2 | Hybrid D1 + router D2 hedges both interpretations |
| Historical quantities (areas by category, concrete/steel ratios) for several finalized objects | Approach 4 «исторические данные» | Reference priors + synthetic history (labelled) |
| Expert confirmation of the seed normative references (and preferred Logical_Rules list from Мосгосстройнадзор practice) | Credibility; rule relevance | `verified=false` badges; rules editable by admin |
| Room-naming classifiers used by Мосгосстройнадзор/БТИ (if any) | Taxonomy coverage | Taxonomy built from the pilot + standard names (СП 54/118 terminology) |
| Whether the machine-readable registry will include sheet titles / floor per page | Faster, more reliable sheet pairing | Parse titles from the title block and sheet header text |

---

## 9. Jury demo scenario and acceptance tests

### 9.1 Demo (≈ 6 minutes)

1. **Upload ALT79B ПД + РД** with registry → protocol READY.
   - Section (1) shows M-002 not triggered (+0.49 % < 1 %). This demonstrates why Module 5 exists.
   - Section (5) contains:
     - (a) `SEMANTIC_DISSONANCE` HIGH/MEDIUM: «Помещение 23 «Помещение» (ПД) в той же позиции обозначено как 22 «Комната отдыха» (РД)» — the typo «Комтана» is normalised, and the card shows both bboxes;
     - (b) `ML_PATTERN_ANALYSIS`: tech-room area outliers (+6.8 %, +5.5 %) against a systematic +1.17 % shift;
     - (c) `LOGICAL_ANALYSIS` HR-LOG-005: «В ПД сумма площадей экспликации 2795,04 м² не равна итогу 2797,27 м²». **This one is not in the expert markup.**
2. **Open card (a)** → 1 click «Преобразовать в CANDIDATE» → a CANDIDATE with `HR-SEM-001@v1` appears in table (2) → inspector confirms → the summary number of violations changes **only now**.
3. **Upload SOSH25 and DOO25** → room 1.109 added (18.2 m²); пищеблок 135–150 changes. The graphic overlay localises the changed zone.
4. **Negative control POL17** → no HIGH suspicions; the overlay shows added РД marking classified as detailing.
5. **Synthetic object** (labelled):
   - a 15-floor building without a lift → the exact ТЗ suspicion JSON (`LOGICAL_ANALYSIS`, «В РД отсутствует лифтовая шахта при 15 этажах.», «СП 54.13330.2022, п. 7.1.3»);
   - «Техническое» → «Склад ГСМ» → `SEMANTIC_DISSONANCE` HIGH with fire-category reasoning;
   - a kitchen of 7.5 m² → `NORMATIVE_ANALYSIS`.
6. **Admin**:
   - changes a `Normative_Base` min_value and deactivates a logical rule → re-run → the suspicion set changes without a redeploy;
   - dry-run of a new rule on the process.
7. **Dozagruzka** of a corrected РД revision → the old suspicions become STALE; the incremental run takes < 1 min; protocol version N+1 is created and the history is preserved.

### 9.2 Acceptance tests

| ID | Test | Pass criterion |
|---|---|---|
| AT-HYP-01 | JSON contract | Output matches the §9.5 field names and types exactly; extra fields are additive |
| AT-HYP-02 | Counts exclusion | Creating 50 suspicions changes no violation counter, dashboard colour or РиН payload |
| AT-HYP-03 | Training exclusion | Dataset builder output contains 0 rows sourced from SUSPICION (including dismissed ones) |
| AT-HYP-04 | Conversion gate | Missing bbox / sha256 / revision / approval → 409 listing each missing item; complete → 201 with a full §9.2 p.4 evidence card |
| AT-HYP-05 | Dedup | Two detectors on the same room merge into one suspicion (noisy-OR confidence); an identical subject on a different object or different revision fingerprint is not merged |
| AT-HYP-06 | Revision safety | A suspicion is never produced from `SUPERSEDED` inputs; upload of a new revision marks old suspicions STALE |
| AT-HYP-07 | Finalization freeze | All mutating endpoints return 423 after FINALIZED; they work again after «Отмена финализации» |
| AT-HYP-08 | Pilot recall (golden) | Suspicion (or routed matrix fact) overlapping the expert bbox (same page; IoU ≥ 0.5 or same room) for ALT79B, SOSH25, DOO25, POL16, IZM12, LOS3A (SHOULD) |
| AT-HYP-09 | FP gate | POL17 sections 1 and 2: 0 HIGH suspicions; ≤ 2 LOW total |
| AT-HYP-10 | ТЗ examples | Synthetic fixtures reproduce all 4 ТЗ examples (lift, ГСМ, 2.4 vs 2.5 m, concrete −20 %) |
| AT-HYP-11 | Rule engine | 3-valued logic truth tables; `UNKNOWN` never emits; malformed rule rejected on save |
| AT-HYP-12 | Edition selection | A norm with two editions picks the one in force at the approval date; overlap → reduced confidence + note |
| AT-HYP-13 | Performance | Per-item NLP ≤ 500 ms (p95); per sheet pair ≤ 30 s; full pilot run ≤ 120 s; incremental ≤ 60 s; API p95 ≤ 200 ms at 100 concurrent users (k6) |
| AT-HYP-14 | Resilience | Killing the graphic detector mid-run yields `PARTIAL` with other detectors' results persisted; redelivered message creates no duplicates |
| AT-HYP-15 | Audit | Each transition produces an Audit_Log row with user, IP, timestamp and before/after |
| AT-HYP-16 | Offline | With network disabled, the run completes (LLM Noop, embedded model files) |
| AT-HYP-17 | Coordinates | Evidence bboxes render correctly on rotated/cropped test pages (Module 1 fixtures) |

---

## 10. Work breakdown

S ≤ 0.5 day, M ≤ 1.5 days, L ≤ 3 days.

| ID | Task | Size | Depends on | Owner (implementation agent) |
|---|---|---|---|---|
| HYP-T01 | Contracts: DB migrations (Suspicions, Logical_Rules ext., Hypothesis_Runs, Change_Matrix_Map, Quantity_History; Evidence_Fragments.suspicion_id; Checks.rule_code), OpenAPI paths, MQ message schemas | M | M1/M2 contract drafts | Backend (Node) + hypotheses agent |
| HYP-T02 | Python `hypothesis-worker` skeleton: aio-pika consumer, run orchestration with budgets, detector plug-in interface, Redis cache, structlog, Prometheus, Dockerfile (arm64/amd64, CPU) | M | T01 | Hypotheses (Python) agent |
| HYP-T03 | Docmodel adapter + inventories (explication/spec tables, room labels, element labels, section layer lists, sheet metadata) with PyMuPDF fallback | M | T02; M1 parse schema | Hypotheses agent |
| HYP-T04 | Sheet pairing + label-based registration with quality gates + ORB fallback | M | T03 | Hypotheses agent |
| HYP-T05 | Taxonomy/normaliser: abbreviation dictionary, pymorphy3, rapidfuzz, ONNX embedding model, antonym lexicon, shift matrix (seed YAMLs) | M | T02 | Hypotheses agent |
| HYP-T06 | Room alignment (number + position Hungarian, renumber detection) + semantic detectors HR-SEM-001…008 | M | T04, T05 | Hypotheses agent |
| HYP-T07 | Rule engine (JSON AST, 3-valued), fact sheet builder, 12 seed Logical_Rules + unit tests | L | T03 | Hypotheses agent |
| HYP-T08 | Normative detector + edition selection + seed rows (with `verified=false`) | M | T07, T06 | Hypotheses agent |
| HYP-T09 | ML pattern detectors (robust z, identical units, ratios with priors, IsolationForest), Quantity_History writer, synthetic history generator | M | T06 | Hypotheses agent |
| HYP-T10 | Graphic diff (viewport, tolerant raster + vector segment diff, room regions, door arcs, overlay PNGs) calibrated on POL17 | L | T04 | Hypotheses (CV) agent |
| HYP-T11 | Scoring (confidence fusion, priority), dedup, router + cross-link, persistence (idempotent upsert), stale handling | M | T06, T07, T08, T09, T10 | Hypotheses agent |
| HYP-T12 | Node API: suspicion endpoints, state machine, evidence gate, conversion transaction into Checks/Evidence_Fragments, auto-promotion policy (D1), audit hooks, RBAC | M | T01 | Backend agent |
| HYP-T13 | Frontend: suspicions tab, card with side-by-side viewers and overlay, evidence binding tool, convert/dismiss/clarify flows | L | T12; M3 evidence viewer | Frontend agent |
| HYP-T14 | Admin UI for Logical_Rules (editor, versions, activate, dry-run) | M | T12, T07 | Frontend agent (+ M8 admin shell) |
| HYP-T15 | Protocol section (5) in JSON/PDF/DOCX/XML exports | S | T11, T12 | Protocol/exports agent (M2/M7) |
| HYP-T16 | Golden tests on the pilot (ALT79B, SOSH25, DOO25, POL16, IZM12, LOS3A), POL17 FP gate in CI, synthetic demo fixtures (lift, ГСМ, kitchen, concrete ratio, vent recreation) | M | T06, T07, T09, T10 | QA/Hypotheses agent |
| HYP-T17 | Stats endpoint for the weekly report + metrics dashboard panel | S | T11 | Backend agent |
| HYP-T18 | LLM adapter interface (Noop default, Ollama, cloud stub) + PII scrubbing | S | T02 | Hypotheses agent |
| HYP-T19 | Incremental runs + finalization freeze integration tests | S | T11, T12 | Backend + Hypotheses agents |

**Critical path:** T01 → T02 → T03 → T04 → T06 → T11 → T12/T13 → T16. Start T07 (rule engine) and T10 (graphic) in parallel right after T03/T04.
