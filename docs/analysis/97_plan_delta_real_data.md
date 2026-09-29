# 97 — Plan delta after the organizers' real data package

> Written by the lead from the synthesis agent's structured return. Key facts are tagged [§1]…[§5] (priorities, edits, build order, questions, installs).

## Summary

The organizer package changes what winning means. The machine score is computed on one JSON for the hidden object OBJ-RECHNIKOV-7-7: 60 points for finding F1, 15 for exact file and page, 15 for values and statuses, 10 for integrity and split handling. Missing any approved critical checkpoint caps the total at 59. That score ignores the UI, verification, retraining, protocol form and bbox IoU, so the product demo is judged separately, in a format we do not know. The plan therefore runs two tracks on one engine. The first is a Python-native `inspector-batch` path with no DB or RabbitMQ. It uses CoreML and does one frozen 2–4 h run that emits the schema-exact submission plus the Приложение 2 protocol. The second is the web product, which imports the same run artifacts for the demo, verification and dashboards. Recognition gets the largest investment: 3 of the 11 agents (OCR core and router; drawings and layout; tables, ИД and NLP). They build on 96's measured pipeline (0.967/0.968 character accuracy against 0.870 for the default), word-level coverage routing (65% of RD drawing text lines are curves), orientation detection, the code corrector, title blocks with the sheet→page map, the CAD-layer toolkit, the room index, typed tables, binder segmentation and text-layer repair. The canonical model changes in these ways:
- catalog codes (PZ-001…SM-132) become the canonical codes;
- `criticality_level` is restored;
- new enums ViolationLabel and ProtocolParamStatus, with a fixed status mapping and per-parameter precedence rules;
- routing follows the organizers' element families (warm floors → FREE-HEATING-001);
- the protocol follows Приложение 2 verbatim, plus Приложения А/Б/В;
- the manifest is the registry and files are identified by sha256;
- archives are read with bsdtar and cp866 name decoding, and DWG files are linked to their PDF twins and never cited;
- revision, completeness and scenario logic moves to Python;
- soft-gost signing, the РиН depth and the synthetic retraining corpus are dropped.

Where reports 93–96 conflicted, I ruled for the measured results in 96. That means no text-line classifier, native DPI, no upsampling and our own orientation detector. Garbled text layers are repaired first and sent to OCR only if repair fails. RAR goes through bsdtar, because Homebrew unrar is killed on this Mac (I verified exit 137). All 132 parameter rows are emitted, which also protects against a broad reading of the gate. The public manifest shows no RD for ОВ, СС or ПБ on the hidden object. The Тюменская ventilation comparator is therefore a must-pass fixture and demo asset, and depth for the hidden object goes to КР/КЖ + ИД, АР, ГП/СПЗУ, ЭОМ and ВК. The critical path to the first train submission is: contracts-lite, then the manifest/sha256 resolver, the OCR benchmark and core, router coverage, title blocks and the room index, the comparator with atomic split and anchor pages, the exporter, and finally `inspector-score` 10/10 on Тюменская (M1). After that come Новослободская with all 132 statuses and N-GOLD labels (M2), breadth and the freeze (M3), and the single hidden run (M4). I closed one open question myself: the organizers' original archive is in ~/Downloads as a nested zip, and I recovered all 19 missing Новослободская files into the scratchpad with sha256 verified (19/19). The environment has no container runtime and only 68 GiB of free disk. Seven consolidated questions remain, including the detailed LLM options and the «почему OrbStack?» answer the user asked for.

## Key facts

- [meta] Report 97 was not written as a file (subagent report-file restriction). The tags below map to the requested sections: [§1] priorities/scoring/demo, [§2] edits to PLAN.md and the canonical model, [§3] agents/build order/critical path, [§4] questions (in user_questions), [§5] installs (in install_needs). The 94 report exists only as corpus_rechnikov_profile.json plus its summary.
- [resolved] The organizers' original archive is on this machine: /Users/evgen/Downloads/archive-2026-09-27_16-20-28.zip (15.5 GB). It wraps archive/01_ПАКЕТ_УЧАСТНИКАМ_3_ОБЪЕКТА.zip (546 entries, cp866 names without the UTF-8 flag) plus a .tar copy. I extracted all 19 missing Новослободская files (F0015…F0080) from the nested zip, decoded cp437→cp866, into /private/tmp/claude-501/-Users-evgen-pl-hackaton/18a4a0ae-5dd8-48b7-a436-1b6a7256ad25/scratchpad/recovered_novoslob/<file_id>.pdf. Their sha256 matches the manifest for 19/19. The «original archive» questions from 93 and 95 are closed; only a durable location outside data/ and data_utf8 is still needed (/private/tmp is ephemeral).
- [env] Machine: M2 Max, 12 cores, 32 GB RAM, macOS 27.0. Disk has only 68 GiB free of 926 GiB (93% used). Installed: Node 22.22.2 (nvm), Python 3.12 (Homebrew; pyenv default is 3.10.9), uv, git, gh, Homebrew tesseract (langs eng, osd, snum only), and system bsdtar with libarchive 3.7.4. Not installed: docker, OrbStack, Colima, LibreOffice, pnpm. /opt/homebrew/bin/unrar exits 137 (SIGKILL) and is unusable.
- [§1.1 What is scored] Each answer is one JSON per object, {object_id, checks[]}, per submission_schema.json. The scoring unit is almost certainly (object_id, parameter_code, location). Components: F1 over VIOLATION_PRESENT (60); recall of exact (file_id, 1-based pdf_page_number) pairs (15); label, protocol_status, criticality and values (15); integrity and split rules (10). Gate: any missed approved critical checkpoint (catalog «Критическое (приостановка работ)», final gold) caps the total at 59. On train, one missed room, IOS4-078 in place of IOS4-079, or «12» in place of «012» turns a 91–94 run into 59. Hedging both codes costs about 3 points (97.1). The old warm-floor routing costs 36 points.
- [§1.2 Priority order] (1) Never miss an approved critical checkpoint: recall-first on Критическое parameters, atomic per-location split, exact room and element tokens, element-family code mapping with top-2 hedging. (2) F1 breadth on the disciplines where the hidden object has at least two stages. (3) Anchor-page localisation, the title-block sheet→page map, and citing only the current revision. (4) Value templates, exact catalog criticality strings, and status precedence for all 132 parameters. (5) Integrity discipline: manifest-only evidence, never F0149/F0418, stage resolved per file, duplicate representatives only, one object per file. (6) Product breadth across the 12 modules: never dropped, but depth is capped.
- [§1.3 Where the hidden points are (public manifest only)] Речников has 89 PD PDFs covering all sections. RD has 44 PDFs, but only for ГП, АР, КР/КЖ, ЭОМ and ВК1; there is no RD for ОВ, СС or ПБ. RD also has 38 archives holding 662 DWG, all with PDF twins, 6 DOCX and 5 loose DWG. ИД is 31 scanned binders with 8,324 pages, 99.6% scans and 72% /Rotate 270. Violations are therefore findable only PD↔RD in ГП/СПЗУ, АР, КР/КЖ, ЭОМ and ВК, and RD↔ИД plus ИД-internal tolerances in КР/ЭОМ/ВК. IOS4 ventilation, the entire train gold theme, is PD-only there. So the per-room vent-tag comparator is sized for the Тюменская must-pass fixture and the demo, and the hidden-score depth goes to КЖ/КР + ИД (АОСР, ИГС, документы о качестве), АР rooms/doors/corridors, ГП/ТЭП, and ЭОМ/ВК spec tables. The generic machinery transfers: room index, title blocks, outlined-text OCR, anchor pages.
- [§1.4 Demo vs automated score] The package score measures only the submission. It ignores UI, verification, retraining, protocol form, API, bbox IoU and FPR. The jury or demo, in an unknown format, judges ТЗ compliance, the Приложение 2 protocol, verification UX and integration. Ruling: one engine, two front-ends. `inspector-batch` (Python, native, no DB and no RabbitMQ) produces the scored artifacts. The web product imports the same run directory (the same claim-check artifact schema) into PostgreSQL to show protocols, evidence, verification and the dashboard. Every number in the demo is reproducible from the batch artifacts. Inspector decisions never flow into a submission. Nobody views Речников outputs before the submission is frozen and sent; after that the Речников protocol can be demoed.
- [§1.5 Demo re-based on real data] The hero objects replace the pilot «9/9» story:
- **Тюменская:** organizer gold 10/10, including the warm floor proven by PD text plus RD absence plus a CAD revision cloud lying exactly over rooms 270/272; a QR code proves that ИД F0198 is RD F0202 p17.
- **Новослободская:** the АОСР parsed; the F150 vs F200 concrete-mark candidate; directional-trigger negatives.
- **A real document error not in the gold:** in the F0201 p18 explication, the «в том числе» sub-zone (30.4 m²) is counted twice, which becomes a SUSPICION.
- **The 658 MB binder** segmented via its «Реестр ИД».
- **The Приложение 2 protocol** rendered verbatim.

The pilots become recognition fixtures and demo extras only. The «Тюменская 10/10 + гейт» page replaces «Пилот 9/9». Bbox IoU calibration drops to P2.
- [§1.6 Posture] «Precision first» becomes «gate-aware»:
- recall-first on Критическое matrix parameters: lower emission threshold, top-2 code hedge when the runner-up has p ≥ 0.1, hedges capped at 20% of emitted critical checks;
- precision-first on Существенное and on FREE-* (evidence-bound only, at most about 5 groups);
- fail-visible internal statuses map to COMPARISON_IMPOSSIBLE or MISSING_DOCUMENT;
- tuning is leave-object-out on Тюменская plus N-GOLD, never on Речников.
- [§1.7 ТЗ §14 vs package] The package scorer is a simplified, weighted version of ТЗ v1.1 §14.3 (no IoU, no FPR threshold) plus the gate. `inspector-eval` still reports the §14 metrics for the jury: CA ≥ 0.95, key-field EM ≥ 0.90, P/R/F1, FPR, IoU, all with n and 95% CI. §11 speed (100 pages ≤ 3 min) holds only on an idle host with native CoreML workers, so the demo runs the ML workers natively and the infrastructure in containers.
- [§2.1 PLAN.md header, §1 and §2]
- **Status:** package v2.0 received; delta in 97.
- **§1 win thesis:**
  - #1: replace СХЕМА GOLD with submission_schema.json, 60/15/15/10 + gate, the `inspector-score` replica, and Тюменская as a must-pass CI gate.
  - #2: the gate-aware posture.
  - #3: real objects instead of pilot + synthetic.
  - New #6: hidden-test integrity.
- **§2 facts, OCR line:** default 0.870, hardened 0.967 [0.952–0.978] on vector pages and 0.968 [0.955–0.983] on scans; key-field EM 0.905 strict / 0.952 relaxed; codes 0.09–0.18 raw, 0.91 and 19/19 after correction.
- **§2 facts, replace «pilot drawings mostly vector» with:**
  - 65% of RD drawing text lines and all RD title blocks are curves;
  - 10% of Тюменская PD pages are mojibake, and 31 Речников PD pages are garbled;
  - ИД is 99.6% scans;
  - CAD OCG layers exist in 42/57 and 83/126 train PDFs.
- **Add Речников scale:** 15,961 pages, about 9.5k OCR pages, a 2–4 h native frozen run, 32 files > 50 MB, 6 files > 200 MB, 38 archives.
- The pilot facts stay as fixture facts.
- [§2.2 PLAN.md §3 architecture]
- Add «two run modes, one engine».
- **ML:** native host execution with CoreML for the batch run and the demo workers.
- **OCR:** the RapidOCR v2 pipeline (PP-OCRv6-small det, PP-OCRv5 cyrillic rec, no text-line classifier, tiles 3200/400, v6-medium fallback). Tesseract is used for OSD only; `rus` stays only in the benchmark comparison.
- **Protocol:** Приложение 2 DOCX template; PDF by HTML→Gotenberg Chromium so the emoji render; fonts Selawik and Noto Color Emoji.
- **Upload limits:** 50/200 MB apply to HTTP upload only; server-side manifest/batch ingest bypasses them.
- **Key rulings:**
  - registry logic in Python `inspector_registry`;
  - `params.code` = catalog code;
  - manifest = registry;
  - evidence only from manifest PDF pages;
  - no signer (step-up re-auth + SHA-256 seal).
- [§2.3 PLAN.md §4 and §5] Replace the agent table with the [§3.1] roster and CP0–CP3 with milestones M0–M4 plus demo D1–D3 [§3.2]. Capacity: the dropped scope saves about 35–40 agent-days, and the new scope (submission, scorer, CAD/rooms, ИД binders, Приложение 2) adds about 25–30. Total ≈145–150 agent-days, or ≈14–16 working days with 11 agents. Per the user, completion matters more than a date.
- [§2.4 PLAN.md §6–§11]
- **§6** (organizer letter): delete. Replace with «Assumptions instead of answers», each backed by an `inspector-score` variant: key K1 vs K3, localisation recall vs Jaccard, gate key/strict/broad, location normalisation strict/light. Add the 7 user questions.
- **§7:**
  - УКЭП → dropped;
  - РиН → trivial stub;
  - retraining → lean M4 on real decisions;
  - extraction → re-prioritised profiles;
  - CV → CAD layers + outlined OCR + room index;
  - add a DWG row (PDF twin; ezdwg optional);
  - ELK → documented only.
- **§8:**
  - codes ruling flipped (catalog canonical; Приложение 2 «AR-14» = AR-040);
  - DWG: UI rejects per ТЗ, batch registers + links the twin;
  - ТЗ v1.0 vs v1.1 ruling;
  - upload-limit ruling.
- **§9:** record the answered decisions.
- **§10:** next steps per [§3.5].
- **§11** index: add 93, 95, 96, 97, corpus_train_profile.json, 95_tyumen_dev_fixtures.json, 95_novoslob_label_seed.json, recognition_benchmark.json, and corpus_rechnikov_profile.json (quarantined).
- [§2.5 90 edits: submission contract (new §3.15)] Output per object:
- `submission/<object_id>.json`, validated against the pinned submission_schema.json (Draft 2020-12, checksum from sha256sums.txt);
- `submission-strict/` (schema fields only);
- a separate sidecar: input_manifest_hash, config_hash, versions, per-file status, missing-on-disk list, page_basis.

Field rules:
- **parameter_code:** catalog code, or FREE-<TOPIC>-<NNN> numbered per finding group.
- **location:** exact printed token («012», «1.109», «-1.05»), a FLOOR/BUILDING/AXES grammar, or OBJECT.
- **pd_value / rd_value / id_value:** from value templates; null when that stage is not part of the check.
- **criticality:** the exact catalog string. FREE → «Существенное (предписание) — требует утверждения».
- **evidence:** {stage, file_id, pdf_page_number}, ordered PD, RD, ID, 1–2 per stage, with one anchor page per stage per group reused for every atomic check.
- Gold-named extras are allowed: comparison_result, location_type, document_status, matrix_scope, parameter_mapping_status, document_sheet_number, finding_id, confidence.

Never cite: DWG, archive members, BAK, excluded ids, non-representatives of a duplicate group, superseded revisions, GROUND_TRUTH_INDEX files (F0194), or other objects. DOCX only with page_basis RENDERED_LIBREOFFICE. In batch mode every CANDIDATE is exported as VIOLATION_PRESENT.
- [§2.6 90 edits: status mapping (new §3.2.11)]

Mapping to violation_label / protocol_status:
- COMPLETE + CANDIDATE or CONFIRMED → VIOLATION_PRESENT; CRITICAL if Критическое, else WARNING.
- NEGATIVE_VERIFIED or NOT_APPLICABLE → NO_VIOLATION / OK.
- MISSING_EVIDENCE at document level → MISSING_DOCUMENT / RD_MISSING, PD_MISSING or ID_MISSING.
- MISSING_EVIDENCE at fragment level, NOT_COMPARABLE or CLARIFICATION_REQUIRED → COMPARISON_IMPOSSIBLE.
- Evidence-bound SUSPICION → VIOLATION_PRESENT with FREE-* / WARNING. Unbound SUSPICION is not exported.

Precedence per parameter:
1. ≤ 1 required stage available → COMPARISON_IMPOSSIBLE.
2. A pairwise violation wins over a missing third stage.
3. Otherwise a missing required stage → MISSING_DOCUMENT (RD > PD > ID).
4. Otherwise NO_VIOLATION.

Other rules:
- PARTIALLY_LOADED is display-only.
- API aliases: CONFIRMED↔CONFIRMED_VIOLATION, REJECTED↔NEGATIVE_VERIFIED; v1.0 PARTIALLY_CONFIRMED maps to «Разделить».
- v1.0 colours: OK green, WARNING yellow, CRITICAL red, ID_MISSING orange (yellow on the 3-colour indicator), RD/PD_MISSING red, COMPARISON_IMPOSSIBLE red.
- [§2.7 90 edits: new enums]
- ViolationLabel.
- ProtocolParamStatus (+ PARTIALLY_LOADED, display only).
- CriticalityLevel: CRITICAL_SUSPEND «Критическое (приостановка работ)», SUBSTANTIAL_ORDER «Существенное (предписание)», INFORMATIONAL (display only).
- ParameterMappingStatus: SOURCE_MATRIX, PROVISIONAL_DOMAIN_MAPPING, MATRIX_GAP_CONFIRMED.
- ComparisonResult: CONFIGURATION_MISMATCH, MISSING_DESIGN_ELEMENT, VALUE_MISMATCH, MATERIAL_SUBSTITUTION, EXTRA_ELEMENT, TOLERANCE_EXCEEDED; mapped from DiscrepancyType.
- LocationType: ROOM, FLOOR, BUILDING, AXES, ELEMENT, OBJECT.
- MatrixScope: MATRIX, FREE_SEARCH.
- DocumentStatus (gold vocabulary).
- ManifestStage: PD, RD, ID, RD_ID_MIXED, UNKNOWN (kept raw, next to the resolved DocStage).
- LocalFileStatus: PRESENT, RECOVERED, MISSING_ON_DISK. This is never MISSING_DOCUMENT.
- TextSource: TEXT_LAYER, TEXT_LAYER_REPAIRED, OCR, OCR_LAYER_ISOLATED.
- PageClass changes: add STAMP_PAGE; redefine BROKEN_ENCODING by mojibake/lexicon/mixed-script; TEXT_UNDER/OVER_IMAGE → RASTER_HIDDEN_OCR.
- PageBasis: PDF_NATIVE, RENDERED_LIBREOFFICE.
- ArchiveMemberRole: PDF_TWIN_SOURCE, CONTEXT_ONLY, FOREIGN_OBJECT, DUPLICATE, IGNORED.
- Split mapping: TRAIN_PUBLIC→TRAIN, TEST_HIDDEN→HIDDEN_TEST.
- EvalKind + SUBMISSION_SCORE.
- [§2.8 90 edits: data model]
- **params:**
  - `param_id` 1…132 is the join key; `code` = catalog code;
  - `alias_codes[]` (M-xxx, ТЗ Latin/Cyrillic short forms) replaces `alias_code`;
  - `criticality_level` is restored beside `review_priority` (Критическое↔HIGH 106, Существенное↔MEDIUM 26);
  - new columns `short_name`, `work_type`, `recommendation_template`, `deviation_verb`, `element_nouns`.
- **change_matrix_map** gains `parameter_mapping_status` and a directional flag.
- **checks** gains `violation_label`, `protocol_status`, `pd_value`, `rd_value`, `id_value`, `document_status`, `location`, `location_type`, `comparison_result` and `hedge_of_finding_id`.
- **files:**
  - manifest fields: dataset_role, split, duplicate_group, annotation_status, manifest_stage, manifest_section, pdf_pages, sha256;
  - resolved stage, discipline, code, revision and approval, with MetaSource EXTRACTED_UNCONFIRMED;
  - `local_status`.
- **New tables:**
  - `logical_documents`: binder segments with doc_kind, act_no, dates, cited RD шифр and sheets, stage_resolved;
  - `archive_members`: virtual id «F0331!path», decoded name, sha256, role, twin_file_id, twin_page_map;
  - `page_title_blocks`: sheet, листов, шифр raw and corrected, стадия, Изм. rows, QR doc/page;
  - `room_index`;
  - `page_layers`: OCG names, revision clouds;
  - `submission_exports`.
- **document_pages** gains text_source, content_rotation, is_stamp_page, glyph_path_ratio, object_identity_ok.
- [§2.9 90 edits: codes (replaces §3.3.3, T-13, C-38)] The canonical external code is the catalog parameter_code. Parser: ^(M|PZ|SPZU|AR|KR|IOS[1-5]|POS|POD|OOS|PPM|ODI|ZU|SM|ПЗ|СПЗУ|АР|КР|ИОС[1-5]|ПОС|ПОД|ООС|ППМ|ОДИ|ЗУ|СМ)-0*(\d{1,3})$. The prefix must agree with the id range: PZ 1–23, SPZU 24–39, AR 40–53, KR 54–67, IOS1 68–70, IOS2 71–73, IOS3 74–75, IOS4 76–79, IOS5 80, POS 81–89, POD 90–97, OOS 98–101, PPM 102–114, ODI 115–123, ZU 124–131, SM 132. On disagreement, resolve by name and warn (Приложение 2 «AR-14» is AR-040). The protocol shows «{short_name} ({code})», and APIs accept every alias. FREE-<TOPIC>-<NNN> uses a fixed topic vocabulary.
- [§2.10 90 edits: routing (replaces §3.12)] Declared as «learned from T»:
- Map a change to the closest parameter of the same engineering system by element family, even when the trigger wording differs (PROVISIONAL_DOMAIN_MAPPING).
- Use FREE-* only for a matrix gap (MATRIX_GAP_CONFIRMED).

Тюменская:
- G-TR-001: IOS4-079, room 012.
- G-TR-002: FREE-HEATING-001, rooms 267/270/271/272 (previously M-077).
- G-TR-003: IOS4-078, MISSING_DESIGN_ELEMENT, rooms 140/142.
- G-TR-004: IOS4-078, CONFIGURATION_MISMATCH, rooms 147/198/314.

Rules:
- Directional triggers are enforced.
- Additions and relocations are context, not findings.
- ИД≠РД is emitted only in the violating direction.
- Same concrete class with lower F/W marks → FREE-STRUCTURE (pending Q4).
- Hedge pairs come from the matrix near-duplicates: IOS4-078/079, AR-040/PPM-104/ODI-116, AR-041/PPM-105, and the other pairs of the 9.
- The old pilot routing survives only for fixtures.
- [§2.11 90 edits: protocol (replaces the 04 §3.10 layout)]

**Body: Приложение 2 verbatim**
- Seven sections: header; 1 статус загрузки; 2 сводная статистика с процентами; 3 не проверено из-за отсутствия ИД; 4 критические; 5 существенные; 6 подозрения ИИ; 7 резолютивная часть 7.1/7.2.
- A4 portrait; ГОСТ margins 20/20/30/15 mm; Segoe UI declared, Selawik embedded; emoji markers; largest-remainder percentages.
- Additions: the «Тип проверки» line, extra partition rows only when non-zero, the disclaimer footnote, «[карточка Б.n]» references.
- Preliminary recommendations carry the prefix «Проект рекомендации (до подтверждения инспектором): ».

**Appendices**
- А: the five §9.2 п.4 tables.
- Б: evidence cards with all v1.1 fields.
- В: input registry, versions, hashes.

**Build**
- One canonical protocol JSON with the blocks appendix2, tz92_tables, evidence_cards, input_registry and submission_checks.
- DOCX from a template authored from the Приложение 2 docx; PDF via HTML→Gotenberg Chromium.
- Golden test: fixture numbers must reproduce every Приложение 2 string.
- [§2.12 90 edits: intake]

**Registry and identity**
- The manifest is the registry, status VALID_WITH_WARNINGS.
- Identity is by sha256.
- excluded_file_ids are refused.
- GROUND_TRUTH_INDEX files are kept out of the evidence corpus.
- A file missing on disk is a LocalFileStatus, never MISSING_DOCUMENT.

**Stages and revisions**
- RD_ID_MIXED and UNKNOWN are resolved per file and per logical document.
- «П-ИД» means ПД «Исходные данные».
- Revisions come from:
  - title blocks;
  - Разрешение numbers;
  - «Состав проекта» (СП-кор3) tables;
  - «Сопоставительная ведомость» and КОРРЕКТИРОВКА N;
  - Изм rows and page-hash diffs.
- File names are only a weak prior (кор3 > кор2, V2_, «ИЗМ ПО ЗАМЕЧАНИЯМ»).
- Near-duplicates are found by text hash.
- Object identity is checked per page (address, plot, шифр prefix).

**Archives**
- Read with bsdtar/libarchive.
- Names: cp437→cp866 when the UTF-8 flag is absent; strip Unicode Cf and bidi characters.
- Guards: ≤ 2 GB uncompressed, ≤ 5,000 members, no path traversal, sandboxed extraction.
- Members are non-citable `archive_members`.

**DWG and DOCX**
- DWG: register it and link it to the same-folder PDF twin by the sheet number in the name, the paper-space stamp and text Jaccard; never cite it. ezdwg is optional.
- DOCX: python-docx; change notes feed the revision chain.

**Limits**
- Batch ingest bypasses the 50/200 MB HTTP limits.
- UI upload keeps the limits and keeps rejecting DWG and ZIP per the ТЗ.
- [§2.13 90 edits: recognition architecture (updates 02 §3 and 01 §3.9)]

- **F0 inventory**, 1–3 ms per page: class, /Rotate, DPI, text-layer quality (lexicon + mixed-script + mojibake ratio), occlusion order via get_bboxlog, OCG layers, glyph-path ratio, STAMP_PAGE/blank, QR window.
- **F1 text layer:**
  - per-font glyph remap or shift repair with a lexicon acceptance test → TEXT_LAYER_REPAIRED, raw text kept;
  - otherwise OCR.
- **F2 word-level coverage map:**
  - v6-small detection at 200 dpi, tiles 3200/400 with seam merge;
  - on OCG layer-isolated renders where layers exist;
  - OCR only the uncovered boxes;
  - embedded rasters over 5% of the page → OCR.
- **F3 OCR v2:**
  - orientation: det-geometry + rec-score probe, Tesseract OSD as tie-break;
  - native DPI clamped to [150, 300];
  - no text-line classifier;
  - 180° retry, 3-way read for short vertical tokens, local re-detection for long low-score lines;
  - v6-medium fallback when the mean line score is < 0.9 or a seal zone is present;
  - quality flags OK ≥ 0.85 / LOW_QUALITY ≥ 0.6 / ABSTAIN;
  - seal, stamp, QR and handwriting zones.
- **F4 merge** with provenance.
- **F5 post-correction:**
  - code corrector + registry prior;
  - room-token grammar that keeps leading zeros;
  - a lexicon for words only.
- **F6 layout:** title-block cells, Изм rows, QR, sheet↔page map with smoothing and duplicate detection; room index across sheets; revision clouds; binder segmentation.
- **F7 typed header-anchored tables:** EXPLICATION with Σ checks, TEP aligner, SPEC_21110, DEVIATION/ИГС, CHANGE_LOG, АОСР + реестр.
- **F8 NLP:** e5-small index over row-context strings → geometric value fetch → normative-vs-object role filter → title-block exclusion.

Not used: generic find_tables in the hot path, deskew, INT8.
- [§2.14 90 edits: other rulings]
- **Ruling 9:** revision selection, completeness and scenario move from Node/TS to Python `inspector_registry`. There is one implementation, used by inspector-batch and by Node through ml-api; Node still persists.
- **§3.13 ownership:**
  - title-block reader: AG-01 → AG-02B;
  - typed tables and ИД parsers → AG-02C;
  - room index and CAD layers → AG-02B.
- **Ruling 20** (signer) is removed: finalize = step-up re-auth + SHA-256 of the canonical protocol JSON.
- **New endpoints:** `POST /api/v1/admin/batch-runs/import` and `GET /processes/{id}/submission?variant=full|strict`.
- **§8 data needs:** N-1, N-3, N-4 and N-13 resolved; N-2 partly resolved; N-5 → manifest; N-7 → stub; N-11 → proxies only.
- **91 traceability:** add a «v1.0 delta» column.
- **ТЗ versions:** v1.1 governs the internal logic; the v1.0 package docs bind the protocol form and the status table; the package JSONs bind the submission.
- **matrix_enriched.json fixes:**
  - M-044 catastrophic-backtracking regex, plus a time/length guard on every regex;
  - context gates for «В20» (vent system) vs «B20» (concrete class) and for «ИД» (исходные данные vs stage).
- [§2.15 Dropped or reduced scope (user decisions)]

**Dropped**
- УКЭП/ГОСТ signing (soft-gost, OpenSSL-gost, CryptoPro documentation).
- mTLS and the dev CA.
- The ~150-object synthetic retraining corpus and the synthetic internal hidden test.
- The organizer letter.
- The ELK profile.
- Pilot 9/9 conversion depth.
- IoU calibration (moved to P2).

**Reduced**
- M6 РиН: a stub on the literal ТЗ paths, with PENDING_SYNC shown and a fixed retry.
- M4: GOLD capture from real decisions, dataset versions with the object split, the gate (inspector-score + §14.3), approval and rollback. The «model» is a bundle of thresholds, mappings and dictionaries.
- M10: a simple report.
- SLA/RTO/RPO/IDS: documented, not proven.

**Kept**
- All 12 modules stay visible.
- Synthetic data only as badged perturbations of train copies, for unit tests.
- [§2.16 Reconciled conflicts between 93–96]
- **OCR** follows 96's hand-GT measurements:
  - no text-line classifier (95 R6 wanted it);
  - native DPI with no upsampling (95 R10 wanted ×2 below 200 dpi; 94 wanted 200 dpi plus a 300 dpi pass). 300 dpi is kept only for stamp crops and low-score value regions;
  - our own orientation detector (94 proposed PP-LCNet);
  - a 2–4 h native run with triage (94 estimated 4–6 h).
- **Garbled layers:** detect per 95/96; repair per 94's per-font shift/remap, validated on Тюменская's 508 mojibake pages first; fall back to OCR.
- **RAR:** 94 is right. Homebrew unrar is killed (verified); use bsdtar.
- **DWG:** register + twin at P0, ezdwg at P3.
- **MISSING_DOCUMENT:** 93 wanted all 132 rows, 94 wanted only critical rows with references. Emit all 132 at OBJECT, which also insures the broad gate variant, and use 94's in-corpus references as the evidence pages for *_MISSING rows.
- **Tesseract:** 93 wanted it kept for the v1.0 wording, 96 drops it from the runtime. Keep a rus adapter only in the eval image, for the comparison table.
- [§2.17 Hidden-test integrity] Adopt 93 §4.9:
- no thresholds, dictionaries, mappings, templates or prompts derived from Речников;
- `inspector-score` refuses TEST_HIDDEN;
- CI greps code and config for F0205–F0417, «Речников», «Ривер Парк», 01-07/22-14 and 01-07/23-14;
- nobody reads Речников outputs before the frozen submission is sent;
- reruns only after content-agnostic crash fixes, logged;
- tag `hidden-run-freeze` + config_hash;
- no cloud processing without explicit approval.

Additions:
- Quarantine corpus_rechnikov_profile.json and the Речников-specific facts in 93/94 (e.g. which ПОС-кор3 is a copy, the foreign з/у 7/8 document) in docs/analysis/_hidden_quarantine/, never read by code. The pipeline must discover such facts through generic mechanisms validated on train objects.
- Engineering priorities may use only public manifest metadata: stages, sections, names, page counts.
- [§3.1 Agent roster, 11 × Opus]

**Recognition (3 agents, ≈38 d, about 26% of capacity)**
- **AG-02A Recognition Core (recognition lead) ≈12 d:** R-01 benchmark, R-02 OCR v2, R-03 orientation, R-04 router + text-layer repair, R-05 render policy, R-10 zones, R-14 batch runner/cache/CoreML, §11 performance, viewer tiles.
- **AG-02B Drawings & Layout ≈12 d:** R-06 code corrector, R-07 title block + QR + sheet↔page, OCG toolkit, revision clouds, R-15 room index, tag grammar and spotter, PD↔RD sheet matching, DWG twin page map, optional ezdwg.
- **AG-02C Tables, ИД & NLP ≈14 d:** R-08 typed tables; R-09 binder typing + АОСР, реестр, протоколы, документы о качестве, сертификаты and ИГС parsers; R-13 NLP + ~35 re-prioritised profiles; normalisation library; PD element–room assertions; absence proof.

**Other agents**
- **AG-00 Platform, Contracts & Ops ≈12 d:** absorbs AG-09 (auth/RBAC, audit, monitoring, notifications, РиН stub, NFR docs); contracts-lite; batch import.
- **AG-01 Ingestion, Registry & Integrity ≈12 d.**
- **AG-03 Matrix & Domain ≈8 d.**
- **AG-04 Comparison, Submission & Protocol ≈14 d.**
- **AG-05 Verification & Learning Loop ≈12 d:** absorbs lean M4/M10.
- **AG-07 Hypotheses & FREE findings ≈10 d.**
- **AG-08 Web & Admin ≈14 d:** viewer with layer toggle and revision clouds.
- **AG-10 Evaluation, QA & Dev data ≈12 d:** inspector-score, inspector-eval, T-GOLD gate, N-GOLD labelling mode + freeze, LOO, hidden-run runbook and guards, M12 negative scenarios + self-test.

AG-01 and AG-03 add about 10 d of recognition-adjacent work. AG-06 and AG-09 are retired as separate agents; their reports remain design references.
- [§3.2 Milestones (estimates from M0 with 11 parallel agents; completion over date)]
- **M0 contracts-lite & data hygiene, ≈1–1.5 d:** pinned schema; JSON Schemas for PageTokens, ExtractedValue, Finding, EvidenceRef and Protocol; the new enums; params seeded from the catalog; manifest loader + sha256 resolver including the 19 recovered files; inspector-score v0 reproducing the 93 §2.3 cases; T-GOLD fixture test; R-01; CI guards.
- **M1 Train-E2E-0, ≈ day 5–6:** inspector-batch on Тюменская produces a schema-valid submission with 10/10 keys, the gold pages under the anchor rule, the gate OK, ≤ 5 extra keys, RT-01…RT-10 green and the runtime logged.
- **M2 Train-E2E-1, ≈ day 9–10:**
  - Новослободская runs fully (4.1k pages) and crash-free;
  - 132 rows on both train objects reproduce the 95 §4.3 stage matrix;
  - АОСР, реестр and ИГС parsers work;
  - КР comparators with directional triggers and F/W handling;
  - integrity rules R1–R15 pass;
  - N-GOLD is labelled and frozen.
- **M3 hidden-ready & freeze, ≈ day 13–15:**
  - breadth for АР, ГП/СПЗУ, КЖ, ЭОМ and ВК;
  - the ИД pipeline at scale;
  - revisions, archives and twins;
  - ingest of files > 50 MB;
  - LOO calibration and hedge/FP budgets;
  - a content-agnostic Речников smoke test (inventory and archive listing only);
  - the freeze tag.
- **M4 hidden run, ≈1 d:** one native run on an idle machine (2–4 h), producing JSON + strict + sidecar + protocol.
- **Product track:**
  - D1 (with M1): Тюменская imported, Приложение 2 protocol, verification of 10 findings, dashboard.
  - D2 (with M3): all 12 modules clickable, ≥ 30 negative scenarios.
  - D3 (after M4): release candidate, rehearsal, backup video; the Речников protocol is shown only after the submission.
- [§3.3 Critical path to the first submission JSON (TRAIN)]
1. AG-00 contracts-lite.
2. AG-01 manifest/sha256 resolver + Python run manifest.
3. AG-02A R-01 benchmark.
4. R-02 OCR core.
5. R-04 router/coverage (outlined tags captured on F0201 p17/p18).
6. AG-02B R-07 title block + sheet↔page, and R-15 room index + tag grammar (rooms 012, 140, 142, 147, 198, 314 and 267–272 located, including 314 on RD p20).
7. AG-04 per-room multiset and presence/absence comparators, group→atomic split, anchor-page rule.
8. AG-04 exporter with jsonschema validation.
9. AG-10 inspector-score = 10/10 with the gate OK.

Parallel feeders:
- AG-02C PD element–room assertions + absence proof → AG-07 FREE path (FREE-HEATING-001 numbering).
- AG-03 catalog codes, change map and value templates.

95_tyumen_dev_fixtures.json lets AG-04 and AG-07 start before recognition lands.
- [§3.4 Critical path from train to the hidden submission, and cut order]

Path:
1. R-14 batch runner: per-file jobs, 50-page chunks, sha256 cache + resume, CoreML, frozen config hash.
2. ИД binder pipeline (AG-02A/02C): orientation, header-band typing, STAMP_PAGE skip, and the АОСР, реестр, ИГС, протокол and документ о качестве parsers.
3. AG-01 revisions, identity and archives.
4. AG-04 comparators for КР/КЖ, АР, ГП/СПЗУ, ЭОМ and ВК, plus the 132-row precedence.
5. Новослободская run + N-GOLD labels.
6. LOO calibration.
7. Freeze.
8. Hidden run.

Cut order if late: product depth first (M10 polish, ML screens, admin dry-run, ELK, ezdwg, VLM). Never cut the T-GOLD gate, the gate policy, the ИД pipeline or the integrity rules.
- [§3.5 Immediate next steps]
1. The user answers the 7 questions.
2. Move the 19 recovered files out of /private/tmp to a durable folder, e.g. /Users/evgen/pl/hackaton/data_recovered/novoslob/. Copy the OCR models and the prototypes (codefix.py, expl_parse.py, score_proto.py, bench_lib.py, recognition_benchmark.json harness) into the repo's tools/.
3. Quarantine corpus_rechnikov_profile.json.
4. Free disk to ≥ 100 GB.
5. Install the container runtime and create the repo.
6. Start M0, with AG-10 (scorer) and AG-02A (benchmark) first, because they are the acceptance gates for everything else.
- [§3.6 Recognition quality gates (the user's top priority; acceptance on recognition_benchmark.json and the Тюменская fixtures)]
- Bench A CA ≥ 0.965 strict (CI low ≥ 0.95).
- Bench B+D ≥ 0.965.
- F0001 p1 ≥ 0.99.
- Orientation 100% on the rotation set plus 50 hand-checked ИД pages.
- Codes EM ≥ 0.95 on 17 stamps.
- Scan key fields relaxed EM ≥ 0.93.
- Room tokens EM ≥ 0.95.
- Sheet = stamp ≥ 0.95 on F0201/F0202.
- ≥ 90% of OCR-only lines captured on F0201 p17/p18.
- Explication rows ≥ 0.98 exact (116 rows).
- ИД doc type ≥ 0.9 on 80 labelled pages.
- A 100-page ИД scan in ≤ 180 s on an idle host.

AG-02A owns the benchmark and publishes a recognition scorecard at every milestone. OCR ground truth becomes human-checked after Q3.

## Plan changes

- **Two run modes on one engine. `inspector-batch` is Python-native with no DB or RabbitMQ, uses CoreML, and produces the scored submission plus the protocol. The web product imports the same run directory (same claim-check artifact schema) through `POST /api/v1/admin/batch-runs/import`.**
  - Why: The automated score depends only on the submission, and the demo must show the same numbers. Docker on macOS cannot use CoreML, and the hidden run needs 2–4 h natively.
  - Affects: PLAN §3, 90 ruling 8, §3.6, §3.11, 00, 06, 92 §3.1.2
- **Add the submission contract (new 90 §3.15) and an exporter that writes schema-validated `submission/<object_id>.json`, a strict variant and a sidecar. The СХЕМА GOLD export becomes secondary.**
  - Why: This is the machine-scored format (60/15/15/10 plus the gate).
  - Affects: 90, 04, 06, 10, 92
- **AG-10 owns `inspector-score`: it replicates 60/15/15/10 plus the gate and its variants, and applies integrity rules R1–R15. The Тюменская 10/10 fixture becomes a must-pass CI gate, with leave-object-out calibration on T and N-GOLD. `inspector-eval` stays for ТЗ §14.**
  - Why: It is the only way to calibrate without touching the hidden object.
  - Affects: 06, 10, 91, 92
- **Gate-aware emission:
- recall-first on Критическое parameters;
- top-2 code hedging when the runner-up p ≥ 0.1, with a hedge budget ≤ 20%;
- all 132 rows at OBJECT;
- FREE-* only when evidence-bound.**
  - Why: One missed approved critical checkpoint caps the score at 59. On train, one missed room or one wrong code dropped the score from 91–94 to 59.
  - Affects: PLAN §1, 04, 07, 92
- **`params.code` becomes the catalog code. `alias_codes[]` holds M-xxx and the ТЗ Latin/Cyrillic short forms, checked by a prefix-validated parser. FREE-<TOPIC>-<NNN> is numbered per finding group.**
  - Why: The scorer keys on catalog codes. All code styles share param_id, and Приложение 2 has one wrong code (AR-14 = AR-040).
  - Affects: 90 §3.3.3, T-13, C-38, 03, 04, 08, packages/contracts
- **Routing by element family with `parameter_mapping_status`: warm floors go to FREE-HEATING-001 and ventilation to IOS4-078/079. Enforce directional triggers. Additions and relocations are context only; ИД≠РД is emitted only in the violating direction. Hedge pairs come from the matrix near-duplicates.**
  - Why: This is the organizers' gold taxonomy; the old M-077 routing costs 36 points on train. It also avoids false-positive traps found on Новослободская.
  - Affects: 90 §3.12, 03, 04, 07
- **Add enums ViolationLabel, ProtocolParamStatus, CriticalityLevel, ParameterMappingStatus, ComparisonResult, LocationType, MatrixScope, ManifestStage, LocalFileStatus, TextSource and ArchiveMemberRole, plus the status mapping and per-parameter precedence rules. Restore `criticality_level` next to `review_priority`. Add generated Checks columns `pd_value`, `rd_value`, `id_value`, `document_status`, `violation_label` and `protocol_status`.**
  - Why: They are the submission fields and the v1.0 table fields. Criticality drives protocol sections 4, 5 and 7 and the gate.
  - Affects: 90 §3.2.1, §3.3, 03, 04, 05, 08
- **The protocol becomes the Приложение 2 form verbatim, with Приложения А (five §9.2 tables), Б (evidence cards) and В (registry and versions). DOCX comes from a template authored from the sample; PDF is rendered HTML→Gotenberg Chromium with Selawik and Noto Color Emoji. A golden string test checks parity.**
  - Why: Приложение 2 is mandatory in both ТЗ versions, and v1.1 additionally mandates the tables and cards.
  - Affects: 04 §3.10, 08, 90 ruling 21
- **The manifest becomes the registry (VALID_WITH_WARNINGS) and files are identified by sha256.
- RD_ID_MIXED/UNKNOWN stages are resolved per file and per logical document.
- Revisions come from title blocks, Разрешение numbers, СП-кор3, «Сопоставительная ведомость», Изм rows and page hashes; file names are only a weak prior.
- Near-duplicates are found by text hash; object identity is checked per page.
- GROUND_TRUTH_INDEX files are excluded from evidence.
- Missing-on-disk is kept distinct from MISSING_DOCUMENT.**
  - Why: The package has no revision or approval fields. Misleading file names occur. Integrity and split handling is worth 10 points.
  - Affects: 01, 90 §3.2.7, 10
- **Revision selection, completeness and scenario move from Node/TS to Python `inspector_registry`. There is one implementation: Node calls it via ml-api and persists the results, and inspector-batch calls it directly.**
  - Why: The scored batch path has no Node or DB, and two implementations would drift.
  - Affects: 90 ruling 9, §3.6, 01, 04
- **Intake of archives, DWG and DOCX:
- archives read with bsdtar/libarchive (never unrar); cp437→cp866 names; bidi and Cf characters stripped; zip-bomb and traversal guards;
- members registered as non-citable `archive_members`;
- DWG linked to its same-folder PDF twin and never cited; ezdwg optional at P3;
- DOCX change notes feed the revision chain;
- server-side batch ingest bypasses the 50/200 MB HTTP limits, while UI upload keeps the ТЗ limits and formats.**
  - Why: The hidden object has 38 archives with 662 DWG (all with PDF twins), cp866 and bidi names, and 32 files over 50 MB. Homebrew unrar is SIGKILLed on this Mac.
  - Affects: 01, 02, 00 (ex-09), PLAN §8
- **Recognition core v2:
- PP-OCRv6-small detector + PP-OCRv5 cyrillic recogniser, with no text-line classifier;
- tiled detection with seam merge; score-driven retries; v6-medium fallback;
- native DPI clamped to [150, 300];
- own orientation detector with OSD tie-break;
- word-level coverage routing;
- garbled-layer detection and repair;
- code corrector + registry prior;
- Tesseract rus removed from the runtime.**
  - Why: Measured on real pages: 0.870 → 0.967/0.968 character accuracy, codes 0.09 → 0.91 and 19/19. 65% of RD drawing lines are curves.
  - Affects: 02 §3.2–3.4, PLAN §2–3, 90 ruling 22
- **Drawings and layout toolkit: CAD OCG layer-isolated rendering, wall and duct layers, revision-cloud zones, and a title-block reader (cells, Изм rows, QR, sheet↔page map with smoothing and duplicate detection). Add a room index across sheets, a tag grammar and closed-vocabulary spotter, and a per-room multiset comparator.**
  - Why: Gold anchors are group-level (room 314 is cited on p18 but drawn on p20). Stamp sheet numbers are off by one in the gold, and RD tags are strokes. The revision cloud sits exactly over the gold rooms.
  - Affects: 02, 01 §3.9, 04, 08 viewer
- **Typed header-anchored tables (EXPLICATION with Σ checks, TEP, SPEC_21110, DEVIATION/ИГС, CHANGE_LOG, АОСР + реестр) and ИД binder segmentation into logical documents (header-band typing, STAMP_PAGE skip, «Реестр ИД» parsing). NLP runs on row-context strings with geometric value fetch and a normative-vs-object filter.**
  - Why: find_tables fails on the real sheets, while the header-anchored parser got 32/32 rows. ИД arrives as 300–500-page scanned binders. e5-small finds labels, not values.
  - Affects: 02 §3.8, §3.11, 01, 03
- **Re-prioritise the ~35 deep profiles to the disciplines where the public manifest shows at least two stages on the hidden object: КР/КЖ + ИД, АР, ГП/СПЗУ, ЭОМ, ВК. Size the ventilation comparator to the Тюменская fixture and the demo.**
  - Why: The hidden object has no RD for ОВ, СС or ПБ. Effort priorities may use public manifest metadata only.
  - Affects: 02, 03, 92
- **New 11-agent roster with 3 recognition agents (AG-02A core/lead, AG-02B drawings and layout, AG-02C tables/ИД/NLP). AG-09 is absorbed by AG-00, AG-06 is split between AG-05 (lean M4/M10) and AG-10 (scoring/eval). Title-block ownership moves to AG-02B.**
  - Why: The user made recognition the top priority. The scope of AG-06 and AG-09 shrank with the dropped УКЭП, РиН depth and synthetic corpus.
  - Affects: PLAN §4, 90 §1.2, §3.13, §3.14
- **Replace CP0–CP3 with milestones M0 (contracts-lite), M1 (Тюменская 10/10), M2 (both train objects, 132 statuses, N-GOLD), M3 (hidden-ready + freeze) and M4 (single hidden run), plus product demos D1–D3.**
  - Why: The first scored artifact on train is the new golden thread. The deadline is completion-first.
  - Affects: PLAN §5, 90 §3.14, 92 §10
- **Adopt the hidden-test integrity rules and quarantine corpus_rechnikov_profile.json and the Речников-specific facts. The pipeline must discover them through generic mechanisms validated on train.**
  - Why: Fair play and ТЗ §14.2. The analysis profile already holds content-level hits on the hidden object.
  - Affects: 10, 92, docs/analysis
- **Drop УКЭП/ГОСТ signing, mTLS, the synthetic retraining corpus, the organizer letter, ELK and the pilot 9/9 depth. Reduce РиН to a stub, M4 to a lean loop, and SLA/IDS to documentation.**
  - Why: User decisions; this frees about 35–40 agent-days for recognition and the scored path.
  - Affects: PLAN §7, §9, 90 rulings 20, 21, 09, 06
- **Re-base the demo on real objects: the Тюменская gold with the revision-cloud and QR proofs, Новослободская АОСР, the real explication double count, the 658 MB binder segmentation and the Приложение 2 protocol. Pilots become fixtures only.**
  - Why: The jury sees the organizers' own objects, and the demo reuses the scored engine.
  - Affects: 92 §3.2, PLAN §1, 90 §9
- **Store the 19 recovered Новослободская files (already sha256-verified) durably outside data/ and data_utf8, and move the models and prototype scripts from /private/tmp into the repo.**
  - Why: The scratchpad is ephemeral, and these files feed N-GOLD and the KR-054 axes checks.
  - Affects: 01, 10
- **Fix matrix_enriched.json: the M-044 catastrophic-backtracking regex (with a time/length guard on all regexes), and context gates for «В20» vs «B20» and «ИД» vs исходные данные.**
  - Why: M-044 hangs on long CAD pages, and the concrete-class regex fires on ventilation system names.
  - Affects: 03
- **Add a «v1.0 delta» column to 91. v1.1 governs the internal logic, v1.0 binds the protocol form and the status table, and the package binds the submission. Add API aliases CONFIRMED↔CONFIRMED_VIOLATION and REJECTED↔NEGATIVE_VERIFIED.**
  - Why: Two ТЗ vintages coexist, and the train gold uses v1.0 statuses.
  - Affects: 91, 05, 90
- **Disk and cache policy: cache text and OCR as compressed JSON keyed by sha256 plus pipeline version, never persist full-page renders, and free ≥ 100 GB before M3.**
  - Why: Only 68 GiB is free. 16k renders would take 30–50 GB.
  - Affects: 02, 00

## Questions for the user

1. **Should the scored run on OBJ-RECHNIKOV-7-7 use the recommended risk policy? It has four parts:
(a) Recall-first on Критическое parameters. When the runner-up code has p ≥ 0.1, emit both codes, with hedges capped at 20% of critical checks.
(b) One row for each of the 132 parameters at location «OBJECT», labelled NO_VIOLATION, MISSING_DOCUMENT or COMPARISON_IMPOSSIBLE. This can be switched off.
(c) No separate findings for additions or relocations; ИД≠РД emitted only in the violating direction.
(d) FREE-* findings only when evidence-bound, at most about 5 groups.**
   - Options: Recommended package (a+b+c+d) | Conservative: no hedging, violations only, no FREE-* | Aggressive: hedge every ambiguous critical code, emit additions and all ИД≠РД changes
   - Recommendation: The recommended package. Final thresholds are set leave-object-out on Тюменская plus the Новослободская labels, never on Речников.
   - Why it matters: One missed approved critical checkpoint caps the total at 59/100. On train, a single missed room or a wrong IOS4 code turned 91–94 points into 59. Each hedge costs about 2–4 F1 points. The 132 rows probably earn status points and protect against a broader reading of the gate; they only hurt if the organizers' F1 counts all labels.
2. **How may LLMs/VLMs be used? You asked for details, so here they are.

Where they help:
1. Reference texts, written offline from the public ТЗ/matrix, reviewed by a human, then frozen:
   - the 132 «Вид работ / Конкретная рекомендация» templates for Раздел 7;
   - short names, element nouns and synonym dictionaries.
   The runtime stays deterministic.
2. A «second opinion» on the hardest recognition step: comparing per-room equipment on dense drawings and assigning outlined labels to rooms. Its output is accepted only if every tag it names is present in our OCR tokens in that zone. Confidence is capped at 0.6; it is never evidence and never sets a status.
3. Development help on train objects: pre-filling labels and error analysis.

The two ways to run a model:
- **Local:** Qwen2.5-VL-7B or Qwen3-VL-8B at 4-bit via Ollama/MLX. About 6 GB RAM, 15–40 s per crop question, moderate quality on small CAD text, fully offline.
- **Cloud** (Claude/GPT/Gemini class): much better on drawings, about $0.01–0.05 per crop pair (a few dollars per object). The documents leave the machine, title blocks contain personal names (152-ФЗ), the product would need the internet, and using it on Речников raises hidden-test fairness questions.**
   - Options: A: none (fully deterministic) | B: offline drafting of reference texts only | C: B + a local VLM second opinion at runtime (P2, after the deterministic comparator is measured) | D: B + cloud models on train objects for development only | E: cloud models also on Речников as a frozen pipeline step
   - Recommendation: B + D now; C as P2 if the measured deterministic comparator leaves recall on the table; not E. The product ships an offline-only adapter that is off by default.
   - Why it matters: Раздел 7 of Приложение 2 needs 132 concrete recommendations, and there is no other realistic way to reach that quality in time. Drawing comparison is where recall is weakest. Cloud use on organizer documents conflicts with 152-ФЗ, the closed-contour product and hidden-test integrity.
3. **You said human review time is available. Please confirm this budget:
1. Новослободская self-labels («N-GOLD»): about 110 items in our labelling view, about 2 h, plus 15% double-labelled by a teammate (about 20 min). This happens right after milestone M2.
2. OCR ground truth: re-check the 6 hand-transcribed pages (about 40 min) and transcribe 8 more ИД scans (about 50 min). This can be done any time from now.
3. Expert review of about 40 recommendation templates and about 40 normative references used in the demo: about 1.5–2 h, after AG-03 drafts them.
Total: about 5 h.**
   - Options: Full ≈5 h (recommended) | Minimum ≈2 h: 30 N-GOLD items + OCR re-check + 20 templates | None: agent-made labels only
   - Recommendation: Full ≈5 h, scheduled at the three points above.
   - Why it matters: N-GOLD is the only way to measure precision and FPR and to calibrate thresholds without touching Речников. Human-checked OCR ground truth makes the CA ≥ 0.95 / EM ≥ 0.90 claims defensible. Reviewed templates make Раздел 7 credible to inspectors.
4. **Three domain calls on routing, for you or a teammate with construction expertise:
(a) Concrete delivered with the same strength class but a lower frost/water mark than the RD requires (e.g. F150 vs F200): is it a KR-055 violation, a FREE-STRUCTURE finding («Существенное — требует утверждения»), or ignored?
(b) A value that increases where the trigger says «уменьшение/понижение» (e.g. a thicker slab): is it no violation?
(c) ИД elevations above the design top, within normal over-pour: is it not a violation?**
   - Options: Recommended: (a) FREE-STRUCTURE with PD+RD+ID evidence, (b) NO_VIOLATION, (c) not a violation | Stricter: (a) KR-055, (b) flag as VALUE_MISMATCH, (c) flag | Give your own rule per item
   - Recommendation: The recommended set.
   - Why it matters: КР/КЖ is the discipline with PD, RD and the largest ИД binders on the hidden object (public manifest). Routing to a critical code without cause risks false positives on critical parameters; routing too cautiously risks gate misses.
5. **What does the hackathon portal or chat say about:
(a) how answers are uploaded (file name, one file per object, zip);
(b) whether there is a jury demo or presentation, and its length and format;
(c) whether code must be submitted or be runnable by the jury?**
   - Options: I will check and tell you | Unknown: use the defaults
   - Recommendation: If unknown:
- submit OBJ-RECHNIKOV-7-7.json exactly per the schema, with the strict variant ready and the sidecar kept separately;
- plan a 12-minute live demo with a backup video;
- ship the repository with `make demo` (containerised infrastructure plus native ML).
   - Why it matters: Packaging may affect the integrity and split points. The demo format decides how much effort goes to the product track (12 modules, protocol, verification UX) versus the automated score.
6. **Which container runtime should we use? You asked why OrbStack.

**What Docker is for.** Docker is now needed only for infrastructure: PostgreSQL, RabbitMQ, Valkey, Gotenberg (LibreOffice + Chromium for protocol PDFs), Mailpit and optional ClamAV. The scored OCR batch and the demo ML workers run natively on the Mac, because CoreML doubles detector speed and Docker on macOS cannot use it.

**Why OrbStack was proposed.** On Apple Silicon it is the lightest and fastest runtime: low idle RAM and CPU, dynamic memory, fast VirtioFS file sharing, Rosetta for amd64 images, and the usual docker/compose CLI. That matters because the laptop also runs a 10-worker OCR batch. OrbStack is free for personal use but needs a paid licence for commercial use.

**Alternatives.**
- Colima: MIT-licensed, free, CLI-only, slightly slower file sharing. Now that ML runs natively, it is just as adequate.
- Docker Desktop: works but is the heaviest.

**Disk.** Only 68 GiB is free (93% used). We need about 100 GB free for caches, images and recovered data.**
   - Options: OrbStack | Colima | Docker Desktop | No Docker: Homebrew services (postgres, rabbitmq, valkey) plus host LibreOffice
   - Recommendation: OrbStack if the hackathon counts as personal use, otherwise Colima. A 4-CPU / 8 GB VM is enough now. Free about 40 GB more disk or attach an external SSD.
   - Why it matters: It is needed before the web stack starts (M0) and for a reproducible `make demo` for the jury. Disk space is a hard limit for the hidden-run cache and the images.
7. **Repository and data location:
- Create a private GitHub repository with Actions? Organizer data is never committed, CI runs only small fixtures, and the hidden run stays local.
- Store the 19 recovered, sha256-verified Новослободская files in /Users/evgen/pl/hackaton/data_recovered/, outside data/ and data_utf8/?**
   - Options: Private GitHub repo + Actions, data_recovered/ as proposed | Local git only, data_recovered/ as proposed | Another location or account (tell us which)
   - Recommendation: A private GitHub repo with Actions, and data_recovered/ as proposed.
   - Why it matters: AG-00 needs the repository to start M0. The recovered files currently sit in the session scratchpad under /private/tmp, which is not durable.

## Install needs

- Container runtime (Q6): OrbStack or Colima with a 4-CPU / 8 GB VM. Images: postgres:17, rabbitmq:4-management, valkey/valkey:8, gotenberg/gotenberg:8 (LibreOffice + Chromium inside; add the Selawik and Noto Color Emoji fonts), axllent/mailpit, and clamav as an optional image (about 1.5 GB RAM). No ELK.
- Disk: free at least 100 GB (68 GiB is free now) or use an external SSD for caches. Keep caches as compressed JSON keyed by sha256 + pipeline version, and never persist full-page renders.
- Python 3.12 ML environment via uv (Homebrew python3.12 is already present): pymupdf 1.28.x, rapidocr ≥ 3.9.2, onnxruntime ≥ 1.20 (1.30 tested; its macOS wheel includes the CoreML execution provider), opencv-python-headless, numpy, shapely, rapidfuzz, jsonschema (Draft 2020-12), python-docx, openpyxl, py7zr, orjson, pydantic, fastapi + uvicorn (ml-api), faststream/aio-pika (web mode), and an e5-small ONNX runtime (tokenizers). optimum/onnx are needed only at build time, to export multilingual-e5-small.
- OCR models pinned by sha256, downloaded by a script with checksums and kept outside git: PP-OCRv6_det_small.onnx (9.9 MB), PP-OCRv6_det_medium.onnx (62 MB), cyrillic_PP-OCRv5_rec_mobile.onnx (8 MB), multilingual-e5-small ONNX. tessdata_best rus.traineddata is kept only for the benchmark comparison and is already in the scratchpad.
- Archives: use the system bsdtar/libarchive on the host (present, libarchive 3.7.4) and libarchive-tools in the Docker images. Do not use the Homebrew unrar (it is SIGKILLed, exit 137), and rarfile is not needed.
- Node: enable pnpm via corepack (Node 22.22 is present). Use NestJS 11 on Fastify and Drizzle, with docx-templates or python-docx for the Приложение 2 DOCX template.
- Fonts: Selawik (SIL OFL, metric-compatible with Segoe UI) and Noto Color Emoji in the renderer image. They are optional on the host.
- Optional: ezdwg (MIT, pip) for DWG enrichment at P3. On linux-aarch64 it needs a Rust sdist build or an amd64 image.
- Optional, only if Q2 = C: Ollama or MLX-VLM with qwen2.5vl:7b (about 6 GB).
- Not needed: brew tesseract-lang, LibreDWG, ODA File Converter, LibreOffice on the host (Gotenberg covers it), unrar, torch at runtime, toxiproxy (use app-level fault injection instead), ELK.
