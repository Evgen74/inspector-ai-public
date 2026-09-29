# B01 — Ingestion: Upload, File Registry, Revisions, Completeness (Module 1 Part A, priority High)

Owner block: **B01-ingestion**. Requirement prefix: **ING-NN**.
Sources used: `01_TZ_text.txt` (full ТЗ, all 14 sections), `02_matrix_all_sheets.txt` (all 4 sheets), `03_perechen_ID_registry_rules.txt`, `img_perechen/image1–4.png` (Приложение 19, read in full), `05_razmetka_poyasn_6p_text.txt`, page previews `img_razmetka/p01–p24`, and the original `Комплект_предметной_разметки.pdf`. I inspected the original with PyMuPDF: page boxes, rotation, image DPI, fonts, Ink annotations, and text-layer title blocks. I also built a throw-away title-block prototype and ran it on all 24 pages. Cross-checked against the B04 report (`04_comparison_protocol.md`) so the contracts line up.

---

## 0. Executive summary (read this first)

1. **Registry-first, stamp-verified.** The ТЗ makes the machine-readable registry mandatory: «без него пакет принимается со статусом CLARIFICATION_REQUIRED». The registry is the authority for stage, шифр, revision, approval status and predecessor/successor. Title-block (штамп) extraction has three jobs: (a) cross-check the registry, (b) auto-fill a draft registry in the UI helper, and (c) feed the OCR key-field metric («Exact Match … шифр, стадия, редакция, номер листа/страницы ≥ 0,90»). The system never *assumes* an approval status. A missing approval mark is CLARIFICATION_REQUIRED.
2. **The pilot shows that `file_id` is an external, organiser-assigned id.** Ids such as `ALT79B-000015`, `DOO25-001733` and `SOSH25-003642` appear nowhere in the page text. They follow the pattern `<OBJECT_MNEMONIC>-<6-digit sequence>`, and the sequence runs into the thousands per object, so real object arrays hold hundreds to thousands of files. The hidden-test GOLD scores «Точное совпадение file_id и страницы», so **we must keep and echo the registry `file_id` exactly** and must not replace it with our own UUIDs. When there is no registry, we generate ids in the same convention.
3. **Sheet ≠ page, with a variable offset.** Examples: ALT79B PD page 19 is «Лист 3»; ALT79B RD page 4 is «Лист 2»; POL17 PD page 26 is «Лист 2»; SOSH25 PD page 49 is «Лист 46». `sheet_page_range` is therefore essential, and we derive it automatically from per-page stamps.
4. **ПД and РД шифры of the same object often differ, sometimes completely.** UNDMS has `59-0222-П-5Э-АР2` for ПД and `305-0294-5Э-Р-АР2` for РД (different designers). LOS3A has `…/Н-АР` for ПД and `…/Н-1-АР2` for РД. ALT79B only swaps the prefix (`П-2025-04.266-АР` and `РД-2025-04.266-АР`). **Cross-stage linkage therefore has to be object + discipline family (+ scope)**, with code similarity used only as a secondary signal. Revision chains use the exact code within one stage.
5. **Pages come in three content classes, and each needs different handling.** (a) Vector pages with a text layer: 17 of 24 pilot pages, where the stamp can be parsed from the text layer. (b) Vector pages whose SHX text was exported as curves: p9, 27,421 paths and no text, so the stamp needs rasterise + OCR. (c) Raster scans: p14 at 200 dpi (below the ТЗ's 300 dpi OCR premise, so it must be flagged LOW_QUALITY); p3/p5 are 150 dpi rasters with an added text layer. Prototype result: the шифр came out exact on 15 of 20 stamped sheets from the text layer alone, stage on 19/20, sheet number on 17/20. All failures are explained and fixable (see §3.9).
6. **Completeness is defined in two layers.** (A) *Declared vs received*: registry rows that have no accepted file. This is exactly the ТЗ example «5 из 15 файлов ИД». (B) *Normative checklist*: ПП 87 sections (§3), РД composition (§4), ИД per 344/пр (§5) with Приложение 19 detail, filtered by an object applicability profile. Only CORE items can make a stage PARTIAL. Everything else becomes MISSING_EVIDENCE rows «не считать нарушением».
7. **Revision selection is deterministic, conservative and inspector-resolvable.** Rules: explicit chains or SUPERSEDED/CANCELLED marks resolve automatically. Two approved heads with no link produce CLARIFICATION_REQUIRED with a *pre-computed suggestion*, so the inspector resolves it in one click and the basis is recorded. A superseded file can never be the reference; this is an invariant enforced by tests. This directly drives two scored metrics: «Связка документов ≥ 0,95» and «FPR … на случаях с устаревшей редакцией ≤ 0,10».
8. **B01 owns ingestion state; the protocol and comparison belong to B04.** B01 produces the upload statuses, `scenario` + `scenario_base` (names aligned with B04), reference selections, completeness items, `input_manifest_hash` (RFC 8785 JCS + SHA-256, aligned with B04 CMP-07), and an incremental *delta* event. B04 consumes the delta to recompute only the affected parameters.

---

## 1. Scope

### 1.1 ТЗ clauses owned by B01

| Clause | Quote / essence | Ownership |
|---|---|---|
| §1.2 bullet 4 | «автоматический контроль наличия документов и инкрементальная дозагрузка файлов до момента финализации протокола» | full |
| §1.3 | «REST over HTTPS (JSON)… с обязательной валидацией схемы OpenAPI 3.0» | full for ingestion endpoints |
| §1.4 | «После загрузки документов система возвращает идентификатор процесса (process_id)… Статус обработки отслеживается через эндпоинт мониторинга» | full |
| §7 module 1 (High) | «Загрузка ПД, РД, ИД (PDF, DOCX, XML)…; контроль наличия документов; адаптация под сценарий загрузки» | Part A (upload, registry, identification, revisions, completeness, scenario inputs); Part B (132-param extraction) belongs to the parsing block |
| §7 module 12 (High) | «повреждённые файлы, нечитаемые форматы, превышение лимитов, сбои интеграции, некорректные данные» | all intake-side negative scenarios |
| §9.1 Назначение | «идентификация стадии, шифра, раздела, редакции и статуса утверждения каждого документа; построение связок сопоставимых актуальных документов; … отдельный контроль комплектности» | full |
| §9.1 alg. 4 | «для каждого извлечённого значения сохраняются file_id, SHA-256 файла, стадия, шифр, редакция, статус утверждения, лист/страница и нормализованный bbox/polygon… после учёта CropBox, MediaBox и Rotate» | B01 provides the file/page metadata and page-geometry registry; the parsing block attaches values |
| §9.1 alg. 5 | «Результаты парсинга сохраняются в Redis по хешу файла» | full (cache layer) |
| §9.1 «Выбор актуальной редакции» | «обязательны object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, sheet/page, file_hash и связь predecessor/successor. Сравнивается последняя применимая утверждённая редакция. При конфликте редакций, отсутствии признака утверждения или неоднозначной связи система присваивает CLARIFICATION_REQUIRED… Устаревшая редакция не может использоваться как эталон.» | full |
| §9.1 «Дозагрузка файлов» | «инкрементальную дозагрузку файлов без перезагрузки существующих… до момента финализации протокола» | full |
| §9.1 error table | unsupported format, corrupted PDF, 50 МБ, 200 МБ, «Таймаут… Повторная попытка обработки (до 2 раз). При неудаче – уведомление администратора» | full |
| §9.1 «Статусы загрузки документов» | PD_/RD_/ID_ UPLOADED / PARTIAL / MISSING | full |
| §9.1 «Статусы процесса проверки» | PENDING / PARSING / READY / VERIFYING / COMPLETED / FINALIZED with «Возможность дозагрузки» | the upload-gating column is full; transitions are co-owned with B04/B03 |
| §9.2 alg. 1 | «загрузка … реестра файлов и цепочек редакций» | B01 provides the snapshot |
| §9.2 alg. 2 | scenario FULL / PD_RD_ONLY / PD_ID_ONLY / RD_ID_ONLY / SINGLE_ONLY / PARTIALLY_LOADED | B01 computes `scenario` + `scenario_base`; B04 applies them |
| §9.2 alg. 4 | «раздел «Статус загрузки документов»», «раздел «Тип проверки»», table «(1) комплектность и сопоставимость» | B01 supplies the data; B04 renders |
| §9.3 п.3, п.5, «Отмена финализации» | «инспектор может дозагрузить файлы без сброса верификации»; «После финализации дозагрузка… невозможны»; after un-finalisation «дозагрузка становится снова возможной» | upload gating full |
| §9.6 scenario 1 + «Блокировка автоматической дозагрузки» | «POST /api/v1/documents/upload → получение process_id»; if finalised, the РиН auto-pull «не запускает проверку, а только уведомляет инспектора… с предложением создать новую проверку» | endpoint full; the РиН hook is shared with B06 |
| §10 #3 Objects, #4 Files | «id, name, address, customer, contractor, permit_number»; «id, object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, predecessor_id, file_hash, file_path, uploaded_at» | full (superset) |
| §12 #11 | «Все загружаемые файлы проходят антивирусную проверку перед сохранением в хранилище» | full |
| §13 #8 | «Ежедневная проверка контрольных сумм (хешей) файлов в хранилище» | full for the file store |
| `03_…` | mandatory registry, 12 fields, «Перезапись файла под тем же file_id запрещена. Повторная загрузка создаёт новую запись и новую версию протокола», 6-row source-selection table | full |
| §3, §4, §5 (+ Приложение 19) | expected composition of ПД / РД / ИД | full as completeness templates |

### 1.2 Related clauses (co-owned or consumed)
- §5 notes 1–3: УКЭП/УНЭП for electronic ИД; scanned ИД allowed «при условии наличия оригинала… визуальную проверку наличия всех обязательных реквизитов (подписи, печати, даты, регистрационные номера)»; РД «штампы «В производство работ» и «Выполнено согласно проекту»». B01 detects these; B04 prints them in table (1), as in B04 CMP-89.
- §6 matrix ↔ documentation mapping. B01 turns it into the `discipline_map` data table; B04 uses it to map a delta to the affected parameters.
- §11 #1 (upload of 10 files ≤ 2 min), #2–3 (OCR deadlines, which B01 uses as job timeouts), #9 (incremental ≤ 1 min, where B01's share is intake + meta), #10–11 (API p95 ≤ 200 ms, 100 inspectors).
- §12 #1–4, #6: authentication, roles, encryption at rest for the file store, audit of every upload/download, ПДн in stamps (ФИО «Разработал/Проверил/ГИП»).
- §13 #1, #4, #7: JSON logs with request_id/user_id, the RabbitMQ queue-size metric, admin alerts on e-mail/Telegram (delivery is owned by monitoring).
- §14.2 «Фиксация теста — … SHA-256 входных файлов/разметки фиксируются организатором»: our SHA-256 must be over the raw bytes so it matches the organiser manifest. «Версионность — … input_manifest_hash».
- §14.3 «Связка документов — Доля evidence_group с точным выбором object_id, стадии, шифра и актуальной редакции ≥ 0,95» is essentially B01's metric. «Ключевые поля Exact Match ≥ 0,90» is shared with the parsing block.

### 1.3 Statuses B01 emits
- **Upload (per stage):** `PD_UPLOADED | PD_PARTIAL | PD_MISSING`, `RD_…`, `ID_…`.
- **Scenario:** `FULL | PD_RD_ONLY | PD_ID_ONLY | RD_ID_ONLY | SINGLE_ONLY | PARTIALLY_LOADED`, plus `scenario_base` (the same enum without PARTIALLY_LOADED, or `NONE`).
- **Document/selection level** (the exact СХЕМА GOLD `completeness_status` enum): `COMPLETE | MISSING_EVIDENCE | NOT_APPLICABLE | NOT_COMPARABLE | CLARIFICATION_REQUIRED`. Completeness *items* additionally use `DECLARED_NOT_RECEIVED` internally, which is printed as MISSING_EVIDENCE with reason «заявлен в реестре, не загружен».
- **File intake:** `RECEIVED → STORED → VALIDATED → META_EXTRACTED` or `REJECTED_{FORMAT|SIZE|CORRUPTED|ENCRYPTED|EMPTY|INFECTED|MISMATCH}` or `FAILED_TIMEOUT` (internal; §3.4).
- **Registry:** `MISSING | INVALID | VALID_WITH_WARNINGS | VALID | DRAFT_UNCONFIRMED`.
- **Package:** `ACCEPTED | ACCEPTED_WITH_REJECTIONS | CLARIFICATION_REQUIRED | REJECTED_PACKAGE_LIMIT`.
- **Process:** the §9.1 names `PENDING | PARSING | READY | VERIFYING | COMPLETED | FINALIZED`. B01 reads them for gating and sets `PARSING` on an accepted upload (§3.7).

---

## 2. Requirements checklist

Legend: priority = importance for winning (MUST / SHOULD / NICE); MVP = FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

### A. Upload API and intake validation

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-01 | Upload ПД/РД/ИД via UI and API, `POST /api/v1/documents/upload`, returns `process_id` | §9.6 сц.1; §1.4; §7 m1 | MUST | FULL | Core entry point; the UI uses the same endpoint |
| ING-02 | Async pull: 202 Accepted + status endpoint; results only on request | §1.4 | MUST | FULL | `GET /api/v1/processes/{id}/status` |
| ING-03 | All JSON requests/responses validated against an OpenAPI 3.0 schema (multipart text fields too) | §1.3 | MUST | FULL | Spec-first; ajv at runtime; contract tests |
| ING-04 | Only PDF, DOCX, XML accepted; others rejected «с указанием поддерживаемых форматов (PDF, DOCX, XML)» | §9.1 err.1 | MUST | FULL | Per-file rejection; DWG/DOC/ZIP/.sig explicitly rejected |
| ING-05 | Format decided by content (magic bytes / container structure); extension–content mismatch rejected | §9.1 err.1; m12 «некорректные данные» | SHOULD | FULL | Prevents renamed executables and `.doc` posing as `.docx` |
| ING-06 | File > 50 МБ rejected, stating the max size | §9.1 err.3 | MUST | FULL | 50 MiB = 52 428 800 bytes, exact number in the message |
| ING-07 | Package > 200 МБ rejected as a whole, stating the exceeded limit | §9.1 err.4 | MUST | FULL | Checked before and during streaming (Content-Length + counter) |
| ING-08 | Corrupted PDF rejected; user notified to re-upload | §9.1 err.2 | MUST | FULL | Sync fast check + async deep check (pikepdf/PyMuPDF), then notification |
| ING-09 | Corrupted DOCX / non-well-formed XML rejected the same way | m12 «нечитаемые форматы» | MUST | FULL | ZIP central directory + required parts; streaming XML parse |
| ING-10 | Password-protected PDF, 0-byte file, 0-page PDF → specific rejection reason | m12 | SHOULD | FULL | Clear RU messages; cheap to implement |
| ING-11 | Hardening: XXE/DTD disabled, DOCX zip-bomb guard, filename sanitisation, PDF active content (JavaScript/Launch/EmbeddedFile) flagged | §12; m12 | SHOULD | FULL | Security judges look for this; low cost |
| ING-12 | Antivirus scan **before** storage; infected → rejected, not stored, security audit event + admin alert | §12.11; §12.5 (1-year retention for security events) | MUST | FULL | ClamAV (clamd INSTREAM); EICAR demo; fail-closed |
| ING-13 | SHA-256 of the raw bytes computed for every file while streaming | 03; §9.1 alg.4; §14.2 | MUST | FULL | Must equal the organiser manifest hash |
| ING-14 | Maximum file count per package (anti-abuse) and upload rate limit | §12.9 | NICE | SIMPLIFIED | Config: 1000 files/package, 20 uploads/min/user |

### B. Storage, immutability, security

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-15 | Keep the original file, its hash and its revision chain | 03 «хранить исходный файл, его хеш и цепочку редакций» | MUST | FULL | Content-addressed write-once store |
| ING-16 | Overwriting under the same `file_id` is forbidden (409 FILE_ID_IMMUTABLE) | 03 | MUST | FULL | DB trigger + `wx` open flag + unique constraint |
| ING-17 | Re-upload creates a new record and triggers a new protocol version | 03 | MUST | FULL | New `Files` row + delta event; B04 bumps the version. Identical bytes are idempotent (decision D5) |
| ING-18 | Encryption at rest of the file store (and DB) | §12.3 | SHOULD | SIMPLIFIED | App-level AES-256-GCM for blobs; DB via volume encryption + pgcrypto for ПДн columns |
| ING-19 | Daily SHA-256 integrity check of all stored files; mismatches alerted and audited | §13.8; §12.7 (187-ФЗ integrity) | SHOULD | FULL | Scheduled job + admin button + tamper demo |
| ING-20 | Audit every upload, download, registry submission, revision decision, N/A marking and rejection (user_id, time, IP, UA, object_id) | §12.4; m9 | MUST | FULL | Writes to the shared `Audit_Log` |
| ING-21 | RBAC: inspector/integration account may upload; supervisor/admin may override; admin edits templates; ML engineer read-only | §12.2 | MUST | FULL | Route guards |
| ING-22 | ПДн minimisation: stamp ФИО not stored as structured fields; masked in logs; developer contacts kept in encrypted columns | §12.6 | SHOULD | SIMPLIFIED | Extract only the fields needed for identification |
| ING-23 | Transport TLS 1.3 | §12.3 | MUST | SIMPLIFIED | Reverse proxy (Caddy/nginx) in compose; mkcert locally (infra block) |
| ING-24 | Backup-friendly layout (DB + file volume), RPO ≤ 15 min | §12.8; §11 #14 | NICE | SIMPLIFIED | Infra block; the store is a plain volume |

### C. Machine-readable file registry

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-25 | Every package comes with a registry in CSV, XLSX or JSON | 03 | MUST | FULL | Multipart part `registry` |
| ING-26 | Registry fields: object_id; file_id / file_name / SHA-256; doc_stage (PD/RD/ID); discipline; document_code; revision; approval_status (DRAFT/APPROVED/FOR_CONSTRUCTION/SUPERSEDED/CANCELLED); approval_date; sheet_page_range; predecessor_id / successor_id; signature_status | 03 table 0 | MUST | FULL | Exact names; aliases for Russian headers |
| ING-27 | No registry → package accepted with status CLARIFICATION_REQUIRED; no violation conclusions until a registry exists | 03 | MUST | FULL | Package + file level flag |
| ING-28 | Row, cross-row and cross-file validation (enums, dates, SHA match, unique file_id, predecessor exists, no cycles, sheet ranges within page count, stage/status consistency) | 03; §9.1 | MUST | FULL | Error list with row/column; RU messages |
| ING-29 | Downloadable templates (CSV/XLSX with dropdowns, JSON + published JSON Schema) | 03 (usability) | SHOULD | FULL | Cuts user error; cheap with exceljs |
| ING-30 | UI helper that builds/auto-fills the registry from parsed stamps and filenames, with provenance, confidence and **mandatory human confirmation** | task; 03 | MUST | SIMPLIFIED | Text-layer stamps FULL; OCR stamps best-effort; approval_status is never auto-set to APPROVED |
| ING-31 | Registry versioning: FULL (replace) or DELTA (merge by file_id); history kept; registry hash part of the manifest | 03; §9.2 alg.1 | SHOULD | FULL | Needed for incremental uploads |
| ING-32 | Registry ↔ stamp cross-check; conflicting metadata → CLARIFICATION_REQUIRED («противоречивые метаданные») | §9.2 status table | SHOULD | SIMPLIFIED | Code/stage/sheet compared; low-confidence OCR produces only a warning |
| ING-33 | Export of the effective input registry (CSV/XLSX/JSON) for the protocol annex and the РиН payload | §9.3 п.4; §9.6 | MUST | FULL | «…вместе с … реестром входных файлов» |

### D. Document identification and page metadata

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-34 | Identify stage, шифр, раздел/марка, revision and approval status of every document | §9.1 Назначение | MUST | SIMPLIFIED | Registry authoritative; stamp extraction verifies and suggests |
| ING-35 | Per file the full mandatory set: object_id, doc_stage, discipline, document_code, revision, approval_status, approval_date, sheet/page, file_hash, predecessor/successor | §9.1 «Выбор актуальной редакции» | MUST | FULL | `Files` columns + `File_Pages` |
| ING-36 | Title-block extraction (ГОСТ Р 21.101-2020 forms 3/4–6): шифр, стадия, лист, листов, Изм. table (Изм., Кол.уч., Лист, №док., дата, Зам./Нов./Аннул.), sheet title, organisation, dates | §9.1 alg.1, key fields | MUST | SIMPLIFIED | Template + anchors on the text layer; OCR of stamp cells as fallback |
| ING-37 | Detect stamps «В производство работ» (→ RD FOR_CONSTRUCTION evidence) and «Выполнено согласно проекту» (→ as-built ИД item 7 of 344/пр) | §5 п.3 | SHOULD | SIMPLIFIED | Text search + blue-ink stamp OCR; the inspector confirms |
| ING-38 | Normalise шифр/discipline (АР1/АР2, КЖ02.1, ОВ2.1, ИОС5.4.2, ГЧ/ТЧ, dash homoglyphs) while **preserving the raw string** for Exact Match | §9.1 alg.1 («знаки в шифрах и редакциях не удаляются»); §14.3 | MUST | FULL | `code_raw` vs `code_match_key` |
| ING-39 | Signature status: PDF digital signatures (/Sig, /ByteRange), XML-DSig, visual requisites on scans (signatures, stamps, dates, reg. numbers) | 03 signature_status; §5 п.1–2 | SHOULD | SIMPLIFIED | Presence only; no GOST crypto validation (see ING-86) |
| ING-40 | Sheet↔page mapping (`sheet_page_range`), auto-derived from per-page stamps | 03 «соответствие листа странице PDF» | MUST | FULL | Pilot proves sheet ≠ page |
| ING-41 | Page geometry registry: MediaBox, CropBox, Rotate, visible size (pt, mm), paper format, normalised transform to [0;1] with top-left origin | §9.1 alg.4 | MUST | FULL | Shared utility plus rotated/offset fixtures (the IoU metric depends on it) |
| ING-42 | Page content class (VECTOR_TEXT / VECTOR_CURVES / RASTER / MIXED / BLANK), min image DPI, LOW_QUALITY flag (< 300 dpi) to route OCR | §9.1 alg.1 (300 dpi; LOW_QUALITY/ABSTAIN) | SHOULD | FULL | Pilot has all three classes |
| ING-43 | DOCX → PDF rendition (hash-linked derived artefact) so page/bbox addressing works; XML evidence located by XPath | §9.1 alg.4 | SHOULD | SIMPLIFIED | LibreOffice/Gotenberg; XML has no pages |
| ING-44 | Detect review markup/annotations in uploaded PDFs (Ink, overlay text) and flag it so the parsers ignore it | data hygiene (pilot pages carry baked-in expert markup) | NICE | SIMPLIFIED | `has_annotations`, `overlay_fonts` flags |

### E. Revisions and reference selection

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-45 | Build predecessor/successor chains from the registry and inspector decisions; detect cycles and branches | 03; §9.1 | MUST | FULL | Graph per document component |
| ING-46 | Select the **latest applicable approved** revision per document | §9.1 | MUST | FULL | Deterministic resolver (§3.10) |
| ING-47 | Exactly one applicable approved revision → use it; record file_id + SHA-256 | 03 row 1 | MUST | FULL | basis=SINGLE_APPROVED |
| ING-48 | A new revision explicitly replacing an old one → keep the old for audit, exclude it from the reference | 03 row 2 | MUST | FULL | basis=EXPLICIT_CHAIN / SUPERSEDED_STATUS |
| ING-49 | Several revisions without an unambiguous status, a revision conflict, no approval mark or an ambiguous link → CLARIFICATION_REQUIRED; violation conclusion blocked | 03 row 3; §9.1 | MUST | FULL | Reason codes + suggestion |
| ING-50 | A superseded or cancelled revision is **never** the reference (invariant) | §9.1 «Устаревшая редакция не может использоваться как эталон» | MUST | FULL | Property-based tests; DB check |
| ING-51 | Inspector resolves CLARIFICATION: picks the authoritative revision + basis text (+ optional change permit ref) | §9.2 table «Выбрать авторитетную редакцию и зафиксировать основание»; §9.3 Назначение | MUST | FULL | API + dialog; audited; new registry version |
| ING-52 | Stage-specific eligibility: PD = APPROVED; RD = FOR_CONSTRUCTION (or APPROVED, configurable); ИД = APPROVED with a signature present | 03 enums; §5 notes | SHOULD | FULL | Rules table, configurable |
| ING-53 | A newer DRAFT exists → the reference stays on the latest approved revision and a warning DRAFT_NEWER_EXISTS is shown | §9.1 «последняя применимая утверждённая» | SHOULD | FULL | FPR protection |
| ING-54 | Declared successor not uploaded → the old revision is still excluded; group = MISSING_EVIDENCE (CURRENT_REVISION_NOT_UPLOADED) | §9.1; 03 | SHOULD | FULL | Never fall back to a stale reference |
| ING-55 | Sheet-scope revisions (sheets re-issued as «Зам./Нов./Аннул.») resolved per sheet | ГОСТ Р 21.101 practice; pilot «Ведомость изменений» pages | SHOULD | SIMPLIFIED | Only when the registry declares `revision_scope=SHEETS`; otherwise document level |

### F. Linkage of comparable current documents

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-56 | Linkage groups of comparable current documents across ПД/РД/ИД (object + discipline family + scope + code) | §9.1 Назначение; §7 m2 «Связка актуальных редакций» | MUST | FULL | `linkage_groups` + reference selections per stage |
| ING-57 | §6 mapping (matrix section ↔ ПД section ↔ РД марки ↔ ИД documents) as a data table | §6 | MUST | FULL | Seed `discipline_map` (§3.12) |
| ING-58 | ИД ↔ РД linkage via the referenced RD code in the ИД stamp/act and via the ИД doc type | §5; §6 | SHOULD | SIMPLIFIED | Registry column `related_document_code` + stamp hint |
| ING-59 | Sheet index (sheet title, floor/elevation, section, axes, drawing type) with baseline sheet-pair hints; unmapped sheets → NOT_COMPARABLE input | 03 row 6 «листы не сопоставлены» | SHOULD | SIMPLIFIED | Titles such as «План 1 этажа. Секция 1.» ↔ «Маркировочный план 1 этажа. Секция 1.» (POL17); B04 owns final pairing |

### G. Completeness and scenario

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-60 | Automatic document-presence control, separate from findings | §1.2; §7 m1; §9.1 «отдельный контроль комплектности»; §9.3 п.1 | MUST | FULL | Own table and screen |
| ING-61 | Upload statuses PD_/RD_/ID_ UPLOADED/PARTIAL/MISSING with defined semantics | §9.1 | MUST | FULL | Definition in §3.11 |
| ING-62 | ПД checklist = ПП 87 sections (§3) incl. ИОС subsections + matrix sections ПОД/ЗУ, with applicability (ТХ for production only; ПОД only with demolition; budget rule; linear objects) | §3; §6 | MUST | FULL | Linear-object list stubbed (ING-85) |
| ING-63 | РД checklist = §4 components (основные комплекты per applicable ПД section, ОД, СО, ведомости; optional сметы/ОЛ/РР/прилагаемые) | §4 | MUST | SIMPLIFIED | Marks derived from the §6 mapping |
| ING-64 | ИД checklist = 13 items of 344/пр (§5) with Приложение 19 sub-items; applicability from present RD disciplines, object profile and construction phase | §5; Прил.19 | MUST | SIMPLIFIED | CORE vs EXPECTED; «по окончании строительства» list from Прил.19 |
| ING-65 | Object applicability profile; NOT_APPLICABLE always carries a basis (auto rule text or inspector comment) | 03 row 5 «NOT_APPLICABLE с обязательным основанием» | MUST | FULL | Profile form + rules |
| ING-66 | A missing required document → MISSING_EVIDENCE, shown in completeness, **not counted as a violation** | 03 row 4; §9.2 alg.3 | MUST | FULL | |
| ING-67 | Unreadable file or unmapped sheets → NOT_COMPARABLE with a replacement request | 03 row 6 | MUST | FULL | Distinct from intake rejection (see §6 C4) |
| ING-68 | Declared-vs-received: registry rows without an accepted file make the stage PARTIAL («5 из 15 файлов ИД») | §9.2 alg.2 example | MUST | FULL | Counts per stage in the status payload |
| ING-69 | Scenario detection FULL / PD_RD_ONLY / PD_ID_ONLY / RD_ID_ONLY / SINGLE_ONLY / PARTIALLY_LOADED + `scenario_base` | §9.2 alg.2 | MUST | FULL | Truth table in §3.11; shared contract with B04 |
| ING-70 | Data for protocol sections «Статус загрузки документов», «Тип проверки» and table (1) «комплектность и сопоставимость» | §9.2 alg.4 | MUST | FULL | JSON block consumed by B04 |
| ING-71 | Inspector can mark items NOT_APPLICABLE (with basis), request re-upload, and see the list of missing documents | §9.2 table actions «Запросить/дозагрузить», «Подтвердить применимость» | MUST | FULL | Completeness screen |

### H. Incremental upload, process gating, versions

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-72 | Incremental upload into an existing process without re-uploading existing files, until finalisation | §1.2; §9.1 | MUST | FULL | `process_id` in the upload form |
| ING-73 | Gating per the §9.1 table: PENDING yes, PARSING no, READY yes, VERIFYING yes, COMPLETED yes, FINALIZED no | §9.1 | MUST | FULL | 409 with an explicit reason |
| ING-74 | Upload during verification does not reset verification decisions | §9.3 п.3 | MUST | FULL | Contract with B03/B04: decisions persist; delta names the changed references |
| ING-75 | After FINALIZED uploads are impossible; after supervisor/admin un-finalisation (→ VERIFICATION_COMPLETED) they are possible again | §9.3 п.5, «Отмена финализации» | MUST | FULL | Gating reads the current status |
| ING-76 | «Создать новую проверку» for a finalised process, carrying file references forward (no re-upload) | §9.6 «с предложением создать новую проверку» | SHOULD | FULL | `POST /processes/{id}/successor` |
| ING-77 | РиН auto-pull into a finalised process → no check started; the inspector is notified with the new-check option | §9.6 | SHOULD | FULL | Hook in ingestion; transport owned by B06 |
| ING-78 | Delta event after each intake completes (files added, references changed, completeness changes, affected families/doc types) so only affected parameters are recomputed within 1 min | §9.2 «Инкрементальное обновление»; §11 #9 | MUST | FULL | `process.snapshot.updated` |
| ING-79 | Deterministic `input_manifest_hash` (RFC 8785 JCS of the effective registry + selections + versions → SHA-256) | §10 Protocols; §14.2 | MUST | FULL | Aligned with B04 CMP-07; B01 computes, B04 stores |

### I. Processing robustness and NFR

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| ING-80 | Redis cache of parse/meta results keyed by file hash (+ parser version), single-flight lock | §9.1 alg.5 | MUST | FULL | Postgres/fs is the source of truth; Redis only accelerates |
| ING-81 | Processing timeout → up to 2 retries → admin notification; the file becomes NOT_COMPARABLE and the process continues | §9.1 err.5 | MUST | FULL | Deadlines from §11 #2–3; watchdog + DLX retry |
| ING-82 | Async RabbitMQ between the API and the Python workers; durable queues, transactional outbox, DLQ | §1.5 | MUST | FULL | Survives broker/worker restarts |
| ING-83 | User notifications for asynchronous rejections/failures (in-app, via status endpoint + notification feed) | §9.1 err.2 «уведомление пользователя» | MUST | FULL | E-mail/Telegram delivery via monitoring for admins |
| ING-84 | Performance: 10 files (≤ 200 МБ package) uploaded and accepted ≤ 2 min; status/metadata endpoints p95 ≤ 200 ms; 100 concurrent inspectors | §11 #1, #10, #11 | MUST | FULL | Measured (autocannon/k6), reported in the demo |
| ING-85 | Linear objects (п. 3² ПП 87, different section list) | §3 Примечание | NICE | OUT_OF_SCOPE | Template stub + NOT_APPLICABLE basis; no pilot data |
| ING-86 | Cryptographic УКЭП verification (ГОСТ Р 34.10-2012 / CryptoPro chain) | §5 п.1; §12.10 | NICE | OUT_OF_SCOPE | Presence detection only; clearly labelled «подпись не проверена криптографически» |
| ING-87 | XSD validation of Минстрой XML schemas (ПЗ XML, electronic ИД) | §9.1 input XML | NICE | SIMPLIFIED | Namespace detection; XSD only if schemas are supplied |
| ING-88 | Expected АОСР list extracted from RD «Общие данные» (hidden-works list) | §5 п.4 «…указывается в Общих данных» | NICE | OUT_OF_SCOPE | Stretch goal; otherwise inspector-maintained |
| ING-89 | Structured JSON logs (timestamp, level, service, message, request_id, user_id) + ingestion metrics (bytes, rejections by code, AV latency, queue depth, parse/meta durations, cache hit rate) | §13.1, §13.4 | SHOULD | FULL | pino + prom-client |
| ING-90 | Batch ingest CLI (directory + registry → process → wait → export) for hidden-test runs | §14.2 | SHOULD | FULL | Same API, scripted |
| ING-91 | Russian UI texts and error messages; machine-readable error codes (RFC 7807 problem+json) | product; §1.5 | MUST | FULL | Message catalog |

**Totals:** 91 requirements (61 MUST · 23 SHOULD · 7 NICE). FULL 69 · SIMPLIFIED 19 · MOCKED 0 · OUT_OF_SCOPE 3.

---

## 3. Proposed design

### 3.1 Components (modular monolith + Python workers; Docker-ready)

```
 React SPA ──HTTPS──▶ API (Node 22, Fastify, TS) ─── Postgres 16/17 (tables §3.3)
   │ (upload wizard,      │  ingestion module:           │
   │  registry editor,    │   upload-controller          └── file volume /data/store (AES-GCM blobs, write-once)
   │  completeness,       │   intake-pipeline (size/format/hash/AV/fast-structure)
   │  revisions)          │   registry-service (parse/validate/version/draft)
   │                      │   normalizer (шифр/discipline/stage)
   │                      │   revision-resolver, linkage, completeness, scenario
   │                      │   gating (process status), manifest, integrity-job
   │                      │   outbox-publisher ─▶ RabbitMQ ◀─ results-consumer
   │                      └── ClamAV clamd (TCP 3310)
   │                      └── Redis 7 (cache, locks, status snapshots)
 Python 3.12 workers (consume RabbitMQ):
   intake-worker:   deep validation (pikepdf + PyMuPDF), page geometry/classes/DPI, annotations,
                    signature presence, DOCX→PDF rendition (LibreOffice / Gotenberg)
   meta-worker:     title-block extraction (text layer → template; OCR fallback on stamp crops),
                    stamps «В производство работ»/«Выполнено согласно проекту», sheet index
   (parse-worker:   full OCR/NLP/CV extraction — parsing block, same queue conventions)
```

- **Why a Node modular monolith:** one deployable API service keeps transactions (Files + registry + outbox) atomic and meets the p95 target easily. Python is used only where the libraries live (PDF, OCR). Each Python worker is a separate container with its own prefetch and concurrency.
- **Docker path:** services `api`, `web`, `intake-worker`, `meta-worker`, `parse-worker`, `postgres`, `redis`, `rabbitmq`, `clamav`, `gotenberg` (optional) and `proxy` (TLS 1.3). Locally without Docker: Homebrew postgres/redis plus `brew install rabbitmq clamav qpdf` and LibreOffice (see §5 R10).

### 3.2 End-to-end upload flow

1. The client (UI wizard or API) sends `multipart/form-data` with the text fields `object_id`, optional `process_id`, optional `registry_mode`, optional `start_check`, file parts `files[]`, and optional part `registry`.
2. **Pre-read gate.** Check authentication and role. Check the process status for gating (§3.7), taking an advisory lock `pg_advisory_xact_lock(hash(process_id))` for the gating decision and record creation. If `Content-Length` exceeds 200 MiB plus a 2 MiB multipart allowance, reply **413 PACKAGE_TOO_LARGE** immediately, before reading the body.
3. **Streaming** (busboy via @fastify/multipart), one pipeline per file part:
   - a byte counter with a hard stop at 50 MiB (per-file rejection; the remainder of the part is drained);
   - a package-total counter (if it passes 200 MiB: abort, discard all quarantined parts, 413 for the whole package);
   - a SHA-256 hash on the fly;
   - a write to `/data/quarantine/<uuid>` (mode 0600; never served).
4. **Sync checks per file**, in parallel with a limit of 4:
   - `file-type` magic: PDF `%PDF-`, DOCX = ZIP with `[Content_Types].xml` + `word/document.xml`, and not `.docm` (no `vbaProject.bin`) or OLE `.doc`; XML = BOM/`<?xml`/`<` start.
   - Extension ∈ {pdf, docx, xml} and consistent with the content.
   - Fast structure checks. PDF: `startxref` + `%%EOF` within the last 2 KB, or a successful xref-stream load via pdf-lib in `ignoreEncryption:false` mode with a 5 s timeout; encrypted → REJECTED_ENCRYPTED. DOCX: yauzl central directory, total uncompressed size ≤ 500 MB and ratio ≤ 100 (zip-bomb guard). XML: streaming `saxes` parse with DTD rejected (no XXE), 20 s limit.
   - Size > 0.
5. **Antivirus**: clamd `INSTREAM` over TCP with a 60 s timeout. `FOUND` → REJECTED_INFECTED, quarantine shredded, security audit event, `notify.admin`. clamd unavailable → fail-closed: 503 `AV_UNAVAILABLE` for the package, overridable only with `AV_MODE=disabled` in dev (logged loudly).
6. **Registry part**, if present: parse and validate (§3.8) against the accepted files. The result sets `registry_status` for the package.
7. **Promote**: encrypt the blob to `/data/store/sha256/ab/cd/<sha256>.blob`. It is content-addressed; if the blob exists, reuse it. The file is opened with `wx`, chmodded to 0440, and the GCM tag is appended. Insert the `Files` rows (`id` = registry `file_id`, or a generated `<OBJ>-<NNNNNN>`), `process_files`, `upload_packages`, `registry_*`, the outbox messages `ingest.file.stored` and the audit entries, **all in one DB transaction**.
8. **Respond 202** with `process_id`, `package_id`, per-file results, registry validation summary, `process_status` and links. If the upload came into READY/VERIFYING/COMPLETED, the process moves to `PARSING` (incremental; §3.7).
9. **Async.** The intake-worker runs the deep validation (pikepdf open + PyMuPDF page count + render of page 1 at 36 dpi) and computes page geometry. A deep-corrupted file becomes `REJECTED_CORRUPTED`: it is removed from the reference candidates (the blob stays for audit, marked), and a user notification «Файл повреждён… загрузите повторно» is sent. Next the meta-worker extracts stamps (§3.9) and the backend applies registry cross-checks. Then the resolver, linkage, completeness and scenario are recomputed; the manifest is computed; `process.snapshot.updated` is published. In PENDING the full parse is queued only when the check is started. In other states it is queued immediately for the new files.

Timing (§11 #1): localhost streaming of 200 MB takes about 2–4 s, AV about 3–6 s in parallel, deep validation < 1 s/file. This fits well within the 2 min target, which also covers network upload.

### 3.3 Data model (PostgreSQL). ТЗ tables keep their exact names and fields; extra columns and tables are marked +.

**Objects** (§10 #3)

| column | type | notes |
|---|---|---|
| id | varchar(64) PK | stable `object_id` from the registry / надзорное дело. The pilot uses per-building mnemonics (ALT79B, DOO25, SOSH25) |
| name, address, customer, contractor, permit_number | text | ТЗ fields; auto-suggested from stamps (e.g. «г.Москва, Алтуфьевское шоссе д.79Б, стр.1», «Заказчик: АО "ГК "ЕКС"») |
| + code | varchar(12) | `^[A-Z0-9]{2,10}$` mnemonic used for generated file ids |
| + supervision_case_no | text | e.g. «дело №56235» (UNDMS) |
| + parent_case_id | varchar(64) | groups buildings of one complex (DOO25/SOSH25 → «Полярная, 25») |
| + object_kind | enum NON_PRODUCTION / PRODUCTION / LINEAR | applicability |
| + work_type | enum NEW / RECONSTRUCTION / CAPITAL_REPAIR | e.g. ALT79B «Реконструкция» |
| + funding | enum BUDGET / NON_BUDGET / MIXED / UNKNOWN | budget rule (§6 C6) |
| + has_demolition | bool | ПОД applicability (POL16/POL17 «со сносом…») |
| + construction_phase | enum NOT_STARTED / IN_PROGRESS / COMPLETED | ИД applicability (Прил.19 closing list) |
| + profile | jsonb | floors_above, has_underground_parking, has_elevators, has_lift_platforms, has_gas, networks[] … |
| + contacts_enc | bytea | pgcrypto-encrypted ПДн (developer contacts) |
| + created_at, updated_at | timestamptz | |

**Files** (§10 #4). Content columns are immutable (trigger); metadata columns change only by applying a registry version or an inspector decision (audited).

| column | type | notes |
|---|---|---|
| id | varchar(64) PK | **= external `file_id`** (registry or generated `<OBJ>-<NNNNNN>`), globally unique, immutable |
| object_id | FK Objects | immutable |
| doc_stage | enum PD / RD / ID | effective (registry or confirmed draft) |
| discipline | varchar(32) | as declared (e.g. «АР2», «ОВ2.1») |
| + discipline_family | varchar(16) | normalised (AR, KR, IOS4 …) — §3.9 |
| document_code | varchar(128) | as declared (raw, signs preserved) |
| + document_code_key | varchar(128) | match key (NFC, dash/homoglyph unification, no spaces) |
| revision | varchar(32) | as declared |
| + revision_order | int[] | parsed ordering tuple (корректировка, изм., letter) or NULL if not orderable |
| + revision_scope | enum FULL / SHEETS | default FULL |
| approval_status | enum DRAFT / APPROVED / FOR_CONSTRUCTION / SUPERSEDED / CANCELLED / + UNKNOWN | UNKNOWN only when no registry |
| approval_date | date | |
| predecessor_id | varchar(64) FK Files NULL | |
| + successor_id | varchar(64) NULL | may point at a not-yet-uploaded file id |
| file_hash | char(64) | SHA-256 of raw bytes, immutable |
| file_path | text | storage URI `store://sha256/ab/cd/<hash>.blob`, immutable |
| uploaded_at | timestamptz | immutable |
| + file_name | text | original name (sanitised copy kept for display), immutable |
| + mime, size_bytes, ext | | immutable |
| + uploaded_by, package_id, source (UI/API/RIN) | | immutable |
| + sheet_page_range | text | canonical form (§3.8) |
| + signature_status | enum UKEP / UNEP / WET_SCAN / ABSENT / UNKNOWN | declared; `signature_detected` separately |
| + doc_type | varchar(40) | taxonomy code (§3.12), e.g. `PD.AR`, `RD.KZH`, `ID.IGS` |
| + related_document_code | varchar(128) | for ИД: RD шифр the document executes |
| + change_ref | text | e.g. «Разрешение № 35834-25 от 08.2025» (feeds `approved_change_ref`, B04) |
| + intake_status | enum (§1.3) | |
| + rejection_code, rejection_message | | |
| + av_result, av_signature_db | text | |
| + page_count, pdf_version, is_encrypted, has_annotations, has_active_content, content_class_summary | | from the intake-worker |
| + rendition_hash, rendition_path | | DOCX → PDF |
| + meta_extracted | jsonb | stamp aggregate per file (code, stage, sheets, revisions, stamps, confidence) |
| + meta_source | enum REGISTRY / DRAFT_CONFIRMED / EXTRACTED_UNCONFIRMED | |
| + meta_status | enum OK / CLARIFICATION_REQUIRED / NOT_COMPARABLE | + `meta_reason_codes text[]` |
| + duplicate_of | varchar(64) NULL | same hash already in the object (§6 C9) |

Constraints: `UNIQUE(id)`; `CHECK (file_hash ~ '^[0-9a-f]{64}$')`; trigger `files_immutable` raises on UPDATE of (id, object_id, file_hash, file_path, file_name, size_bytes, uploaded_at, uploaded_by, package_id) and on any DELETE (retention purge only through a privileged function that writes an audit record).

**+ File_Pages** (shared with the parsing block; B01 fills geometry and meta)
`file_id, page_index (1-based), mediabox float[4], cropbox float[4], rotate smallint, vis_width_pt, vis_height_pt, width_mm, height_mm, paper_format ('A0','A3x4',…), content_class, text_chars, min_image_dpi, quality_flag (OK/LOW_QUALITY/ABSTAIN), sheet_no text, sheet_title text, floor_hint, section_hint, axes_hint, stamp_bbox_norm float[4], stamp jsonb, stamp_confidence real, stamps_detected text[] ('V_PROIZVODSTVO','VYPOLNENO_SOGLASNO'), overlay_markup bool`. PK (file_id, page_index).

**+ Processes**
`id uuid PK (process_id), object_id, status (§9.1 enum), status_before_parsing, scenario, scenario_base, pd_status, rd_status, id_status, registry_status, registry_version, snapshot_version int, input_manifest_hash char(64), predecessor_process_id, created_by, source, auto_start bool, created_at, updated_at, row_version`.

**+ Process_Files** `process_id, file_id, package_id, included bool, added_at` (a successor process references files without copying them).

**+ Upload_Packages** `id uuid, process_id, seq_no, source, uploaded_by, ip, user_agent, total_bytes, file_count, accepted_count, rejected_count, registry_id, package_status, idempotency_key, created_at`.

**+ Registries** `id, process_id, version, source (UPLOADED_FILE/UI_HELPER/RIN/INSPECTOR_DECISION), format (CSV/XLSX/JSON), mode (FULL/DELTA), raw_sha256, raw_path, status, issues jsonb, created_by, confirmed_by, created_at`.
**+ Registry_Entries** `registry_id, row_no, file_id, fields jsonb (raw), parsed jsonb, row_status (VALID/INVALID/UNMATCHED_NO_FILE/FILE_NOT_IN_REGISTRY), issues jsonb`.
**+ Documents** (logical document = revision family) `id, object_id, doc_stage, discipline_family, document_code_key, doc_type, scope (корпус/секция/этап), title`; Files carry `document_id`.
**+ Revision_Links** `predecessor_file_id, successor_file_id, basis (REGISTRY/INSPECTOR/INFERRED_SUGGESTION), created_by, created_at`.
**+ Linkage_Groups** `id, process_id, object_id, discipline_family, scope, key_hash`.
**+ Reference_Selections** `id, process_id, snapshot_version, linkage_group_id, document_id, doc_stage, selected_file_id NULL, selected_sha256, selected_revision, effective_sheets jsonb, status (COMPLETE/CLARIFICATION_REQUIRED/MISSING_EVIDENCE/NOT_APPLICABLE/NOT_COMPARABLE), basis (SINGLE_APPROVED/EXPLICIT_CHAIN/SUPERSEDED_STATUS/INSPECTOR_DECISION/INFERRED_ORDER), reason_codes text[], candidates jsonb, excluded jsonb [{file_id, reason}], suggestion jsonb, decided_by, decision_comment, algorithm_version, computed_at`. A DB CHECK plus trigger rejects a `selected_file_id` whose approval_status ∈ {SUPERSEDED, CANCELLED} (ING-50 invariant).
**+ Completeness_Templates** `id, template_version, doc_stage, item_code, parent_code, title_ru, normative_ref, level (CORE/EXPECTED/OPTIONAL), applicability jsonb (JSONLogic), match jsonb {doc_types[], discipline_families[]}, is_active` (admin-editable, versioned).
**+ Completeness_Items** `id, process_id, snapshot_version, template_item_id, status (PRESENT/MISSING_EVIDENCE/DECLARED_NOT_RECEIVED/NOT_APPLICABLE/CLARIFICATION_REQUIRED/NOT_COMPARABLE), matched_file_ids text[], basis text (mandatory for NOT_APPLICABLE), set_by (SYSTEM/user_id), updated_at`.
**+ Processing_Jobs** `id, file_id, job_type (VALIDATE/META/PARSE/RENDITION), attempt, status (QUEUED/RUNNING/DONE/FAILED/TIMEOUT/DEAD), deadline_at, started_at, finished_at, worker_id, error_code, cache_hit bool`.
**+ Outbox** `id, exchange, routing_key, payload jsonb, headers jsonb, created_at, published_at` (transactional outbox, publisher confirms).
**+ Notifications** `id, recipient_user_id / recipient_role, process_id, type, payload, created_at, read_at`.
**+ Discipline_Map, Doc_Types, Code_Dictionary**: seed data (§3.12).

Shared (written, not owned): **Audit_Log** (§10 #12), **Monitoring_Metrics** (§10 #13). Read by B04: **Checks.completeness_status**, which B04 fills per parameter using our selections and items.

### 3.4 File intake state machine

```
RECEIVED ──size>50MiB──▶ REJECTED_SIZE
   │──bad magic/ext────▶ REJECTED_FORMAT | REJECTED_MISMATCH
   │──0 bytes──────────▶ REJECTED_EMPTY
   │──fast-structure───▶ REJECTED_CORRUPTED | REJECTED_ENCRYPTED
   │──AV FOUND─────────▶ REJECTED_INFECTED
   ▼
STORED ──deep validation fail──▶ REJECTED_CORRUPTED (async; notify user)
   │──timeout×3─────────────────▶ FAILED_TIMEOUT (NOT_COMPARABLE; notify admin)
   ▼
VALIDATED ──meta extraction──▶ META_EXTRACTED ──(check started)──▶ PARSE_QUEUED → PARSED | FAILED_TIMEOUT
```
Only `STORED` and later states create a `Files` record that counts as "accepted". Sync rejections create no `Files` row; they are logged with hash, name, reason and user in `Audit_Log` and returned in the response. Async rejections keep the row with `intake_status=REJECTED_*` and exclude it from every computation.

### 3.5 REST endpoints (OpenAPI 3.0, `/api/v1`, RFC 7807 errors with `code` + `message_ru`)

| Method & path | Purpose | Request → Response (sketch) |
|---|---|---|
| `POST /documents/upload` | ТЗ endpoint. New process or incremental upload | multipart: `object_id` (req. unless registry has one), `process_id?`, `registry?` (file), `registry_mode? FULL/DELTA`, `start_check? bool` (API default true, UI false), `files[]` (1..1000). Header `Idempotency-Key?`. **202** `{process_id, package_id, object_id, process_status, package_status, registry:{status, version, errors:[{row, field, code, message_ru}], warnings:[…]}, files:[{client_name, file_id?, sha256?, size, intake_status, error?:{code,message_ru,limit?}}], links:{status, completeness, registry}}`. **413** PACKAGE_TOO_LARGE `{limit_bytes:209715200, actual_bytes}`. **409** UPLOAD_NOT_ALLOWED `{process_status, reason_ru, retry_after_s?, actions:["CREATE_SUCCESSOR"]}`. **422** NO_ACCEPTED_FILES (all rejected; no process created). **503** AV_UNAVAILABLE |
| `GET /processes/{id}/status` | Monitoring endpoint (§1.4). Served from a Redis snapshot, p95 target ≤ 50 ms | `{process_id, object_id, status, allowed_actions:{upload, start_check, verify, finalize}, upload_statuses:{pd:{status, accepted, rejected, declared, declared_not_received, core_missing}, rd:{…}, id:{…}}, scenario, scenario_base, registry_status, jobs:{queued, running, failed, timeout}, snapshot_version, input_manifest_hash, protocol:{latest_version, status}}` |
| `POST /processes/{id}/start` | Start the check from PENDING (→ PARSING) | 202; 409 if not PENDING or no accepted files |
| `GET /processes/{id}/files` | Effective registry view with intake/meta/selection status per file | paginated rows (all registry fields + provenance) |
| `GET /files/{file_id}` | File metadata + pages summary | |
| `GET /files/{file_id}/content` | Download the original (decrypted); audited; inspector/admin only | binary; `Digest: sha-256=…` |
| `GET /files/{file_id}/pages/{n}/stamp.png` | Stamp crop for the registry helper (rendered by the intake-worker, cached) | image |
| `GET /registry/template?format=csv\|xlsx\|json` | Templates (XLSX with dropdown validation) | file |
| `GET /registry/schema` | JSON Schema of the JSON registry | JSON |
| `POST /registry/validate` | Dry-run validation, optionally against `process_id` | `{status, errors, warnings, rows}` |
| `GET /processes/{id}/registry` | Current version + history | |
| `GET /processes/{id}/registry/draft` | Auto-filled draft from stamps/filenames (per cell: value, source, confidence, page) | |
| `POST /processes/{id}/registry` | Submit a new version (file upload, or JSON rows from the helper with `confirm=true`) | new version + validation; triggers recompute |
| `GET /processes/{id}/registry/export?format=` | Effective input registry for the protocol annex / РиН | file |
| `GET /processes/{id}/completeness` | Stage statuses, scenario, checklist tree with items and matched files | |
| `PATCH /processes/{id}/completeness/items/{item_id}` | Inspector: `{status:"NOT_APPLICABLE", basis}` or revert | audited; recompute |
| `GET /processes/{id}/revisions` | Linkage groups with per-stage selections, candidates, excluded, reasons, suggestion | |
| `POST /processes/{id}/revisions/{selection_id}/decision` | Inspector picks the authoritative file: `{file_id, basis_ru, change_ref?}` | audited; writes Revision_Links + a new registry version (source INSPECTOR_DECISION); recompute |
| `POST /processes/{id}/successor` | «Создать новую проверку» from a FINALIZED process; carries file references | 201 `{process_id}` |
| `GET/POST /objects`, `GET/PATCH /objects/{id}` | Object passport incl. applicability profile | |
| `POST /admin/storage/integrity-check` | Run the integrity check now (admin) | 202 + report id |
| `GET /admin/completeness-templates`, `PUT …/{id}` | Template admin (versioned) | |

Internal endpoints for the workers are not needed; they read blobs through the shared storage library (Node and Python implementations of the same blob format).

### 3.6 RabbitMQ topology and messages

Common envelope: `{message_id (uuid), schema: "<name>/v1", produced_at, request_id, process_id, attempt, payload}`. Messages are persistent, the publisher uses confirms, and all messages go through the outbox.

| Exchange (topic) | Routing key | Consumer queue | Payload (sketch) |
|---|---|---|---|
| `ii.ingest` | `ingest.file.stored` | `q.intake.validate` (intake-worker, prefetch 2) | `{file_id, sha256, storage_uri, mime, size, enc:"AES256GCM-v1", deadline_at}` |
| `ii.ingest` | `intake.file.validated` / `intake.file.rejected` | `q.api.intake-results` | `{file_id, page_count, pdf_version, is_encrypted, has_annotations, has_active_content, signatures:[{type:"PDF_SIG"\|"XMLDSIG", signer_hint?}], pages:[{page_index, mediabox, cropbox, rotate, vis_w, vis_h, mm_w, mm_h, paper_format, content_class, text_chars, min_image_dpi, quality_flag}], rendition?:{sha256, uri, page_count}}` or `{file_id, code:"CORRUPTED"\|"ENCRYPTED"\|"EMPTY", detail}` |
| `ii.ingest` | `meta.file.requested` | `q.meta` (meta-worker, high priority) | `{file_id, sha256, storage_uri, pages_to_scan:"all"\|[..], titleblock_version}` |
| `ii.ingest` | `meta.file.extracted` | `q.api.meta-results` | `{file_id, titleblock_version, pages:[{page_index, stamp:{code:{raw, conf, bbox}, stage:{raw, conf}, sheet:{raw, conf}, sheets_total, revisions:[{izm, kind:"Зам."\|"Нов."\|"Аннул."\|"Изм.", doc_no, date}], sheet_title, org, dates[], korrektirovka?}, stamps_detected[], overlay_markup}], file_aggregate:{code_raw, stage, discipline_family, revision_guess, approval_hint, sheet_page_map}}` |
| `ii.parse` | `parse.file.requested` | `q.parse` (parsing block) | `{file_id, sha256, storage_uri, pages_meta_ref, scenario_base, extraction_profile, deadline_at}` |
| `ii.parse` | `parse.file.completed` / `.failed` | `q.api.parse-results` | owned by the parsing block; B01 tracks job state + cache |
| `ii.process` | `process.snapshot.updated` | `q.comparison.incremental` (B04), `q.ws.gateway` | §3.13 delta |
| `ii.process` | `process.status.changed` | `q.ws.gateway`, dashboard | `{from, to, by}` |
| `ii.notify` | `notify.user` / `notify.admin` | notification service (B07/monitoring) | `{type: FILE_REJECTED_CORRUPTED\|REGISTRY_INVALID\|PARSE_TIMEOUT\|AV_INFECTED\|INTEGRITY_MISMATCH\|NEW_DOCS_AFTER_FINALIZATION, …}` |
| `ii.retry` (DLX) | `retry.<queue>` | TTL queues `q.retry.30s`, `q.retry.120s` → back to origin | on failure/timeout with attempt < 3 |
| `ii.dead` | `#` | `q.dead` | after attempt 3 → admin alert |

**Timeouts and retries (ING-81).**
- Deadlines: validate 60 s; meta 30 s + 2 s/page (max 10 min); parse 60 s + 1.2 s/page, capped at 11 min (100 pages ≈ 3 min, 500 pages ≈ 11 min, aligned with §11 #2–3 and their tolerance).
- Enforcement is double. The worker runs each job in a child process and hard-kills it at the deadline, then publishes `failed{TIMEOUT}`. The API-side watchdog (every 15 s) marks `RUNNING` jobs past `deadline_at + 30 s` as TIMEOUT, which covers worker crashes.
- «до 2 раз» is read as 2 retries (3 attempts). After the third failure: `FAILED_TIMEOUT`, the file's selection becomes NOT_COMPARABLE (reason PROCESSING_TIMEOUT), `notify.admin`, and the process continues without the file.
- RabbitMQ `consumer_timeout` is set to 15 min.

### 3.7 Process status gating (ING-73…77)

| Process status (§9.1) | Upload allowed | B01 behaviour on upload |
|---|---|---|
| PENDING | yes | intake + meta run; full parse waits for `start` (or `start_check=true`) |
| PARSING | **no** | 409 `UPLOAD_NOT_ALLOWED` «Дозагрузка недоступна: выполняется парсинг документов. Повторите после его завершения.» + `retry_after_s`. The UI may hold the files and resubmit automatically (client-side only) |
| READY | yes | status → PARSING (`status_before_parsing=READY`); incremental parse of new files only; B04 returns the process to READY after the protocol update |
| VERIFYING | yes | → PARSING (`status_before_parsing=VERIFYING`); decisions are untouched (§9.3 п.3); B04/B03 restore VERIFYING |
| COMPLETED (= VERIFICATION_COMPLETED) | yes | → PARSING; if new candidates appear, B03 moves to VERIFYING, otherwise back to COMPLETED |
| FINALIZED (= PROTOCOL_FINALIZED) | **no** | 409 with action `CREATE_SUCCESSOR`. A РиН auto-pull stores nothing into the process; it sends `notify.user NEW_DOCS_AFTER_FINALIZATION` with the files parked on the object, so the offer «создать новую проверку» can attach them |
| (un-finalised → COMPLETED) | yes | as COMPLETED |

Transition ownership (to be ratified by the architecture pass): B01 sets `PENDING` (creation) and `→PARSING` (accepted upload or start). B04 sets `→READY` or restores `status_before_parsing`. B03 sets VERIFYING, COMPLETED, FINALIZED and un-finalisation. All go through one `ProcessStateMachine` service with optimistic locking (`row_version`) and a transition audit.

Inspector decisions on revisions and N/A marks also trigger a recompute and a delta. They do not change the process status because no parsing is needed; B04 recomputes the affected parameters within §11 #9.

### 3.8 Registry specification

**Formats.**
- CSV: UTF-8 with or without BOM (cp1251 detected and converted, with a warning). Delimiter auto-detected `;` or `,` (Excel-RU default `;`). Header row required.
- XLSX: sheet named «Реестр», otherwise the first sheet, header in row 1.
- JSON: `{"registry_format":"ii-registry/1.0","object_id":"…","mode":"FULL|DELTA","files":[{…}]}`.
- Header aliases: `шифр`→document_code, `стадия`→doc_stage, `марка`/`раздел`→discipline, `изм`/`редакция`→revision, `статус`→approval_status, `дата утверждения`→approval_date, `листы/страницы`→sheet_page_range, `sha256`/`sha-256`/`хеш`→sha256, etc. Case- and space-insensitive.

**Columns.** Required columns come from the ТЗ; optional ones are extensions (*ext*).

| column | req | type / rule |
|---|---|---|
| object_id | ✔ | `^[A-Za-z0-9._-]{1,64}$`; must equal the process object |
| file_id | ✔ | `^[A-Za-z0-9._-]{1,64}$`; unique in the registry and globally; if it exists with a different hash → error FILE_ID_IMMUTABLE |
| file_name | ✔ | must match an uploaded part (NFC, case-insensitive) *or* be matched by sha256 (name mismatch = warning) |
| sha256 | ✔ | 64 hex, case-insensitive; must equal the computed hash, else error REGISTRY_HASH_MISMATCH (file → CLARIFICATION_REQUIRED) |
| doc_stage | ✔ | PD / RD / ID (aliases ПД/РД/ИД, П/Р) |
| discipline | ✔ | free text; normalised to `discipline_family`; unknown family → warning |
| document_code | ✔ | stored raw; `document_code_key` derived |
| revision | ✔ | free text («0», «1», «Изм.2», «Корр.2/Изм.1», «A»); orderability parsed |
| approval_status | ✔ | DRAFT / APPROVED / FOR_CONSTRUCTION / SUPERSEDED / CANCELLED; FOR_CONSTRUCTION only with RD (else error) |
| approval_date | ✔ (except DRAFT) | ISO `YYYY-MM-DD` or `ДД.ММ.ГГГГ`; not in the future (warning) |
| sheet_page_range | ✔ | grammar below; pages ≤ page_count |
| predecessor_id | – | existing file_id (registry, DB, or declared in the same registry); no cycles |
| successor_id | – | may reference a not-uploaded file (then the current revision is "declared, not received") |
| signature_status | ✔ | UKEP / UNEP / WET_SCAN / ABSENT (aliases УКЭП/УНЭП/скан/нет); required for ИД, recommended for others |
| doc_type | *ext* | taxonomy code (§3.12); inferred if missing (flagged) |
| revision_scope | *ext* | FULL / SHEETS |
| related_document_code | *ext* | ИД → RD шифр |
| change_ref | *ext* | approved change / «Разрешение на внесение изменений» ref |
| scope | *ext* | корпус/секция/этап (e.g. «корпус 9», «этап 12») |
| applicability / not_applicable_reason | *ext* | declares a checklist item N/A with basis |
| title | *ext* | document title |

**`sheet_page_range` grammar.**
- Canonical machine form: `S[-S]:P[-P](,S[-S]:P[-P])*`, for example `1-7:13-19,8:21`.
- A sheet token may be alphanumeric (`3а`, `1.1`, `ОД1`). A sheet range must map to a page range of equal length when both sides are numeric.
- The short form `P[-P]` (pages only) means that sheet numbers are taken from the stamps, or "sheet = page" if no stamps are found (flag `SHEETS_ASSUMED`).
- The human form «л.1-7=с.13-19; л.8=с.21» is also accepted. JSON may use `[{"sheet":"3","page":19}]`.
- Example from the pilot: ALT79B-000015 → `3-4:19-20` (plus the other pages).

**Validation outcomes.**
- *Row errors* → the row is INVALID → the matched file gets `meta_status=CLARIFICATION_REQUIRED` (reason REGISTRY_ROW_INVALID).
- *Uploaded file without a row* → CLARIFICATION_REQUIRED (REGISTRY_ROW_MISSING).
- *Row without an uploaded file*, status not in {SUPERSEDED, CANCELLED} → DECLARED_NOT_RECEIVED, which feeds PARTIAL.
- *No registry* → package CLARIFICATION_REQUIRED, and every file of the package is CLARIFICATION_REQUIRED (REGISTRY_MISSING) until a registry version is confirmed.
- *Registry object_id ≠ process object* → package-level error; the registry is rejected and the files are kept as REGISTRY_MISSING.

**Versioning.** Each submission becomes an immutable `Registries` row plus the stored raw file with its SHA-256. DELTA merges by `file_id`; a metadata change of an existing row (e.g. an old file → SUPERSEDED) is allowed and audited. The effective registry = fold of versions. `registry_version` is part of the manifest.

**UI helper («Мастер реестра»), ING-30.**
- Available right after upload.
- Pre-fills each row from: `file_id` (keep the id-like filename, e.g. `ALT79B-000015.pdf`, otherwise generate), `file_name`, `sha256` (locked), `doc_stage` (stamp «Стадия» П/Р/ИС → PD/RD/ID; code markers `П-`, `-П-`, `РД-`, `-Р-`; ИД title words «Исполнительная схема», «Акт освидетельствования»), `discipline` + `document_code` (stamp graph 1), `revision` (max Изм. number from the stamp revision rows; «Корректировка №N» from the title), `approval_date` suggestion (latest Изм. date or stamp date), `sheet_page_range` (from per-page sheet numbers), `predecessor_id` suggestion (same code key, lower order), `signature_status` suggestion (embedded signature → UKEP?; a scan with blue-ink blobs → WET_SCAN?).
- `approval_status` is suggested only from explicit evidence: «В производство работ» → FOR_CONSTRUCTION; «Аннул.» → CANCELLED. Otherwise the cell stays empty and must be chosen.
- Every cell shows provenance (e.g. «штамп, стр. 19, уверенность 0,93») and a stamp thumbnail.
- «Подтвердить реестр» saves version N with `source=UI_HELPER, confirmed_by=user`.

### 3.9 Identification: title block, normaliser, classification

**Evidence from the pilot (24 pages, inspected programmatically).**

| pilot p. | evidence ref | stage | шифр in stamp (text layer) | sheet | page class |
|---|---|---|---|---|---|
| 2, 4 | PD ALT79B-000015 p.19, 20 | П | `П-2025-04.266-АР` | 3, 4 | vector+text, A0 |
| 3, 5 | RD ALT79B-000077 p.4, 5 | Р | `РД-2025-04.266-АР` | 2, 3 | raster 150 dpi + text layer, A0 |
| 6 | PD UNDMS-000214 p.16 | П | `59-0222-П-5Э-АР2` | 3 | vector+text, A3 |
| 7 | RD UNDMS-000252 p.10 | Р | `305-0294-5Э-Р-АР 2` (Изм.1 «Зам.» №01-25 12.05.2025) | 5 | vector+text, A3 |
| 8 | RD UNDMS-000252 p.4 | — | change sheet «Разрешение 01-25» | — | A4 (different form) |
| 9 | RD IZM12-000064 p.4 | (visual) Р | `132-0621-ОК-1/Н-4-КЖ02.1` (visual only), blue stamp «В ПРОИЗВОДСТВО РАБОТ» | (visual) | **vector, text as curves** (27,421 paths, 0 text), A0 |
| 10 | ИД IZM12-000007 p.15 | ИС | (not in text layer) «Исполнительная схема… Ремонт свай» | 1 of 1 | vector+text, A4 |
| 11 | PD LOS3A-000009 p.41 | П | `19-0322-ОК-1/Н-АР` | 9 | vector+text, A1 |
| 12 | RD LOS3A-000069 p.15 | Р | `19-0322-ОК-1/Н-1-АР2` | 5 | vector+text, A1 |
| 13 | RD LOS3A-000069 p.8 | — | «Ведомость изменений», «Разрешение 35834-25 08.2025» | — | A4 |
| 14 | ИД OKT103-000099 p.1 | (visual) ИД | (visual; КЖ code of the RD set) | 1 | **raster 200 dpi scan**, handwritten notes, blue stamps |
| 15 | PD POL16-000035 p.62 | П | `130-1222-ОК-1/Н–АР1.ГЧ` (**en dash**) | 11 | vector+text, A3x4 |
| 16 | RD POL16-000136 p.21 | Р | `130-1222-ОК-1/Н-АР2` (Изм.1 «1-Пл-25», Изм.2) | 19 | vector+text, A2 |
| 17 | PD DOO25-000875 p.27 | П | `04-П.СКБ-ПИР-П` + `-АР-ГЧ` (split spans) | 2 | vector+text, A1 |
| 18 | RD DOO25-001733 p.12 | Р | `04-П.СКБ-ПИР-Р` + `-АР1` | 8 | vector+text, A1 |
| 19 | PD SOSH25-003562 p.49 | П | `24-П-ПИР-П-АР` | 46 | vector+text, A3x4 |
| 20 | RD SOSH25-003642 p.34 | Р | `24-П-ПИР-Р-АР1` | 29 | vector+text, A0 |
| 21, 23 | PD POL17-000031 p.26, 27 | П | `133-0820-ОК-1-` (**tail missing from text layer**), «Корректировка №2» | 2, 3 | vector+text, A3x3 |
| 22, 24 | RD POL17-000096 p.7, 8 | Р | `133-0820-ОК-1-АР1` | 5, 6 | vector+text, A3x3 |

Other observations:
- All pages have `Rotate=0` and CropBox = MediaBox. Geometry fixtures must therefore be *synthetic* (rotated and offset pages) to test §9.1 alg.4.
- The expert markup is baked into page content as red text (`#e60000`, TimesNewRoman `AAAAAA+` subset fonts, which differ from the drawing fonts GOST-Common/ISOCPEUR/Arial), plus white Ink annotations. The meta-worker ignores spans in non-drawing overlay fonts inside the stamp zone and flags `overlay_markup`.
- The pilot ids appear nowhere in the pages. Sequence numbers are not ordered by stage (IZM12 ИД 000007 < RD 000064), so the file_id is opaque and must not be parsed for stage.

**Prototype result** (template zone = bottom-right 200×75 mm; the шифр row = largest-font spans 44–62 mm above the frame bottom, concatenated left-to-right):
- шифр exact on **15 of 20** stamped drawing sheets with a text layer.
- 1 contaminated (p12: the customer line «Заказчик: АО "ГК "ЕКС"» shares the row; fixed by using cell borders from vector lines).
- 2 truncated (p21/p23: the tail is drawn as curves; fixed by OCR of the graph-1 cell crop).
- 2 without a usable text layer (p9 curves, p14 scan) need OCR.
- Stage from the anchor «Стадия»: 19/20. Sheet number from the «Лист» anchor: 17/20.
- A regex for «Нов.» false-matched the surname «Новиков», which proves that the Изм. table must be parsed by cell, not by regex on the whole zone.

**Title-block extractor (meta-worker), algorithm.**
1. Locate the frame. Take the inner frame's bottom-right corner from long vector lines (≥ 150 mm) near the page edges. Fallback: page edge − 5 mm. For raster pages, use Hough lines on a 150 dpi render of the bottom-right 250×100 mm.
2. Fit the template. Use ГОСТ Р 21.101-2020 Приложение Ж form 3 (185×55 mm, drawings), forms 4–6 (185×15 mm, following sheets and text documents), and a variant for the change-register form (pilot p8/p13). Fit with ±5 mm tolerance and ±2 % scale. Snap cells to the actual ruling lines when vector lines are present (fixes contamination).
3. Read the cells. From the text layer when `text_chars` in the zone ≥ threshold, joining spans per cell by baseline and x order and keeping the raw glyphs. Otherwise crop each needed cell at 400 dpi and run OCR: Tesseract 5 `rus+eng`, `tessdata_best`, psm 7, whitelist per field (the шифр whitelist = Cyrillic/Latin capitals, digits, `-–./ `). If Tesseract confidence < 70, try the second engine (PaddleOCR ru) when it is installed; otherwise report ABSTAIN.
4. Fields: graph 1 шифр; graph 2 object name; graph 3 sheet title (→ sheet index: floor via «1-го этажа», «отм. 0.000» → 1st floor with a per-object elevation table, section via «Секция 1», axes via «в осях 14-30/А-М»); graph 6 stage; graph 7 sheet; graph 8 sheets total; revision table rows (Изм., Кол.уч., Лист, №док., date, kind Зам./Нов./Аннул.); graph 9 organisation.
5. Stamps: search the whole page (text layer, else OCR of blue-hue connected components, HSV hue 200–250°) for «В ПРОИЗВОДСТВО РАБОТ», «ВЫПОЛНЕНО СОГЛАСНО ПРОЕКТУ», «Изменения внесены», «АННУЛИРОВАН», «ЗАМЕНЁН».
6. Output confidence per field and `bbox_norm` of the stamp (visible-area normalisation, §3.14).

**Normaliser** (a TypeScript library, single source of truth; the Python workers emit raw strings only):
- `code_raw`: exactly as read. Only Unicode NFC and outer whitespace trimming; used for Exact Match and for display.
- `code_match_key`: NFC; dashes U+2010–2015 and U+2212 → `-`; Latin homoglyphs inside Cyrillic tokens → Cyrillic (A/А, B/В, C/С, E/Е, H/Н, K/К, M/М, O/О, P/Р, T/Т, X/Х); all whitespace removed; uppercase. Used only for grouping and matching.
- Tokenise on `[-/. ]`. Discipline = the longest dictionary match among the trailing tokens: АР, АС, КР, КЖ, КЖИ, КМ, КМД, КД, ОВ, ОВиК, ВК, НВК, ЭОМ, ЭМ, ЭО, ЭС, ЭН, СС, СКС, АПС, СОУЭ, ПТ, АУПТ, ГП, ПП, ПЗУ, СПЗУ, ПЗ, ИОС, ТХ, ТМ, ТС, ПОС, ПОД, ООС, ПБ, МПБ, ППМ, ОДИ, ЭЭ, МОЭЭ, ЗУ, СМ, ГСН, ГСВ, … The dictionary is admin-editable.
- The part index is kept (АР1, АР2 → family AR, part 1/2; КЖ02.1 → KR/KZH, part 02.1; ОВ2.1 → IOS4, part 2.1). Suffixes `ГЧ`/`ТЧ` (graphic/text part) and `изм.N` are stripped into attributes.
- **ИОС numbering:** `ИОС<n>` = subsection n; `ИОС5.<n>[.<k>]` = section 5, subsection n, book k (the pilot's `АНО/150321/1-П-ИОС5.4.2` = ОВ). This is necessary because the ТЗ and ПП 87 numberings differ (§6 C5).
- **Stage markers:** leading `П-`/`РД-`, infix `-П-`/`-Р-`, `ПИР-П`/`ПИР-Р`. «РП» (рабочий проект) is ambiguous → the registry must decide (flag).
- `revision_order`: parse «Корректировка №N» (PD) and the max «Изм. M» into a tuple `(N, M)`; letters map to their ordinal; unparseable → NULL (not orderable).

**Registry ↔ stamp cross-check (ING-32).** Compare `document_code_key`, `doc_stage` and `sheet_page_range` against the per-page stamps.
- MATCH or NOT_EXTRACTED → OK.
- MISMATCH with confidence ≥ 0.8 → the file is CLARIFICATION_REQUIRED (META_REGISTRY_STAMP_MISMATCH, fields listed).
- MISMATCH with lower confidence → warning only.
- The object address in the stamp versus `Objects.address` → warning META_OBJECT_MISMATCH (catches a file uploaded to the wrong object).

### 3.10 Revision resolver (deterministic, pure function; ING-45…55)

Grouping:
- A **document** = a connected component over accepted files where either (a) the key (object_id, doc_stage, discipline_family, document_code_key) is equal, or (b) the files are connected by predecessor/successor edges (union-find). This handles codes renamed between revisions.
- **Linkage group** = (object_id, discipline_family, scope). It contains documents of all stages (§3.12 maps families across stages).

```
resolve(document D, rules R, decisions I) -> Selection
  F  = accepted files of D (intake_status ∈ {VALIDATED, META_EXTRACTED, PARSED})
  if F = ∅                         -> MISSING_EVIDENCE [DOC_ABSENT]   (only emitted if a checklist/param needs it)
  U  = files with meta_status=NOT_COMPARABLE or FAILED_TIMEOUT
  if F \ U = ∅                     -> NOT_COMPARABLE [FILE_UNREADABLE|PROCESSING_TIMEOUT]
  M  = files with registry problems (REGISTRY_MISSING / ROW_MISSING / ROW_INVALID / HASH_MISMATCH / META_MISMATCH)
  if I has a valid decision for D  -> COMPLETE basis=INSPECTOR_DECISION (valid = made after the latest file of D arrived; else re-open)
  if M ≠ ∅                         -> CLARIFICATION_REQUIRED [reasons of M]   (a registry problem blocks conclusions)
  X  = { f | f.status ∈ {SUPERSEDED, CANCELLED} } ∪ { f | ∃ successor edge f→g, g ∈ D } ∪ { f | f.successor_id declared }
  E  = { f ∈ F\U\X | eligible(stage, f) }        -- PD: APPROVED; RD: FOR_CONSTRUCTION (APPROVED if R.rd_accepts_approved); ID: APPROVED ∧ signature ≠ ABSENT
  if E = ∅:
      if ∃ f∈X with declared successor not uploaded -> MISSING_EVIDENCE [CURRENT_REVISION_NOT_UPLOADED]
      if ∃ f∈F\U\X with status ∈ {UNKNOWN, DRAFT}   -> CLARIFICATION_REQUIRED [NO_APPROVAL_MARK | ONLY_DRAFT]
      if ID with signature ABSENT                   -> CLARIFICATION_REQUIRED [SIGNATURE_MISSING]
  detect cycles/branches in edges over F           -> CLARIFICATION_REQUIRED [CHAIN_CYCLE | CHAIN_BRANCH]
  if |E| = 1 -> COMPLETE basis = (X≠∅ ? EXPLICIT_CHAIN|SUPERSEDED_STATUS : SINGLE_APPROVED)
  else:  -- several approved heads without an explicit link
      s = suggest(E): all revision_order defined, strictly increasing, approval_date non-decreasing in the same order
      if R.mode = INFERRED and s ≠ null -> COMPLETE basis=INFERRED_ORDER (shown with a warning)
      else -> CLARIFICATION_REQUIRED [MULTIPLE_APPROVED_NO_LINK | REVISION_ORDER_CONFLICT], suggestion = s
  warnings: DRAFT_NEWER_EXISTS if ∃ DRAFT with revision_order > selected; SUCCESSOR_DECLARED_NOT_RECEIVED
  if selected has revision_scope FULL and later SHEETS-scope eligible files exist:
      effective_sheets = apply in order: Зам. replaces, Нов. adds, Аннул. removes  (ING-55)
  record: selected file_id + SHA-256 + revision; excluded[] with reasons; candidates[]; algorithm_version
```

Invariants (property tests with fast-check over random registries):
1. The selected file is never SUPERSEDED or CANCELLED and never has an uploaded successor.
2. The result is independent of input ordering.
3. Adding a DRAFT never changes the selection.
4. Adding an explicit successor always moves the selection to it or produces CLARIFICATION, never back to the old file.
5. Every CLARIFICATION carries ≥ 1 reason code.

Linkage completeness per stage (`Reference_Selections` per document) feeds B04 (which checks applicability and completeness first, then compares) and table (1) of the protocol.

### 3.11 Completeness, upload statuses and scenario (ING-60…71)

**Checklist item evaluation** (per process snapshot):
```
for item in templates(stage) where item.is_active:
  if manual override N/A (basis)                  -> NOT_APPLICABLE (basis = inspector text)
  elif not applicability(item, object.profile, present_families, phase)
                                                   -> NOT_APPLICABLE (basis = rule text, e.g. «ТХ: объект непроизводственного назначения (§3 п.6)»)
  docs = documents matching item.match (doc_types / discipline_families), stage-equal
  if docs = ∅: DECLARED_NOT_RECEIVED if a registry row matches, else MISSING_EVIDENCE
  elif all selections(docs) = CLARIFICATION_REQUIRED -> CLARIFICATION_REQUIRED
  elif all selections(docs) = NOT_COMPARABLE         -> NOT_COMPARABLE
  else PRESENT
```

**Upload status per stage X** (loading only; quality issues stay at item level):
- `X_MISSING` ⇔ no accepted (non-rejected) file with doc_stage = X.
- `X_UPLOADED` ⇔ ≥ 1 accepted file **and** no registry row of stage X is DECLARED_NOT_RECEIVED **and** no CORE item of stage X is MISSING_EVIDENCE / DECLARED_NOT_RECEIVED.
- `X_PARTIAL` ⇔ otherwise.

**Scenario** (truth table; names aligned with B04):

| stages not MISSING | any present stage PARTIAL? | scenario_base | scenario |
|---|---|---|---|
| PD, RD, ID | no | FULL | FULL |
| PD, RD | no | PD_RD_ONLY | PD_RD_ONLY |
| PD, ID | no | PD_ID_ONLY | PD_ID_ONLY |
| RD, ID | no | RD_ID_ONLY | RD_ID_ONLY |
| exactly one | no | SINGLE_ONLY | SINGLE_ONLY |
| any of the above | yes | (as above) | PARTIALLY_LOADED |
| none | – | NONE | – (start blocked, 422) |

B04 drives rule sufficiency from `scenario_base`. The protocol prints «Тип проверки: PARTIALLY_LOADED (базовый сценарий: FULL)». Whether CORE normative gaps (not only registry-declared gaps) trigger PARTIALLY_LOADED is decision D8.

**Template seeds (v1).** Every row carries `normative_ref`.

*ПД (ПП 87, §3 plus matrix sections).* CORE: ПЗ, СПЗУ, АР, КР, ИОС1 ЭОМ, ИОС2 ВК-водоснабжение, ИОС3 ВК-канализация, ИОС4 ОВ, ИОС5 СС (each ИОС only if the object has that network), ПОС, ООС, ППМ, БЭ, ОДИ. Conditional:
- ТХ: CORE if PRODUCTION; OPTIONAL otherwise («по требованию заказчика»).
- ПОД: CORE if `has_demolition` (matrix section 7; §6 «в составе ПОС»).
- ЗУ/ЭЭ: EXPECTED (matrix section 11; absent from the §3 table).
- СМ: CORE if BUDGET, else OPTIONAL.
- ИН: OPTIONAL.
- ИОС6 газ: OPTIONAL, if has_gas.
- LINEAR objects: all → NOT_APPLICABLE with basis «линейный объект: перечень п. 3² не поддержан в MVP».

*РД (§4).* For every applicable ПД section with an RD counterpart (§3.12): at least one «основной комплект» of the mapped марки (CORE); «Общие данные» sheet within each комплект (EXPECTED, detected by sheet title «Общие данные»); СО per ГОСТ 21.110 (EXPECTED); ведомости ВО/ВС/ВР (EXPECTED, usually inside ОД); сметы, ОЛ/ГЧ, РР, прилагаемые документы (OPTIONAL; «РР … как правило, не включаются»).

*ИД (344/пр Прил.1 items 1–13 per §5; Приложение 19 sub-items as children).*

| item | App.19 children | level / applicability |
|---|---|---|
| ID.01 Акт освидетельствования ГРО | 3.2 | CORE once phase ≥ IN_PROGRESS |
| ID.02 Акт разбивки осей | 3.1 | CORE (same) |
| ID.03 АОСР | 6.1–6.5.4, 7, 8, 9.1–9.7 | CORE ≥ 1 per applicable RD family (КЖ/АР/ВК/ОВ…) |
| ID.04 Акты освидетельствования строительных (ответственных) конструкций | 10.1–10.6 | CORE if KR applicable |
| ID.05 Акты освидетельствования участков сетей ИТО | 11.1.1–11.1.12, 11.2.1–11.2.7 | CORE per applicable ИОС family |
| ID.06 Замечания застройщика/техзаказчика | – | OPTIONAL (exist only if remarks were made) |
| ID.07 Комплект РД с отметками о соответствии («Выполнено согласно проекту», «В производство работ») | 1 | CORE |
| ID.08 Исполнительные геодезические схемы | 3.3.1–3.3.6 | CORE |
| ID.09 Исполнительные схемы участков сетей ИТО | 4.1–4.9, 5.1–5.8 | CORE per applicable ИОС |
| ID.10 Акты испытания технических устройств и систем ИТО | 12.1–12.3, 14 | EXPECTED |
| ID.11 Результаты экспертиз, обследований, лабораторных испытаний | 13.1–13.10 | EXPECTED |
| ID.12 Документы о качестве материалов | 2 | CORE |
| ID.13 Общий и специальные журналы работ | – | CORE |
| ID.X15 Лифты (акт тех. освидетельствования, декларация ТР ТС 011/2011, паспорт) | 15 | CORE if has_elevators, phase COMPLETED |
| ID.X16 Подъёмные платформы для инвалидов | 16 | CORE if has_lift_platforms, phase COMPLETED |
| ID.OTHER.* Техплан БТИ, ЗОС, Разрешение на ввод, КС-2/КС-3, энергопаспорт, АИС «ОСИГ», РНИС… | – | OPTIONAL (referenced by matrix «Источник в ИД», not ИД per 344/пр; their absence → param-level MISSING_EVIDENCE via B04) |

Phase rule: while `IN_PROGRESS`, the items listed in the closing paragraph of Приложение 19 («При проведении проверки по окончании строительства рекомендуется проверять… 10.4, 10.5, 10.6, 11.1.1 … 13.10, 14, 15, 16») are NOT_APPLICABLE with basis «проверка по окончании строительства». When `COMPLETED` they become EXPECTED.

### 3.12 Doc-type taxonomy and §6 discipline map (seed data, admin-editable)

| family | ПД doc_type | РД doc_types (марки) | ИД doc_types | matrix section (§6) |
|---|---|---|---|---|
| PZ | PD.PZ | RD.OD (ТЭП in ОД) | – | 1 ПЗ |
| SPZU | PD.SPZU | RD.GP (ГП/ПП, благоустройство) | ID.IGS(3.3.6), ID.IS_BLAG, ID.AOSR | 2 СПЗУ |
| AR | PD.AR | RD.AR (АР, АР1, АР2…) | ID.IGS(3.3.4 поэтажные), ID.AOSR, ID.RD_ASBUILT | 3 АР |
| KR | PD.KR | RD.KZH, RD.KM, RD.KMD, RD.KK (КЖ0, КЖ02.1…) | ID.AOSR, ID.AOOK, ID.IGS(3.3.1–3.3.3), ID.JOURNAL_CONCRETE | 4 КР |
| IOS1 | PD.IOS1 | RD.EOM, RD.ES, RD.EM, RD.EO, RD.EN | ID.AOUS(11.1.10, 11.2.6–7), ID.IS_NET(4.5, 5.6), ID.TEST | 5 ИОС1 |
| IOS2 | PD.IOS2 | RD.VK, RD.NV (В1/Т3) | ID.AOUS(11.1.7, 11.2.2), ID.IS_NET(4.1, 5.1) | 5 ИОС2 |
| IOS3 | PD.IOS3 | RD.VK, RD.NK (К1/К2) | ID.AOUS(11.1.5–6, 11.2.3–5), ID.IS_NET(4.2, 4.8, 4.9, 5.2) | 5 ИОС3 |
| IOS4 | PD.IOS4 | RD.OV (ОВ1, ОВ2.1), RD.TS, RD.TM/ИТП, RD.HS | ID.AOUS(11.1.1–4, 11.2.1), ID.IS_NET(4.3, 5.3, 5.4), ID.PASSPORT_VENT | 5 ИОС4 |
| IOS5 | PD.IOS5 | RD.SS, RD.APS, RD.SOUE, RD.SKS | ID.AOUS(11.1.11–12), ID.IS_NET(4.6, 5.7) | 5 ИОС5 |
| IOS6 | PD.IOS6 | RD.GSN, RD.GSV | ID.AOUS(11.1.8), ID.IS_NET(4.4, 5.5) | – |
| TX | PD.TX | RD.TX | ID.TEST(12.1) | – |
| POS | PD.POS | (ППР — not RD; optional) | ID.OZHR, ID.JOURNALS | 6 ПОС |
| POD | PD.POD | (ППР на демонтаж) | ID.SURVEY, ID.IS | 7 ПОД |
| OOS | PD.OOS | (техрегламент) | ID.OTHER.OSIG, ID.OTHER.WASTE | 8 ООС |
| PB | PD.PB | RD.AR/OV/EOM/APS/PT/VPV | ID.PASSPORT_DOORS, ID.TEST_VPV, ID.TEST(12.2), ID.QUALITY | 9 ППМ |
| ODI | PD.ODI | RD.AR, RD.GP | ID.AOSR (пандусы, поручни, тактильная плитка), ID.X16 | 10 ОДИ |
| EE | PD.EE | RD.AR, RD.OV | ID.OTHER.ENERGY_PASSPORT, ID.OTHER.METERS | 11 ЗУ |
| SM | PD.SM | RD.SM | ID.OTHER.KS2, ID.OTHER.KS3 | 12 СМ |
| BE, IN | PD.BE, PD.IN | – | – | – |

B04 uses `matrix section → family/doc_types` to translate a delta into affected parameters. The parsing block uses `doc_type` to pick extraction profiles.

### 3.13 Snapshot, manifest and incremental delta (ING-78, ING-79)

After every intake completion (all files of a package are terminal), registry version, inspector decision or N/A mark:
1. Recompute documents → selections → completeness → stage statuses → scenario. Recomputation is incremental by affected linkage groups, but it is cheap enough (O(n log n) for thousands of files) to recompute fully and diff.
2. Build the **manifest** and serialise it with RFC 8785 (JCS): `{object_id, process_id, registry_version, registry_sha256, templates_version, algorithm_versions:{normalizer, resolver, titleblock, completeness}, files:[sorted by file_id: {file_id, sha256, doc_stage, discipline, document_code, revision, approval_status, approval_date, signature_status, sheet_page_range, role: REFERENCE|EXCLUDED_SUPERSEDED|EXCLUDED_DRAFT|EXCLUDED_CANCELLED|CLARIFICATION|NOT_COMPARABLE|REJECTED}], selections:[sorted: {group_key, stage, document_key, selected_file_id, basis, status}]}`. Then `input_manifest_hash = sha256(JCS bytes)`. B04 stores it in `Protocols.input_manifest_hash`. If B04 CMP-07 prefers hashing only the registry part, the same function is reused with that subset; one implementation lives in a shared package.
3. Publish `process.snapshot.updated`:
```json
{ "process_id": "…", "snapshot_version": 7, "previous_snapshot_version": 6,
  "trigger": "UPLOAD|REGISTRY_UPDATE|INSPECTOR_DECISION|NA_MARK|INTAKE_FAILURE",
  "input_manifest_hash": "…", "scenario": "PARTIALLY_LOADED", "scenario_base": "FULL",
  "upload_statuses": {"pd":"PD_UPLOADED","rd":"RD_UPLOADED","id":"ID_PARTIAL"},
  "delta": {
    "files_added": ["ALT79B-000078"], "files_rejected": [],
    "references_changed": [{"group_key":"ALT79B|AR|-","stage":"RD","document_key":"РД-2025-04.266-АР",
                            "old_file_id":"ALT79B-000077","new_file_id":"ALT79B-000078","reason":"EXPLICIT_CHAIN"}],
    "selection_status_changed": [{"group_key":"…","stage":"RD","old":"COMPLETE","new":"CLARIFICATION_REQUIRED","reasons":["MULTIPLE_APPROVED_NO_LINK"]}],
    "completeness_changed": [{"item_code":"ID.08","old":"MISSING_EVIDENCE","new":"PRESENT"}],
    "affected": {"families":["AR"], "doc_types":["RD.AR"], "stages":["RD"]}
  } }
```
B04 recomputes only the parameters whose sources intersect `affected`, keeps the previous protocol version in history, and flags earlier decisions whose evidence file is no longer the reference («основание изменилось»). This is a B03/B04 policy; B01 guarantees that the old→new mapping is explicit.

### 3.14 Page geometry normalisation (shared contract with parsing/B04)

- Visible rectangle V = CropBox ∩ MediaBox, in PDF user space.
- For a point p in user space: translate by V.origin, rotate by `Rotate` (0/90/180/270, clockwise per the PDF spec) so that the displayed page's top-left is (0,0) with y pointing down, then divide by the displayed width and height.
- The PyMuPDF equivalent is `page.rect` / `page.rotation_matrix`, which the library must use consistently. Bboxes are `[x0,y0,x1,y1]`, clamped to [0,1] and rounded to 4 decimals (the pilot uses 4 decimals). This convention is confirmed in the B04 report against pilot boxes.
- Fixtures: generated PDFs with Rotate 90/180/270 and CropBox offsets, each carrying known marker rectangles. Test: round-trip `norm(denorm(b)) == b`, and IoU ≥ 0.99 for rendered-image detection.

### 3.15 Storage, encryption, integrity (ING-15…19)

- **Blob format v1:** `magic "IIB1" | key_id (1 B) | iv (12 B) | ciphertext | tag (16 B)`, AES-256-GCM. The master key comes from env/secret (`STORE_KEY_<id>`), which allows rotation (key_id). The SHA-256 in the DB is over the *plaintext* (what the registry and organisers hash). The GCM tag also detects tampering.
- The content-addressed path gives deduplication across uploads; `Files` rows stay separate (a new record per upload per 03).
- **Integrity job** runs daily at 03:00 and on demand: stream-decrypt each blob and recompute its SHA-256. On a mismatch or GCM failure: write `Monitoring_Metrics` (`storage_integrity_errors`), `Audit_Log` (severity SECURITY), `notify.admin`, and mark the affected files NOT_COMPARABLE (reason STORAGE_INTEGRITY) until an admin resolves it.
- **Storage adapter interface:** `fs` (MVP) and `s3` (MinIO with Object Lock, later).

### 3.16 UI screens (React; Russian)

1. **«Новая проверка / Загрузка документов».**
   - Object picker (search by address/code) or «Создать объект» with passport fields and the applicability profile. Suggestions come from stamps after the first upload.
   - Drop zone for files and folders. Client-side checks: extension, size ≤ 50 МБ.
   - Automatic splitting into packages of ≤ 200 МБ, uploaded sequentially into the same `process_id`. This is needed because real objects have thousands of files.
   - Registry slot (CSV/XLSX/JSON) with «Скачать шаблон».
   - Per-file progress and result table (status chips + RU error text with limits). A package summary.
2. **«Реестр файлов» (Мастер реестра)** — an editable grid (AG Grid Community or TanStack Table).
   - Every registry column. Auto-filled cells show a provenance icon, a confidence colour and a stamp thumbnail popover.
   - Inline validation (red = error, amber = warning); bulk edit (set stage/object/status for a selection); predecessor picker with a chain preview.
   - «Проверить», «Подтвердить реестр» (creates a version), history/diff between versions, export.
3. **«Комплектность».**
   - Three columns ПД / РД / ИД with PD_/RD_/ID_ status chips and «загружено N из M по реестру».
   - Scenario badge («Тип проверки: … (базовый: …)»).
   - Checklist tree (ПП 87 sections, РД комплекты, ИД items with Приложение 19 sub-items), each with a status chip, matched files and basis.
   - Actions: «Дозагрузить», «Неприменимо…» (basis required), «Запросить замену».
   - Kept visually separate from findings (§9.3 п.1).
4. **«Редакции и связки».**
   - Per linkage group (object + discipline): a stage lane (ПД/РД/ИД), a revision timeline per document (chain arrows), the selected reference (green, with file_id/SHA-256/revision/basis), excluded revisions (grey, reason) and conflicts (amber CLARIFICATION with reason codes).
   - The «Выбрать актуальную редакцию» dialog pre-selects the suggestion; basis text is required; `change_ref` is optional. One click + confirm.
5. **Process header** (shared): status chip, allowed actions driven by `allowed_actions`, a notification bell (rejections, timeouts, «новые документы после финализации — создать новую проверку»).

### 3.17 Libraries (pin exact versions at install; lines current as of 2026)

- **Node 22:**
  - fastify 5 + @fastify/multipart (busboy streaming, per-file limits);
  - ajv 8 + ajv-formats; OpenAPI 3.0 via @fastify/swagger (+ contract tests with openapi-response-validator);
  - file-type (magic), pdf-lib (fast xref check), yauzl (ZIP), saxes (streaming XML, no DTD);
  - csv-parse, exceljs (read/write XLSX + dropdown validation), canonicalize (RFC 8785);
  - amqplib + amqp-connection-manager, ioredis, pg + Kysely (typed SQL) + node-pg-migrate;
  - pino, prom-client, fast-check + vitest.
  - ClamAV client: a custom 60-line INSTREAM implementation (fewer dependencies) or `clamscan`.
- **Python 3.12:** pymupdf ≥ 1.24, pikepdf ≥ 9 (bundles qpdf — deep structural validation without a system qpdf), python-docx, lxml with `resolve_entities=False, no_network=True` (+ defusedxml), opencv-python-headless (lines, blue-ink stamp blobs), pytesseract + Tesseract 5.5 with `rus` from tessdata_best (currently **not installed**), optionally paddleocr (ru), aio-pika, redis, pydantic 2 (message schemas generated from the same JSON Schemas), cryptography (AESGCM).
- **Services:** RabbitMQ 3.13/4.x (management plugin), Redis 7, PostgreSQL 16/17, ClamAV 1.4 (clamd + freshclam), Gotenberg 8 or LibreOffice headless for DOCX → PDF.

---

## 4. Interfaces with other blocks

| Counterpart | B01 consumes | B01 produces | Contract |
|---|---|---|---|
| Parsing / extraction (Module 1 Part B) | `parse.file.completed/failed`; OCR primitives (shared Python lib) | `parse.file.requested` with page metadata; `File_Pages`; Redis cache key convention `parse:{sha256}:{parser_version}`; job deadlines | Same envelope and retry policy; the parser never re-computes geometry; the title-block module lives in the meta-worker (owned by B01's Python implementer) and reuses the parsing block's OCR wrapper |
| **B04** comparison / protocol | `Protocols` (to know the latest version), process status transitions it performs | `process.snapshot.updated` (delta); `Reference_Selections`; `Completeness_Items`; `scenario`/`scenario_base`; upload statuses; `input_manifest_hash`; registry export; `change_ref` hints; stamp flags («В производство работ», «Выполнено согласно проекту», signature presence) for table (1) | B04 never re-resolves revisions; it reads the selection per stage. It sets READY / restores `status_before_parsing`. Enum names follow СХЕМА GOLD / §9.1 |
| **B03** verification | revision decisions and N/A marks made in the verification UI (it may embed B01's dialogs) | revision/completeness APIs; `allowed_actions`; reference-changed info | Decisions persist across uploads; un-finalisation → COMPLETED re-enables upload |
| B06 РиН integration | pulled files + metadata (`source=RIN`) via the internal `ingestPackage()` | `NEW_DOCS_AFTER_FINALIZATION` notification; effective input registry for the РиН payload | Gating identical to the UI; B06 handles transport, УКЭП and retries (1/5/15 min) |
| B07 dashboard / notifications | – | process status, upload statuses, scenario, completeness counts (colour indication inputs); `notify.user/admin` | Dashboard reads `GET /processes/{id}/status` |
| Audit (Module 9) | – | audit events: UPLOAD, UPLOAD_REJECTED, AV_INFECTED, DOWNLOAD, REGISTRY_SUBMITTED, REGISTRY_CONFIRMED, REVISION_DECISION, NA_MARK, PROCESS_SUCCESSOR, INTEGRITY_MISMATCH | `Audit_Log(user_id, action, object_id, details, timestamp, ip_address, user_agent)` |
| Monitoring (Module 11) | – | metrics (`ingest_bytes_total`, `ingest_rejections_total{code}`, `av_scan_seconds`, `intake_job_seconds{type}`, `cache_hit_ratio`, `rabbit_queue_depth` via exporter), JSON logs, `notify.admin` | Prometheus scrape `/metrics`; alert rules owned by monitoring |
| Normative admin (Module 8) | – | Completeness_Templates / discipline dictionary admin screens (could be hosted in the admin UI) | versioned; template version in the manifest |
| Security / auth block | JWT/session, roles | – | Roles: INSPECTOR, SUPERVISOR, ADMIN, ML_ENGINEER, INTEGRATION |

---

## 5. Too complex / risky items and the simplification that still meets the letter

| # | Item | Why it is hard | Simplification that keeps the letter |
|---|---|---|---|
| R1 | Stamp extraction to EM ≥ 0,90 on scans and curve-text pages | 3 page classes; varied stamp layouts; split spans; OCR of CAD fonts (ISOCPEUR/GOST) | Registry-first, so linking does not depend on OCR. Text-layer template extraction (already 15/20 exact in the prototype; cell snapping fixes contamination). OCR **only on small cell crops at 400 dpi** with field whitelists. ABSTAIN when unsure. Human confirmation in the helper. Report EM and coverage honestly |
| R2 | Sheet-scope revisions (Зам./Нов./Аннул. per sheet) | Needs sheet-level identity and the change register | Supported only with a registry `revision_scope=SHEETS` + `sheet_page_range`; otherwise document level. Stamp revision rows are shown as evidence |
| R3 | Full ИД completeness (Приложение 19 ≈ 80 sub-items, work-dependent) | Construction is progressive; the hidden-works list lives in RD «Общие данные» | 13 items of 344/пр with App.19 children; CORE vs EXPECTED; applicability by present RD families, object profile and phase; inspector N/A with basis. ОД extraction is a stretch goal (ING-88) |
| R4 | УКЭП cryptographic validation | GOST algorithms, CryptoPro licence, CA chains | Presence detection (PDF /Sig, XML-DSig) + registry declaration; UI label «подпись не проверена криптографически». No claim of validation |
| R5 | Visual requisites check on scans (signatures, seals, dates, reg. numbers) | CV detection of handwriting/seals is unreliable | Blue-ink / seal blob heuristic (HSV) + date regex in the OCR of the stamp zone → `requisites_hint` with low confidence; the inspector confirms. Flagged in table (1) |
| R6 | Encryption at rest of DB + files | Postgres has no native TDE | App-level AES-256-GCM for blobs (demonstrable); DB on an encrypted volume (documented) + pgcrypto for ПДн columns |
| R7 | DOCX pagination/bbox | DOCX has no fixed pages; LibreOffice pagination ≠ Word | A LibreOffice PDF rendition becomes the canonical paged form, stored with its own SHA-256 and linked to the original; evidence references the rendition page and the original file_id + SHA-256 |
| R8 | XML inputs of unknown schemas | Минстрой publishes many XSDs (ПЗ, ИД) | Well-formedness + safe parse + namespace-based doc_type detection; XPath locators for evidence; XSD validation only when schemas are provided |
| R9 | Thousands of files per object vs the 200 МБ package limit | Pilot sequences up to 003642 | UI auto-chunking into ≤ 200 МБ packages within one process; a registry for thousands of rows; batch CLI; per-package limit applies per request (§6 C1) |
| R10 | Local environment gaps | Docker, RabbitMQ, ClamAV, qpdf and LibreOffice are **not installed**; Tesseract has no `rus` | `brew install rabbitmq clamav` (+ `freshclam`), `brew install --cask libreoffice` (~700 MB) or Gotenberg later in Docker; pikepdf removes the need for system qpdf; download `rus.traineddata` (tessdata_best). ClamAV on arm64 Docker: verify multi-arch image availability, otherwise use a Debian `clamav-daemon` image; clamd needs ~1–1.5 GB RAM |
| R11 | Process-status ownership spans B01/B03/B04 | Race conditions on concurrent uploads and decisions | One `ProcessStateMachine` with optimistic locking + a per-process advisory lock for uploads; transition table in code + tests |
| R12 | Strict vs inferred revision resolution | Too strict → many CLARIFICATIONs; too loose → FPR on stale revisions | STRICT by default (letter), with a pre-computed suggestion so the inspector resolves in 1 click; INFERRED mode as a per-object switch (D2) |

---

## 6. ТЗ contradictions / ambiguities for this block (with recommended interpretation)

| # | Issue | ТЗ refs | Recommendation |
|---|---|---|---|
| C1 | §11 #1 «Загрузка файлов (до 10 файлов по 50 МБ)» = 500 MB contradicts the package limit «Превышен общий лимит загрузки (200 МБ) → Отклонение пакета» | §11 #1 vs §9.1 | Package = one upload request, 200 MiB. The perf test measures 10 files ≤ 200 МБ in one package, and additionally 10×50 МБ as 3 sequential packages into one process (both ≤ 2 min). Limits are configurable |
| C2 | «без него [реестра] пакет принимается со статусом CLARIFICATION_REQUIRED» — CLARIFICATION_REQUIRED is defined as a finding/verification status, not a package status | 03 vs §9.2/§9.3 | Package-level `registry_status=MISSING` → package_status CLARIFICATION_REQUIRED; every file of it is CLARIFICATION_REQUIRED in selection; B04 maps this to CLARIFICATION_REQUIRED for dependent evidence groups; no violation conclusions |
| C3 | Process statuses (§9.1) vs verification statuses (§9.3): COMPLETED vs VERIFICATION_COMPLETED, FINALIZED vs PROTOCOL_FINALIZED; «PENDING» means different things in the two tables; §9.3 is mis-titled as §9.2 | §9.1, §9.3 | Process API uses the §9.1 names; protocol/verification objects use the §9.3 names; documented 1:1 mapping COMPLETED≡VERIFICATION_COMPLETED, FINALIZED≡PROTOCOL_FINALIZED; «PENDING» of a candidate is a separate enum |
| C4 | «Загружен повреждённый PDF → Отклонение» vs «Файл нечитаем или листы не сопоставлены → NOT_COMPARABLE; запросить замену» | §9.1 err. vs 03 row 6 | Structurally broken (cannot be opened, truncated, encrypted) → rejected at intake. Opens but is unusable (blank, illegible, below-quality scan, OCR failure, unmapped sheets, processing timeout) → accepted, NOT_COMPARABLE with a replacement request |
| C5 | §3 lists 13 ПД sections (incl. ТХ, БЭ, ИН) while the matrix uses ПЗ…СМ incl. ПОД and ЗУ and lacks ТХ/БЭ/ИН; ИОС numbering in §3 (ИОС2 and ИОС3 both «ВК», no газ) differs from ПП 87 (ИОС1…ИОС6 incl. газоснабжение); the pilot uses `ИОС5.4.2` (section 5, subsection 4, book 2) | §3, §6, Матрица, пилот | Key everything by section code, not number; completeness template = union with applicability flags; the normaliser understands both `ИОС<n>` and `ИОС5.<n>.<k>` |
| C6 | «Разработка разделов 6, 11, 5 и 9 для объектов, финансируемых из бюджетов, обязательна в полном объёме» uses numbers that, under the §3 table, mean ТХ/ОДИ/ИОС/ППМ, but look like the pre-2022 ПП 87 numbering (5 ИОС, 6 ПОС, 9 ПБ, 11 смета), which matches the matrix's own numbering («Раздел 6. ПОС», «Раздел 12. СМ») | §3 примечание vs Матрица | Implement as a configurable applicability rule keyed by section codes. Default = literal §3 reading (ТХ, ОДИ, ИОС, ППМ become CORE for BUDGET objects); ask organisers. Low impact: these sections are CORE by default anyway except ТХ |
| C7 | Files table (§10) lacks successor_id, sheet_page_range, signature_status, file_name that the registry requires; «file_hash» vs «SHA-256» naming | §10 #4 vs 03 | Files = superset; column names from §10 kept verbatim (`file_hash`), registry names used in the registry/API (`sha256`) with a documented mapping |
| C8 | Who assigns `file_id`: the registry says «file_id… Уникальный идентификатор», Files has `id`; overwrite forbidden «под тем же file_id» | 03, §10 | `Files.id` = registry `file_id` (external, echoed in all outputs, which is critical for GOLD matching); generated `<OBJ>-<NNNNNN>` only without a registry; same id + different hash → 409 |
| C9 | «Повторная загрузка создаёт новую запись и новую версию протокола» — for byte-identical re-uploads this creates noise | 03 | Different bytes → new record + protocol version. Identical bytes → idempotent (upload event audited, response DUPLICATE with the existing file_id, no new protocol version); decision D5 |
| C10 | «Таймаут… Повторная попытка обработки (до 2 раз)»: 2 attempts or 2 retries? | §9.1 | 2 retries (3 attempts), then an admin notification |
| C11 | «Если загружены частично (например, 5 из 15 файлов ИД) → PARTIALLY_LOADED» overlaps with FULL/PD_RD_ONLY/…; where does «15» come from? | §9.2 alg.2 | «15» = registry-declared count (and CORE checklist items). Return `scenario` (PARTIALLY_LOADED when any present stage is PARTIAL) + `scenario_base` (stage combination) |
| C12 | Only PDF/DOCX/XML are accepted, but electronic ИД with УКЭП often comes as XML + detached `.sig/.p7s`; §11 #8 mentions «CV-анализ одного чертежа (DWG)» | §5 п.1, §9.1, §11 #8 | Letter wins: `.sig`, `.dwg`, `.zip`, `.doc` are rejected with the supported-format message. Signature status comes from the registry + embedded signatures. The DWG metric is interpreted as «a drawing (PDF export of DWG)». Decision D4 on companions |
| C13 | DOCX and XML have no «лист/страница» or bbox, yet the evidence card and GOLD require page + bbox | §9.1 alg.4, СХЕМА GOLD | DOCX → PDF rendition (page/bbox on the rendition); XML → `page=null`, `locator={xpath}`; confirm with organisers |
| C14 | Приложение 19 closing paragraph lists «11.2.8», which does not exist (the list ends at 11.2.7) | Прил.19 p.118 | Ignore 11.2.8; log as a source typo |
| C15 | ИД taxonomies differ: §5 = 13 items of 344/пр; Приложение 19 = 16 items with sub-items; the matrix «Источник в ИД» cites non-ИД documents (Техплан БТИ, ЗОС, Разрешение на ввод, КС-2/3, энергопаспорт, АИС «ОСИГ», логи РНИС) | §5, Прил.19, Матрица | Top level = 344/пр items; App.19 = children; non-344 documents = `ID.OTHER.*` (OPTIONAL for stage completeness, but required per parameter → MISSING_EVIDENCE at param level via B04) |
| C16 | approval_status enum has no value for ИД «signed by all parties» or for «approved by экспертиза vs customer»; FOR_CONSTRUCTION only makes sense for RD | 03 | ИД: APPROVED = signed (signature_status ≠ ABSENT); PD: APPROVED = customer-approved / positive экспертиза; FOR_CONSTRUCTION allowed only for RD (validation error otherwise); stamp «РП» → registry must decide |
| C17 | «Сравнивается последняя применимая утверждённая редакция» when a newer DRAFT exists | §9.1 | The latest *approved* revision stays the reference; warning DRAFT_NEWER_EXISTS shown to the inspector |
| C18 | Redis cache «по хешу файла» — results also depend on parser/OCR/matrix/model versions | §9.1 alg.5 | Keys include versions: `parse:{sha256}:{parser_version}`, `meta:{sha256}:{titleblock_version}`; extraction caches (B04/parsing) add matrix/model versions |
| C19 | «PENDING — Документы загружены, проверка не начата» implies an explicit start, but the API flow implies automatic processing | §9.1 | UI: explicit «Запустить проверку» (lets inspectors assemble packages); API/РиН: `start_check=true` by default |
| C20 | 50 МБ / 200 МБ — MB or MiB? | §9.1 | MiB (52 428 800 / 209 715 200 bytes), exact byte limits printed in messages; boundary tests |

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation | Impact |
|---|---|---|---|---|
| D1 | May a registry built with the UI helper (auto-filled from stamps, confirmed by a human) lift CLARIFICATION_REQUIRED? | (a) yes, after explicit confirmation; (b) only an uploaded registry counts | (a). It is still a machine-readable registry, versioned, with `confirmed_by`; approval_status must be chosen by the human | Demo flow and usability; the letter holds |
| D2 | Revision resolution when several approved revisions have no explicit link | (a) STRICT: CLARIFICATION + one-click suggestion; (b) INFERRED: auto-pick when revision order and dates agree; (c) per-object switch | (c) with default STRICT | Balances the «Связка» metric (≥ 0,95) against the stale-revision FPR |
| D3 | Package semantics | (a) 200 МБ per upload request, UI auto-splits large folders into several packages of one process; (b) 200 МБ per process total | (a) | Real objects have thousands of files |
| D4 | Non-listed formats (ZIP, `.sig/.p7s` detached signatures, DWG, DOC) | (a) reject all (letter); (b) accept `.sig/.p7s` only as companions of an XML/PDF (not documents); (c) also ZIP | (a) for MVP; (b) as a later toggle if organisers confirm | ТЗ compliance vs convenience |
| D5 | Byte-identical re-upload | (a) idempotent: audit event, no new record/protocol version; (b) literal: new record + new protocol version every time | (a) | Avoids protocol-version noise; different bytes always create a new record |
| D6 | Object granularity | (a) per building/корпус/этап (as in the pilot: DOO25 vs SOSH25) with an optional `parent_case_id`; (b) per supervision case/complex | (a) | GOLD object_id split; linkage scope |
| D7 | Antivirus engine and policy | (a) ClamAV, fail-closed, EICAR demo; (b) mock in dev only | (a) in compose and locally via Homebrew; (b) only as an explicit dev flag | §12.11 compliance is demonstrable |
| D8 | Do normative CORE gaps (not only registry-declared missing files) make a stage PARTIAL (and the scenario PARTIALLY_LOADED)? | (a) declared-vs-received only; (b) declared + CORE checklist items; (c) configurable | (c) with default (b) | Truthfulness vs the stickiness of PARTIALLY_LOADED; `scenario_base` is always shown |
| D9 | DOCX → PDF rendition tooling | (a) LibreOffice locally (~700 MB) now; (b) Gotenberg container later; (c) no rendition (text-only evidence for DOCX) | (a) now, (b) in Docker | bbox/page for DOCX evidence |
| D10 | Encryption at rest | (a) app-level AES-256-GCM for blobs + encrypted volume for DB; (b) volume encryption only | (a) | Visible §12.3 compliance; ~0.5 day |
| D11 | Check start | (a) explicit «Запустить проверку» in the UI, auto for API/РиН; (b) always automatic | (a) | Matches PENDING semantics |
| D12 | ИД phase handling | (a) object `construction_phase` drives Прил.19 «по окончании строительства» items; (b) ignore phase | (a) | Fewer false MISSING_EVIDENCE rows during construction |

---

## 8. Data needed

| # | What | Why | Fallback if never received |
|---|---|---|---|
| N1 | A real registry sample (CSV/XLSX/JSON) from the organisers: exact column names, enum spellings, whether predecessor/successor are filled, the file_id convention | Registry parser/validator must accept their files verbatim; «Связка» metric depends on it | Our schema with generous header aliases + templates; tolerant enum aliases (ПД/РД/ИД, П/Р, УКЭП…) |
| N2 | Full source files for 1–2 pilot objects (e.g. ALT79B-000015 and ALT79B-000077 complete PDFs) | Realistic sheet↔page maps, stamps, file sizes, processing times | Reconstruct demo files from the 24 pilot pages: each page placed at its original page index (padding pages, so that «ALT79B-000015 стр.19» stays true) + synthetic stamped documents generated with reportlab. Clearly labelled as reconstructed |
| N3 | Examples of XML inputs (which schemas: Минстрой ПЗ XML? electronic ИД/АОСР XML?) and DOCX inputs | Type detection, XPath locators, possible XSD validation | Generic well-formed XML support + a synthetic АОСР XML and a DOCX ПЗ extract |
| N4 | How the hidden test will be fed (API upload per object? directory + registry + SHA-256 manifest?) and whether our output must echo their file_ids | Batch path and id preservation | Batch CLI + API; echo registry file_ids; compute SHA-256 on raw bytes |
| N5 | Приложение № 2 (protocol sample) | Layout of «Статус загрузки документов», «Тип проверки», table (1) columns | Structure from §9.2 alg.4 (as in B04); B01 JSON is layout-agnostic |
| N6 | Object passports: object kind, funding source, demolition, construction phase, elevators/gas | Applicability of ПД/ИД checklist items | Passport form with defaults + suggestions from stamp text («Реконструкция», «со сносом…», «ДОО», «СОШ»); inspector confirms |
| N7 | Conventions for approval evidence per stage in Moscow practice (e.g. what counts as «утверждённая» ПД: экспертиза conclusion no./date; RD «В производство работ» stamp form; ИД signing parties) | Eligibility rules | Configurable rules table (§3.10) defaulting to the registry declaration |
| N8 | Confirmation that 50/200 МБ are MiB and that a package = one request | Boundary behaviour | MiB, per request (C1, C20) |
| N9 | Russian OCR data (tessdata_best `rus`) and permission to install ClamAV/RabbitMQ/LibreOffice locally | Environment | Download/install; otherwise Docker later |
| N10 | Whether external/cloud services are allowed (152-ФЗ) — e.g. cloud OCR/LLM for stamps | Choice of OCR engines | Local only: Tesseract (+ PaddleOCR) |

---

## 9. Jury demo scenario and acceptance tests

### 9.1 Demo (≈ 7 minutes, B01 part)

1. **Happy path with registry.** Create the object «Алтуфьевское ш., 79Б» (ALT79B, «Реконструкция»). Upload the reconstructed ПД АР (`ALT79B-000015`) and РД АР (`ALT79B-000077`) plus `registry.csv`. The 202 response comes back with `process_id`. The file table shows SHA-256, «Антивирус: чисто», and stamp data «П-2025-04.266-АР, стадия П, лист 3 ↔ стр. 19». The completeness panel shows PD_PARTIAL (only АР of the ПП 87 sections), RD_PARTIAL, ID_MISSING, «Тип проверки: PARTIALLY_LOADED (базовый: PD_RD_ONLY)».
2. **Full synthetic object.** Upload a complete synthetic object package: PD_UPLOADED, RD_UPLOADED, ID_PARTIAL («загружено 5 из 15 по реестру»), scenario PARTIALLY_LOADED (base FULL). Upload the missing 10 ИД files **during VERIFYING**: status goes to PARSING and back to VERIFYING, earlier decisions are intact, ID_UPLOADED, scenario FULL. The delta event is shown in the process log; the incremental update finishes in < 1 min.
3. **Negative scenarios live** (one package, five bad files):
   - `.dwg` → «Формат не поддерживается. Допустимые: PDF, DOCX, XML»;
   - 60 МБ PDF → «превышает 50 МБ (52 428 800 байт)»;
   - truncated PDF → «Файл повреждён… загрузите повторно»;
   - EICAR test file → «не прошёл антивирусную проверку», security audit entry, admin Telegram/e-mail mock;
   - password-protected PDF → specific message.
   Then a 210 МБ package → the whole package is rejected with the limit.
4. **No registry.** Upload without a registry: the package shows «CLARIFICATION_REQUIRED — реестр не приложен». Open «Мастер реестра»: rows are pre-filled from stamps with provenance thumbnails, and approval_status is empty. The inspector sets the statuses, confirms, and the CLARIFICATION clears.
5. **Revision conflict.** Add RD АР «Изм. 2» as APPROVED without a predecessor link. The group turns amber: CLARIFICATION_REQUIRED «две утверждённые редакции без связи», with a suggestion. One click picks «Изм. 2» with basis «Разрешение № 35834-25». «Изм. 1» is shown greyed «исключена из эталонного сравнения, сохранена для аудита». Audit shows who, when and why.
6. **Immutability and integrity.** Re-upload different bytes under `ALT79B-000077` → 409 «Перезапись файла под тем же file_id запрещена». Upload the corrected file as `ALT79B-000078` with `predecessor_id=ALT79B-000077` → new record + new protocol version. Admin runs «Проверка целостности» after one byte of a blob was altered on disk → mismatch detected, alert, file marked NOT_COMPARABLE.
7. **Gating.** An upload during PARSING → 409 with an explanation. After «Завершить» (FINALIZED) → 409 + the button «Создать новую проверку» (files carried over, no re-upload). A supervisor un-finalises → upload allowed again.
8. **Robustness.** Fault injection makes the parser hang: 2 retries, then an admin notification; the file becomes NOT_COMPARABLE and the rest of the process continues. Re-upload the same file into a new check: the Redis cache hit is shown (0 s parse).

### 9.2 Acceptance tests (automated; mapped to requirements)

| Test | Proves | Pass criterion |
|---|---|---|
| T-API-01 OpenAPI contract tests for every ingestion endpoint (requests + responses) | ING-01…03 | 100 % schema-valid; invalid form fields → 400 problem+json |
| T-NEG-01…12 fixtures: dwg, doc, docm, zip, 0-byte, 50 MiB exact / +1 byte, 200 MiB package exact / +1, truncated PDF, garbage PDF header, encrypted PDF, XXE XML, zip-bomb DOCX, EICAR, `.pdf` with DOCX content | ING-04…12 | Exact code + RU message; no `Files` row for sync rejections; audit entry; package rule respected |
| T-HASH-01 SHA-256 equals `shasum -a 256` for 50 files incl. 50 MiB | ING-13 | 100 % |
| T-IMM-01 overwrite attempts (API, SQL UPDATE, storage re-write) | ING-15…16 | All refused (409 / trigger error / EEXIST) |
| T-REG-01…20 registry validation matrix (each rule, CSV `;`/`,`, BOM, cp1251, XLSX, JSON, aliases, DELTA merge) | ING-25…31 | Expected errors/warnings per row |
| T-REV-01…25 resolver table-driven cases: single approved; explicit chain; SUPERSEDED status; two approved no link; cycle; branch; only DRAFT; UNKNOWN; newer DRAFT; declared successor missing; ИД without signature; registry–stamp mismatch; inspector decision then new file; SHEETS scope | ING-45…55 | Expected status/basis/reasons; **invariant: 0 selections of SUPERSEDED/CANCELLED** |
| T-REV-PBT fast-check property tests (10 000 random registries) | ING-50 | Invariants §3.10 hold |
| T-LINK-01 linkage on pilot-like codes (ALT79B, UNDMS different bases, LOS3A, POL16 en dash, DOO25 split spans) | ING-38, ING-56 | Correct family/group for all; «Связка» accuracy on the synthetic hidden-like set ≥ 0,95 (target 1,0) |
| T-TB-01 stamp extractor on the 24 pilot pages vs a hand-made gold JSON (шифр, стадия, лист) | ING-36 | Report EM per field + coverage; target on text-layer sheets ≥ 0,90 EM, ABSTAIN (not wrong) on unreadable ones |
| T-GEO-01 synthetic PDFs with Rotate 90/180/270 + CropBox offsets | ING-41 | IoU ≥ 0,99 round-trip |
| T-CMP-01…15 completeness/scenario truth table incl. «5 из 15», N/A with basis, phase rule, budget rule | ING-60…71 | Exact statuses; NOT_APPLICABLE never without basis |
| T-GATE-01 upload in each process status + un-finalisation + РиН auto-pull when finalised | ING-72…77 | Matches the §9.1 table; notification emitted |
| T-DELTA-01 delta event content after upload / decision / N/A | ING-78 | Only affected families listed; manifest hash changes iff inputs change; the same inputs give the same hash |
| T-ROB-01 timeout injection, worker kill, broker restart, Redis down | ING-80…83 | 3 attempts then admin notify; no lost jobs (outbox); cache bypass works |
| T-PERF-01 10 files / 200 МБ upload; 10×50 МБ in 3 packages; status endpoint 100 VU | ING-84 | ≤ 2 min; p95 ≤ 200 ms (target ≤ 50 ms) |
| T-INT-01 integrity job with a tampered blob | ING-19 | Detected, alerted, audited |

---

## 10. Work breakdown

Implementation agents (proposed): **ING-BE** (Node backend, ingestion module), **ING-PY** (Python intake/meta workers), **FE** (React), **OPS** (compose/infra), **QA** (fixtures/tests). Coordination with B04 (comparison), B03 (verification), the parsing block, B06 (РиН), audit and monitoring.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| W01 | OpenAPI 3.0 spec for ingestion endpoints + JSON Schemas (registry JSON, messages, status/completeness/revisions payloads); shared enums package (TS + generated pydantic) | S | – | ING-BE |
| W02 | DB migrations: Objects, Files (+immutability trigger), File_Pages, Processes, Process_Files, Upload_Packages, Registries, Registry_Entries, Documents, Revision_Links, Linkage_Groups, Reference_Selections (+invariant trigger), Completeness_Templates/Items, Processing_Jobs, Outbox, Notifications | M | W01 | ING-BE |
| W03 | Upload endpoint: streaming multipart, 50/200 MiB limits, magic/ext checks, SHA-256, quarantine, fast structure checks (PDF/DOCX/XML incl. XXE/zip-bomb), per-file results, idempotency key, advisory lock, RU error catalog | M | W02 | ING-BE |
| W04 | ClamAV INSTREAM client, fail-closed policy, EICAR test, security audit + admin notify | S | W03, W13 | ING-BE |
| W05 | Blob store: content-addressed write-once fs adapter, AES-256-GCM format v1 (Node + Python readers), daily/on-demand integrity job | S | W03 | ING-BE (+ING-PY reader) |
| W06 | Registry service: CSV/XLSX/JSON parsing, header aliases, row/cross-row/cross-file validation, versions FULL/DELTA, templates (XLSX dropdowns), export | M | W02 | ING-BE |
| W07 | Normaliser library (code_raw/match key, discipline dictionary incl. ИОС numbering, stage markers, revision order) + test corpus from all pilot codes | S | – | ING-BE |
| W08 | Revision resolver + documents/union-find + reason codes + suggestions + SHEETS scope; table-driven + property-based tests | L | W06, W07 | ING-BE |
| W09 | Linkage groups, discipline_map/doc_types seed (§3.12), ИД related-code linking, sheet index + baseline pair hints | M | W07, W08, W15 | ING-BE |
| W10 | Completeness engine: template seeds (ПП 87, §4, 344/пр + Прил.19 + phase rule), JSONLogic applicability, declared-vs-received, stage statuses, scenario + scenario_base, N/A API | M | W08, W09 | ING-BE |
| W11 | Process state machine + gating + successor process + un-finalise hook + РиН auto-pull hook; snapshot recompute, manifest (JCS) and `process.snapshot.updated` delta | M | W02, W10 | ING-BE (ratify with B03/B04) |
| W12 | RabbitMQ topology, outbox publisher, result consumers, job orchestration (deadlines by page count), watchdog, DLX retries ×2, DLQ + admin alert; Redis cache and single-flight locks; status snapshots in Redis | M | W02 | ING-BE |
| W13 | Compose services: postgres, redis, rabbitmq (+mgmt), clamav (verify arm64), gotenberg (opt.), proxy TLS 1.3; local Homebrew setup script (rabbitmq, clamav+freshclam, libreoffice, tessdata rus) | S | – | OPS |
| W14 | Python intake-worker: deep validation (pikepdf/PyMuPDF), page geometry + normalisation utility + rotated/offset fixtures, content class/DPI/LOW_QUALITY, annotations/overlay/active-content flags, signature presence, DOCX→PDF rendition, stamp crop rendering | M | W12, W05 | ING-PY |
| W15 | Python meta-worker: title-block template (forms 3, 4–6, change register), frame detection, cell snapping, text-layer reading, OCR fallback on cell crops (Tesseract rus + whitelist; optional PaddleOCR), stamps «В производство работ»/«Выполнено согласно проекту», revision rows, sheet titles → floor/section/axes; gold JSON for the 24 pilot pages + EM report | L | W14 | ING-PY |
| W16 | Registry draft builder (auto-fill + provenance + confidence + suggestions) and confirm flow; registry ↔ stamp cross-check | M | W06, W15 | ING-BE |
| W17 | Frontend: upload wizard (object passport/profile, folder drop, client checks, auto-chunking, progress, RU errors) | M | W01 (mock), W03 | FE |
| W18 | Frontend: registry editor grid (provenance, stamp thumbnails, validation, bulk edit, chain picker, versions/diff, export) | L | W16, W17 | FE |
| W19 | Frontend: completeness panel + revisions/linkage panel with decision dialog + gating-aware header + notifications | M | W10, W11, W17 | FE |
| W20 | Fixtures & tests: negative-scenario generator, boundary sizes, EICAR, tampered blob, perf scripts (autocannon/k6), contract tests, resolver PBT runner in CI | M | W03–W12 | QA |
| W21 | Demo dataset: reconstruct pilot files at original page indices + registry with pilot file_ids; synthetic full object (reportlab stamps per ГОСТ Р 21.101) incl. revision-conflict and «5 из 15 ИД» cases; XML/DOCX samples | M | W06 | QA (+ING-PY) |
| W22 | Batch ingest CLI (dir + registry → process → wait → export manifest/registry) | S | W03, W06, W11 | ING-BE |
| W23 | Observability: pino JSON logs (request_id, user_id), prom metrics, audit events wiring | S | W03, W12 | ING-BE |

Critical path: W01 → W02 → W06/W07 → **W08 (resolver)** → W10 → W11 → B04 integration. In parallel: W12 → W14 → **W15 (stamps)** → W16 → W18. Estimated effort: ING-BE ≈ 10–12 dev-days, ING-PY ≈ 6–7, FE ≈ 6–7, QA ≈ 4, OPS ≈ 1.
