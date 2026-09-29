# 91 — ТЗ Traceability & Completeness Audit («Инспектор ИИ»)

Role: ТЗ traceability / completeness critic (planning phase, no application code).
Requirement prefixes used here: **TZ-NNN** = one atomic requirement extracted from the ТЗ and its annexes (the rows of the traceability matrix); **TRC-NN** = requirements on the traceability function itself; **F-NN** = findings (gaps, conflicts, silent downgrades).
Sources: `docs/spec/01_TZ_text.txt` (read line by line, §1–§14, every table row), `02_matrix_all_sheets.txt` (sheets СХЕМА GOLD, МЕТРИКИ, ПРИМЕРЫ РАЗМЕТКИ; МАТРИЦА spot-checked), `03_perechen_ID_registry_rules.txt`, and the eleven block reports `00_…`–`10_…` (sections 1–2 read in full for all, design/decision sections read where a conflict was suspected). Checklist IDs cited: ARC (B00), ING (B01), EXT (B02), MTX (B03), CMP (B04), VER (B05), MLF (B06), HYP (B07), UI (B08), PLT (B09), ERR (B10); 868 block requirements in total.

Block IDs in this report are the **report-file IDs** (B01 = `01_ingestion…`, B02 = `02_extraction…`, … B10 = `10_error…`). Several reports use a different, module-based numbering (see F-16 and §3.1).

---

## 0. Executive summary

**Coverage result.** I extracted **389 atomic ТЗ requirements** (TZ-001…TZ-389). Every one maps to at least one block requirement, apart from 3 small gaps. Tally by status:

| Status | Count | Meaning |
|---|---|---|
| OK | 316 | Covered, consistent across blocks, MVP decision meets the letter |
| PARTIAL | 25 | Covered, but SIMPLIFIED/MOCKED in a way that does not fully meet the letter; acceptable if labelled honestly |
| CONFLICT | 37 | Covered, but blocks disagree on priority, MVP level, design, owner or enum |
| DOWNGRADED | 4 | Mandatory ТЗ wording, but the covering blocks mark it SHOULD/NICE/OUT_OF_SCOPE or proxy-only without adequate justification (TZ-035, TZ-036, TZ-222, TZ-247) |
| GAP | 3 | No block requirement covers it, or the coverage is unverified (TZ-002, TZ-372, TZ-389) |
| DATA | 4 | Blocked by input the organizers have not supplied (TZ-041, TZ-115, TZ-152, TZ-327) |

(Counts come from the Status column of §2 and were tallied mechanically; a row has exactly one status. Rows where one block downgrades a mandatory item and others do not are classed CONFLICT, e.g. IDS TZ-308, УКЭП TZ-310, hidden-works TZ-037.)

**The block reports are strong on breadth.** All 12 modules, all 16 tables, all 15 performance rows, all 11 security rows and all 8 monitoring rows are covered. The risk is **not missing scope**. It is (a) cross-block **conflicts** that will surface as integration bugs, and (b) a few **mandatory items quietly downgraded**. Five findings are critical:

1. **F-01** Приложение № 2 (the mandatory protocol form) is missing. The protocol layout is our guess until the organizers answer.
2. **F-02** There is **no single candidate / change-routing policy**. Four blocks decide differently what becomes a scored CANDIDATE and who emits it: B03 (strict triggers + room-level M-003), B04 (default DEVIATION), B07 (claims 6 of 8 pilot groups for Module 5, with auto-promotion) and B06 (a learned scorer that may demote to NEGATIVE_VERIFIED). This single choice drives Precision, Recall, F1 and FPR on the hidden test.
3. **F-03** Incremental upload during verification: B01 moves the process to PARSING, while B00, B05 and B10 keep the status and run a sub-state. B01's model breaks §9.3 п.3 «без сброса верификации».
4. **F-04** The «Обязательное проведение юзабилити-тестирования на выборке из 5 инспекторов» was downgraded to SHOULD (B00, B08) or to proxy testers (B05).
5. **F-05** Nobody owns **achieving** the §14.3 thresholds. There is an excellent harness (B06), but no proxy-test target, no error budget and no iteration plan, and ~97 of 132 parameters have only generic extraction. §14.3: «Система не считается принятой при недостижении любого обязательного порога».

**Structural fixes proposed in this report:**
- a canonical block → module → build-agent map (§3.1);
- a consolidated ruling table for all 30 findings, to be ratified at the CP0 contract freeze (§3.2);
- a canonical routing table for every pilot finding (§3.3);
- a `tz_requirements.yaml` + `@req`/`@tz` test-tagging scheme that turns this matrix into a live, CI-gated «Соответствие ТЗ» page for the jury (§3.4).

---

## 0.1 Findings register

Severity: **critical** = a High module or mandatory ТЗ wording is at risk, or the scored hidden-test outcome is directly affected; **major** = a mandatory requirement is weakened or blocks disagree in a way that will break integration; **minor** = cosmetic, naming or tolerance-level issues.

| ID | Sev | Finding | Blocks | Resolution (proposed ruling) |
|---|---|---|---|---|
| F-01 | critical | **Приложение № 2 missing.** §9.2: «Требования к содержанию и оформлению выходного автопротокола … определяются образцом … в Приложении № 2 … и являются обязательными». Not supplied. CMP-49 is SIMPLIFIED. Two interim styles are proposed: B04 copies the organizers' pilot visual language, B00 uses ГОСТ Р 7.0.97-2016 styling | B04, B08, B00 | Send a formal request to the organizers today (see §8 letter). Meanwhile keep one template-driven renderer (F-13) whose layout is data. Interim layout = B04 §3.10, the pilot's visual language, which is closest to what the authors produce, wrapped in the mandatory §9.2 п.4 sections. Label the PDF «Форма протокола — по образцу Приложения № 2 (ожидается)». Budget a 0.5-day swap task once it arrives |
| F-02 | critical | **Candidate / routing policy not unified.** B03 D-02 is strict for numeric triggers and catches the pilot via room-level M-003.b. B04 D1 makes DEVIATION the default for design-decision params. B07 claims ALT79B, UNDMS, LOS3A, POL16, DOO25 and SOSH25 as Module 5 changes and needs auto-promotion (D1b) plus a change-fact router (D2b). B03 D-08 maps only IZM12 and LOS3A outside the matrix. B06 D6 lets a learned scorer demote a discrepancy to system NEGATIVE_VERIFIED. Without one ruling, the same change is either double-counted (FP) or dropped by both (FN) | B03, B04, B06, B07 | One ruling (§3.3): (1) **Module 2 owns every change that maps to a matrix param**, using B03's map (M-003.b room-level, M-044 layer stack, M-054.b tolerance, M-077/078/079 vent). Policy is per param: DEVIATION for qualitative/configuration params, TRIGGER for pure normative bounds (B03 D-02a + B04 D1c agree on this split). (2) **Module 5 owns only unmapped changes** (IZM12, LOS3A, logical/normative/ML rules). B07 D2b is the router, seeded from B03's map. (3) **Auto-promotion SUSPICION → CANDIDATE is allowed only** when the full §9.2 п.4 card passes the validator, with `promoted_by=SYSTEM` and the SUSPICION kept for audit (B07 D1b). (4) **The learned scorer changes risk ordering only** until a real-GOLD gate passes (F-19). The user ratifies in D-U2 |
| F-03 | critical | **Process status during incremental upload.** B01 §3.7 moves READY/VERIFYING/COMPLETED → PARSING on every upload. B00 §6 #3, B05 §3.4 and B10 X1 keep the status and use `recheck_state`. With B01's model, verification is blocked during every re-parse (§9.1 table: PARSING = «верификация: Нет»), which contradicts §9.3 п.3 | B01, B05, B00, B08, B10 | Adopt B00/B05: PARSING is used only for the initial parse (and for a re-parse from READY before any decision). Later uploads keep the status and set `recheck_state=RUNNING`; only the affected findings are locked; finalization is blocked until the recheck ends. B01 rewrites §3.7 (gating table, ING-73/74) and B08 renders the sub-state. Upload into FINALIZED = 423 PROTOCOL_FINALIZED (B10 X2) |
| F-04 | critical | **Usability test with 5 inspectors downgraded.** §9.3: «Обязательное проведение юзабилити-тестирования на выборке из 5 инспекторов с последующей доработкой интерфейса до достижения целевых метрик». ARC-33 and UI-86 are SHOULD/SIMPLIFIED; VER-69 is MUST but uses proxies | B05, B08, B00 | Raise to MUST everywhere. Ask the organizers (Мосгосстройнадзор is the customer) for 5 inspectors for 30-minute remote sessions on the «УТ-1» protocol (B05 §3.17). Run a proxy round first and fix the UI, then the real round. Report SUS, clicks per violation and time per protocol from built-in telemetry (VER-68). If no inspectors are available, show the proxy results with an explicit disclaimer. Never claim the ТЗ test was done |
| F-05 | critical | **No owner for achieving §14.3 thresholds.** B06 builds the harness and gate (MLF-35…46). B02 measures OCR on proxies. But no block sets proxy targets per metric, an error budget or an iteration plan. Recall is exposed through generic extraction (EXT-18/CMP-91: deep profiles for only 30–35 params). Localization ≥ 0,95 at IoU ≥ 0,5 is exposed because expert boxes are region-level (B02 risk 1) | B02, B04, B06, B00 | Name a **Quality owner** (AG-09 with AG-02). Freeze a proxy hidden test in week 1: pilot 9 groups + 3 vent + synthetic objects, object-split, SHA-256 locked. Run `inspector-eval` nightly with a per-metric target 2 pp above the ТЗ threshold. Keep an error budget per metric and parameter. Precision/FPR guard = abstain policy (B03 MTX-41, B10 ERR-23). The recall plan prioritises tier-A/B params in ПЗ/АР/КР, where the pilot shows the hidden test is concentrated. Report CI and n honestly (MLF-44) |
| F-06 | major | **132-parameter coverage is SIMPLIFIED.** «извлечение данных по 132 параметрам» (§7 M1 High) and «Для каждого параметра (i) из 132» (§9.2 п.3). EXT-18 and CMP-91 give deep treatment to about 30–35 params. MTX-58 does CV on 1–2 params. The rest is generic | B02, B03, B04 | Hard invariant: **every active param yields exactly one definite status per object in every run** (MTX-57): CANDIDATE, NEGATIVE_VERIFIED, MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE or CLARIFICATION_REQUIRED, with a basis, never silence. Ship a 132-row coverage view (protocol table 1 plus an admin «Покрытие Матрицы» tab). Publish the tier list (A 38 / B 63 / C 27 / D 4) in the docs. Deepen by expected frequency, not alphabetically |
| F-07 | major | **CV (§9.1 п.3) SIMPLIFIED.** «масштабирование по размерной линейке, распознавание линий и измерение расстояний». Vector-only in practice (EXT-24…26); raster is approximate; used on 1–2 params (MTX-58) | B02, B03 | All three CV functions become MUST on vector PDFs, each with a demo endpoint (`/v1/cv/scale`, `/lines`, `/measure`) and a visual overlay. On raster (pilot p14 scan): scale from OCR'd dimensions plus LSD lines, flagged with a confidence. Measure §11 #8 per sheet. At least 3 geometric params (e.g. M-041 door width, a clear height, a room dimension) use CV end-to-end in the demo |
| F-08 | major | **§5 notes 2–3 downgraded and split.** «система осуществляет визуальную проверку наличия всех обязательных реквизитов (подписи, печати, даты, регистрационные номера)»; «Чертежи должны содержать штампы «В производство работ» и «Выполнено согласно проекту»». These are SHOULD in EXT-41/42, ING-37/39, ERR-80 and CMP-89, but MUST in MTX-30/31. Detection is claimed by both B01 and B02 | B01, B02, B03, B04, B10 | MUST everywhere. Owners: **B02 detects** (EXT-41/42: blue-ink and shape detection, regex for dates and reg. numbers, stamp phrase OCR). **B01 records** the per-file `requisites_status` and `signature_status` and applies completeness. **B04 prints** them in table (1). **B10 ERR-80** maps «реквизиты не обнаружены» → CLARIFICATION_REQUIRED for dependent groups. Demo on the pilot p14 scan (seal and signature detected) |
| F-09 | major | **§5 note 4 (hidden-works list in ОД).** ING-88 is NICE / OUT_OF_SCOPE, MTX-32 is MUST / SIMPLIFIED (PKG-HIDDEN-WORKS), and B03 HR-LOG-036 turns the same thing into a Logical rule | B01, B03, B07 | Adopt MTX-32. B02 extracts the «Перечень видов работ, для которых необходимо составление актов освидетельствования скрытых работ» from ОД. B01 adds dynamic expected АОСР items to completeness. Missing АОСР → MISSING_EVIDENCE, not a SUSPICION. HR-LOG-036 is retired or kept only as a consistency check. Fallback: an inspector-maintained list on the object card |
| F-10 | major | **DB encryption at rest SIMPLIFIED.** §12.3: «Все данные в покое (база данных, файловое хранилище) … должны быть зашифрованы». PLT-71, ARC-56 and ING-18 give column-level PII encryption plus a "documented" encrypted volume. Only the file store is FULL (PLT-70) | B09, B00, B01 | Demonstrable DB encryption. Option A (recommended): PostgreSQL data directory on an encrypted volume (LUKS on the Linux compose host or VM; FileVault on the dev Mac), plus pgcrypto for PII columns, plus encrypted backups (restic, PLT-75). Show `cryptsetup status` in the security demo. Option B: evaluate Percona's `pg_tde` for PG 17 (TDE inside the DB); verify maturity before adopting. Record as ADR |
| F-11 | major | **IDS/DDoS decisions conflict.** §12.9 «Внедрение системы обнаружения вторжений (IDS) и защиты от DDoS-атак». ARC-64 = NICE / OUT_OF_SCOPE; PLT-76/77 = MUST / SIMPLIFIED (IDS-lite + rate limits); ERR-83 = NICE / OUT_OF_SCOPE (certified IDS); ERR-49 = SHOULD | B00, B09, B10 | Adopt B09 as canonical and change ARC-64 to MUST / SIMPLIFIED. IDS-lite rules, security events and alerts, nginx limit_req/limit_conn, plus an optional `ids` compose profile (CrowdSec or Suricata on the host) shown live. The certified ФСТЭК СОВ stays OUT_OF_SCOPE with a production statement |
| F-12 | major | **УКЭП / client-certificate priority conflict.** §12.10 «Все запросы к внешним системам подписываются УКЭП»; §9.6 «Аутентификация: клиентские сертификаты (УКЭП)». PLT-12/13 = MUST / SIMPLIFIED (real GOST R 34.10-2012 via a pluggable signer + mTLS); ARC-38 = SHOULD / SIMPLIFIED; ARC-39 = SHOULD / MOCKED; ERR-43 = NICE / MOCKED; VER-52 = SHOULD / MOCKED; CMP-63 = NICE / MOCKED | B00, B09, B10, B05, B04 | Adopt B09 (`soft-gost` signer + mTLS with a dev CA) as MUST / SIMPLIFIED in all blocks. Label everywhere «алгоритмическая подпись ГОСТ Р 34.10-2012; не квалифицированная (нет аккредитованного УЦ/СКЗИ)». CryptoPro stays OUT_OF_SCOPE with a runbook |
| F-13 | major | **Three competing protocol-export designs.** B00: Node renderer + Gotenberg. B04: Node, Playwright HTML→PDF, docx-templates, xmlbuilder2 (D4a). B08: Python render worker, docxtpl → LibreOffice PDF, lxml (D16a, B08 owns). DOCX/XML are SHOULD in CMP-47/48 and MUST in UI-20/21 | B00, B04, B08 | **One renderer, one owner (AG-02), one template source.** Recommended: a single DOCX template (easiest to align with Приложение № 2, which is almost certainly a Word/PDF form); PDF via Gotenberg/LibreOffice; XML from the canonical JSON with a published XSD. B08 owns only the export UI and jobs. DOCX and XML become MUST (§7 M7 names all three formats). Measure §11 #5 (≤ 30 s) with evidence crops |
| F-14 | major | **Embedding model conflict.** B02 (EXT-17) measured `multilingual-e5-small` (34/40 top-1, 8 ms) against `paraphrase-multilingual-MiniLM-L12-v2` (22/40). B03 (MTX-10), B04, B06 (C4, "shared with Module 1") and B07 (HYP-37, D5) specify MiniLM-L12. Two encoders mean two indexes, twice the RAM, and train/serve skew | B02, B03, B04, B06, B07 | One encoder in the model bundle, config-switchable. Recommendation: **e5-small** (measured best; loadable via the sentence-transformers API, so a «совместимый аналог»). Keep MiniLM-L12 benchmark numbers in the docs as the "closest literal analogue" argument. User decides in D-U3 |
| F-15 | major | **Evidence viewer and coordinate-test mismatch.** §9.1 п.4 «это обязательно для корректного отображения разметки на повернутых и смещённых листах». B00 plans pdf.js + OpenSeadragon. B08 plans OpenSeadragon on PyMuPDF raster tiles, explicitly no pdf.js. B02-T16 builds the pixel test against PDF.js. B05 relies on the same MuPDF engine | B00, B02, B05, B08 | Adopt B08/B05: MuPDF tiles + SVG overlay in [0;1]. Retarget B02-T16 to the OpenSeadragon overlay using the 7 synthetic rotated/offset fixtures plus the 27 pilot GOLD boxes. Remove pdf.js from B00 §0 #7 |
| F-16 | major | **Block numbering and owners inconsistent.** B00 §4/§10, B03, B04 and B06 use a module-based "Bxx" numbering (B02 = comparison, B03 = verification, B05 = hypotheses, B06 = РиН …) that does not match the report files. B01, B02 and B03 name owners by role ("ml-nlp-cv", "Comparison engine (Python)", "Domain expert") instead of the AG-00…AG-09 roster. No build agent explicitly owns the matrix rule DSL/evaluator or the matrix content | B00, B01, B02, B03, B04, B06 | Freeze the canonical map in §3.1 at CP0. Rename references in the contracts and ADRs (not in the frozen analysis reports). Assign the matrix evaluator to AG-02 and the matrix content and enrichment to AG-09, with the domain-expert review (MTX-T16) as a user task |
| F-17 | major | **Dual ownership and divergent DDL for §10 tables.** Rejection_Log and Dispute_Log: "owns" in both B05 and B06; `violation_id` is bigint (B05) vs uuid (B06). Params / Normative_Base / Logical_Rules: B03 "owns/seeds", B08 "owns". Evidence_Fragments: owned by B04, but B02 "produces rows" and B07 needs extra columns | B00, B03, B04, B05, B06, B07, B08 | AG-00 is the **only DDL owner** (ARC-T06). Semantic owners per table are in §3.1. Rejection_Log/Dispute_Log: B05 writes them in the decision transaction; B06 reads them and updates `retraining_status`/`resolution_status` through an API. Params: B03 = content/schema, B08 = admin API/UI. Evidence_Fragments: B04 owns; B02 writes `extracted_values`, never fragments. Key types follow B00 §3.6 (UUIDv7; INT for params; BIGINT for suspicions/audit) |
| F-18 | major | **Logical_Rules expression language conflict.** B07 evaluates a JSON-AST (all/any/not, exists/count/sum over collections). B03 seeds 40 rules «in B05's AST» (sic: B07's). B08 builds the Logical_Rules admin with react-querybuilder → JSONLogic subset (no aggregates). §7 M8 «без перекодирования» and §10 #9 need admin-editable rules | B03, B07, B08 | Adopt B03 D-11: JSONLogic for applicability/threshold templates, the B07 AST for Logical_Rules. B08 edits Logical_Rules with a JSON editor plus schema validation, a Russian rule preview and a dry-run endpoint served by the single Python evaluator (B07). Merge the seeds: B03's 40 + B07's ~12, deduplicated, with one `code`/`version` scheme |
| F-19 | major | **Learned scorer can demote to NEGATIVE_VERIFIED.** B06 §3.2 D6: «Score < τ → a system-preliminary NEGATIVE_VERIFIED … «Расхождение отклонено моделью…»». The C1 verifier is trained on synthetic data (1 real positive, 1 real negative). B04's status rules do not include this path. B10 ERR-23 (fail-visible) says data-quality doubts must not become NEGATIVE_VERIFIED | B04, B06, B10 | MVP: the scorer only sets `risk_level` and ordering (as B04 §3.8 assumes). Quality reasons (low OCR confidence, unit mismatch) → NOT_COMPARABLE via B10's mapping. Within-tolerance noise (C3) → NEGATIVE_VERIFIED is allowed. Enable model demotion only after a gate on **real** GOLD, per category, behind a flag |
| F-20 | major | **Module 5 approach 4 downgraded.** §9.5 table #4 «ML-паттерн-анализ — Обучение на исторических данных для поиска аномалий». HYP-08 = MUST / SIMPLIFIED, but HYP-56 (cross-object historical model) = **SHOULD / MOCKED**; MTX-28 = SHOULD. Module 5 is High | B07, B03 | HYP-56 → MUST / SIMPLIFIED. A real IsolationForest/robust-z model trained on a cross-object feature store. Seed it with labelled synthetic history plus every finalized object, registered in Model_Versions (HYP-44). Ask the organizers for historical ТЭП/consumption data (§8). The demo shows «Расход бетона на 20% ниже среднего» on a synthetic object with the badge «синтетический пример» |
| F-21 | major | **Normative references and §2 mapping.** 294 sp/gost/fz/other references are drafted with confidence levels; many are LOW or «требует проверки» (MTX-07/42 SIMPLIFIED). ПП 2078, ПП 2161, ГрК ст. 49/52/53/54 and Закон 4802-1 appear only in scope lists; no requirement produces a §2 compliance statement | B03, B09 | (1) MTX-T16 domain-expert pass on at least the ~40 demo references before CP2 (user decision D-U9). (2) Normative_Base seed holds all 13 §2 acts as rows with editions as of 07.2026. (3) A one-page «Соответствие нормативной базе (§2)» in the docs, listing each act → where it is applied (B03 refs, B09 152/187/397 measures, B05 «no automatic предписание» for ГрК ст. 54). (4) The UI shows the confidence badge until verified |
| F-22 | minor | **Notification channels and priority inconsistent** (§9.2 п.5 «Инспектор получает уведомление»). ARC-28 = MUST / FULL (in-app + email + Telegram); CMP-71 = MUST / SIMPLIFIED; UI-31 = MUST / FULL in-app; VER-64 = SHOULD / SIMPLIFIED (in-app + SSE, email/Telegram out); UI-88 = OUT_OF_SCOPE (inspector email/Telegram). B08 plans polling only (SSE "optional later"), while B05 relies on SSE | B00, B04, B05, B08 | MUST: in-app (polling, per B08) + email (Mailpit). Telegram only for admin alerts (§13.7). SSE optional |
| F-23 | minor | **Stack/version conflicts.** AntD 5 (B00) vs 6.6 (B08, verified on npm); React Router 7 vs 8; TS 5 vs 6; NestJS + Drizzle (B00) vs Fastify + Kysely + node-pg-migrate (B01) vs "either" (B05); PostgreSQL 16/17; Python 3.11 (B02) vs 3.12 (B00); OCR baseline Tesseract (B00 D11) vs PP-OCRv5 primary (B02, measured); LLM default "local Ollama" (B00 D1b) vs "none" (B02, B03, B07) | B00, B01, B02, B05, B07, B08 | B00 decides backend/runtime (NestJS 11 + Fastify, Drizzle, PG 17, Python 3.12). B08's npm-verified frontend versions win. PP-OCRv5 is primary with Tesseract `rus` as fallback/OSD (both Apache-2.0). LLM default = none; the local adapter is optional (D-U1) |
| F-24 | minor | **Matrix-count control not covered.** МЕТРИКИ sheet «Контроль версии Матрицы — Число параметров 132; Ожидается 132» | B03, B08 | Publish-time invariant in `matrix_versions`: exactly 132 params with codes M-001…M-132. Admins deactivate (`is_active=false`) but never delete or add params. A deactivated param is reported as NOT_APPLICABLE with basis «параметр деактивирован администратором (версия Матрицы N)» |
| F-25 | minor | **Linear objects.** §3 «для линейных объектов входит иной перечень разделов». ING-85 = NICE / OUT_OF_SCOPE vs MTX-59 = SHOULD / SIMPLIFIED | B01, B03 | Adopt MTX-59: `object.is_linear` → all params NOT_APPLICABLE with the basis «п. 3² Положения (ПП 87) — иной состав разделов; не поддерживается в MVP». A banner on the object card |
| F-26 | minor | **Enum mismatches.** `discovery_method` ML_PATTERN (B00, B04, B08) vs ML_PATTERN_ANALYSIS (B07); GRAPHIC_DIFF only in B07. Suspicion `inspector_status`: PENDING/CONVERTED/DISMISSED (B05) vs 7 values (B07). SyncStatus (B10 X10). LINKING_ERROR vs BINDING_ERROR (B10 X15) | B00, B05, B06, B07, B08, B09 | Single `enums.yaml` (ARC-15) at CP0: ML_PATTERN_ANALYSIS (mirrors the other three `*_ANALYSIS` values of §9.5); GRAPHIC_DIFF kept as a 5th value; B07's suspicion status set; B09 SyncStatus; LINKING_ERROR (the ТЗ wording «ошибка привязки» fits either; B00 and B08 already use it) |
| F-27 | minor | **input_manifest_hash definition differs.** B01 ING-79: JCS of the effective registry + selections + versions. B04 CMP-07: JCS of the canonical registry. The name suggests inputs only | B01, B04 | `input_manifest_hash` = SHA-256(JCS({object_id, files:[{file_id, sha256, doc_stage, document_code, revision, approval_status}], registry_sha256, reference_selections})), **no model/matrix versions** (they are separate fields per §14.2). Golden test vector in `packages/contracts/vectors` |
| F-28 | minor | **Performance margins.** §11 #3 (500 pages ≤ 10 min ±60 s) measured at ≈ 9.3 min for A4 on the dev box, with A0/A1 rasters riskier. §11 #12–14 (SLA/RTO/RPO) are designed and drilled only | B02, B09 | #3: INT8 recognizer, per-page fan-out, text-layer-first; the benchmark reports the real hardware. #12–14: honest PARTIAL on the НФТ page with the restore-drill timing |
| F-29 | minor | **Priority mismatches on the same ТЗ row.** §11 #8: PLT-89 SHOULD vs EXT-27/ARC-49 MUST. §11 #11: VER-75/ARC-52 SHOULD vs PLT-92 MUST. §12.5/§13.3 retention: MLF-65 NICE, ERR-53 SHOULD vs PLT-35/41 MUST. §11 #7: CMP-83 SHOULD vs EXT-20 MUST | B00, B02, B04, B05, B06, B09, B10 | Apply the normalisation rule TRC-03 (§3.5): any §11–§13 row = MUST in every block that implements it |
| F-30 | minor | **Small letter-of-ТЗ items.** The §1.1 full service name appears nowhere. ELK is an optional profile (ARC-70), so it may be off in the demo. Module 7 says three colours, but B08 adds a neutral grey state | B00, B08, B09 | Show the full name on the login/«О системе» page and in the protocol header. Run the ELK profile in the demo with a reduced heap (32 GB RAM is enough). Keep grey only as «нет результата / в обработке», never as a fourth severity (already B08's rule) |

---

## 1. Scope

This block covers **the whole ТЗ** as an audit surface, not one module:

- **§1** Общие положения (name, purpose, 4 functions, interaction type, pull principle, platform).
- **§2** Нормативная база (13 acts, ГрК articles).
- **§3–§6** Composition of ПД/РД/ИД and the matrix ↔ documentation mapping.
- **§7** 12 modules with priorities (High: 1, 2, 3, 4, 5, 12; Medium: 7, 8, 9, 10, 11; Low: 6).
- **§8** Matrix, Params table (21 fields), examples PZ-01/KR-55/AR-41.
- **§9.1–9.6** Detailed module descriptions:
  - error table (5 rows);
  - upload statuses (9);
  - process statuses (6 × 2 capability columns);
  - parameter statuses (8 × 3 columns);
  - verification statuses (6);
  - AI scenarios (3);
  - retraining requirements (4 bullets);
  - hypothesis approaches (4), Suspicion structure (10 fields);
  - РиН parameters (6 rows) and rules.
- **§10** 16 DB tables with their key fields.
- **§11** 15 performance rows. **§12** 11 security rows. **§13** 8 monitoring rows.
- **§14** GOLD unit, 5 split rules, 6 metrics, reporting rules.
- **Приложение 1**: sheets СХЕМА GOLD (20 fields), МЕТРИКИ (8 rows + matrix-count control), ПРИМЕРЫ РАЗМЕТКИ (9 groups).
- **Перечень ИД** docx: registry (11 fields), 6 source-selection situations, storage rule, Приложение 19.

Related statuses and NFRs: all of them (the matrix below lists each enum value where the ТЗ tabulates it).

---

## 2. Requirements checklist — the traceability matrix

### 2.0 Legend

- **Prio** (for winning): MUST if the ТЗ uses mandatory wording (обязательн…, должен/должны, «только», «запрещ…», «система обязана/осуществляет», «не может»), the row belongs to a High module, or the row is scored in §14. SHOULD for Medium/Low module features without such wording. NICE otherwise.
- **Covering reqs**: block requirement IDs (primary owner first).
- **Eff. MVP**: the consolidated decision I recommend after resolving conflicts (FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE).
- **Status**: OK / PARTIAL / CONFLICT / DOWNGRADED / GAP / DATA, defined in §0. The **F** column gives the finding.

### 2.1 §1 Общие положения

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-001 | §1.1 | Short UI name «Инспектор ИИ» | MUST | ARC-01, UI-01 | FULL | OK | |
| TZ-002 | §1.1 | Full name «Интеллектуальный сервис для автоматической сверки трёх массивов строительной документации: проектной, рабочей и исполнительной» shown (about page, protocol header) | NICE | — | FULL | GAP | F-30 |
| TZ-003 | §1.2 | Automated desk review (камеральная проверка) of ПД, РД, ИД of capital construction objects | MUST | ARC-02 | FULL | OK | |
| TZ-004 | §1.2 b.1 | Detect violations/inconsistencies between ПД, РД and ИД across the 132 controlled params | MUST | MTX-57, CMP-15…31, CMP-91, EXT-18 | SIMPLIFIED | PARTIAL | F-06 |
| TZ-005 | §1.2 b.2 | Inspector verification with the decision and its justification recorded | MUST | VER-15…32, PLT-27 | FULL | OK | |
| TZ-006 | §1.2 b.3 | Programmatic API for exchange with external IS (ИАИС «РиН»): documents and check results | MUST | PLT-01…11, ARC-37 | FULL (vs mock) | OK | |
| TZ-007 | §1.2 b.4 | Automatic control of document presence | MUST | ING-60…71, MTX-29 | FULL | OK | |
| TZ-008 | §1.2 b.4 | Incremental upload until protocol finalization | MUST | ING-72…75, VER-33, UI-36 | FULL | CONFLICT | F-03 |
| TZ-009 | §1.3 | REST over HTTPS | MUST | ARC-03, PLT-68, UI-12 | FULL | OK | |
| TZ-010 | §1.3 | All requests and responses in JSON (multipart upload and binary downloads documented as the only exceptions; errors are problem+json) | MUST | ARC-03, ERR-60, B00 §6 #9, B10 T6 | FULL | OK | |
| TZ-011 | §1.3 | Mandatory OpenAPI 3.0 schema validation of **requests** | MUST | ARC-04, ING-03, EXT-46, CMP-84, VER-70, MLF-58, HYP-35, PLT-101, ERR-62, UI-03, UI-60, PLT-80 | FULL | OK | |
| TZ-012 | §1.3 | Mandatory OpenAPI 3.0 schema validation of **responses** | MUST | ARC-05, PLT-101, UI-03 | FULL (keep ON in demo/prod; ARC-05 says "switchable in prod") | OK | |
| TZ-013 | §1.4 | Asynchronous: after upload the system returns `process_id` | MUST | ARC-06, ING-01, ING-02 | FULL | OK | |
| TZ-014 | §1.4 | Result formed asynchronously and available on request (pull) | MUST | ARC-07, CMP-85, MLF-57, ERR-63 | FULL | OK | |
| TZ-015 | §1.4 | Processing status tracked via a monitoring endpoint (`GET /api/v1/processes/{id}/status`) | MUST | ARC-07, ING-02, EXT-47, UI-04, UI-27 | FULL | OK | |
| TZ-016 | §1.5 | Web app with UI for uploading documents and receiving analysis results | MUST | UI-02, UI-27, UI-34…39 | FULL | OK | |
| TZ-017 | §1.5 | Client on React | MUST | ARC-08, UI-02 | FULL | CONFLICT | F-23 |
| TZ-018 | §1.5 | Server on Node.js | MUST | ARC-09 | FULL | CONFLICT | F-23 |
| TZ-019 | §1.5 | ML modules in Python ≥ 3.11 | MUST | ARC-10, EXT-45, MLF-59 | FULL (3.12) | OK | |
| TZ-020 | §1.5 | Inter-module interaction via REST API | MUST | ARC-11 | FULL | OK | |
| TZ-021 | §1.5 | Inter-module interaction via async RabbitMQ | MUST | ARC-11, ING-82, CMP-86, HYP-35, MLF-57, PLT-100 | FULL | OK (exchange names: B10 X7 → B00 names) | |

### 2.2 §2–§6 Normative base and documentation composition

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-022 | §2 | Development and operation comply with the 13 acts in force as of July 2026 (ГрК, ПП 87, ПП 2078, ПП 2161, 344/пр, ГОСТ Р 21.101-2020, ГОСТ 21.110-2013, 123-ФЗ, 261-ФЗ, 397-ПП, 152-ФЗ, 187-ФЗ, 4802-1) | MUST | MTX-42, MTX-24, PLT-72, PLT-73, PLT-82 | SIMPLIFIED | PARTIAL | F-21 |
| TZ-023 | §2 (ГрК ст. 54) | Inspector powers (e.g. suspension of works) stay with the inspector; the system never issues a предписание or suspension automatically | MUST | CMP-39, VER-42, UI-15, MTX-06 | FULL | OK | |
| TZ-024 | §2 (397-ПП) | РиН integration grounded in 397-ПП (documented in the integration contract) | NICE | PLT-01 (scope), PLT-20 | FULL | OK | |
| TZ-025 | §3 | The 13 ПП 87 sections (ПЗ, СПЗУ, АР, КР, ИОС1–5, ТХ, ПОС, ООС, ППМ, БЭ, ОДИ, СМ, ИН) serve as the ПД completeness template and section dictionary | MUST | ING-62, MTX-48, MTX-50 | FULL | OK | |
| TZ-026 | §3 | ТХ applicability: production objects mandatory; non-production on the customer's request | SHOULD | ING-62, MTX-12 | FULL | OK | |
| TZ-027 | §3 прим. | Linear objects have a different section list (п. 3²) | SHOULD | MTX-59, ING-85 | SIMPLIFIED (N/A with basis) | CONFLICT | F-25 |
| TZ-028 | §3 прим. | Budget-funded objects: sections 6, 11, 5, 9 mandatory in full | MUST | MTX-35 (HR-LOG-017), ING-62 | FULL | OK | |
| TZ-029 | §3 | ИОС subsections: ИОС1 ЭОМ, ИОС2 ВК, ИОС3 ВК (К1/К2), ИОС4 ОВ, ИОС5 СС (АПС, СОУЭ) mapped to disciplines | MUST | ING-57, MTX-37, UI-16 | FULL | OK | |
| TZ-030 | §4 | RD composition (9 components: основные комплекты, рабочие чертежи по маркам, СО по ГОСТ 21.110, ведомости ВО/ВС/ВР, ОД, СМ, ОЛ/ГЧ, РР, прилагаемые документы) as completeness template and doc-kind vocabulary | MUST | ING-63, MTX-36 | SIMPLIFIED (marks from §6 map) | OK | |
| TZ-031 | §5 | ИД composition: 13 items of Приказ 344/пр (Прил. 1) as the ИД completeness checklist | MUST | ING-64, MTX-29 (111-item JSON) | FULL | OK | |
| TZ-032 | §5 | Format per ИД item (paper/electronic) captured | SHOULD | ING-39, ING-64 | FULL | OK | |
| TZ-033 | §5 прим. 1 | Electronic ИД valid without paper duplicate when signed by УКЭП/УНЭП → signature presence recorded | MUST | ING-39, MTX-33, ERR-80, ING-86 (crypto OOS) | SIMPLIFIED (presence, not crypto) | PARTIAL | |
| TZ-034 | §5 прим. 2 | Scanned ИД accepted without e-signature (original kept by the developer) | MUST | ING-39, ERR-12 | FULL | OK | |
| TZ-035 | §5 прим. 2 | «система осуществляет визуальную проверку наличия всех обязательных реквизитов (подписи, печати, даты, регистрационные номера)» | MUST | EXT-41 (SHOULD), MTX-30 (MUST), ING-39 (SHOULD), ERR-80 (SHOULD), CMP-89 (SHOULD) | SIMPLIFIED | DOWNGRADED | F-08 |
| TZ-036 | §5 прим. 3 | Working-drawing set is the main part of ИД; drawings carry stamps «В производство работ» and «Выполнено согласно проекту» → detect and report | MUST | ING-37 (SHOULD), EXT-42 (SHOULD), MTX-31 (MUST), CMP-89 | SIMPLIFIED | DOWNGRADED | F-08 |
| TZ-037 | §5 прим. 4 | Hidden works / structures / network sections subject to inspection come from ПД and are listed in ОД → expected АОСР set | MUST | MTX-32 (MUST SIMPL), ING-88 (NICE OOS), HR-LOG-036 | SIMPLIFIED | CONFLICT | F-09 |
| TZ-038 | §6 | Matrix section ↔ ПД section ↔ РД component ↔ ИД document mapping (12 rows) held as data | MUST | ING-57, MTX-34 | FULL | OK | |
| TZ-039 | §6 | The mapping drives linkage and the incremental impact map | MUST | MTX-45, CMP-72, ING-78 | FULL | OK | |
| TZ-040 | §6 | The matrix covers key control points of all ПД/РД/ИД sections | MUST | MTX-02, MTX-34 | FULL | OK | |

### 2.3 §7 Modules (every row, every function)

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-041 | §7 M1 (High) | Upload ПД, РД, ИД in PDF, DOCX, XML | MUST | ING-01, ING-04, EXT-01, EXT-02, EXT-03 | FULL (XML SIMPLIFIED: no samples) | DATA | F-06 |
| TZ-042 | §7 M1 | Extract data by the 132 params per the Matrix | MUST | EXT-16…18, MTX-09, CMP-91, MTX-52, EXT-19, EXT-21 | SIMPLIFIED | PARTIAL | F-06 |
| TZ-043 | §7 M1 | Document presence control | MUST | ING-60 | FULL | OK | |
| TZ-044 | §7 M1 | Adapt to the load scenario | MUST | CMP-14, MTX-15, HYP-33, ERR-24 | FULL | OK | |
| TZ-045 | §7 M2 (High) | Link current revisions of ПД/РД/ИД | MUST | ING-56, ING-46, CMP-18 | FULL | OK | |
| TZ-046 | §7 M2 | Separate statuses for completeness and findings | MUST | CMP-35, VER-07, UI-41 | FULL | OK | |
| TZ-047 | §7 M2 | Mandatory evidence cards | MUST | CMP-57, VER-06, HYP-25 | FULL | OK | |
| TZ-048 | §7 M3 (High) | Check candidates by evidence cards | MUST | VER-01…14 | FULL | OK | |
| TZ-049 | §7 M3 | Assign CONFIRMED_VIOLATION, NEGATIVE_VERIFIED or CLARIFICATION_REQUIRED | MUST | VER-15, VER-19, VER-25 | FULL | OK | |
| TZ-050 | §7 M3 | Atomic decisions | MUST | VER-30, VER-31, CMP-42, MTX-21 | FULL | OK | |
| TZ-051 | §7 M4 (High) | Versioned GOLD from confirmed positive and negative examples | MUST | MLF-01, MLF-02, MLF-04, MLF-24 | FULL | OK | |
| TZ-052 | §7 M4 | Object-level split | MUST | MLF-09, ARC-35 | FULL | OK | |
| TZ-053 | §7 M4 | Model published only after acceptance | MUST | MLF-11…15, ERR-54 | FULL | OK | |
| TZ-054 | §7 M5 (High) | Form SUSPICION outside the Matrix | MUST | HYP-01, HYP-02 | FULL | OK | |
| TZ-055 | §7 M5 | Not counted as a violation, not in GOLD, until evidence binding and the inspector's decision | MUST | HYP-17…20, CMP-37, VER-56, ARC-36 | FULL | CONFLICT | F-02 |
| TZ-056 | §7 M6 (Low) | Automatic pull of files for checking | SHOULD | PLT-05 (MOCKED), PLT-07, ARC-41 | MOCKED (mock РиН) | PARTIAL | |
| TZ-057 | §7 M6 | Transfer of check results | MUST | PLT-09…16 | FULL (vs mock) | OK | |
| TZ-058 | §7 M7 (Med) | Colour indication of objects: green/yellow/red | MUST | UI-13, UI-14, UI-15 | FULL | OK | F-30 |
| TZ-059 | §7 M7 | Filters by sections | MUST | UI-16 | FULL | OK | |
| TZ-060 | §7 M7 | Filters by statuses | MUST | UI-17 | FULL | OK | |
| TZ-061 | §7 M7 | Filters by dates | MUST | UI-18 | FULL | OK | |
| TZ-062 | §7 M7 | Export protocols to PDF | MUST | UI-19, CMP-46 | FULL | CONFLICT | F-13 |
| TZ-063 | §7 M7 | Export protocols to DOCX | MUST | UI-20 (MUST), CMP-47 (SHOULD) | FULL | CONFLICT | F-13 |
| TZ-064 | §7 M7 | Export protocols to XML | MUST | UI-21 (MUST), CMP-48 (SHOULD) | FULL | CONFLICT | F-13 |
| TZ-065 | §7 M8 (Med) | Admin can **add** normative references | MUST | UI-51, MTX-23 | FULL | OK | |
| TZ-066 | §7 M8 | Admin can **edit** normative references | MUST | UI-52, MTX-23 | FULL | OK | |
| TZ-067 | §7 M8 | Admin can **deactivate** normative references | MUST | UI-53, MTX-23 | FULL | OK | |
| TZ-068 | §7 M8 | Admin updates thresholds `min_value`/`max_value` without recoding | MUST | UI-55, UI-57, MTX-08, CMP-32, ERR-58, ARC-80, ERR-59 | FULL | OK | |
| TZ-069 | §7 M9 (Med) | Record all inspector actions (confirm/reject, reason, time) | MUST | PLT-25…28, VER-60, HYP-38, UI-59, UI-68, MLF-56, PLT-34 | FULL | OK | |
| TZ-070 | §7 M9 | Protocol versioning | MUST | PLT-30…32, CMP-67, CMP-73, VER-59, UI-42, UI-43 | FULL | OK | |
| TZ-071 | §7 M10 (Med) | Automatically generated report for ML engineers | MUST | MLF-47, MLF-51, MLF-52, UI-75 | FULL | OK | |
| TZ-072 | §7 M10 | Report contains rejection statistics | MUST | MLF-48, HYP-43 | FULL | OK | |
| TZ-073 | §7 M10 | Report contains model-tuning recommendations | MUST | MLF-49 | FULL | OK | |
| TZ-074 | §7 M10 | Report is weekly | MUST | MLF-47 | FULL | OK | |
| TZ-075 | §7 M11 (Med) | Collect performance metrics | MUST | PLT-43…49, PLT-57 | FULL | OK | |
| TZ-076 | §7 M11 | Log system events | MUST | PLT-38…42 | FULL | OK | |
| TZ-077 | §7 M11 | Integrate with a centralised monitoring system | MUST | PLT-50…52 | FULL | OK | |
| TZ-078 | §7 M12 (High) | Handle corrupted files | MUST | ERR-02, ERR-06, ING-08…10, EXT-36, ARC-20, ARC-83, ERR-48 | FULL | OK | |
| TZ-079 | §7 M12 | Handle unreadable formats | MUST | ERR-07, ERR-13, ING-05 | FULL | OK | |
| TZ-080 | §7 M12 | Handle exceeded limits | MUST | ERR-03, ERR-04, ERR-08, ING-06, ING-07, ING-14 | FULL | OK | |
| TZ-081 | §7 M12 | Handle integration failures | MUST | ERR-09, ERR-37…41, PLT-19 | FULL | OK | |
| TZ-082 | §7 M12 | Handle incorrect data | MUST | ERR-10, ERR-17, ERR-22, ING-28 | FULL | OK | |

### 2.4 §8 Matrix and table Params

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-083 | §8 | The Matrix is the core; all 132 params from Приложение 1 loaded verbatim | MUST | MTX-02, MTX-49, ARC-T07 | FULL | OK | |
| TZ-084 | §8.1 | `id` INT (PK) | MUST | MTX-01, ARC-13 | FULL | OK | |
| TZ-085 | §8.1 | `code` VARCHAR(20), e.g. KR-55, AR-41 | MUST | MTX-01, MTX-03 | FULL | OK | |
| TZ-086 | §8.1 | `section` VARCHAR(50) ∈ {ПЗ, СПЗУ, АР, КР, ИОС1–5, ППМ, ОДИ, ЗУ, ПОС, ПОД, ООС, СМ} | MUST | MTX-01, MTX-04 | FULL | OK | |
| TZ-087 | §8.1 | `parameter_name` VARCHAR(255) | MUST | MTX-01 | FULL | OK | |
| TZ-088 | §8.1 | `unit` VARCHAR(20) (м², м³, мм, шт., Марка, Класс) | MUST | MTX-01, MTX-19 | FULL | OK | |
| TZ-089 | §8.1 | `source_pd` TEXT | MUST | MTX-01 | FULL | OK | |
| TZ-090 | §8.1 | `source_rd` TEXT | MUST | MTX-01 | FULL | OK | |
| TZ-091 | §8.1 | `source_id` TEXT | MUST | MTX-01 | FULL | OK | |
| TZ-092 | §8.1 | `trigger_logic` TEXT (e.g. «< 0.9 м») | MUST | MTX-01, MTX-18 | FULL | OK | |
| TZ-093 | §8.1 | `review_priority` VARCHAR(20) HIGH/MEDIUM/LOW, «только очередность … не юридическое действие» | MUST | MTX-06, CMP-40, VER-13 | FULL | OK | |
| TZ-094 | §8.1 | `sp_reference` TEXT (absent in the xlsx) | MUST | MTX-07 | SIMPLIFIED (drafted, confidence-badged) | PARTIAL | F-21 |
| TZ-095 | §8.1 | `gost_reference` TEXT (absent in the xlsx) | MUST | MTX-07 | SIMPLIFIED | PARTIAL | F-21 |
| TZ-096 | §8.1 | `fz_reference` TEXT (absent in the xlsx) | MUST | MTX-07 | SIMPLIFIED | PARTIAL | F-21 |
| TZ-097 | §8.1 | `other_normative` TEXT (absent in the xlsx) | MUST | MTX-07 | SIMPLIFIED | PARTIAL | F-21 |
| TZ-098 | §8.1 | `data_type` VARCHAR(20) ∈ {number, string, boolean, coordinate, enum} (absent in the xlsx) | MUST | MTX-05 | FULL | OK | |
| TZ-099 | §8.1 | `min_value` FLOAT (absent in the xlsx) | MUST | MTX-08 | FULL (18 explicit, others via references) | OK | |
| TZ-100 | §8.1 | `max_value` FLOAT (absent in the xlsx) | MUST | MTX-08 | FULL | OK | |
| TZ-101 | §8.1 | `regex_pattern` VARCHAR(255) (absent in the xlsx) | MUST | MTX-09, EXT-16 | FULL (132, ≤ 255 chars, compile-checked) | OK | |
| TZ-102 | §8.1 | `is_active` BOOLEAN (absent in the xlsx) | MUST | MTX-01, UI-56 | FULL | OK | F-24 |
| TZ-103 | §8.1 | `created_at` TIMESTAMP | MUST | MTX-01 | FULL | OK | |
| TZ-104 | §8.1 | `updated_at` TIMESTAMP | MUST | MTX-01 | FULL | OK | |
| TZ-105 | §8.2 | Example codes PZ-01, KR-55, AR-41 supported (= M-001, M-055, M-041; verified against the xlsx) | MUST | MTX-03, UI-66, B00 §6 #7 | FULL | OK | |

### 2.5 §9.1 Upload and parsing

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-106 | §9.1 Назн. | Identify stage, шифр, раздел, редакция and approval status of each document | MUST | ING-34, ING-36, EXT-14 | SIMPLIFIED (registry authoritative, stamp-verified) | OK | |
| TZ-107 | §9.1 Назн. | Build linkages of comparable current documents | MUST | ING-56…59 | FULL | OK | |
| TZ-108 | §9.1 Назн. | Extract values and coordinates of evidence fragments by the 132 params | MUST | EXT-18, EXT-29, EXT-30 | SIMPLIFIED | PARTIAL | F-06 |
| TZ-109 | §9.1 Назн. | Separate completeness control | MUST | ING-60, CMP-52 | FULL | OK | |
| TZ-110 | §9.1 Выход | Output = structured data (table Checks); interpreted as `extracted_values` → `checks` | MUST | B00 §6 #12, CMP-68 | FULL | OK | |
| TZ-111 | §9.1 п.1 | OCR technology chosen by the executor | MUST | EXT-05 | FULL (PP-OCRv5 + Tesseract rus) | CONFLICT | F-23 |
| TZ-112 | §9.1 п.1 | OCR acceptance on a hidden fixed sample of printed text ≥ 300 dpi → an organizer-runnable OCR output mode | MUST | EXT-55, MLF-35, MLF-46, B06-T15 (`inspector-ocr`) | FULL | OK | |
| TZ-113 | §9.1 п.1 | Character Accuracy = 1 − CER ≥ 0,95 | MUST | EXT-06, MLF-35 | FULL | OK | F-05 |
| TZ-114 | §9.1 п.1 | Exact Match ≥ 0,90 for шифр, стадия, редакция, лист/страница, номер помещения/элемента | MUST | EXT-09, MLF-38, ING-38 | FULL | OK | F-05 |
| TZ-115 | §9.1 п.1 | CER with Unicode NFC and repeated-space normalisation; case ignored only where meaningless; signs in шифры/редакции never removed | MUST | EXT-07, MLF-36, ING-38 | FULL | DATA | (organizer answer B02 D6) |
| TZ-116 | §9.1 п.1 | Handwritten and pre-marked illegible zones excluded from the OCR metric | MUST | EXT-10, EXT-11, MLF-37, ERR-11, EXT-52 | FULL | OK | |
| TZ-117 | §9.1 п.1 | «система обязана вернуть LOW_QUALITY или ABSTAIN» for such zones | MUST | EXT-10 (FULL), EXT-11, ERR-11 (SIMPL), ERR-12 | FULL (heuristic detector) | OK | |
| TZ-118 | §9.1 п.1 | Share of such zones and overall coverage reported | MUST | EXT-12, MLF-37 | FULL | OK | |
| TZ-119 | §9.1 п.2 | NLP search by the 132 params using `regex_pattern` | MUST | EXT-16, MTX-09 | FULL | OK | |
| TZ-120 | §9.1 п.2 | NLP search using semantic anchors | MUST | EXT-17, MTX-09 | FULL | OK | |
| TZ-121 | §9.1 п.2 | Sentence-BERT (all-MiniLM-L6-v2) or compatible analogues | MUST | EXT-17, MTX-10, HYP-37 | FULL | CONFLICT | F-14 |
| TZ-122 | §9.1 п.3 | CV for PDF drawings: scaling by the dimension ruler | MUST | EXT-24, MTX-58 | SIMPLIFIED | PARTIAL | F-07 |
| TZ-123 | §9.1 п.3 | CV: line recognition | MUST | EXT-25 | SIMPLIFIED | PARTIAL | F-07 |
| TZ-124 | §9.1 п.3 | CV: distance measurement | MUST | EXT-26 | SIMPLIFIED | PARTIAL | F-07 |
| TZ-125 | §9.1 п.4 | For each extracted value store file_id, SHA-256, stage, шифр, редакция, approval status, sheet/page | MUST | EXT-29, ING-35 | FULL | OK | |
| TZ-126 | §9.1 п.4 | Normalised bbox/polygon in [0;1] of the visible page after CropBox, MediaBox, Rotate | MUST | EXT-30, ARC-18, ING-41, HYP-24, EXT-53 | FULL | OK | |
| TZ-127 | §9.1 п.4 | «обязательно для корректного отображения разметки на повернутых и смещённых листах» (viewer correctness) | MUST | EXT-31, VER-08, UI-44 | FULL | CONFLICT | F-15 |
| TZ-128 | §9.1 п.5 | Parse results cached in Redis by file hash | MUST | ARC-16, ING-80, EXT-33, EXT-34, HYP-36 | FULL | OK | |
| TZ-129 | §9.1 ред. | Mandatory per file: object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, sheet/page, file_hash, predecessor/successor | MUST | ING-35, ING-26, ING-40, ING-45, UI-26 | FULL | OK | |
| TZ-130 | §9.1 ред. | Compare the latest applicable approved revision | MUST | ING-46, ING-52, CMP-18 | FULL | OK | |
| TZ-131 | §9.1 ред. | Revision conflict / missing approval sign / ambiguous link → CLARIFICATION_REQUIRED and no violation conclusion | MUST | ING-49, CMP-19, ERR-14 | FULL | OK | |
| TZ-132 | §9.1 ред. | An outdated revision can never be the reference | MUST | ING-50, CMP-18, VER-27, ERR-15, HYP-28 | FULL | OK | |
| TZ-133 | §9.1 дозагр. | Incremental upload without re-uploading existing files | MUST | ING-72, UI-36, ARC-24 | FULL | OK | |
| TZ-134 | §9.1 дозагр. | Upload possible until protocol finalization | MUST | ING-73, ING-75, ERR-26 | FULL | CONFLICT | F-03 |
| TZ-135 | §9.1 err.1 | Unsupported format → file rejected, naming the supported formats (PDF, DOCX, XML) | MUST | ING-04, ERR-01, UI-34, ARC-20 | FULL | OK | |
| TZ-136 | §9.1 err.2 | Corrupted PDF → file rejected; user notified to re-upload | MUST | ING-08, EXT-36, ERR-02, ERR-73, ING-83, ERR-71 | FULL (repairable-PDF policy: B10 E-D1) | OK | |
| TZ-137 | §9.1 err.3 | File > 50 МБ → rejected, stating the maximum | MUST | ING-06, ERR-03, UI-34, ARC-19 | FULL (MiB; the pilot kit 51,49 MiB is rejected on purpose) | OK | |
| TZ-138 | §9.1 err.4 | Package > 200 МБ → package rejected, stating the exceeded limit | MUST | ING-07, ERR-04, ARC-19 | FULL | OK | |
| TZ-139 | §9.1 err.5 | Processing timeout → up to 2 retries; on failure the administrator is notified | MUST | ING-81, EXT-37, ERR-05, ARC-21, PLT-58, UI-32 | FULL (2 retries = 3 attempts) | OK (delays: B10 X8) | |
| TZ-140 | §9.1 upl. | PD_UPLOADED / PD_PARTIAL / PD_MISSING | MUST | ING-61, ARC-23, UI-29, CMP-50 | FULL | OK | |
| TZ-141 | §9.1 upl. | RD_UPLOADED / RD_PARTIAL / RD_MISSING | MUST | ING-61, ARC-23, UI-29, CMP-50 | FULL | OK | |
| TZ-142 | §9.1 upl. | ID_UPLOADED / ID_PARTIAL / ID_MISSING | MUST | ING-61, ARC-23, UI-29, CMP-50 | FULL | OK | |
| TZ-143 | §9.1 proc. | PENDING: upload yes, verification no | MUST | ARC-22, ING-73, VER-48, UI-28, ERR-28 | FULL | OK | |
| TZ-144 | §9.1 proc. | PARSING: upload no, verification no | MUST | ING-73, ERR-25 | FULL | CONFLICT | F-03 |
| TZ-145 | §9.1 proc. | READY: upload yes, verification yes | MUST | ING-73, VER-48 | FULL | OK | |
| TZ-146 | §9.1 proc. | VERIFYING: upload yes (until finalization), verification yes | MUST | ING-73, VER-48 | FULL | CONFLICT | F-03 |
| TZ-147 | §9.1 proc. | COMPLETED: upload yes, verification no (edits via explicit reopen → VERIFYING) | MUST | VER §3.4, B00 §6 #2, ING-73 | FULL | OK | |
| TZ-148 | §9.1 proc. | FINALIZED (button «Завершить»): upload no, verification no | MUST | VER-43, VER-44, ERR-26, ERR-27 | FULL | OK | |

### 2.6 §9.2 Comparison and preliminary protocol

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-149 | §9.2 Назн. | Evidence group «объект + параметр/правило + актуальные ПД/РД/ИД» is the unit of result, not a page or file | MUST | CMP-01, MTX-22 | FULL | OK | |
| TZ-150 | §9.2 Назн. | Compare values **and geometry** | MUST | CMP-24…31 | SIMPLIFIED (geometry via text-layer label sets + CV) | PARTIAL | F-07 |
| TZ-151 | §9.2 Назн. | Record the preliminary discrepancy and its sources | MUST | CMP-57, CMP-58 | FULL | OK | |
| TZ-152 | §9.2 | Protocol content and layout per Приложение № 2 («являются обязательными») | MUST | CMP-49 | SIMPLIFIED | DATA | F-01 |
| TZ-153 | §9.2 п.1 | Load the Matrix version, the file registry and the revision chains | MUST | CMP-03 | FULL | OK | |
| TZ-154 | §9.2 п.1 | Matrix, dataset and model versions fixed in every run | MUST | CMP-04, ARC-25, EXT-43, HYP-27, MTX-11, UI-58 | FULL | OK | |
| TZ-155 | §9.2 п.1 | … and in the protocol | MUST | CMP-05, UI-22, VER-14 | FULL | OK | |
| TZ-156 | §9.2 п.2 | ПД+РД+ИД → FULL | MUST | CMP-08, ING-69 | FULL | OK | |
| TZ-157 | §9.2 п.2 | ПД+РД → PD_RD_ONLY | MUST | CMP-09, ING-69 | FULL | OK | |
| TZ-158 | §9.2 п.2 | ПД+ИД → PD_ID_ONLY | MUST | CMP-10, ING-69 | FULL | OK | |
| TZ-159 | §9.2 п.2 | РД+ИД → RD_ID_ONLY | MUST | CMP-11, ING-69 | FULL | OK | |
| TZ-160 | §9.2 п.2 | Only one type → SINGLE_ONLY | MUST | CMP-12, ING-69, ERR-24 | FULL | OK | |
| TZ-161 | §9.2 п.2 | Partially loaded (e.g. 5 of 15 ИД files) → PARTIALLY_LOADED | MUST | CMP-13, ING-68, ING-69 | FULL (`scenario_base` kept) | OK | |
| TZ-162 | §9.2 п.3 | For each of the 132 params, order: applicability → evidence completeness → currency and comparability of revisions → only then subject comparison | MUST | CMP-15, MTX-12…14 | FULL | OK | |
| TZ-163 | §9.2 п.3 | Comparable current sources → expected_value, actual_value, delta | MUST | CMP-24, MTX-16 | FULL | OK | |
| TZ-164 | §9.2 п.3 | Preliminary status only CANDIDATE or NEGATIVE_VERIFIED | MUST | CMP-33, MTX-16 | FULL | CONFLICT | F-02, F-19 |
| TZ-165 | §9.2 п.3 | CONFIRMED_VIOLATION only by the inspector, after the evidence check and absent an approved change cancelling the requirement | MUST | CMP-34, VER-16, VER-17, ERR-33, HYP-20 | FULL | OK | |
| TZ-166 | §9.2 п.3 | Pairwise comparison when two stages suffice; an absent inapplicable stage → NOT_APPLICABLE | MUST | CMP-23, MTX-14 | FULL | OK | |
| TZ-167 | §9.2 п.3 | Mandatory source absent → MISSING_EVIDENCE, not in the violation count | MUST | CMP-17, ING-66, ERR-20 | FULL | OK | |
| TZ-168 | §9.2 п.3 | Insufficient evidence / non-comparable sources / undetermined current revision → NOT_COMPARABLE or CLARIFICATION_REQUIRED; data quality, not a violation | MUST | CMP-19, CMP-22, CMP-36, ERR-21, ERR-23, MTX-17, MTX-52 | FULL | OK | |
| TZ-169 | §9.2 п.4 | Structured protocol document: JSON | MUST | CMP-45, ARC-29 | FULL | OK | |
| TZ-170 | §9.2 п.4 | Structured protocol document: PDF | MUST | CMP-46, UI-19, ARC-29 | FULL | CONFLICT | F-13 |
| TZ-171 | §9.2 п.4 | Section «Статус загрузки документов» | MUST | CMP-50, UI-39 | FULL | OK | |
| TZ-172 | §9.2 п.4 | Section «Тип проверки» (load scenario) | MUST | CMP-51, UI-30 | FULL | OK | |
| TZ-173 | §9.2 п.4 | Table (1) completeness and comparability | MUST | CMP-52, ING-70 | FULL | OK | |
| TZ-174 | §9.2 п.4 | Table (2) preliminary candidates | MUST | CMP-53 | FULL | OK | |
| TZ-175 | §9.2 п.4 | Table (3) inspector-confirmed violations | MUST | CMP-54 | FULL | OK | |
| TZ-176 | §9.2 п.4 | Table (4) verified negative results | MUST | CMP-55 | FULL | OK | |
| TZ-177 | §9.2 п.4 | Table (5) free-search hypotheses | MUST | CMP-56, HYP-23, HYP-55 | FULL | OK | |
| TZ-178 | §9.2 п.4 | Evidence card for every candidate: finding_id, param/rule code, expected/actual, file_id + SHA-256 of each source, stage, шифр, редакция, approval status, sheet/page, bbox/polygon, обоснование, risk level, inspector decision and reason | MUST | CMP-57…60, VER-06, HYP-25, CMP-61 | FULL | OK | |
| TZ-179 | §9.2 п.5 | Protocol saved in table Protocols with a version | MUST | CMP-67, PLT-30 | FULL | OK | |
| TZ-180 | §9.2 п.5 | Process status set to READY | MUST | CMP-70 | FULL | OK | |
| TZ-181 | §9.2 п.5 | Inspector notified that the protocol is ready | MUST | ARC-28, CMP-71, UI-31, VER-64, ARC-81 | FULL (in-app + email) | CONFLICT | F-22 |
| TZ-182 | §9.2 инкр. | On re-upload, no full re-run; update only params with new data | MUST | CMP-72, ARC-27, MTX-45, EXT-35, HYP-29 | FULL | OK | |
| TZ-183 | §9.2 инкр. | Previous protocol version kept in history | MUST | CMP-73, PLT-30 | FULL | OK | |
| TZ-184 | §9.2 риск | Risk level (высокий/средний/низкий) only orders expert review; ≠ violation status; not an automatic basis for предписание or suspension | MUST | CMP-39, MTX-20, VER-13, UI-15 | FULL | OK | |
| TZ-185 | §9.2 табл. | NEGATIVE_VERIFIED: not counted; mandatory negative example for FP evaluation; inspector reviews by sample or on dispute | MUST | CMP-41, VER-41, MLF-68 | SIMPLIFIED (10 % sample tab) | OK | |
| TZ-186 | §9.2 табл. | CANDIDATE: not counted; inspector confirms, rejects or requests clarification | MUST | CMP-38, VER-15, VER-19, VER-25 | FULL | OK | |
| TZ-187 | §9.2 табл. | CONFIRMED_VIOLATION: counted; inspector decides further action within his powers | MUST | CMP-38, VER-42 (NICE SIMPL) | SIMPLIFIED (optional «дальнейшее действие» field) | OK | |
| TZ-188 | §9.2 табл. | MISSING_EVIDENCE: not counted; request/re-upload the document | MUST | VER-39, ING-71 | SIMPLIFIED | OK | |
| TZ-189 | §9.2 табл. | NOT_APPLICABLE: not counted; confirm applicability if needed | MUST | VER-40, ING-71 | SIMPLIFIED | OK | |
| TZ-190 | §9.2 табл. | NOT_COMPARABLE: not counted; clarify data composition/quality | MUST | VER-40 | SIMPLIFIED | OK | |
| TZ-191 | §9.2 табл. | CLARIFICATION_REQUIRED: not counted; choose the authoritative revision and record the basis | MUST | VER-26, ING-51 | FULL | OK | |
| TZ-192 | §9.2 табл. | SUSPICION: not counted; first bind evidence, then convert to CANDIDATE if needed | MUST | VER-55, VER-57, HYP-19, HYP-21, UI-81 | FULL | CONFLICT | F-02 |
| TZ-193 | §9.2 табл. | Summary violation count = CONFIRMED_VIOLATION only | MUST | CMP-38, UI-23, HYP-17 | FULL | OK | |

### 2.7 §9.3 Verification by the inspector (mis-titled in the source)

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-194 | §9.3 Назн. | Expert check of the evidence card | MUST | VER-01…14 | FULL | OK | |
| TZ-195 | §9.3 Назн. | Choice of the current revision | MUST | VER-26, VER-27, ING-51 | FULL | OK | |
| TZ-196 | §9.3 Назн. | Confirm or reject a candidate with a coded reason | MUST | VER-15, VER-18…20 | FULL | OK | |
| TZ-197 | §9.3 Назн. | Create a verified negative example | MUST | VER-21, MLF-02 | FULL | OK | |
| TZ-198 | §9.3 Назн. | Finalize the protocol with full traceability of decisions | MUST | VER-43, VER-58, PLT-32 | FULL | OK | |
| TZ-199 | §9.3 стат. | PENDING: candidate awaits the inspector; upload yes | MUST | VER-48 | FULL | OK | |
| TZ-200 | §9.3 стат. | CONFIRMED_VIOLATION: positive GOLD label; upload yes until finalization | MUST | VER-48, VER-53 | FULL | OK | |
| TZ-201 | §9.3 стат. | NEGATIVE_VERIFIED: rejected with a coded reason; negative GOLD label; upload yes until finalization | MUST | VER-48, VER-21 | FULL | OK | |
| TZ-202 | §9.3 стат. | CLARIFICATION_REQUIRED: current revision or additional basis needed; upload yes until finalization | MUST | VER-48, VER-25 | FULL | OK | |
| TZ-203 | §9.3 стат. | VERIFICATION_COMPLETED: all candidates processed; not finalized; upload yes | MUST | VER-48, B00 §6 #1 | FULL (≡ process COMPLETED) | OK | |
| TZ-204 | §9.3 стат. | PROTOCOL_FINALIZED: finalized, decisions fixed; upload no | MUST | VER-43, VER-48 | FULL (≡ process FINALIZED) | OK | |
| TZ-205 | §9.3 п.1 | For each candidate at the same time: expected and actual values; ПД/РД/ИД pages with highlighted areas; шифры and редакции; approval status; link to the approved change | MUST | VER-01…05, VER-09 | FULL | OK | |
| TZ-206 | §9.3 п.1 | Completeness statuses displayed separately from candidates | MUST | VER-07, UI-41 | FULL | OK | |
| TZ-207 | §9.3 п.2 | «Подтвердить нарушение» → CONFIRMED_VIOLATION; decision holds user_id, timestamp, inspector comment | MUST | VER-15, PLT-27, ARC-32, MLF-33 | FULL | OK | |
| TZ-208 | §9.3 п.2 | «Отклонить» → NEGATIVE_VERIFIED; reason_code and comment mandatory (examples: wrong revision, approved change, OCR error, linking error, param not applicable) | MUST | VER-19, VER-20, ERR-31, ARC-32, MLF-33 | FULL | OK (LINKING/BINDING spelling: F-26) | F-26 |
| TZ-209 | §9.3 п.2 | «Требует уточнения» → CLARIFICATION_REQUIRED | MUST | VER-25 | FULL | OK | |
| TZ-210 | §9.3 п.2 | Composite candidate never gets PARTIALLY_CONFIRMED; the inspector splits it into atomic findings, each with its own decision and evidence | MUST | VER-30, CMP-42, ERR-32, MLF-32 | FULL | OK | |
| TZ-211 | §9.3 п.3 | Inspector can upload missing files without resetting verification | MUST | VER-33, ING-74, ERR-35, CMP-74, VER-35 | FULL | CONFLICT | F-03 |
| TZ-212 | §9.3 п.3 | After upload the system runs an incremental check and updates the protocol | MUST | VER-34, CMP-72 | FULL | OK | |
| TZ-213 | §9.3 п.4 | Finalization only after all CANDIDATE are processed or explicitly moved to CLARIFICATION_REQUIRED | MUST | VER-37, ERR-29 | FULL | OK | |
| TZ-214 | §9.3 п.4 | MISSING_EVIDENCE listed separately and never becomes a violation | MUST | VER-38, UI-40 | FULL | OK | |
| TZ-215 | §9.3 п.4 | Only inspector-confirmed records go to РиН, with protocol, Matrix and model versions and the input file registry | MUST | VER-49, PLT-11, CMP-79, ERR-42, ING-33, HYP-31, CMP-62 | FULL | OK | |
| TZ-216 | §9.3 п.5 | After finalization, uploads and status changes are impossible | MUST | VER-44, ERR-27, ARC-30, CMP-76, HYP-30 | FULL (API + DB trigger) | OK | |
| TZ-217 | §9.3 отм. | Un-finalization only by the administrator or an inspector with supervisor rights | MUST | VER-45, PLT-29, ERR-30, UI-45 | FULL | OK | |
| TZ-218 | §9.3 отм. | Every un-finalization recorded in the audit log with a mandatory reason | MUST | VER-46, PLT-29 | FULL | OK | |
| TZ-219 | §9.3 отм. | After un-finalization → VERIFICATION_COMPLETED; uploads possible again | MUST | VER-47, ING-75, ARC-31, CMP-77, MLF-34, PLT-22 | FULL | OK | |
| TZ-220 | §9.3 юз. | Full verification cycle of one protocol (132 params, 14 violations) ≤ 30 min for an experienced user | MUST | VER-65, VER-68, PLT-96 | FULL (УТ-1 benchmark protocol) | OK | |
| TZ-221 | §9.3 юз. | ≤ 3 clicks per violation to complete verification | MUST | VER-66, UI-50, MLF-70 | FULL | OK | |
| TZ-222 | §9.3 юз. | Mandatory usability test on 5 inspectors, then UI rework until the target metrics are met | MUST | VER-69 (MUST SIMPL), UI-86 (SHOULD), ARC-33 (SHOULD) | SIMPLIFIED (proxies unless organizers provide inspectors) | DOWNGRADED | F-04 |

### 2.8 §9.4 Feedback and controlled retraining

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-223 | §9.4 Назн. | Versioned GOLD from expert-confirmed positive and negative examples | MUST | MLF-01 | FULL | OK | |
| TZ-224 | §9.4 Назн. | Analysis of error causes | MUST | MLF-19 | FULL | OK | |
| TZ-225 | §9.4 Назн. | Controlled retraining without automatic model publication | MUST | MLF-20, MLF-11, MLF-14 | SIMPLIFIED (calibrated scorer + data-derived components) | OK | |
| TZ-226 | §9.4 сц.1 | Rejected with coded reason → NEGATIVE_VERIFIED stored as a negative example in the dataset draft; included in a dataset_version only after curator review | MUST | MLF-02, VER-21, UI-72 | FULL | OK | |
| TZ-227 | §9.4 сц.2 | Clarification requested → show sources, coordinates and the revision conflict; not in GOLD | MUST | MLF-03, VER-28 | FULL | OK | |
| TZ-228 | §9.4 сц.3 | Confirmed → positive GOLD candidate; external transfer only after protocol finalization | MUST | MLF-04, VER-53 | FULL | OK | |
| TZ-229 | §9.4 треб. | Release composition determined by coverage of target categories | MUST | MLF-05 | FULL | OK | |
| TZ-230 | §9.4 треб. | Release contains only CONFIRMED_VIOLATION and NEGATIVE_VERIFIED with complete evidence cards | MUST | MLF-06, ERR-55 | FULL | OK | |
| TZ-231 | §9.4 треб. | CANDIDATE, SUSPICION, MISSING_EVIDENCE and unfinished decisions never used for training | MUST | MLF-07, HYP-18 | FULL | OK | |
| TZ-232 | §9.4 треб. | «100 подтверждённых нарушений» alone is not a sufficient quality criterion | SHOULD | MLF-08 | FULL | OK | |
| TZ-233 | §9.4 треб. | Object-level split: all pages, documents and revisions of one object in only one of train/validation/test | MUST | MLF-09, ERR-56 | FULL | OK | |
| TZ-234 | §9.4 треб. | Hidden test and its SHA-256 fixed before the competition; never used for training, threshold tuning or manual tuning | MUST | MLF-10, MLF-31, ERR-57 | FULL | OK | |
| TZ-235 | §9.4 треб. | New model publishable only after passing the §14 acceptance thresholds | MUST | MLF-11, ARC-34, UI-73 | FULL (internal frozen test) | OK | |
| TZ-236 | §9.4 треб. | No Recall drop > 2 pp on any mandatory category | MUST | MLF-12 | FULL | OK | |
| TZ-237 | §9.4 треб. | No FPR rise > 2 pp on verified negative groups | MUST | MLF-13 | FULL | OK | |
| TZ-238 | §9.4 треб. | Publication decision signed by the responsible person | MUST | MLF-14, UI-87 (УКЭП OOS), MLF-74 | SIMPLIFIED (step-up auth + Ed25519 digest) | OK | |
| TZ-239 | §9.4 треб. | Rollback must remain possible | MUST | MLF-15 | FULL | OK | |
| TZ-240 | §9.4 треб. | Per iteration: model_version, dataset_version, matrix_version, set composition and hashes, training code and parameters, all metrics, publication decision, responsible person, link to the previous model | MUST | MLF-16, MLF-23, MLF-25 | FULL | OK | |
| TZ-241 | §9.4 прим. | System comment when agreeing with a rejection («Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR. Запись включена в черновик…») | MUST | MLF-17, VER-22, UI-76 | FULL | OK | |
| TZ-242 | §9.4 прим. | System comment on a disputed rejection («Статус: CLARIFICATION_REQUIRED. Показаны точные страницы…»); not in GOLD, not sent externally until the inspector re-decides | MUST | MLF-18, VER-23 | FULL | OK | |

### 2.9 §9.5 Free hypothesis search

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-243 | §9.5 Назн. | Automatic hypotheses about discrepancies outside the Matrix, status SUSPICION; not a violation until an evidence card exists and the inspector decides | MUST | HYP-01, HYP-02 | FULL | OK | |
| TZ-244 | §9.5 #1 | Logical analysis «Если A, то должно быть B» (e.g. floors > 10 → lift) | MUST | HYP-03, MTX-25 | FULL | OK | |
| TZ-245 | §9.5 #2 | Semantic dissonance of ПД vs РД terminology («Техническое» vs «Склад ГСМ») | MUST | HYP-05, MTX-27 | FULL | OK | |
| TZ-246 | §9.5 #3 | Normative analysis vs СП/ГОСТ/СанПиН (e.g. 2.4 m vs 2.5 m) | MUST | HYP-06, HYP-07, MTX-26 | SIMPLIFIED (facts limited to reliably extracted values) | PARTIAL | |
| TZ-247 | §9.5 #4 | ML pattern analysis trained on historical data for anomalies (e.g. concrete −20 % vs average) | MUST | HYP-08 (SIMPL), HYP-56 (SHOULD MOCKED), MTX-28 (SHOULD) | SIMPLIFIED | DOWNGRADED | F-20 |
| TZ-248 | §9.5 стр. | Suspicion fields: suspicion_id, discovery_method, confidence, description, pd_reference, rd_reference, review_priority, normative_base, finding_status = SUSPICION, inspector_status = PENDING | MUST | HYP-09…15, MTX-46 | FULL | CONFLICT | F-26 |
| TZ-249 | §9.5 дедуп. | Hypotheses merged only within one object and comparable revisions | MUST | HYP-16 | FULL | OK | |
| TZ-250 | §9.5 | SUSPICION not a violation, not in the summary count, not a positive training label | MUST | HYP-17, HYP-18, CMP-37, UI-23, MLF-67, UI-47, HYP-46 | FULL | OK | |
| TZ-251 | §9.5 | Conversion to CANDIDATE requires concrete sources and evidence coordinates | MUST | HYP-19, VER-55, ERR-36 | FULL | CONFLICT | F-02 |
| TZ-252 | §9.5 | CONFIRMED_VIOLATION requires the inspector's decision | MUST | HYP-20 | FULL | OK | |

### 2.10 §9.6 Integration with ИАИС «РиН»

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-253 | §9.6 табл. | External system = ИАИС «РиН» | MUST | PLT-01, PLT-20 | FULL (mock with own OpenAPI) | OK | |
| TZ-254 | §9.6 табл. | Interaction type: REST over HTTPS (JSON) | MUST | PLT-02 | FULL | OK | |
| TZ-255 | §9.6 табл. | Interaction type: automatic file pull | SHOULD | PLT-05, PLT-07, ARC-41 | MOCKED (connector real, source mocked) | PARTIAL | |
| TZ-256 | §9.6 табл. | Principle: asynchronous pull of results | MUST | PLT-03 (`GET /api/v1/inspection/{process_id}`) | FULL | OK | |
| TZ-257 | §9.6 табл. | Basis 397-ПП; operator ДИТ; coordinator Мосгосстройнадзор (documented) | NICE | PLT scope, PLT-23 | FULL (docs) | OK | |
| TZ-258 | §9.6 сц.1 | Upload via the interface: `POST /api/v1/documents/upload` → `process_id` | MUST | ING-01, PLT-04 | FULL | OK | |
| TZ-259 | §9.6 | Result transfer endpoint `POST /api/v1/inspection/{process_id}` | MUST | PLT-09 | FULL | OK | |
| TZ-260 | §9.6 | Transfer only when the protocol is PROTOCOL_FINALIZED | MUST | PLT-10, ERR-37, VER-50 | FULL | OK | |
| TZ-261 | §9.6 | Authentication by client certificates (УКЭП) | MUST | PLT-12 (MUST), ARC-38 (SHOULD), ERR-43 (NICE MOCKED) | SIMPLIFIED (mTLS dev CA) | CONFLICT | F-12 |
| TZ-262 | §9.6 | 5xx or timeouts → up to 3 retries with exponential delays 1, 5, 15 min | MUST | PLT-14, ERR-38, ARC-40 | FULL (`DEMO_TIME_SCALE` in the demo) | OK | |
| TZ-263 | §9.6 | РиН unavailable → protocol stays PROTOCOL_FINALIZED, sync = PENDING_SYNC; resending continues with journaling | MUST | PLT-15, PLT-16, ERR-39, UI-46 | FULL | OK (SyncStatus enum: F-26) | F-26 |
| TZ-264 | §9.6 | External transfer failure never cancels or changes the signed inspector decision | MUST | PLT-15, VER-50 | FULL | OK | |
| TZ-265 | §9.6 | Prescription statuses ISSUED, IN_PROGRESS, COMPLETED, CANCELLED, EXTENDED | SHOULD | PLT-17 (MOCKED), ARC-42 | MOCKED (mirror from the mock) | PARTIAL | |
| TZ-266 | §9.6 блок. | Auto-pull into a finalized protocol does not start a check; it only notifies the inspector and offers a new check | MUST | PLT-08, ERR-40, ING-76, ING-77, CMP-78, VER-51, UI-33 | FULL | OK | |

### 2.11 §10 Database tables (16) and their key fields

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-267 | §10 #1 | Params: id, code, parameter_name, source_pd, source_rd, source_id, sp_reference, gost_reference, fz_reference | MUST | MTX-01, ARC-13, ARC-14, UI-56 | FULL | CONFLICT | F-17 |
| TZ-268 | §10 #2 | Checks: id, param_id, object_id, expected_value, actual_value, completeness_status, finding_status, review_priority, evidence_group_id | MUST | CMP-68, ARC-14 | FULL | OK | |
| TZ-269 | §10 #3 | Objects: id, name, address, customer, contractor, permit_number | MUST | ARC-14, UI-25, B01 §3.3 (no ING ID) | FULL | OK | |
| TZ-270 | §10 #4 | Files: id, object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, predecessor_id, file_hash, file_path, uploaded_at | MUST | ING-35, ING-15, ING-16, ARC-14 | FULL | OK | |
| TZ-271 | §10 #5 | Protocols: id, object_id, version, matrix_version, dataset_version, model_version, input_manifest_hash, status, created_at, finalized_at | MUST | CMP-67, PLT-30, ARC-26 | FULL | CONFLICT | F-27 |
| TZ-272 | §10 #6 | Rejection_Log: id, violation_id, rejection_reason, ai_verdict, suggested_fix, retraining_status | MUST | VER-24, MLF-21 | FULL | CONFLICT | F-17 |
| TZ-273 | §10 #7 | Dispute_Log: id, violation_id, inspector_comment, ai_comment, resolution_status, resolved_by | MUST | VER-23, MLF-22 | FULL | CONFLICT | F-17 |
| TZ-274 | §10 #8 | Suspicions: id, object_id, discovery_method, confidence, description, inspector_status | MUST | HYP-22 | FULL | OK | |
| TZ-275 | §10 #9 | Logical_Rules: id, rule_name, condition, expected, normative_base, is_active | MUST | HYP-04, MTX-25, UI-64, HYP-40 | FULL | CONFLICT | F-18 |
| TZ-276 | §10 #10 | Normative_Base: id, document_name, document_number, section, parameter_name, min_value, max_value, effective_from, effective_to | MUST | MTX-24, UI-51…54, HYP-07 | FULL | OK (owner: F-17) | F-17 |
| TZ-277 | §10 #11 | ML_Retraining_Log: id, model_version, dataset_version, split_hashes, precision, recall, f1, false_positive_rate, per_category_metrics, approval_status, approved_by | MUST | MLF-23 | FULL | OK | |
| TZ-278 | §10 #12 | Audit_Log: id, user_id, action, object_id, details, timestamp, ip_address, user_agent | MUST | PLT-26 | FULL | OK | |
| TZ-279 | §10 #13 | Monitoring_Metrics: id, metric_name, value, timestamp, service_name, tags | MUST | PLT-57 | FULL | OK | |
| TZ-280 | §10 #14 | Evidence_Fragments: id, evidence_group_id, file_id, stage, sheet_page, bbox_polygon_norm, extracted_value, role_expected_actual | MUST | CMP-69 | FULL | CONFLICT | F-17 |
| TZ-281 | §10 #15 | Dataset_Items: id, evidence_group_id, gold_label, expert_id, reason_code, dataset_version, split, object_group_id | MUST | MLF-24 | FULL | OK | |
| TZ-282 | §10 #16 | Model_Versions: model_version, artifact_hash, dataset_version, metrics_json, approval_status, approved_by, deployed_at, rollback_to | MUST | MLF-25 | FULL | OK | |

### 2.12 §11 Performance (all 15 rows)

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-283 | §11 #1 | Upload up to 10 files × 50 МБ ≤ 2 min (±30 s) | MUST | PLT-83, ARC-43, ING-84 | FULL (3 packages ≤ 200 МБ; B01 C1) | OK | |
| TZ-284 | §11 #2 | OCR of a PDF up to 100 pages ≤ 3 min (±30 s) | MUST | PLT-84, EXT-39, ARC-44 | FULL (≈ 112 s measured, A4) | OK | |
| TZ-285 | §11 #3 | OCR of a PDF up to 500 pages ≤ 10 min (±60 s) | MUST | PLT-85, EXT-40 | FULL (≈ 9.3 min measured; thin margin) | PARTIAL | F-28 |
| TZ-286 | §11 #4 | Comparison of 132 params (fully loaded documents) ≤ 2 min (±30 s) | MUST | PLT-86, CMP-80, MTX-44, ARC-45 | FULL | OK | |
| TZ-287 | §11 #5 | Protocol generation (JSON/PDF) ≤ 30 s (±10 s) | MUST | PLT-87, CMP-81, ARC-46 | FULL | OK | |
| TZ-288 | §11 #6 | Sending to РиН ≤ 30 s (±10 s) | MUST | PLT-18, ARC-47 | FULL (vs mock) | OK | |
| TZ-289 | §11 #7 | ML analysis of one parameter (NLP) ≤ 500 ms (±100 ms) | MUST | PLT-88, EXT-20, MLF-61, MTX-44, CMP-83 (SHOULD), ARC-48, HYP-34 | FULL | CONFLICT | F-29 |
| TZ-290 | §11 #8 | CV analysis of one drawing («DWG») ≤ 30 s (±10 s) | MUST | EXT-27 (MUST FULL), ARC-49, PLT-89 (SHOULD SIMPL), EXT-57 (DWG OOS) | FULL (per PDF sheet) | CONFLICT | F-29 |
| TZ-291 | §11 #9 | Incremental protocol update ≤ 1 min (±15 s) | MUST | PLT-90, CMP-82, VER-36, ARC-50, ING-78 | FULL | OK | |
| TZ-292 | §11 #10 | API response time p95 ≤ 200 ms (±50 ms) | MUST | PLT-91, ARC-51, ERR-69, MLF-73, VER-71 | FULL | OK | |
| TZ-293 | §11 #11 | ≥ 100 concurrent inspectors | MUST | PLT-92 (MUST), ARC-52 (SHOULD), VER-75 (SHOULD SIMPL), UI-49 | FULL (k6 100 VUs) | CONFLICT | F-29 |
| TZ-294 | §11 #12 | Availability SLA 99.9 % 24/7 | SHOULD | PLT-93, ARC-53 | SIMPLIFIED (design + blackbox uptime) | PARTIAL | F-28 |
| TZ-295 | §11 #13 | RTO ≤ 1 h | SHOULD | PLT-94, ERR-70 | SIMPLIFIED (timed restore drill) | PARTIAL | F-28 |
| TZ-296 | §11 #14 | RPO ≤ 15 min | SHOULD | PLT-95, ING-24 | SIMPLIFIED (WAL archiving + PITR drill) | PARTIAL | F-28 |
| TZ-297 | §11 #15 | Full verification cycle ≤ 30 min (±10 min) for an experienced user | MUST | PLT-96, VER-65 | FULL | OK | |

### 2.13 §12 Security (all 11 rows)

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-298 | §12 #1 | Login/password authentication for all user categories | MUST | PLT-61…63, ARC-54, UI-05, ERR-44 | FULL | OK | |
| TZ-299 | §12 #2 | RBAC: inspector (view/verify), administrator (params and normative base), ML engineer (logs and retraining data) | MUST | PLT-64…66, VER-61, UI-06, MLF-55, HYP-39, ARC-55, ING-21, ERR-45 | FULL | OK | |
| TZ-300 | §12 #3 | Encryption at rest: database | MUST | PLT-71, ARC-56, ING-18 | SIMPLIFIED → make demonstrable | PARTIAL | F-10 |
| TZ-301 | §12 #3 | Encryption at rest: file storage | MUST | PLT-70, ING-18 | FULL (AES-256-GCM envelope) | OK | |
| TZ-302 | §12 #3 | Encryption in transit, TLS 1.3 | MUST | PLT-68 (edge FULL), PLT-69 (internal SIMPL), ARC-57, ERR-50, ING-23 | SIMPLIFIED (internal TLS in the prod-like profile) | PARTIAL | |
| TZ-303 | §12 #4 | Every user action recorded with time, IP address, action type and object id | MUST | PLT-25, ARC-58, UI-07, VER-60, ING-20, PLT-36 | FULL | OK | |
| TZ-304 | §12 #5 | Log retention ≥ 90 days (routine), ≥ 1 year (security events) | MUST | PLT-35 (MUST), ARC-59, ERR-53 (SHOULD), MLF-65 (NICE) | SIMPLIFIED (configured, not provable in time) | CONFLICT | F-29 |
| TZ-305 | §12 #6 | Personal data (inspector ФИО, developer contacts) processed per 152-ФЗ | MUST | PLT-72, PLT-42, UI-83, MLF-64, VER-73, ING-22, ARC-60, EXT-50, HYP-45 | SIMPLIFIED (technical FULL, organisational templates) | OK | |
| TZ-306 | §12 #7 | 187-ФЗ integrity requirements (not a КИИ object) | MUST | PLT-73, PLT-33, ARC-61, MLF-63 | FULL | OK | |
| TZ-307 | §12 #8 | Daily backups of DB and file storage; 30-day retention | MUST | PLT-74, PLT-75, ARC-62 | FULL | OK | |
| TZ-308 | §12 #9 | Intrusion detection system (IDS) | MUST | PLT-76 (MUST SIMPL), ERR-49, ARC-64 (NICE OOS), ERR-83 (OOS) | SIMPLIFIED (IDS-lite + optional CrowdSec/Suricata profile) | CONFLICT | F-11 |
| TZ-309 | §12 #9 | DDoS protection | MUST | PLT-77, ARC-63, ERR-08 | SIMPLIFIED (rate/conn limits; perimeter documented) | PARTIAL | F-11 |
| TZ-310 | §12 #10 | All requests to external systems signed with УКЭП | MUST | PLT-13 (MUST SIMPL), ARC-39 (SHOULD MOCKED), ERR-43 (NICE MOCKED), VER-52 | SIMPLIFIED (soft-GOST signer) | CONFLICT | F-12 |
| TZ-311 | §12 #11 | Every uploaded file scanned by antivirus before it is stored | MUST | PLT-78, ING-12, ERR-46, ARC-65 | FULL (ClamAV, fail-closed) | OK | |

### 2.14 §13 Monitoring and logging (all 8 rows, metric list atomised)

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-312 | §13 #1 | Structured JSON logs with mandatory timestamp, level, service, message, request_id, user_id | MUST | PLT-38, PLT-39, ARC-66, EXT-48, ERR-64, ING-89 | FULL | OK | |
| TZ-313 | §13 #2 | Levels: INFO for routine operations, ERROR for failures, WARNING for non-critical problems, DEBUG only in the test contour | MUST | PLT-40, ARC-67 | FULL | OK | |
| TZ-314 | §13 #3 | Log retention 90 days for INFO+; 1 year for security-related ERROR/WARNING | MUST | PLT-41 | SIMPLIFIED (ILM policies) | OK | |
| TZ-315 | §13 #4 | Metric: CPU and RAM per service | MUST | PLT-43, ARC-68 | FULL | OK | |
| TZ-316 | §13 #4 | Metric: disk usage | MUST | PLT-44 | FULL | OK | |
| TZ-317 | §13 #4 | Metric: requests per second | MUST | PLT-45 | FULL | OK | |
| TZ-318 | §13 #4 | Metric: average response time | MUST | PLT-46 | FULL | OK | |
| TZ-319 | §13 #4 | Metric: HTTP 5xx count | MUST | PLT-47, ERR-65 | FULL | OK | |
| TZ-320 | §13 #4 | Metric: RabbitMQ queue size | MUST | PLT-48 | FULL | OK | |
| TZ-321 | §13 #4 | Metric: active user sessions | MUST | PLT-49 | FULL | OK | |
| TZ-322 | §13 #5 | Prometheus integration (metrics collection) | MUST | PLT-50, ARC-69 | FULL | OK | |
| TZ-323 | §13 #5 | Grafana integration (dashboards) | MUST | PLT-51, ARC-69 | FULL | OK | |
| TZ-324 | §13 #6 | ELK (Elasticsearch, Logstash, Kibana) for centralised log storage and search | MUST | PLT-52, ARC-70 | FULL (run the profile in the demo) | OK | F-30 |
| TZ-325 | §13 #7 | Alerts on metric thresholds (e.g. CPU > 80 %, response time > 500 ms) | MUST | PLT-53, ARC-71 | FULL | OK | |
| TZ-326 | §13 #7 | Alerts sent to the administrator by email | MUST | PLT-54, ERR-66 | FULL (Mailpit in the demo) | OK | |
| TZ-327 | §13 #7 | Alerts sent to Telegram | MUST | PLT-55, ERR-66 | FULL (real bot if a token is supplied; else mock) | DATA | (D-U8) |
| TZ-328 | §13 #8 | Daily checksum verification of stored files (corruption or unauthorised change) | MUST | PLT-56, ING-19, ERR-52, ARC-72 | FULL | OK | |

### 2.15 §14 Quality acceptance and GOLD

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-329 | §14.1 | Label unit = evidence_group: one object, one param or atomic rule, comparable current ПД/РД/ИД revisions, fragments with coordinates | MUST | MLF-26, CMP-01, MTX-21 | FULL | OK | |
| TZ-330 | §14.1 | Positive GOLD label only for CONFIRMED_VIOLATION; negative only for NEGATIVE_VERIFIED | MUST | MLF-06, ARC-36, B00 `dataset_items` CHECK | FULL | OK | |
| TZ-331 | §14.1 | Each label stores the expert decision, reason, date and source versions | MUST | MLF-26, VER-54 | FULL | OK | |
| TZ-332 | §14.1 | The pilot (9 objects) defines the card format and scenarios, not a quantitative acceptance set | MUST | MLF-28 | FULL | OK | |
| TZ-333 | §14.2 | Object isolation: train/validation/hidden test split by object_id | MUST | MLF-09 | FULL | OK | |
| TZ-334 | §14.2 | Test fixation: hidden-test composition and SHA-256 of inputs/markup fixed by the organizer → the system verifies the organizer manifest | MUST | MLF-46, ING-13, ING-90 | FULL | OK | |
| TZ-335 | §14.2 | Class composition: confirmed violations, verified negatives, missing evidence, non-applicable params and revision conflicts → each must be emitted correctly | MUST | CMP-90, MTX-38, MLF-30 | FULL | OK | |
| TZ-336 | §14.2 | No leakage: no hidden-test GOLD labels; no threshold selection on the hidden test | MUST | MLF-31, ERR-57 | FULL | OK | |
| TZ-337 | §14.2 | Versioning: each result carries dataset_version, matrix_version, model_version, input_manifest_hash | MUST | CMP-06, MLF-29, ARC-25, UI-22 | FULL | CONFLICT | F-27 |
| TZ-338 | §14.3 | OCR: Character Accuracy = 1 − ΣLevenshtein/Σchars ≥ 0,95; CER, WER and coverage published separately | MUST | EXT-06, EXT-08, MLF-35, ARC-73 | FULL | OK | F-05 |
| TZ-339 | §14.3 | Key fields: Exact Match ≥ 0,90 after the set normalisation | MUST | EXT-09, MLF-38 | FULL | OK | F-05 |
| TZ-340 | §14.3 | Document linkage: share of evidence_groups with exact object_id, stage, шифр and current revision ≥ 0,95 | MUST | MLF-39, ING-46, ING-56 | FULL | OK | F-05 |
| TZ-341 | §14.3 | Evidence localization: exact file_id and page; bbox/polygon correct at IoU ≥ 0,50 after page normalisation; ≥ 0,95 of groups with complete evidence | MUST | EXT-56, MLF-40, CMP-58 | FULL | OK | F-05 |
| TZ-342 | §14.3 | Violation detection: P ≥ 0,90, R ≥ 0,80, F1 ≥ 0,85 by evidence_group; a match needs the right param/discrepancy type and correct evidence | MUST | MLF-41, CMP-44, CMP-02 | FULL (harness) | PARTIAL | F-05 |
| TZ-343 | §14.3 | False Positive Rate ≤ 0,10 on NEGATIVE_VERIFIED and on outdated-revision cases | MUST | MLF-42, MTX-40, CMP-44 | FULL | OK | F-05 |
| TZ-344 | §14.3 | Metrics computed per object and separately by section and violation type | MUST | MLF-43, MTX-39, CMP-66 | FULL | OK | |
| TZ-345 | §14.3 | Publish sample size, coverage/abstention and 95 % CI with every point estimate | MUST | MLF-44, EXT-13 | FULL | OK | |
| TZ-346 | §14.3 | Not accepted if any mandatory threshold fails, even when overall F1 passes | MUST | MLF-45 | FULL | OK | |

### 2.16 Приложение 1 sheets: СХЕМА GOLD, МЕТРИКИ, ПРИМЕРЫ РАЗМЕТКИ

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-347 | GOLD | `evidence_group_id` (object + atomic param/rule + current sources and evidence) | MUST | CMP-02, MLF-27 | FULL | OK | |
| TZ-348 | GOLD | `finding_id`: stable id of the atomic finding | MUST | CMP-02 | FULL | OK | |
| TZ-349 | GOLD | `object_id`: group for the object-level split | MUST | CMP-65, MLF-24 | FULL | OK | |
| TZ-350 | GOLD | `matrix_code / rule_version`: M-001…M-132 or a free-search rule version | MUST | CMP-65, HYP-26 | FULL | OK | |
| TZ-351 | GOLD | `expected_value` (string/number/geometry) | MUST | CMP-24, CMP-31 | FULL (geometry as JSON) | OK | |
| TZ-352 | GOLD | `actual_value` (string/number/geometry) | MUST | CMP-24, CMP-31 | FULL | OK | |
| TZ-353 | GOLD | `source_expected_file_id / sha256` | MUST | CMP-57 | FULL | OK | |
| TZ-354 | GOLD | `source_expected_stage/code/revision/approval` | MUST | CMP-57 | FULL | OK | |
| TZ-355 | GOLD | `source_expected_page / bbox_polygon` [0;1] | MUST | CMP-58, CMP-59 | FULL (multi-box list; B04 #8, B02 C12) | OK | |
| TZ-356 | GOLD | `source_actual_file_id / sha256` | MUST | CMP-57 | FULL | OK | |
| TZ-357 | GOLD | `source_actual_stage/code/revision/approval` | MUST | CMP-57 | FULL | OK | |
| TZ-358 | GOLD | `source_actual_page / bbox_polygon` [0;1] | MUST | CMP-58, CMP-59 | FULL | OK | |
| TZ-359 | GOLD | `approved_change_ref` (string or NONE) | MUST | CMP-43 (SIMPL), VER-05, VER-17, MTX-43 | SIMPLIFIED (registry doc type + hint; inspector sets the final value) | OK | |
| TZ-360 | GOLD | `completeness_status` ∈ {COMPLETE, MISSING_EVIDENCE, NOT_APPLICABLE, NOT_COMPARABLE, CLARIFICATION_REQUIRED} | MUST | CMP-35, ING §1.3 | FULL | OK | |
| TZ-361 | GOLD | `finding_status` ∈ {NEGATIVE_VERIFIED, CANDIDATE, CONFIRMED_VIOLATION, SUSPICION} | MUST | CMP-35 | FULL | OK | |
| TZ-362 | GOLD | `review_priority` HIGH/MEDIUM/LOW, only the review order | MUST | CMP-40 | FULL | OK | |
| TZ-363 | GOLD | `expert_id / timestamp` (for GOLD) | MUST | VER-54, MLF-24 | FULL | OK | |
| TZ-364 | GOLD | `expert_reason_code / comment` for confirmation **and** rejection | MUST | VER-18, VER-19 | FULL | OK | |
| TZ-365 | GOLD | `dataset_version / matrix_version / model_version` | MUST | CMP-06 | FULL | OK | |
| TZ-366 | GOLD | `split` TRAIN/VALIDATION/HIDDEN_TEST assigned by object_id (for release) | MUST | MLF-09, MLF-24 | FULL | OK | |
| TZ-367 | GOLD | CANDIDATE and SUSPICION are not positive GOLD labels | MUST | MLF-07, HYP-18 | FULL | OK | |
| TZ-368 | GOLD | GOLD import/export strictly in this schema (for the organizers' scoring) | MUST | MLF-27, CMP-65, ARC-74 | FULL | OK | |
| TZ-369 | МЕТРИКИ | «Без полного доказательства finding не засчитывается» → no candidate without a complete card | MUST | CMP-57 (card validator), MLF-41 | FULL | OK | |
| TZ-370 | МЕТРИКИ | Revision-conflict cases are part of the hidden test (linkage metric) | MUST | ING-49, CMP-90 | FULL | OK | |
| TZ-371 | МЕТРИКИ | Regression gate: signed decision required; automatic publication forbidden | MUST | MLF-12…14, ERR-54 | FULL | OK | |
| TZ-372 | МЕТРИКИ | Matrix version control: «Число параметров 132 — Ожидается 132» | SHOULD | — (MTX-02, MTX-47 partially) | FULL (publish-time invariant) | GAP | F-24 |
| TZ-373 | ПРИМЕРЫ | The 9 pilot evidence groups (1 CONFIRMED_VIOLATION, 7 CANDIDATE, 1 NEGATIVE_VERIFIED) reproducible as regression fixtures, with bboxes | MUST | VER-74, MTX-53…55, EXT-56 (27/27 boxes IoU ≥ 0.997), B03 MTX-T17 | FULL | OK | |
| TZ-374 | ПРИМЕРЫ | Export in the notation «PD:ALT79B-000015:стр.19:bbox [0.7800,0.1000,0.9100,0.3500]» | SHOULD | CMP-65 | FULL | OK | |
| TZ-375 | ПРИМЕРЫ | Out-of-matrix pilot groups (IZM12 pile repair, LOS3A moved door) produce CANDIDATE-level findings with evidence | MUST | MTX-60, B03 D-08, HYP D1/D2 | FULL | CONFLICT | F-02 |
| TZ-376 | ПРИМЕРЫ | Organizer file ids (e.g. ALT79B-000015) kept and echoed exactly | MUST | ING-26, B01 §0 #2 | FULL | OK | |

### 2.17 Перечень ИД: mandatory registry, source-selection rules, Приложение 19

| ID | ТЗ ref | Requirement (atomic) | Prio | Covering reqs | Eff. MVP | Status | F |
|---|---|---|---|---|---|---|---|
| TZ-377 | Реестр | Every uploaded set comes with a separate machine-readable registry (CSV/XLSX/JSON) | MUST | ING-25, UI-35, PLT-06 | FULL | OK | |
| TZ-378 | Реестр | Without a registry the package is accepted with status CLARIFICATION_REQUIRED | MUST | ING-27, CMP-21, ERR-16, VER-29 | FULL | OK | |
| TZ-379 | Реестр | Registry fields: object_id; file_id/file_name/SHA-256; doc_stage PD/RD/ID; discipline; document_code (no free abbreviation); revision; approval_status DRAFT/APPROVED/FOR_CONSTRUCTION/SUPERSEDED/CANCELLED; approval_date; sheet_page_range with sheet ↔ PDF page map; predecessor_id/successor_id; signature_status | MUST | ING-26, ING-28, ING-39, ING-40 | FULL | OK | |
| TZ-380 | Правила | Store the original file, its hash and its revision chain | MUST | ING-15, ARC-17 | FULL | OK | |
| TZ-381 | Правила | Overwriting a file under the same file_id is forbidden | MUST | ING-16, ERR-18 | FULL | OK | |
| TZ-382 | Правила | Re-upload creates a new record and a new protocol version | MUST | ING-17, CMP-75, ERR-19 | FULL (byte-identical re-upload idempotent: B01 D5) | OK | |
| TZ-383 | Сит. 1 | One applicable approved revision → use it; record file_id and SHA-256 | MUST | ING-47 | FULL | OK | |
| TZ-384 | Сит. 2 | A new revision explicitly replaces the old → keep the old for audit, exclude it from the reference comparison | MUST | ING-48, CMP-20 | FULL | OK | |
| TZ-385 | Сит. 3 | Several revisions with no unambiguous status → CLARIFICATION_REQUIRED; violation conclusion blocked until the inspector decides | MUST | ING-49, VER-26 | FULL | OK | |
| TZ-386 | Сит. 4 | Mandatory document missing → MISSING_EVIDENCE, shown in completeness, not counted as a violation | MUST | ING-66 | FULL | OK | |
| TZ-387 | Сит. 5 | Document not applicable to the object/work type → NOT_APPLICABLE with a mandatory basis | MUST | ING-65, CMP-16, MTX-12 | FULL | OK | |
| TZ-388 | Сит. 6 | File unreadable or sheets not matched → NOT_COMPARABLE; request replacement/clarification | MUST | ING-67, ERR-13, EXT-38 | FULL | OK | |
| TZ-389 | Прил. 19 | «Примерный перечень исполнительной документации» used as the expected ИД list (incl. «по окончании строительства» items) | MUST | ING-64, MTX-29 | SIMPLIFIED (CORE vs EXPECTED items) | GAP | TRC-T06 |

Note on TZ-389: block requirements cover it. It is marked GAP because Приложение 19 exists only as scans, and no one has yet checked the 111-item transcription (`id_completeness_checklist.json`) against `img_perechen/image1–4.png`. An unchecked transcription of a scan is not evidence. It becomes OK once a human spot-check is done (task TRC-T06).

### 2.18 Requirements on the traceability function itself (TRC)

| ID | Requirement | Ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| TRC-01 | Every TZ-NNN row maps to ≥ 1 block requirement; zero unmapped rows at CP0 exit | task | MUST | FULL | This matrix; 3 gaps closed by F-24, F-30 and TRC-T06 |
| TRC-02 | Every MUST TZ row has ≥ 1 automated test or scripted demo step tagged `@tz TZ-NNN`; CI fails otherwise | §14 spirit; win | MUST | FULL | Turns claims into evidence |
| TRC-03 | Priority normalisation: mandatory ТЗ wording or a High-module row ⇒ MUST in every block implementing it | §7 priorities | MUST | FULL | Removes F-08, F-11, F-12, F-20, F-29 |
| TRC-04 | Exactly one semantic owner per TZ row, per §10 table and per enum; AG-00 the only DDL owner | §10 | MUST | FULL | Removes F-16, F-17 |
| TRC-05 | All CONFLICT rows ruled at the CP0 contract freeze and recorded as ADRs | task | MUST | FULL | §3.2 ruling table is the input |
| TRC-06 | Jury-facing «Соответствие ТЗ» page generated from test results, with status per TZ row and a link to evidence | win | SHOULD | FULL | Also used internally at CP1–CP3 |
| TRC-07 | Every SIMPLIFIED/MOCKED/OUT_OF_SCOPE item carries an explicit label in the UI or docs (never presented as full compliance) | honesty | MUST | FULL | Expert jury credibility |
| TRC-08 | Re-audit at CP1, CP2, CP3; the delta is reported to the orchestrator | process | SHOULD | FULL | Keeps the matrix live |
| TRC-09 | One consolidated question letter to the organizers (all blocks' open questions) | §8 | MUST | FULL | 12 blocks asked ~25 questions separately |
| TRC-10 | Each block requirement links to a TZ row or is tagged `derived` with a reason | hygiene | SHOULD | SIMPLIFIED | Lets us show scope beyond the ТЗ without muddying compliance |

### 2.19 Reverse traceability (block → ТЗ)

A script checked every block requirement ID cited above against the checklists of the 11 reports. All 756 cited IDs exist, and none is cited wrongly.

**The 112 block requirements not cited are supporting or derived items. None of them points to a ТЗ clause missing from §2.** They fall into these groups:
- **User wish / delivery:** ARC-75…77, PLT-98/99, UI-79, ERR-74…78.
- **Hardening beyond the letter:** ING-11, PLT-80/81, ERR-47/51.
- **UX quality:** UI-08…10, UI-24, UI-62/63, UI-82/84, VER-62/63, VER-67.
- **Resilience:** ERR-67/68, ERR-81/82, PLT-59, PLT-102.
- **Implementation enablers:** EXT-04, EXT-15, EXT-22/23, EXT-28, EXT-32, EXT-44, EXT-51, ING-29…32, ING-42…44, ING-53…55.
- **Explicit NICE / OUT_OF_SCOPE extras:** UI-89/90, PLT-103, MLF-75, EXT-54, EXT-58.

TRC-10 asks the owners to tag these `derived` in `tz_requirements.yaml`. Once tagged, the compliance page separates "ТЗ letter" from "above the ТЗ".

---

## 3. Proposed design

### 3.1 Canonical block → module → owner map (resolves F-16, F-17)

| Report block (file) | Alias used inside B00/B03/B04/B06 | ТЗ scope | Build agent (B00 §10.2) | Semantic owner of §10 tables |
|---|---|---|---|---|
| B00 `00_architecture` | — | §1, cross-cutting, contracts | AG-00 | DDL of all tables (only DDL owner) |
| B01 `01_ingestion…` | "B01 Upload/parsing" (part A) | M1 intake, registry, revisions, completeness; M12 intake | AG-01 | Objects, Files |
| B02 `02_extraction…` | "B01 Upload/parsing" (part B) | M1 OCR/NLP/CV/coordinates | AG-01 (roles ml-extraction, ml-nlp-cv); `ml-eval` harness → AG-04 | `extracted_values`, `document_pages` (not a ТЗ table) |
| B03 `03_matrix…` | "domain agent" | §8, Params content, rule DSL, Normative_Base / Logical_Rules seeds, ИД checklist | **Evaluator/DSL: AG-02. Content/enrichment: AG-09.** Seeds of Logical_Rules: AG-05 | Params (content/schema), Normative_Base (content) |
| B04 `04_comparison…` | "B02 Comparison/protocol" | M2, protocol renderer (M7 exports) | AG-02 | Checks, Protocols (content), Evidence_Fragments |
| B05 `05_verification…` | "B03 Verification" | M3 | AG-03 | Rejection_Log, Dispute_Log (writes in the decision transaction) |
| B06 `06_feedback…` | "B04 Retraining + B10 Weekly report" | M4, M10, §14 harness | AG-04 | Dataset_Items, Model_Versions, ML_Retraining_Log; updates `retraining_status`/`resolution_status` via API |
| B07 `07_free_hypothesis…` | "B05 Hypotheses" | M5 | AG-05 | Suspicions, Logical_Rules (evaluator) |
| B08 `08_frontend…` | "B07 Dashboard / B08 Normative" | M7, M8, web shell | AG-07 | Admin API for Params / Normative_Base / Logical_Rules (writes via the published-version flow) |
| B09 `09_platform…` | "B06 РиН", "B09 Audit", "B11 Monitoring" | M6, M9, M11, §11–§13 | AG-06 (РиН), AG-08 (audit, monitoring, security) | Audit_Log, Monitoring_Metrics, Protocols (versioning semantics) |
| B10 `10_error…` | "B12 Negative scenarios" | M12 | AG-09 | errors.yaml (contract), no table |
| **91 (this)** | — | whole ТЗ | AG-00 (tooling) + AG-09 (tests) | `tz_requirements.yaml` |

Rule: inside the contracts, ADRs and code, blocks are referenced by **ТЗ module number** («M3 Верификация») or by **agent** (AG-03), never by "Bxx". Bxx aliases are ambiguous.

### 3.2 Consolidated ruling table for CP0 (input to the contract freeze)

| # | Topic | Conflicting positions | Proposed ruling | Changes required |
|---|---|---|---|---|
| R1 | Candidate policy (F-02) | B03 D-02a strict / B04 D1c per-param / B07 D1b, D2b / B06 D6 | Per-param `candidate_policy` (B04 §3.4.3). Numeric normative params = TRIGGER. Qualitative/configuration params = DEVIATION. Room-level diffs live under M-003.b etc. (B03). Router (B07 D2b) seeded from B03's map. Auto-promotion only with the full card | B04 spec per param; B07 router; B03 map published as `change_matrix_map` |
| R2 | Scorer demotion (F-19) | B06 D6 vs B04 status rules / B10 ERR-23 | Scorer → risk ordering only in MVP; demotion behind a flag after a real-GOLD gate | B06 §3.2; B04 §3.4.2 note |
| R3 | Incremental status (F-03) | B01 → PARSING vs B00/B05 sub-state | Sub-state `recheck_state`; PARSING only initially | B01 §3.7, ING-73/74; B08 capability map |
| R4 | Renderer (F-13) | B00 / B04 / B08 | One DOCX template → DOCX + PDF (Gotenberg/LibreOffice); XML + XSD from JSON; owner AG-02; B08 = UI/jobs | B04 D4, B08 D16, B00 §0 #10 |
| R5 | Embedding (F-14) | e5-small vs MiniLM-L12 | e5-small in the bundle (config-switchable) | B03, B04, B06 C4, B07 D5 |
| R6 | Viewer (F-15) | pdf.js vs MuPDF tiles | MuPDF tiles + SVG overlay; pixel test retargeted | B00 §0 #7, B02-T16 |
| R7 | Logical_Rules language (F-18) | JSONLogic (B08) vs AST (B07) | AST for Logical_Rules; JSONLogic for applicability; one Python evaluator + dry-run API | B08 UI-64, B03 MTX-T12 |
| R8 | Table ownership & DDL (F-17) | multiple "owners" | §3.1 column 5; AG-00 DDL | all |
| R9 | Security MVP levels (F-10, F-11, F-12) | B00 vs B09 vs B10 | B09 wins; ARC-39/64 and ERR-43/83 re-graded to MUST / SIMPLIFIED; DB encryption made demonstrable | B00, B10 |
| R10 | §5 notes 2–4 (F-08, F-09) | SHOULD vs MUST; OOS vs SIMPLIFIED | MUST / SIMPLIFIED; B02 detects, B01 records, B04 prints | B01 ING-37/39/88, B02 EXT-41/42, B10 ERR-80 |
| R11 | Enums (F-26) | several | `enums.yaml` values as in F-26 | all |
| R12 | input_manifest_hash (F-27) | B01 vs B04 | Inputs only, JCS + SHA-256, golden vector | B01 ING-79, B04 CMP-07 |
| R13 | Notifications (F-22) | several | In-app + email MUST; Telegram for admin alerts | B05 VER-64, B08 UI-88 |
| R14 | Stack (F-23) | several | B00 backend/runtime; B08 frontend versions; PP-OCRv5 primary; LLM none by default | B00 §3.5, B01 §3.17 |
| R15 | Priority normalisation (F-29) | per-row mismatches | TRC-03 | all |
| R16 | Matrix count (F-24), linear objects (F-25) | uncovered / OOS vs SIMPLIFIED | Invariant 132; linear → N/A with basis | B03, B08, B01 |

### 3.3 Canonical routing of pilot evidence (R1 made concrete)

| Pilot group | Expected status | Emitted by | Param / rule | Discrepancy type | Notes |
|---|---|---|---|---|---|
| ALT79B-V01 | CANDIDATE | M2 | M-003.b room-level SET_DIFF (+ function change), M-002 = NEGATIVE_VERIFIED (+0,49 % < 1 %) | FUNCTION_CHANGED, VALUE_CHANGED | The M-002 vs M-003 contrast is a demo point (B03) |
| UNDMS-V01 | CANDIDATE | M2 | M-044 layer stack (B03 MTX-54) | LAYER_REMOVED | RD change-log entry shown as information, not as `approved_change_ref` (VER-05) |
| IZM12-V01 | CANDIDATE | M5 → auto-promoted | HR-LOG-007 (B03) | UNDOCUMENTED_WORK | `rule_version` in the GOLD `matrix_code/rule_version` field |
| LOS3A-V01 | CANDIDATE | M5 → auto-promoted | HR-LOG-038 (B03) | POSITION_SHIFTED | Change noted in the RD ведомость |
| OKT103-V01 | CONFIRMED_VIOLATION (by inspector) | M2 → M3 | M-054.b TOLERANCE_CHECK | TOLERANCE_EXCEEDED | 200 dpi scan; zone-level ABSTAIN for handwriting (B10 E-D2) |
| POL16-V01 | CANDIDATE | M2 | M-011 primary, alt M-003 (B03 D-12) | VALUE_CHANGED | |
| DOO25-V01 | CANDIDATE | M2 | M-003.b | CONFIGURATION_CHANGED, VALUE_CHANGED | |
| SOSH25-V01 | CANDIDATE | M2 | M-003.b | ELEMENT_ADDED, TOTAL_CHANGED | |
| POL17-N01 | NEGATIVE_VERIFIED | M2 | M-003.b / M-002 | — | FP regression test: 0 CANDIDATE and 0 HIGH suspicions (HYP-49) |
| Vent 1–3 (пояснения) | CANDIDATE | M2 | M-077.c, M-078.b, M-079.b (B03 MTX-56) | CONFIGURATION_CHANGED, ELEMENT_MISSING | Graphic evidence via label sets; GRAPHIC_DIFF only corroborates |
| ALT79B explication sum 2795,04 vs 2797,27 | SUSPICION | M5 | HR internal-consistency rule | TOTAL_CHANGED (internal) | Out-of-matrix demo from B07 §0 #4; not in the pilot GOLD |

This table becomes the golden test `T-ROUTING` (AG-09). Any change needs an ADR.

### 3.4 Traceability tooling

**Artifact.** `packages/contracts/traceability/tz_requirements.yaml` is generated once from §2 of this report and then maintained by hand under AG-00 review:

```yaml
- id: TZ-213
  ref: "§9.3 п.4"
  text_ru: "Финализация разрешена только после обработки всех CANDIDATE либо их явного переноса в CLARIFICATION_REQUIRED"
  prio: MUST
  module: M3
  owner: AG-03
  covers: [VER-37, ERR-29]
  mvp: FULL
  status: OK            # OK|PARTIAL|CONFLICT|DOWNGRADED|GAP|DATA (planning status)
  findings: []
  evidence:             # filled by CI
    tests: [T-NS-D05, e2e/verification/finalize-gate.spec.ts]
    demo_step: "DEMO-3.4"
```

**Tagging.** Tests carry both the block requirement and the ТЗ row:
- Vitest/Playwright: `test('… @req VER-37 @tz TZ-213', …)`;
- pytest: `@pytest.mark.req("EXT-30")` and `@pytest.mark.tz("TZ-126")`;
- k6: tags `{tz: 'TZ-292'}`;
- Schemathesis: operation-level `x-tz` extensions.

ARC-T18 already plans `@req` tags; this adds `@tz`.

**Generator** (`tools/traceability`, Python). It reads the YAML, collects JUnit XML from all suites, k6 summaries and the §11 benchmark JSON (PLT-97), and emits `traceability.json`:
- per-row status: PASS / FAIL / NO_TEST / PARTIAL (declared);
- per-module and per-priority rollups.

**CI gate.** The build fails if a MUST row has NO_TEST, or if a block requirement ID in the YAML does not exist in the report registry. It warns on SHOULD rows without tests.

**Runtime surface** (read-only, admin and jury role, OpenAPI-validated):
- `GET /api/v1/compliance/tz?module=&status=&prio=` → `{items:[{id, ref, text_ru, prio, module, mvp, status, tests:[{id, result, run_at}], demo_step}], totals}`.
- `GET /api/v1/compliance/tz/{id}` → one row with evidence links.
- `GET /api/v1/compliance/report.pdf` → a PDF annex for the jury pack, rendered by the same renderer as the protocols (R4).

**UI.** «Соответствие ТЗ» page under Администрирование, next to «Соответствие ТЗ (НФТ)» (B09 PLT-97) and «Самопроверка» (B10 ERR-76). It shows filters by section/module/status, a honest-label column (SIMPLIFIED/MOCKED shown in amber with the reason) and deep links to the demo step or screen.

**No new DB tables.** The artifact is static per build and served from S3/`fs`. Test runs are CI artifacts.

### 3.5 Priority normalisation rule (TRC-03)

A block requirement is MUST if its ТЗ source row contains any of:
- «обязательн…», «должен/должна/должны/должно», «только», «запрещ…», «не может/не могут», «не допускается», «система обязана», «система осуществляет»;
- or belongs to a High module (1, 2, 3, 4, 5, 12);
- or is a §11/§12/§13 row;
- or is a §14.3 metric.

MVP can still be SIMPLIFIED/MOCKED with a label, but priority cannot drop. Applying the rule re-grades: ARC-33, ARC-39, ARC-52, ARC-64, CMP-47, CMP-48, CMP-83, EXT-41, EXT-42, ING-37, ING-39, ING-88, ERR-43, ERR-49, ERR-53, ERR-80, ERR-83 (IDS part), HYP-56, MLF-65, MTX-28, PLT-89, UI-86, VER-52, VER-64, VER-75.

---

## 4. Interfaces with other blocks

| Block / agent | Consumes from 91 | Produces for 91 |
|---|---|---|
| AG-00 (B00) | Ruling table R1–R16 as CP0 agenda; `tz_requirements.yaml` seed; canonical owner map | Ratified ADRs; contracts updated; generator wired into CI (ARC-T18) |
| AG-01 (B01, B02) | F-03, F-08, F-09, F-15, F-25, F-27 changes | Tests tagged `@tz` for §9.1 rows; the Приложение 19 transcription check |
| AG-02 (B03 engine, B04) | F-02, F-06, F-13, F-14, F-19, F-24 changes; routing table §3.3 | `T-ROUTING` golden test; 132-row coverage view; renderer |
| AG-03 (B05) | F-04 (usability plan), F-22 | Usability report; verification tests |
| AG-04 (B06) | F-05 (quality owner with AG-09), F-19 | Nightly proxy-eval results into `traceability.json` |
| AG-05 (B07) | F-02 router/auto-promotion rules, F-18, F-20, F-26 | Suspicion tests; approach-4 model evidence |
| AG-06/AG-08 (B09) | F-10, F-11, F-12, F-28 | Security demo evidence; НФТ benchmarks |
| AG-07 (B08) | F-13 (UI only), F-15, F-18 UI, F-22, F-23, F-30; compliance page | Compliance page implementation |
| AG-09 (B10, data, QA) | TRC-02 gate, organizer letter content, proxy hidden test | Negative suite tags; proxy test manifest |

Contract: the `tz_requirements.yaml` schema above plus the `@tz` tag convention. Rows change only by PR reviewed by AG-00 and the row owner.

---

## 5. Too complex or risky items

| Item | Why risky | Simplification that still meets the letter |
|---|---|---|
| Reaching every §14.3 threshold on an unseen hidden test (F-05) | No real training data; 132 heterogeneous params; region-level GOLD boxes | Precision-first abstention; deep coverage where the pilot says the test lives (explications, layer stacks, tolerances); evidence-region convention tuned on the 27 pilot boxes; honest n, coverage and CI. The ТЗ only requires us to **report** abstention, and abstention is not a violation |
| Real usability test with 5 inspectors (F-04) | Depends on the customer's staff | A moderated remote protocol ready to run in 2.5 hours total (5 × 30 min); proxy round first; transparent reporting |
| Legally qualified УКЭП (F-12) | Needs an accredited УЦ and certified СКЗИ | Algorithmic GOST R 34.10-2012 signature + mTLS behind a `Signer` interface, clearly labelled |
| Certified IDS/DDoS (F-11) | ФСТЭК-certified tools, perimeter | IDS-lite + rate limits + optional CrowdSec/Suricata profile; production statement |
| DB TDE (F-10) | Community PG has no TDE | Encrypted volume + pgcrypto for PII, demonstrated; pg_tde evaluated as an option |
| Keeping 11 reports and the contracts consistent during the build | Drift is guaranteed without tooling | `tz_requirements.yaml` + CI gate + CP re-audits (TRC-02, TRC-08) |

---

## 6. ТЗ contradictions and ambiguities (index; most are already handled by blocks)

| # | Issue | ТЗ refs | Handled by | Recommended interpretation |
|---|---|---|---|---|
| A1 | §9.3 carries the title of §9.2 | §9.3 | B00 #4, B05 | Treat as «Модуль верификации инспектором» |
| A2 | Process statuses (COMPLETED/FINALIZED) vs verification statuses (VERIFICATION_COMPLETED/PROTOCOL_FINALIZED) | §9.1, §9.3 | B00 #1, B05 §3.2, B10 §1.2 | Two enums with a fixed mapping; the API returns both |
| A3 | PARSING forbids uploads and verification vs §9.3 п.3 | §9.1, §9.3 | B00 #3, B10 T13 | Sub-state (F-03) |
| A4 | «CV-анализ одного чертежа (DWG)» while inputs are PDF/DOCX/XML | §11 #8 | B00 #5, EXT-57 | One PDF drawing sheet; DWG rejected as an unsupported format |
| A5 | all-MiniLM-L6-v2 is English-only | §9.1 п.2 | B00 #6, B02 | «Совместимый аналог», chosen by benchmark (F-14) |
| A6 | PZ-01/KR-55/AR-41 vs M-001…M-132 | §8.2 | B00 #7, MTX-03 | Alias codes (verified: M-001, M-055, M-041) |
| A7 | §8.1 fields missing in the xlsx | §8.1 | B03 | Enrichment with confidence (F-21) |
| A8 | 10 × 50 МБ = 500 МБ > the 200 МБ package limit | §11 #1, §9.1 | B00 #16, B01 C1, B10 T3 | Package = one request; the NFR is measured over 3 packages |
| A9 | Приложение № 2 mandatory but absent | §9.2 | B00 #25, B04 | F-01 |
| A10 | Three different section lists: §3 has 13 ПП 87 sections; §6 has 12 matrix sections (adds ПОД, ЗУ; lacks ТХ, БЭ, ИН); §8.1 `section` enum | §3, §6, §8.1 | MTX-04, MTX-48 | `section` = §8.1 enum; `pp87_section_no` for completeness; ТХ/БЭ/ИН only in completeness |
| A11 | §2 row 13 is labelled «Закон РФ № 61-ФЗ» but its details read «от 15 апреля 1993 г. № 4802-1» | §2 | new | Cite as «Закон РФ от 15.04.1993 № 4802-1 «О статусе столицы Российской Федерации» (ред. от 26.12.2025)». Treat «61-ФЗ» as a likely reference to the amending law; ask the organizers |
| A12 | NEGATIVE_VERIFIED is both a system status and an inspector decision; the §9.2 table calls system negatives «обязательный отрицательный пример для оценки ложных срабатываний» | §9.2, §9.3, §14.1 | B00 #13, CMP-41, MLF | Keep every system negative with full evidence (FP evaluation and sample review). Only inspector-decided negatives become GOLD |
| A13 | Who converts SUSPICION → CANDIDATE: the §9.2 status table lists it as an inspector action; §9.5 only states the evidence precondition | §9.2, §9.5 | B07 D1 | System promotion is allowed with a complete card (`promoted_by=SYSTEM`); the inspector path always exists (F-02) |
| A14 | «≤ 30 минут» (§9.3) vs «Не более 30 минут ±10 минут» (§11 #15); likewise every §11 row has a tolerance | §9.3, §11 | new | Design and report against the strict value; the tolerance is the acceptance band, not the target |
| A15 | Module 7 names three colours; objects without results need a state | §7 M7 | B08 | Grey = «нет результата / в обработке», never a severity (F-30) |
| A16 | МЕТРИКИ «Число параметров 132» vs Module 8 «добавлять … нормативные ссылки» | МЕТРИКИ, §7 M8 | new | Module 8 adds references, not params; the param count is invariant (F-24) |
| A17 | GOLD schema has singular expected/actual sources; pilot groups have several pages and boxes | СХЕМА GOLD, ПРИМЕРЫ | B04 #8, B02 C12 | Lists of fragments per role; IoU on unions; ask the organizers |
| A18 | §9.1 OCR acceptance uses a separate hidden OCR sample; §14.2 hidden test is object-level | §9.1, §14.2 | B06 T15 | Two run modes: `inspector-ocr` (page images → text + boxes) and `inspector-batch` (object packages → GOLD-schema JSONL) |
| A19 | Matrix row M-117 («< 1,5 м» for МГН doors) is probably an error; M-121 3,5 vs 3,6 м | Приложение 1 | B03 D-04, D-06 | Default to the norm with the matrix value shown; ask the organizers |
| A20 | «Повторная загрузка создаёт новую запись и новую версию протокола» for byte-identical files | Реестр | B01 D5, B10 T10 | Identical bytes → idempotent, audited, no new version |

---

## 7. Decisions needed from the user (consolidated across blocks)

| # | Question | Options | Recommendation | Blocks affected |
|---|---|---|---|---|
| D-U1 | External/cloud LLM (152-ФЗ, localisation) | none / local Ollama / Russian cloud / foreign cloud | **None by default, local optional; never foreign cloud for real documents.** The core must pass the demo with LLM = none | B00 D1, B02, B03 D-01, B07 D4 |
| D-U2 | Candidate policy and routing (F-02, R1–R2) | strict triggers / any deviation / per-param + router + gated auto-promotion | **Per-param policy + router + gated auto-promotion; scorer = ordering only** | B03, B04, B06, B07 |
| D-U3 | Embedding model (F-14) | e5-small / MiniLM-L12 | **e5-small** (measured), MiniLM-L12 documented | B02, B03, B04, B06, B07 |
| D-U4 | Protocol renderer (F-13) | HTML→Chromium / DOCX template → LibreOffice / both | **One DOCX template → DOCX + PDF**, owner AG-02 | B00, B04, B08 |
| D-U5 | Send the consolidated organizer letter now (§8) | yes / no | **Yes, today** | all |
| D-U6 | Ask the organizers for 5 inspectors for the usability test (F-04) | yes / proxies only | **Yes**, with proxies as a fallback | B05, B08 |
| D-U7 | DB encryption approach (F-10) | encrypted volume + pgcrypto / Percona pg_tde / documented only | **Encrypted volume + pgcrypto**, demonstrated; pg_tde evaluated | B09 |
| D-U8 | Real Telegram bot token for alerts | real / mock | **Real** for the demo | B09, B10 |
| D-U9 | Domain expert (1–2 h) to verify ~40 demo normative references and M-117 | expert / badges only | **Expert** | B03, B07 |
| D-U10 | Docker runtime now (OrbStack/Colima) | install / no-Docker | **OrbStack now**; compose parity from day 1 | B00 |
| D-U11 | Accept the re-grading of priorities by TRC-03 | yes / no | **Yes** | all |

---

## 8. Data needed

The first eight rows form **one consolidated organizer letter** (TRC-09). The other rows are data we need from elsewhere.

| What | Why | Fallback if never received | Asked by |
|---|---|---|---|
| **Приложение № 2** (sample output protocol) | §9.2 makes its form mandatory (F-01) | Template-driven interim layout, labelled | B00, B04, B08 |
| **Hidden-test run protocol**: UI, API or CLI; input manifest format; expected output (GOLD-schema JSON/XLSX?); how IoU is computed for multi-box evidence | Decides which interface gets scored | `inspector-batch` + `inspector-eval` + GOLD-schema export, all documented | B00, B02, B06 |
| OCR acceptance: normalisation of dashes, homoglyphs and case; format of pre-marked illegible zones; scoring of LOW_QUALITY/ABSTAIN | §9.1 п.1 metric fidelity | Publish strict and relaxed metrics | B02 D6 |
| How out-of-matrix findings (IZM12, LOS3A) are labelled in the hidden test (`rule_version`?) | Routing (F-02) | Rule codes + auto-promotion | B03 D-08 |
| Matrix issues: M-117 threshold, M-121, duplicate params | FP control | Norm-based defaults, shown in admin | B03 |
| 5 inspectors for the usability test | §9.3 mandatory (F-04) | Proxies + disclaimer | B05 |
| Historical data for approach 4 (ТЭП/consumption per object) | §9.5 #4 (F-20) | Synthetic history, labelled | B07 |
| Clarification of «Закон РФ № 61-ФЗ» vs № 4802-1 | §2 citation (A11) | Cite 4802-1 | new |
| Clean originals of pilot files; ≥ 1 full ПД/РД/ИД set; ИД XML samples | Realistic runs, XML input | Sanitised pilot pages + synthetic generator | B00, B01, B02, B06 |
| ИАИС «РиН» API description | Integration fidelity | Mock with our own OpenAPI | B00, B09 |

---

## 9. Jury demo scenario and acceptance criteria

**Demo (≈ 3 min, at the end of the main storyline B00 §9.1):**
1. Open «Администрирование → Соответствие ТЗ».
2. Show 389 rows grouped by ТЗ section, with totals by status and the live PASS/FAIL from the latest CI run.
3. Filter on «High modules, MUST». Every row is green or amber-labelled (SIMPLIFIED/MOCKED with the reason); zero red.
4. Click TZ-213 (finalization gate). It jumps to the recorded e2e test result and the demo step where finalization is refused with the list of blockers.
5. Click TZ-137 (50 МБ). It shows the negative-fixture test and the live rejection of the organizers' own 51,49 MiB pilot kit (B10 E-D6).
6. Click TZ-342 (P/R/F1). It shows the proxy-test evaluation report with n, coverage and 95 % CI, and the honest statement that the hidden test belongs to the organizers.
7. Download the PDF annex «Соответствие ТЗ» for the jury pack.

**Acceptance criteria / tests for this block:**

| Test | Criterion | Proves |
|---|---|---|
| T-TRC-01 | The generator runs on the repo; 389 rows parsed; every `covers` ID exists in the requirement registry | TRC-01, TRC-10 |
| T-TRC-02 | CI fails when a MUST row loses its last test (mutation test on the YAML) | TRC-02 |
| T-TRC-03 | At CP0 exit, zero rows with status CONFLICT or DOWNGRADED; every ruling R1–R16 has an ADR | TRC-03…05 |
| T-TRC-04 | `GET /api/v1/compliance/tz` validates against OpenAPI; p95 < 200 ms | TRC-06, TZ-011/012, TZ-292 |
| T-TRC-05 | Every SIMPLIFIED/MOCKED row has a Russian label string in the UI catalogue | TRC-07 |
| T-ROUTING | The 9 pilot groups + 3 vent items + 1 synthetic suspicion produce exactly the statuses and emitters in §3.3; no change counted twice | F-02 |
| T-MATRIX-132 | Publishing a matrix version with ≠ 132 params, or deleting a param, is rejected; a deactivated param is reported NOT_APPLICABLE with basis | F-24 |
| T-COVERAGE-132 | For each pilot object, the protocol holds exactly one status per active param × object (132 rows), never empty | F-06 |

---

## 10. Work breakdown

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| TRC-T01 | Convert §2 of this report into `packages/contracts/traceability/tz_requirements.yaml` (389 rows) and a JSON Schema for it | S | ARC-T01 | AG-00 |
| TRC-T02 | CP0 ruling session: walk R1–R16, write ADRs, update the affected contracts (enums, errors, DDL owners, renderer, viewer) | M | block reports, TRC-T01 | AG-00 + all agents |
| TRC-T03 | Apply priority normalisation TRC-03 to the requirement registry (25 re-grades listed in §3.5) | S | TRC-T02 | AG-00 |
| TRC-T04 | `@tz` tagging convention in Vitest/pytest/Playwright/k6/Schemathesis; extend the ARC-T18 generator; CI gate | M | ARC-T18 | AG-09 |
| TRC-T05 | Compliance API (3 endpoints) + OpenAPI + PDF annex via the protocol renderer | S | TRC-T04, R4 renderer | AG-07 (API with AG-00) |
| TRC-T06 | Human spot-check of the Приложение 19 transcription (111 items) against `img_perechen/image1–4.png`; fix differences | S | — | AG-09 |
| TRC-T07 | Consolidated organizer letter (the §8 rows) in Russian, ready to send | S | — | AG-09 (user sends, D-U5) |
| TRC-T08 | `T-ROUTING` golden test from §3.3 | M | B04 engine, B07 router | AG-02 + AG-05 |
| TRC-T09 | `T-MATRIX-132` and `T-COVERAGE-132` tests | S | MTX-T02, B04 protocol | AG-02 |
| TRC-T10 | Proxy hidden-test manifest (pilot + vent + synthetic, object-split, SHA-256 frozen) and nightly `inspector-eval` job feeding `traceability.json` | M | B06 T10, MTX-T18 | AG-04 + AG-09 |
| TRC-T11 | Compliance UI page «Соответствие ТЗ» (filters, honest labels, deep links) | M | TRC-T05 | AG-07 |
| TRC-T12 | Re-audits at CP1, CP2, CP3 (diff of statuses, new conflicts) | S ×3 | TRC-T04 | AG-00 (this critic role) |
| TRC-T13 | «Соответствие нормативной базе (§2)» one-pager + Normative_Base rows for the 13 acts | S | MTX-T11, D-U9 | AG-09 |

Critical path: TRC-T01 → TRC-T02 (inside CP0) → TRC-T04 → TRC-T05/T11. TRC-T06, T07 and T13 can start immediately.
