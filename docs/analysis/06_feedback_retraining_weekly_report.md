# B06 — Feedback & Controlled Retraining (Module 4, High), Weekly ML Report (Module 10, Medium), §14 Acceptance-Metrics Evaluation Harness

Planning/analysis only; no application code. Written 2026-09-27 by the B06 planning agent.
Sources: `docs/spec/01_TZ_text.txt` (full), `02_matrix_all_sheets.txt` (all 4 sheets), `03_perechen_ID_registry_rules.txt`, `05_razmetka_poyasn_6p_text.txt`, the originals `ТЗ/Комплект_предметной_разметки.pdf` (inspected with PyMuPDF: geometry, content streams, annotations) and the page previews.

---

## 0. TL;DR

- **What we are building:** a closed, auditable loop. An inspector decision becomes a draft GOLD item. The item is curated, then released as a versioned `dataset_version` with object-level splits and SHA-256 manifests. A controlled training job follows, then a full §14.3 evaluation, then a regression gate. Only after that can a responsible person sign a publication decision, and the published model can always be rolled back. Around the loop sit a weekly ML report and a **standalone evaluation CLI (`inspector-eval`)**. Organizers can run the CLI against their hidden test in the "СХЕМА GOLD" format.
- **Honest ML stance:** there are 9 pilot groups, of which only 1 is positive and 1 is negative GOLD. That is too little to train or validate any parametric model; §14.1 says so itself. Our retrainable "model" is therefore a **versioned model bundle** built from 6 components:
  - Parametric (actually trained): a calibrated candidate verifier (a false-positive filter and risk ranker) and per-category operating thresholds.
  - Data-derived (rebuilt from feedback, not gradient-trained): a numeric noise-tolerance table, a semantic anchor bank, an OCR confusion lexicon, and approved-change patterns.
  - All 6 are versioned, hashed and gated in the same way.
  - To show the loop end to end we bootstrap with a **labelled synthetic corpus**: about 150 synthetic objects with all §14.2 class types, plus a simulated inspector. The corpus is clearly flagged `source=SYNTHETIC` and is never presented as real acceptance.
- **Corrections to the "known facts" (verified in the originals):**
  1. The red expert markup in `Комплект_предметной_разметки.pdf` is **not** stored as Ink annotations. It is vector content: `0.9 0 0 RG` rectangles, a rounded callout box and a leader arrow, drawn by a ReportLab overlay that pypdf appended **at the tail of the single page content stream**. The normalized red rectangles match the bboxes in sheet «ПРИМЕРЫ РАЗМЕТКИ» to 3–4 decimals (e.g. p.2 `[0.78,0.10,0.91,0.35]`, `[0.36,0.10,0.64,0.25]` = ALT79B PD стр.19).
  2. The **Ink annotations are white strokes (colour 1,1,1, width 9.75) over the title-block zone**. They are visual redactions of object names or signatures (checked on p.6: the Ink covers «…Здание Управления внутренних дел…»). **The text layer underneath is NOT removed.** A naive parser will extract the redacted text. This matters for PII and sensitivity (§12.6) and for which text is allowed into datasets and exports.
  3. Some drawings carry **native red elements**: p.15 evacuation paths, p.19 revision clouds «Корректировка №14…». Colour-based markup detection is therefore wrong. The overlay must be taken from the stream tail. The native «Корректировка №…» clouds are also a real **approved-change signal** for features.
  4. All 24 pilot pages have `Rotate=0` and `CropBox=MediaBox`. **The pilot cannot validate rotation or crop normalization** (§9.1 p.4). Synthetic rotated and offset pages are required.
  5. We can produce **clean copies** of the pilot pages by truncating the overlay tail (starting at `q 0 0 W H re W n … BT /F1 12 Tf 14.4 TL ET`). Without clean copies, our pipeline would "read the answer" from the callout text during demo and evaluation.

---

## 1. Scope

### 1.1 ТЗ clauses covered

| Clause | Quote / essence | B06 responsibility |
|---|---|---|
| §7 Module 4 (High) | «Версионированный GOLD из подтверждённых положительных и отрицательных примеров; объектное разбиение; публикация модели только после приёмки» | Full ownership |
| §7 Module 10 (Medium) | «Автоматическая генерация отчёта для ML-инженеров: статистика отклонений, рекомендации по донастройке моделей» | Full ownership |
| §9.4 purpose | «формирование версионированного GOLD-набора … анализ причин ошибок и запуск управляемого дообучения без автоматической публикации модели» | Full |
| §9.4 «Сценарии работы ИИ» | 3 rows: rejected → negative draft, included only after the curator; clarification → not in GOLD; confirmed → positive GOLD candidate, external transfer only after finalization | Full (B03 renders; B06 stores and enforces) |
| §9.4 «Требования к дообучению» | coverage-based release; only CONFIRMED_VIOLATION/NEGATIVE_VERIFIED with full cards; exclusions; object split; frozen hidden test + SHA-256; publication gate (§14 thresholds, Recall −2 pp, FPR +2 pp); signed decision; rollback; per-iteration record | Full |
| §9.4 AI comments | «Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR. Запись включена в черновик…» / «Статус: CLARIFICATION_REQUIRED. Показаны точные страницы…» | Full (templates plus the AI-verdict service) |
| §9.3 (partial) | atomic findings, no `PARTIALLY_CONFIRMED` label; decision fields (`user_id`, `timestamp`, comment; `reason_code` + comment); cancelling finalization | Consumer: eligibility rules and revocation |
| §9.2 step 1, §14.2 «Версионность» | «Версии Матрицы, набора данных и модели фиксируются в каждом запуске и в протоколе» | Provider of the active `model_version`/`dataset_version` |
| §9.5 | «SUSPICION … не используется как положительная учебная метка» | Enforced exclusion |
| §9.1 p.1 | OCR acceptance: CA = 1−CER ≥ 0,95; key-field EM ≥ 0,90; NFC plus whitespace normalization; case rules; excluded zones → LOW_QUALITY/ABSTAIN; shares reported | Metric definitions in the harness |
| §9.1 p.4 | normalized [0;1] bbox after CropBox/MediaBox/Rotate | Harness geometry normalization |
| §10 tables #6, #7, #11, #15, #16 | Rejection_Log, Dispute_Log, ML_Retraining_Log, Dataset_Items, Model_Versions | Owner |
| §11 #7 | «ML-анализ одного параметра (NLP) ≤ 500 мс» | Scorer / AI-verdict latency |
| §12 #2, #4, #6, #7 | ML-engineer role access; audit; 152-ФЗ; integrity | Applied to B06 |
| §13 #1, #4, #5, #8 | JSON logs; metrics; Prometheus; checksum verification | Applied to B06 |
| §14.1–14.3 | GOLD unit = evidence_group; split rules; test composition; no leakage; versioning; all metrics, thresholds, per-object/section/type breakdowns, n, coverage/abstention, 95% CI; «не считается принятой при недостижении любого обязательного порога» | Harness plus the gate |
| Прил. 1 sheets «СХЕМА GOLD», «МЕТРИКИ», «ПРИМЕРЫ РАЗМЕТКИ» | GOLD field list; metric table incl. «Regression gate … автоматическая публикация запрещена»; pilot groups | The format contract |

### 1.2 Statuses this block touches
- Finding statuses: `CONFIRMED_VIOLATION` (→ POSITIVE), `NEGATIVE_VERIFIED` (→ NEGATIVE, **inspector-sourced only**), `CLARIFICATION_REQUIRED`, `CANDIDATE`, `SUSPICION`, `MISSING_EVIDENCE`, `NOT_APPLICABLE`, `NOT_COMPARABLE` (the last five are never labels).
- Verification/protocol: `VERIFICATION_COMPLETED`, `PROTOCOL_FINALIZED` (= process `FINALIZED`). Items are released only from finalized protocols.
- GOLD `split`: `TRAIN / VALIDATION / HIDDEN_TEST`.
- Our own: dataset-version status, item status, `retraining_status`, model `approval_status`, dispute `resolution_status` (see §3).

### 1.3 Related NFRs
- §1.3 OpenAPI 3.0 validation.
- §1.4 async pull: every B06 job returns an id plus a status endpoint.
- §1.5 Python ≥ 3.11 for ML; RabbitMQ.
- §11 #7 (≤ 500 ms) and #10 (API p95 ≤ 200 ms: B06 heavy work is always async).
- §12, §13 as listed above.

---

## 2. Requirements checklist (prefix MLF)

Priority means priority for winning. MVP decision is one of FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| MLF-01 | Maintain a versioned GOLD set built from expert-confirmed positive and negative examples | §7 M4; §9.4 | MUST | FULL | Core of Module 4 |
| MLF-02 | Rejection with coded reason → store as a negative example in the **draft** of the next dataset version; include in `dataset_version` only after the curator checks it | §9.4 row 1 | MUST | FULL | Item state machine plus curator queue |
| MLF-03 | Clarification request → no GOLD item (sources, coordinates and revision conflict are shown by B03) | §9.4 row 2 | MUST | FULL | Hard exclusion rule |
| MLF-04 | Confirmation → positive GOLD candidate; external transfer only after protocol finalization | §9.4 row 3; §9.3 p.4 | MUST | FULL | B06 marks it; the integration module enforces the transfer |
| MLF-05 | Release composition is determined by coverage of target categories | §9.4 | MUST | FULL | Coverage report plus configurable per-category minima |
| MLF-06 | Release contains only CONFIRMED_VIOLATION / NEGATIVE_VERIFIED with **complete evidence cards** | §9.4; СХЕМА GOLD | MUST | FULL | Automatic eligibility validator against СХЕМА GOLD |
| MLF-07 | CANDIDATE, SUSPICION, MISSING_EVIDENCE and unfinished decisions are never used in training | §9.4; §9.5 | MUST | FULL | Validator plus DB CHECK plus trainer assertion |
| MLF-08 | Do not accept a raw count («100 подтверждённых нарушений») as the quality criterion; use coverage criteria | §9.4 | SHOULD | FULL | Coverage matrix in the release screen and the weekly report |
| MLF-09 | Object-level split: all pages, docs and revisions of one object in exactly one split; sticky across versions | §9.4; §14.2 | MUST | FULL | `object_group_id` split registry |
| MLF-10 | Hidden test set plus its SHA-256 frozen before use; never used for training, threshold tuning or manual tuning | §9.4; §14.2 | MUST | FULL | Internal frozen `HIDDEN_TEST`; trainer refuses it; aggregate-only access |
| MLF-11 | New model publishable only after passing the §14.3 thresholds | §9.4 | MUST | FULL | Gate on the internal frozen test (synthetic in the demo) |
| MLF-12 | No Recall drop > 2 pp on any mandatory category versus the previous model | §9.4; МЕТРИКИ | MUST | FULL | Exact rational comparison per category |
| MLF-13 | No FPR rise > 2 pp on verified negative groups | §9.4; МЕТРИКИ | MUST | FULL | Also on outdated-revision cases |
| MLF-14 | Publication decision signed by a responsible person; automatic publication forbidden | §9.4; МЕТРИКИ | MUST | SIMPLIFIED | Password step-up plus canonical decision digest plus Ed25519 server signature; УКЭП behind an interface |
| MLF-15 | Rollback always possible | §9.4; §10 #16 `rollback_to` | MUST | FULL | Active-model pointer plus hot-reload event |
| MLF-16 | Per-iteration record: model/dataset/matrix versions, set composition and hashes, training code and parameters, all metrics, decision, responsible person, link to the previous model | §9.4 | MUST | FULL | ML_Retraining_Log plus Model_Versions |
| MLF-17 | AI system comment when the AI agrees with a rejection (ТЗ template) | §9.4 | MUST | FULL | Deterministic Russian template |
| MLF-18 | AI system comment on a disputed rejection → CLARIFICATION_REQUIRED, not in GOLD, not transferred until the inspector re-decides; Dispute_Log entry | §9.4; §10 #7 | MUST | FULL | AI-verdict service (rules plus score) |
| MLF-19 | Analysis of error causes: coded reasons, `suggested_fix`, aggregation | §9.4 purpose; §10 #6 | MUST | FULL | Rule-based suggestion generator |
| MLF-20 | Controlled retraining pipeline (manual or approved trigger; Python) | §9.4; §1.5 | MUST | SIMPLIFIED | Small calibrated scorer plus data-derived components; no deep fine-tuning |
| MLF-21 | Table Rejection_Log (`id, violation_id, rejection_reason, ai_verdict, suggested_fix, retraining_status`) | §10 #6 | MUST | FULL | Plus extension fields |
| MLF-22 | Table Dispute_Log (`id, violation_id, inspector_comment, ai_comment, resolution_status, resolved_by`) | §10 #7 | MUST | FULL | |
| MLF-23 | Table ML_Retraining_Log (`id, model_version, dataset_version, split_hashes, precision, recall, f1, false_positive_rate, per_category_metrics, approval_status, approved_by`) | §10 #11 | MUST | FULL | |
| MLF-24 | Table Dataset_Items (`id, evidence_group_id, gold_label, expert_id, reason_code, dataset_version, split, object_group_id`) | §10 #15 | MUST | FULL | Immutable per-version rows |
| MLF-25 | Table Model_Versions (`model_version, artifact_hash, dataset_version, metrics_json, approval_status, approved_by, deployed_at, rollback_to`) | §10 #16 | MUST | FULL | |
| MLF-26 | Label unit = evidence_group; each label stores the expert decision, reason, date and source versions | §14.1 | MUST | FULL | Frozen evidence-card snapshot |
| MLF-27 | GOLD import/export strictly in the «СХЕМА GOLD» format (XLSX/CSV/JSON/JSONL) | Прил. 1 | MUST | FULL | Shared JSON Schema; the harness uses the same loader |
| MLF-28 | Pilot (9 groups) used as format and scenario reference only, never for quantitative acceptance | §14.1; МЕТРИКИ | MUST | FULL | Reports always show n and CI; pilot flagged |
| MLF-29 | Each result carries `dataset_version, matrix_version, model_version, input_manifest_hash` | §9.2 p.1; §14.2 | MUST | FULL | B06 exposes the active versions; B02 stamps the protocol |
| MLF-30 | Test composition includes confirmed violations, verified negatives, missing evidence, not-applicable and revision conflicts | §14.2 | MUST | FULL | Internal test plus the synthetic generator; harness per class |
| MLF-31 | No leakage: hidden-test labels unavailable to training and tuning; no threshold selection on the test | §14.2 | MUST | FULL | Split-aware file layout plus RBAC plus access log |
| MLF-32 | Composite candidate → atomic findings; no `PARTIALLY_CONFIRMED` training label | §9.3 p.2 | MUST | FULL | Validator rejects it |
| MLF-33 | Decision completeness: confirm = `user_id`, `timestamp`, comment; reject = `reason_code` plus comment | §9.3 p.2 | MUST | FULL | Eligibility rule |
| MLF-34 | Cancelling finalization (supervisor) → suspend or revoke the affected items; flag models trained on revoked items | §9.3 «Отмена финализации» | SHOULD | FULL | Event-driven |
| MLF-35 | OCR Character Accuracy = 1 − ΣLevenshtein/Σchars ≥ 0,95; also CER, WER, coverage | §9.1; §14.3 | MUST | FULL | Harness; needs OCR GOLD (the text layer of vector pages is used as a surrogate) |
| MLF-36 | OCR normalization: Unicode NFC, collapse repeated whitespace; case-folding only where case carries no meaning; signs in codes and revisions never removed | §9.1 | MUST | FULL | Published normalization spec |
| MLF-37 | Handwritten or pre-marked illegible zones excluded from the metric; the system must return LOW_QUALITY/ABSTAIN there; share of such zones and coverage reported | §9.1 | MUST | FULL | Abstain-compliance metric |
| MLF-38 | Key-field Exact Match ≥ 0,90 (шифр, стадия, редакция, лист/страница, номер помещения/элемента) | §9.1; §14.3 | MUST | FULL | Per-field and pooled |
| MLF-39 | Document linkage accuracy ≥ 0,95 (object_id, stage, code, actual revision) | §14.3 | MUST | FULL | |
| MLF-40 | Evidence localization: exact file_id and page, IoU ≥ 0,50 after page-geometry normalization; ≥ 0,95 of groups with complete evidence | §14.3; §9.1 p.4 | MUST | FULL | Hungarian matching; polygon IoU |
| MLF-41 | P/R/F1 per evidence_group; a match needs the right parameter/type **and** correct evidence; P ≥ 0,90, R ≥ 0,80, F1 ≥ 0,85 | §14.3; МЕТРИКИ | MUST | FULL | «Без полного доказательства finding не засчитывается» |
| MLF-42 | FPR = FP/(FP+TN) on NEGATIVE_VERIFIED and outdated-revision cases ≤ 0,10 | §14.3 | MUST | FULL | Reported separately and combined |
| MLF-43 | Metrics per object, per section and per violation type | §14.3 | MUST | FULL | `discrepancy_type` taxonomy (extension) |
| MLF-44 | Sample size, coverage/abstention and 95% CI published with each point estimate | §14.3 | MUST | FULL | Wilson plus object-cluster bootstrap |
| MLF-45 | Not accepted if **any** mandatory threshold fails, even when the aggregate F1 passes | §14.3 | MUST | FULL | Verdict = AND of thresholds; NOT_EVALUATED ≠ pass |
| MLF-46 | Standalone evaluation CLI that organizers can run on their hidden test from a СХЕМА GOLD file, with SHA-256 verification of GOLD and inputs | §14.2; brief | MUST | FULL | `inspector-eval`, offline, Docker image |
| MLF-47 | Weekly report generated automatically on a schedule | §7 M10 | MUST | FULL | Cron in the ML service; idempotent per period |
| MLF-48 | Report: rejection statistics by reason_code, parameter, section, stage pair, extraction method and model version | §7 M10 | MUST | FULL | |
| MLF-49 | Report: model-tuning recommendations | §7 M10 | MUST | FULL | Deterministic rule engine with evidence; never auto-applied |
| MLF-50 | Report: drift section (input, score and label drift) | brief | SHOULD | SIMPLIFIED | PSI on ~10 features plus score; minimum-sample guard |
| MLF-51 | Report formats JSON, HTML and PDF | brief | SHOULD | FULL | Jinja2 → HTML → WeasyPrint PDF |
| MLF-52 | Report delivery: in-app notification plus e-mail to the ML-engineer role | brief; §13 #7 channels | SHOULD | SIMPLIFIED | SMTP to MailHog in dev |
| MLF-53 | Report delivery to Telegram | §13 #7 (channel analogy) | NICE | MOCKED | Only if a bot token is supplied |
| MLF-54 | Report history stored with hashes; re-download | brief | SHOULD | FULL | Weekly_Reports table |
| MLF-55 | RBAC: ML-engineer (logs, retraining data), data curator, responsible approver, inspector; four-eyes rules | §12 #2; §9.4 | MUST | FULL | Curator and approver as extra roles (decision D1) |
| MLF-56 | Every curator, training, evaluation, approval, deploy and rollback action written to Audit_Log (time, IP, action, object) | §12 #4; §7 M9 | MUST | FULL | |
| MLF-57 | Async pull pattern for jobs (202 plus id plus status); RabbitMQ between Node and Python | §1.4; §1.5 | MUST | FULL | |
| MLF-58 | OpenAPI 3.0 schema validation for all B06 endpoints | §1.3 | MUST | FULL | |
| MLF-59 | ML code in Python ≥ 3.11 | §1.5 | MUST | FULL | |
| MLF-60 | Structured JSON logs (`timestamp, level, service, message, request_id, user_id`); Prometheus metrics (job durations, queue depth, online precision, drift) | §13 #1, #4, #5 | SHOULD | FULL | |
| MLF-61 | Scorer / AI-verdict inference ≤ 500 ms per parameter | §11 #7 | MUST | FULL | Microseconds for LR/HGB |
| MLF-62 | Negative scenarios: training failure or timeout, ML service down (decision never blocked), artifact hash mismatch (refuse to load), test hash mismatch (abort), empty or invalid dataset, gate NOT_EVALUATED | §7 M12 | MUST | FULL | |
| MLF-63 | Integrity: dataset manifests and model artifacts are write-once; hash verified on every load; daily checksum job | §12 #7; §13 #8 | SHOULD | FULL | |
| MLF-64 | PII minimization: pseudonymous `expert_id`; no ФИО or contacts in datasets or reports; text under opaque redaction annotations never exported | §12 #6 | MUST | FULL | Pilot redactions are visual-only |
| MLF-65 | Retention of ML logs and reports (90 days / 1 year); backups 30 days | §12 #5, #8; §13 #3 | NICE | SIMPLIFIED | Documented config, no purge job in MVP |
| MLF-66 | Synthetic plus pilot bootstrap corpus that demonstrates the full loop | brief | MUST | FULL | Required for the demo and the gate to be non-trivial |
| MLF-67 | SUSPICION never becomes a positive label; a promoted CANDIDATE with `rule_version` follows the normal path | §9.5 | MUST | FULL | |
| MLF-68 | Random audit sample of system-negative groups, so online recall and FN can be estimated | derived from §9.2 table («Просмотр по выборке») | SHOULD | SIMPLIFIED | Sampling queue and weekly FN estimate |
| MLF-69 | Candidate explanation (top features) shown to the inspector and the ML engineer | §9.3 p.1 (evidence transparency) | NICE | SIMPLIFIED | LR contributions / HGB permutation importances |
| MLF-70 | The AI comment and the dispute re-decision add no extra clicks (≤ 3 clicks per violation) | §9.3 usability | SHOULD | FULL | Inline banner plus one-click re-decision |
| MLF-71 | ML never modifies normative thresholds (`min_value`/`max_value`, trigger logic); such recommendations go to the admin (Module 8) | §7 M8; §8.1 | MUST | FULL | Legal separation: noise tolerance ≠ norm |
| MLF-72 | A matrix-version change flags affected GOLD items (changed parameter) for curator re-review | §9.2 p.1; §9.4 | SHOULD | SIMPLIFIED | `stale_matrix` flag |
| MLF-73 | Training, evaluation and report jobs never degrade API latency (p95 ≤ 200 ms) | §11 #10 | SHOULD | FULL | Separate worker processes |
| MLF-74 | Cryptographic УКЭП/GOST signature of the publication decision | §12 #10 (analogy) | NICE | MOCKED | Pluggable signer; Ed25519 in MVP |
| MLF-75 | Fine-tuning the sentence-embedding encoder from feedback | §9.1 p.2 (model) | NICE | OUT_OF_SCOPE | Anchor bank (non-parametric) instead; offline script optional |

**Totals:** 75 requirements. FULL 64, SIMPLIFIED 8 (MLF-14, 20, 50, 52, 65, 68, 69, 72), MOCKED 2 (MLF-53, 74), OUT_OF_SCOPE 1 (MLF-75).

---

## 3. Proposed design

### 3.1 Components

```
                 ┌──────────────────── Node.js API (public, OpenAPI 3.0, RBAC, Audit) ─────────────────────┐
 React UI  ───►  │ /api/v1/feedback/*  /api/v1/datasets/*  /api/v1/ml/*  /api/v1/ml/reports/*              │
 (ML/curator/    │ transactional hooks on inspector decisions (B03) → rejection_log, dataset_items(DRAFT)  │
  approver)      └──────┬─────────────────────────────┬───────────────────────────────────────────────┬──┘
                        │ REST (internal, sync)        │ RabbitMQ (topic inspector.events / jobs)      │ PostgreSQL
                        ▼                              ▼                                               ▼
        ┌─────────────────────────┐   ┌──────────────────────────────────────────────┐   ┌─────────────────────┐
        │ ml-service (FastAPI)    │   │ ml-workers (same image, separate processes)  │   │ B06 tables (§3.13)  │
        │  /internal/ml/score     │   │  trainer   (ml.training.requested)           │   └─────────────────────┘
        │  /internal/ml/ai-verdict│   │  evaluator (ml.evaluation.requested)         │   ┌─────────────────────┐
        │  bundle loader (hash ✓) │   │  reporter  (ml.report.weekly.requested, cron)│   │ Artifact storage    │
        └─────────────────────────┘   │  feedback-consumer (decision/finalize events)│   │ (write-once FS/MinIO)│
                                      └──────────────────────────────────────────────┘   │ datasets/, models/, │
        ┌───────────────────────────────────────────────┐                                │ reports/, evals/    │
        │ inspector-eval (standalone CLI + Docker image, │ ◄── also imported as a library └─────────────────────┘
        │ no DB, no network)                             │     by the evaluator
        └───────────────────────────────────────────────┘
```

Python package layout (single repo `ml/`):
- `inspector_ml/{schemas,features,scorer,anchors,tolerances,ocr_lexicon,change_patterns,bundle,feedback,datasets,gate,reports,service}`
- `inspector_eval/` has zero DB dependencies and is imported by the evaluator.
- `synth/` holds the generator; `pilot/` holds the GOLD builder and overlay stripper.

### 3.2 What "the model" is (and why this is the only honest choice)

The ТЗ requires retraining from inspector feedback, yet all real labels come from the pilot: 1 positive and 1 negative GOLD. So we version a **model bundle** (`model_version`, e.g. `m-1.3.0`). Every component in it is derived only from TRAIN plus VALIDATION items of a released `dataset_version`.

| # | Component | Learns from | Method | Artifact | Affects | Becomes meaningful at |
|---|---|---|---|---|---|---|
| C1 | **Candidate verifier**: FP filter plus risk ranker, p(CONFIRMED \| features) | all eligible POS/NEG items | LogisticRegression (L2, balanced) for n < 500; HistGradientBoosting with `monotonic_cst` (+1 on `delta_over_trigger`) for n ≥ 500 and ≥ 50 positives; chosen by GroupKFold CV by `object_group_id`; Platt calibration (isotonic when n > 1000) | `scorer.joblib` plus `coef.json` | Precision, FPR, (Recall) | ~200 labels, ≥ 30 positives per gated category |
| C2 | **Operating thresholds** τ (global, optional per section) | VALIDATION only | maximize Recall subject to P ≥ 0,92 and FPR ≤ 0,08 on validation (2 pp headroom over §14.3); fall back to max F1; HIGH-priority recall floor | `thresholds.json` | P/R trade-off | ≥ 30 validation items per section with its own τ |
| C3 | **Numeric noise tolerance** per parameter (rounding, unit conversion). **Not** the normative trigger | NEGATIVE items with WITHIN_TOLERANCE / OCR_ERROR / EXTRACTION_ERROR | ε_p = min(P95 of \|Δ\| on those negatives, 0.5 × normative trigger margin); never above the trigger | `tolerances.json` | FPR | ≥ 5 negatives per parameter |
| C4 | **Semantic anchor bank**: per-parameter positive and negative phrase prototypes (e.g. «S застр.», «Пл. застройки»), kNN over multilingual MiniLM embeddings (the encoder is shared with Module 1) | confirmed items (phrase ↔ param), BINDING_ERROR (phrase ↛ param) | Rebuild the index; no gradient training | `anchors.parquet` (phrase, param, polarity, embedding) | linkage, localization, recall | a few examples per parameter |
| C5 | **OCR confusion lexicon plus code patterns** (З↔3, О↔0, Latin/Cyrillic homoglyphs in шифр) | OCR_ERROR rejections with an optional `corrected_value` | Confusion-pair counts; pattern whitelist | `ocr_lexicon.json` | key-field EM, CER, FPR | tens of corrections |
| C6 | **Approved-change patterns** («Корректировка №», «Изм.», «Ведомость изменений», revision clouds, change-sheet references) | APPROVED_CHANGE negatives with `approved_change_ref` | Pattern mining plus curated list | `change_patterns.json` | FPR (feature for C1, not auto-negation) | tens of examples |

Only C1 and C2 are "trained". C3–C6 are data-derived configuration, and we say so plainly in the UI and the docs. All six are packaged, hashed, evaluated and gated **identically**, so the whole §9.4 publication discipline applies to the whole bundle. `model_version = rules-baseline-1.0` (C1 disabled: every trigger breach becomes CANDIDATE) is the first "previous model" for the gate.

**Feature vector for C1** (built by one shared module `inspector_ml.features`, called both at inference time and at training time to avoid train/serve skew; B02 persists the snapshot `features_json` plus `feature_schema_version` on each evidence group):
- Parameter: `param_code` (one-hot or target-encoded on train only), `section`, `data_type`, `review_priority`, `stage_pair` (PD-RD, RD-ID, PD-ID, ID-internal).
- Extraction, per side: `extraction_method` (TEXT_LAYER/OCR/TABLE/CV/DOCX/XML), OCR confidence min/mean, page quality (estimated dpi, blur), `anchor_similarity`, `regex_matched`, number of alternative values found (ambiguity), cross-occurrence consistency (the same value in ТЭП and in the explication).
- Value: |Δ|, relative Δ, `delta_over_trigger` (margin), direction (worse/better under the trigger semantics), `unit_converted`, `unit_mismatch`, `rounding_digits_diff`.
- Revision metadata: both sides APPROVED, date gap, `has_successor`, conflict flags, `signature_status`.
- `approved_change_signal` (C6 hits on the same sheet/room), evidence-completeness count, bbox area ratio, `origin` (MATRIX/FREE_SEARCH).

**How the scorer is used (decision D6):** score ≥ τ → `CANDIDATE`, with risk level = f(score, review_priority). Score < τ → a system-preliminary `NEGATIVE_VERIFIED` with `verification_source=SYSTEM` and a visible note (e.g. «Расхождение отклонено моделью: вероятная ошибка OCR, p=0,07»). The inspector can re-open it as a CANDIDATE in one click, and it is eligible for the random audit sample (MLF-68). System negatives are **never** GOLD.

### 3.3 Label lifecycle and state machines

**Item status** (`dataset_items` row in the rolling draft):
```
decision recorded (B03) ──► DRAFT ──(protocol FINALIZED ∧ eligibility OK ∧ no open dispute)──► PENDING_CURATION
      │                        │                                                                 │
      │ CLARIFICATION_REQUIRED │ eligibility fails ──► INELIGIBLE (errors listed; fixable by B03) │ curator
      ▼                        │ AI dispute ──► DISPUTED ──(inspector re-decides)──► DRAFT        ├─► ACCEPTED ──(release)──► RELEASED(v)
   no item (logged only)       │ protocol un-finalized ──► SUSPENDED                              ├─► EXCLUDED (reason)
                               ▼                                                                   └─► RETURNED (to inspector/supervisor)
RELEASED(v) ──(un-finalization or changed decision)──► REVOKE_PENDING ──(next release)──► dropped from v+1; models on v flagged
```

`rejection_log.retraining_status` mirrors this: `NEW → IN_DRAFT → DISPUTED? → CURATOR_ACCEPTED | CURATOR_EXCLUDED → RELEASED → USED_IN_TRAINING → (REVOKED)`.

**Dataset version:** a single rolling `DRAFT` row always exists (the next number). `DRAFT → IN_REVIEW` happens when the curator builds a release candidate: frozen selection, coverage report, split preview. Then `IN_REVIEW → RELEASED` (immutable, hashes written) or back to `DRAFT`. `RELEASED → DEPRECATED` (superseded) or `REVOKED` (contains revoked items). Releases are **cumulative**: v+1 = v − revoked + newly accepted.

**Model version:** `TRAINING → TRAINED → (gate) GATE_FAILED | PENDING_APPROVAL → APPROVED | REJECTED → DEPLOYED → ROLLED_BACK | RETIRED`. There is **no** transition from GATE_FAILED to APPROVED: the API returns 409 and the UI button is disabled.

**Dispute:** `OPEN → RESOLVED_UPHELD` (inspector keeps the rejection → NEGATIVE, flagged `disputed=true`, requires an explicit individual curator review) `| RESOLVED_CHANGED` (→ CONFIRMED_VIOLATION) `| RESOLVED_CLARIFICATION | ESCALATED` (to a supervisor). The AI raises at most one dispute per decision round.

### 3.4 GOLD record format and eligibility validator

**Canonical flattened field names** (JSON Schema `gold_record.schema.json`, shared with B02/B03 and the harness). The composite headers of «СХЕМА GOLD» are split into columns:
- Identity: `evidence_group_id, finding_id, object_id, object_group_id*`, `matrix_code | rule_version`.
- Values: `expected_value, actual_value` (string | number | geometry).
- Sources: `source_expected_{file_id,sha256,stage,code,revision,approval,page,bbox_polygon}` and `source_actual_{…}`. `bbox_polygon` is a list of shapes, each `[x0,y0,x1,y1]` or `[[x,y],…]` in [0;1] with a top-left origin of the visible page.
- Status and decision: `approved_change_ref` (string | "NONE"), `completeness_status, finding_status, review_priority, expert_id, timestamp, expert_reason_code, comment`.
- Versions and split: `dataset_version, matrix_version, model_version, split`.
- Extension fields, marked `*`, all optional for the harness: `object_group_id*, discrepancy_type*, case_tags*` (e.g. `OUTDATED_REVISION`, `REVISION_CONFLICT`, `SCAN`, `ROTATED`), `source_type*` (PRODUCTION/PILOT/SYNTHETIC/IMPORTED), `element_ref*` (room/element number for key-field EM).
- Evidence sets with more than two sources (e.g. UNDMS has PD p.16 plus RD p.10 plus the RD change sheet p.4; IZM12 has RD plus ID with 2 bboxes) use an optional `evidence[]` array: `{role: EXPECTED|ACTUAL|CONTEXT, file_id, sha256, stage, code, revision, approval, page, shapes[]}`. The flattened columns are its first EXPECTED and ACTUAL entries.
- The loader also accepts the pilot compact notation `PD:ALT79B-000015:стр.19:bbox [..];[..]`, so sheet «ПРИМЕРЫ РАЗМЕТКИ» can be ingested as-is.
- Code aliases: `PZ-01 ≡ M-001`, `KR-55 ≡ M-055`, `AR-41 ≡ M-041` (the section prefix is checked against the matrix section; the number is global).

**Eligibility rules** (all must hold for PENDING_CURATION):
1. `finding_status ∈ {CONFIRMED_VIOLATION, NEGATIVE_VERIFIED}` **and** `verification_source = INSPECTOR`.
2. The protocol is `FINALIZED` (it is not an "unfinished decision").
3. `completeness_status = COMPLETE`.
4. Every mandatory «СХЕМА GOLD» field is present: file_id plus sha256 plus stage/code/revision/approval plus page for both sides; `expert_id`, `timestamp`, `expert_reason_code`, `comment`; the three versions.
5. For CONFIRMED: `approved_change_ref = "NONE"` and at least one shape on the actual side (the ID-internal OKT103 case may reuse the same file with different shapes). For NEGATIVE: `expert_reason_code` is in the taxonomy, and APPROVED_CHANGE ⇒ `approved_change_ref ≠ "NONE"`.
6. Atomic: there is no `PARTIALLY_CONFIRMED` and exactly one matrix_code/rule per item.
7. The source SHA-256 values match the Files registry (they are recomputed from storage).
8. None of the sources has `approval_status ∈ {SUPERSEDED, CANCELLED}` as the reference ("Устаревшая редакция не может использоваться как эталон").
9. `origin ≠ SUSPICION`.
10. There is no open dispute.

Negatives without a discrepancy location (POL17 has «bbox —») must carry the **compared zones**; a whole compared sheet is `[0,0,1,1]`. Such shapes are tagged `zone_kind=COMPARED_AREA` and are excluded from the localization denominator.

**Reason-code taxonomy** (shared enum, owned jointly with B03; the ТЗ examples are listed first):

| reason_code | ТЗ wording | Learning target |
|---|---|---|
| WRONG_REVISION | «актуальная редакция выбрана неверно» | Linkage-rules report (Module 1), not ML; C1 negative |
| APPROVED_CHANGE | «согласованное изменение» (ref mandatory) | C6 plus C1 negative |
| OCR_ERROR | «ошибка OCR» (optional `corrected_value`) | C5, C3, C1 |
| BINDING_ERROR | «ошибка привязки» | C4 hard negatives, C1 |
| NOT_APPLICABLE | «параметр неприменим» | Applicability rules → admin recommendation; C1 |
| EXTRACTION_ERROR | wrong value parsing (units, scale, table) | regex_pattern recommendation (Module 8), C3 |
| WITHIN_TOLERANCE | rounding or tolerance | C3 |
| DUPLICATE | duplicate finding | dedup rule |
| OTHER | comment ≥ 20 chars mandatory | Manual analysis bucket |

**`discrepancy_type` taxonomy** (extension, needed for "по типам нарушения"; proposed by B02, editable by the inspector on confirmation). Pilot examples are in brackets:
- `VALUE_MISMATCH`, `THRESHOLD_BREACH`
- `TOLERANCE_EXCEEDED` (OKT103)
- `CLASS_DOWNGRADE`, `MATERIAL_SUBSTITUTION`
- `ELEMENT_MISSING` (UNDMS armour sheet; ventilation warm floor, local exhausts 140/142)
- `ELEMENT_ADDED` (SOSH25 room 1.109)
- `CONFIGURATION_CHANGED` (DOO25 пищеблок; vent chamber 012; branches 147/198/314)
- `LOCATION_SHIFT` (LOS3A door)
- `FUNCTION_CHANGED` (ALT79B room functions)
- `UNDOCUMENTED_WORK` (IZM12 pile repair)
- `AREA_RECALCULATION` (POL16)
- `OTHER`

### 3.5 Object-level split and the frozen test

- **Split unit = `object_group_id`**, not just `object_id`. Several корпуса of one complex share a typical project. For example, «Полярная, 25 — ДОО» and «Полярная, 25 — СОШ» must stay in one split. The default is `object_group_id = object_id`, and the curator can merge groups.
- **Sticky registry** `object_splits(object_group_id → split)`: once assigned, never changed. New groups are assigned at release time by greedy stratified allocation. The targets are 70/15/15 by group count, and the allocation balances positives per section/type. It is deterministic (seeded by `sha256(object_group_id || salt)` order).
- **Frozen internal `HIDDEN_TEST`:**
  - `test_sets(test_set_id, manifest_sha256, object_group_ids, frozen_at, frozen_by)` is created **before the first training job**.
  - Adding objects creates `test_set v2` with a new hash; old results stay bound to the old hash.
  - Every evaluator access writes `test_access_log` (who, model, purpose) and **re-verifies the hash**; a mismatch aborts the run (MLF-62).
- **Anti-leakage enforcement:**
  1. The trainer receives only `train.jsonl` and `validation.jsonl` paths. It asserts that no item has `split=HIDDEN_TEST` and that no `object_group_id` from the test manifest appears in its input.
  2. τ is selected on VALIDATION only.
  3. Test results are exposed **only as aggregates** to ML engineers (no per-item drill-down, so no "ручная донастройка" on the test); per-item test errors are visible only to the admin with an audit record.
  4. A property test checks that no `object_group_id` appears in two splits across all versions.
- The organizer's hidden test is separate: we never see it. `inspector-eval` verifies its SHA-256 when the organizers pass `--gold-sha256`.

### 3.6 AI verdict, system comments, disputes, `suggested_fix`

Node calls `POST /internal/ml/ai-verdict` synchronously **after** the decision is committed (timeout 800 ms). If the ML service is unavailable, `ai_verdict=UNAVAILABLE`, the decision is still saved (never blocked), and the verdict is recomputed asynchronously from the queue.

Deterministic rules (evaluated first) plus the score:

| Inspector reason | AI DISAGREE when… | Otherwise |
|---|---|---|
| OCR_ERROR | both values come from `TEXT_LAYER`/DOCX/XML (no OCR involved) with extraction confidence ≥ 0.98, or OCR confidence ≥ 0.97 and C5 has no confusion pair explaining the difference | AGREE |
| WRONG_REVISION | the registry shows the used revision is the latest APPROVED/FOR_CONSTRUCTION with no successor and no conflict | AGREE |
| NOT_APPLICABLE | the applicability rules for the object type mark the parameter applicable | AGREE |
| WITHIN_TOLERANCE | \|Δ\| > trigger + ε_p (clearly beyond the normative trigger) | AGREE |
| BINDING_ERROR / EXTRACTION_ERROR | C4 similarity ≥ 0.9 on both sides and value consistency across occurrences | AGREE |
| any | C1 score ≥ 0.95 **and** `delta_over_trigger` ≥ 3 | AGREE |

System comments are Russian templates. The first two reproduce the ТЗ verbatim:
- AGREE: «Результат инспектора: NEGATIVE_VERIFIED. Причина: {reason_code}. Запись включена в черновик следующей версии набора данных; её использование для обучения допускается только после проверки куратором данных и выпуска dataset_version».
- DISAGREE: «Статус: CLARIFICATION_REQUIRED. Показаны точные страницы и доказательные фрагменты. До повторного решения инспектора запись не включается в GOLD и не передаётся во внешнюю систему». It is followed by «Основание: …» (e.g. «значение извлечено из текстового слоя PDF без OCR, уверенность 0,99»).
- CONFIRMED (our wording, consistent with §9.4 row 3): «Результат инспектора: CONFIRMED_VIOLATION. Запись сохранена как положительный GOLD-кандидат; передача во внешнюю систему — только после финализации протокола; включение в dataset_version — после финализации и проверки куратором данных».
- CLARIFICATION: «Статус: CLARIFICATION_REQUIRED. Показаны источники, координаты и конфликт редакций. Запись не включается в GOLD».

On DISAGREE, the service writes a Dispute_Log row (`OPEN`) and sets the item to `DISPUTED`. The finding's verification status becomes `CLARIFICATION_REQUIRED` until the inspector re-decides. The original decision stays immutable in Audit_Log. B03 shows an inline banner with «Подтвердить отклонение» / «Подтвердить нарушение» (one click, MLF-70). Because finalization is allowed with CLARIFICATION_REQUIRED (§9.3 p.4), a dispute never blocks finalization.

`suggested_fix` (JSONB) is generated per rejection from the reason code, features and aggregates: `{target: TOLERANCE|ANCHORS|REGEX|OCR_LEXICON|LINKAGE_RULES|APPLICABILITY|CHANGE_PATTERNS, param_code, proposal_ru, evidence}`. Examples: «Добавить синоним "S застр." к якорям M-001»; «Проверить regex_pattern M-055: извлечено "В3" вместо "B30"».

### 3.7 Training pipeline (Python worker `trainer`)

1. **Trigger:** an ML engineer calls `POST /api/v1/ml/training-jobs {dataset_version (RELEASED only), base_model_version, config_preset}` → 202 `{job_id}`. The scheduler never starts training on its own; the weekly report only *recommends* it.
2. **Load:** the manifest is read and every split file hash verified. Assertions: no HIDDEN_TEST, only eligible labels, no SUSPICION/CANDIDATE.
3. **Features:** built from stored snapshots. If `feature_schema_version` differs, features are recomputed from Checks/Evidence_Fragments through `inspector_ml.features`.
4. **Fit C1:** GroupKFold (k = min(5, #groups)) by `object_group_id`; LR vs HGB model selection; calibration.
5. **Select C2** on VALIDATION.
6. **Rebuild C3–C6.**
7. **Package the bundle** `models/<model_version>/`: `scorer.joblib, coef.json, thresholds.json, tolerances.json, anchors.parquet, ocr_lexicon.json, change_patterns.json, feature_schema.json, training_config.yaml, lineage.json` (dataset_version plus split hashes, matrix_version, parent model, git SHA, image digest, lockfile hash, seeds). Then build a deterministic tar (sorted entries, `mtime=0`, gzip `mtime=0`) and compute `artifact_hash = SHA-256`. Also compute `semantic_hash` = SHA-256 of the canonical JSON of coefficients, thresholds and tables, in case pickle bytes differ across library builds.
8. **Enqueue evaluation** (`ml.evaluation.requested`) for VALIDATION plus the frozen HIDDEN_TEST plus the OCR benchmark, for both the candidate and the current active model.
9. **Record** an ML_Retraining_Log row and a Model_Versions row (`TRAINED`); emit `ml.training.completed`.

Failures: at most 30 minutes, 1 automatic retry on infrastructure errors (not on data errors) → `FAILED` with the error, an admin notification and a metric.

### 3.8 Evaluation service and regression gate

- **Offline replay mode** (default for C1/C2/C3 changes): stored evidence-group features are re-scored with the candidate bundle, and predictions are regenerated in the GOLD schema.
- **Re-run mode** (when C4/C5/C6 change, since they affect extraction and linkage): the extraction and comparison stages are re-run on the test objects from the Redis/parse cache (parsed by file hash), so there is no OCR recomputation.
- Metrics always come from the **same `inspector_eval` library** as the CLI, so there is one source of truth.
- **Gate** (`gate_config.yaml`, versioned with matrix_version):
  - A. **§14.3 thresholds on the frozen HIDDEN_TEST (point estimate):** CA ≥ 0,95 (on the OCR benchmark), EM ≥ 0,90, linkage ≥ 0,95, localization ≥ 0,95, P ≥ 0,90, R ≥ 0,80, F1 ≥ 0,85, FPR ≤ 0,10. A NOT_EVALUATED metric counts as a **fail**.
  - B. **Recall regression per mandatory category** with ≥ 1 positive: `recall_new − recall_prev ≥ −0.02`, computed with `fractions.Fraction` so the boundary is exact (−2.0 pp passes, −2.1 pp fails). With small n this literally means "no newly missed positive"; we apply it literally and show n.
  - C. **FPR regression:** `fpr_new − fpr_prev ≤ 0.02` on inspector-verified negative groups, and separately on outdated-revision cases.
  - D. **Integrity:** dataset RELEASED; split hashes match; frozen test hash matches; artifact hash verified; lineage complete.
  - The verdict is the AND of all checks. `gate_result` JSON stores every check with its values, n and CI.
- **Mandatory categories** (decision D5; default): every matrix section present in the test (ПЗ, СПЗУ, АР, КР, ИОС1–5, ППМ, ОДИ, ЗУ, ПОС, ПОД, ООС, СМ), every `discrepancy_type`, and the aggregate of HIGH-priority parameters (106 of 132 are «HIGH — обязательная экспертная проверка», 26 are MEDIUM, there are no LOW). A category with 0 positives is reported as «не оценено (нет примеров)» and is not a pass.

### 3.9 Publication, signature, deploy, rollback

- `POST /models/{v}/submit-for-approval` (ML engineer) → `PENDING_APPROVAL`, allowed only if `gate_passed`.
- `POST /models/{v}/approve {decision, comment, password}` is **role ML_APPROVER («Ответственное лицо»)** and is subject to **four-eyes**: the approver must differ from the job's requester.
  - Server flow: re-authenticate with the password (step-up), build the canonical decision JSON `{model_version, artifact_hash, semantic_hash, dataset_version, split_hashes, matrix_version, metrics_digest, gate_result_digest, decision, comment, user_id, role, timestamp, ip}`, compute its SHA-256, and sign it with Ed25519 (server key). All of it is stored in `model_versions.approval_signature`.
  - A `Signer` interface allows a CryptoPro/УКЭП implementation later (MLF-74).
  - A gate failure returns 409.
- `POST /models/{v}/deploy` works for APPROVED only. It sets the single active pointer, `deployed_at` and `rollback_to = previous active`, and publishes `ml.model.deployed`. Scoring workers load the bundle, **verify `artifact_hash`** and swap atomically; a hash mismatch means refusing the new bundle and alerting.
- `POST /models/rollback {to_version?, reason}` (approver or admin; reason mandatory) activates `rollback_to` (or a chosen APPROVED version) and publishes `ml.model.rolled_back`. It is audited.
- Protocols already created keep their recorded `model_version`; new runs use the new active version.
- `GET /models/{v}/decision/verify` re-computes the digest and checks the signature.

### 3.10 Evaluation harness `inspector-eval` (standalone; organizers can run it)

**CLI:**
```
inspector-eval run  --gold GOLD.(xlsx|csv|json|jsonl) [--gold-sha256 HEX] --pred PRED.(jsonl|json|xlsx)
                    [--ocr-gold zones.jsonl --ocr-pred ocr_pred.jsonl]
                    [--keyfields-gold kf.jsonl --keyfields-pred kf_pred.jsonl]
                    [--page-geometry pages.jsonl] [--matrix matrix.csv] [--split HIDDEN_TEST]
                    [--loc-mode fragment|union] [--iou 0.5] [--unlabeled strict|ignore]
                    [--bootstrap 2000 --seed 20260927] [--no-per-item] --out DIR
inspector-eval validate --gold FILE      # schema check against СХЕМА GOLD, lists missing mandatory fields
inspector-eval hash FILE                 # SHA-256
```
- Exit codes: 0 = accepted, 2 = a threshold failed or a metric is NOT_EVALUATED, 1 = error.
- Outputs: `metrics.json`, `report.html` (plus an optional `report.pdf`), `per_group.csv` (suppressed by `--no-per-item`), `summary.txt`.
- The tool is offline and has no DB.
- A companion contract, owned by Modules 1–2 and coordinated by B06 (task T15): `inspector-batch --input DIR --registry registry.csv --out predictions.jsonl` produces predictions in the same GOLD schema minus the expert fields, plus `score, risk_level, abstain_reason, verification_source`. `inspector-ocr --zones zones.jsonl --out ocr_pred.jsonl` returns `{zone_id, text, status: OK|LOW_QUALITY|ABSTAIN, confidence}`.

**Metric definitions** (published in the harness README as "установленная нормализация"):

1. **OCR** (MLF-35..37). Zones are `{zone_id, file_id, page, shape, text, excluded: null|HANDWRITTEN|ILLEGIBLE, case_sensitive}`.
   - Normalization: NFC, collapse `\s+` to a single space, trim; case-fold only when `case_sensitive=false`; punctuation and signs are never removed.
   - `CA = 1 − ΣLev(ref,hyp)/Σlen(ref)` over non-excluded zones (micro); `CER = 1 − CA`; `WER` = word-level Levenshtein over token sequences divided by Σ ref words (rapidfuzz works on token lists).
   - **Abstention on an evaluable zone counts as full deletion** (strict primary). "CA on covered zones" is reported as secondary.
   - `coverage` = share of evaluable zones with status OK. `excluded_share` = share of excluded zones. `abstain_compliance` = share of excluded zones where the system returned LOW_QUALITY/ABSTAIN.
2. **Key-field Exact Match** (MLF-38).
   - Fields: `document_code, doc_stage, revision, sheet, page, element_ref`.
   - They are derived automatically from the GOLD source columns (`source_*_code/stage/revision/page`), plus the optional keyfields file (for `element_ref` and title-block fields).
   - Normalization: NFC plus whitespace; stage canonicalization `{П, ПД, PD}→PD`, `{Р, РД, RD}→RD`, `{ИД, ID}→ID`; sheet and page compared as integers; codes and revisions case- and sign-preserving (a strict variant is primary; a homoglyph-folded variant is reported as secondary).
   - Reported per field and pooled.
3. **Linkage** (MLF-39): a group is correct iff `object_id` matches and, for every GOLD source role, the predicted `stage, code, revision` equal the GOLD ones (the actual revision). Denominator = all GOLD groups that have sources. A missing predicted group counts as incorrect.
4. **Localization** (MLF-40).
   - Geometry: normalized [0;1], top-left origin of the visible page. When predictions arrive in PDF user space, `normalize(bbox, mediabox, cropbox, rotate)` translates by the CropBox origin, flips y, applies the /Rotate clockwise and divides by the displayed width and height. It is unit-tested for 0/90/180/270 rotation and offset CropBoxes.
   - Per (file_id, page): Hungarian assignment (scipy `linear_sum_assignment`) of GOLD shapes to predicted shapes on IoU (shapely polygons; bbox fast path).
   - A group is localized iff **every** GOLD shape (roles EXPECTED/ACTUAL, excluding `COMPARED_AREA`) has a match with the exact file_id, exact page and IoU ≥ 0.5.
   - Metric = share of localized groups among GOLD groups with shapes. `--loc-mode union` (union-polygon IoU per page) is diagnostic only.
5. **Detection P/R/F1** (MLF-41).
   - Positive GOLD = `CONFIRMED_VIOLATION`. A positive prediction = system `CANDIDATE` (the system cannot confirm, per §9.2).
   - Matching: for each object, pair GOLD and predicted groups with the **same matrix_code** (or the same `rule_version`/`discrepancy_type` for free-search rules), using Hungarian assignment on mean IoU so several findings of one parameter can be told apart (e.g. the ventilation item 3 rooms).
   - **TP** needs the correct code and localization pass (МЕТРИКИ: «Без полного доказательства finding не засчитывается»). A right code with wrong evidence counts as FP plus FN.
   - GOLD positives on which the system abstained (MISSING_EVIDENCE / NOT_COMPARABLE / CLARIFICATION_REQUIRED) count as FN and are also reported as `abstained_positives`.
   - Unmatched predicted CANDIDATEs on (object, code) pairs absent from GOLD: `--unlabeled strict` (default) counts them as FP; `ignore` reports them separately (depends on whether GOLD is exhaustive; see §6).
6. **FPR** (MLF-42): FP/(FP+TN).
   - Over GOLD `NEGATIVE_VERIFIED` groups: a system CANDIDATE on the group is FP; any non-positive status is TN.
   - Separately over **outdated-revision cases** (`case_tags ∋ OUTDATED_REVISION`, or derived from a SUPERSEDED source in the manifest): a CANDIDATE whose expected source is the superseded revision, or any CANDIDATE on a group whose GOLD is negative, is FP.
   - Reported per set and combined.
7. **Status accuracy for the §14.2 classes** (extra, not a threshold): accuracy of MISSING_EVIDENCE / NOT_APPLICABLE / CLARIFICATION_REQUIRED on GOLD groups of those classes. **Unsafe-conclusion rate** = CANDIDATE on groups whose GOLD is MISSING/NA/CONFLICT.
8. **Breakdowns** (MLF-43):
   - Pooled micro (primary) and per-object table plus macro average.
   - `by_section`: the matrix section from the code via the bundled matrix CSV, with free search as «СВОБОДНЫЙ ПОИСК».
   - `by_discrepancy_type` and `by_priority`.
9. **Uncertainty** (MLF-44): for every proportion we report `n` and a Wilson 95% CI. We also report an **object-cluster bootstrap** CI (resampling `object_group_id`, B = 2000, fixed seed; percentile), and it is the primary CI for P/R/F1/FPR. With fewer than 5 clusters the bootstrap is marked "insufficient clusters" and Wilson is used. Coverage and abstention are reported with each metric.
10. **Verdict** (MLF-45): a `thresholds[]` list of `{metric, threshold, value, ci_low, ci_high, n, status: PASS|FAIL|NOT_EVALUATED}`. `accepted = all PASS`. `failed[]` lists the reasons.

`metrics.json` also echoes `gold_sha256`, `pred_sha256`, harness version and the set of `model_version / dataset_version / matrix_version / input_manifest_hash` values seen in the predictions (§14.2 «Версионность»). It warns if predictions lack them.

### 3.11 Weekly report (Module 10)

- **Schedule:** Monday 09:00 Europe/Moscow, covering the previous ISO week (APScheduler in the `reporter` worker; configurable via `PUT /api/v1/ml/reports/weekly/schedule`). It is idempotent (unique `period_start, kind`), retried 3 times, and failures alert the admin. Ad-hoc generation for any period (`kind=AD_HOC`) is available from the UI (used in the demo).
- **Content** (JSON is the source of truth; HTML and PDF are rendered from it with Jinja2 plus matplotlib SVG charts and WeasyPrint with embedded DejaVu/PT Sans for Cyrillic):
  - `meta`: period, generated_at, active model (version, deployed_at, dataset_version, matrix_version).
  - `volume`: protocols created/finalized, groups compared, candidates, confirmed, rejected, clarifications, disputes.
  - `rejections`: `by_reason_code` (count, share, Δ vs previous week), `by_param` (candidates, rejected, rejection rate with Wilson CI, top reason, section), `by_section`, `by_stage_pair`, `by_extraction_method`, `by_model_version`. All data is aggregate; there is no ranking of individual inspectors (152-ФЗ, HR sensitivity).
  - `online_quality`: precision proxy = confirmed/(confirmed + rejected) per param and section with an 8-week trend. **Audit-sample FN estimate** from randomly reviewed system negatives (MLF-68), with CI.
  - `disputes`: opened, upheld, changed, still open; the AI-agreement rate.
  - `data_quality`: MISSING_EVIDENCE / NOT_COMPARABLE / CLARIFICATION rates, OCR LOW_QUALITY/ABSTAIN share, parse failures and timeouts (from Module 12 logs).
  - `drift`: PSI (10 quantile bins, ε-smoothing) vs the training dataset for key features (OCR confidence, `delta_over_trigger`, extraction-method mix, scan share, page-size mix) and for the score. χ² for categorical features. Status is `OK` (< 0.10), `MODERATE` (< 0.25) or `SIGNIFICANT`, and «недостаточно данных» when n < 100.
  - `dataset`: draft version, items pending curation (oldest age), accepted-unreleased, coverage gaps vs targets per category.
  - `models`: pending approvals, last gate result, rollbacks.
  - `recommendations[]`: `{id, priority, category, target, evidence, text_ru, owner: ML_ENGINEER|ADMIN_NORMATIVE|CURATOR}`.
- **Recommendation rules** (minimum support n ≥ 5; never auto-applied; normative changes are routed to the admin per MLF-71):
  - R1: rejection rate ≥ 50% with WITHIN_TOLERANCE dominant → calibrate ε_p (e.g. «M-002: 7 из 9 отклонений — округление; рекомендован допуск 0,05 м²; нормативный порог 1% не изменять»).
  - R2: BINDING_ERROR dominant → anchor/regex review with the top mis-bound phrases.
  - R3: OCR_ERROR ≥ 30% on scans → lexicon or preprocessing, with the confusion pairs.
  - R4: WRONG_REVISION ≥ 3 → registry and linkage rules (Module 1).
  - R5: APPROVED_CHANGE frequent → improve C6 or request change documents in the registry.
  - R6: NOT_APPLICABLE frequent for an object type → applicability rule (admin).
  - R7: PSI ≥ 0.25 → investigate or retrain on the latest dataset_version.
  - R8: precision proxy < 0.90 for 2 consecutive weeks → retrain.
  - R9: coverage gap → data-collection request to the curator.
  - R10: items pending curation > 7 days → curator reminder.
  - R11: models trained on revoked items → retrain.
- **Delivery:** a Weekly_Reports row with 3 files and their SHA-256, an in-app notification to ML_ENGINEER/ML_APPROVER users, and an e-mail (HTML summary plus PDF attachment plus link; SMTP, MailHog in docker-compose). Telegram is optional (MOCKED unless a token is configured). Downloads are RBAC-protected.

### 3.12 Bootstrap corpus: pilot plus synthetic plus simulated inspector

**Pilot GOLD builder** (`pilot/`):
1. Parse «ПРИМЕРЫ РАЗМЕТКИ» (9 groups) with the compact-notation loader.
2. Extract the overlay rectangles from the tail of each pilot page's content stream (stroke width 4 = evidence, 3 = callout, 2.5 = leader). Cross-check against the sheet bboxes; the test is IoU = 1.0 within tolerance.
3. Page → finding map (verified):

   | Pages | Finding |
   |---|---|
   | 2–5 | ALT79B (PD 19/20, RD 4/5) |
   | 6–8 | UNDMS (PD 16, RD 10, RD 4 change sheet) |
   | 9–10 | IZM12 (RD 4, ID 15) |
   | 11–13 | LOS3A (PD 41, RD 15, RD 8) |
   | 14 | OKT103 (ID 1, raster scan → OCR path) |
   | 15–16 | POL16 |
   | 17–18 | DOO25 |
   | 19–20 | SOSH25 |
   | 21–24 | POL17 (negative, no overlay) |

4. Produce **clean copies** by truncating the overlay.
5. Hand-author **registries** for the 9 objects: file_ids from the sheet; `sheet_page_range` maps each extracted single-page file to its original page number (the registry field «соответствие листа странице PDF»); revisions and approvals are assumed and marked as such.
6. **OCR GOLD surrogate:** render the vector pages at 300 dpi and use their own text layer as the reference transcription. Handwritten zones such as the signatures on p.14 are tagged `excluded`.
7. The ventilation 6-page set (АНО/150321, 3 items → **5 atomic findings**: 012 configuration; 267/270/271/272 warm floor missing; 140/142 local exhausts missing; 147/198 changed; 314 changed) is imported as **CANDIDATE** (decision D4). It demonstrates atomic splitting.

**Synthetic generator** (`synth/`; ReportLab/python-docx/XML; deterministic seed):
- About 150 objects in ~130 object groups, split by group into train/validation/test of about 100/25/25 objects.
- Each object has a registry (§3 fields), revision chains and PD/RD/ID documents: ТЭП tables, room explications, КЖ/КМ specifications, door schedules, АОСР acts, geodetic schemes with tolerance tables.
- Parameters: about 30–40 table- or numeric-extractable ones (M-001..004, 007, 008, 010, 012, 019, 022, 023, 030, 040–042, 055–059, 062, 069, 071, 078, 103, 105, 116–118, 121, 125, 126, 132), plus explication-level configuration types mirroring the pilot (room function/area change, room added/removed).
- Injected case mix per object (targets): true violations about 20% of compared groups; benign rounding (e.g. 2797,27 vs 2797,3); approved changes with a «Корректировка №» note plus a registry change document; outdated revisions (superseded PD differs, approved PD matches); MISSING_EVIDENCE (ID absent); NOT_APPLICABLE (gas M-018 without gas supply); revision conflicts (two APPROVED revisions without a predecessor link); header synonyms; unit variants (м2/м²/кв.м).
- Document noise: about 30% rasterized at 200–300 dpi with blur, ±1.5° skew and JPEG artifacts; **/Rotate 90/270 and offset CropBox** pages; DOCX and XML variants.
- Ground truth by construction: GOLD in the «СХЕМА GOLD» format with exact normalized shapes, OCR zones and key fields.
- **Simulated inspector** (it drives the **real API**, so the audit, logs and events are genuine):
  - Confirms a CANDIDATE that matches a GOLD positive.
  - Rejects the others with the reason code implied by the trap type (OCR_ERROR, APPROVED_CHANGE plus ref, WRONG_REVISION, WITHIN_TOLERANCE, BINDING_ERROR).
  - Asks for clarification with p = 0.05.
  - Makes a wrong decision with p = 0.03, which lets the AI dispute and DISPUTED-state paths fire.
  - Finalizes protocols; a simulated curator accepts eligible items.
- The loop runs in "weeks": run 1 with `rules-baseline-1.0` → feedback → `gold-1.0.0` → train `m-1.0.0` → gate → approve → deploy → run 2 shows higher precision and lower FPR in the weekly report. A deliberately bad preset (τ too high) produces `m-1.0.1-bad`, which fails the gate (e.g. «Recall КР −6,7 п.п.»), for the demo.
- Everything synthetic carries `source_type=SYNTHETIC`, and the UI shows a «Синтетические данные» badge.

### 3.13 Data model (PostgreSQL; ТЗ names kept as snake_case)

```sql
-- §10 #6
rejection_log(id uuid pk, violation_id uuid /*finding id (Checks)*/, evidence_group_id text, protocol_id uuid, protocol_version int,
  object_id text, param_code text, section text, decision_id uuid /*B03*/, rejection_reason text /*reason_code enum*/,
  inspector_comment text, corrected_value text null, inspector_id text /*pseudonymous*/, decided_at timestamptz,
  ai_verdict text check (ai_verdict in ('AGREE','DISAGREE','UNAVAILABLE')), ai_confidence real, ai_rationale jsonb, ai_comment text,
  suggested_fix jsonb, retraining_status text /*NEW|IN_DRAFT|DISPUTED|CURATOR_ACCEPTED|CURATOR_EXCLUDED|RELEASED|USED_IN_TRAINING|REVOKED*/,
  model_version text, matrix_version text, created_at timestamptz default now());
-- §10 #7
dispute_log(id uuid pk, violation_id uuid, evidence_group_id text, rejection_log_id uuid, inspector_comment text, ai_comment text,
  resolution_status text /*OPEN|RESOLVED_UPHELD|RESOLVED_CHANGED|RESOLVED_CLARIFICATION|ESCALATED*/, resolved_by text, resolved_at timestamptz,
  resolution_comment text, created_at timestamptz);
-- §10 #15 (immutable per-version snapshot rows; dataset_version='draft:<next>' for the rolling draft)
dataset_items(id uuid pk, item_key uuid /*stable across versions*/, evidence_group_id text, finding_id text, object_id text, object_group_id text,
  gold_label text check (gold_label in ('POSITIVE','NEGATIVE')), finding_status text, verification_source text check (verification_source='INSPECTOR'),
  matrix_code text, rule_version text, section text, discrepancy_type text, case_tags text[],
  expert_id text, decided_at timestamptz, reason_code text, expert_comment text,
  evidence_card jsonb /*full СХЕМА GOLD record*/, evidence_card_sha256 text, features_json jsonb, feature_schema_version text,
  source_type text /*PRODUCTION|PILOT|SYNTHETIC|IMPORTED*/, item_status text, eligibility_errors jsonb, disputed bool default false, stale_matrix bool default false,
  curator_id text, curated_at timestamptz, curator_comment text,
  dataset_version text, split text check (split in ('TRAIN','VALIDATION','HIDDEN_TEST') or split is null),
  protocol_id uuid, protocol_version int, protocol_finalized_at timestamptz, matrix_version text, created_at timestamptz,
  check (finding_status in ('CONFIRMED_VIOLATION','NEGATIVE_VERIFIED')));
dataset_versions(dataset_version text pk, status text, parent_version text, matrix_version text, created_by text, released_by text, released_at timestamptz,
  manifest_uri text, manifest_sha256 text, split_hashes jsonb, counts jsonb, coverage_report jsonb, test_set_id text, release_notes text);
object_splits(object_group_id text pk, split text, assigned_at timestamptz, assigned_in_version text);
test_sets(test_set_id text pk, manifest_sha256 text, object_group_ids text[], frozen_at timestamptz, frozen_by text);
test_access_log(id bigserial, test_set_id text, user_id text, model_version text, purpose text, hash_ok bool, at timestamptz);
-- §10 #16
model_versions(model_version text pk, parent_model_version text, artifact_uri text, artifact_hash text, semantic_hash text, components jsonb,
  dataset_version text, matrix_version text, feature_schema_version text, training_job_id uuid, metrics_json jsonb, gate_result jsonb, gate_passed bool,
  approval_status text, approved_by text, approved_at timestamptz, approval_signature jsonb /*digest, sig, signer, alg*/, decision_comment text,
  deployed_at timestamptz, deployed_by text, rollback_to text, rolled_back_at timestamptz, rollback_reason text, is_active bool default false,
  trained_on_revoked bool default false, created_at timestamptz);
-- §10 #11 (one row per iteration, incl. failed/rejected)
ml_retraining_log(id uuid pk, model_version text, base_model_version text, dataset_version text, matrix_version text, split_hashes jsonb,
  precision real, recall real, f1 real, false_positive_rate real, per_category_metrics jsonb, metrics_validation jsonb, metrics_test jsonb, ci jsonb,
  coverage jsonb, gate_checks jsonb, training_params jsonb, code_version jsonb /*git sha, image digest, lock hash*/, seeds jsonb,
  status text /*QUEUED|RUNNING|SUCCEEDED|FAILED*/, error text, logs_uri text, requested_by text, started_at timestamptz, finished_at timestamptz,
  approval_status text, approved_by text, decision_at timestamptz);
eval_runs(id uuid pk, kind text /*VALIDATION|HIDDEN_TEST|OCR_BENCH|EXTERNAL_GOLD|PILOT|SYNTHETIC*/, model_version text, dataset_version text,
  gold_sha256 text, pred_sha256 text, metrics_json jsonb, report_uris jsonb, created_by text, created_at timestamptz);
weekly_reports(id uuid pk, kind text /*WEEKLY|AD_HOC*/, period_start timestamptz, period_end timestamptz, generated_at timestamptz, status text,
  files jsonb /*{json:{uri,sha256},html:{…},pdf:{…}}*/, summary jsonb, delivered jsonb, active_model_version text, unique(kind, period_start));
audit_sample(id uuid pk, evidence_group_id text, protocol_id uuid, sampled_at timestamptz, reviewer_id text, outcome text, reviewed_at timestamptz);
```
DB-level guards:
- The CHECKs above guarantee no CANDIDATE, SUSPICION, MISSING_EVIDENCE or SYSTEM-sourced rows.
- A trigger forbids UPDATE of released rows (`dataset_version NOT LIKE 'draft:%'`).
- `model_versions` rows are append-only apart from state columns.

### 3.14 REST endpoints (Node public API; OpenAPI 3.0; all mutating calls audited)

| Method, path | Role | Request → Response |
|---|---|---|
| GET `/api/v1/feedback/rejections` | ML_ENG, CURATOR | filters `from,to,param,section,reason,status,model_version` → paged Rejection_Log with `ai_verdict, suggested_fix` |
| GET `/api/v1/feedback/disputes` · POST `/…/disputes/{id}/escalate` | ML_ENG, SUPERVISOR | → Dispute_Log |
| GET `/api/v1/ml/active-versions` | any service | → `{model_version, dataset_version, matrix_version, artifact_hash}` (B02 stamps protocols) |
| GET `/api/v1/datasets/draft/items` | CURATOR | `status=PENDING_CURATION&section&type` → items plus evidence card links |
| POST `/api/v1/datasets/draft/items/{id}/curate` · `/bulk-curate` | CURATOR (≠ deciding inspector) | `{action: ACCEPT|EXCLUDE|RETURN, comment}` → item (bulk refuses `disputed=true`) |
| POST `/api/v1/datasets/versions` | CURATOR | `{notes}` → 202 `{dataset_version, status: IN_REVIEW, coverage_report, split_preview}` |
| POST `/api/v1/datasets/versions/{v}/release` | CURATOR | → `{manifest_sha256, split_hashes, counts}`; 409 if coverage blockers remain |
| GET `/api/v1/datasets/versions[/{v}]` · GET `/{v}/diff?against=` | ML_ENG, CURATOR | → list / manifest / diff |
| GET `/api/v1/datasets/versions/{v}/export?format=jsonl|xlsx|csv&split=` | ML_ENG (HIDDEN_TEST: ADMIN only) | → file in the СХЕМА GOLD format |
| POST `/api/v1/datasets/import` | ADMIN | multipart GOLD file plus `source_type` → 202 import job |
| POST `/api/v1/datasets/test-sets` · GET `/…/test-sets` | ADMIN | freeze → `{test_set_id, manifest_sha256}` |
| POST `/api/v1/ml/training-jobs` · GET `/…/{id}` | ML_ENG | `{dataset_version, base_model_version, config_preset}` → 202 `{job_id}` / status, progress, log tail |
| GET `/api/v1/ml/models[/{v}]` | ML_ENG, APPROVER | → registry, lineage, metrics vs previous, gate checklist |
| POST `/api/v1/ml/models/{v}/submit-for-approval` | ML_ENG | → PENDING_APPROVAL (409 if gate failed) |
| POST `/api/v1/ml/models/{v}/approve` | APPROVER (≠ requester) | `{decision: APPROVE|REJECT, comment, password}` → `{approval_signature}`; 409 or 403 |
| POST `/api/v1/ml/models/{v}/deploy` · POST `/api/v1/ml/models/rollback` | APPROVER, ADMIN | `{}` / `{to_version?, reason}` → active model |
| GET `/api/v1/ml/models/{v}/decision/verify` | ML_ENG, APPROVER, ADMIN | → `{digest_ok, signature_ok}` |
| POST `/api/v1/ml/evaluations` · GET `/…/{id}` | ML_ENG | `{model_version, dataset_version, split}` or multipart `{gold, pred, ocr_gold?, …}` → 202 / metrics JSON plus report links (test split: aggregates only) |
| GET `/api/v1/ml/reports/weekly[/{id}]?format=json|html|pdf` · POST `/api/v1/ml/reports/weekly` | ML_ENG, APPROVER | list / file / 202 ad-hoc `{period_start, period_end}` |
| GET/PUT `/api/v1/ml/reports/weekly/schedule` | ADMIN | `{cron, tz, recipients, channels}` |
| GET/POST `/api/v1/ml/audit-sample` | INSPECTOR, ML_ENG | sampling queue and outcomes (MLF-68) |

Internal (Python FastAPI, not exposed publicly): `POST /internal/ml/score` (batch `{groups:[{evidence_group_id, features}]}` → `{score, risk_level, preliminary_status, top_features}`) and `POST /internal/ml/ai-verdict` (`{decision, reason_code, evidence_group}` → `{ai_verdict, confidence, rationale, ai_comment, suggested_fix}`).

### 3.15 RabbitMQ

- Exchanges: `inspector.events` (topic), `inspector.jobs` (direct), DLX `inspector.dlx` (with a parking queue).
- Every message carries the envelope `{message_id, correlation_id(request_id), schema_version, occurred_at, producer}`. Consumers are idempotent (dedupe table keyed by `message_id`); delivery is manual-ack with 3 retries and exponential backoff, then DLX.

| Routing key | Producer → consumer | Payload (essentials) |
|---|---|---|
| `verification.decision.recorded` | Node/B03 → feedback-consumer | `decision_id, finding_id, evidence_group_id, protocol_id, protocol_version, object_id, param_code, decision, reason_code, comment, inspector_id, decided_at, model_version, matrix_version, supersedes_decision_id?` |
| `protocol.finalized` / `protocol.finalization_cancelled` | B03 → feedback-consumer | `protocol_id, version, at, by, reason?` → promote to PENDING_CURATION / suspend or revoke |
| `dataset.version.released` | Node → reporter, UI notifier | `dataset_version, manifest_sha256, counts` |
| `ml.training.requested` (queue `ml.training`) | Node → trainer | `job_id, dataset_version, base_model_version, config, requested_by` |
| `ml.training.progress/completed/failed` | trainer → Node | `job_id, stage, pct, model_version?, error?` |
| `ml.evaluation.requested/completed` | trainer/Node ↔ evaluator | `eval_id, model_version, dataset_version, split, mode: REPLAY|RERUN` / `metrics_digest, gate_passed` |
| `ml.model.deployed` / `ml.model.rolled_back` (fanout) | Node → ml-service, B02 workers | `model_version, artifact_uri, artifact_hash` |
| `ml.report.weekly.requested/generated` | scheduler/Node ↔ reporter → notifier | `report_id, period, files{uri,sha256}` |
| `matrix.version.changed` | Module 8 → feedback-consumer | `matrix_version, changed_codes[]` → `stale_matrix` flags |

### 3.16 UI screens (React; Russian UI; visible by role)

1. **«Обратная связь»**: the Rejection_Log table (filters by reason, parameter, section, model, period). A row opens a drawer with the evidence card (the B03 viewer component), AI verdict, `suggested_fix` and history.
2. **«Спорные случаи»**: disputes with status, both comments, re-decision link and escalation.
3. **«Курирование данных»**: the PENDING_CURATION queue, a side-by-side PD/RD/ID page viewer with shapes, eligibility errors and «Принять / Исключить / Вернуть» (hotkeys). A disputed badge blocks bulk acceptance.
4. **«Версии набора данных»**: the draft counter and coverage heatmap (section × label × split with targets). Also release candidate creation, split preview, release, diff between versions, split hashes, frozen test hash and export.
5. **«Модели»**: the registry table, lineage (model → dataset → matrix → parent), a metrics table vs the active model with Δ pp, and the **gate checklist**: every §14.3 threshold plus the per-category regressions, with n and CI bars. Actions: «Отправить на утверждение», «Утвердить публикацию» (password modal plus decision text; disabled with a tooltip when the gate fails), «Развернуть», «Откатить» (reason required), and signature verification.
6. **«Обучение»**: start a job (dataset/preset selection) and watch its status, progress and log tail.
7. **«Оценка качества»**: upload GOLD plus predictions (plus optional OCR/key-field files) → run the harness → view the report (the same HTML as the CLI).
8. **«Еженедельные отчёты»**: the list, an inline HTML viewer, JSON/HTML/PDF download, «Сформировать сейчас», and schedule settings (admin).

In B03's verification screen, B06 supplies the inline AI banner and the one-click re-decision.

### 3.17 Libraries (minimum versions; rationale)

- Python 3.11/3.12; FastAPI ≥ 0.110 plus Pydantic 2 (typed schemas, OpenAPI for internal endpoints); aio-pika ≥ 9.4 (async RabbitMQ); SQLAlchemy ≥ 2.0 plus psycopg 3.
- Data and ML: numpy, pandas ≥ 2.2, pyarrow; scikit-learn ≥ 1.4 (LogisticRegression, HistGradientBoosting with `monotonic_cst`, CalibratedClassifierCV, GroupKFold; CPU-only, deterministic with a seed); joblib.
- Harness: scipy ≥ 1.11 (`linear_sum_assignment`); shapely ≥ 2.0 (polygon IoU); rapidfuzz ≥ 3.0 (fast Levenshtein over chars and token lists); openpyxl ≥ 3.1 (XLSX GOLD). Wilson CI is implemented in-house (a 5-line formula) to keep the CLI free of statsmodels.
- Reports: Jinja2 ≥ 3.1, matplotlib ≥ 3.8 (SVG charts), WeasyPrint ≥ 61 (PDF; needs Pango and fonts in the image); APScheduler 3.10; cryptography ≥ 42 (Ed25519).
- Bootstrap tooling: pymupdf ≥ 1.24 (pilot tools), reportlab ≥ 4, python-docx ≥ 1.1 (synthetic).
- Embeddings for C4 come from Module 1's encoder: we recommend `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` or `intfloat/multilingual-e5-small` as the "совместимый аналог" of the English-only all-MiniLM-L6-v2.
- Tests: pytest plus hypothesis (property tests on splits and metrics).
- No MLflow or DVC. The §10 tables are the registry, which avoids an extra service; this could be added later.

### 3.18 Deployment

- Image `ml-service` (python:3.11-slim plus libpango, fonts-dejavu, CPU-only, no torch in the trainer) runs 4 commands: `api | trainer | evaluator | reporter` (plus `feedback-consumer`).
- Image `inspector-eval` (slim; numpy/scipy/shapely/rapidfuzz/openpyxl/jinja2; optional weasyprint): `docker run -v $PWD:/data inspector-eval run --gold /data/gold.xlsx …`.
- Volumes: `/data/ml/{datasets,models,reports,evals}`, write-once (files are chmod 0444 after writing; hash recorded).
- Compose adds `mailhog`. Everything also runs locally without Docker (`uv venv`, env-configured `DATABASE_URL`, `AMQP_URL`, `STORAGE_ROOT`).

---

## 4. Interfaces with other blocks

| Block / module | B06 consumes | B06 produces |
|---|---|---|
| Module 1 Upload/Parsing | Files registry (file_id, sha256, stage, code, revision, approval, predecessor/successor, `sheet_page_range`, `signature_status`), page geometry (MediaBox/CropBox/Rotate), OCR confidence, extraction method, parse cache; the `inspector-ocr` zone contract | C4 anchor bank and C5 lexicon (as a published bundle); recommendations (regex, anchors, registry) |
| Module 2 Comparison/Protocol | evidence groups (Checks) plus Evidence_Fragments plus `features_json` / `feature_schema_version`; `discrepancy_type`; `inspector-batch` predictions in the GOLD schema; `input_manifest_hash` | `/internal/ml/score` (score, risk, preliminary status, top features); `GET /ml/active-versions` for stamping protocols; C3 tolerances |
| Module 3 Verification | decision events (incl. atomic split, `corrected_value`, `approved_change_ref`), finalization/un-finalization events, evidence-card viewer component | AI verdict plus system comment plus the dispute flow (a finding goes to CLARIFICATION_REQUIRED pending re-decision); a shared reason-code enum; the audit-sample queue |
| Module 5 Free search | SUSPICION records (excluded); promoted CANDIDATEs with `rule_version` | Guarantee that SUSPICION is never a positive label |
| Module 6 РиН integration | — | Nothing is transferred from datasets. The manifest includes model/dataset versions, and transfer of confirmed findings stays gated by finalization (their rule) |
| Module 7 Dashboard | — | Optional ML widget (active model, online precision) |
| Module 8 Normative base | `matrix.version.changed`, Params (section, priority, trigger, data_type) | Recommendations addressed to the admin (never auto-applied, MLF-71) |
| Module 9 Audit | Audit_Log writer API | All B06 actions audited |
| Module 11 Monitoring | Prometheus scrape, JSON log shipping, alert channels | `ml_*` metrics: job duration and status, queue depth, online precision, PSI, items pending curation, gate results |
| Module 12 Negative scenarios | common error envelope and retry policy | B06-specific failure handling (MLF-62) |
| Core platform | auth/RBAC (plus the CURATOR and ML_APPROVER roles), OpenAPI tooling, RabbitMQ topology, storage abstraction | — |

**Hard contracts to freeze first (task T01):**
1. `gold_record.schema.json`, which is also the prediction schema minus the expert fields.
2. The reason_code and discrepancy_type enums.
3. `features_json` v1 field list.
4. Decision and finalization event payloads.
5. OCR zone and key-field files.
6. `/internal/ml/score` I/O.

---

## 5. Too complex or risky items, and the simplification that still satisfies the letter

| Item | Why it is risky | Simplification that satisfies the ТЗ |
|---|---|---|
| Meaningful retraining from 9 pilot groups (1 POS, 1 NEG) | Statistically impossible; §14.1 concedes it | The bundle's C1/C2 are trained on a **labelled synthetic corpus** through the real feedback path; the pilot is used for format validation and a live demo. All synthetic metrics are labelled as such |
| Fine-tuning embeddings or a CV model on CPU (Apple Silicon Docker has no GPU) | Slow, non-deterministic, little data | Non-parametric anchor bank (C4); fine-tuning out of scope (MLF-75) |
| Full-pipeline re-evaluation for every training job (500-page OCR) | Minutes to hours | Replay mode on stored features; re-run of extraction and comparison only, from the parse cache (by file hash) |
| УКЭП signature of the publication decision | Needs CryptoPro and certificates | Step-up auth plus canonical digest plus Ed25519 behind a `Signer` interface (MLF-14/74) |
| Recall "no drop > 2 pp" on tiny categories | One miss can exceed 2 pp, so the gate often blocks | Apply it literally (effectively zero regression); show n and CI; make synthetic test categories ≥ 20 positives so the demo gate is informative |
| Online recall is unobservable (labels exist only for candidates the old model raised: selection bias) | Production-derived test sets overstate recall | Random audit sample of system negatives (MLF-68); synthetic plus organizer GOLD are exhaustive by construction |
| Protecting the hidden test from "ручная донастройка" | UI drill-down leaks per-item errors | Aggregate-only test results; admin-only per-item view with an audit record; access log plus hash check |
| Drift on low volumes | PSI is noisy below about 100 samples | Minimum-sample guard («недостаточно данных»); few features |
| PDF generation with Cyrillic in containers | Fonts and Pango dependencies | WeasyPrint with bundled fonts in the image; fallback to HTML-only with PDF printed by Chromium (Playwright) if WeasyPrint fails to build |
| Matching system groups to GOLD without shared ids | Several findings per parameter per object | (object, code) blocking plus Hungarian on IoU |
| Pilot pages contain the answer (callout text) | The pipeline would "cheat" in the demo | Clean copies via overlay truncation; the harness is always run on clean copies |
| Redaction is visual-only (text under white Ink is still extractable) | PII or sensitive text leaking into datasets and reports | Parser marks text under opaque annotations as `redacted`; it is never stored in evidence cards or exports (flag for Module 1) |
| Un-finalization after release | Released sets must stay immutable | REVOKE_PENDING → dropped in the next version; `trained_on_revoked` flag plus recommendation R11 |
| Determinism of the artifact hash | Pickle bytes can differ between library builds | Pinned lockfile plus fixed seeds plus deterministic tar; a `semantic_hash` for reproducibility checks |

---

## 6. ТЗ contradictions and ambiguities (with recommended interpretation)

1. **NEGATIVE_VERIFIED has two meanings.** It is a system-preliminary result (§9.2: «система формирует … предварительный статус CANDIDATE либо NEGATIVE_VERIFIED») and also an inspector rejection (§9.3/§9.4, "отрицательная GOLD-метка"). → Add `verification_source ∈ {SYSTEM, INSPECTOR}`; only INSPECTOR rows are GOLD (DB CHECK).
2. **"Положительный GOLD-кандидат" at confirmation vs «незавершённые решения в обучение не включаются».** → A confirmation creates a draft item; it becomes curatable only after the protocol is FINALIZED, since decisions can change before that.
3. **"Hidden test fixed before the competition"** (organizer-level) vs the system's own repeated retraining, which needs a frozen gating set. → Two notions: the organizer's external hidden test (we only run the harness on it) and our internal frozen `HIDDEN_TEST` split (the СХЕМА GOLD enum value), frozen before the first training run.
4. **«Обязательная категория» is undefined.** → Sections plus discrepancy types plus the HIGH-priority aggregate (decision D5). Note that the matrix calls HIGH «обязательная экспертная проверка».
5. **Where the "§14 thresholds" for publication are measured.** → On the internal frozen HIDDEN_TEST plus the OCR benchmark, by point estimate; CI bounds are reported. NOT_EVALUATED counts as a fail.
6. **"Рассчитываются … по объектам": micro or macro.** → Primary pooled micro over evidence groups with object-cluster bootstrap CIs; the per-object table and macro average are also reported.
7. **OCR abstention on normal zones is not specified.** → Strict: counted as deletion errors; coverage and "CA on covered zones" reported. This prevents gaming the metric by abstaining.
8. **Negative groups without bboxes** (POL17 «bbox —») vs «СХЕМА GOLD» requiring bboxes. → Negatives carry the compared zones (`COMPARED_AREA`, possibly `[0,0,1,1]`) and are excluded from the localization denominator.
9. **Semantics of `Rejection_Log.ai_verdict` are undefined.** → The AI's agreement with the inspector's rejection. DISAGREE creates a Dispute_Log row and CLARIFICATION_REQUIRED until re-decision, exactly as the §9.4 example shows. The inspector's authority is preserved: the AI never overrides, it only requests a re-decision.
10. **Is GOLD exhaustive per object?** This affects FP counting of unmatched candidates. → Default strict (FP), with `--unlabeled ignore` and a separate count; ask the organizers.
11. **"Outdated-revision cases" have no marker** in «СХЕМА GOLD». → `case_tags ∋ OUTDATED_REVISION`, or derivation from a SUPERSEDED source in the manifest.
12. **Composite headers in «СХЕМА GOLD»** (`matrix_code / rule_version`, `source_*_stage/code/revision/approval`, `expert_reason_code / comment`). → Flattened canonical names; the loader accepts both the composite and flattened forms, and the pilot compact notation.
13. **Code families:** M-001..M-132 in the matrix vs PZ-01 / KR-55 / AR-41 in §8.2. → Alias table (numbers are global: KR-55 = M-055).
14. **Roles:** §12 lists inspector, admin and ML engineer only, while §9.4 needs a «куратор данных» and an «ответственное лицо». → Add CURATOR and ML_APPROVER (decision D1).
15. **Overlap between Model_Versions and ML_Retraining_Log.** → ML_Retraining_Log holds one row per iteration, including failed and rejected ones; Model_Versions is the artifact registry plus deployment state.
16. **Violation "type"** is needed for per-type metrics but is absent from the matrix and the schema. → `discrepancy_type` extension.
17. **Module 10 says "статистика отклонений" only.** Rates need confirmations too. → Report both, plus disputes and data quality.
18. **"Минимум 100 подтверждённых нарушений … не является достаточным критерием"** gives no replacement. → Release blockers or warnings from a per-category coverage matrix (configurable minima; the demo defaults to ≥ 3 POS and ≥ 3 NEG per mandatory category in TRAIN).
19. **The "example comment when AI agrees" heading** in §9.4 contains a doubled phrase («Пример комментария ИИ при согласии с отклонением: Пример системного комментария при отклонении кандидата…»), which is an editing artefact. We use the quoted text verbatim.
20. **The pilot's "стр." values refer to pages of the original files** (e.g. ALT79B-000015 p.19), not to the pages of the compiled PDF (p.2). → The registry `sheet_page_range` maps the extracted page to the original page number, so the reported pages match GOLD.

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Roles for the data curator and the approver of model publication | (a) Add CURATOR and ML_APPROVER roles; (b) fold both into ML engineer / admin | **(a)**, with four-eyes (curator ≠ deciding inspector; approver ≠ job requester). Demo users: `inspector`, `supervisor`, `admin`, `ml_engineer`, `curator`, `approver` |
| D2 | How "signed" the publication decision must be | (a) Step-up password plus digest plus Ed25519; (b) real УКЭП (CryptoPro); (c) checkbox | **(a)** with a pluggable `Signer` |
| D3 | Can the synthetic corpus be used to demonstrate retraining and the gate? | Yes (flagged) / No (pilot only; the gate is trivial) | **Yes**, clearly badged; never claimed as real acceptance |
| D4 | Status of the ventilation 6-page set (АНО/150321) and of the 7 pilot CANDIDATEs | Import as CANDIDATE / as CONFIRMED | **CANDIDATE**. The jury or an inspector confirms them live in the demo; that is the loop |
| D5 | Definition of "mandatory category" for the gate | Sections / discrepancy types / HIGH aggregate / §14.2 classes / combination | **Sections plus discrepancy types plus the HIGH aggregate** |
| D6 | May the ML scorer suppress rule candidates into system-preliminary NEGATIVE_VERIFIED? | (a) Yes, below τ, with a note plus one-click re-open plus audit sampling; (b) rank-only, no suppression | **(a)**. Without suppression, precision ≥ 0,90 depends only on the rules and retraining cannot improve it. Keep a HIGH-priority recall floor |
| D7 | Weekly-report delivery channels | in-app / e-mail / Telegram | **In-app plus e-mail (MailHog in dev)**; Telegram only if a bot token is provided |
| D8 | External LLMs for AI comments or suggestions | Cloud LLM / local LLM / none | **None**: deterministic templates reproduce the ТЗ text exactly with no 152-ФЗ exposure; a local LLM is possible later only for `suggested_fix` wording |
| D9 | Primary metric aggregation and OCR abstention handling | micro vs macro; abstain = error vs excluded | **Micro** plus the per-object table; **abstain = error** plus coverage |
| D10 | Will the organizers run our `inspector-eval`, or their own scorer? | Ours / theirs / both | Ship **both** `inspector-eval` and `inspector-batch`, and ask the organizers for the GOLD file format and whether GOLD is exhaustive per object |
| D11 | Default weekly schedule | Mon 09:00 MSK / other | Mon 09:00 MSK, previous ISO week |

---

## 8. Data needed

| What | Why | Fallback if we never get it |
|---|---|---|
| **Приложение № 2** (sample protocol) | The protocol export fields that feed predictions and evidence cards | Predictions use the СХЕМА GOLD schema; the protocol mapping is adapted later |
| Original full files behind the pilot ids (ALT79B-000015, …) | True multi-page runs and exact page numbering | Single-page clean copies registered with `sheet_page_range` mapping to the original page numbers |
| More inspector-labelled groups (CONFIRMED plus NEGATIVE) across sections | Any real training or validation | Synthetic generator plus simulated inspector; the pilot for format |
| OCR GOLD transcriptions (printed text ≥ 300 dpi; handwritten zones marked) | MLF-35..37 on real data | Text layer of vector pilot pages rendered at 300 dpi as the reference; the synthetic corpus |
| Key-field GOLD (шифр, стадия, редакция, лист, помещение) | MLF-38 | Derived from GOLD source columns plus title blocks of vector pages plus synthetic |
| Registries (object_id, revision chains, approval) for the pilot objects | Linkage metric; outdated or conflict cases | Hand-authored registries marked as assumed |
| Organizer hidden-test format (XLSX/JSON?), SHA-256, exhaustiveness | Run-ability and FP semantics | Loader accepts XLSX/CSV/JSON/JSONL plus the composite headers; `--unlabeled` switch |
| Official list of mandatory categories and reason codes (if Мосгосстройнадзор has one) | Gate definition, taxonomy | Our taxonomy (§3.4) and D5 |
| Real volumes (decisions per week) | Sizing drift and recommendation thresholds | Configurable minimum-support thresholds |
| Who the «ответственное лицо» is | Role design | ML_APPROVER role |
| Examples of real "согласованное изменение" documents (PD amendments, experts' conclusions) | C6 patterns and APPROVED_CHANGE validation | Pilot change sheets (UNDMS p.8, LOS3A p.13, SOSH25 «Корректировка №…») plus synthetic |

---

## 9. Jury demo scenario and acceptance tests

### 9.1 Demo (about 6 minutes; synthetic items carry a badge)

1. **Confirm live (pilot):** the jury opens pilot candidate ALT79B-V01 (clean copies, with PD/RD pages side by side) and confirms it. The CONFIRMED system comment appears. Under «Курирование», the item shows as «положительный GOLD-кандидат — ожидает финализации».
2. **AI agrees:** reject a synthetic candidate with APPROVED_CHANGE plus a reference. The ТЗ-verbatim AGREE comment appears.
3. **AI disagrees:** reject another with OCR_ERROR where both values come from the text layer. The AI disagrees, the DISAGREE comment appears, the status becomes CLARIFICATION_REQUIRED and a Dispute_Log row is created. «Подтвердить отклонение» is one click, and the item is flagged `disputed`.
4. **Curate and release:** finalize the protocol. The items move to PENDING_CURATION; the curator accepts them. Release `gold-1.1.0`, then show the coverage heatmap, object-group splits, `split_hashes`, and the frozen HIDDEN_TEST hash unchanged since v1.0.0.
5. **Train and gate:** start training → `m-1.1.0`. The gate checklist shows every §14.3 threshold PASS on the synthetic test (with n and CI) and the per-section recall Δ ≥ −2 pp. The approver (a different user) re-enters the password and signs; the model is deployed, and signature verification shows ✓. Then show a pre-trained `m-1.1.1-bad`: «Recall КР −6,7 п.п. — FAIL», with «Утвердить» disabled. Then roll back to `m-1.0.0` with a reason and show the audit trail.
6. **Weekly report:** click «Сформировать сейчас». The HTML/PDF shows rejections by reason_code, parameter and section, the precision trend (week 1 vs week 2 after deploy), PSI and concrete recommendations (e.g. the M-002 tolerance). The e-mail arrives in MailHog.
7. **Terminal:** run `inspector-eval run --gold pilot_gold.xlsx --pred pilot_pred.jsonl`. It shows n=1 positive and a Wilson CI of about [0,21; 1,00] with verdict NOT ACCEPTED (insufficient sample), which illustrates §14.1. Then run on the synthetic hidden test: the full table, exit code 0, and the organizers can repeat it with `--gold-sha256`.

### 9.2 Acceptance criteria and tests

- **Metric unit tests** with hand-computed fixtures:
  - CER/WER (incl. NFC, repeated spaces, case rules, preserved signs such as «АНО/150321/1-П-ИОС5.4.2»).
  - Wilson CI (compared with reference values).
  - IoU for bbox and polygon.
  - Geometry normalization for Rotate 0/90/180/270 plus an offset CropBox.
  - Hungarian matching of two findings of the same parameter.
  - Strict detection: wrong evidence → FP plus FN.
  - FPR on negatives and outdated cases.
  - Verdict = AND, with NOT_EVALUATED failing.
- **Conformance:** the harness ingests sheet «ПРИМЕРЫ РАЗМЕТКИ» as-is. The 9 groups are parsed, and the bboxes equal the overlay rectangles extracted from the pilot PDF (IoU ≥ 0.99).
- **Label hygiene (property tests):** released datasets never contain CANDIDATE, SUSPICION, MISSING_EVIDENCE, CLARIFICATION_REQUIRED, SYSTEM-sourced rows or items from non-finalized protocols (DB CHECK plus test). A PARTIALLY_CONFIRMED label is rejected.
- **Split isolation:** no `object_group_id` appears in more than one split across all versions; the sticky assignment survives re-release.
- **Leakage guards:** the trainer aborts on HIDDEN_TEST input. A mismatched test manifest hash aborts evaluation. The test split API returns aggregates only for ML_ENG.
- **Gate boundaries:** Recall Δ = −2,0 pp passes and −2,1 pp fails (exact Fraction). FPR +2,0 pp passes and +2,1 pp fails. A §14.3 threshold failure blocks approval.
- **Publication:** approve with a failed gate returns 409; approve by the requester returns 403; approve without step-up returns 401. The signature verifies. Deploy switches the active version, and workers verify the artifact hash (a tampered file is refused). Rollback restores the previous model and writes audit entries.
- **AI verdict:** the rule table is covered (OCR_ERROR on text-layer values → DISAGREE, etc.). The ML service being down gives UNAVAILABLE, the decision is saved and verdict inference stays under 500 ms. The templates match the ТЗ strings byte-for-byte.
- **Revocation:** un-finalizing a protocol moves draft items to SUSPENDED and released items to REVOKE_PENDING; the next release drops them; the model is flagged.
- **Reproducibility:** retraining with the same dataset, config and seed yields identical metrics and `semantic_hash`.
- **Weekly report:** the JSON validates against its schema; the PDF renders Cyrillic; generation is idempotent per period; the cron fires under a fake clock; recommendation rules fire on seeded data; the e-mail is delivered to MailHog.
- **End-to-end (synthetic):** the loop script goes from baseline → dataset → train → gate PASS → approve → deploy, and week-2 precision improves over week 1. The bad preset → gate FAIL.

---

## 10. Work breakdown

Sizes: S ≤ 0.5 day, M ≤ 1.5 days, L ≤ 3 days. Owner agents:
- **ML-Feedback** (Python, B06 core)
- **Eval-Harness** (Python)
- **Data-Synth** (Python)
- **Backend** (Node)
- **Frontend** (React)
- **DevOps**

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| T01 | Freeze shared contracts: `gold_record.schema.json` (plus the predictions variant), reason_code and discrepancy_type enums, `features_json` v1, decision and finalization event payloads, OCR-zone and key-field files, `/internal/ml/score` I/O (review with the Module 2/3 agents) | S | — | ML-Feedback |
| T02 | DB migrations for the B06 tables (§3.13) plus DB guards (CHECKs, immutability trigger) plus seed roles CURATOR and ML_APPROVER | M | T01 | Backend |
| T03 | `inspector_eval` library plus CLI: loaders (XLSX/CSV/JSON/JSONL/composite headers/pilot notation, code aliases), normalization, geometry, matching, all §14.3 metrics, status accuracy, breakdowns, Wilson plus cluster bootstrap, verdict, JSON/HTML report, exit codes, README with the normalization spec, unit tests | L | T01 | Eval-Harness |
| T04 | Pilot toolkit: overlay extraction (stream tail) plus clean-copy generator, GOLD from «ПРИМЕРЫ РАЗМЕТКИ» (cross-validated), registries for 9 objects plus the ventilation set (5 atomic CANDIDATEs), OCR GOLD surrogate from the text layer, redaction-zone map | M | T01 | Data-Synth |
| T05 | Synthetic generator: about 150 objects, registries, PD/RD/ID in PDF/DOCX/XML, all §14.2 classes plus outdated or conflict revisions, scan noise, Rotate/CropBox pages, GOLD plus OCR plus key-field ground truth (coordinate the parameter list with the Module 1/2 agents) | L | T01 | Data-Synth |
| T06 | Feedback capture: decision/finalization/matrix event consumers (or Node transactional hooks), Rejection_Log, draft Dataset_Items, eligibility validator, SUSPENDED/REVOKE flows, idempotency | M | T02; Module 3 decision API | Backend (with the validator in ML-Feedback Python, shared) |
| T07 | AI-verdict service (rule table plus score), Russian templates (verbatim), Dispute_Log creation, `suggested_fix` generator, UNAVAILABLE fallback, latency test | M | T02, T01 (C1 optional at first) | ML-Feedback |
| T08 | Curation and release: curator queue API, four-eyes, coverage report and blockers, sticky object-group split allocation, manifests plus SHA-256, frozen test sets plus access log, export/import, diff | M | T02, T06 | Backend (split and manifest logic in Python lib, called by Node) |
| T09 | Model bundle and trainer: feature builder (shared with Module 2), C1 (LR/HGB, GroupKFold, calibration), C2 threshold selection, C3–C6 builders, deterministic packaging plus hashes, lineage, failure handling | L | T01, T05 (data), Module 2 features | ML-Feedback |
| T10 | Evaluator plus regression gate: replay and re-run modes, runs `inspector_eval` on VALIDATION/HIDDEN_TEST/OCR bench for candidate and active models, per-category exact comparisons, `gate_result`, ML_Retraining_Log | M | T03, T09 | ML-Feedback |
| T11 | Model registry and publication: submit, approve (step-up plus digest plus Ed25519 `Signer`), deploy (event plus hot reload with hash verification in `ml-service`), rollback, verify endpoint, audit | M | T02, T10 | Backend (plus the ML-Feedback loader) |
| T12 | Weekly report: aggregations, PSI and χ² drift, recommendation rules R1–R11, JSON schema, Jinja2 HTML plus WeasyPrint PDF, APScheduler, delivery (in-app plus SMTP/MailHog; Telegram stub), Weekly_Reports, ad-hoc generation | M | T02, T06; Monitoring hooks | ML-Feedback (delivery: Backend) |
| T13 | Frontend screens (§3.16): feedback, disputes, curation (reuses the Module 3 evidence viewer), dataset versions plus heatmap, models plus gate checklist plus approve/deploy/rollback, training jobs, evaluation upload/report, weekly reports; the AI banner in the verification UI | L | T06–T12 APIs; Module 3 viewer | Frontend |
| T14 | Loop demo orchestration: simulated inspector and curator via the real API, week-1/week-2 runs, pre-trained bad model, demo seed script, reset script | M | T05, T06, T08, T09, T10, T11 | Data-Synth |
| T15 | `inspector-batch` and `inspector-ocr` CLI contracts with the Module 1/2 agents (wrappers around their pipeline) | S | T01 | ML-Feedback (coordination) |
| T16 | Docker: `ml-service` image (api/workers, fonts, Pango), `inspector-eval` image, compose services plus MailHog, volumes, healthchecks; local no-Docker run docs | S | T03, T09, T12 | DevOps |
| T17 | Acceptance test suite (§9.2) plus CI job: harness conformance on the pilot sheet, gate boundaries, leakage and property tests, end-to-end synthetic loop | M | T03, T08, T10, T11, T14 | Eval-Harness |

Critical path: T01 → T05 → T09 → T10 → T11 → T14 → demo. T03 runs in parallel from day 1, since it is the organizer-facing deliverable and the metric source of truth. T13 can start against mocked APIs once T01 is frozen.
