# «Инспектор ИИ» — master plan v2 (hackathon task №10, Мосстройнадзор)

Status (2026-09-27): planning complete, re-based on the organizers' real data package. Build not started; waiting on the user's answers to the open questions in §8. Details live in `docs/analysis/`; `97_plan_delta_real_data.md` is the authoritative delta over the earlier reports, and `90_consistency_and_canonical_model.md` remains the canonical model where 97 does not override it.

## 1. What changed with the real data

The organizers' package, decoded in `data_utf8/`, resolved most of the earlier unknowns:

- **Приложение 2 exists.** It is a 7-section sample protocol with a резолютивная часть. The protocol follows it verbatim, and the ТЗ §9.2 five tables, evidence cards and registry go into appendices А/Б/В (`93_scoring_contract_appendix2.md`).
- **The machine score is known.** One JSON per object follows `submission_schema.json`. Missing any approved critical checkpoint caps the total at 59/100.

| Component | Points |
|---|---|
| Finding F1 over `(object_id, parameter_code, location)` | 60 |
| Exact file + 1-based PDF page | 15 |
| Values and statuses | 15 |
| Document integrity and split handling | 10 |

- **The hidden test is OBJ-RECHNIKOV-7-7, and its inputs are provided.** It has 213 files, about 16k pages, archives (zip/7z/rar) with 662 DWG that all have PDF twins, and DOCX. The ИД is 31 scanned binders with 8.3k pages, 72% rotated. Labels are withheld.
- **Two train objects.** Тюменская 5 is the gold seed: 4 groups and 10 checks on ventilation and warm floors, all at page level. Новослободская is unlabeled: 145 PDFs, strong in КР and pit ИД.
- **The package ТЗ docx is v1.0**, while our PDF ТЗ is v1.1. Ruling: internal logic follows v1.1, the protocol form follows Приложение 2, and the output follows the submission schema.
- **Canonical parameter codes are the catalog codes** (PZ-001 … SM-132). M-xxx and the Приложение 2 short forms (KR-55, СПЗУ-30) are aliases with the same integer id.

## 2. How we win

1. **The scored submission for Речников 7-7, produced by one frozen automated run.** The posture is gate-aware:
   - recall-first on «Критическое» parameters;
   - atomic per-location checks with exact tokens («012», not «12»);
   - element-family code mapping with a bounded top-2 hedge;
   - one anchor page per stage per finding group;
   - all 132 parameter rows emitted.

   On the train gold, one missed room or one wrong IOS4 code drops 91–94 points to 59. That is why the posture is built around the gate.
2. **The product demo for the jury:** all 12 modules, the Приложение 2 protocol, the verification UX and the dashboard, on real objects. The Тюменская gold is the hero case.
3. **Integrity:** no tuning on Речников; nobody views its outputs before the submission is frozen; inspector decisions never flow into the submission.

The package score ignores UI, verification, retraining, protocol form and bbox IoU, so it and the demo are judged separately. One engine serves both.

## 3. Recognition is the top priority

It gets 3 of 11 agents and quality gates on a real benchmark (`96_recognition_real_data.md`, `recognition_benchmark.json`). Measured facts:

- **OCR accuracy.** The default RapidOCR scores only 0.870 character accuracy on real pages. The hardened pipeline scores 0.967 overall and 0.968 on scans: PP-OCRv6-small detector plus PP-OCRv5 cyrillic recogniser, no line classifier, tiled detection with seam merge, native DPI, and our own orientation detector. Tesseract rus reaches 0.79–0.90.
- **Word-level OCR on drawings.** 65% of text lines on the gold RD ventilation plans are drawn as curves, so OCR runs wherever the text layer has gaps, not per page.
- **Code corrector.** OCR returns Cyrillic capitals as Latin letters or digits. A deterministic corrector lifts document-code exact match from 0.09–0.18 to 0.91.
- **Header-anchored table parser.** PyMuPDF `find_tables` fails on real explications and ТЭП. Our parser got 32/32 rows, and its sum checks expose real double counts.
- **CAD layers.** 42 of 57 Тюменская PDFs and 83 of 126 Новослободская PDFs keep their CAD layers. Isolating the text layer speeds OCR, and a revision-cloud layer sits exactly over the gold warm-floor rooms.
- **Title-block QR codes** link ИД extracts to RD pages.
- **Other problems we must handle:**
  - garbled text layers with a constant glyph shift, repairable;
  - junk scanner OCR layers, to re-OCR;
  - binder segmentation via the «Реестр ИД» first page;
  - revisions from title blocks and «Состав проекта», never from file names.
- **Throughput.** About 1.4–2.1 s per scanned page on the M2 Max. The full hidden run is 2–4 h, native with CoreML and cached by sha256.

Quality gates, checked at every milestone:

- character accuracy ≥ 0.965, with CI low ≥ 0.95;
- orientation 100% on the rotation set;
- document codes EM ≥ 0.95;
- room tokens EM ≥ 0.95;
- sheet = stamp ≥ 0.95;
- explication rows ≥ 0.98;
- ИД document type ≥ 0.9;
- a 100-page ИД scan in ≤ 180 s.

## 4. Architecture (v2)

- **Two run modes on one engine.**
  - `inspector-batch` is Python-native, with no DB and no RabbitMQ. It produces the submission JSON, a strict variant, a sidecar with the manifest and config hashes, and the protocol.
  - The web product (React + NestJS + PostgreSQL + RabbitMQ) imports the same run artifacts for the demo, verification and dashboards.
- **Docker** is needed only for infrastructure: PostgreSQL, RabbitMQ, Valkey, Gotenberg for protocol PDFs, and Mailpit. ML workers run natively, because CoreML doubles detector speed and Docker on macOS cannot use it.
- **Registry = `document_manifest.jsonl`**, with files identified by sha256. Revision selection, completeness and scenario move to Python (`inspector_registry`); Node calls it.
- **Archives** are read with bsdtar/libarchive, with names decoded from cp866. Never `unrar`: it is killed by Gatekeeper on this Mac.
- **DWG** is linked to its PDF twin and never cited; ezdwg is optional enrichment.
- **Routing follows the organizers' gold.** Warm floors go to FREE-HEATING-001, a matrix gap. Ventilation goes to IOS4-078/079. Directional triggers are enforced: an improvement is not a violation.
- **Everything else from `00_architecture.md` and `90_…md` stands:** contracts-first, the Node-only writer rule for domain tables, immutable protocol versions and the status machines.

## 5. Agents: 11, all on Opus

| Agent | Scope | Est. |
|---|---|---|
| AG-02A Recognition Core (lead) | benchmark, OCR v2, orientation, router + text-layer repair, render policy, zones, batch runner/cache/CoreML, tiles | ≈12 d |
| AG-02B Drawings & Layout | code corrector, title block + QR + sheet↔page, CAD layer toolkit, revision clouds, room index, tag grammar, PD↔RD sheet matching, DWG twins | ≈12 d |
| AG-02C Tables, ИД & NLP | typed tables, binder typing, АОСР / реестр / ИГС / quality-document parsers, ~35 deep profiles, normalisation | ≈14 d |
| AG-00 Platform, Contracts & Ops | contracts-lite, auth/RBAC, audit, monitoring, notifications, РиН stub, batch import | ≈12 d |
| AG-01 Ingestion, Registry & Integrity | manifest resolver, revisions, archives, completeness, scenario | ≈12 d |
| AG-03 Matrix & Domain | catalog codes, rule DSL, change map, value templates, recommendation templates | ≈8 d |
| AG-04 Comparison, Submission & Protocol | comparators, atomic split, anchor pages, exporter, Приложение 2 renderer | ≈14 d |
| AG-05 Verification & Learning Loop | verification UX, lean M4/M10 | ≈12 d |
| AG-07 Hypotheses & FREE findings | 4 approaches, FREE-* findings | ≈10 d |
| AG-08 Web & Admin | shell, dashboard, viewer with layer toggle, Module 8 admin | ≈14 d |
| AG-10 Evaluation, QA & Dev data | `inspector-score` (60/15/15/10 + gate), `inspector-eval` (§14), gold gate, Новослободская labelling, hidden-run runbook, M12 negative scenarios | ≈12 d |

Total is about 145–150 agent-days, roughly 14–16 working days. Completion matters more than a date. Rules of engagement are unchanged from the architecture report: contracts are law, directories are owned, generated code is committed, CI guards run, and no runtime internet.

## 6. Milestones

| Milestone | Est. | Done when |
|---|---|---|
| M0 contracts-lite & data hygiene | 1–1.5 d | Schemas and enums pinned; params seeded from the catalog; manifest + sha256 resolver; `inspector-score` v0; recognition benchmark wired |
| M1 train E2E-0 | ~day 5–6 | `inspector-batch` on Тюменская gives a schema-valid submission with 10/10 keys, the gold pages and the gate OK. Demo D1: Тюменская imported, Приложение 2 protocol, verification, dashboard |
| M2 train E2E-1 | ~day 9–10 | Новослободская runs fully; 132 rows on both train objects; АОСР, реестр and ИГС parsers; КР comparators; integrity rules; Новослободская labels frozen |
| M3 hidden-ready & freeze | ~day 13–15 | Breadth for АР, ГП/СПЗУ, КЖ, ЭОМ, ВК; ИД at scale; revisions, archives, twins; files > 50 MB; calibration on the train objects only; freeze tag. Demo D2: all 12 modules clickable |
| M4 hidden run | ~1 d | One native run on an idle machine; submission + strict + sidecar + protocol. Demo D3: release candidate, rehearsal, backup video |

Critical path to M1: contracts-lite → manifest resolver → OCR benchmark and core → coverage router → title block + room index → comparators with atomic split and anchor pages → exporter → score 10/10 on Тюменская.

Cut order if late: product depth first (M10 polish, ML screens, admin dry-run, ezdwg, VLM). Never cut the gold gate, the gate policy, the ИД pipeline or the integrity rules.

## 7. Scope decisions already made by the user

- **Dropped:** real УКЭП/ГОСТ signing and mTLS; real РиН integration, which becomes a trivial stub; the synthetic 150-object retraining corpus; the organizer letter; ELK.
- **Lean:** Module 4 keeps GOLD capture from real decisions, versioning, the object split, the gate, approval and rollback. SLA/RTO/RPO/IDS are documented, not proven.
- **Agreed:** about 35 deep extraction profiles plus generic ones; clearly labelled synthetic data allowed; human review time available; completion over date; recognition is the top priority.

## 8. Open questions for the user

Full wording with options is in `97_plan_delta_real_data.md` §«Questions for the user».

1. The risk policy for the scored run on Речников: code hedging, 132 rows, FREE-* limits.
2. LLM/VLM usage.
3. The human review budget, about 5 h.
4. Three domain routing calls for КР.
5. How answers are submitted and whether there is a demo or presentation.
6. The container runtime, plus about 100 GB of free disk.
7. Repository: a private GitHub repo with Actions.

## 9. Immediate next steps

1. The user answers §8.
2. Install the container runtime, free disk, and create the repository.
3. Move the OCR models and prototype scripts from the session scratchpad into the repo's `tools/`.
4. Start M0, with AG-10 (scorer) and AG-02A (benchmark) first, because they are the acceptance gates for everything else.

## 10. Document and data index

| Path | Content |
|---|---|
| `data/` | Organizer files as extracted, names in broken encoding. Read-only, never modified |
| `data_utf8/` | Hard-link mirror with decoded names; `_name_mapping.csv`; 19 Новослободская files restored from the original archive and 2 exact-name links (`_recovered_files.txt`). Read-only for agents |
| `data_utf8/ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0/` | Submission schema, scoring weights, split policy, manifest, catalog, train gold, Приложение 2, legend |
| `docs/spec/` | Extracted ТЗ v1.1 text, matrix sheets, pilot markup text and previews |
| `docs/analysis/00`…`10_*.md` | Per-block designs (still valid unless 97 overrides) |
| `docs/analysis/90_…md`, `91_…md`, `92_…md` | Canonical model, ТЗ traceability, hackathon strategy |
| `docs/analysis/93_scoring_contract_appendix2.md` | Scoring contract, Приложение 2 spec, ТЗ v1.0↔v1.1 delta, `inspector-score` spec |
| `docs/analysis/94_corpus_rechnikov_hidden_test.md` + `corpus_rechnikov_profile.json` | Hidden-object input profile. Quarantined: input handling only, never tuning |
| `docs/analysis/95_corpus_train_objects.md` + `corpus_train_profile.json`, `95_tyumen_dev_fixtures.json`, `95_novoslob_label_seed.json` | Train corpora, gold fixtures, labelling seed |
| `docs/analysis/96_recognition_real_data.md` + `recognition_benchmark.json` | Recognition benchmark, measured pipeline, AG-02 task plan |
| `docs/analysis/97_plan_delta_real_data.md` | Authoritative plan delta, roster, milestones, questions, installs |
| `docs/analysis/matrix_enriched.json`, `id_completeness_checklist.json` | 132 parameters with rules and thresholds; ИД checklist. Pending fixes are listed in 97 |
