# 92 — Hackathon Strategy: how «Инспектор ИИ» wins (task №10, Мосгосстройнадзор)

Status: PLANNING / STRATEGY (no application code). Requirement prefix: `STR-NN`. Task prefix: `STR-T..`.
Role: hackathon strategist (cross-cutting). Consolidates B00–B10 (`00_architecture.md` … `10_error_handling_negative_scenarios.md`, `_block_summaries.json`) against the full ТЗ (`docs/spec/01_TZ_text.txt`), the matrix workbook (МАТРИЦА, СХЕМА GOLD, МЕТРИКИ, ПРИМЕРЫ РАЗМЕТКИ) and the pilot markup kits.

Facts I re-verified for this report:
- ALT79B ПД стр.19 (pilot p.2) has **24 explication rows summing to 2795,04 м²**, but the sheet states «Общий итог по этажу **2797,27 м²**» (Δ 2,23 м²). The expert markup does not mention this. It is a safe live "we found something your experts did not mark" moment.
- `Комплект_предметной_разметки.pdf` is **53 993 684 bytes (51,49 MiB)**. It breaks the ТЗ 50 МБ file limit however МБ is read, so the letter of the ТЗ requires us to reject the organizers' own file.

---

## 0. Executive summary (the win thesis on one screen)

**Win thesis.** The jury is most likely a mix of Мосгосстройнадзор inspectors (domain) and ДИТ/organizer technical experts. They will score five things:
1. ТЗ compliance by module priority: all 12 modules are present, and the 6 High modules are deep.
2. An objective run on the hidden test (§14.3).
3. A live demo on their own documents.
4. The inspector's verification UX.
5. Integration and engineering readiness.

We win by being the team that covers **all of it, exactly to the letter, visibly, and honestly**:

| # | Move | Why it wins points |
|---|---|---|
| 1 | **Make our output scorable on their hidden test.** Emit СХЕМА GOLD field names verbatim plus the ПРИМЕРЫ notation (`PD:ALT79B-000015:стр.19:bbox […]`). Echo registry `file_id`s. Use page = PDF page index. Use region-level bboxes (whole table or zone, as the experts draw them). Ship `inspector-batch` + `inspector-eval`. | §14.3 metrics are computed per evidence_group and need the right param, file_id and page, with IoU ≥ 0,50. A format mismatch scores zero even if the system "works". This is the #1 lever and the #1 risk. |
| 2 | **Precision-first, fail-visible.** Uncertainty becomes MISSING_EVIDENCE / NOT_COMPARABLE / CLARIFICATION_REQUIRED / ABSTAIN, never a guess. Recall comes from the "big-5" extractors: explication tables, ТЭП/specification tables, layer stacks, RD change-log rows, ИД tolerance tables. | All §14.3 thresholds are mandatory («не считается принятой при недостижении любого обязательного порога»). P ≥ 0,90 and FPR ≤ 0,10 are reachable; recall is the hard one. 7 of the 8 non-negative pilot findings sit in those five sources; the eighth, IZM12, is a document-level rule. |
| 3 | **A 12-minute demo that hits every ТЗ beat on the organizers' own pilot pages.** The protocol comes out in *their* «Графическая фиксация» visual style. | The domain jury recognizes its own documents and format. The technical jury sees the whole lifecycle working. |
| 4 | **Proof artifacts inside the product:** «Соответствие ТЗ» (clause → requirement → test → result), «Пилот: 9/9 групп», «Качество §14.3» (n, CI, coverage), «НФТ §11» (15 rows measured), «Самопроверка» (≈60 negative scenarios live in < 2 min). | Turns "we claim" into "you can click and verify". Cheap once tests carry `@req` tags. |
| 5 | **Honesty as a feature.** Synthetic data carries a badge. Metrics carry n and a 95 % CI. The §14.1 caveat is quoted. УКЭП is labelled "real GOST crypto, not a qualified signature". | Expert jurors punish overclaiming; they reward rigor. |
| 6 | **Demo-able at every checkpoint.** Contracts freeze at T-13. A golden thread on real pilot data runs by T-10. Feature-complete at T-6. RC at T-3. Freeze and rehearsals T-2…T-0. | The biggest real risk is integration collapse across ~10 agents, not any single algorithm. |
| 7 | **Cut depth, never breadth.** A pre-agreed 3-level cut order, with effort caps per module. | The block WBS sums to **244 tasks and ≤ 360,5 agent-days**, against roughly 140 agent-days available (10 agents × 14 days). |

**Top 5 risks:** (R01) hidden-test output not scorable; (R02) integration collapse, with no end-to-end path on demo day; (R03) recall below 0,80; (R04) visible false positives in front of inspectors; (R05) the live demo breaks. Mitigations are in §5.

**Decisions the user must make today (§7):**
- deadline, format and judging criteria;
- LLM policy (recommend: none in the critical path);
- install OrbStack and the brew dependencies;
- candidate policy (per-parameter);
- scorer suppression off for hidden-test runs;
- approve sending the organizer letter (§8.2, Russian draft ready);
- recruit 5 usability participants;
- a domain expert for about 40 normative references.

---

## 1. Scope

### 1.1 ТЗ clauses this strategy is built around

- **§7 (module priorities):**

  | Priority | Modules |
  |---|---|
  | High | 1 (Загрузка и парсинг), 2 (Сравнение и протокол), 3 (Верификация), 4 (Обратная связь и дообучение), 5 (Свободный поиск гипотез), 12 (Обработка ошибок) |
  | Medium | 7 (Дашборд), 8 (Нормативная база), 9 (Аудит), 10 (Еженедельный отчёт), 11 (Мониторинг) |
  | Low | 6 (Интеграция с ИС) |

  Strategy: every module must be demoable, and depth follows priority.
- **§14.1**: «Пилотная предметная разметка … задаёт формат карточки и сценарии проверки, но из-за малого объёма и дисбаланса классов не является достаточной выборкой для количественной приёмки модели.» This tells us the organizers hold a larger hidden test.
- **§14.2**:
  - «Состав hidden test и SHA-256 … фиксируются организатором до передачи задания участникам»;
  - «В тесте обязательны подтверждённые нарушения, проверенные отрицательные группы, отсутствующие доказательства, неприменимые параметры и конфликт редакций»;
  - «Участникам не передаются GOLD-метки hidden test; подбор порога по hidden test запрещён»;
  - «Каждый результат содержит dataset_version, matrix_version, model_version и input_manifest_hash».
- **§14.3 thresholds:**

  | Metric | Threshold |
  |---|---|
  | OCR Character Accuracy | ≥ 0,95 |
  | Key-field Exact Match | ≥ 0,90 |
  | Связка | ≥ 0,95 |
  | Локализация (IoU ≥ 0,50) | ≥ 0,95 групп |
  | Precision / Recall / F1 | ≥ 0,90 / ≥ 0,80 / ≥ 0,85 |
  | FPR on NEGATIVE_VERIFIED and outdated revisions | ≤ 0,10 |

  Metrics are reported per object, per section and per violation type, with n, coverage/abstention and a 95 % CI: «Система не считается принятой при недостижении любого обязательного порога, даже если сводная F1 выше порога».
- **§9.2**: the protocol form follows «Приложение № 2 … являются обязательными для исполнения». This appendix was **not provided**.
- **§9.3** usability criteria:
  - «не должно превышать 30 минут» (132 параметра, 14 нарушений);
  - «не более 3 кликов на одно нарушение»;
  - «Обязательное проведение юзабилити-тестирования на выборке из 5 инспекторов».
- **§11**: 15 NFR rows. **§12**: 11 security rows. **§13**: 8 monitoring rows. These are cheap to show and expensive to forget.
- **§1.1–1.5**: the name «Инспектор ИИ»; REST/JSON with OpenAPI 3.0 validation; the pull model with `process_id`; React + Node.js + Python ≥ 3.11 + RabbitMQ.
- **Registry rules** (`03_…`): the mandatory CSV/XLSX/JSON registry; «без него пакет принимается со статусом CLARIFICATION_REQUIRED»; «Перезапись файла под тем же file_id запрещена».

### 1.2 What this report produces
1. What the jury evaluates, and how to maximize each dimension (§3.1).
2. The killer demo script: 12 min, plus 7-min and 20-min variants and a "jury brings documents" branch (§3.2).
3. Cheap differentiators beyond the ТЗ (§3.3).
4. The demo dataset plan: legal pilot reuse plus synthetic packages covering the §14.2 classes (§3.4), and what to ask the organizers (§8).
5. Top risks and mitigations (§5).
6. A phased T-day timeline with the "demo-able at every checkpoint" rule, and the scope-cut order (§10).

Related statuses used throughout (verbatim from the ТЗ):
- Process: PENDING, PARSING, READY, VERIFYING, COMPLETED, FINALIZED.
- Verification: PENDING, CONFIRMED_VIOLATION, NEGATIVE_VERIFIED, CLARIFICATION_REQUIRED, VERIFICATION_COMPLETED, PROTOCOL_FINALIZED.
- Parameter: NEGATIVE_VERIFIED, CANDIDATE, CONFIRMED_VIOLATION, MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE, CLARIFICATION_REQUIRED, SUSPICION.
- Upload: PD_/RD_/ID_{UPLOADED, PARTIAL, MISSING}.
- Scenario: FULL, PD_RD_ONLY, PD_ID_ONLY, RD_ID_ONLY, SINGLE_ONLY, PARTIALLY_LOADED.
- Sync: PENDING_SYNC.
- Prescriptions: ISSUED, IN_PROGRESS, COMPLETED, CANCELLED, EXTENDED.

---

## 2. Requirements checklist — the jury compliance scorecard

This is the list a jury member would tick through the ТЗ with. Each row says which block delivers the item and at which demo step (§3.2) it becomes visible. It consolidates **868 block requirements** (B00 84, B01 91, B02 59, B03 60, B04 92, B05 75, B06 75, B07 56, B08 90, B09 103, B10 83) into the jury-visible level.

Legend:
- Prio: **MUST / SHOULD / NICE** (for winning).
- MVP: **FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE**.
- Proof: a demo step number (§3.2), or «Q&A», «page» (a compliance page), «self-test».

### A. General, stack, API (§1)
| ID | ТЗ ref | Jury-visible requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-01 | §1.1 | The name «Инспектор ИИ» in the UI, protocol and API docs | SHOULD | FULL | B08 | all | Trivial, visible |
| STR-02 | §1.2 | All four core functions demonstrable: 132-param cross-check, verification, external API, completeness plus incremental upload | MUST | FULL | all | 2–6 | Core of the task |
| STR-03 | §1.3 | REST over HTTPS with JSON; request **and** response validated against OpenAPI 3.0; a bad request returns a 400 problem+json | MUST | FULL | B00, B10 | 2 (terminal) | Literal wording, cheap to prove |
| STR-04 | §1.4 | Upload → `process_id` (202); a status endpoint; results fetched on request (pull) | MUST | FULL | B00, B01 | 2 (curl) | Literal wording |
| STR-05 | §1.5 | React client, Node.js server, Python ≥ 3.11 ML, REST **and** RabbitMQ between modules | MUST | FULL | B00 | slide + RabbitMQ UI | Stack is mandated |
| STR-06 | §9.1 п.5 | Parse results cached in Redis by file hash | MUST | FULL | B02 | self-test, Grafana counter | Cheap |

### B. Module 1, upload and parsing (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-07 | §9.1 err.1 | Unsupported format rejected, naming the supported formats (PDF, DOCX, XML) | MUST | FULL | B01, B10 | 2 (.dwg) | ТЗ error table |
| STR-08 | §9.1 err.2 | Corrupted PDF rejected with a request to re-upload | MUST | FULL | B10 | 2 | ТЗ error table; severity classes per B10 |
| STR-09 | §9.1 err.3–4 | 50 МБ per file and 200 МБ per package, with the limit stated in the message | MUST | FULL | B01 | 2 (organizers' 51,49 MiB kit) | ТЗ error table |
| STR-10 | §9.1 err.5 | Timeout → up to 2 retries → admin notified | MUST | FULL | B10 | 9 (self-test), 10 (Telegram) | ТЗ error table |
| STR-11 | §9.1 | Upload statuses PD/RD/ID_{UPLOADED, PARTIAL, MISSING} | MUST | FULL | B01 | 3 | Protocol section |
| STR-12 | §9.1 | Process statuses with the upload/verification permission matrix enforced | MUST | FULL | B00, B05 | 5 (423 after finalize) | Statuses are verbatim |
| STR-13 | registry rules | Machine-readable registry CSV/XLSX/JSON; missing → CLARIFICATION_REQUIRED | MUST | FULL | B01 | 2, Q&A branch | Explicit rule |
| STR-14 | §9.1 | Per file: object_id, doc_stage, discipline, document_code, revision, approval_status/date, sheet/page, file_hash, predecessor/successor | MUST | FULL | B01 | protocol annex Б | Linkage metric ≥ 0,95 |
| STR-15 | §9.1 | Latest applicable approved revision; a conflict → CLARIFICATION_REQUIRED; an outdated revision is never the reference | MUST | FULL | B01, B04 | 3 (table 1б/1д), 4d | Scored (FPR on outdated) |
| STR-16 | §9.1, §1.2 | Incremental upload without re-uploading, until finalization | MUST | FULL | B01, B05 | 4d | Core function |
| STR-17 | §9.1 alg.1 | OCR CA ≥ 0,95 and EM ≥ 0,90 on printed ≥ 300 dpi; handwriting → LOW_QUALITY/ABSTAIN; share and coverage reported | MUST | FULL (measured on proxy sets) | B02 | page «Качество», 4 (OKT103 hatch) | Scored |
| STR-18 | §9.1 alg.2 | NLP with regex_pattern plus semantic anchors; Sentence-BERT or a «совместимый аналог» | MUST | FULL (multilingual-e5-small, benchmark shown) | B02 | Q&A | all-MiniLM is English-only |
| STR-19 | §9.1 alg.3 | CV on PDF drawings: scale from the dimension line or scale bar, lines, distances | MUST | SIMPLIFIED (vector geometry + scale voting; no symbol recognition) | B02 | Q&A / 20-min variant | Realistic scope |
| STR-20 | §9.1 alg.4 | Every value carries file_id, SHA-256, stage, code, revision, approval, page and a bbox normalized to [0;1] after CropBox/MediaBox/Rotate | MUST | FULL | B02 | page «Качество» (rotated fixtures) | Localization metric |
| STR-21 | §1.2, §9.1 | Separate completeness control (ПП 87 sections, РД composition, ИД per 344/пр + Приложение 19) | MUST | FULL | B01, B03 | 3 (table 1) | Explicit |
| STR-22 | §7 #1, §9.2 alg.2 | «адаптация под сценарий загрузки»: FULL … PARTIALLY_LOADED | MUST | FULL | B01, B04 | 3 | Explicit |
| STR-23 | §9.1 | Extraction covers all 132 parameters | MUST | SIMPLIFIED depth (about 35 deep profiles + generic; every param gets an honest status) | B02, B03 | 3 (coverage view) | 132 deep profiles are infeasible |

### C. Module 2, comparison and protocol (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-24 | §9.2 | The unit of result is the evidence group (object + param/rule + current ПД/РД/ИД) | MUST | FULL | B04 | 3 | Scoring unit |
| STR-25 | §9.2 alg.1, §14.2 | matrix/dataset/model versions and input_manifest_hash fixed per run and printed in the protocol | MUST | FULL | B04, B00 | 3 (header) | Explicit |
| STR-26 | §9.2 alg.3 | Order: applicability → evidence completeness → currency/comparability → subject comparison | MUST | FULL | B04 | card decision trace | Explicit |
| STR-27 | §9.2 alg.3 | expected/actual/delta with CANDIDATE or NEGATIVE_VERIFIED; the system never sets CONFIRMED_VIOLATION | MUST | FULL | B04 | 3 | Legal core |
| STR-28 | §9.2 | NOT_APPLICABLE, MISSING_EVIDENCE, NOT_COMPARABLE and CLARIFICATION_REQUIRED are "not violations" | MUST | FULL | B04 | 3 (table 1) | Hidden-test classes |
| STR-29 | §9.2 alg.4 | Protocol JSON/PDF with «Статус загрузки документов», «Тип проверки» and the five separate tables | MUST | FULL | B04 | 3, 5 | Explicit |
| STR-30 | §9.2 alg.4 | Evidence card fields: finding_id, code, expected/actual, file_id + SHA-256 per source, stage, шифр, revision, approval, page, bbox, rationale, risk, inspector decision + reason | MUST | FULL | B04, B05 | 4a | Explicit |
| STR-31 | §9.2 alg.5 | Protocol stored with a version → READY → inspector notified | MUST | FULL | B04, B08 | 2 (bell) | Explicit |
| STR-32 | §9.2 | Incremental update recomputes only affected params; the previous version stays in history | MUST | FULL | B04 | 4d, 7 | Explicit |
| STR-33 | §9.2 | Protocol form per Приложение № 2 | MUST | SIMPLIFIED (our template in the organizers' «Графическая фиксация» style; swappable in ≤ 1 day) | B04 | 5 (PDF) | Appendix not provided |
| STR-34 | §9.2 | Risk level is ordering only, not a violation; disclaimer printed | MUST | FULL | B04, B08 | protocol legend, dashboard colour rule | Explicit |

### D. Module 3, verification (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-35 | §9.3 alg.1 | Shown at once: expected/actual, ПД/РД/ИД pages with highlighted zones, шифры, revisions, approval, approved-change link | MUST | FULL | B05 | 4a | The jury's inspectors will probe this |
| STR-36 | §9.3 alg.1 | Completeness statuses shown separately from candidates | MUST | FULL | B05 | 4 (tabs) | Explicit |
| STR-37 | §9.3 alg.2 | Confirm → CONFIRMED_VIOLATION with user_id, timestamp and comment | MUST | FULL | B05 | 4a | Explicit |
| STR-38 | §9.3 alg.2 | Reject → NEGATIVE_VERIFIED; reason_code + comment mandatory | MUST | FULL | B05 | 4b | Explicit |
| STR-39 | §9.3 alg.2 | «Требует уточнения» → CLARIFICATION_REQUIRED | MUST | FULL | B05 | 4b, 4d | Explicit |
| STR-40 | §9.3 alg.2 | Composite candidate split into atomic findings; no PARTIALLY_CONFIRMED | MUST | FULL | B05 | 4c | Explicit |
| STR-41 | §9.3 alg.3 | Missing documents uploaded without resetting verification; incremental recheck | MUST | FULL | B05, B01 | 4d | Explicit |
| STR-42 | §9.3 alg.4 | Finalization only after every CANDIDATE is processed; MISSING_EVIDENCE listed separately; only confirmed records go to РиН, with versions and registry | MUST | FULL | B05 | 5, 6 | Explicit |
| STR-43 | §9.3 alg.5 | No uploads and no status changes after finalization | MUST | FULL | B05, B00 | 5 (423) | Explicit |
| STR-44 | §9.3 | Un-finalization only by admin or supervisor, with a mandatory reason and an audit record, returning to VERIFICATION_COMPLETED | MUST | FULL | B05, B09 | 20-min variant / Q&A | Explicit |
| STR-45 | §9.3, §11 #15 | ≤ 30 min per protocol (132 params / 14 violations); ≤ 3 clicks per violation | MUST | FULL (instrumented; live counter) | B05 | 4a counter, «УТ-1» report | Explicit |
| STR-46 | §9.3 | Usability test with 5 inspectors, iterated until the targets are met | MUST | SIMPLIFIED (5 proxies unless the organizers provide inspectors; the method is published) | B05, user | page «Юзабилити» | No access yet |

### E. Module 4, feedback and retraining (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-47 | §9.4 scenarios | A reject becomes a negative draft, included only after the curator; a clarify is excluded from GOLD; a confirm becomes a positive GOLD candidate, passed out only after finalization | MUST | FULL | B06 | 8 | Explicit |
| STR-48 | §9.4 | A release holds only CONFIRMED_VIOLATION and NEGATIVE_VERIFIED with complete cards; never CANDIDATE, SUSPICION, MISSING_EVIDENCE or unfinished decisions | MUST | FULL | B06 | 8 | Explicit |
| STR-49 | §9.4, §14.2 | Object-level split; the hidden test and its SHA-256 are frozen and never used for training or thresholds | MUST | FULL | B06 | 8 | Explicit |
| STR-50 | §9.4 | Publish only if §14 thresholds pass, Recall drops ≤ 2 pp per mandatory category and FPR rises ≤ 2 pp; signed by the responsible person; rollback available | MUST | FULL | B06 | 8 | Explicit |
| STR-51 | §9.4 | Lineage per iteration: model/dataset/matrix versions, hashes, code/params, metrics, decision, person, previous model | MUST | FULL | B06 | 8 | Explicit |
| STR-52 | §9.4 | System comments reproduce the §9.4 agree/disagree templates verbatim | MUST | FULL | B06, B05 | 4b | Explicit and cheap |

### F. Module 5, free hypothesis search (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-53 | §9.5 | SUSPICION outside the matrix: not a violation, not in the summary count, not a GOLD label | MUST | FULL | B07 | 3 (table 5) | Explicit |
| STR-54 | §9.5 | Four approaches: logical, semantic dissonance, normative, ML pattern | MUST | FULL (ML pattern = intra-object robust statistics plus a history store) | B07 | 3 + DEMO-02 | Explicit |
| STR-55 | §9.5 | Suspicion JSON structure exactly as specified (`suspicion_id` … `inspector_status`) | MUST | FULL | B07 | API | Explicit |
| STR-56 | §9.5 | Dedup only within one object and comparable revisions | MUST | FULL | B07 | test | Explicit |
| STR-57 | §9.5 | → CANDIDATE only with concrete sources and coordinates; → CONFIRMED only by inspector decision | MUST | FULL | B07, B05 | 3/4 | Explicit |

### G. Module 6, ИАИС «РиН» (Low, but cheap and visible)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-58 | §9.6 | `POST /api/v1/documents/upload`; `POST /api/v1/inspection/{process_id}` only in PROTOCOL_FINALIZED | MUST | FULL (against the mock РиН) | B09 | 6 | No real РиН access |
| STR-59 | §9.6, §12.10 | Client certificates (УКЭП) and a УКЭП signature on requests | SHOULD | MOCKED (mTLS with a dev CA; real GOST R 34.10-2012/Streebog signature, not qualified) | B09 | 6 | CryptoPro unavailable |
| STR-60 | §9.6 | 5xx/timeout → 3 retries at 1/5/15 min; PENDING_SYNC; the signed decision is never altered | MUST | FULL (time-scaled in the demo) | B09 | 6 | Explicit |
| STR-61 | §9.6 | Prescription statuses ISSUED … EXTENDED | NICE | SIMPLIFIED (mirrored from the mock) | B09 | 20-min | Low value |
| STR-62 | §9.6 | Auto-pull into a finalized protocol → notify only and offer a new check | SHOULD | SIMPLIFIED (mock feed) | B09 | 6 | Explicit, cheap |

### H. Modules 7–8 (Medium)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-63 | §7 #7 | Object colours green/yellow/red; filters by section, status and date; export of protocols to PDF, DOCX and XML | MUST | FULL | B08 | 1, 5, 6 | Explicit |
| STR-64 | §7 #8 | Admin adds, edits and deactivates normative references and updates min_value/max_value «без перекодирования» | MUST | FULL | B08, B03 | 7 | Explicit, great demo beat |

### I. Modules 9–11 (Medium)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-65 | §7 #9 | Audit of every inspector action (decision, reason, time); protocol versioning | MUST | FULL | B09 | 7 (audit entry) | Explicit |
| STR-66 | §7 #10 | Auto-generated weekly report for ML engineers: rejection stats and tuning recommendations | MUST | FULL | B06 | 8 | Explicit |
| STR-67 | §7 #11, §13 | Metrics, JSON logs, Prometheus + Grafana, ELK, alerts by e-mail and Telegram | MUST | FULL (ELK as an on-demand profile) | B09 | 10 | Explicit |

### J. Module 12 (High)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-68 | §7 #12 | Damaged files, unreadable formats, exceeded limits, integration failures and bad data are all handled | MUST | FULL | B10 | 2, 9 (self-test) | High priority |

### K–M. NFR, security, monitoring (§11–§13)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-69 | §11 | All 15 NFR rows measured and shown with hardware and page-format mix | MUST | FULL for rows 1–11 and 15; SIMPLIFIED for 12–14 (designed and drilled, not proven) | B09 | 11 (page «НФТ») | Credibility |
| STR-70 | §12.1–2 | Login/password; roles inspector, admin, ML engineer (+ supervisor, curator, approver) | MUST | FULL | B09 | 20-min | Explicit |
| STR-71 | §12.3 | Encryption at rest; TLS 1.3 in transit | MUST | SIMPLIFIED (TLS 1.3 at the edge; app-level AES-256-GCM for files and PII; encrypted volume documented) | B09 | Q&A | Laptop MVP |
| STR-72 | §12.4–5 | Audit with time, IP, action and object id; retention 90 d / 1 y | MUST | FULL | B09 | 7 | Explicit |
| STR-73 | §12.6–7 | 152-ФЗ measures; 187-ФЗ integrity | MUST | SIMPLIFIED (measures mapped; hash-chained audit; immutable finalized records) | B09 | Q&A | Documentable |
| STR-74 | §12.8 | Daily backups, 30-day retention | MUST | FULL | B09 | page «НФТ» (drill) | Explicit |
| STR-75 | §12.9 | IDS and DDoS protection | SHOULD | SIMPLIFIED (rate limits + IDS-lite; a certified IDS is out of scope) | B09 | Q&A | Out of hackathon reach |
| STR-76 | §12.11 | Antivirus before storage | MUST | FULL (ClamAV, fail-closed) | B01, B09 | 9 (EICAR) | Explicit |
| STR-77 | §13.8 | Daily hash integrity check | MUST | FULL | B09 | self-test | Explicit |

### N. Quality acceptance (§14)
| ID | ТЗ ref | Requirement | Prio | MVP | Owner | Proof | Why |
|---|---|---|---|---|---|---|---|
| STR-78 | §14.2 | Every result carries dataset_version, matrix_version, model_version and input_manifest_hash | MUST | FULL | B04 | 3 | Explicit |
| STR-79 | §14 | Output in СХЕМА GOLD format plus a batch mode so the organizers can score the hidden test | MUST | FULL | B04, B06 | handover | **Top scoring lever** |
| STR-80 | §14.3 | Metrics with n, coverage/abstention and 95 % CI, per section and violation type | MUST | FULL | B06 | 11 (page «Качество») | Explicit |
| STR-81 | §14.2 | Correct handling of every hidden-test class: confirmed, negative, missing evidence, N/A, revision conflict | MUST | FULL | B01, B04 | DEMO-01 | Scored |

### O. Win-specific (not written in the ТЗ, required to win)
| ID | Requirement | Prio | MVP | Owner | Why |
|---|---|---|---|---|---|
| STR-82 | One-command run (`make demo` / `docker compose up`); offline; arm64 + amd64 images | MUST | FULL | AG-00 | The jury may run us |
| STR-83 | Synthetic data badged everywhere. Pilot materials used only inside the hackathon, in a private repo. No redacted text surfaced | MUST | FULL | AG-09 | Ethics and trust |
| STR-84 | «Соответствие ТЗ» traceability page generated from `@req`-tagged tests | SHOULD | FULL | AG-00, AG-09 | Converts claims to proof |
| STR-85 | Pilot scoreboard: 9/9 groups plus 3 ventilation findings reproduced on **clean copies**; IoU vs ПРИМЕРЫ bboxes | MUST | FULL | AG-09, B06 | "Same answer as your experts" |
| STR-86 | Internal hidden test frozen (SHA-256) before any tuning; separate style pack | MUST | FULL | AG-09 | Mirrors §14.2; honest numbers |
| STR-87 | 12-min script rehearsed 3× clean; snapshots S0–S5; backup clips | MUST | FULL | user, AG-09 | Demo reliability |
| STR-88 | Submission package: repo, Russian README, OpenAPI/AsyncAPI, ADRs, deck, video, user guides | MUST | FULL | AG-00, user | Formal requirement of hackathons |
| STR-89 | Organizer letter sent within 24 h; answers tracked | MUST | FULL | user | Unblocks R01 |
| STR-90 | Q&A prep sheet and drill | SHOULD | FULL | user | Defense quality |

---

## 3. Proposed design (strategy)

### 3.1 What the jury most likely evaluates, and how to maximize each dimension

**Assumed jury.**
- Мосгосстройнадзор inspectors and management (domain lens): statuses, evidence, false alarms, speed, protocol form.
- ДИТ Москвы or organizer technical experts (engineering lens): stack, API, integration, security, operability.
- Hackathon organizers: completeness and presentation.

The weights below are **estimates** until the organizers publish the criteria; getting the official «критерии оценки» is data need N1 (§8).

| # | Dimension | Est. weight | What they will look for | How we maximize | Proof artifact |
|---|---|---|---|---|---|
| J1 | **ТЗ compliance by module priority** | 25–35 % | All 12 modules present; High modules deep; statuses and names verbatim; nothing mandatory missing | Scorecard §2; never cut breadth; verbatim ТЗ strings (statuses, §9.1 error texts, §9.4 comments); «Соответствие ТЗ» page | Traceability page, 1-page handout |
| J2 | **Objective hidden-test quality (§14.3)** | 20–30 % (if run) | P/R/F1, FPR, localization, linkage, OCR CA/EM | §3.1.1 mechanics; precision-first; big-5 extractors; region bboxes; GOLD export; `inspector-eval` so they can score us in one command | GOLD JSONL/XLSX, eval report with CI |
| J3 | **Live demo on their documents** | 15–20 % | Works on the pilot pages; honest on gaps; no crash | Pilot per-object packages from clean copies; «Пилот 9/9» scoreboard; cold-start branch (§3.2.4) | Script §3.2 |
| J4 | **Verification UX** | 10–15 % | ≤ 3 clicks, ≤ 30 min, side-by-side bbox, speed, keyboard | Keyboard-first workspace; auto-advance; AI-prefilled reasons; live click and time counter; «УТ-1» usability report with 5 participants | Counter overlay, usability page |
| J5 | **Protocol quality and legal correctness** | 5–10 % | Form (Приложение 2), 5 tables, evidence cards, disclaimers, signature block | Template in the organizers' own «Графическая фиксация» style; watermark until finalization; printed handout | PDF/DOCX/XML exports |
| J6 | **Integration readiness** | 5–10 % | OpenAPI, РиН contract, retries, security, Docker | Redoc; rin-mock with the literal endpoints and fault modes; GOST signature; `docker compose` profiles; batch CLI | API docs, РиН demo |
| J7 | **Engineering quality** | 5–10 % | Architecture fidelity (React/Node/Python/RabbitMQ/Redis), tests, observability | Contract-first; CI gates; Grafana/Kibana; «Самопроверка»; «НФТ» page | Pages + repo |
| J8 | **Pitch, value, roadmap** | 5–10 % | Why it matters, what it saves, how it goes to production | Time-to-protocol and verification-time numbers; production path (CryptoPro, real РиН, ФСТЭК, HA) | Deck, Q&A sheet |

#### 3.1.1 Hidden-test scoring mechanics, and what they imply
From §14.1–14.3 and СХЕМА GOLD / МЕТРИКИ / ПРИМЕРЫ:

1. **The unit is the evidence_group.** A true positive needs «правильный параметр/тип расхождения и корректное доказательство». The strict reading is: same `matrix_code` (or rule), `file_id` and page exact, bbox IoU ≥ 0,50. The implications:
   - **Echo organizer `file_id`s exactly** (B01 found they never appear on the pages). Registry-first ingestion is the only reliable way.
   - **Page = PDF page index in the original file.** ПРИМЕРЫ «стр.19» refers to the original file's page, not the sheet number. Keep `sheet_no` separately.
   - **Region-level evidence boxes.** Expert boxes frame whole explication tables, room zones, change-log rows and tolerance-table blocks, often several per page. Emit a region box per evidence type (table bbox, zone bbox, row-band bbox) plus token boxes for the UI. Compute IoU on the union and tune this convention on the 27 pilot boxes (B02 T-LOC-01, B06 harness).
   - **Param codes.** Pilot groups carry no code, so our mapping (ALT79B/DOO25/SOSH25 → M-003; POL16 → M-011; UNDMS → M-044; OKT103 → M-054; vent → M-077/078/079; IZM12/LOS3A → rule codes) is a guess. Emit `alt_param_codes`, publish the mapping, and **ask** (letter Q4).
2. **Who is "positive"?** GOLD positives are CONFIRMED_VIOLATION (inspector-only), while the system can only emit CANDIDATE. The scorer most likely compares our CANDIDATE/NEGATIVE_VERIFIED with GOLD CONFIRMED/NEGATIVE. Always emit a full card on CANDIDATE, and **ask** (Q2).
3. **Non-violation classes are in the test** (MISSING_EVIDENCE, NOT_APPLICABLE, revision conflict). If the organizers score status accuracy, fail-visible behaviour earns points directly. FPR explicitly includes «случаи с устаревшей редакцией», so the revision resolver quality is scored.
4. **All thresholds are mandatory.** Plan the operating point to satisfy P ≥ 0,90 and FPR ≤ 0,10 first, then push recall through breadth, not looser thresholds.
5. **Recall levers, ordered by yield on pilot-like data:**
   - explication and room-level diffs (5/9 pilot groups);
   - RD change-log mining as corroboration (UNDMS, LOS3A);
   - ИД tolerance tables (OKT103);
   - layer stacks (UNDMS);
   - ТЭП/specification tables (ТЗ examples KR-55/AR-41/PZ-01);
   - the router plus evidenced auto-promotion of room-level changes to CANDIDATE (B07 D1/D2). The pilot contains no SUSPICION, so these must surface as CANDIDATE.
6. **Leakage hygiene.** Never tune on the internal hidden test. Mark hidden-test runs `purpose=EVALUATION` and add their hashes to a blocklist (B10 E-D9).
7. **Deploy `rules-baseline` for hidden-test runs** unless the internal hidden test shows the trained bundle is better (decision U6). A verifier trained on synthetic data can suppress real positives.

#### 3.1.2 Hidden-test runbook (rehearsed at T-3)
1. `docker compose --profile core --profile eval up -d` on the organizers' machine, or ours if they hand over data.
2. `inspector-batch run --input /data/hidden --registry auto --purpose EVALUATION --out /data/out`. This takes a directory plus a registry (or builds a draft registry from stamps and marks it as such). Objects run in parallel, one process per object.
3. Outputs:
   - `predictions.gold.jsonl` and `.xlsx`: СХЕМА GOLD columns, ПРИМЕРЫ notation column, `alt_param_codes`;
   - protocol JSON/PDF per object;
   - `run_manifest.json` with every version and `input_manifest_hash`;
   - a SHA-256 manifest of the inputs.
4. Optional: `inspector-eval run --gold their_gold --pred predictions.gold.jsonl --gold-sha256 …` gives the report with n, CI and a verdict.
5. Time budget: text-layer PDFs take seconds per page; scans take about 1,1 s per A4 page on 12 CPU cores (B02). Publish a per-object runtime estimate in the README.

### 3.2 The killer demo script (12:00)

#### 3.2.1 Pre-staging (T-30 min before the slot)
- `make demo-reset STAGE=S0` restores a snapshot where **every finding was produced by the real pipeline and every decision was made through the API** (audited). No hand-inserted rows.
- The S0 dashboard has 12 objects:
  - 9 pilot objects plus АНО/150321 (ventilation);
  - **ДЕМО-01** «Школа на 550 мест (синтетический объект)» in VERIFYING, with ID_PARTIAL «5 из 15», one КЖ revision conflict and one pending candidate;
  - **ДЕМО-02** «Жилой дом 15 этажей (синтетический)», used for the hypotheses;
  - ALT79B is present as an object but has no process yet (it is uploaded live).
- Pilot expert labels are applied by a `pilot-expert` user through the API: OKT103 is CONFIRMED_VIOLATION (🔴) and POL17 is NEGATIVE_VERIFIED (🟢).
- ML state:
  - `gold-1.0.0` released;
  - `m-1.0.0` deployed;
  - `m-1.1.0` (good) and `m-1.1.1-bad` pre-trained with gate results computed;
  - week-1 weekly report present.
- Windows and tabs:
  - (1) Inspector (browser profile A);
  - (2) Supervisor/Admin (profile B);
  - (3) ML approver (profile C);
  - (4) terminal with prepared `curl` commands;
  - (5) rin-mock UI;
  - (6) Grafana;
  - (7) Kibana;
  - (8) Mailpit;
  - (9) Telegram desktop.

  Session TTL is 2 h in the demo profile. Resolution is 1920×1080 and the UI font is scaled for the projector.
- `DEMO_TIME_SCALE=60` with a visible banner «Время ускорено ×60 (демо)». No internet needed.
- **Two people:** the user narrates, and an operator drives the UI with hotkeys. If there is only one person, use the 7-minute variant.

#### 3.2.2 Minute-by-minute (what is said is in Russian because it is spoken to the jury)

| Time | Screen | Action | Key line (RU) | ТЗ proven | Fallback |
|---|---|---|---|---|---|
| 0:00–0:40 | Dashboard | Show 12 objects: OKT103 🔴, POL17 🟢, others 🟡; hover tooltips; filter «Раздел: АР» | «Это ваши пилотные объекты. Красный — только после решения инспектора; уровень риска цвет не меняет.» | §7 #7, §9.2 risk ≠ violation | Screenshot |
| 0:40–2:00 | Upload wizard + terminal | Drop ALT79B ПД (стр.19–20), РД (стр.4–5), `registry.csv` **plus** the organizers' `Комплект_предметной_разметки.pdf`, a `.dwg` and `broken.pdf`. The three bad files are rejected inline with the ТЗ wording («Превышен максимальный размер файла 50 МБ», «Формат не поддерживается. Допустимые: PDF, DOCX, XML», «Файл повреждён…»). Start → 202 with `process_id`. In the terminal: `curl …/processes/{id}/status` shows PARSING → READY (pull); one invalid request → 400 problem+json. Bell: «Протокол готов» | «Даже ваш собственный файл 51,49 МиБ мы обязаны отклонить — лимит ТЗ 50 МБ.» | §1.3, §1.4, §9.1 errors, registry | S1 snapshot + clip |
| 2:00–3:30 | Protocol ALT79B v1 | Header: matrix/dataset/model versions and input_manifest_hash. «Статус загрузки» per stage; «Тип проверки» (PARTIALLY_LOADED, base PD_RD_ONLY). The five tables. **M-002 → NEGATIVE_VERIFIED (+0,49 % < 1 %)** while **M-003 → CANDIDATE** (№23 «Помещение» → «Комната отдыха»; rooms 18–21). Table (5): **SUSPICION «Σ экспликации ПД 2795,04 м² ≠ итог 2797,27 м²»**. Coverage of 132: NOT_APPLICABLE with basis, MISSING_EVIDENCE for ИД | «Сверка только ТЭП пропустила бы все три пилотные находки по площадям. А вот расхождение, которого нет в экспертной разметке.» | §9.2 alg.1–4, §9.5, §14.2 versions | S1 |
| 3:30–4:00 | Verification (ALT79B) | The candidate opens already zoomed: ПД (blue) and РД (red) side by side. `C`, `Enter` → CONFIRMED; overlay «2 действия · 9 с»; the next card opens automatically | «Два действия. Лимит ТЗ — три клика.» | §9.3 alg.1–2, usability | Clip |
| 4:00–4:35 | Verification (UNDMS) | «Отклонить → Согласованное изменение», citing the РД «Лист регистрации изменений». **The AI disagrees**: CLARIFICATION_REQUIRED plus a Dispute_Log row with the verbatim §9.4 text | «Запись в листе изменений — не согласование. Система не даст незаметно "закрыть" расхождение.» | §9.3, §9.4 comments | Clip |
| 4:35–5:00 | Verification (АНО vent) | Composite «местные отсосы 140/142/147/198/314» → `S` → split by rooms → atomic findings | «Статуса PARTIALLY_CONFIRMED нет — каждое расхождение решается отдельно.» | §9.3 atomic findings | Clip |
| 5:00–6:00 | ДЕМО-01 | Table 1б: КЖ has two APPROVED revisions without a link → one click on «ред. 2 (основание: штамп „В производство работ“)». MISSING_EVIDENCE tab: drop the 10 missing ИД files → incremental v2 in < 1 min → «Решения сохранены: 12 из 12» → new chain candidate KR-55 «В30 (ПД) → В25 (РД ред.2, АОСР)» → confirm | «Дозагрузка без сброса верификации; пересчитаны только затронутые параметры.» | §9.1 revisions, §9.2 incremental, §9.3 alg.3 | S2 snapshot |
| 6:00–6:50 | Finalization | «Завершить» with 1 pending → blocked, with jump links. Process it → preview «В ИАИС „РиН“ будет передано: k подтверждённых + версии + реестр» → sign (ЭП, демо) → PROTOCOL_FINALIZED. Try an upload → 423 «…создайте новую проверку». Open the PDF (organizers' style with blue/red frames and «Вывод»), DOCX and XML (valid against the XSD) | «Форма протокола — в визуальном языке вашей „Графической фиксации“.» | §9.3 alg.4–5, §7 #7 exports | S3 |
| 6:50–7:40 | rin-mock + dashboard | The mock is pre-set to 503×2 → «Ожидает синхронизации (PENDING_SYNC)», attempt timeline 1/5/15 (scaled) → «Передано». Mock UI: payload holds only CONFIRMED records plus versions plus registry; «Подпись ГОСТ Р 34.10-2012: действительна». Dashboard: ДЕМО-01 turns 🔴. Mock pushes new docs for the finalized object → notification only plus «Создать новую проверку» | «Сбой РиН не меняет подписанное решение.» | §9.6 | Clip |
| 7:40–8:40 | Admin (profile B) | **Start the «Самопроверка» and k6 in the background.** Матрица → M-002: trigger 1 % → 0,4 % with a reason → «Оценить влияние: 1 находка сменит статус» → publish v+1 → audit before/after with IP → «Перепроверить» ALT79B → v2 header shows the new matrix_version; M-002 is now CANDIDATE | «Порог изменён без программиста — версия матрицы фиксируется в протоколе.» | §7 #8, §7 #9, §9.2 alg.1 | S4 |
| 8:40–9:45 | ML (profile C) | Curation queue (ДЕМО-01 items after finalization) → `gold-1.1.0` (object split, SHA-256, frozen test hash unchanged) → `m-1.1.0` gate: all §14.3 rows PASS with n and CI, ΔRecall per category ≥ −2 pp → re-auth and sign → deploy. `m-1.1.1-bad`: «Recall КР −6,7 п.п. — FAIL», «Утвердить» disabled. Rollback button. Weekly report PDF plus the e-mail in Mailpit. Badge «Синтетические данные» | «Модель не публикуется без приёмки и подписи ответственного; откат — в один клик.» | §9.4, §7 #10 | S5 |
| 9:45–10:40 | Самопроверка | «62 из 62 — PASS · 1 мин 48 с», with the coverage matrix ТЗ → scenarios → codes → tests. Click the timeout row → «Повторная попытка 1 из 2, 2 из 2 → администратор уведомлён» → Telegram message. EICAR row → «угроза, файл не сохранён» | «Все отрицательные сценарии ТЗ — проверяются вживую.» | §9.1 errors, §7 #12, §12.11 | Pre-run report |
| 10:40–11:25 | Grafana + Kibana + Telegram | Grafana «Обзор сервиса»: 100 sessions (k6), p95 ≈ tens of ms under the 200 ms line, RabbitMQ queue depth, CPU per service; alert «CPU > 80 %» (demo-scaled `for:`) in Telegram and e-mail. Kibana: paste one `request_id` → api → worker → ml → rin | «Метрики, логи и алерты — как в разделе 13.» | §11 #10–11, §13 | Screenshots |
| 11:25–12:00 | «Соответствие ТЗ» | 12/12 modules; N/N clauses mapped; tests green. «НФТ» table with 15 rows on M2 Max. «Пилот: 9/9 групп, IoU ≥ 0,5». Internal hidden-test metrics with CI (synthetic badge) and the §14.1 caveat | «Разворачивается одной командой, работает в закрытом контуре без интернета.» | §11, §14 | Handout |

Background jobs, started at 7:40 from the admin window: the Tier-1 self-test (≈ 1:48) and k6 with 100 VUs for 4 minutes. The CPU-stress burst runs on a 1-CPU-limited helper container from 9:45 so the alert fires by about 10:20 without starving the UI.

#### 3.2.3 Variants
- **7-minute core** (single presenter): 0:00–0:30 dashboard; 0:30–1:30 upload + rejections + pull; 1:30–2:45 protocol (M-002 vs M-003 + Σ suspicion); 2:45–3:45 verification (confirm + AI dispute); 3:45–5:00 ДЕМО-01 incremental + finalize + РиН retry; 5:00–5:45 threshold change without recoding; 5:45–7:00 «Самопроверка» + «Соответствие ТЗ» (ML and monitoring shown as tiles on that page).
- **20-minute technical deep dive** (if the jury asks for more): the 12-minute script plus:
  - the registry wizard auto-filled from stamps;
  - the OKT103 200-dpi scan with the handwriting zone ABSTAIN and «реквизиты: подпись ✓, печать ✓»;
  - rotated/CropBox fixtures with pixel-exact overlays;
  - supervisor un-finalization with a reason;
  - the audit chain tamper check;
  - Normative_Base with a future `effective_from`;
  - a Logical_Rules dry-run («этажей > 10 → лифт» on ДЕМО-02);
  - the backup/restore drill output;
  - `inspector-eval` in the terminal.
- **3-minute video** (submission): problem (20 s) → upload → protocol → verify → finalize → РиН (80 s) → threshold + ML gate (40 s) → self-test + monitoring (25 s) → compliance + call to action (15 s).

#### 3.2.4 Branch: "the jury brings its own documents"
1. Check the sizes. If any file is > 50 МБ, the service rejects it (ТЗ). Offer the offline «Подготовка комплекта» helper (differentiator D15): it splits by document and sheets and drafts a registry. It is outside the service and does not break the limit.
2. Upload without a registry → banner «CLARIFICATION_REQUIRED — реестр не приложен» → «Мастер реестра» pre-filled from title blocks (stage, шифр, sheet, revision). The jury states which files are approved → confirm → start.
3. Expect PARTIALLY_LOADED, many MISSING_EVIDENCE / NOT_APPLICABLE with basis, and candidates where explications or specifications exist. Talk track: «Система честно показывает, чего не хватает для вывода, и ничего не выдумывает.»
4. Time box: 3–5 minutes. Rehearse this twice with internal "unseen" packages (§3.4.4).

### 3.3 Differentiators beyond the letter of the ТЗ (cheap but impressive)

| # | Differentiator | Cost | Why it impresses | Owner |
|---|---|---|---|---|
| D1 | **"Found what your experts didn't mark"**: ALT79B Σ 2795,04 vs «итог» 2797,27 (verified) via rule HR-LOG-005 | S | Domain jurors check it on the spot | B07 |
| D2 | **"Same answer as your experts"**: pilot scoreboard, 9/9 statuses plus IoU vs ПРИМЕРЫ bboxes, computed on **clean copies** | S–M (harness exists) | Instant credibility | B06, AG-09 |
| D3 | **Protocol in the organizers' own «Графическая фиксация нарушений» style**: blue ПД / red РД frames, «Вывод» box, their disclaimer | S (template) | Looks like their own work product | B04 |
| D4 | **Live click and time counter overlay** in verification | S | Proves ≤ 3 clicks and ≤ 30 min instead of claiming it | B05 |
| D5 | Keyboard-first verification with auto-advance and AI-prefilled reason and comment | in plan | Inspectors feel the speed | B05 |
| D6 | **«Соответствие ТЗ» traceability page** (clause → requirement → test → last result), generated from `@req` tags | M | The jury can self-audit | AG-00, AG-09 |
| D7 | **«Самопроверка»**: about 60 negative scenarios live in < 2 min | M | Memorable proof of Module 12 | B10 |
| D8 | **«НФТ §11» page** with all 15 rows measured, hardware stated | S | Few teams measure NFRs | B09 |
| D9 | `inspector-eval` + `inspector-batch` + GOLD export: "score us on your hidden test in one command" | in B06 plan | Removes friction for the evaluators | B06 |
| D10 | M-002 vs M-003 contrast: "trigger-only sverka misses all three pilot area findings" | 0 | Shows domain depth | B03, B04 |
| D11 | Change-log intelligence: RD «Лист регистрации изменений» used as supporting evidence, **not** treated as an approved change; the AI disputes a rejection that relies on it | S–M | Precisely the inspector's legal logic | B04, B05 |
| D12 | Real GOST R 34.10-2012 / Streebog signatures on the РиН payload and the finalization seal (not qualified; CryptoPro swap documented) | M | Credible path to УКЭП | B09 |
| D13 | Closed contour: no runtime internet, models and fonts vendored, CPU-only laptop | S | 152-ФЗ story; works in any venue | AG-00 |
| D14 | Explainable decision trace per parameter in Russian (why N/A, why NOT_COMPARABLE) | S | Trust, not a black box | B04 |
| D15 | Offline «Подготовка комплекта» helper (split > 50 МБ PDFs, draft registry) | S | Solves the organizers' own 51,49 MiB problem without breaking the ТЗ | AG-09 |
| D16 | Organizers' kit rejected live with the ТЗ wording | 0 | Letter-of-ТЗ proof | B01, B10 |
| D17 | «Интерпретации ТЗ» page: 20+ contradictions found and resolved (status naming, DWG, MiniLM, 50 МБ, PARSING vs incremental, …) | S (docs) | Signals rigor to the technical jury | AG-00 |
| D18 | Printed handout: finalized protocol (ДЕМО-01) + a one-page ТЗ compliance matrix | S | Inspectors read paper | user |
| D19 | Time-to-value numbers: "протокол по 132 параметрам за N мин; медиана верификации M мин" (measured) | S | Business value for the pitch | B09, B05 |

### 3.4 Demo dataset plan

#### 3.4.1 Principles (legal and ethical)
1. **Pilot materials** (`Комплект_предметной_разметки*.pdf`, matrix, Перечень) are used **only inside the hackathon**. Keep them in a private repo or outside git (a local path mounted into compose). **Never publish them** in public videos or repos. They contain real addresses and a law-enforcement building (UNDMS «здание МВД»). Public-facing material uses ДЕМО-01/02 only.
2. **Respect redactions.** The white Ink strokes hide object names and signatures, but the text layer underneath survives (B02, B06). The sanitizer must drop occluded text from extraction, UI, exports and logs. There is a test (grep over API responses and exports for known redacted strings).
3. **Clean copies as input, overlay as GOLD only.** Truncate the ReportLab overlay at the tail of each page's content stream (B06). Otherwise the system "reads the answer", which a technical juror can spot.
4. **Synthetic documents never impersonate real parties.**
   - Use fictional organisations («ООО „Проект-Демо“»), fictional permit numbers prefixed «ДЕМО-», and generic names («Иванов И.И.»).
   - No real logos, stamps or signatures. Stamps render as «ОБРАЗЕЦ».
   - A margin watermark «СИНТЕТИЧЕСКИЙ ДОКУМЕНТ — ДЛЯ ДЕМОНСТРАЦИИ» sits outside title blocks and evidence zones.
   - 344/пр form structures (АОСР) are public templates, filled with synthetic content.
5. **Normative documents:** cite numbers and clauses with confidence badges; do not embed full texts of paid standards.
6. **Generated by the pipeline, not seeded.** Every finding shown was computed from documents, and every decision was made through the API, which the audit trail proves.
7. **Badging.** `objects.source_type ∈ {PILOT, SYNTHETIC, REAL, SELFTEST}` drives a visible badge. Metrics are always split into pilot, synthetic-internal-test and OCR bench, each with n and CI.

#### 3.4.2 Layer A — pilot-derived packages (per object; built by `tools/demo-data pilot`)
Each object gets:
- per-document PDFs **padded to the original page index**, so page 19 really is PDF page 19 (placeholder pages are marked «Лист не предоставлен в пилотной выборке»);
- a hand-authored registry with the organizers' `file_id`s, approval statuses marked `assumed=true`, and `sheet_page_range`;
- GOLD from ПРИМЕРЫ cross-checked against the overlay rectangles (IoU ≥ 0,99);
- the expected statuses.

| Object | Pilot pages → files (original page) | Expected result (our mapping) | Demo use |
|---|---|---|---|
| ALT79B | p2–3 → ПД `ALT79B-000015` стр.19–20; p4–5 → РД `ALT79B-000077` стр.4–5 | M-003 CANDIDATE (function and area); M-002 NEGATIVE (+0,49 %); SUSPICION Σ 2795,04 ≠ 2797,27 | Live upload (step 2–4a) |
| UNDMS | p6 → ПД `UNDMS-000214` стр.16; p7–8 → РД `UNDMS-000252` стр.10, стр.4 (change sheet) | M-044 LAYER_REMOVED (6 mm armored sheet); change-log row as supporting evidence; approved_change_ref NONE | AI dispute (4b) |
| IZM12 | p9 → РД `IZM12-000064` стр.4 (text drawn as outlines → OCR); p10 → ИД `IZM12-000007` стр.15 | Rule HR-LOG-007 (ИД works without an РД basis) → CANDIDATE via the router | 20-min variant |
| LOS3A | p11 → ПД `LOS3A-000009` стр.41; p12–13 → РД `LOS3A-000069` стр.15, стр.8 (change log) | Door moved (change log + configuration) → CANDIDATE | Dashboard 🟡 |
| OKT103 | p14 → ИД `OKT103-000099` стр.1 (200-dpi scan, handwriting, seal) | M-054 TOLERANCE_EXCEEDED; handwriting zone ABSTAIN; LOW_DPI; pilot-expert CONFIRMED | Dashboard 🔴; 20-min OCR |
| POL16 | p15 → ПД `POL16-000035` стр.62; p16 → РД `POL16-000136` стр.21 | M-011 (alt M-003) CANDIDATE | Dashboard 🟡 |
| DOO25 | p17 → ПД `DOO25-000875` стр.27; p18 → РД `DOO25-001733` стр.12 | M-003 CANDIDATE (пищеблок 135–150) | Dashboard 🟡 |
| SOSH25 | p19 → ПД `SOSH25-003562` стр.49; p20 → РД `SOSH25-003642` стр.34 | M-003.b ELEMENT_ADDED 1.109, 18,2 м² | Dashboard 🟡 |
| POL17 | p21–22 → ПД `POL17-000031` стр.26–27; p23–24 → РД `POL17-000096` стр.7–8 | NEGATIVE_VERIFIED; 0 candidates (FP guard); pilot-expert NEGATIVE | Dashboard 🟢 |
| АНО/150321 | 6-page «пояснения» (raster crops; vector originals requested) | M-079 / M-077 / M-078 CANDIDATEs; composite to split | Split demo (4c) |

Also keep the **unsplit organizers' kit** as a negative fixture (FILE_TOO_LARGE).

#### 3.4.3 Layer B — synthetic hero objects (same generator, deterministic seed)
**ДЕМО-01 «Школа на 550 мест (синтетический объект)»** is engineered to match the «УТ-1» usability benchmark (132 params evaluated, 14 true violations incl. 1 composite, 5 false-positive traps, 1 revision conflict, 6 MISSING_EVIDENCE, 5 NOT_APPLICABLE, 2 SUSPICION). One object then serves three purposes: the hero demo, the mandatory usability test and a §14.2 class showcase.

| Stage | Files (file_id `DEMO01-000nnn`) | Planted content | §14.2 class / param |
|---|---|---|---|
| ПД | ПЗ (DOCX) with ТЭП; ПЗ XML (Минстрой-like) with ТЭП | M-001/M-002/M-007 values; «газоснабжение не предусмотрено»; «снос не предусмотрен» | NOT_APPLICABLE with basis (M-018, M-090…M-097); XML/DOCX inputs |
| ПД | АР rev 0 (APPROVED) and АР «Корректировка №1» rev 1 (APPROVED, predecessor = rev 0) | Rev 0 differs from РД; rev 1 matches РД | **Outdated-revision trap** → must be NEGATIVE (FPR on outdated) |
| ПД | КР spec (B30 W6 F150, A500С); ППМ (doors EI 60); ИОС4 ОВ; ОДИ | Reference values | Baselines |
| РД | АР (FOR_CONSTRUCTION, «В производство работ» stamp) | Evacuation door 0,9 → 0,8 м (AR-41 = M-041); room function «Техническое» → «Склад ГСМ»; a zone with 3 changed rooms (composite) | CANDIDATE; SEMANTIC_DISSONANCE; split |
| РД | КЖ rev 1 and rev 2, **both APPROVED, no link** | rev 2 B25 | **Revision conflict** → CLARIFICATION_REQUIRED → after resolution, KR-55 CANDIDATE |
| РД | ППМ doors EI 30 | Ordinal downgrade | CANDIDATE (M-069 family) |
| РД | ЭОМ spec identical; ТЭП 2797,27 vs 2797,3 (rounding) | — | NEGATIVE_VERIFIED groups (rounding tolerance) |
| РД | A deviation covered by the ПД «Корректировка №1» plus a registry change document | — | NEGATIVE with approved_change_ref |
| ИД | АОСР бетонирование (DOCX, 344/пр structure): B25 | Chains ПД B30 → РД B25 → ИД B25 | FULL-scenario 3-array finding |
| ИД | АОСР армирование (XML) | — | XML ИД |
| ИД | Исполнительная геодезическая схема: 300-dpi scan, **Rotate=90, offset CropBox**, tolerance table exceeded | M-054 | Rotation normalization proof |
| ИД | Журнал бетонных работ: scan with a handwriting zone | — | ABSTAIN / LOW_QUALITY |
| ИД | One unreadable 100-dpi blurred page | — | NOT_COMPARABLE |
| Registry | Declares 15 ИД files; the first upload has 5 | «5 из 15» | ID_PARTIAL → PARTIALLY_LOADED → FULL after re-upload; MISSING_EVIDENCE for undeclared CORE items |

**ДЕМО-02 «Жилой дом 15 этажей (синтетический)»** is a small package of 5–6 files for Module 5. It reproduces the ТЗ examples verbatim:
- no lift shaft in РД with 15 floors → LOGICAL_ANALYSIS, with the exact JSON from §9.5;
- «Техническое» → «Склад ГСМ» → SEMANTIC_DISSONANCE;
- room height 2,4 м vs 2,5 м → NORMATIVE_ANALYSIS;
- concrete consumption −20 % → ML_PATTERN_ANALYSIS.

#### 3.4.4 Layer C — ML loop corpus and internal hidden test
- **Training/validation corpus:** about 150 synthetic objects in about 130 object groups (B06 §3.12), including rotated and cropped pages, scan noise, DOCX/XML variants, header synonyms and unit variants. Every file carries `source_type=SYNTHETIC`. A "simulated inspector" drives the real API. At T-7 the corpus can drop to 50 objects.
- **Internal hidden test:** 25 objects generated with a **separate style pack** (different fonts, table layouts, header synonyms and phrasing) authored by a different agent from the extractor developers. It is **frozen with a SHA-256 manifest at T-12, before any tuning**, and never inspected item-by-item by developers (aggregate metrics only). This mirrors §14.2 and gives honest numbers for the «Качество» page.
- **Unseen-document rehearsal:** the Data agent repackages pilot pages without registries, with different file names and in merged/split variants, to rehearse the cold-start branch (§3.2.4).

#### 3.4.5 Layer D — negative fixtures (B10 `negfixtures`)
- Format and size: DWG; 0-byte file; 50 MiB exactly and 50 MiB + 1 byte; a 5 × 45 MiB package.
- Damaged PDFs: truncated at 70–97 %; bit-flipped content stream.
- Encrypted PDF.
- EICAR in plain form, in a ZIP and inside a PDF.
- XXE XML; zip-bomb DOCX; HTML renamed to `.pdf`; a PDF with JavaScript.
- Duplicate bytes; a file belonging to another object.
- Registry defects: hash mismatch, a declared-but-missing file, a foreign-object row.

These feed the «Самопроверка» and the upload step of the demo.

#### 3.4.6 Layer E — OCR and key-field benchmark
- DS-A: vector pilot pages rendered at 300 dpi with degradations. The ground truth is the text layer.
- DS-C: key fields from title blocks.
- DS-D: handwriting and seal zones (OKT103 p.14 plus synthetic).
- Human verification of the real-scan labels takes about 3 hours (B02 decision; owner: the user or a teammate).

#### 3.4.7 One pipeline, not eight
Eight block tasks build overlapping datasets: B01-W21, B04-T14, B06-T04/T05, B08-T29, VT-16, B10-T22, MTX-T18 and part of HYP-T16. Consolidate them into **one** `tools/demo-data` package owned by AG-09 (Data & Demo):
- `pilot/` (split, pad, clean, sanitize, GOLD, registries);
- `synth/` (generator, style packs, hero configs, corpus, internal hidden test);
- `negfixtures/`;
- `manifests/` (SHA-256).

Blocks consume the artifacts and never build their own. This saves an estimated 6–8 agent-days and removes format drift.

### 3.5 Demo control plane (technical design; owned by AG-09 with AG-00)

**Components**
- `tools/demo-data` (Python 3.12, uv): ReportLab 4.x (BSD) for PDFs with ГОСТ Р 21.101 stamps; python-docx 1.x and docxtpl for DOCX; lxml for XML; Faker `ru_RU` restricted to fictional entities; PyMuPDF for Rotate/CropBox manipulation and page padding (AGPL, acceptable for the hackathon as B02 notes); pikepdf for overlay truncation; Pillow and OpenCV-headless for scan noise; a deterministic seed.
- `tools/demo-control` (Makefile + Python):

  | Command | What it does |
  |---|---|
  | `make demo-seed` | Runs every demo package through the **real pipeline** via the public API, applies scripted decisions through the API (simulated inspector / pilot-expert / curator), trains the good and bad bundles |
  | `make demo-snapshot STAGE=Sx` | `pg_dump -Fc` + storage tarball + Redis RDB + RabbitMQ definitions |
  | `make demo-reset STAGE=Sx` | Restores Sx in ≤ 60 s |
  | `make demo-check` | Runs the Playwright "jury path" E2E |

- The **compliance generator** collects `@req` tags from the Vitest/pytest/Playwright JUnit outputs, joins them with `compliance/requirements.yaml` (STR + ARC + block IDs → ТЗ clause) and writes `compliance.json`, which is served read-only.

**Demo stage machine (snapshots)**
- S0: baseline (dashboard seeded; ДЕМО-01 in VERIFYING; ALT79B without a process).
- S1: ALT79B READY.
- S2: after the verification beats and the ДЕМО-01 incremental update.
- S3: ДЕМО-01 FINALIZED and SYNCED.
- S4: matrix v+1 published and ALT79B rechecked.
- S5: `m-1.1.0` deployed.

Any segment can be restarted from its predecessor snapshot.

**Data model additions** (minimal; they align with existing block tables):
- `objects.source_type` enum {PILOT, SYNTHETIC, REAL, SELFTEST}. This unifies B06 `source_type` with B10 `purpose`.
- `processes.purpose` enum {INSPECTION, EVALUATION, SELFTEST, DEMO_SEED}. EVALUATION and SELFTEST are excluded from dashboards, weekly stats and GOLD (B10 NS-K12).
- `compliance.json` is a build artifact, not a table. Traceability must not be editable at runtime.
- The overlay reads `ui_events` (owned by B05). `nfr_results` is owned by B09.

**REST endpoints** (OpenAPI 3.0.3, JSON; admin/auditor roles; absent in the `prod` profile where marked):

| Method | Path | Response sketch |
|---|---|---|
| GET | `/api/v1/admin/compliance` | `{generated_at, app_version, clauses:[{tz_ref, title_ru, requirements:[{id, block, prio, mvp, tests:[{id, status, last_run}]}]}], totals}` |
| GET | `/api/v1/admin/compliance/pilot-scoreboard` | `[{finding_id, expected_status, actual_status, param_expected, param_actual, file_page_match, iou_min, pass}]` |
| GET | `/api/v1/admin/quality/metrics` | `[{suite: PILOT/INTERNAL_HIDDEN/OCR_BENCH, source_type, n, metrics:{…, ci95}, coverage, abstention, verdict}]` |
| GET | `/api/v1/system/info` | `{app_version, versions:{matrix, model, dataset}, demo_time_scale, offline, hardware}` (drives the banner) |

`demo-reset` is **CLI-only**, with no HTTP endpoint, for safety.

**RabbitMQ:** no new exchanges. `demo-seed` uses only public APIs, which exercises the real queues.

**UI screens:**
- «Соответствие ТЗ» (clause tree with green/amber/red and waiver text);
- «Пилот: сверка с экспертной разметкой»;
- «Качество (§14.3)»;
- demo banner;
- the click/time counter overlay, toggled with `Ctrl+Shift+U` (built by B05);
- «НФТ §11» (B09) and «Самопроверка» (B10) are linked from the compliance page.

### 3.6 Submission package and pitch
**Submission checklist:**
- private repo with a README in Russian (1-command run, hardware, ports);
- `docker compose` profiles and offline image tarballs (arm64 + amd64);
- OpenAPI (Redoc) and AsyncAPI;
- rin-mock contract;
- ADRs, including «Интерпретации ТЗ»;
- user guides «Руководство инспектора», «администратора» and «ML-инженера»;
- the evaluation README (`inspector-batch`, `inspector-eval`);
- the deck (PDF), the 3-minute video and the handout.

**Deck (10 slides, Russian)**:
1. «Инспектор ИИ»: one-line value.
2. Problem: three arrays, 132 parameters, the cost of a missed deviation.
3. Solution flow: Загрузка → Сверка → Верификация → Финализация → РиН → Обучение.
4. Principles: evidence-first with bbox; fail-visible; only the inspector confirms; precision-first.
5. (Live demo.)
6. ТЗ compliance: 12/12 modules, traceability.
7. Quality: pilot 9/9 + metrics with CI + the §14.1 caveat.
8. NFR and security: §11 table, §12 measures, closed contour.
9. Integration and deployment: OpenAPI, РиН adapter, compose, CPU-only hardware, production path (CryptoPro, real РиН, ФСТЭК-certified AV/IDS, HA).
10. Effect and roadmap (measured time-to-protocol, verification median; pilot on a real archive).

**Q&A prep** (question in Russian, answer gist in English; drill each answer to ≤ 45 s):

| Question | Answer gist |
|---|---|
| «Почему не all-MiniLM-L6-v2?» | English-only; the ТЗ allows «совместимые аналоги»; our Russian benchmark: e5-small 34/40 top-1 at 8 ms vs 22/40 for multilingual MiniLM; switchable |
| «Что если нет реестра?» | CLARIFICATION_REQUIRED per the registry rules; the wizard pre-fills from stamps; a human confirms approvals; no conclusions before that |
| «Может ли ИИ сам подтвердить нарушение?» | No. DB constraint plus a single decision endpoint; CONFIRMED only by an inspector |
| «Как отличаете согласованное изменение?» | Registry approvals, revision chains and approved_change_ref; the change log is supporting evidence only; the AI disputes rejections based on it |
| «Метрики на 9 группах?» | Pilot reported with n and CI plus a frozen synthetic internal test; §14.1 quoted; `inspector-eval` ready for your hidden test |
| «Где обучение?» | Versioned bundle (calibrated verifier + thresholds + data-derived components); gate; four-eyes; rollback; shown on synthetic data, grows with finalized protocols |
| «152-ФЗ?» | Closed contour; no external calls; PII encryption; access audit; redactions respected; retention |
| «УКЭП?» | Pluggable signer; real GOST R 34.10-2012 today, not qualified; CryptoPro in production |
| «Железо?» | 12-core CPU laptop measured; no GPU; workers scale horizontally; §11 table |
| «Интеграция с РиН?» | OpenAPI contract with the literal ТЗ endpoints; adapter swap by config; retries and PENDING_SYNC |
| «Плохие сканы?» | Zone-level LOW_QUALITY/ABSTAIN; LOW_DPI; never a violation from unreadable data → NOT_COMPARABLE |
| «Почему кандидат при +0,49 %?» | Room function and area changed; the trigger drives priority; the per-parameter policy is admin-tunable |
| «DWG?» | Inputs are PDF/DOCX/XML per the ТЗ; DWG is rejected with a message; "чертёж" = PDF sheet |
| «500 страниц?» | Text layer first, OCR only for rasters; measured figures on the «НФТ» page |
| «Кто отменяет финализацию?» | Admin or supervisor, with a reason and re-authentication, audited; returns to VERIFICATION_COMPLETED; РиН receives the superseding version |
| «Почему статусы называются по-разному?» | The ТЗ has two naming schemes; we expose both with a fixed mapping |
| «Утечка скрытой выборки?» | `purpose=EVALUATION`, hash blocklist, object-level split, the trainer refuses |
| «Порог без программиста?» | Module 8, a versioned matrix, audit; shown live |
| «Линейные объекты?» | Different ПД composition (§3 note); out of MVP scope, stated in the interpretations page |
| «Что дальше?» | Pilot on a real archive; real РиН API; CryptoPro; certified AV/IDS; HA |

---

## 4. Interfaces with other blocks

### 4.1 What the strategy needs from each block (demo beats and dates)
| Block | Must deliver for the demo | By |
|---|---|---|
| B00 / AG-00 | `make demo`, compose profiles, a single global `DEMO_TIME_SCALE`, `@req` tag convention + compliance generator hook, snapshot-friendly storage, `system/info`, rulings in §4.2 | CP0 (T-13); compliance by T-6 |
| B01 | ТЗ-worded rejections (incl. the organizers' kit), registry CSV + wizard (basic grid by CP2, stamp pre-fill by CP3), revision conflict + one-click resolve, incremental upload without reset, `inspector-batch` ingest | CP1 happy path; CP2 rest |
| B02 | Text-layer explication extraction (ALT79B p.19/p.4), OKT103 tolerance table OCR with ABSTAIN zones, page-class badges, cache-hit metric, **region-level bbox convention** tuned on the 27 pilot boxes | CP1 (explications); CP2 (OCR) |
| B03 | Seeded 132 params with the per-param candidate policy, M-002/M-003 contrast, N/A bases, threshold publish through Module 8, confidence badges on references | CP1 (M-002/M-003); CP2 (all) |
| B04 | Five tables + sections, evidence card, pilot-style PDF, DOCX/XML, **GOLD export + ПРИМЕРЫ notation**, incremental update, pilot regression test | CP1 (JSON + basic PDF); CP2 (exports, incremental) |
| B05 | Workspace with viewer, `C/Enter` confirm, dispute flow, split, finalize/un-finalize, counter overlay, «УТ-1» | CP1 (confirm/finalize); CP2 (dispute/split); CP3 (usability) |
| B06 | `inspector-eval`, synthetic loop, good/bad pre-trained bundles, gate UI, weekly report + e-mail | CP2 (loop); CP3 (metrics page) |
| B07 | HR-LOG-005 Σ check, semantic dissonance on ALT79B, ДЕМО-02 suspicions, router + evidenced auto-promotion, table (5) | CP2 |
| B08 | Dashboard colours, filters, export buttons, admin matrix publish + impact preview, notifications bell | CP1 (dashboard); CP2 (admin) |
| B09 | rin-mock with fault modes, delivery retries, GOST signer, Grafana dashboard, Kibana trace, Telegram/e-mail alerts, «НФТ» page, k6 script | CP1 (mock happy path); CP2 (faults, monitoring); CP3 (НФТ) |
| B10 | errors.yaml + envelope, negfixtures, «Самопроверка» Tier-1 (≈ 60), chaos hooks in the demo profile | CP2 (≥ 30 scenarios); CP3 (60) |

### 4.2 Cross-block rulings needed before CP0 (conflicts found while consolidating)
| # | Conflict | Where | Recommended ruling |
|---|---|---|---|
| X-R1 | **Four different protocol/report renderers**: Playwright + docx-templates in Node (B04-T13); docxtpl + LibreOffice + lxml in Python (B08-T25); WeasyPrint (B06-T12); Gotenberg (B00) | B00, B04, B06, B08 | **One Python `render` worker**: Jinja2 → WeasyPrint for PDF (protocol + weekly report), docxtpl for DOCX, lxml + XSD for XML. Gotenberg/LibreOffice only for DOCX→PDF *input* renditions. Confirm with a 1-hour spike on an A4-landscape card with 2 thumbnails. Saves about 3 agent-days and one heavy runtime |
| X-R2 | **Embedding model**: B02 benchmarked multilingual-e5-small (34/40 top-1); B07 and B06 C4 reference multilingual MiniLM (22/40 in B02's test) | B02, B06, B07 | e5-small everywhere; MiniLM stays as a switchable baseline for the «совместимый аналог» narrative |
| X-R3 | **Evidence viewer built twice** (B05 VT-10/VT-11 and B08-T10 + B02-T16) | B02, B05, B08 | B05 owns the viewer and the tile service; B08 and B07 reuse the component |
| X-R4 | **Eight dataset builders** | B01, B03, B04, B05, B06, B07, B08, B10 | One `tools/demo-data` pipeline (AG-09), §3.4.7 |
| X-R5 | Error body shapes, conflicting codes (409 vs 423 for FINALIZED, etc.) | B00, B01, B05, B08 | B10 ruling: RFC 9457 + `code`; 423 PROTOCOL_FINALIZED; 409 PROCESS_BUSY |
| X-R6 | Incremental upload moves the process to PARSING (B01) vs an active-run sub-state (B00/B05) | B01 vs B00, B05 | Sub-state (B10 X1). Otherwise verification freezes on every re-upload, contradicting §9.3 п.3 |
| X-R7 | Candidate policy wording differs (B03 "strict numeric, any change for qualitative" vs B04 "per-param DEVIATION default") | B03, B04 | One per-param `candidate_policy` ∈ {TRIGGER, DEVIATION}: DEVIATION for configuration, room, layer and presence params; TRIGGER for normative numeric bounds; the trigger always drives risk |
| X-R8 | Scorer suppression of candidates into system NEGATIVE_VERIFIED (B06 D6 "suppress below τ") | B06 | **Off by default** for demo and hidden-test runs; the scorer ranks and sets risk only. Enable only if the internal hidden test shows P↑ with R not lower (decision U6) |
| X-R9 | UI kit: AntD 5 (B00) vs AntD 6.6 (B08, versions checked on npm) | B00, B08 | AntD 6 (B08) |
| X-R10 | Two rule evaluators (B03 rule DSL/JSONLogic and B07 Logical_Rules AST) | B03, B07 | JSONLogic for applicability and thresholds; **one** AST evaluator library shared by Logical_Rules and matrix sub-checks |
| X-R11 | Explication extraction built in four places (MTX-T08, B04-T07, HYP-T03/T06, B02-T07) | B02, B03, B04, B07 | One extractor in `inspector_docproc` (B02 owns); B03 owns the taxonomy; B04/B07 consume |
| X-R12 | Redis vs Valkey; MinIO vs encrypted fs; Mailpit vs MailHog | B00, B06, B09 | Follow B09: Valkey 8, encrypted fs by default with an S3 driver, Mailpit |
| X-R13 | Per-feature demo delays vs one `DEMO_TIME_SCALE` | B00, B09 | One global scale (B10 X11) |
| X-R14 | Auth/audit/compose/observability tasks duplicated between AG-00 (ARC-T09/T14/T19/T20) and B09 (PLT-T05–T08, T22–T24) | B00, B09 | AG-00 owns the skeleton (sessions, guards, compose, logging libs); B09 owns audit, security features, the monitoring profile and dashboards |

---

## 5. Top risks that could lose the hackathon, and mitigations

| ID | Risk | L | I | Early warning | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R01 | **Hidden-test output not scorable**: format, param codes, page numbering or bbox granularity differ from the organizers' scorer | M | Critical | No organizer answer by T-10; pilot scoreboard < 9/9 | Letter Q2–Q5 on day 1; GOLD columns verbatim + ПРИМЕРЫ notation + `alt_param_codes`; page = PDF index; region bboxes; `inspector-eval` mirrors МЕТРИКИ; pilot scoreboard as a CI gate; runbook rehearsal (§3.1.2) | B04, B06, AG-09 |
| R02 | **Integration collapse**: ~10 agents and 244 tasks; no end-to-end path on the day | M–H | Critical | CP1 golden thread missing at T-10; red CI for more than 1 day | CP0 freeze (T-13); golden thread by T-10; daily merge window; the jury-path Playwright E2E is a merge gate from CP1; feature flags; scope-cut levels (§10.4); velocity check at each CP | AG-00, user |
| R03 | **Recall < 0,80** on the hidden test | H | High | Internal hidden-test recall < 0,6 at CP2 | Invest in the big-5 extractors; router + evidenced auto-promotion; region boxes; breadth across the ТЭП/spec params; accept and explain honestly while P and FPR pass | B02, B03, B04, B07 |
| R04 | **Visible false positives in front of inspector-jurors** | M | High | POL17 produces > 0 candidates; raw graphic diff produces CANDIDATEs | Per-param policy; POL17 FP gate in CI; stale-revision invariant; NOT_COMPARABLE over guesses; raster graphic diff only as LOW SUSPICION; curated demo objects | B04, B07 |
| R05 | **Live demo breaks** (crash, slow step, hung queue, projector) | M | High | Any rehearsal needs manual intervention | Snapshots S0–S5 (reset ≤ 60 s); offline; warm caches; no heavy OCR live; pre-trained models; per-segment clips; 3 clean rehearsals; spare laptop or VM with the same snapshot | AG-09, user |
| R06 | **Jury supplies unknown documents** (no registry, > 50 МБ, scans) | M | M–H | Cold-start rehearsal fails | Branch §3.2.4 rehearsed twice; registry wizard; fail-visible statuses; «Подготовка комплекта» helper | B01, AG-09 |
| R07 | **Medium/Low infrastructure starves the High modules** (B09 alone plans ≤ 46,5 d; B08 ≤ 52 d) | M–H | High | High-module tasks behind while ELK/GOST/HA progress | Effort caps per module (§10.5); cut levels; time-box infra; reuse off-the-shelf configs | user, AG-00 |
| R08 | Synthetic data perceived as cheating | L–M | M | Jury asks «это заранее подготовлено?» | Badges; separate metrics; the pipeline-generated principle; show `make demo-seed` logs; pilot is always real | AG-09 |
| R09 | **Answer leakage from the pilot overlay** (extraction reads expert callouts) | M if forgotten | High (credibility) | Callout text appears in extracted_values | Clean copies + sanitizer + B02 T-VIS-01 test in CI; evaluate only on clean copies | B02, AG-09 |
| R10 | PII/sensitive exposure (redacted title blocks, УНДМС/МВД) | M | M–H | Redacted strings found by grep | Sanitizer; private repo; synthetic-only public materials; never zoom into title blocks in the demo | AG-09, B02 |
| R11 | Environment friction (no Docker, ClamAV arm64, no Tesseract `rus`, ELK RAM) | H at start | M | Day-1 installs not done | Install OrbStack and the brew deps on T-14; hybrid mode; ELK profile on demand; RAM budget (VM ≥ 10 CPU / 20 GB) | user, AG-00 |
| R12 | §11 OCR NFR fails on A0 rasters live | M | M | Benchmark > target | Text-layer first; measure on A4 (the acceptance premise); report the page mix; never OCR 500 pages live | B02, B09 |
| R13 | Wrong normative clause shown to expert jurors | M | M | Expert review not done by T-5 | Confidence badges and «требует проверки»; expert pass on about 40 demo references; no clause numbers in spoken lines unless verified | B03, user |
| R14 | Mandatory usability test (5 inspectors) not done | M | M | No participants booked by T-7 | Ask the organizers; recruit 5 proxies by T-7; sessions T-5…T-3; publish method + results | B05, user |
| R15 | Unknown deadline and judging criteria → misallocation | H now | High | — | Get the Положение/criteria and the schedule on day 1; the T-template adapts (§10.3) | user |
| R16 | Status-model confusion (two naming schemes) read as a deviation | M | M | Jury question | Show the ТЗ codes verbatim in tooltips; «Интерпретации ТЗ» page | B05, B08 |
| R17 | Presenter overload or timing overrun | M | M | Rehearsal > 12:30 | Two-person delivery; timer; 7-minute fallback; hotkeys; pre-opened tabs | user |
| R18 | "You trained nothing" ML skepticism | M | M | — | Honest bundle explanation; auditable loop; gate on labelled synthetic data; roadmap for real data | B06 |
| R19 | Приложение № 2 arrives late and differs | M | M | Arrives after T-6 | Template-driven renderer; reserve 1 day in T-5…T-3 for the swap | B04 |
| R20 | Scorer trained on synthetic data hurts hidden-test recall | M | High | Internal hidden-test recall drops vs baseline | U6: deploy `rules-baseline` for evaluation unless proven better; suppression off | B06 |

**Too complex / risky at strategy level, and the simplification that still meets the letter:**
- *Full live lifecycle including training in 12 minutes* → pre-trained bundles; the gate, approval and rollback are shown live (all real API calls).
- *Proving the §11 OCR throughput live* → recorded benchmark on the «НФТ» page with hardware and the page mix; live runs use vector pages.
- *Usability test with real inspectors* → 5 proxies with the published «УТ-1» method; the same tooling is ready for the official test.
- *Deep extraction for all 132 params* → about 35 deep profiles + generic; every param gets a definite, explained status.
- *Covering 12 modules in 12 minutes* → background jobs, pre-staged snapshots, two presenters, compliance page tiles for the rest.
- *Unknown evaluation infrastructure* → multi-arch images, offline tarballs, `inspector-batch`, documented runtime.

---

## 6. ТЗ contradictions and ambiguities that affect scoring

Put all of these on the «Интерпретации ТЗ» page. It turns ambiguity into evidence of rigor.

| # | Issue | Scoring effect | Recommended interpretation |
|---|---|---|---|
| C1 | GOLD positive = CONFIRMED_VIOLATION (inspector-only), while the system emits CANDIDATE | Defines what counts as TP | Emit CANDIDATE with a full card as the system prediction; ask (Q2) |
| C2 | Matrix triggers vs pilot labels: ALT79B +0,49 %, SOSH25 +0,29 %, DOO25 −0,29 % are marked CANDIDATE although M-002 says «> 1 %» | Recall on area/room changes | Per-param candidate policy (X-R7); the trigger drives risk; M-003 room-level diff |
| C3 | No param codes for out-of-matrix pilot findings (IZM12, LOS3A) or duplicate params (M-040/M-104 …) | TP needs the "правильный параметр" | Rule codes + `alt_param_codes`; report duplicates under both codes and count once; ask (Q4) |
| C4 | «стр.» = PDF page index or printed sheet number? | Localization metric | Page = PDF page index of the original file; `sheet_no` kept separately; pad pilot files to original indices |
| C5 | Several expert boxes per page; the ТЗ says «bbox/polygon» (singular) | IoU computation | Union of region boxes per role; report per-box too; ask (Q3) |
| C6 | 50 МБ limit vs the organizers' 51,49 MiB kit | Letter compliance | Reject (show it); per-document split files for the demo |
| C7 | Two status naming schemes (COMPLETED/FINALIZED vs VERIFICATION_COMPLETED/PROTOCOL_FINALIZED); §9.3 carries the title of §9.2 | Perceived deviation | Expose both with a fixed mapping; tooltips show the ТЗ codes |
| C8 | Приложение № 2 mandatory but missing | Protocol-form compliance | Our layout in the organizers' own «Графическая фиксация» language; swappable; request it (Q1) |
| C9 | Usability test "обязательное", no inspectors provided | J4 score | Proxies plus a formal request (Q8) |
| C10 | §11 #8 «CV-анализ одного чертежа (DWG)» vs PDF/DOCX/XML inputs | NFR interpretation | "Чертёж" = one PDF sheet; DWG rejected with a message |
| C11 | all-MiniLM-L6-v2 is English-only | Literal model name | e5-small as the «совместимый аналог», with the benchmark table shown |
| C12 | No registry → CLARIFICATION_REQUIRED blocks all conclusions | Live test with jury documents | Wizard-built registry lifts it after explicit human confirmation (B01 decision) |
| C13 | Who converts SUSPICION → CANDIDATE is unspecified; the pilot has no SUSPICION labels | Recall on room-level changes | Router + evidenced auto-promotion (complete card, confidence ≥ 0,8, promotable rule); switchable (B07 D1/D2) |
| C14 | NEGATIVE_VERIFIED emitted by both the system and the inspector | GOLD hygiene | `decided_by`; only inspector negatives become GOLD |
| C15 | Is GOLD exhaustive per object? | Precision counting | Conservative internal eval (unmatched = FP); ask (Q2) |
| C16 | Linear objects have a different ПД composition | Scope | Out of scope; stated |
| C17 | "Обязательная категория" for the Recall gate is undefined | Gate semantics | Sections + discrepancy types + HIGH aggregate (B06) |
| C18 | PARSING forbids verification, yet re-uploads happen during VERIFYING | UX and letter | Active-run sub-state; PARSING only for the initial run (X-R6) |

---

## 7. Decisions needed from the user

Ordered by urgency. ⚑ means needed on day 1.

| # | Question | Options | Recommendation | Impact |
|---|---|---|---|---|
| U1 ⚑ | Hackathon deadline, demo slot length, judging criteria, whether the jury runs our code / hidden-test logistics | provide / ask organizers | Send us the Положение and the schedule; ask the rest in the letter | Timeline (§10.3), demo variant, packaging |
| U2 ⚑ | LLM policy (152-ФЗ) | none / local (Ollama) / Russian cloud / foreign cloud | **No LLM in the critical path; deterministic templates.** An optional local adapter off by default; never a cloud LLM for documents | Reproducible metrics, clean 152-ФЗ story, offline demo |
| U3 ⚑ | Install OrbStack + `brew install tesseract-lang rabbitmq clamav mailpit toxiproxy` now | yes / later | **Yes, today** | Unblocks OCR (`rus`), AV, chaos, compose parity |
| U4 ⚑ | Candidate policy | trigger-only / any deviation / per-param | **Per-param** (X-R7) | Reproduces the 7 pilot CANDIDATEs while protecting precision |
| U5 | Auto-promotion SUSPICION → CANDIDATE | off / strict hybrid / aggressive | **Strict hybrid** (complete evidence + confidence ≥ 0,8 + promotable rule) | Recall on room-level changes |
| U6 | ML scorer suppression for hidden-test and demo runs | suppress below τ / rank only | **Rank only; deploy `rules-baseline` for evaluation** unless the internal hidden test proves the bundle better | Protects recall on unseen data |
| U7 | Use clearly badged synthetic data (hero objects, ML loop, УТ-1) | yes / no | **Yes** | Covers the §14.2 classes and the ML loop |
| U8 | Show the organizers' kit being rejected | yes / raise the limit | **Yes** (raising the limit breaks the ТЗ) | Letter-of-ТЗ proof |
| U9 ⚑ | Usability participants | organizers' inspectors / 5 proxies | Ask the organizers **and** recruit 5 proxies (civil/MEP engineers, 45 min each, T-5…T-3) | STR-46 |
| U10 | Domain expert for about 40 normative references (≈ 1 day) | you / a consultant / skip | A consultant or knowledgeable friend by T-5 | Avoids wrong clauses in front of experts |
| U11 | Presenter + operator | one / two people | **Two** (you narrate, one operator) | 12-minute feasibility |
| U12 | Demo hosting | laptop / RF cloud VM / both | **Laptop primary** (offline, M2 Max) + VM as backup if the venue allows | Reliability |
| U13 | Telegram bot token | real / mock | **Real bot** (cheap, visible); mock in CI | §13.7 visibility |
| U14 | Branding | neutral / Мосгосстройнадзор look | **Neutral «Инспектор ИИ»**, city-gov-like palette, **no official logos** | Avoids impersonation |
| U15 ⚑ | Approve sending the organizer letter (§8.2) | send / edit | **Send within 24 h** | R01, R14, C1–C5 |
| U16 | Team mapping: split AG-09 into *Data & Demo* and *QA & Negative* | yes / no | **Yes** | The dataset pipeline and demo control plane need a dedicated owner |
| U17 | Repo and data hygiene | public / private | **Private**; pilot data outside git (mounted path) | Legal |

---

## 8. Data needed — the organizer ask list

### 8.1 Prioritized asks
| # | What | Why | Fallback if never received |
|---|---|---|---|
| Q1 | **Приложение № 2** (sample protocol) | §9.2 makes the form mandatory | Our template in the organizers' «Графическая фиксация» style; 1-day swap reserved |
| Q2 | **Hidden-test protocol**: who runs what (our Docker/API vs data handed over), input format (files + registry format), output format (СХЕМА GOLD? JSONL/XLSX?), CANDIDATE vs CONFIRMED matching, GOLD exhaustiveness per object, time limits | Defines what scores | GOLD JSONL/XLSX + ПРИМЕРЫ notation + `inspector-batch`/`inspector-eval`; conservative assumptions documented |
| Q3 | Page numbering (PDF index vs sheet) and the multi-box IoU method | Localization metric | PDF index; union IoU; per-box reported too |
| Q4 | Param codes for out-of-matrix findings and duplicate params; the violation-type taxonomy | "Правильный параметр/тип" | Rule codes + `alt_param_codes`; our taxonomy (B03 §3.11) |
| Q5 | EM/CER normalization (dashes, Latin/Cyrillic homoglyphs, case) | OCR/key-field metrics | Strict and relaxed variants reported |
| Q6 | Full original files for 1–2 pilot objects without markup; a registry sample in their format; ИД in XML (XSD) | Realism, the FULL scenario, the registry parser | Padded pilot pages + synthetic ДЕМО packages + our XSD |
| Q7 | Vector originals of АНО/150321 (ИОС5.4.2, ОВ1, ОВ2.1) | Graphic-diff quality | Raster crops → low-confidence composite; synthetic vector recreation |
| Q8 | 5 inspectors for 30–45 min (in person or remote) for the §9.3 usability test | Mandatory item | 5 proxies, method published |
| Q9 | **Judging criteria**, jury composition, demo length, whether the jury uploads its own documents, venue internet, reference hardware for §11 | Allocation of effort and demo design | Assumptions in §3.1; offline demo; hardware stated |
| Q10 | Cloud LLM allowance (incl. Russian providers) | Architecture choice | Closed contour, no LLM |
| Q11 | Threshold confirmation: M-117 (< 1,5 м — likely 0,9 м per СП 59.13330), M-048, ranges M-031/M-047/M-084/M-116, M-119 | FP control | Conservative defaults, flagged, admin-editable |
| Q12 | Reason-code classification and approved-change document types used by Мосгосстройнадзор | Rejection codes, approved_change_ref | Our dictionary (B05) |
| Q13 | Confirm 50/200 МБ = MiB, per file / per upload request | Limit behaviour | MiB, per request (B01) |
| Q14 | ИАИС «РиН» API description (even a data structure) | Adapter realism | Our OpenAPI contract with the literal ТЗ paths |

### 8.2 Draft letter (Russian, ready to send after the user's approval)

> **Тема:** Задача №10 «Инспектор ИИ» — уточняющие вопросы команды
>
> Уважаемые организаторы!
>
> Чтобы результат нашего решения был пригоден для автоматической оценки по разделу 14 ТЗ, просим уточнить:
> 1. **Приложение № 2** (образец выходного протокола), обязательное согласно п. 9.2, отсутствует в комплекте материалов. Просим направить его.
> 2. **Порядок оценки на скрытой выборке:** запускаете ли вы наше решение сами (Docker/API) или передаёте входные данные нам; формат входа (файлы и реестр CSV/XLSX/JSON); ожидаемый формат выхода (поля листа «СХЕМА GOLD»; JSONL или XLSX); сопоставляется ли наш статус CANDIDATE с эталонным CONFIRMED_VIOLATION; является ли разметка исчерпывающей по объекту (считаются ли кандидаты вне разметки ложными срабатываниями).
> 3. **Нумерация страниц** в эталоне: «стр.» — индекс страницы PDF-файла или номер листа по штампу? Как считается IoU при нескольких рамках на странице?
> 4. **Коды параметров** для находок вне Матрицы (например, IZM12-V01, LOS3A-V01) и для дублирующих параметров (M-040/M-104 и др.); используется ли классификатор типов нарушений?
> 5. **Нормализация** для Exact Match и CER: дефисы и тире, латиница и кириллица в шифрах, регистр.
> 6. Можно ли получить **полные исходные файлы** 1–2 пилотных объектов (например, ALT79B-000015, ALT79B-000077) без экспертной разметки, **пример реестра** файлов в вашем формате и пример ИД в **XML** (со схемой XSD)?
> 7. **Векторные исходники** к разметке АНО/150321 (ИОС5.4.2, ОВ1, ОВ2.1).
> 8. Для обязательного **юзабилити-тестирования** (п. 9.3): можно ли организовать 30–45 минут работы с 5 инспекторами (очно или удалённо)?
> 9. **Регламент защиты:** критерии оценки, состав жюри, длительность демонстрации, будет ли жюри загружать собственные документы, доступ к интернету на площадке, эталонное оборудование для проверки раздела 11.
> 10. Допускается ли использование облачных LLM (в том числе российских) или решение должно работать полностью в закрытом контуре?
> 11. Подтвердите пороги: M-117 (ширина двери в свету «< 1,5 м» — возможно, 0,9 м по СП 59.13330), M-048, диапазоны M-031, M-047, M-084, M-116, M-119.
> 12. Используемый в Мосгосстройнадзоре **классификатор причин отклонения** и типы документов «согласованного изменения» (если есть).
> 13. Лимит 50 МБ: файл «Комплект_предметной_разметки.pdf» (51,49 МиБ) его превышает. Верно ли, что лимит 50 МБ применяется к одному файлу, а 200 МБ — к одному запросу загрузки (в МиБ)?
> 14. Описание **API ИАИС «РиН»** (хотя бы структура данных), если его можно предоставить.
>
> С уважением, команда «Инспектор ИИ».

---

## 9. Demo acceptance criteria (the "demo readiness gate") and tests

| ID | Criterion | How proven | By |
|---|---|---|---|
| DR-01 | `make demo-reset STAGE=S0 && make demo` from a clean state → all services healthy in ≤ 3 min (cached images) | Scripted timer | CP3 |
| DR-02 | The full 12-minute script executed **3 consecutive times** with no code change, manual DB edits or restarts, each run ≤ 12:30 | Rehearsal log + recordings | T-1 |
| DR-03 | Live latency budget: ALT79B upload → READY ≤ 60 s; ДЕМО-01 incremental ≤ 60 s; matrix publish + recheck ≤ 60 s; РиН retry sequence ≤ 30 s at ×60; self-test ≤ 2 min; card switch ≤ 300 ms | `demo-check` timings | CP3 |
| DR-04 | Offline: with network disabled the whole script passes | Airplane-mode rehearsal | CP3 |
| DR-05 | Every jury-visible string is Russian; no English errors or stack traces; error toasts show `request_id` | Playwright text assertions + axe | CP3 |
| DR-06 | Every finding in any snapshot was produced by the pipeline; every decision has an audit row from an API call | SQL check: findings ↔ runs; decisions ↔ audit | CP2 |
| DR-07 | Synthetic badge visible on every synthetic object, metric and export | Playwright | CP2 |
| DR-08 | Pilot scoreboard: 9/9 expected statuses; file_id + page exact; IoU ≥ 0,5 for ≥ 95 % of fragments with GOLD bboxes; POL17 → 0 candidates; evaluated on clean copies | CI job | CP2 (target), CP3 (gate) |
| DR-09 | Snapshots S0–S5 each restore in ≤ 60 s; a backup clip (≤ 40 s) exists for every segment | Checklist | T-2 |
| DR-10 | Browser profiles pre-logged in; session TTL ≥ 2 h in the demo profile; tested on a 1920×1080 projector | Rehearsal | T-2 |
| DR-11 | No redacted or PII text anywhere (API responses, exports, logs) | grep test over known redacted strings | CP2 |
| DR-12 | Hidden-test runbook rehearsed on the internal hidden set: batch run + GOLD export + eval within the documented time; outputs validate against the СХЕМА GOLD schema | CLI log | T-3 |
| DR-13 | «Соответствие ТЗ»: 100 % of ТЗ clauses mapped; every non-green item has waiver text | Compliance generator | CP3 |
| DR-14 | «Самопроверка» Tier-1: ≥ 60 scenarios, 100 % PASS, ≤ 2 min | Run report | CP3 |
| DR-15 | Q&A drill: 20 questions, each answered in ≤ 45 s | Drill | T-1 |
| DR-16 | Submission package complete (§3.6) | Checklist | T-1 |
| DR-17 | Cold-start branch (§3.2.4) rehearsed twice on repackaged "unseen" documents, ≤ 5 min | Rehearsal | T-2 |

---

## 10. Work breakdown, timeline and scope-cut order

### 10.1 Strategy-owned tasks
Sizes: S ≤ 0,5 d, M ≤ 1,5 d, L ≤ 3 d.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| STR-T01 | Decision session (U1–U17) and recording of outcomes | S | — | user + strategist |
| STR-T02 | Send the organizer letter (§8.2); track answers; propagate them to the blocks | S | T01 | user |
| STR-T03 | Cross-block rulings ADR (X-R1…X-R14) ratified at CP0 | S | T01 | AG-00 |
| STR-T04 | `tools/demo-data pilot`: split, pad, clean copies, sanitizer, GOLD from ПРИМЕРЫ (overlay cross-check), registries for 9 objects + vent | M | — | AG-09 Data & Demo |
| STR-T05 | `synth` generator core + ДЕМО-01 (УТ-1 spec) + ДЕМО-02 | L | T04 formats, B03 param list | AG-09 |
| STR-T06 | Internal hidden test: 25 objects, separate style pack, frozen SHA-256 manifest (T-12) | M | T05 core | AG-09 (different author) |
| STR-T07 | ML corpus (150 objects; 50 in the T-7 plan) + simulated inspector/curator scripts via the API | M | T05, B05/B06 APIs | AG-09 + AG-04 |
| STR-T08 | Demo control plane: demo profile, `DEMO_TIME_SCALE` banner, `demo-seed`, snapshots S0–S5, `demo-reset`, long demo sessions | M | CP1 | AG-09 + AG-00 |
| STR-T09 | Compliance generator + «Соответствие ТЗ», «Пилот», «Качество» pages + `/admin/compliance*`, `/admin/quality/metrics`, `/system/info` | M | `@req` tags (AG-00), B06 harness | AG-00 + AG-09 |
| STR-T10 | Jury-path Playwright E2E (`make demo-check`) as a merge gate | M | CP1 | QA & Negative agent |
| STR-T11 | Click/time counter overlay | S | B05 VT-12, VT-15 | B05 FE |
| STR-T12 | «Подготовка комплекта» helper (split > 50 МБ, draft registry) — NICE | S | B01 registry schema | AG-09 |
| STR-T13 | Hidden-test runbook + batch rehearsal on the internal hidden set | S | B06-T03/T15, B01-W22 | AG-04 + AG-09 |
| STR-T14 | Usability sessions: recruit, schedule, facilitate (5 participants, rounds 1–2) | M | B05 VT-15, ДЕМО-01 | user + B05 |
| STR-T15 | Normative references expert pass (about 40 demo refs) | M | B03 seeds | domain expert |
| STR-T16 | Pitch deck (10 slides, RU) + talk track + handout | M | CP2 | user + AG |
| STR-T17 | Backup clips per segment + 3-minute submission video | S | CP3 | user |
| STR-T18 | Rehearsals ×3 with timer; defect triage after each | S×3 | CP3 | user + all |
| STR-T19 | Q&A sheet (§3.6) + drill | S | T16 | user |
| STR-T20 | Submission package: README RU, guides, OpenAPI/AsyncAPI, ADRs, «Интерпретации ТЗ», images tarball | M | CP3 | AG-00 + user |
| STR-T21 | Daily checkpoint recording (2-minute clip of the current demo path) | S/day | CP0 | AG-09 |
| STR-T22 | Velocity check and scope-cut decision at each checkpoint | S×4 | — | user + AG-00 |

### 10.2 Baseline phased timeline (T-14 working days → T-0 defense)

**Principle: demo-able at every checkpoint.** Each checkpoint has a demo subset that runs end-to-end with `make demo`, is recorded (STR-T21) and becomes the fallback for the next phase.

| Phase | Days | Goals | Checkpoint and demo-able state |
|---|---|---|---|
| **P0 — Decide and freeze** | T-14 … T-13 | U1–U17; letter sent; OrbStack + brew installs; AG-00 contracts (OpenAPI/AsyncAPI/DB/enums/errors v1) and rulings X-R1…X-R14; pilot toolkit (STR-T04); extractor/OCR/viewer prototypes inside owned directories | **CP0 (end of T-13): walking skeleton.** `compose up` → upload → 202 `process_id` → status → a fake worker returns a canned pilot protocol → protocol viewer renders 5 tables → dashboard shows 10 pilot objects with colours from canned statuses |
| **P1 — Golden thread on real data** | T-12 … T-10 | Real ALT79B (text layer → explications → M-002/M-003 → evidence group with bbox) + OKT103 (OCR tolerance) + POL17 (negative); protocol JSON + basic PDF; viewer + confirm/reject/finalize; rin-mock happy path; dashboard from real statuses; **internal hidden test frozen (T-12)** | **CP1 (end of T-10): golden thread.** Script steps 1–6 on real pilot data: upload → READY → ALT79B candidate with blue/red boxes → confirm → finalize → РиН SYNCED → object turns red. The jury-path E2E becomes a merge gate |
| **P2 — Breadth: all 12 modules visible** | T-9 … T-6 | Registry wizard (basic), revisions, completeness, scenarios; 132-param coverage with statuses; UNDMS/SOSH25/DOO25/POL16; change-log miner; incremental + carry-over; exports DOCX/XML + GOLD; split; dispute; un-finalize; ML loop (LR + thresholds, gate, approve, rollback) + `inspector-eval` v1; hypotheses (logical 12 rules, semantic, normative, robust-z) + HR-LOG-005; matrix admin publish + impact; audit viewer; weekly report; Grafana + alerts + ELK profile; errors.yaml + ≥ 30 self-test scenarios; ДЕМО-01/02 through the real pipeline | **CP2 (end of T-6): feature-complete.** The full 12-minute script runs start to end (rough edges allowed); all 12 modules clickable; DR-06/07/11 pass |
| **P3 — Depth and proof** | T-5 … T-3 | Pilot scoreboard 9/9 and region-box tuning; internal hidden-test metrics; §11 benchmarks + k6 + «НФТ»; usability rounds 1–2 (proxies); TLS 1.3, AES-GCM, GOST signer, backup drill; self-test to 60; compliance page; docs; Приложение 2 swap if received; hidden-test runbook rehearsal | **CP3 (end of T-3): release candidate.** Clean clone → `make demo` on a fresh machine or VM; the script runs once with no intervention; DR-01/03/04/05/08/12/13/14 pass |
| **P4 — Freeze and rehearse** | T-2 … T-0 | Bug fixes only (P0/P1 severity); rehearsals ×3; backup clips + 3-minute video; deck + handout; Q&A drill; cold-start rehearsal ×2; submission package | **Final gate (T-1):** DR-02/09/10/15/16/17 pass → defense at T-0 |

### 10.3 Compression and expansion variants

| Variant | CP0 | CP1 | CP2 | CP3 | Freeze | Pre-applied cuts |
|---|---|---|---|---|---|---|
| **T-7** | T-7 (½ day) | T-5 | T-3 | T-1,5 | 1,5 d | Level 1 + Level 2 from the start; ML corpus 50 objects; 1 usability round |
| **T-10** | T-10 (1 day) | T-7 | T-4 | T-2 | 2 d | Level 1 from the start |
| **T-14** (baseline) | T-13 | T-10 | T-6 | T-3 | 2–3 d | Level 1 from the start (see §10.5 capacity) |
| **T-21** | T-19 | T-15 | T-9 | T-5 | 4 d | None pre-applied. Add: deeper graphic diff, 50 deep profiles, 2 usability rounds with real inspectors, cloud VM deployment |

### 10.4 Scope-cut order (never cut High modules; cut depth, not breadth)

**Trigger rule:** if a checkpoint's demo subset does not run end-to-end by the end of its day, apply the next level **immediately**. Do not try to "catch up".

**Level 0 — Never cut (the spine):**
- all 12 modules present;
- High modules 1, 2, 3, 4, 5 and 12 working end to end;
- the protocol's two sections and five tables + evidence card fields;
- statuses and gates exactly per the ТЗ;
- §9.1 error-table behaviours;
- SUSPICION exclusion;
- GOLD versioning + object split + gate + signed approval + rollback;
- OpenAPI request/response validation;
- RabbitMQ + the Redis cache;
- pull model;
- incremental upload;
- РиН: finalized-only + retries + PENDING_SYNC;
- colours, filters and exports;
- threshold change without recoding;
- audit;
- weekly report;
- Prometheus/Grafana + alerts;
- the pilot scoreboard;
- GOLD export.

**Level 1 — Polish and extensions (cut first; pre-applied in the T-14 baseline if capacity demands):**
- impact-preview what-if; SSE presence;
- prescriptions sync; openssl-gost sidecar / CrowdSec; internal TLS profile;
- VLM/LLM adapters; IsolationForest and synthetic history;
- raster GRAPHIC_DIFF (keep text-token inventories); ConfigDiff raster fallback;
- object card 8 tabs → 3; dashboard charts; a11y/responsive pass;
- registry editor provenance thumbnails; matrix version restore + ordinal-scale editor;
- Logical_Rules visual builder → JSON editor with validation;
- SUS form and facilitator console polish; PSI drift; bundle components C3–C6 (keep C1 + C2);
- four-eyes curation (keep a single curator);
- sheet-scope revisions (keep document-level).

**Level 2 — Depth of Medium/Low modules:**
- Grafana 5 dashboards → 1;
- ELK → a minimal single-node Elasticsearch + Logstash + Kibana pass-through, no app/security routing;
- weekly report PDF → HTML + JSON (PDF via the shared renderer only if free);
- Normative_Base editor → editable table;
- audit GOST seals → SHA-256 hash chain;
- backup PITR drill → nightly dump + restore script;
- РиН pull connector → a mock "incoming documents" button;
- mTLS → signature only;
- notification centre → bell + toast;
- protocol diff UI → change list.

**Level 3 — Depth of High modules (keep breadth, every status still produced):**
- deep parameter profiles 35 → 20 (the demo-priority-1 list from B03 + the ТЗ examples);
- CV → dimension-text + declared-scale only;
- OCR engine → PP-OCRv5 only (Tesseract only for orientation);
- hypothesis detectors: logical + semantic + normative, with ML pattern as robust-z only;
- ML corpus 150 → 50 objects;
- automatic split proposal → manual split;
- registry wizard stamp pre-fill → CSV import + manual grid;
- DOCX/XML adapters → text + tables without rendered locators (page = rendition page 1 note);
- usability: one round with 5 proxies.

### 10.5 Capacity math and effort caps

- **Demand:** 244 block tasks sum to ≤ 360,5 agent-days (upper bounds). At a realistic ~70 % of the upper bound that is ≈ 250 agent-days.
- **Deduplication** through the §4.2 rulings saves ≈ 28–32 agent-days:

  | Source of duplication | Saving (agent-days) |
  |---|---|
  | datasets | 6–8 |
  | viewer | ~3,5 |
  | renderer | ~3 |
  | explication extractor | ~3 |
  | messaging | ~2 |
  | compose | ~2 |
  | auth/audit | ~2 |
  | observability | ~1,5 |
  | perf harness | ~1,5 |
  | normalization | ~1,5 |
  | revision resolver | ~1,5 |
  | rule engine | ~1 |

- **Level 1 cuts** save ≈ 30–35 agent-days. The result is ≈ 185 agent-days.
- **Supply:** 10 agents × 14 days = 140 agent-days. So the T-14 baseline needs Level 1 **plus** partial Level 2 (Medium/Low only), or more days (≈ 19) at full quality.
- **Recalibrate at CP1:** if completed size-units are < 70 % of plan, apply Level 2 fully at once.

**Effort caps per module (caps, not targets; at 140 agent-days):**

| Area | Cap (agent-days) | Share |
|---|---|---|
| AG-00 platform and contracts | 15 | 11 % |
| M1 upload/parsing (B01 + B02 incl. their UI) | 25 | 18 % |
| M2 comparison/protocol (B03 + B04 incl. renderer) | 24 | 17 % |
| M3 verification (B05 incl. viewer) | 16 | 11 % |
| M4 + M10 (B06 incl. eval harness, ML UI) | 12 | 9 % |
| M5 hypotheses (B07) | 9 | 6 % |
| M12 errors/negative (B10) | 8 | 6 % |
| M7 + M8 dashboard/admin (B08) | 12 | 9 % |
| M6 + M9 + M11 + §12 (B09) | 10 | 7 % |
| Data, demo, compliance (AG-09) | 9 | 6 % |
| **High modules (M1–M5, M12) combined** | **≈ 90** | **≈ 64 %** |

### 10.6 Daily operating rhythm
- **Morning:** one integration merge window. `main` must stay green: contract drift check, unit tests, jury-path E2E from CP1.
- **Midday:** automated `make demo-check` on `main`, with a report to the user.
- **Evening:** record the checkpoint clip (STR-T21); update the burn-down by size-units; make the cut decision if behind.
- **Definition of Done** (adds to B00's): the feature appears in the demo script or on a compliance page, is seeded through `demo-seed`, has `@req`-tagged tests, uses Russian strings and does not break the jury path.
- **No new features after CP3.** Only fixes to failed DR-xx criteria.
