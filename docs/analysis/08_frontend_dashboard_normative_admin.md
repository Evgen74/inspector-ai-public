# B08: Frontend architecture, Inspector Dashboard (Module 7), Normative Base Management (Module 8)

Planning and analysis only. No application code has been written. Author: B08 planning agent. Date: 2026-09-27.
Sources: `docs/spec/01_TZ_text.txt` (full ТЗ), `02_matrix_all_sheets.txt` (Приложение 1, all 4 sheets), `03_perechen_ID_registry_rules.txt`, `05_razmetka_poyasn_6p_text.txt`, page previews `img_razmetka/*`, `img_perechen/*`, originals in `ТЗ/`.
Library versions were checked against the npm registry on 2026-09-27. PyMuPDF render timings were measured on the pilot markup PDF on the dev machine (M2 Max).

---

## 0. Summary of key decisions (proposed)

1. **Stack.** React 19.3, Vite 8, TypeScript 6.0 (not 7.0: typescript-eslint 8.70 needs TS below 6.1), **Ant Design 6.6 with `ru_RU`** (no ProComponents: 2.8.x supports only antd 5 and 3.x is still beta), TanStack Query 5, React Router 8 with `nuqs` for URL-synced filters, **Orval** (hooks, zod schemas and MSW mocks generated from the single OpenAPI 3.0 spec), ECharts 6, react-querybuilder 8 with JSONLogic for Logical_Rules, and OpenSeadragon 6 for evidence viewing.
2. **Evidence viewer.** OpenSeadragon renders **server-side PyMuPDF raster tiles** with an SVG overlay in normalized [0;1] coordinates. We do not use pdf.js for drawings. Pilot sheets are A0 vector pages with up to about 113k path objects. MuPDF renders a whole page at 150 dpi in 0.6–1.8 s and a 300-dpi tile in 0.1–0.2 s. Using the same engine that computes the coordinates guarantees that bboxes line up after CropBox/MediaBox/Rotate (§9.1 p.4). react-pdf is kept only as an optional fallback for text documents.
3. **Object colour rule (strict).** 🔴 red means at least one `CONFIRMED_VIOLATION`. 🟡 yellow means an inspector action or data is required (pending `CANDIDATE`, `CLARIFICATION_REQUIRED`, `MISSING_EVIDENCE`, `NOT_COMPARABLE`, `PARTIALLY_LOADED`, or the registry is missing). 🟢 green means no candidates are pending, there are no confirmed violations and the evidence set is complete. ⚪ neutral grey is a labelled "нет результата/в обработке" state, not a fourth severity. HIGH `review_priority` never turns an object red, because the ТЗ says risk ≠ violation (§9.2). The server computes the colour with one shared TS function and stores it for filtering.
4. **Module 8 changes thresholds and triggers without recoding.** Params gets a typed, JSON-Schema-validated `trigger_rule` (templates ABS / RATIO / DELTA_PCT / DELTA_ABS / DIRECTIONAL / ORDINAL / PRESENCE / EXTERNAL_STATUS / SEMANTIC). `min_value`/`max_value` mean something defined for each template. A threshold can be inherited from time-bounded Normative_Base rows. Every save publishes a new immutable `matrix_version` snapshot with a mandatory reason, writes an audit entry, emits a RabbitMQ `matrix.version.published` event and invalidates Redis. Engines load the current snapshot at the start of a run. A running process keeps its pinned version and the UI offers "Перепроверить по матрице vN".
5. **Exports.** PDF, DOCX and XML are all rendered from the protocol JSON by one Python render worker: a docxtpl DOCX template, then LibreOffice to PDF, and lxml XML validated against our own XSD. When Приложение № 2 arrives we only edit the Word template.
6. **Pull model everywhere.** Adaptive polling with ETag/304 (2 s while PARSING, 15 s for notifications, 30 s for the dashboard). No websockets; SSE is optional later.

---

## 1. Scope: ТЗ clauses covered

| Clause | Quote / essence | What B08 owns |
|---|---|---|
| §1.1 | «Инспектор ИИ» (краткое наименование для интерфейса) | Product name in the shell, title and exports |
| §1.2 | «верификация выявленных нарушений инспектором…»; «автоматический контроль наличия документов и инкрементальная дозагрузка файлов до момента финализации протокола» | UI for document presence (completeness), dozagruzka entry points and gating |
| §1.3 | «REST over HTTPS (JSON)… с обязательной валидацией схемы OpenAPI 3.0» | Client generated from the same OpenAPI spec; zod runtime validation |
| §1.4 | «возвращает идентификатор процесса (process_id)… Статус обработки отслеживается через эндпоинт мониторинга» | Process monitor, polling, results on request |
| §1.5 | «Веб-приложение с пользовательским интерфейсом… клиентской частью на React» | Whole SPA |
| §7 Module 7 (Medium) | «Цветовая индикация объектов (зелёный/жёлтый/красный); фильтры по разделам, статусам, датам; экспорт протоколов в PDF, DOCX, XML» | Dashboard, colour rule, filters, export UI and orchestration |
| §7 Module 8 (Medium) | «Интерфейс для администратора системы, позволяющий добавлять, редактировать и деактивировать нормативные ссылки, обновлять пороговые значения параметров (min_value, max_value) без перекодирования системы» | Admin UI and Node backend for Params / Normative_Base / Logical_Rules / matrix versions |
| §7 Module 9 (UI side) | «Фиксация всех действий инспектора… версионность протоколов» | Audit viewer, protocol version history and diff UI |
| §7 Modules 4, 10, 11, 6 (UI side) | GOLD curation and model publication; weekly report; monitoring; РиН | Frontend screens ("hooks") consuming those blocks' APIs |
| §8.1 | Params table (id…is_active, created_at, updated_at) | Admin editor for every field; storage extensions |
| §8.2 | Codes PZ-01 / KR-55 / AR-41 | Alias codes next to M-xxx |
| §9.1 | Error table (format, corrupted PDF, 50 МБ, 200 МБ, timeout); upload statuses `PD_UPLOADED…ID_MISSING`; process statuses `PENDING…FINALIZED` with «Возможность дозагрузки/верификации»; «Дозагрузка возможна до момента финализации» | Upload wizard messages, status chips, action gating |
| §9.1 p.4 | bbox «приводятся к диапазону [0;1] относительно видимой области страницы после учёта CropBox, MediaBox и Rotate» | Viewer overlay contract |
| §9.1 (03 file) | Machine-readable registry CSV/XLSX/JSON with 11 mandatory fields; «без него пакет принимается со статусом CLARIFICATION_REQUIRED»; «Перезапись файла под тем же file_id запрещена» | Registry builder step |
| §9.2 | Scenarios `FULL/PD_RD_ONLY/PD_ID_ONLY/RD_ID_ONLY/SINGLE_ONLY/PARTIALLY_LOADED`; protocol sections and five separate tables; evidence card fields; «Протокол сохраняется… с присвоением версии… Инспектор получает уведомление»; «Предыдущая версия протокола сохраняется в истории»; status table; «Уровень риска… не равен статусу нарушения» | Protocol viewer (read-only), versions, diff, READY notification, colour semantics |
| §9.3 | «Статусы комплектности отображаются отдельно от кандидатов»; «MISSING_EVIDENCE выводится отдельным перечнем»; «Отмена финализации доступна только администратору системы или инспектору с правом супервизора… с обязательным указанием причины»; button «Завершить»; usability limits of ≤3 clicks and ≤30 min | Shell and viewer never add clicks; deep links; unfinalize entry point; role model. The verification workspace itself belongs to Module 3 |
| §9.4 | Curator check before a record enters `dataset_version`; «Решение о публикации подписывается ответственным лицом; должна сохраняться возможность отката»; system comments | ML/curator screens (frontend) |
| §9.5 | SUSPICION «не входит в сводное число нарушений»; logical rules example «Если этажей > 10, должен быть лифт» | Suspicion lists; Logical_Rules admin |
| §9.6 | `PENDING_SYNC`; «автоматическая дозагрузка… только уведомляет инспектора о наличии новых документов с предложением создать новую проверку» | Sync status display; notification with a "new check" action |
| §10 | Objects, Files, Protocols, Checks, Suspicions, Logical_Rules, Normative_Base, Audit_Log, Rejection_Log, Dispute_Log, Dataset_Items, Model_Versions, ML_Retraining_Log | B08 **owns** Params (admin side), Normative_Base, Logical_Rules (admin side), plus new Matrix_Versions, Notifications, Export_Jobs, Saved_Filters, Ordinal_Scales. It reads the rest |
| §11 | API p95 ≤ 200 ms; 100 concurrent inspectors; protocol generation ≤ 30 s; verification cycle ≤ 30 min | Query design, polling budget, export caching, telemetry |
| §12 | 1 login/password; 2 roles; 3 TLS 1.3; 4 audit with IP; 6 152-ФЗ; 11 antivirus (UI shows the result) | Auth UI, role guards, secure session, PD minimisation |
| §13 | JSON logs with request_id/user_id; metrics include «количество активных сессий пользователей» | X-Request-Id propagation, client error reporting, usability telemetry |
| §14.2 | «Каждый результат содержит dataset_version, matrix_version, model_version и input_manifest_hash» | Version badges in the viewer and every export |

Related statuses rendered by B08 (single dictionary, §3.4): process, upload, scenario, finding, completeness, inspector-decision, protocol, sync, approval, review priority, discovery method, prescription (`ISSUED, IN_PROGRESS, COMPLETED, CANCELLED, EXTENDED`), dataset/model states.

---

## 2. Requirements checklist (prefix UI-)

Priority means priority for winning: MUST / SHOULD / NICE. MVP decision: FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

### 2.1 Platform, shell, cross-cutting

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| UI-01 | Product name «Инспектор ИИ» in header, `<title>`, login and exports | §1.1 | MUST | FULL | Trivial and it is the letter of the ТЗ |
| UI-02 | Web UI to upload documents and get analysis results; React client | §1.5 | MUST | FULL | Core deliverable |
| UI-03 | All calls are REST/JSON against the OpenAPI 3.0 spec; the client is generated from the same spec; responses are zod-validated in dev | §1.3 | MUST | FULL | Orval pipeline; one source of truth |
| UI-04 | Pull model: upload returns `process_id`; status comes from the monitoring endpoint; results are fetched on request | §1.4 | MUST | FULL | Adaptive polling (§3.7) |
| UI-05 | Login with login/password for all user categories | §12.1 | MUST | FULL | Cookie session |
| UI-06 | Role-based navigation and guards: inspector, supervisor (unfinalize), admin, ML engineer, data curator, plus a "responsible person" permission for model publication | §12.2, §9.3, §9.4 | MUST | FULL | The server is authoritative; the UI hides and disables |
| UI-07 | Every user action is audited (time, IP, type, object id); UI sends `X-Request-Id` and a mandatory reason where the ТЗ requires one | §12.4, §7 m.9 | MUST | FULL | Server writes Audit_Log; UI supplies context |
| UI-08 | Russian UI; ru-RU number/date formats (decimal comma, `DD.MM.YYYY HH:mm`, Europe/Moscow); correct plurals | — | MUST | FULL | Government user base |
| UI-09 | Accessibility: colour never the sole carrier (icon plus text), keyboard navigation, contrast AA; reference WCAG 2.1 AA / ГОСТ Р 52872-2019 | — | SHOULD | SIMPLIFIED | axe checks on key pages; no formal audit |
| UI-10 | Responsive: desktop-first (1366–1920), tablet ≥1024 for reading, phone ≥360 for lists and notifications | — | SHOULD | SIMPLIFIED | Verification and admin are desktop only |
| UI-11 | Client errors and web vitals reported to the backend log pipeline with request_id/user_id | §13.1 | SHOULD | SIMPLIFIED | `POST /api/v1/client-logs` |
| UI-12 | Served over HTTPS (nginx, TLS 1.3) in Docker; same-origin `/api` | §12.3 | SHOULD | SIMPLIFIED | Self-signed certificate locally |

### 2.2 Module 7: Dashboard, objects, processes, protocols, exports, notifications

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| UI-13 | Colour indication of objects: green/yellow/red | §7 m.7 | MUST | FULL | Rule in §3.5 |
| UI-14 | Colour computed server-side by one deterministic, documented rule over the latest protocol version; reasons shown in a tooltip | §7 m.7 | MUST | FULL | Filtering and exports agree with the UI |
| UI-15 | Colour never implies a violation for CANDIDATE/SUSPICION or review priority | §9.2 (risk ≠ status), §9.5 | MUST | FULL | Methodological correctness is visible to the jury |
| UI-16 | Filter by matrix sections (ПЗ…СМ, ИОС1–5 as a sub-tree) | §7 m.7 | MUST | FULL | Server-side filter |
| UI-17 | Filter by statuses: indicator, process, finding, completeness, upload, sync | §7 m.7 | MUST | FULL | Multi-select |
| UI-18 | Filter by dates with a date-field selector (upload / protocol created / finalized / last activity) | §7 m.7 | MUST | FULL | RangePicker, ru locale |
| UI-19 | Export protocol to **PDF** | §7 m.7, §9.2 p.4 | MUST | FULL | Render worker (§3.9) |
| UI-20 | Export protocol to **DOCX** | §7 m.7 | MUST | FULL | docxtpl template |
| UI-21 | Export protocol to **XML**, validated against a published XSD | §7 m.7 | MUST | FULL | Own XSD (no format in the ТЗ) |
| UI-22 | Viewer and every export show `matrix_version`, `dataset_version`, `model_version`, `input_manifest_hash`, protocol version, scenario and upload statuses | §9.2 p.1, p.4; §14.2 | MUST | FULL | Letter of the ТЗ |
| UI-23 | "Число нарушений" counts only `CONFIRMED_VIOLATION` (never CANDIDATE/SUSPICION/MISSING_EVIDENCE) | §9.2 table, §9.5 | MUST | FULL | Shared counter function |
| UI-24 | Object list with search, sort, server pagination and KPI tiles | §7 m.7 | SHOULD | FULL | Standard |
| UI-25 | Object card with Objects fields (name, address, customer, contractor, permit_number) and stable object id (надзорное дело) | §10.3, 03 | MUST | FULL | — |
| UI-26 | Documents tab: file registry, revision chains (predecessor/successor), approval status, SHA-256, superseded revisions visibly excluded from reference | §9.1, 03 | MUST | FULL | «Устаревшая редакция не может использоваться как эталон» |
| UI-27 | Process list and status monitor with per-file progress and errors | §1.4, §9.1 | MUST | FULL | Polling |
| UI-28 | Actions enabled strictly per the §9.1 status table (dozagruzka / verification availability) using server `capabilities` | §9.1 | MUST | FULL | Tooltip explains why an action is disabled |
| UI-29 | Upload statuses `PD_/RD_/ID_ UPLOADED/PARTIAL/MISSING` shown per object and process | §9.1 | MUST | FULL | Three chips |
| UI-30 | Scenario type (`FULL`…`PARTIALLY_LOADED`) shown, including a pre-start prediction | §9.2 p.2 | MUST | FULL | Completeness preview step |
| UI-31 | Inspector notified when a protocol is READY | §9.2 p.5 | MUST | FULL | In-app bell, toast, deep link |
| UI-32 | Admin notified after a file processing timeout plus 2 retries | §9.1 | MUST | SIMPLIFIED | In-app. Email/Telegram delivery belongs to Module 11 |
| UI-33 | Notification about new РиН documents after finalization, with a "Создать новую проверку" action | §9.6 | SHOULD | SIMPLIFIED | Depends on the Module 6 mock |
| UI-34 | Upload: PDF/DOCX/XML only; ТЗ-worded rejection messages (unsupported format, corrupted PDF, >50 МБ file, >200 МБ package) | §9.1 | MUST | FULL | Client pre-check, server authoritative |
| UI-35 | Registry builder: 11 mandatory fields; import CSV/XLSX/JSON; build in UI with auto-suggestions; export; warning that a missing or incomplete registry means `CLARIFICATION_REQUIRED` | 03, §9.1 | MUST | FULL | Central to linkage correctness (≥0.95 metric) |
| UI-36 | Incremental dozagruzka without re-uploading existing files, until finalization | §1.2, §9.1, §9.3 p.3 | MUST | FULL | Wizard in "append" mode |
| UI-37 | After finalization, dozagruzka and status changes are impossible (UI read-only) | §9.3 p.5 | MUST | FULL | Capabilities-driven |
| UI-38 | Re-upload never overwrites: a new record plus a new protocol version; UI explains the dedup and new-revision outcome | 03 | MUST | FULL | Hash lookup |
| UI-39 | Protocol viewer: «Статус загрузки документов», «Тип проверки», five separate tables, evidence card with every mandatory field | §9.2 p.4 | MUST | FULL | Read-only. Decisions happen in the Module 3 workspace |
| UI-40 | MISSING_EVIDENCE shown as a separate list, never as a violation | §9.3 p.4 | MUST | FULL | — |
| UI-41 | Completeness statuses shown separately from candidates | §9.3 p.1 | MUST | FULL | Table (1) is separate |
| UI-42 | Protocol version history: all versions listed and viewable | §9.2, §7 m.9 | MUST | FULL | — |
| UI-43 | Diff between any two protocol versions | §9.2 (incremental) | SHOULD | FULL | Strong demo value |
| UI-44 | Evidence pages with highlighted regions from normalized bbox/polygon (CropBox/MediaBox/Rotate-safe) | §9.1 p.4, §9.3 p.1 | MUST | FULL | Shared `EvidenceViewer` (also used by Module 3) |
| UI-45 | Unfinalize button only for admin/supervisor, with a mandatory reason | §9.3 | MUST | FULL | Calls the Module 3 endpoint |
| UI-46 | РиН sync status (`PENDING_SYNC`, attempts, next retry) per protocol | §9.6 | SHOULD | SIMPLIFIED | Read-only chip plus admin retry |
| UI-47 | Suspicions (SUSPICION) listed separately, not counted, linked to evidence binding | §9.5 | MUST | FULL | Table (5) and object tab |
| UI-48 | Dashboard charts: findings by section and status; protocols per week | §7 m.7 | NICE | SIMPLIFIED | Two charts |
| UI-49 | Frontend respects API p95 ≤ 200 ms and 100 concurrent users (pagination, ETag/304, polling budget) | §11 #10–11 | SHOULD | SIMPLIFIED | Budget in §3.7 |
| UI-50 | Shell adds no clicks to verification: notification to workspace in 1 click; filtered queue links | §9.3 usability | SHOULD | FULL | Deep links |

### 2.3 Module 8: Normative base and matrix management

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| UI-51 | Admin can **add** normative references (document_name, document_number, section, parameter_name, min_value, max_value, effective_from, effective_to) | §7 m.8, §10.10 | MUST | FULL | — |
| UI-52 | Admin can **edit** normative references | §7 m.8 | MUST | FULL | Optimistic locking |
| UI-53 | Admin can **deactivate** (and reactivate) references; no hard delete | §7 m.8 | MUST | FULL | `is_active` plus optional `effective_to` |
| UI-54 | The validity period (effective_from/effective_to) is honoured when a check runs; future-dated rows are shown as «Будущая редакция» | §10.10 | MUST | FULL | Snapshot carries validity windows |
| UI-55 | Admin updates parameter thresholds `min_value`/`max_value` **without recoding**; they take effect on the next check | §7 m.8, §8.1 | MUST | FULL | Engines read the snapshot per run |
| UI-56 | Admin edits the other Params fields per §8.1: parameter_name, unit, source_pd/rd/id, trigger_logic, review_priority, sp/gost/fz/other refs, data_type, regex_pattern, is_active | §8.1 | MUST | FULL | Param editor drawer |
| UI-57 | Machine-readable trigger rule (typed templates) editable without code: the part of "without recoding" that covers non-numeric triggers | §7 m.8, §8.1 trigger_logic | SHOULD | FULL | Only about 26 of 132 triggers are plain numeric thresholds (§3.12.2) |
| UI-58 | Each published change bumps `matrix_version` (immutable snapshot plus SHA-256); every run and protocol records it | §9.2 p.1, §14.2 | MUST | FULL | Matrix_Versions table |
| UI-59 | Each admin change writes Audit_Log with before/after, reason and matrix_version | §7 m.9, §12.4 | MUST | FULL | Same transaction |
| UI-60 | Validation on client and server: types, units, min ≤ max, date order, overlapping validity, regex compiles (Python syntax), trigger_rule JSON Schema, code format | §1.3 | MUST | FULL | Shared JSON Schema/zod |
| UI-61 | Per-entity change history with field diffs, plus restore of an earlier state (as a new version) | §7 m.9 | SHOULD | SIMPLIFIED | Restore only for Params/Normative rows |
| UI-62 | Impact preview ("what-if"): how many existing findings would change under the new threshold | — (quality) | NICE | SIMPLIFIED | Numeric templates only |
| UI-63 | Optimistic locking (`If-Match`/row_version) with a conflict dialog | — | SHOULD | FULL | Several admins |
| UI-64 | Logical_Rules CRUD (rule_name, condition, expected, normative_base, is_active) with a visual builder and a test run | §10.9, §9.5 | SHOULD | FULL | react-querybuilder to JSONLogic |
| UI-65 | Matrix export to XLSX (the Приложение 1 layout plus added columns); import through a seed script | — | SHOULD | SIMPLIFIED | Import UI is NICE |
| UI-66 | Canonical codes `M-001…M-132` with ТЗ-style aliases (`PZ-01`, `KR-55`, `AR-41`) that are searchable | §8.1, §8.2 | SHOULD | FULL | Reconciles the ТЗ and the matrix |
| UI-67 | Editable ordinal scales (concrete class B…, EI, КМ0–КМ5, energy class…) for downgrade triggers | §7 m.8 spirit | NICE | SIMPLIFIED | Seeded dictionary with a simple editor |

### 2.4 Other admin and ML screens (frontend side of Modules 4, 6, 9, 10, 11, 12)

| ID | Requirement | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| UI-68 | Audit log viewer (filters by user, action, object, date; before/after details) | §7 m.9, §12.4 | MUST | FULL | Cheap and demo-visible |
| UI-69 | Users and roles management | §12.1–2 | SHOULD | SIMPLIFIED | Seeded users plus basic CRUD |
| UI-70 | Monitoring overview (service health, queue sizes, 5xx, active sessions) with links to Grafana/Kibana | §13.4–6 | SHOULD | SIMPLIFIED | Reads the Module 11 API |
| UI-71 | ИАИС «РиН» sync queue (PENDING_SYNC, retries at 1/5/15 min, manual retry) | §9.6 | NICE | MOCKED | External system is a mock |
| UI-72 | Dataset curation queue: draft items reviewed by the curator, then a `dataset_version` release with object-level split preview and hashes | §9.4, §14.2 | MUST | FULL | Frontend of a High module |
| UI-73 | Model registry: metrics against §14.3 thresholds, per-category regression gate (ΔRecall ≥ −2 pp, ΔFPR ≤ +2 pp), publication decision by the responsible person, rollback | §9.4, §14.3 | MUST | FULL | Frontend of a High module |
| UI-74 | Rejection_Log and Dispute_Log viewers for the ML engineer | §10.6–7, §12.2 | SHOULD | FULL | Tables with filters |
| UI-75 | Weekly retraining report viewer (list, render, download) | §7 m.10 | SHOULD | FULL | Reads the Module 10 artifact |
| UI-76 | System comments (§9.4 examples, e.g. «Результат инспектора: NEGATIVE_VERIFIED. Причина: OCR_ERROR…») shown in finding history | §9.4 | SHOULD | FULL | Text produced by Modules 3/4 |
| UI-77 | Negative-state UX catalog: offline, 5xx, timeout, 409 conflict, 403, 413, integration failure, corrupted file | §7 m.12 | MUST | FULL | Error catalog in the domain package |
| UI-78 | Idempotent upload/start/export (`Idempotency-Key`) so retries never create duplicate processes | §7 m.12 | SHOULD | FULL | Header in the mutator |
| UI-79 | Docker-ready: static build behind nginx, runtime `/config.json`, same-origin `/api`, `client_max_body_size` ≥ 210m | user wish | MUST | FULL | — |
| UI-80 | Session security: HttpOnly Secure SameSite cookie, CSRF header, idle timeout, no personal data in localStorage | §12.3, §12.6 | SHOULD | FULL | — |
| UI-81 | Entry point to convert SUSPICION to CANDIDATE (routes into the Module 3/5 evidence-binding workspace) | §9.5 | SHOULD | FULL | Navigation only |
| UI-82 | Saved filter presets and shareable URLs | — | NICE | FULL | Free with URL state |
| UI-83 | Personal data minimisation: developer contacts and inspector full names only for authorised roles | §12.6 | SHOULD | SIMPLIFIED | Field-level hiding |
| UI-84 | Settings screen (limits shown, colour policy, polling intervals) | — | NICE | SIMPLIFIED | Read-mostly |
| UI-85 | Usability telemetry: clicks per finding and time per protocol, to prove ≤3 clicks and ≤30 min | §9.3, §11 #15 | SHOULD | SIMPLIFIED | Event hook to Monitoring_Metrics |
| UI-86 | Usability test with 5 inspectors, then UI rework | §9.3 | SHOULD | SIMPLIFIED | Proxy participants plus a documented protocol (shared with Module 3) |
| UI-87 | Model publication signed with УКЭП (CryptoPro browser plugin) | §9.4 («подписывается») | NICE | OUT_OF_SCOPE | Replaced by password re-entry and a named, recorded approver |
| UI-88 | Email/Telegram delivery of inspector notifications | — | NICE | OUT_OF_SCOPE | In-app only. Admin alerts via Module 11 |
| UI-89 | Map view of objects | — | NICE | OUT_OF_SCOPE | Not required; needs a geocoder in a closed network |
| UI-90 | Languages other than Russian | — | NICE | OUT_OF_SCOPE | Not required |

Tally: 90 requirements. FULL 66, SIMPLIFIED 19, MOCKED 1, OUT_OF_SCOPE 4.

---

## 3. Proposed design

### 3.1 Architecture and repository layout (proposal; the platform block confirms)

```
/apps/web              React SPA (this block)
/apps/api              Node.js API (platform skeleton + module routes; B08 adds admin/dashboard/notifications)
/services/ml-*         Python ≥3.11 workers (parsing, comparison, hypotheses, render)
/packages/api-spec     openapi.yaml: SINGLE source of truth (OpenAPI 3.0.3)
/packages/api-client   generated by Orval (hooks, zod, MSW mocks); never hand-edited
/packages/domain       TS: status enums + RU labels/colours/icons, capability map, colour rule,
                       counters, protocol diff, error catalog, formatters; used by web AND api
/infra                 docker-compose, nginx, Dockerfiles
```

- **Dev**: `pnpm dev` runs Vite on :5173 and proxies `/api` to `http://localhost:3000`. `VITE_API_MOCK=1` runs the whole UI against MSW mocks generated from the spec, so frontend agents are not blocked by the backend.
- **Docker**: `apps/web/Dockerfile` is multi-stage (`node:22-alpine` build, then `nginx:alpine`). nginx serves the SPA (`try_files $uri /index.html`) and proxies `/api/` to `api:3000` with `client_max_body_size 210m`, `proxy_request_buffering off` and a 300 s timeout. It sends CSP (`default-src 'self'; img-src 'self' blob: data:; worker-src 'self' blob:`), `X-Frame-Options: DENY` and a Referrer-Policy. Runtime `/config.json` is rendered from env by the entrypoint (apiBase, grafanaUrl, kibanaUrl, poll intervals, feature flags), so one image works everywhere.
- **Closed-network readiness**: no CDN at runtime; the Golos Text font is self-hosted through `@fontsource`; all workers are bundled.

### 3.2 Frontend tech stack (versions verified on npm, 2026-09-27)

| Concern | Choice | Version | Rationale / alternatives rejected |
|---|---|---|---|
| Framework | React + react-dom | 19.3 | ТЗ mandates React |
| Build | Vite + @vitejs/plugin-react | 8.3 / 6.1 | Fast; code splitting per route |
| Language | TypeScript, strict | **6.0.x** | TS 7.0.2 (native) is out, but typescript-eslint 8.70 supports only TS <6.1 |
| UI kit | **Ant Design** + @ant-design/icons, `ConfigProvider locale={ru_RU}` + dayjs `ru` | 6.6 / 6.3 | Densest enterprise kit: Table with virtual scroll, Form, RangePicker, Tree-select, Steps, Upload.Dragger, Descriptions, Timeline; full ru_RU; best known to AI coding agents. Alternatives: Gravity UI (Yandex) and Consta (Russian design systems, smaller component set, riskier for agents); MUI (verbose, DataGrid features paid); Mantine (fewer enterprise widgets). **No ProComponents**: 2.8.10 supports only antd 5 and 3.x is beta. We write a thin FilterBar/DataTable instead |
| Server state | @tanstack/react-query (+ devtools) | 5.104 | Polling via `refetchInterval`, cache, retries |
| API client | **Orval** (react-query client, zod, MSW mocks), custom fetch mutator | 8.38 | Contract-first; mocks let agents work in parallel. openapi-typescript + openapi-fetch is a lighter alternative without mocks |
| Runtime validation | zod | 4.6 | Generated schemas; dev-mode response validation |
| Routing | react-router (declarative data router) | 8.4 | Needs React ≥19.2.7. Fallback 7.18 if agents hit v8 API gaps |
| URL filter state | nuqs (react-router adapter) | 2.10 | Typed search params; shareable filters |
| Local UI state | zustand | 5.0 | Session and UI prefs only |
| Forms | antd Form + antd-zod rules | 6.6 / 8.0 | Same zod schemas as the API |
| Charts | echarts + echarts-for-react | 6.1 / 3.0.6 | Robust, ru locale; lazy-loaded |
| Evidence viewer | **openseadragon** (+ own React wrapper) | 6.1 | Deep zoom of huge sheets, tiles, SVG overlays (§3.10) |
| PDF fallback | react-pdf (pdfjs-dist 6.3) | 11.0 | Only for small text PDFs if tiles are unavailable |
| Rule builder | react-querybuilder + @react-querybuilder/antd, json-logic-js | 8.24 / 2.0.5 | Visual builder that exports JSONLogic, which Python can evaluate |
| Hashing | hash-wasm (in a Web Worker) | 4.12 | Streaming SHA-256 of 50 MB files without freezing the UI |
| Virtual lists | @tanstack/react-virtual | 3.14 | Registry grid with hundreds of files |
| Field diff | jsondiffpatch | 0.7 | History and matrix-version diffs |
| Font | @fontsource/golos-text | 5.3 | Cyrillic-first, self-hosted |
| Tests | vitest, @testing-library/react, @playwright/test, @axe-core/playwright | 5.0 / – / 1.63 / 4.13 | Unit, E2E and a11y |

### 3.3 App shell, routing, roles

**Layout.** antd `Layout` with a collapsible left `Menu` (role-filtered) and a top bar with the product name «Инспектор ИИ», global search (object / дело / шифр / process_id), the notification bell, and the user menu (full name, roles, logout). Pages use a `PageHeader` with breadcrumbs. The sidebar collapses to icons below `lg` (992 px).

**Routes** (lazy route chunks: `admin/*`, `ml/*`, viewer, charts):

| Path | Screen | Roles |
|---|---|---|
| `/login` | S-01 Вход | public |
| `/` | redirect by role (inspector/supervisor to `/dashboard`, admin to `/admin/matrix`, ML to `/ml/models`, curator to `/ml/datasets/curation`) | all |
| `/dashboard` | S-02 Дашборд | INS, SUP, ADM (read) |
| `/objects/:objectId` (`?tab=`) | S-04 Карточка объекта | INS, SUP, ADM (read) |
| `/objects/:objectId/upload` (`?processId=` for append) | S-05 Мастер загрузки | INS, SUP |
| `/processes`, `/processes/:processId` | S-06/S-07 Монитор процессов | INS, SUP, ADM |
| `/protocols/:protocolId` (`?compare=`) | S-08/S-09 Протокол, сравнение версий | INS, SUP, ADM (read), CUR (read, via curation) |
| `/protocols/:protocolId/verify` | S-10 Верификация (**Module 3 plug-in**) | INS, SUP |
| `/files/:fileId/view?page=&bbox=` | S-11 Просмотр документа | INS, SUP, ADM, CUR, MLE |
| `/notifications` | S-12 Уведомления | all |
| `/admin/matrix`, `/admin/matrix/:code` | S-13/S-14 Матрица, параметр | ADM (SUP read) |
| `/admin/normative`, `/admin/normative/:id` | S-15/S-16 Нормативная база | ADM (SUP read) |
| `/admin/rules`, `/admin/rules/:id` | S-17 Логические правила | ADM |
| `/admin/matrix-versions`, `/:version` | S-18 Версии матрицы | ADM, MLE (read), SUP (read) |
| `/admin/audit` | S-19 Журнал аудита | ADM, SUP (own team) |
| `/admin/users` | S-20 Пользователи | ADM |
| `/admin/monitoring` | S-21 Мониторинг | ADM |
| `/admin/integration` | S-22 ИАИС «РиН» | ADM |
| `/admin/settings` | S-23 Настройки | ADM |
| `/ml/rejections`, `/ml/disputes` | S-24/S-25 | MLE |
| `/ml/datasets/curation`, `/ml/datasets`, `/ml/datasets/:version` | S-26/S-27 | CUR (write), MLE (read) |
| `/ml/models`, `/ml/models/:version` | S-28 | MLE, APPROVER permission for the decision |
| `/ml/reports`, `/ml/reports/:id` | S-29 | MLE, ADM |
| `/403`, `/404`, `/500`, offline banner, session-expired modal | S-30 | — |

**Roles and permissions** (a user may hold several roles; the server enforces, the UI mirrors `GET /auth/me.permissions`):

| Permission | INSPECTOR | SUPERVISOR | ADMIN | ML_ENGINEER | DATA_CURATOR |
|---|---|---|---|---|---|
| objects.read / dashboard | ✓ | ✓ (all) | ✓ | – | – |
| documents.upload, process.start | ✓ | ✓ | – | – | – |
| verification.decide (Module 3) | ✓ | ✓ | – | – | – |
| protocol.finalize («Завершить») | ✓ | ✓ | – | – | – |
| protocol.unfinalize (reason) | – | ✓ | ✓ | – | – |
| protocol.export | ✓ | ✓ | ✓ | – | – |
| matrix.read / normative.read | ✓ (read) | ✓ (read) | ✓ | ✓ (read) | – |
| matrix.write / normative.write / rules.write | – | – | ✓ | – | – |
| audit.read | – | ✓ (team) | ✓ | – | – |
| users.manage, settings, monitoring, integration | – | – | ✓ | – | – |
| ml.logs.read (Rejection/Dispute/weekly) | – | – | – | ✓ | – |
| dataset.curate / dataset.release | – | – | – | – (read) | ✓ |
| model.approve ("ответственное лицо") | granted per user as a separate permission (default: none) | | | | |

**Session.** `POST /auth/login` sets a `__Host-session` HttpOnly Secure SameSite=Strict cookie. A CSRF token is returned in the body and sent as `X-CSRF-Token`. After 30 minutes idle the user sees a warning at 25 minutes, then logs out. A 401 anywhere opens the session-expired modal, which preserves the current route. No tokens or personal data go into localStorage (only UI prefs such as the collapsed sidebar and table density).

### 3.4 Design system

**Tokens** (antd `ConfigProvider theme`): primary `#1F4E8C`, radius 4, font "Golos Text" with system-ui fallback, base 14 px, compact algorithm toggle for dense tables. Colours are split into reserved groups so that nothing is ambiguous:

| Group | Use | Colours |
|---|---|---|
| Object indicator | only the dashboard colour | red `#C62828` + ⛔ icon, yellow `#F2A900` (dark text) + ⚠ icon, green `#2E7D32` + ✔ icon, neutral grey `#8C8C8C` + ◌ |
| Finding status | tags | CONFIRMED_VIOLATION red-solid; CANDIDATE amber-outline; NEGATIVE_VERIFIED green-outline; SUSPICION purple-dashed |
| Process status | neutral blues/greys only (never red/yellow/green) | PENDING grey, PARSING blue with spinner, READY cyan, VERIFYING geekblue, COMPLETED indigo, FINALIZED dark slate with 🔒 |
| Evidence overlay | by **role**, matching the pilot legend («ПД — проектное решение, база сравнения» blue; «РД — зона отсутствующего или измененного решения» red) | EXPECTED blue `#1D4ED8`, ACTUAL red `#C62828`, context grey, SUSPICION purple dashed |

**Status dictionary** (`packages/domain/statuses.ts`). Every ТЗ code maps to a RU label, a short hint and a colour. Tags show the RU label with the exact ТЗ code in a tooltip and in a `data-code` attribute, so the jury can see that the codes are the ТЗ's own. Codes are namespaced because `PENDING` has three meanings in the ТЗ:

| Namespace | Code → RU label |
|---|---|
| process | PENDING «Ожидает запуска проверки»; PARSING «Обработка документов»; READY «Протокол сформирован, ожидает верификации»; VERIFYING «Идёт верификация»; COMPLETED «Верификация завершена, протокол не финализирован»; FINALIZED «Протокол финализирован» |
| upload | PD_UPLOADED «ПД загружена полностью», PD_PARTIAL «ПД загружена частично», PD_MISSING «ПД отсутствует» (same pattern for RD_*, ID_*) |
| scenario | FULL «Полная сверка ПД–РД–ИД»; PD_RD_ONLY «ПД и РД (ИД отсутствует)»; PD_ID_ONLY «ПД и ИД (РД отсутствует)»; RD_ID_ONLY «РД и ИД (ПД отсутствует)»; SINGLE_ONLY «Загружен один массив»; PARTIALLY_LOADED «Частичная загрузка» |
| finding | CANDIDATE «Кандидат (не нарушение)»; CONFIRMED_VIOLATION «Подтверждённое нарушение»; NEGATIVE_VERIFIED «Расхождение не подтверждено»; SUSPICION «Гипотеза (вне Матрицы)» |
| completeness | COMPLETE «Комплектно»; MISSING_EVIDENCE «Нет обязательного документа/фрагмента»; NOT_APPLICABLE «Неприменимо»; NOT_COMPARABLE «Несопоставимо»; CLARIFICATION_REQUIRED «Требует уточнения» |
| inspector | PENDING «Ожидает решения»; CONFIRMED_VIOLATION; NEGATIVE_VERIFIED; CLARIFICATION_REQUIRED |
| protocol | VERIFICATION_COMPLETED; PROTOCOL_FINALIZED |
| sync | PENDING_SYNC «Ожидает передачи в ИАИС «РиН»» (+ extensions NOT_SENT, SYNCED, SYNC_FAILED) |
| approval | DRAFT «Черновик»; APPROVED «Утверждён»; FOR_CONSTRUCTION «В производство работ»; SUPERSEDED «Заменён»; CANCELLED «Аннулирован» |
| priority | HIGH «Высокий — обязательная экспертная проверка»; MEDIUM «Средний — экспертная проверка»; LOW «Низкий». Always shown with the hint «только очерёдность экспертной проверки; не юридическое действие» |
| discovery | LOGICAL_ANALYSIS «Логический анализ»; SEMANTIC_DISSONANCE «Семантический диссонанс»; NORMATIVE_ANALYSIS «Нормативный анализ»; ML_PATTERN «ML-паттерн-анализ» |
| prescription | ISSUED, IN_PROGRESS, COMPLETED, CANCELLED, EXTENDED |
| reason codes (Module 3 owns the list) | WRONG_REVISION «Актуальная редакция выбрана неверно», APPROVED_CHANGE «Согласованное изменение», OCR_ERROR «Ошибка OCR», LINKING_ERROR «Ошибка привязки», NOT_APPLICABLE «Параметр неприменим», OTHER |

**Shared components** (`shared/ui`, documented in a `/dev/kit` page in dev builds):
`ObjectIndicator` (dot, icon, label, reasons tooltip), `StatusTag({ns, code})`, `CodeChip` («M-041 · AR-41»), `HashText` (SHA-256 shown as `3fa1c2d4…9b07` with copy), `DocRef` (stage chip ПД/РД/ИД, шифр, «ред. 2», «л. 4 / стр. 5», approval tag), `MetricDelta` (expected → actual, Δ and Δ% with unit, ru format), `VersionBadges` (matrix v15 · dataset v3 · model v2 · manifest `ab12…`), `UploadStatusChips`, `ScenarioTag`, `FilterBar` (URL-synced), `DataTable` (server pagination, sort, column settings, virtual scroll), `ReasonModal` (mandatory reason, minimum 10 characters, used for all audited admin actions and unfinalize), `ConfirmDanger`, `EmptyState` / `ErrorState` / `ForbiddenState`, `FieldDiffTable`, `AuditTimeline`, `EvidenceCard` (read-only; Module 3 wraps it with decision buttons), `EvidenceViewer` (§3.10), `PollingIndicator`.

**Formatting** (`packages/domain/format.ts`): `Intl.NumberFormat('ru-RU')` gives «6 234,1 м²». Inputs accept both `,` and `.` (antd `InputNumber decimalSeparator=","`). Dates are stored in UTC and displayed as `DD.MM.YYYY HH:mm` in Europe/Moscow. Plurals use `Intl.PluralRules('ru')` («1 нарушение / 2 нарушения / 5 нарушений»).

**Accessibility.** Colour always comes with an icon and text. Visible focus rings. All icon buttons have `aria-label`. Tables are keyboard-navigable and expanded rows are announced. Contrast is ≥ 4.5:1, which is why yellow uses dark text. An axe run in Playwright gates CI on 10 key pages.

**Responsive.** antd breakpoints (xs<576, sm≥576, md≥768, lg≥992, xl≥1200, xxl≥1600). Target 1366×768 and 1920×1080. Tables become card lists below `md`. Admin and verification screens show «Экран предназначен для работы на компьютере» below `lg` but remain readable.

### 3.5 Object colour indication rule (Module 7 core)

Colour is computed on the server by `computeIndicator()` from `packages/domain` (the same code the UI uses for explanations). It is materialised into `objects.indicator_*` whenever a `protocol.ready`, `protocol.updated`, `verification.decided`, `protocol.finalized` or `protocol.unfinalized` event arrives, so `?color=RED` is a cheap SQL filter.

Input: the object's **current process** (the latest by created_at) and the **latest protocol version** of that process, including working inspector decisions. Counters are taken over atomic findings (evidence groups) of the 132-parameter matrix. Suspicions are excluded from colour and shown only as a badge.

```
computeIndicator(obj):
  P  = obj.currentProcess;  Pr = latestProtocolVersion(P)
  if Pr is null:                                   → NONE  "Нет результата" (+ process status label)
  c = counters(Pr)                                 // atomic findings; SUSPICION excluded
  if c.CONFIRMED_VIOLATION ≥ 1:                    → RED    reasons=[CONFIRMED_VIOLATION(n)]
  reasons = []
  if c.CANDIDATE_PENDING ≥ 1:                      reasons += CANDIDATES_PENDING(n, high=n_high)
  if c.CLARIFICATION_REQUIRED ≥ 1:                 reasons += CLARIFICATION_REQUIRED(n)
  if c.MISSING_EVIDENCE ≥ 1:                       reasons += MISSING_EVIDENCE(n)
  if c.NOT_COMPARABLE ≥ 1:                         reasons += NOT_COMPARABLE(n)
  if Pr.scenario == PARTIALLY_LOADED:              reasons += PARTIAL_UPLOAD
  if Pr.registry_missing:                          reasons += REGISTRY_MISSING
  if reasons not empty:                            → YELLOW reasons
  else:                                            → GREEN  reasons=[NO_VIOLATIONS_COMPLETE]
                                                   // NOT_APPLICABLE and NEGATIVE_VERIFIED are fine
  // Overlays (not colours): spinner if P.status==PARSING; 🔒 if FINALIZED;
  // "матрица устарела" badge if Pr.matrix_version < current; PENDING_SYNC chip.
```

Truth table (this is also the unit-test table, at least 20 cases in CI):

| Latest protocol state | Colour | Tooltip |
|---|---|---|
| none (process PENDING/PARSING or no process) | ⚪ NONE | «Нет результата: обработка документов» |
| ≥1 CONFIRMED_VIOLATION (with any others) | 🔴 RED | «Подтверждено нарушений: 2 (M-055, M-041)» |
| 0 confirmed, ≥1 CANDIDATE pending (HIGH or not) | 🟡 YELLOW | «Ожидают решения: 7 кандидатов (HIGH: 5)» |
| 0 confirmed, 0 pending, ≥1 CLARIFICATION_REQUIRED | 🟡 YELLOW | «Требует уточнения редакции: 1» |
| 0 confirmed, 0 pending, ≥1 MISSING_EVIDENCE or NOT_COMPARABLE | 🟡 YELLOW | «Нет обязательных документов: 4» |
| scenario PARTIALLY_LOADED or registry missing | 🟡 YELLOW | «Комплект загружен частично» |
| all NEGATIVE_VERIFIED / NOT_APPLICABLE, evidence complete (finalized or not) | 🟢 GREEN | «Нарушений не выявлено; комплект полный» (+ «не финализирован» sub-label) |
| pilot Октябрьская 103 | 🔴 | CONFIRMED_VIOLATION (geodetic tolerances) |
| pilot Полярная 17 | 🟢 | NEGATIVE_VERIFIED control pair |
| other pilot objects | 🟡 | CANDIDATE awaiting decision |

Alternative policy **TRIAGE** (not recommended; exposed as an admin setting `indicator_policy`): red is also triggered by a HIGH-priority CANDIDATE pending longer than N days. 106 of 132 parameters are HIGH, so TRIAGE would turn almost every object red before verification, and it contradicts §9.2 («Уровень риска… не равен статусу нарушения»).

### 3.6 Screen inventory (wireframe level)

**S-01 Вход.** Centred card: «Инспектор ИИ», login, password, «Войти», error «Неверный логин или пароль». No self-registration. A footer notes that personal data is processed under 152-ФЗ.

**S-02 Дашборд инспектора**
```
┌ Инспектор ИИ   [🔍 адрес, дело, шифр, process_id]                        🔔 3   Иванов И.И. ▾ ┐
│ ◧ Дашборд      │ Дашборд инспектора                                     [+ Новая проверка]      │
│ ◧ Проверки     │ ┌──────────┬────────────┬──────────────┬──────────────┬────────────┬─────────┐ │
│ ◧ Уведомления  │ │Объектов 10│⛔ С нарушен.1│⚠ Требуют действий 8│✔ Без нарушений 1│◌ Нет результата 0│Ожид. верификации 7│
│ ── Админ. ──   │ └──────────┴────────────┴──────────────┴──────────────┴────────────┴─────────┘ │
│                │ [Индикация ▾][Статус процесса ▾][Статус находок ▾][Разделы ▾ ПЗ…СМ (дерево)]   │
│                │ [Дата: ▾протокол сформирован  01.09.2026 – 27.09.2026][Приоритет ▾][Сценарий ▾]│
│                │ [Инспектор ▾]  Пресеты: «Мои на верификации» «Красные за неделю»  [Сбросить]   │
│                │ ┌───────────────────────────────────────────────────────────────────────────┐ │
│                │ │Инд│Объект / адрес          │Дело  │Процесс         │Сценарий  │ПД РД ИД│Подтв│Канд (HIGH)│Уточн│Нет док│Обновлён│⋯│
│                │ │⛔ │Октябрьская ул., 103    │OKT103│🔒 Финализирован │SINGLE_ONLY│ – – ✓ │ 1 │ 0      │ 0 │ 0 │27.09 14:02│⋯│
│                │ │⚠ │Алтуфьевское ш., 79Б    │ALT79B│Протокол готов  │PD_RD_ONLY│ ✓ ✓ – │ 0 │ 1 (1)  │ 0 │ 2 │27.09 13:40│⋯│
│                │ │✔ │Полярная ул., 17        │POL17 │Вериф. завершена│PD_RD_ONLY│ ✓ ✓ – │ 0 │ 0      │ 0 │ 0 │26.09 18:11│⋯│
│                │ └───────────────────────────────────────────────────────────────────────────┘ │
│                │ [Находки по разделам × статус: stacked bar]   [Протоколы по неделям: bar]       │
```
Row menu (⋯): Открыть · Дозагрузить (gated) · Протокол · Экспорт ▸ PDF/DOCX/XML. The section filter uses the **matrix sections** from Params.section (ПЗ 23, СПЗУ 16, АР 14, КР 14, ИОС1 3, ИОС2 3, ИОС3 2, ИОС4 4, ИОС5 1, ПОС 9, ПОД 8, ООС 4, ППМ 13, ОДИ 9, ЗУ 8, СМ 1 = 132). "По разделам" means objects that have findings of the selected statuses in those sections. All filter state lives in the URL.

**S-03 Объект (создание/редактирование)**: modal with object_code (дело/стабильный id, unique), name, address, customer, contractor, permit_number, assigned inspector.

**S-04 Карточка объекта**
```
┌ ← Дашборд / Алтуфьевское ш., 79Б                       ⚠ Требует действий (i)   [Дозагрузить][Новая проверка] ┐
│ Дело ALT79B · Заказчик … · Подрядчик … · Разрешение № …                                                    │
│ Тек. проверка prc_… : [Протокол сформирован] · Сценарий PD_RD_ONLY · [ПД ✓][РД ✓][ИД –] · Протокол v2 · матрица v15 │
│ Tabs: Обзор | Проверки | Документы | Протоколы | Находки | Гипотезы | Журнал | Интеграция                  │
│ Обзор: counters by status (5 tiles, CONFIRMED is the only red one), completeness block, last events,       │
│        CTA «Перейти к верификации (1 кандидат)» (1 click to S-10), banner «Доступна матрица v16 — Перепроверить» │
│ Документы: registry table grouped by stage → discipline → document_code; revision chain shown as a         │
│        mini-timeline (ред.1 SUPERSEDED ─▶ ред.2 APPROVED ★эталон); columns: file, stage, discipline, шифр, │
│        ред., approval, date, листы/стр., подпись, SHA-256, status (PARSED/LOW_QUALITY/REJECTED); open viewer│
│ Находки: findings of the latest protocol; filters section/status/priority; row opens EvidenceCard drawer   │
│ Протоколы: versions list → S-08; Журнал: Audit timeline for the object; Интеграция: РиН sync log            │
```

**S-05 Мастер загрузки** (antd `Steps`; "append" mode skips step 1):
1. **Объект**: select or create (S-03).
2. **Файлы**: `Upload.Dragger` with multiple files. Client pre-checks: extension and magic bytes (`%PDF-`, `PK` for DOCX, `<?xml`), each file ≤ 50 МБ, package ≤ 200 МБ. The exact ТЗ-derived messages are «Формат не поддерживается. Допустимые форматы: PDF, DOCX, XML», «Превышен максимальный размер файла: 50 МБ», «Превышен общий лимит загрузки пакета: 200 МБ», and for a corrupted file «Файл повреждён. Загрузите файл повторно». SHA-256 is computed in a worker, then `POST /files/lookup` marks «Уже загружен, будет переиспользован». Uploads run 3 in parallel with per-file progress and cancel. Server rejections (antivirus, corrupted) appear inline on the file row.
3. **Реестр файлов** (registry builder, see §3.8):
```
│ [Импорт реестра CSV/XLSX/JSON] [Скачать шаблон] [Экспорт реестра]         Заполнено 11/12 · ⚠ 1 конфликт │
│ Файл              │SHA-256  │Стадия│Марка│Шифр документа        │Ред.│Статус утв.     │Дата утв. │Листы↔стр.│Предшеств.│Подпись│
│ P-2025-04-266-AR… │3fa1…9b07│PD ⓐ │АР ⓐ│П-2025-04-266-АР ⓐ(0.93)│1  │APPROVED        │12.03.2025│1–24 ↔ 1–24│—        │УКЭП   │
│ RD-KZh02.1.pdf    │…        │RD ⓐ │КЖ  │…                     │2  │FOR_CONSTRUCTION│…         │…         │ред.1 ▾  │нет    │
│ ⚠ Две утверждённые редакции «…-АР» без связи predecessor → будет CLARIFICATION_REQUIRED                    │
```
   ⓐ marks auto-suggested values (from the Module 1 metadata sniff) with a confidence score. The user confirms or edits them. Cells validate inline.
4. **Комплектность**: expected checklist per stage (ПД sections from §3; РД components from §4; ИД items from §5 and Приложение 19), each marked present or missing. Also shows the predicted upload statuses (`PD_UPLOADED/PD_PARTIAL/…`) and the **predicted scenario** (`FULL/PD_RD_ONLY/…/PARTIALLY_LOADED`), with the note that MISSING_EVIDENCE is not a violation.
5. **Запуск**: summary, then «Запустить проверку» (`Idempotency-Key`). Shows `process_id` and redirects to S-07.

**S-06/S-07 Монитор процессов.** The list shows process_id, object, created, status tag, progress bar, stage, files done/total, errors, duration. The detail page has a stepper (Загрузка → Антивирусная проверка → Парсинг/OCR → Извлечение по 132 параметрам → Сравнение → Протокол), a per-file table (status, pages, OCR quality `LOW_QUALITY/ABSTAIN`, cache hit, attempts x/3, error) and an event log. Admins also get «Повторить обработку файла». Polling rules are in §3.7.

**S-08 Протокол** (read-only; decisions happen in S-10)
```
┌ Протокол проверки № prc_…/v3  [Проект — не финализирован]           [Экспорт ▾][Сравнить версии][Верификация][«Завершить»*][Отменить финализацию**] ┐
│ Объект … · Дело … · Сформирован 27.09.2026 13:40 · Версии: матрица v15 · набор v3 · модель v2 · manifest ab12…ef │
│ ▸ Статус загрузки документов: [ПД ✓ PD_UPLOADED][РД ◐ RD_PARTIAL][ИД – ID_MISSING] + реестр входных файлов (SHA-256) │
│ ▸ Тип проверки: PD_RD_ONLY — «ПД и РД (ИД отсутствует)»                                                         │
│ ▸ Сводка: Подтверждённых нарушений 1 · Кандидатов 7 · Проверено отрицательных 118 · Нет документов 4 · Гипотез 2 │
│ (1) Комплектность и сопоставимость   [MISSING_EVIDENCE | NOT_APPLICABLE | NOT_COMPARABLE | CLARIFICATION_REQUIRED] │
│ (2) Предварительные кандидаты  (CANDIDATE; sorted HIGH→LOW, then section)                                      │
│ (3) Подтверждённые инспектором нарушения (CONFIRMED_VIOLATION)                                                 │
│ (4) Проверенные отрицательные результаты (NEGATIVE_VERIFIED)                                                  │
│ (5) Гипотезы свободного поиска (SUSPICION) — «не входят в число нарушений»                                     │
│ Перечень отсутствующих доказательств (MISSING_EVIDENCE) — отдельный список                                     │
│ Row expand → EvidenceCard: finding_id · код (M-041 · AR-41) · expected/actual/Δ · per source: role, file_id,    │
│   SHA-256, стадия, шифр, редакция, статус утверждения, лист/стр., bbox (crop thumbnail) · обоснование ·        │
│   уровень риска · approved_change_ref · решение инспектора (кто, когда, reason_code, комментарий) · system comment │
└ * «Завершить» shown when capabilities.can_finalize (Module 3 action); ** SUP/ADM only, ReasonModal            ┘
```

**S-09 Сравнение версий**: pick two versions (defaults: previous → current). Summary chips «+2 новых · −1 снято · 3 сменили статус · 1 изменилось значение · 4 изменения комплектности · +2 файла». The table shows finding_id, parameter, change type, and before → after (status, values, evidence file/revision). A toggle «только изменения». A meta block shows matrix_version, input_manifest_hash and the files added.

**S-10 Верификация (Module 3).** The shell provides the route, header context, `EvidenceViewer`, `EvidenceCard`, `ReasonModal`, `StatusTag` and hotkey infrastructure. Module 3 provides the page.

**S-11 Просмотр документа.** Full-screen `EvidenceViewer`: page thumbnails rail, zoom/pan, bbox list, «Показать фрагмент», «Скачать оригинал».

**S-12 Уведомления.** Bell drawer (latest 20, unread first) plus a full page with type and date filters and «Отметить все прочитанными».

**S-13 Матрица параметров**
```
┌ Матрица контроля · текущая версия v15 (27.09.2026 12:01, Петров А.А.: «уточнён порог ширины двери»)  [Экспорт XLSX][История версий] ┐
│ [Поиск: код/алиас/наименование][Раздел ▾][Приоритет ▾][Шаблон триггера ▾][Активность ▾][Порог из нормативной базы ▾] │
│ Код   │Алиас│Раздел│Параметр                      │Ед.│Шаблон     │min│max│Источник порога        │Приор.│Акт.│Изм.  │
│ M-041 │AR-41│АР    │Ширина эвакуационных выходов │м  │ABS_MIN    │0,9│ — │СП 1.13130.2020 (действ.)│HIGH │ ✓  │v15   │
│ M-002 │PZ-02│ПЗ    │Общая площадь здания          │м² │DELTA_PCT  │ — │1 %│вручную                 │HIGH │ ✓  │v1    │
│ M-055 │KR-55│КР    │Класс прочности бетона        │B  │ORDINAL    │ — │ — │шкала CONCRETE_CLASS    │HIGH │ ✓  │v1    │
```

**S-14 Редактор параметра** (right drawer, 720 px, anchored sections):
1. *Идентификация*: code (read-only), alias, section (read-only for the base 132), parameter_name, unit, data_type (`number|string|boolean|coordinate|enum`), review_priority (segmented control with the fixed hint), is_active (switch; turning it off needs a reason and shows «Параметр будет исключён из следующих проверок; в протоколе он будет указан как NOT_APPLICABLE с основанием "деактивирован в матрице vN"»).
2. *Источники*: source_pd, source_rd, source_id.
3. *Триггер*: trigger_logic (human text, as in Приложение 1). The machine rule shows a template select, then dynamic fields (reference stage, compared stages, direction, tolerance, ordinal scale, sub-values). A live sentence renders the rule: «Кандидат формируется, если значение в РД или ИД меньше 0,9 м (порог: СП 1.13130.2020, действует с …)». «Проверить правило» takes sample values and returns the engine verdict through the server.
4. *Пороговые значения*: min_value and max_value (ru decimal) with their meaning for the chosen template. «Источник порога» is either «задан вручную» or «из нормативной базы» (pick THRESHOLD links; a validity timeline shows current and upcoming values). An «Оценить влияние» button opens the impact preview.
5. *Нормативные ссылки*: sp_reference, gost_reference, fz_reference, other_normative. A «Выбрать из нормативной базы» picker fills the text and creates a REFERENCE link.
6. *Извлечение*: regex_pattern (monospace, max 255) with a tester (sample text, matches highlighted by the Python engine) and semantic anchors as tags.
7. *История*: AuditTimeline with field diffs and the matrix_version for each change, plus «Восстановить значения».

The footer has «Сохранить и опубликовать». It opens a ReasonModal listing each changed field (old → new), then publishes. The toast reads «Опубликована матрица v16. Изменения применятся к следующим проверкам». A 409 opens a conflict dialog (their version vs yours, reload).

**S-15/S-16 Нормативная база.**
- Table columns: document_number, document_name, section (пункт), parameter_name, min/max and unit, validity with a state chip (Действует / Будущая редакция / Истекла / Деактивирована), linked parameters, «Проверено экспертом» flag, updated.
- Filters: «Действует на дату» (date), doc type (СП/ГОСТ/ФЗ/СанПиН/ПП/иное), search, «показать неактивные».
- The editor drawer holds every §10.10 field plus unit, doc type, verified, and linked params with a role (THRESHOLD/REFERENCE).
- Deactivate / activate need a reason. Before deactivating, a dependents warning appears, for example: «Используется как источник порога для M-041, M-105. После деактивации будет применяться значение параметра 0,9 м» or «…порог отсутствует → проверка по M-041 вернёт NOT_COMPARABLE».
- The history tab mirrors S-14.

**S-17 Логические правила.** The list shows rule_name, condition/expected rendered as text, normative, priority and active. The editor has a react-querybuilder **condition** builder and an **expected** builder over the facts catalog (for example `M-007 Этажность (надземная)`, `has_elevator`). It also has a normative picker, `review_priority`, `is_active`, and a test panel where the admin picks a process and sees whether the rule would raise a SUSPICION with its facts. Example seeded rule: «Если этажей > 10 → должен быть лифт».

**S-18 Версии матрицы.** Table of version, published_at, author, reason, change chips, SHA-256 and «используется в N протоколах». The detail view shows a frozen snapshot (132 rows, normative, rules), a diff against any other version, and «Восстановить как новую версию».

**S-19 Журнал аудита.** Filters: user, action, entity type, object, date, IP. Rows expand to details (before/after diff, reason, request_id, user_agent). CSV export.

**S-20 Пользователи.** Table of users and roles; create, deactivate, reset password, assign roles and the `model.approve` permission.

**S-21 Мониторинг.** Tiles for service status, RabbitMQ queue depth, 5xx per 5 minutes, p95 latency, active sessions, latest alerts; buttons «Открыть Grafana / Kibana».

**S-22 ИАИС «РиН».** Queue of PENDING_SYNC protocols with attempt numbers, the next retry (1/5/15 min schedule) and the last error; «Повторить сейчас»; incoming-document events.

**S-23 Настройки.** Upload limits (read-only 50/200 МБ), indicator policy, polling intervals, notification preferences.

**S-24..S-29 ML screens** are covered in §3.14.

### 3.7 Data fetching, polling, caching, errors

- **Query keys**: `['objects', filters]`, `['object', id]`, `['process', id, 'status']`, `['protocol', id]`, `['protocolDiff', a, b]`, `['notifications']`, `['params', filters]`, `['param', code]`, `['normative', filters]`, `['matrixVersions']`.
- **Adaptive polling** (the pull model, §1.4):

| Resource | Interval | Stop / slow-down |
|---|---|---|
| process status | 2 s while PENDING-with-uploads/PARSING; 10 s after 2 min | stop at READY/VERIFYING/COMPLETED/FINALIZED, or on a terminal file error |
| object card (active process) | 10 s | stop when nothing is running |
| notifications | 15 s visible tab; paused when hidden (`refetchIntervalInBackground:false`) | — |
| dashboard list | 30 s | — |
| export job | 1 s → 3 s | stop at READY/FAILED |

  Every polled endpoint returns an `ETag`; the mutator sends `If-None-Match`, and a 304 costs about 1 ms of server time. Budget at 100 inspectors: about 7 req/s for notifications, about 3 req/s for the dashboard, plus bursts for active processes. This is comfortably within p95 ≤ 200 ms.
- **Mutations** invalidate precise keys. A verification decision invalidates `['protocol', id]` and `['objects']`, so the colour updates on the next dashboard poll.
- **Errors**: the backend returns RFC 7807 `application/problem+json` `{type,title,status,detail,code,errors[],request_id}`. The domain error catalog maps codes to RU messages and a UI treatment:

| code | UI |
|---|---|
| UNSUPPORTED_FORMAT, FILE_TOO_LARGE, PACKAGE_TOO_LARGE, FILE_CORRUPTED, AV_INFECTED | inline on the file row with the ТЗ wording |
| PROCESSING_TIMEOUT | process detail: «Повторная попытка 1 из 2…», then «Обработка не удалась, администратор уведомлён» |
| STATUS_FORBIDDEN (e.g. upload to FINALIZED) | modal «Протокол финализирован — дозагрузка невозможна. Создать новую проверку?» |
| CONFLICT (row_version) | conflict dialog |
| VALIDATION_ERROR | field errors mapped onto the form |
| FORBIDDEN / UNAUTHENTICATED | 403 page / session modal |
| INTEGRATION_UNAVAILABLE | chip «PENDING_SYNC — повтор в 14:35»; the decision is unaffected |
| network / 5xx | retry ×2 for GET with backoff; offline banner; mutations are never auto-retried (Idempotency-Key makes a manual retry safe) |

- The **request id** (`X-Request-Id`, uuid v7) is generated per call and shown in error toasts («Код обращения: …») for support and for tracing in Kibana.

### 3.8 Upload wizard and registry builder: flow and contracts

1. `POST /api/v1/documents/upload` (ТЗ path; multipart `files[]`, `object_id`, optional `process_id` for append, optional `registry`) returns `202 {process_id, status:"PENDING", files:[{file_id, file_name, sha256, status:"ACCEPTED"|"REJECTED", rejection:{code,message}}]}`. A new process starts in `PENDING` («Документы загружены, проверка не начата»), which is exactly the ТЗ semantics.
2. Module 1 runs a fast **metadata sniff** (title block text, filename patterns) and exposes suggestions: `GET /processes/{id}/registry` returns rows `{file_id, fields:{doc_stage:{value,confidence,source:"AUTO"|"USER"|"IMPORT"}, …}, validation:[…]}`. The grid polls every 2 s until every row has `sniff_status=DONE`.
3. The user edits the grid, or imports a file with `POST /processes/{id}/registry/import`. That returns parsed rows matched by file_name/SHA-256, with unmatched rows on both sides listed. Saving is `PUT /processes/{id}/registry` (full replace, If-Match). `GET /processes/{id}/registry?format=csv|xlsx|json` exports it, and `GET /registry/template?format=xlsx` gives the template.
4. Validation (server-authoritative, mirrored client-side): the 11 mandatory fields (object_id, file_id/file_name/SHA-256, doc_stage ∈ PD/RD/ID, discipline, document_code, revision, approval_status ∈ DRAFT/APPROVED/FOR_CONSTRUCTION/SUPERSEDED/CANCELLED, approval_date, sheet_page_range, predecessor/successor, signature_status). The revision chain must be acyclic. Two APPROVED/FOR_CONSTRUCTION revisions of the same code without a link produce the warning «CLARIFICATION_REQUIRED». A SUPERSEDED revision marked as reference is an error. A missing registry gives a banner: «Без реестра пакет будет принят со статусом CLARIFICATION_REQUIRED» (the user may still proceed, per 03).
5. `GET /processes/{id}/completeness-preview` returns `{predicted_scenario, upload_status:{PD,RD,ID}, checklist:[{stage, group, expected_item, present, file_ids[]}]}`.
6. `POST /processes/{id}/start` (Idempotency-Key) moves the process to `PARSING`. API clients such as the РиН pull may call upload with `auto_start=true` plus a registry. That is a Module 1/6 decision; the UI always uses an explicit start.
7. **Append mode**: the same steps 2–5 against an existing `process_id`. The entry button is enabled only when `capabilities.can_upload` is true (PENDING, READY, VERIFYING, COMPLETED). For FINALIZED the UI offers «Создать новую проверку».

### 3.9 Protocol viewer, versions, diff, export

- **Consumed protocol JSON** (owned by Module 2; fields B08 needs): `protocol_id, process_id, object{…}, version, status, created_at, finalized_at, versions{matrix_version,dataset_version,model_version,input_manifest_hash}, scenario, upload_status{PD,RD,ID}, file_registry[], summary{violations_confirmed,candidates,negative_verified,missing_evidence,not_applicable,not_comparable,clarification,suspicions}, completeness[], findings[{finding_id, evidence_group_id, param_code, section, finding_status, inspector_status, completeness_status, review_priority, expected_value, actual_value, delta, unit, rationale, approved_change_ref, decision{user_id,user_name,timestamp,reason_code,comment}, system_comment, related_param_codes[], sources[{role:"EXPECTED"|"ACTUAL", file_id, sha256, stage, document_code, revision, approval_status, sheet, page, bbox_polygon_norm:[[x0,y0,x1,y1],…] | polygon[[x,y]…]}]}], suspicions[], sync{status,attempts,next_retry_at}`.
- **Versions**: `GET /processes/{id}/protocols` lists `[{protocol_id, version, status, created_at, finalized_at, matrix_version, …, change_reason: "INITIAL"|"INCREMENTAL_UPLOAD"|"FINALIZED"|"UNFINALIZED"|"RECHECK_MATRIX"}]`. The recommended rule for Modules 2/3/9 is that a new version is created on generation, incremental update, finalization, unfinalization and matrix re-check, not on each decision. Decisions between versions stay visible as the working state and in audit.
- **Diff**: `GET /protocols/{id}/diff?against={id2}` returns `{from, to, summary{added,removed,status_changed,value_changed,completeness_changed,files_added}, items[{key, finding_id, param_code, change, before, after}], meta_changes{…}}`. The pure function `diffProtocols(a,b)` lives in `packages/domain` and is shared by the API and a client fallback. It keys by `evidence_group_id` and falls back to `param_code + object + source document_code`. **Contract for Module 2: `finding_id`/`evidence_group_id` must be stable across versions.**
- **Export**: `GET /protocols/{id}/export?format=pdf|docx|xml`.
  - It returns `200` with the file (`Content-Disposition: attachment; filename*=UTF-8''Протокол_ALT79B_prc…_v3.pdf`) when it is cached by `(protocol_id, version, format, template_version)`.
  - Otherwise it returns `202 {export_id}` and the UI polls `GET /exports/{export_id}`, which gives `{status, download_url}`.
  - Exports are pre-generated in the background on `protocol.ready`/`protocol.finalized`, so they are usually instant. Generation stays within ≤30 s (§11 #5).
  - Non-finalized protocols carry the watermark «ПРОЕКТ — протокол не финализирован».
  - **Renderer** (Python worker `protocol-render`, RabbitMQ `protocol.export.requested` → `protocol.export.completed|failed`):
    - DOCX: docxtpl (Jinja in a Word template; free image support, unlike docxtemplater's paid image module). Evidence crops are embedded as PNG rendered by PyMuPDF.
    - PDF: LibreOffice headless converts the DOCX (fonts PT Astra Serif / Liberation, embedded), so both formats share one layout.
    - XML: lxml builds from the protocol JSON and validates against `inspector-protocol-1.0.xsd`, which is published at `/api/v1/schemas/protocol.xsd`.
  - The **template is editable in Word** once Приложение № 2 arrives.

### 3.10 EvidenceViewer (shared with Module 3)

- **Renderer**: OpenSeadragon with a custom tile source, `GET /api/v1/files/{file_id}/pages/{page}/tiles/{z}/{x}_{y}.webp`. Tiles are rendered by PyMuPDF from the **visible page area after CropBox/MediaBox/Rotate** and cached on disk/Redis by `(sha256,page,z,x,y)`.
  - A page descriptor `GET /files/{file_id}/pages/{page}` returns `{width_pt, height_pt, rotation, tile_size:512, max_level, dpi_levels}`.
  - Fallback for Phase 1: a single `…/pages/{page}/image?dpi=150` used as an OSD simple image.
  - Measured on the pilot: A0 sheets with 42k–113k vector paths render in 0.6–1.8 s at 150 dpi and 0.1–0.2 s per 300-dpi tile.
  - pdf.js was rejected as the primary renderer: re-rendering 100k-path pages at each zoom step is slow, canvas size limits blur A0 at high zoom, and bbox alignment would depend on two geometry engines (pdf.js vs MuPDF).
- **Overlay**: an SVG layer in OSD viewport coordinates. Normalized `[x0,y0,x1,y1]` or polygons map to `(x·W, y·H)`, so there is zero math on rotated pages because tiles are already in visible-area space. Styles follow the role colours. Labels read «ПД · ожидаемое», «РД · фактическое». Hovering a bbox highlights the matching row in the card.
- **Features**: fit-to-bbox with padding («Показать фрагмент»), next/prev bbox, page rail, **synchronised side-by-side mode** (EXPECTED left, ACTUAL right, optional linked zoom), crop thumbnails (`…/pages/{p}/crop?bbox=&dpi=150`) in protocol tables, keyboard (+/−/0, arrows, `[`/`]` for bbox), and «Скачать оригинал» (`GET /files/{id}/content`, Range-enabled, authorised).
- **Other formats**: DOCX is shown through a server-converted `preview.pdf`. Module 1 must compute DOCX coordinates on that preview (contract). XML is shown in a syntax-highlighted tree with `xpath` locators instead of bbox (evidence fragment `locator:{type:"xpath", value}`).
- **Auth**: tiles are fetched with `loadTilesWithAjax:true, ajaxWithCredentials:true` using the cookie session.

### 3.11 Notifications

- **Table** `notifications(id, user_id, type, severity, title, body, entity_type, entity_id, link, dedup_key, created_at, read_at)`. Fan-out to users is by role or assignment.
- **Types**:
  - PROTOCOL_READY: assigned inspector, or all inspectors of the object if none is assigned. Link to S-10.
  - PROTOCOL_UPDATED: after an incremental update.
  - UPLOAD_REJECTED.
  - PROCESSING_FAILED: sent to admins after a timeout and 2 retries.
  - NEW_DOCUMENTS_AFTER_FINALIZATION: action «Создать новую проверку».
  - SYNC_PENDING / SYNC_FAILED: sent to admins and the inspector.
  - MATRIX_UPDATED: sent to inspectors with open processes: «Опубликована матрица v16 — доступна перепроверка».
  - DATASET_DRAFT_ITEMS: sent to the curator.
  - MODEL_PENDING_APPROVAL: sent to holders of model.approve.
  - WEEKLY_REPORT_READY: sent to ML engineers.
- **Endpoints**: `GET /api/v1/notifications?unread_only=&cursor=` returns `{items[], unread_count, next_cursor}`, plus `POST /notifications/{id}/read` and `POST /notifications/read-all`. SSE `GET /notifications/stream` is an optional flag.
- **UI**: bell badge, antd `notification` toast for new items while the app is open, and optional browser Notification API (asked only on a user click).

### 3.12 Module 8: normative base and matrix management (detailed)

#### 3.12.1 Data model (PostgreSQL; ТЗ names kept, extensions justified)

```sql
-- §8.1 Params: all ТЗ columns verbatim + extensions (marked ext)
CREATE TABLE params (
  id serial PRIMARY KEY,
  code varchar(20) UNIQUE NOT NULL,          -- 'M-041' (Приложение 1 is canonical)
  alias_code varchar(20) UNIQUE,             -- ext: 'AR-41' (ТЗ §8.2 style: PZ/SPZU/AR/KR/IOS1-5/POS/POD/OOS/PPM/ODI/ZU/SM)
  section varchar(50) NOT NULL,              -- 'АР', 'ИОС4', …
  parameter_name varchar(255) NOT NULL, unit varchar(20),
  source_pd text, source_rd text, source_id text,
  trigger_logic text NOT NULL,
  review_priority varchar(20) NOT NULL CHECK (review_priority IN ('HIGH','MEDIUM','LOW')),
  sp_reference text, gost_reference text, fz_reference text, other_normative text,
  data_type varchar(20) NOT NULL CHECK (data_type IN ('number','string','boolean','coordinate','enum')),
  min_value double precision, max_value double precision,
  regex_pattern varchar(255),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  trigger_rule jsonb NOT NULL,               -- ext: typed machine rule (JSON Schema v1, §3.12.2)
  semantic_anchors text[] NOT NULL DEFAULT '{}',  -- ext: Sentence-BERT anchors editable w/o code
  row_version int NOT NULL DEFAULT 1, updated_by int,   -- ext: optimistic lock, author
  CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
);
-- §10.10 Normative_Base: ТЗ columns + extensions
CREATE TABLE normative_base (
  id serial PRIMARY KEY,
  document_name text NOT NULL, document_number varchar(100) NOT NULL,
  section varchar(100),                      -- clause, e.g. 'п. 4.2.5'
  parameter_name varchar(255) NOT NULL,
  min_value double precision, max_value double precision,
  effective_from date NOT NULL, effective_to date,
  unit varchar(20),                          -- ext
  doc_type varchar(10) CHECK (doc_type IN ('SP','GOST','FZ','SANPIN','PP','OTHER')),  -- ext
  is_active boolean NOT NULL DEFAULT true, deactivation_reason text,                  -- ext: "деактивировать"
  expert_verified boolean NOT NULL DEFAULT false,                                     -- ext: seeded rows start unverified
  row_version int NOT NULL DEFAULT 1, created_at timestamptz, updated_at timestamptz, created_by int, updated_by int,
  CHECK (effective_to IS NULL OR effective_from <= effective_to),
  CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
);
CREATE TABLE param_normative_links (          -- ext: M:N, temporal succession of thresholds
  param_id int REFERENCES params(id), normative_id int REFERENCES normative_base(id),
  role varchar(10) NOT NULL CHECK (role IN ('THRESHOLD','REFERENCE')),
  PRIMARY KEY (param_id, normative_id)
);  -- app rule: THRESHOLD links of one param must not overlap in validity
-- §10.9 Logical_Rules: ТЗ columns + extensions
CREATE TABLE logical_rules (
  id serial PRIMARY KEY, rule_name varchar(255) NOT NULL,
  condition jsonb NOT NULL, expected jsonb NOT NULL,      -- JSONLogic subset
  normative_base text, is_active boolean NOT NULL DEFAULT true,
  normative_id int REFERENCES normative_base(id), description text,
  review_priority varchar(20) DEFAULT 'MEDIUM', builder_state jsonb,
  row_version int NOT NULL DEFAULT 1, created_at timestamptz, updated_at timestamptz, created_by int, updated_by int
);
CREATE TABLE ordinal_scales (code varchar(40) PRIMARY KEY, name text, ordered_values text[] NOT NULL); -- ext
CREATE TABLE matrix_versions (               -- ext: immutable published snapshots
  version int PRIMARY KEY, parent_version int, snapshot jsonb NOT NULL, snapshot_sha256 char(64) NOT NULL,
  change_summary jsonb NOT NULL, reason text NOT NULL, published_by int NOT NULL, published_at timestamptz NOT NULL
);
-- also ext: notifications, export_jobs(id, protocol_id, format, template_version, status, file_path, sha256, created_by, created_at),
-- saved_filters(id, user_id, name, query jsonb); objects gets indicator_color, indicator_reasons jsonb,
-- indicator_counters jsonb, indicator_updated_at, object_code, assigned_inspector_id (Objects owned by Module 1).
```

#### 3.12.2 Typed trigger rule (`trigger_rule`, JSON Schema v1)

The 132 trigger texts were auto-classified and then corrected by hand (a preliminary pass; the T20 seed finalises it):

| Template | Meaning of `min_value`/`max_value` | ≈N | Examples |
|---|---|---|---|
| `ABS_MIN` / `ABS_MAX` / `ABS_RANGE` (+ `sub_values[]`) | absolute normative limits | 16 | M-041 min 0,9 м; M-030 min 4,2 м; M-040/M-104 min 1,2 м; M-118 max 0,014 м; M-048 riser max 150 мм + tread min 300 мм; M-042 2,0/1,9 м |
| `RATIO_MIN` | minimum share | 1 | M-038 ≥ 10 % МГН places |
| `DELTA_PCT` | allowed deviation, % (max) | 7 | M-002 1 %; M-024/025/093/132 5 %; M-067 2 %; M-082 10 % |
| `DELTA_ABS` | allowed absolute deviation (max) | 2 | M-001 0; M-034 0,5 м |
| `DIRECTIONAL` (`direction: DECREASE\|INCREASE\|ANY`) | tolerance around the reference stage (default 0) | ≈50 | M-058 slab thickness decrease; M-014 power increase; M-007 floors mismatch |
| `ORDINAL` (`scale`, `direction: DOWNGRADE`) | n/a (scale order in `ordinal_scales`) | ≈15 | M-055 B35→B30; M-103 EI60→EI30; M-050/M-107 КМ; M-021/M-124 energy class |
| `PRESENCE` | n/a (element present in reference ⇒ required in compared) | ≈16 | M-120 handrails; M-122 tactile strips; M-129 meters |
| `EXTERNAL_STATUS` | n/a (needs data from external systems) | 4 | M-098…M-101 (АИС «ОСИГ», ГЛОНАСС/РНИС, КПТС, ТРПО) |
| `SEMANTIC` | n/a; comparison by ML/CV only | ≈21 | M-043/M-106 door direction; M-081 crane zone; M-102 fire compartments |

```json
{ "schema_version": 1, "template": "ABS_MIN",
  "reference_stage": "PD", "compare_stages": ["RD","ID"],
  "direction": null, "ordinal_scale": null,
  "sub_values": [], "threshold_source": "NORMATIVE",      // NORMATIVE | PARAM
  "applicability": null }                                   // optional JSONLogic over object facts (NICE)
```
Only about 26 parameters carry explicit numeric thresholds. The UI therefore says plainly which part of each rule is editable without code: thresholds and tolerances for numeric templates; scales for ordinal ones; priority, activity, regex and anchors for all of them. **Contract for Module 2 (comparison) and Module 1 (extraction): thresholds, tolerances, scales, regex and anchors are read from the matrix snapshot at run time and are never hard-coded.**

#### 3.12.3 Threshold resolution (resolves the duplicate min/max in Params vs Normative_Base)
At evaluation time, for a parameter with `threshold_source = NORMATIVE` the engine picks the THRESHOLD-linked Normative_Base row that satisfies `is_active` and `effective_from ≤ D ≤ effective_to (or null)`, where D is the reference date (default: protocol run date, setting `normative_date_basis`). If there is none, it falls back to `params.min_value/max_value`. If no threshold exists at all for a numeric template, the result is `NOT_COMPARABLE` with the basis «порог не задан». The applied threshold and its source (document, clause, validity) go into the evidence card and the protocol. The snapshot carries every validity window, so the engine resolves thresholds itself and the snapshot does not depend on a date.

#### 3.12.4 Versioning, publish flow, effect on checks
1. `PATCH /admin/params/{code}` with `If-Match: "rv-7"` and `{changes, reason}`.
2. One DB transaction runs under `pg_advisory_xact_lock(matrix)`: validate, update the row (row_version+1), build the snapshot, compute the SHA-256, `INSERT matrix_versions (max+1)`, `INSERT audit_log` (action `PARAM_UPDATED`, details `{entity_type, entity_id, before, after, reason, matrix_version}`), and `INSERT outbox`.
3. After commit, the outbox relay publishes `matrix.version.published` and the API sets Redis `matrix:current = vN` (the snapshot is cached per version).
4. Engines (Modules 1, 2, 5) load `GET /api/v1/matrix/versions/current` at **run start** and subscribe to the event to reload regex, anchors and rules. A process **pins** the matrix_version at its first run, and incremental updates reuse the pinned version, so protocol versions stay consistent (§9.2 p.1). Open processes show «Доступна матрица vN — Перепроверить», which starts a full re-run and creates a new protocol version with `change_reason=RECHECK_MATRIX`.
5. The same flow applies to Normative_Base, Logical_Rules and Ordinal_Scales changes. Each save means one version (simple and auditable). An XLSX bulk import, when implemented, is published as a single version.

#### 3.12.5 Validation rules (shared zod/JSON Schema; the server is authoritative)
- `code` matches `^M-\d{3}$` and `alias_code` matches `^[A-Z]{2,4}\d?-\d{2,3}$`.
- `review_priority` is in the enum. `data_type` is in the enum. Numeric fields are allowed only for number/coordinate data types. min ≤ max.
- `unit` is at most 20 characters (all 132 current units fit; the longest is 14).
- `regex_pattern` is at most 255 characters and must compile in **Python `re`**. It is checked by the ML service through `POST /admin/params/{code}/regex-test`, with a timeout for ReDoS safety.
- `trigger_rule` must pass the JSON Schema. The template must be compatible with `data_type`. ORDINAL needs an existing scale. ABS_* needs at least one bound or an active THRESHOLD link.
- Normative_Base: `effective_from ≤ effective_to`. Overlapping THRESHOLD validity for the same parameter is rejected. Deactivating a row that is referenced shows its dependents and needs an explicit confirmation.
- `reason` is mandatory on every write (≥10 characters). `If-Match` is required, otherwise the server returns 428.

#### 3.12.6 Admin REST endpoints (B08 backend; OpenAPI-validated)

| Method & path | Request | Response |
|---|---|---|
| GET `/api/v1/admin/params?section=&priority=&template=&is_active=&q=` | — | `{items:[ParamRow{code,alias_code,section,parameter_name,unit,data_type,template,min_value,max_value,threshold:{value_min,value_max,source,normative_ref,valid_to},review_priority,is_active,last_changed_version}], matrix_version}` |
| GET `/api/v1/admin/params/{code}` | — | full Param + links + ETag |
| PATCH `/api/v1/admin/params/{code}` | If-Match; `{changes:{…§8.1 fields, trigger_rule, semantic_anchors}, reason}` | `{param, matrix_version}`; 409 CONFLICT / 422 VALIDATION_ERROR |
| POST `/api/v1/admin/params/{code}/rule-test` | `{trigger_rule?, min_value?, max_value?, samples:[{stage,value}]}` | `{verdicts:[{finding_status, explanation}]}` (evaluated by the Module 2 engine) |
| POST `/api/v1/admin/params/{code}/regex-test` | `{regex_pattern, sample_text}` | `{valid, matches:[{start,end,groups}], error}` |
| POST `/api/v1/admin/params/{code}/impact-preview` | `{min_value?, max_value?, trigger_rule?}` | `{evaluated_checks, flips:[{object_id, process_id, finding_id, from, to}]}` (numeric templates, over stored Checks values) |
| GET `/api/v1/admin/params/export?format=xlsx` | — | file |
| GET `/api/v1/admin/normative-base?q=&doc_type=&active_on=&include_inactive=` | — | `{items[], total}` |
| POST `/api/v1/admin/normative-base` | `{document_name, document_number, section, parameter_name, min_value, max_value, unit, doc_type, effective_from, effective_to, links:[{param_code, role}], reason}` | `{row, matrix_version}` |
| PATCH `/api/v1/admin/normative-base/{id}` | If-Match; `{changes, reason}` | `{row, matrix_version}` |
| POST `/api/v1/admin/normative-base/{id}/deactivate` · `/activate` | `{reason, effective_to?}` | `{row, matrix_version, affected_params[]}` |
| GET/POST `/api/v1/admin/logical-rules`, PATCH `/{id}`, POST `/{id}/deactivate` · `/activate` | same pattern | same pattern |
| POST `/api/v1/admin/logical-rules/{id}/test` | `{process_id}` or `{facts}` | `{condition_result, expected_result, would_raise_suspicion}` (Module 5 evaluator) |
| GET `/api/v1/facts/catalog` (Module 5) | — | `[{key, label, type, source_param_code?}]` |
| GET `/api/v1/admin/ordinal-scales`, PUT `/{code}` | `{ordered_values, reason}` | new matrix_version |
| GET `/api/v1/matrix/versions`, `/current`, `/{v}`, `/{v}/diff?against=` | — | list / snapshot / diff |
| POST `/api/v1/matrix/versions/{v}/restore` | `{reason}` | `{matrix_version}` (new) |
| GET `/api/v1/admin/{entity}/{id}/history` | — | audit entries with field diffs (reads Module 9 Audit_Log) |

#### 3.12.7 Dashboard, notification and export endpoints (B08 backend)

| Method & path | Notes |
|---|---|
| POST `/api/v1/auth/login` · `/logout`, GET `/api/v1/auth/me` | platform auth. `me` returns `{id, full_name, roles[], permissions[]}` |
| GET `/api/v1/dashboard/summary?…filters` | `{objects_total, by_color:{RED,YELLOW,GREEN,NONE}, protocols_awaiting_verification, my_pending_candidates, pending_sync, by_section:[{section, CANDIDATE, CONFIRMED_VIOLATION, NEGATIVE_VERIFIED, MISSING_EVIDENCE, …}], weekly:[{week, created, finalized}]}` |
| GET `/api/v1/objects?q=&color=&process_status=&finding_status=&completeness_status=&section=&priority=&scenario=&sync_status=&inspector_id=&date_field=&date_from=&date_to=&sort=&page=&page_size=` | `{items:[{id, object_code, name, address, customer, contractor, permit_number, indicator:{color, reasons[], label}, counters:{confirmed, candidates, candidates_high, clarification, missing_evidence, not_comparable, suspicions}, upload_status:{PD,RD,ID}, last_process:{process_id,status,scenario,updated_at,capabilities}, last_protocol:{protocol_id,version,status,matrix_version,created_at,finalized_at,sync_status,matrix_outdated}, assigned_inspector}], total}` |
| POST `/api/v1/objects`, GET/PATCH `/api/v1/objects/{id}`, GET `/api/v1/objects/{id}/findings?…` | Objects (Module 1 table, B08 routes if Module 1 agrees) |
| GET `/api/v1/processes?object_id=&status=&from=&to=` | list for S-06 (Module 1 owns processes; B08 needs this list) |
| GET `/api/v1/processes/{id}/status` | **the monitoring endpoint** (Module 1): `{process_id, object_id, status, scenario, upload_status, capabilities{can_upload,can_verify,can_finalize,can_unfinalize}, progress{stage,pct,files_total,files_done,eta_seconds}, files[{file_id,file_name,sha256,status,pages,ocr_quality,cache_hit,attempts,error}], latest_protocol{protocol_id,version,status}, matrix_version, updated_at}` + ETag |
| GET `/api/v1/notifications…`, POST `…/{id}/read`, `…/read-all` | §3.11 |
| GET `/api/v1/protocols/{id}/diff?against=` | §3.9 |
| GET `/api/v1/protocols/{id}/export?format=`, GET `/api/v1/exports/{export_id}`, GET `/api/v1/exports/{export_id}/file` | §3.9 |
| GET `/api/v1/schemas/protocol.xsd` | XSD for the XML export |
| POST `/api/v1/client-logs` | batched client errors and web vitals (to Module 11) |
| POST `/api/v1/telemetry/ux` | usability events `{protocol_id, finding_id, event, ts}` for the ≤3-click and ≤30-min proof (UI-85) |

#### 3.12.8 RabbitMQ (exchange `inspector.events`, topic, durable; envelope `{event_id, type, version:1, occurred_at, request_id, actor_user_id, payload}`)

| Routing key | Direction | Payload | Consumers |
|---|---|---|---|
| `matrix.version.published` | **produced** by B08 API (outbox) | `{matrix_version, parent_version, changed:{params:[codes], normative_ids:[], logical_rule_ids:[], ordinal_scales:[]}, reason, published_by}` | Module 1 (regex/anchors reload), Module 2 (rules), Module 5 (logical rules), B08 notifications (MATRIX_UPDATED) |
| `protocol.export.requested` | produced | `{export_id, protocol_id, version, format, template_version}` | protocol-render worker |
| `protocol.export.completed` / `.failed` | consumed | `{export_id, file_path, sha256}` / `{export_id, error}` | B08 API |
| `protocol.ready`, `protocol.updated` | consumed | `{process_id, protocol_id, version, object_id, change_reason}` | indicator recompute, notifications, export pre-generation |
| `verification.decided`, `protocol.finalized`, `protocol.unfinalized` | consumed | `{protocol_id, finding_id?, status, actor}` | indicator recompute, export invalidation |
| `process.status.changed` | consumed | `{process_id, from, to}` | object card cache invalidation |
| `file.rejected`, `process.failed` | consumed | `{process_id, file_name, code, message}` / `{process_id, file_id, attempts, error}` | notifications (inspector / admin) |
| `rin.sync.status`, `rin.documents.arrived` | consumed | `{protocol_id, sync_status, attempt, next_retry_at}` / `{object_id, protocol_status, files[]}` | notifications, sync chip |
| `dataset.draft.item_added`, `model.pending_approval`, `report.weekly.ready` | consumed | ids and summary | notifications (curator / approver / ML) |

### 3.13 Process-status to UI-action map (from the §9.1 table; the server returns `capabilities`, the UI never recomputes them)

| Process status | Дозагрузка | Верификация | UI actions |
|---|---|---|---|
| PENDING | Да | Нет | edit registry, add files, «Запустить проверку» |
| PARSING | Нет | Нет | progress only; upload disabled with tooltip «Идёт обработка документов» |
| READY | Да | Да | open protocol, «Перейти к верификации», dozagruzka, draft export |
| VERIFYING | Да (до финализации) | Да | same as READY |
| COMPLETED | Да | Нет | «Завершить» (finalize), dozagruzka, draft export |
| FINALIZED | Нет | Нет | final export, РиН sync status, «Отменить финализацию» (SUP/ADM, reason), «Создать новую проверку» |

### 3.14 ML and curator screens (frontend "hooks"; data from Modules 4 and 10)

- **S-24 Журнал отклонений** (Rejection_Log: violation_id, rejection_reason, ai_verdict, suggested_fix, retraining_status). Filters: reason_code, section, param, date. Charts by reason_code.
- **S-25 Спорные случаи** (Dispute_Log: inspector_comment, ai_comment, resolution_status, resolved_by). Status workflow chips; link to the evidence card.
- **S-26 Курирование набора**: queue of draft Dataset_Items (evidence_group, gold_label POSITIVE for CONFIRMED_VIOLATION / NEGATIVE for NEGATIVE_VERIFIED, reason_code, expert_id, object_group_id). Each item gets a completeness check (all mandatory card fields present, per СХЕМА GOLD), the EvidenceCard preview, and the actions «Принять в набор» / «Отклонить» / «Вернуть эксперту». The ТЗ rule is enforced visibly: CANDIDATE, SUSPICION, MISSING_EVIDENCE and unfinished decisions are never listed as eligible.
- **S-27 Версии наборов**: the «Выпустить dataset_version» wizard shows the object-level split preview (TRAIN/VALIDATION/HIDDEN_TEST counts; one object stays in one split), category coverage and split hashes, then asks for confirmation. The list shows version, date, sizes, hashes and author.
- **S-28 Реестр моделей**: for each model_version, the §14.3 metrics against thresholds (OCR CA ≥ 0,95; EM ≥ 0,90; linkage ≥ 0,95; localization ≥ 0,95; P ≥ 0,90; R ≥ 0,80; F1 ≥ 0,85; FPR ≤ 0,10), with sample size, coverage/abstention and 95 % CI. It also shows per-category regression against the previous model (ΔRecall ≥ −2 pp, ΔFPR ≤ +2 pp) as a pass/fail matrix, plus model/dataset/matrix versions, hashes and the link to the previous model. «Подписать решение о публикации» is available only when every gate passes, requires `model.approve` and password re-entry, and records the approver, time and comment. «Откатить к vN» is also available. Automatic publication does not exist in the UI.
- **S-29 Еженедельные отчёты**: list by ISO week. The viewer renders the report (rejection statistics, top reason_codes by section/param, recommendations), with PDF/MD download.

---

## 4. Interfaces with other blocks

| Block / module | B08 consumes | B08 produces | Contract notes |
|---|---|---|---|
| Platform (API skeleton, auth, DB, RabbitMQ, Redis, compose) | auth session, `me`, migrations framework, outbox relay, OpenAPI tooling, RFC 7807 errors, request-id middleware | web container, nginx config, `packages/domain` | OpenAPI spec is the single source; Orval generation runs in CI |
| Module 1: upload and parsing | `POST /documents/upload`, `GET /processes/{id}/status` (+ capabilities, ETag), processes list, registry endpoints, completeness preview, file lookup, page descriptor, tiles, crops, preview.pdf for DOCX | registry edits; start; the matrix snapshot (regex, anchors) | Coordinates normalized to the **visible area** after CropBox/MediaBox/Rotate, computed with the same MuPDF used for tiles; DOCX coordinates on `preview.pdf`; XML locators by xpath |
| Module 2: comparison and protocol | protocol JSON (§3.9), versions list, `protocol.ready/updated` events, rule evaluator for `rule-test`/`impact-preview` | matrix snapshot with typed trigger rules and threshold resolution (§3.12.3); diff function; render templates | **Stable `finding_id`/`evidence_group_id` across versions**; no hard-coded thresholds; SUSPICION excluded from violation counts; protocol records the pinned matrix_version |
| Module 3: verification | decision and finalize/unfinalize endpoints, `verification.decided` events, reason-code list | shell route `/protocols/:id/verify`, EvidenceViewer, EvidenceCard, ReasonModal, StatusTag, hotkey infra, UX telemetry hook | Button label **«Завершить»** exactly (§9.1); unfinalize reason is mandatory; ≤3 clicks per violation |
| Module 4: GOLD and retraining | Dataset_Items, dataset versions, Model_Versions, ML_Retraining_Log, approval and rollback endpoints | curator and approver UI | Approver = `model.approve` permission; approval record includes approver, time and comment |
| Module 5: hypotheses | suspicions, facts catalog, rule test evaluator | Logical_Rules CRUD (JSONLogic subset: `== != < <= > >= and or ! in var missing`) | Python must evaluate the same JSONLogic subset (json-logic implementation or a small own evaluator); `matrix.version.published` triggers a reload |
| Module 6: РиН | sync status per protocol, sync queue, `rin.*` events, manual retry | notification with «Создать новую проверку» | Sync failure never changes an inspector decision (display rule) |
| Module 9: audit | Audit_Log read API; audit writer used by B08 admin writes | audit viewer UI | Recommend `entity_type`/`entity_id` columns besides construction `object_id`; details carry before/after/reason |
| Module 10: weekly report | report list and artifact | viewer | — |
| Module 11: monitoring | health, metrics summary, Grafana/Kibana URLs | client-logs, UX telemetry, web vitals | JSON logs carry request_id/user_id |
| Module 12: negative scenarios | error code catalog | UX treatment per code (§3.7) | problem+json codes are shared in `packages/domain` |

---

## 5. Too complex or risky items, with a simplification that still satisfies the ТЗ

| Item | Why risky | Simplification (still meets the letter of the ТЗ) |
|---|---|---|
| Viewing A0 vector drawings (up to 113k paths) with precise overlays | pdf.js is slow to re-render at zoom, canvas limits cause blur, and a second geometry engine risks bbox misalignment | Server MuPDF tiles plus OpenSeadragon. Phase 1 is a single 150-dpi page image; Phase 2 adds tiles. The same engine as the coordinates means exact alignment |
| Exports in 3 formats with Приложение № 2 layout (missing) | Three renderers could drift; the layout is unknown | One DOCX template (docxtpl), then LibreOffice to PDF; XML from JSON plus own XSD. The template is swappable when App. 2 arrives |
| "Without recoding" for non-numeric triggers (about 106 of 132) | min/max alone cannot express direction, ordinal or presence rules | Typed templates with schema-validated JSON and explicit min/max semantics per template. SEMANTIC/EXTERNAL rules expose only priority, activity, regex and anchors, and are labelled honestly |
| Registry auto-suggestions | Depends on Module 1 metadata sniffing and OCR for scans | The grid works manually from day 1; suggestions arrive asynchronously; CSV/XLSX import and template cover the rest |
| Protocol diff | Needs identity stability of findings across versions | Contract with Module 2 (stable ids) plus a fallback composite key; diff computed by a shared pure function |
| Live colours for 100 users | Websockets add infrastructure | Materialised indicator on events plus 30 s polling with ETag; SSE later if needed |
| Impact preview | Rule evaluator must not be duplicated in TS and Python | Server calls the single Module 2 evaluator; limited to numeric templates over stored Checks values; NICE priority |
| ML screens before Module 4/10 APIs exist | Blocking | Build against the OpenAPI spec and Orval MSW mocks; swap to the live API when ready |
| Usability test with 5 inspectors (§9.3) | No access to real inspectors | Telemetry proves clicks and time; a proxy test with 5 participants on a script; results documented |
| УКЭП signature of the model publication decision | CryptoPro plugin integration is heavy | Named approver, password re-entry, immutable audit record; УКЭП out of scope and stated |
| Normative temporal validity versus Params thresholds | Two sources of truth | Resolution rule (§3.12.3) plus validity windows in the snapshot; the evidence card shows which threshold applied |

---

## 6. ТЗ contradictions and ambiguities (for this block), with recommended interpretation

1. **Приложение № 2 (protocol sample) is mandatory but was not provided** (§9.2). *Recommendation:* lay the protocol out in exactly the §9.2 p.4 order (upload status, scenario, five tables, evidence cards) and keep the layout in an editable Word template. Request App. 2 from the organisers.
2. **Colour semantics are undefined** (§7 m.7). *Recommendation:* the strict rule in §3.5. Red only for CONFIRMED_VIOLATION, consistent with «CANDIDATE… Включение в число нарушений: Нет» and the risk ≠ status clause.
3. **Process statuses vs verification statuses** (§9.1 vs §9.3): COMPLETED ≈ VERIFICATION_COMPLETED and FINALIZED ≈ PROTOCOL_FINALIZED. **`PENDING` means three different things** (process, candidate decision, sync `PENDING_SYNC`). *Recommendation:* a namespaced dictionary; show the RU label with the ТЗ code tooltip; map process to protocol status 1:1 in the domain package.
4. **COMPLETED allows dozagruzka but not verification** (§9.1). If new files create new CANDIDATEs, verification is needed again. *Recommendation:* after an incremental update that yields new candidates, the process returns to VERIFYING (Modules 2/3 decide). The UI follows server `capabilities`.
5. **Two places hold thresholds**: Params.min/max (§8.1) and Normative_Base.min/max (§10.10). *Recommendation:* inheritance through THRESHOLD links with validity windows (§3.12.3); Params values are the fallback.
6. **Normative_Base has no `is_active`**, yet Module 8 requires «деактивировать». *Recommendation:* add `is_active` (plus reason) and keep `effective_to` for temporal end-dating.
7. **Which date selects the effective norm?** Unspecified. *Recommendation:* the protocol run date by default, with a setting to use the ПД approval date (norms in force at design time). The applied norm is always shown.
8. **Section filter "по разделам"**: §3 lists ПП 87 sections 1–13 (with ТХ, БЭ, ИН), while §6 and the matrix use 12 matrix sections (with ПОД and ЗУ, split into ИОС1–5). *Recommendation:* filter by matrix `Params.section` (16 values); ТХ/БЭ/ИН have no parameters.
9. **Parameter codes**: M-001…M-132 in Приложение 1 vs PZ-01 / KR-55 / AR-41 in §8.1–8.2. *Recommendation:* canonical M-xxx plus `alias_code`; both searchable; exports show «M-055 (KR-55)».
10. **Duplicate parameters across sections**: M-040≈M-104 (corridor width <1,2 м), M-041≈M-105 (door width <0,9 м), M-043≈M-106 (door direction), M-050≈M-107 (КМ class), M-069≈M-109 (FRLS cables), M-080≈M-108 (АПС detectors), M-021≈M-124 (energy class), M-038≈M-121 (МГН parking). *Risk:* one physical defect counted twice on the dashboard. *Recommendation:* Module 2 fills `related_param_codes`; the dashboard shows «связанные параметры» and does not add related findings twice in the headline number (counts by evidence group). Decide with Module 2.
11. **Suspicious or context-dependent thresholds in the matrix**: M-117 «ширина полотна двери в свету < 1,5 м», M-119 «< 1,5 м» for a universal cabin (this looks like a turning-circle diameter rather than a door or cabin dimension), and ranges M-031 «10–12 м», M-047 «1,5–1,8 м», M-084 «3,5–4,5 м», M-116 «1,5–1,8 м». *Recommendation:* seed the conservative lower bound, mark the rows `expert_verified=false`, and let the admin fix them in Module 8 (a good live demo of "без перекодирования"). Ask an expert to confirm.
12. **M-098…M-101 (unit «Статус»)** need data from external systems (АИС «ОСИГ», РНИС/ГЛОНАСС, «Мобильный КПТС», ТРПО) that are not part of ПД/РД/ИД. *Recommendation:* template EXTERNAL_STATUS; result MISSING_EVIDENCE or NOT_APPLICABLE unless an ИД document carries the status. The admin can deactivate these with a reason.
13. **The matrix has no LOW-priority parameters** (106 HIGH, 26 MEDIUM), though LOW is allowed. The UI supports LOW anyway.
14. **XML export format is unspecified.** *Recommendation:* publish our own XSD versioned alongside the API; align with РиН if a format is ever provided.
15. **Which protocol version is exported?** *Recommendation:* any version (default latest). Non-finalized versions carry a «ПРОЕКТ» watermark; only a finalized version goes to РиН.
16. **Notification channel for «Инспектор получает уведомление»** (§9.2 p.5) is unspecified. *Recommendation:* in-app (bell, toast, deep link). Email/Telegram is reserved for admin alerts (§13.7).
17. **Roles**: §12.2 names 3 roles, but the ТЗ also needs a supervisor (§9.3), a data curator (§9.4) and a "responsible person" for publication (§9.4). *Recommendation:* 5 roles plus the `model.approve` permission.
18. **Audit_Log.object_id** could mean the construction object or the acted-on entity. *Recommendation:* keep `object_id` = construction object (nullable) and add `entity_type`/`entity_id`.
19. **Matrix change during an open process** (§9.2 p.1 requires versions to be fixed per run). *Recommendation:* pin the version per process and offer an explicit re-check. The change "applies to the next check".
20. **Deactivating a Params row** may conflict with "132 parameters". *Recommendation:* allowed with a reason. In protocols the parameter appears as NOT_APPLICABLE with the basis «деактивирован в матрице vN», which satisfies «NOT_APPLICABLE с обязательным основанием» (03).
21. **§11 #11 (100 concurrent inspectors) vs the pull model**: polling load needs budgeting. ETag, adaptive intervals and pause-when-hidden solve it (§3.7).
22. **Object visibility for inspectors** (all objects vs assigned only) is unspecified. *Recommendation:* all objects readable, a «Мои» default filter, notifications by assignment.

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation | Impact |
|---|---|---|---|---|
| D1 | Colour policy for objects | (a) STRICT: red = confirmed only; (b) TRIAGE: red also for HIGH candidates pending | **(a) STRICT**, with neutral grey for "нет результата" | Methodological correctness in front of Мосгосстройнадзор experts; filter semantics |
| D2 | UI kit | (a) Ant Design 6 + ru_RU; (b) Gravity UI; (c) Consta; (d) MUI | **(a)** | Velocity of AI agents, density, ru locale |
| D3 | Evidence viewer engine | (a) server MuPDF tiles + OpenSeadragon; (b) pdf.js/react-pdf client rendering | **(a)**, with react-pdf fallback for text PDFs | A0 drawing performance, bbox alignment accuracy |
| D4 | Protocol layout while Приложение № 2 is missing | (a) our §9.2-ordered layout in a Word template; (b) wait for App. 2 | **(a)** now, and ask the organisers for App. 2 | Export fidelity score |
| D5 | XML export schema | (a) own versioned XSD; (b) guess the РиН format | **(a)** | Integration-readiness story |
| D6 | Matrix publishing granularity | (a) each save publishes a version with a mandatory reason; (b) draft changeset then publish | **(a)** (simpler, fully auditable) | Admin UX complexity; version count |
| D7 | Effect of a matrix change on open processes | (a) pin the version per process and offer "Перепроверить"; (b) auto re-run all open processes | **(a)** | Reproducibility (§9.2 p.1) vs freshness |
| D8 | Reference date for the effective normative | (a) protocol run date; (b) ПД approval date; (c) configurable | **(c)**, default (a) | Correctness of threshold selection |
| D9 | Roles | (a) 5 roles + `model.approve`; (b) only the 3 roles of §12.2 | **(a)** | Unfinalize, curation and publication flows |
| D10 | Auth source | (a) local login/password (ТЗ); (b) + LDAP/AD/ЕСИА | **(a)** for MVP | Effort |
| D11 | Notification transport | (a) polling 15 s; (b) SSE; (c) WebSocket | **(a)**, SSE behind a flag | Infra simplicity, pull-model consistency |
| D12 | Upload start | (a) explicit «Запустить» after registry confirmation (UI) and `auto_start` for the API; (b) auto-start on upload | **(a)** | Registry quality, linkage metric |
| D13 | Branding | (a) neutral «Инспектор ИИ» with Golos Text; (b) styled after mos.ru | **(a)** | Avoids imitating an official portal |
| D14 | Show ТЗ codes next to RU labels | (a) RU label plus code tooltip/chip; (b) RU only | **(a)** | Jury traceability to the ТЗ |
| D15 | Are external or cloud APIs allowed at all (152-ФЗ)? For B08 this affects fonts, maps and telemetry | (a) closed contour, everything self-hosted; (b) cloud allowed | **(a)** for B08 regardless | No CDN; fonts bundled |
| D16 | Render worker ownership (exports) | (a) B08 owns templates and the renderer, B02 owns the JSON; (b) B02 owns everything | **(a)** | Avoids two PDF generators |

---

## 8. Data needed

| What | Why | Fallback if never received |
|---|---|---|
| Приложение № 2 (sample output protocol) | Mandatory layout for exports (§9.2) | §9.2-ordered layout in an editable DOCX template; state the assumption in the demo |
| Normative references for the 132 parameters (sp/gost/fz/other, clause, thresholds, validity) | Params fields required by §8.1 are absent from the xlsx; needed for Normative_Base seed | Seed document-level references only where the trigger text names them (СП 1.13130, СП 59.13330, СП 54.13330) plus our curated draft, all marked `expert_verified=false`. Never invent clause numbers |
| Expert confirmation of thresholds M-031, M-047, M-084, M-116, M-117, M-119 | Correct candidates, low FPR | Conservative lower bound, flagged, editable by admin |
| Expected XML structure (РиН or Мосгосстройнадзор) | XML export acceptance | Own XSD |
| Object requisites for the 9 pilot objects + АНО vent object (customer, contractor, permit) | Object cards and exports look real | Addresses from the pilot markup; other fields «не указано» |
| Real org structure (inspectors, supervisors, curators, approvers) | Seed users and roles | 6 demo users (one per role, plus the approver) |
| Target browsers/OS in the customer contour (Astra Linux? Yandex Browser? Chromium-GOST?) | Build targets and QA | Evergreen Chromium ≥ 120, Firefox ESR, Yandex Browser; ES2020 target |
| Typical volume (objects per inspector, files per package, pages per file) | Pagination and performance budgets | Design for 10k objects, 500 files per object, 500 pages per file |
| Brand or visual guidelines, if any | Look and feel | Neutral government style |
| Access to 5 inspectors for usability testing (§9.3) | Required usability test | 5 proxy participants, a scripted test, telemetry evidence |
| Pilot page ↔ original file mapping | Demo fixtures with real overlays | Verified that compilation page 2 = `PD:ALT79B-000015 стр.19` (bboxes from ПРИМЕРЫ РАЗМЕТКИ match the page geometry), so fixtures can be cut from the 24-page markup PDF. Note: that PDF is 54 МБ, larger than the 50 МБ limit, so it must be split per object (and uploading the whole file makes a nice negative demo) |

---

## 9. Jury demo scenario and acceptance criteria

### 9.1 Demo script (about 8 minutes, B08 parts)
1. **Log in as the inspector.** The dashboard shows 10 objects. Октябрьская 103 is ⛔ red («Подтверждено: 1»), Полярная 17 is ✔ green, and the others are ⚠ yellow («Ожидают решения»). Hovering the tooltips shows the reasons. Filter «Разделы: АР», then a date range, then the «Мои на верификации» preset. Copy the URL and open it in a new tab to show the same filters.
2. **New check.** In the wizard, drop files including a `.dwg`, a 60 МБ PDF and the whole 54 МБ markup PDF. Each is rejected inline with the ТЗ wording. Drop valid files. The registry grid auto-fills stage, шифр and revision; one conflict of two APPROVED revisions shows «будет CLARIFICATION_REQUIRED». The completeness step shows «Сценарий: PD_RD_ONLY», `ID_MISSING`. Start, and the `process_id` is shown.
3. **Process monitor.** The stepper advances by polling, with per-file OCR quality. The bell shows «Протокол готов», and one click opens it.
4. **Protocol.** Show the header versions (matrix / dataset / model / manifest), upload statuses, scenario, the five separate tables and the separate MISSING_EVIDENCE list. Expand a candidate. The evidence card crops come from the pilot sheet (ALT79B, A0), and the full viewer shows blue ПД and red РД frames aligned on the drawing with synced side-by-side zoom.
5. **Verification** (Module 3). Confirm one candidate, then go back to the dashboard: the object turned red on the next poll.
6. **Dozagruzka.** Add an ИД file. The scenario becomes FULL, an incremental update produces protocol v2, and «Сравнить версии» shows «+2 новых, 1 изменение комплектности».
7. **Export** to PDF, DOCX and XML. Open the files. The XML validates against `/schemas/protocol.xsd`. The draft carries the «ПРОЕКТ» watermark.
8. **Log in as the admin, Матрица.** Open M-117, which shows «ширина двери в свету < 1,5 м» as `expert_verified=false`. Change `min_value` with a reason. «Оценить влияние» reports «1 находка сменит статус». Publish, and v16 appears. The audit log shows before/after, IP and reason. The object card shows the banner «Доступна матрица v16 — Перепроверить». The re-check creates a new protocol version with matrix v16 in its header.
9. **Нормативная база.** Add «СП 59.13330» with `effective_from` in the future; it shows as «Будущая редакция» and is not applied. Deactivate an old row, and the dependents warning appears.
10. **Логические правила.** Build «Если этажей > 10 → должен быть лифт» in the visual builder and test it on a process to get «будет сформирована SUSPICION».
11. **Roles.** The inspector opening `/admin/matrix` gets 403. The ML engineer sees the weekly report, the model registry with the gate matrix, and «Подписать решение о публикации» disabled until the gates pass. The curator sees the draft queue.

### 9.2 Acceptance criteria and tests
- **Colour rule**: table-driven unit tests (≥20 cases from §3.5) for `computeIndicator`. An E2E test confirms a candidate and asserts the colour change within 35 s. **No test case lets CANDIDATE, SUSPICION or HIGH alone produce RED.**
- **Capabilities**: for each of the 6 process statuses, E2E asserts the enabled/disabled upload, verify, finalize and unfinalize buttons exactly per §9.1. Tooltips give reasons.
- **Filters**: every filter is reflected in the URL and in the API query (MSW contract tests). A section filter returns only objects with findings in that section. The date-field selector works on each of the 4 fields.
- **Exports**: each of PDF/DOCX/XML downloads in ≤30 s (cold) and ≤1 s (cached). XML passes XSD validation in CI. All three contain versions, scenario, upload statuses and the five tables. The violation count equals the CONFIRMED count.
- **Upload negatives**: 4 rejection messages match the ТЗ wording. A duplicate hash is reused. A package over 200 МБ is rejected as a whole. Upload after FINALIZED is blocked with the "new check" offer.
- **Registry**: missing mandatory fields block «Далее» unless the user chooses «продолжить без реестра», which shows the CLARIFICATION_REQUIRED warning. Import of CSV/XLSX/JSON round-trips with export.
- **Viewer**: a fixture with rotated (90°) and CropBox-offset pages renders overlays at the expected pixel positions (visual snapshot with ≤2 px tolerance). Pilot ALT79B p.19 bboxes frame the room table.
- **Module 8**:
  - Editing min/max creates matrix v+1, a snapshot SHA-256 and an audit entry with before/after, reason and IP.
  - A new process uses v+1 and an open process keeps its pinned version.
  - 409 on stale `If-Match`. A regex invalid in Python is rejected. min > max is rejected. Overlapping THRESHOLD validity is rejected.
  - A future-dated normative row is not applied before its date (engine integration test with Module 2).
  - Deactivation is soft and reversible, and history lists every change.
- **Roles**: route guards plus server 403 for each forbidden endpoint per role (API tests). Unfinalize without a reason is impossible.
- **Performance**: dashboard first render ≤1,5 s on LAN with 10k seeded objects (server pagination). The polling budget test with 100 simulated sessions keeps API p95 ≤200 ms (k6 run with Module 11).
- **A11y**: no axe "serious/critical" violations on S-02, S-04, S-05, S-08, S-13, S-14, S-15. The colour indicator carries text and an icon.
- **Usability telemetry**: in the demo protocol (14 candidates) the clicks-per-decision median is ≤3 and total time is recorded (shared with Module 3).

---

## 10. Work breakdown

Owners (proposed implementation agents): **web-core** (shell, dashboard, objects, upload, processes, protocol, viewer, notifications), **web-admin** (Module 8 UI, admin and ML screens), **api-admin** (Node: Module 8 backend, dashboard aggregation, notifications, export orchestration), **render** (Python export worker; may be merged into api-admin or B02). External dependencies: PLAT = platform skeleton; M1…M12 = module owners.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| B08-T01 | Frontend scaffold: Vite 8/React 19/TS 6 strict, antd 6 + ru_RU + dayjs ru, ESLint/Prettier, Vitest, Playwright, runtime `/config.json`, Dockerfile (nginx, CSP, 210m body, `/api` proxy) | M | PLAT monorepo | web-core |
| B08-T02 | Orval pipeline (hooks, zod, MSW mocks), fetch mutator (problem+json, 401, CSRF, X-Request-Id, Idempotency-Key, ETag), mock mode | S | T01, PLAT OpenAPI skeleton | web-core |
| B08-T03 | `packages/domain`: namespaced status dictionary (RU labels, colours, icons), capability map, `computeIndicator`, counters, `diffProtocols`, error catalog, ru formatters and plurals, with unit tests | M | T01 | web-core (shared with api-admin) |
| B08-T04 | Design system components + theme + `/dev/kit` page (StatusTag, ObjectIndicator, CodeChip, HashText, DocRef, MetricDelta, VersionBadges, FilterBar, DataTable, ReasonModal, states, AuditTimeline, FieldDiffTable) | M | T03 | web-core |
| B08-T05 | App shell: layout, role menu, route guards, login, session and idle timeout, 403/404/500/offline, global search, UX telemetry hook | M | T02, T04, PLAT auth | web-core |
| B08-T06 | Dashboard: KPI tiles, URL-synced FilterBar (sections tree, statuses, date field + range, priority, scenario, inspector), object table, presets, 2 charts | M | T05, T21 | web-core |
| B08-T07 | Object create/edit modal and object card with 8 tabs (documents with revision-chain timeline, findings, suspicions, journal, integration) | L | T05, T10, M1 files API, M2 protocol list | web-core |
| B08-T08 | Upload wizard: client validation, SHA-256 worker, parallel upload with progress, registry builder grid (auto-suggest polling, import/export/template, validation), completeness preview, start, append mode | L | T05, M1 upload/registry/preview endpoints | web-core |
| B08-T09 | Process monitor list and detail (stepper, per-file table, adaptive polling, admin retry) | M | T05, M1 status endpoint | web-core |
| B08-T10 | EvidenceViewer: OpenSeadragon wrapper, tile source, SVG overlay, fit-to-bbox, side-by-side sync, crops, keyboard, DOCX preview and XML tree modes | L | T04, M1 page/tile/crop endpoints | web-core (Module 3 co-reviews) |
| B08-T11 | Protocol viewer: header and versions, upload statuses, scenario, 5 tables, MISSING_EVIDENCE list, read-only EvidenceCard, sync chip, «Завершить» / unfinalize entry points | L | T10, M2 protocol schema, M3 endpoints | web-core |
| B08-T12 | Protocol versions list and diff view | M | T11, T24 | web-core |
| B08-T13 | Export UI (menu, 200/202 handling, polling, filenames, watermark info) | S | T11, T25 | web-core |
| B08-T14 | Notifications center (bell, drawer, page, toasts, deep links, read state) | S | T05, T23 | web-core |
| B08-T15 | Admin, Матрица: table (filters, template, threshold source) and Param editor drawer (all §8.1 fields, typed trigger form, live sentence, thresholds and normative source timeline, refs picker, regex tester, rule test, reason/publish, 409 dialog, history) | L | T05, T22, T26 | web-admin |
| B08-T16 | Admin, Нормативная база: table (active-on-date), editor, deactivate/activate with dependents warning, history | M | T15, T22 | web-admin |
| B08-T17 | Admin, Логические правила: list, react-querybuilder to JSONLogic editor, test panel | M | T22, M5 facts catalog and evaluator | web-admin |
| B08-T18 | Admin: matrix versions (list, snapshot, diff, restore), impact preview modal, ordinal scales editor | M | T22, T26 | web-admin |
| B08-T19 | Admin misc: audit viewer, users and roles, monitoring overview, РиН queue (mock), settings | M | M9 audit API, M11, M6, PLAT auth | web-admin |
| B08-T20 | DB: migrations for params (+ext), normative_base, links, logical_rules, ordinal_scales, matrix_versions, notifications, export_jobs, saved_filters, object indicator columns; seed 132 params from xlsx with alias codes, typed trigger inference and initial thresholds; publish v1 | M | PLAT DB | api-admin |
| B08-T21 | Dashboard and objects API: filters, summary, indicator materialisation on protocol/verification events | M | T03, T20, M2 events | api-admin |
| B08-T22 | Admin API: CRUD, validation (shared schemas), optimistic locking, publish transaction (snapshot, SHA-256, audit, outbox → `matrix.version.published`, Redis), snapshot/current endpoint, version diff/restore, history | L | T20, M9 audit writer, PLAT outbox | api-admin |
| B08-T23 | Notifications service: consumers for protocol/file/process/rin/ml events, fan-out by role/assignment, endpoints, ETag | M | T20, PLAT RabbitMQ | api-admin |
| B08-T24 | Protocol diff endpoint (shared `diffProtocols`) | S | T03, M2 protocol schema | api-admin |
| B08-T25 | Export: orchestration endpoint and cache, Python `protocol-render` worker (docxtpl DOCX with evidence crops, LibreOffice PDF, lxml XML + XSD), pre-generation on ready/finalized, watermark | L | T20, M2 protocol JSON, M1 crop renderer | render |
| B08-T26 | Rule-test, regex-test and impact-preview endpoints (proxy to Module 2/1 Python evaluators) | M | T22, M2 evaluator, M1 regex service | api-admin |
| B08-T27 | ML screens: rejection/dispute logs, curation queue, dataset release wizard, model registry with gate matrix, approval (re-auth) and rollback, weekly report viewer | L | T05, T10, M4 and M10 APIs (MSW mocks first) | web-admin |
| B08-T28 | Normative seed curation (document-level refs for the 132 params, flagged unverified) and threshold review list for an expert | S | T20 | api-admin (+ domain review) |
| B08-T29 | Demo fixtures: 10 pilot objects, evidence groups from ПРИМЕРЫ РАЗМЕТКИ mapped onto split markup pages, 6 demo users, 2 protocol versions for the diff demo | M | T20, M1/M2 seed formats | api-admin |
| B08-T30 | Hardening: a11y (axe), responsive pass, code-splitting/perf budgets, negative-state catalog, Playwright jury E2E (§9.1), k6 polling budget with Module 11 | M | T06–T19, T27 | web-core |

Critical path for the demo: T01 → T02/T03 → T04 → T05 → (T08, T09, T10) → T11 → T13/T12. In parallel: T20 → T22 → T15/T16, and T25. Everything frontend can start on MSW mocks as soon as T02 lands.
