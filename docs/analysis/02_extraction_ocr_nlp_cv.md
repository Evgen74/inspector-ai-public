# B02 — Content extraction: OCR, NLP, CV, coordinates

**Block:** B02-extraction · **Module 1 «Загрузка и парсинг документов» (High), part B — content extraction**
**Date:** 2026-09-27 · **Phase:** planning/analysis (no application code)
**Sources read:** `01_TZ_text.txt` (full), `02_matrix_all_sheets.txt` (all 4 sheets), `03_perechen_ID_registry_rules.txt`, `05_razmetka_poyasn_6p_text.txt`, page previews, and the original PDFs/DOCX inspected with PyMuPDF (page boxes, rotation, annotations, text layer, images, vector paths).

**Empirical probes executed for this report** (dev machine: Apple M2 Max, 12 cores (8P+4E), CPU only; scripts are in the session scratchpad `/private/tmp/claude-501/-Users-evgen-pl-hackaton/18a4a0ae-5dd8-48b7-a436-1b6a7256ad25/scratchpad/{ocrprobe,coordtest,emb}` — temporary, re-create them in tasks B02-T02/T13):

| Probe | What was measured | Where the result is used |
|---|---|---|
| P1 page inventory | MediaBox/CropBox/Rotate, image coverage and effective DPI, text-layer size, fonts, text render modes, vector paths, annotations for all 24+6 pilot pages | §3.2, App. B |
| P2 OCR accuracy | Tesseract 5.5.2 (`rus` best/fast, psm 3/11) vs PP-OCRv5 (RapidOCR 3.9.2 + ONNX Runtime 1.30, `cyrillic`/`eslav` rec, mobile det) on 5 regions; the vector text layer is ground truth; metric = bbox-matched character accuracy | §3.4, App. A |
| P3 OCR throughput | full 300-dpi A4 page, process pool 1×12 … 8×1 | §3.4.6 |
| P4 real scan | p14 (200-dpi ИД scan): tolerance table, handwriting, title block, blue-ink stamp/signature mask | §3.5 |
| P5 coordinates | 7 synthetic PDFs (offset CropBox, Rotate 0/90/180/270/−90, negative-origin MediaBox); formula vs PyMuPDF vs rendered pixels; the 27 GOLD bboxes vs red vector rectangles | §3.14, App. E |
| P6 embeddings | 7 sentence-embedding models on a 40-query Russian anchor-retrieval test over the 132 parameter names; latency; bulk throughput | §3.11 |
| P7 tables and CV | `find_tables()` on explications/specs; scale inference by (dimension value ÷ segment length) voting | §3.8, §3.13 |

---

## 0. Executive summary

1. **The pilot pages are heterogeneous, so every page (and every region) has to be routed separately.** Of the 24 pilot pages:
   - 18 are vector with a real text layer (ArchiCAD/AutoCAD/Revit exports; fonts ISOCPEUR, GOST Common, Arial).
   - 4 are **HYBRID**: a full-page raster plus a vector text layer. p3 and p5 have a 150-dpi raster; p22 and p24 are tiled from 55 raster tiles.
   - 1 is **vector with text converted to outlines** (p9: 27,421 paths, while the text layer holds only the expert's 19-word callout; OCR of the rendered page recovers "Железобетонная плита В30 W6 F150 - 900 мм" at confidence 0.97).
   - 1 is a **pure scan** (p14: 200 dpi, with handwriting, a seal and signatures).

   A naive "text layer if present, else OCR" rule would silently miss p9 and the raster-only text of p3/p5.
2. **The expert markup is page content, not annotations.**
   - The markup is red vector strokes: width 4.0 = evidence box, 3.0 = callout, 2.5 = leader line.
   - The only annotations are **white Ink strokes that redact title-block cells**. The text under them is still in the text layer.
   - Extraction must therefore be **visibility-aware**, and pilot files need a "sanitizer" so the expert callouts do not leak into extraction or evaluation.
3. **The coordinate convention is proven.**
   - All **27/27 GOLD bboxes** in «ПРИМЕРЫ РАЗМЕТКИ» are reproduced by the red width-4 rectangles with **IoU ≥ 0.997**. The convention is top-left origin, y pointing down, normalized to the displayed page.
   - All pilot pages have `Rotate=0` and `CropBox=MediaBox` at the origin, so they do not exercise §9.1 step 4. **7 synthetic fixtures** do: offset CropBox, Rotate 90/180/270/−90, and a negative-origin MediaBox. On all of them the canonical formula, PyMuPDF and the rendered pixels agree to 4 decimals.
4. **OCR engine: PP-OCRv5 via RapidOCR/ONNX Runtime** (Apache-2.0, pip wheels for arm64 and amd64, no Paddle runtime).
   - **Clean A4 tables and title blocks:** measured character accuracy **0.97–0.98**, against 0.77–0.92 for Tesseract 5.5 `rus`.
   - **Dense drawing labels:** 0.80–0.93 for PP-OCRv5, against 0.56–0.89 for Tesseract.
   - Tesseract `rus` stays as the fallback and as the OSD (orientation) engine.
5. **Throughput meets §11 on the dev machine, with little margin at 500 pages.**
   - **1.12 s per dense 300-dpi A4 page** with 4 workers × 3 threads.
   - 100 pages ≈ 112 s (limit 180 s, OK); 500 pages ≈ 9.3 min (limit 10 min ±1).
   - Text-layer-first processing takes most CAD sheets out of the OCR path entirely.
6. **Behaviour on the real scan:**
   - Numeric table cells (+491, +980, −2.900) are read at confidence **0.95–1.00**.
   - Handwriting comes back at **0.30–0.46**, a usable LOW_QUALITY/ABSTAIN signal.
   - A blue/violet-ink HSV mask isolates the handwriting, seal and signature zones. This also supports §5 note 2 (visual check of mandatory реквизиты).
   - **Latin/Cyrillic homoglyphs** appear in both OCR output ("KP-4.1", "KЖ0.2", "B2.4") and vector text (`В25` alongside `B25`). This needs a deterministic, context-aware script harmonization that keeps the raw text.
7. **Semantic anchors.** `all-MiniLM-L6-v2` is English-only. On a 40-query Russian anchor test:

   | Model | Top-1 | Top-3 | Latency per query |
   |---|---|---|---|
   | `intfloat/multilingual-e5-small` | **34/40** | **38/40** | **8 ms** |
   | `cointegrated/LaBSE-en-ru` | 34/40 | — | 24 ms |
   | `cointegrated/rubert-tiny2` | 29/40 | — | 1.5 ms |
   | `paraphrase-multilingual-MiniLM-L12-v2` | 22/40 | — | — |

   Choose **multilingual-e5-small** (MIT licence; ship as ONNX). The §11 limit of ≤500 ms per parameter leaves about 50× headroom.
8. **Explication tables are the key extraction.** Most pilot findings are room function and area changes, visible in explication tables: ALT79B, POL16, DOO25 and SOSH25, plus the negative POL17. `page.find_tables()` extracts them with cell bboxes. It needs a header classifier, a splitter for side-by-side tables (p19: three explications merged into 31 columns), and filtering of false positives from drawing grids.
9. **CV has to stay realistic.**
   - On vector sheets, a vote over (dimension value ÷ paper length of the adjacent segment) recovers the declared scale: **1:100** on p2, p4 and p21, and **1:200** on p19, whose building (155 m) could only fit A0 at 1:200.
   - For the MVP, CV means vector geometry plus text labels.
   - Raster CV covers only lines, scale, stamps and handwriting. **No symbol recognition.**
10. **Main risks:**
    - bbox granularity against expert GOLD boxes (region-level, several boxes per page);
    - unknown hidden-test normalization details (dash variants, homoglyphs);
    - breadth of 132 parameters. Mitigation: deep extraction profiles for about 35 parameters, a generic profile for the other 97, and an honest MISSING_EVIDENCE / NOT_COMPARABLE when nothing is found.

---

## 1. Scope

### 1.1 ТЗ clauses covered

| Clause | Quote (verbatim) | B02 responsibility |
|---|---|---|
| §7 п.1 (High) | «Загрузка ПД, РД, ИД (PDF, DOCX, XML); извлечение данных по 132 параметрам согласно Матрице контроля…» | Content extraction from all three formats for 132 params (upload/registry/completeness = B01) |
| §9.1 Назначение | «…идентификация стадии, шифра, раздела, редакции и статуса утверждения каждого документа; … извлечение значений и координат доказательных фрагментов по 132 параметрам» | Title-block key fields (feeds B01 identification) + values + coordinates |
| §9.1 Вход/Выход | «Вход: PDF, DOCX, XML файлы (ПД, РД, ИД). Выход: Структурированные данные (таблица Checks).» | extracted_values + Checks skeleton (see §4) |
| §9.1 шаг 1 OCR | «технология распознавания выбирается исполнителем. Приёмка … печатного текста … не менее 300 dpi. Character Accuracy = 1 − CER … не ниже 0,95; Exact Match для ключевых полей (шифр, стадия, редакция, номер листа/страницы, номер помещения или элемента) — не ниже 0,90. Для расчёта CER применяется Unicode NFC и нормализация повторных пробелов; регистр может игнорироваться только для полей, где он не несёт смысла, а знаки в шифрах и редакциях не удаляются. Рукописные и заранее размеченные нечитаемые зоны не включаются в OCR-метрику, но система обязана вернуть LOW_QUALITY или ABSTAIN; доля таких зон и общая покрываемость отчётно фиксируются.» | Full |
| §9.1 шаг 2 NLP | «Поиск по 132 параметрам с использованием регулярных выражений (regex_pattern) и семантических якорей. Используется модель Sentence-BERT (all-MiniLM-L6-v2) или её совместимые аналоги.» | Full |
| §9.1 шаг 3 CV | «Для чертежей PDF выполняется масштабирование по размерной линейке, распознавание линий и измерение расстояний.» | Full (scope-limited, §5) |
| §9.1 шаг 4 | «для каждого извлечённого значения сохраняются file_id, SHA-256 файла, стадия, шифр, редакция, статус утверждения, лист/страница и нормализованный bbox/polygon. Координаты приводятся к диапазону [0;1] относительно видимой области страницы после учёта CropBox, MediaBox и Rotate…» | Full |
| §9.1 шаг 5 | «Результаты парсинга сохраняются в Redis по хешу файла для ускорения повторных проверок.» | Full |
| §9.1 errors | «Загружен повреждённый PDF-файл → Отклонение файла, уведомление пользователя о необходимости повторной загрузки»; «Таймаут при обработке файла → Повторная попытка обработки (до 2 раз). При неудаче – уведомление администратора» | Parse-time detection + retry policy (format/size checks = B01) |
| §9.1 Дозагрузка / §9.2 incremental | «инкрементальную дозагрузку файлов без перезагрузки существующих»; «инкрементальное обновление только по тем параметрам, для которых появились новые данные» | Per-file extraction, cache reuse, `params_touched` |
| §5 прим. 2 | «…система осуществляет визуальную проверку наличия всех обязательных реквизитов (подписи, печати, даты, регистрационные номера).» | CV requisite detection (simplified) |
| §5 прим. 3 | «Чертежи должны содержать штампы «В производство работ» и «Выполнено согласно проекту».» | Stamp detection (simplified) |
| §8.1 Params | `unit`, `data_type` (number, string, boolean, coordinate, enum), `min_value`, `max_value`, `regex_pattern`, `is_active` | Extraction consumes these dynamically (admin-editable, §7 п.8 «без перекодирования») |
| §10 | Checks (evidence_group_id…), Files, Evidence_Fragments (`file_id, stage, sheet_page, bbox_polygon_norm, extracted_value, role_expected_actual`) | Produces rows for Evidence_Fragments via extracted_values |
| §11 п.2/3/7/8/9 | OCR 100 стр. ≤3 мин ±30 с; 500 стр. ≤10 мин ±60 с; «ML-анализ одного параметра (NLP) Не более 500 мс»; «CV-анализ одного чертежа (DWG) Не более 30 секунд»; инкрементальное обновление ≤1 мин | Full |
| §13 | JSON logs with timestamp, level, service, message, request_id, user_id; Prometheus/Grafana; ELK | Service-level compliance |
| §14.3 | OCR «отдельно публикуются CER, WER и coverage»; «Ключевые поля … ≥ 0,90»; «Локализация доказательства: Точное совпадение file_id и страницы; bbox/polygon считается верным при IoU ≥ 0,50 после нормализации геометрии страницы … ≥ 0,95 групп»; «публикуются размер выборки, coverage/abstention и 95%-й доверительный интервал» | Evaluation harness |
| 03 registry | «sheet_page_range — Диапазон листов/страниц и соответствие листа странице PDF»; «Файл нечитаем или листы не сопоставлены → NOT_COMPARABLE» | Sheet↔page evidence, readability signals |
| Matrix «МЕТРИКИ» | «bbox/polygon IoU ≥ 0,50 после учёта CropBox/MediaBox/Rotate» | Same as §9.1 step 4 |

### 1.2 Boundary with neighbour blocks
- **B01 (Module 1A: upload, registry, completeness).** Owns format, size and antivirus checks, the file registry (CSV/XLSX/JSON), the `doc_stage/discipline/document_code/revision/approval_status` metadata, the PD/RD/ID upload statuses, and completeness. B02 *supplies evidence* for all of these (title-block fields, sheet numbers, readability) but does not decide them.
- **Module 2 (comparison/protocol).** Owns evidence groups, expected/actual/delta and finding statuses. B02 supplies typed, located values and tables.
- **Modules 3/7 (UI).** Render pages and overlays using B02 geometry.
- **Modules 4/10.** Consume B02 versions, OCR-error statistics and evaluation reports.

---

## 2. Requirements checklist

Legend: priority for winning — MUST / SHOULD / NICE; MVP decision — FULL / SIMPLIFIED / MOCKED / OUT_OF_SCOPE.

| ID | Requirement (atomic) | ТЗ ref | Prio | MVP | Justification |
|---|---|---|---|---|---|
| EXT-01 | Extract content from PDF: vector, raster and hybrid pages | §7 п.1, §9.1 Вход | MUST | FULL | Core input; all pilot data is PDF |
| EXT-02 | Extract content from DOCX: paragraphs, tables, headers/footers, embedded images (OCR) | §7 п.1, §9.1 | MUST | FULL | python-docx; the provided DOCX holds 2 tables plus 4 embedded scans |
| EXT-03 | Extract content from XML | §7 п.1, §9.1 | MUST | SIMPLIFIED | No XML sample exists; generic XPath flattener plus 1 schema adapter |
| EXT-04 | Per-page and per-region classification with text-layer-first routing; OCR only where no reliable visible text exists | §9.1 п.1, §11 | MUST | FULL | Proven necessary by pilot p3, p5, p9, p14, p22, p24 |
| EXT-05 | OCR engine for Russian printed technical documents on CPU (Docker/ARM) | §9.1 п.1, §1.5 | MUST | FULL | PP-OCRv5 (RapidOCR ONNX) primary, Tesseract `rus` fallback; measured |
| EXT-06 | OCR Character Accuracy = 1 − CER ≥ 0.95 on printed text ≥ 300 dpi | §9.1 п.1, §14.3 | MUST | FULL | Measured 0.97–0.98 on the document-type proxy |
| EXT-07 | CER computed after Unicode NFC and whitespace collapse; case-insensitive only for fields where case is meaningless; characters in codes/revisions never removed | §9.1 п.1 | MUST | FULL | Implemented in the eval harness and in the key-field normalizer |
| EXT-08 | Publish CER, WER and coverage separately | §14.3 | MUST | FULL | Eval report fields |
| EXT-09 | Exact Match ≥ 0.90 for шифр, стадия, редакция, лист/страница, номер помещения/элемента | §9.1 п.1, §14.3 | MUST | FULL | Title-block parser plus explication room numbers; text layer where available |
| EXT-10 | Handwritten zones → LOW_QUALITY or ABSTAIN, excluded from the metric | §9.1 п.1 | MUST | FULL | Confidence plus blue-ink detection; recognition itself is out of scope (EXT-58) |
| EXT-11 | Pre-marked illegible zones → LOW_QUALITY or ABSTAIN | §9.1 п.1 | MUST | FULL | `PREMARKED` zone input (API and eval file); forced ABSTAIN |
| EXT-12 | Report the share of LOW_QUALITY/ABSTAIN zones and overall coverage per page, file and run | §9.1 п.1, §14.3 | MUST | FULL | Stored in `document_pages` and `extraction_runs` |
| EXT-13 | Report sample size and 95% CI with OCR metrics | §14.3 | SHOULD | FULL | Page-level bootstrap in the eval harness |
| EXT-14 | Title-block (основная надпись) extraction: шифр, стадия, лист, листов, изм., дата, наименование, масштаб, with bboxes | §9.1 Назначение | MUST | FULL | ГОСТ Р 21.101 forms; geometry-aware (cells), line-joining of wrapped codes |
| EXT-15 | Sheet ↔ PDF page mapping evidence for the registry | 03 `sheet_page_range` | MUST | FULL | `sheet_label` per page; mismatch flags to B01 |
| EXT-16 | NLP extraction per parameter via `regex_pattern` read from Params at runtime (admin-editable, hot reload on matrix_version) | §9.1 п.2, §7 п.8, §8.1 | MUST | FULL | No recoding when admins change patterns |
| EXT-17 | Semantic anchors with a Sentence-BERT-compatible model | §9.1 п.2 | MUST | FULL | multilingual-e5-small (measured); deviation from the name all-MiniLM justified |
| EXT-18 | Extraction profile for all 132 params (method, document scope, anchors, parser) | §7 п.1, §9.1 | MUST | SIMPLIFIED | Deep profiles for ~35 params, generic for 97 (§5 R1) |
| EXT-19 | Typed normalization (number/string/boolean/coordinate/enum), units, class systems with ordinal ranks | §8.1 `data_type`, `unit` | MUST | FULL | Required for «понижение класса» comparisons |
| EXT-20 | NLP analysis of one parameter ≤ 500 ms (±100) | §11 п.7 | MUST | FULL | Measured about 8 ms per query plus retrieval < 50 ms |
| EXT-21 | Table extraction from vector PDFs: ТЭП, экспликации, спецификации ГОСТ 21.110, ведомости | §3/§4, §8.2 sources | MUST | FULL | `find_tables()` plus classifier and typed parsers |
| EXT-22 | Table extraction from scans | §9.1 | MUST | SIMPLIFIED | Ruled grids (OpenCV) plus cell OCR; borderless tables → column clustering, flagged |
| EXT-23 | Table extraction from DOCX (merged cells) | §9.1 | MUST | FULL | python-docx gridSpan/vMerge |
| EXT-24 | CV: scale calibration «по размерной линейке», dimension lines and declared scale | §9.1 п.3 | MUST | SIMPLIFIED | Vector: voting per viewport; raster: OCR'd dimensions, flagged |
| EXT-25 | CV: line recognition on drawings | §9.1 п.3 | MUST | SIMPLIFIED | Vector paths exact; raster LSD/Hough |
| EXT-26 | CV: distance measurement | §9.1 п.3 | MUST | SIMPLIFIED | Vector exact (mm = pt·25.4/72·scale); raster approximate with confidence |
| EXT-27 | CV analysis of one drawing sheet ≤ 30 s (±10) | §11 п.8 | MUST | FULL | Measured get_drawings 0.1–0.7 s; find_tables ≤ 7 s on the heaviest A0 |
| EXT-28 | Graphic/configuration evidence: room-zone label sets, room function/area, system-branch labels | §9.2 «сопоставление значений и геометрии», pilot | SHOULD | SIMPLIFIED | Label-set diffs instead of symbol CV |
| EXT-29 | Persist per value: file_id, SHA-256, stage, code, revision, approval status, sheet/page | §9.1 п.4 | MUST | FULL | Denormalized in `extracted_values` |
| EXT-30 | Normalized bbox/polygon in [0;1] of the visible page after CropBox/MediaBox/Rotate | §9.1 п.4, §14.3 | MUST | FULL | Verified formula; 7 fixtures plus 27 GOLD boxes |
| EXT-31 | Identical coordinates in backend and front-end renderer (PDF.js), including rotated/offset pages | §9.1 п.4 «корректного отображения» | MUST | FULL | Shared fixtures; Playwright pixel test |
| EXT-32 | Displayable locator (page + bbox) for DOCX/XML sources | §9.1 п.4 | MUST | SIMPLIFIED | LibreOffice-rendered PDF (DOCX); rendered XML view plus XPath |
| EXT-33 | Redis cache of parse results keyed by file SHA-256 | §9.1 п.5 | MUST | FULL | Summary in Redis; heavy artifacts in object storage |
| EXT-34 | Version-aware cache (pipeline, OCR model, embedder, matrix_version) | §9.2 п.1, §14.2 | MUST | FULL | Keys include versions |
| EXT-35 | Incremental processing: parse only new files; emit `params_touched` | §9.1, §9.2, §11 п.9 | MUST | FULL | Per-file jobs plus cache |
| EXT-36 | Corrupted PDF detected at parse → reject, notify user to re-upload | §9.1 errors | MUST | FULL | Open/repair/render probes |
| EXT-37 | Processing timeout → up to 2 retries, then administrator notification | §9.1 errors | MUST | FULL | RabbitMQ retry queue + DLQ + alert event |
| EXT-38 | Unreadable file or unmapped sheets → signal for NOT_COMPARABLE | 03 rules | MUST | FULL | Page/file readability flags |
| EXT-39 | OCR: 100-page PDF ≤ 3 min (±30 s) | §11 п.2 | MUST | FULL | Measured ≈ 112 s on the dev box |
| EXT-40 | OCR: 500-page PDF ≤ 10 min (±60 s) | §11 п.3 | MUST | FULL | ≈ 9.3 min measured; mitigations in §3.4.6 |
| EXT-41 | Visual check of mandatory реквизиты on scanned ИД (подписи, печати, даты, рег. номера) | §5 прим. 2 | SHOULD | SIMPLIFIED | Blue-ink/shape heuristics plus regex |
| EXT-42 | Detect stamps «В производство работ» / «Выполнено согласно проекту» | §5 прим. 3 | SHOULD | SIMPLIFIED | Stamp-zone OCR plus fuzzy match (pilot p9 has one) |
| EXT-43 | Record extraction component versions (pipeline, OCR model, embedder) → model_version | §9.2 п.1, §9.4, §14.2 | MUST | FULL | `extraction_runs` |
| EXT-44 | Keep raw text, engine and confidence per value for reason codes such as OCR_ERROR and «ошибка привязки» | §9.3 п.2, §9.4 | MUST | FULL | Needed for inspector UI and retraining statistics |
| EXT-45 | ML module in Python ≥ 3.11; REST plus RabbitMQ | §1.5 | MUST | FULL | Python 3.11 worker |
| EXT-46 | JSON REST endpoints validated against OpenAPI 3.0 | §1.3 | MUST | FULL | Node API facade |
| EXT-47 | Async pull: extraction progress visible through process status | §1.4 | MUST | FULL | Progress events → process status PARSING |
| EXT-48 | Structured JSON logs with the mandatory fields | §13 п.1 | MUST | FULL | structlog |
| EXT-49 | Prometheus metrics for extraction | §13 п.4–5 | SHOULD | FULL | `/metrics` |
| EXT-50 | Encryption at rest and 152-ФЗ for caches/artifacts; no external transfer of document content | §12.3, §12.6 | MUST | SIMPLIFIED | Encrypted volume/AES-GCM artifacts; no cloud by default |
| EXT-51 | Visibility-aware extraction: skip invisible text (render mode 3), text occluded by opaque annotations, text outside the visible area; do not ingest expert markup | §9.1 п.4 «видимой области», pilot | SHOULD | FULL | Pilot white-ink redactions and red callouts |
| EXT-52 | Scans under 300 dpi still processed, with a LOW_DPI warning | §9.1 п.1 | SHOULD | FULL | Pilot p14 is 200 dpi; DOCX scans are about 96 dpi |
| EXT-53 | Orientation (0/90/180/270) and deskew for scans, with coordinates mapped back to the displayed page | §9.1 п.4 | MUST | FULL | OSD plus line-orientation classifier; inverse affine |
| EXT-54 | Optional LLM/VLM assist behind a pluggable interface; deterministic pipeline by default; grounded outputs only | — (152-ФЗ constraint) | NICE | MOCKED | Interface plus local Ollama provider, off by default |
| EXT-55 | OCR evaluation harness and labeled proxy set | §9.1 п.1, §14.3 | MUST | FULL | Needed to prove EXT-06/09/10/12 |
| EXT-56 | Localization evaluation harness (file+page exact, IoU ≥ 0.5, multi-box) | §14.3 | MUST | FULL | Pilot 27 boxes as the seed set |
| EXT-57 | DWG input | §11 п.8 wording | SHOULD | OUT_OF_SCOPE | Inputs are PDF/DOCX/XML; reject with the supported-format list (B01) |
| EXT-58 | Handwriting recognition | §9.1 п.1 (excluded from metric) | NICE | OUT_OF_SCOPE | Detect and abstain only |
| EXT-59 | Plausibility validation of extracted values (implausible → LOW_QUALITY), separate from normative min/max | §8.1 | SHOULD | FULL | Guards against OCR digit errors, e.g. area 5511,65 |

**Totals:** 59 requirements — FULL 45, SIMPLIFIED 11, MOCKED 1, OUT_OF_SCOPE 2.

---

## 3. Proposed design

### 3.1 Architecture and pipeline

```
Node API (upload, registry = B01) ──AMQP cmd "extract.file"──▶  ml-extractor (Python 3.11, N replicas)
                                                               │
 F0 intake      sha256 → Redis lookup parse:v{P}:{sha}  ──hit──▶ reuse artifacts, re-run only NLP if matrix_version changed
                open/repair/encryption/page-count guards ──fail─▶ extraction.rejected (CORRUPTED_PDF …)
 F1 inventory   per page: MediaBox/CropBox/Rotate, image coverage & DPI, visible text stats, vector density,
                annotations/occluders → page_class
 F2 text layer  visible spans/words/chars with unrotated bboxes → normalized (§3.14)
 F3 OCR         render (or extract native image) → orientation/deskew → tiles → PP-OCRv5 → back-map coords
                → merge with text layer (HYBRID) → homoglyph/lexicon post-fix → quality flags
 F4 layout      zones: title block, tables, viewports, stamps/seals/signatures/handwriting, text blocks
 F5 tables      detect → classify (EXPLICATION/TEP/SPEC_21110/…) → typed rows with cell geometry
 F6 CV          vector segments, dimensions, per-viewport scale, distances, room-zone label sets
 F7 NLP         span index (e5-small ONNX) → per-param routes (table/regex/token/CV) → normalize → score
 F8 persist     Postgres: extraction_runs, document_pages, page_zones, extracted_values (+ Checks skeleton)
                object store: page artifacts JSON (spans, tables, drawings summary); Redis summary
 F9 events      extraction.progress / completed{params_touched} / failed / rejected
```

Deployment units (docker-compose ready):
- `ml-extractor` image: python:3.11-slim (multi-arch). It includes `tesseract-ocr`, `tesseract-ocr-rus`, `libreoffice-writer-nogui` (optional profile), and ONNX models baked in: PP-OCRv5 det/rec/cls and e5-small. There is **no torch** in the runtime image.
- Health and metrics come from an embedded FastAPI app on `:8090` (`/health`, `/metrics`, `/internal/*`).
- Workers run one file at a time (AMQP prefetch = 1), with an internal process pool for page-level parallelism.

### 3.2 Page inventory and classification

**Signals per page:**
- `img_cov`: area share covered by image placements, clipped to the visible area.
- `native_dpi`: of the dominant image.
- `vis_chars`: visible text characters. Excluded: render mode 3 (`texttrace.type==3`), text under opaque annotations, text outside CropBox, and text in the colour of the pilot markup inside markup callouts.
- `inv_chars`: invisible text, i.e. a scanner OCR layer.
- `n_paths`: from `get_drawings()`.
- `garbage_ratio`: U+FFFD, Private Use Area characters, control characters, Latin-1 mojibake.
- `dict_hit`: share of tokens found in a Russian + construction lexicon.

**Classes and routing:**

| Class | Rule (defaults, tuned on proxy set) | Route | Pilot evidence |
|---|---|---|---|
| VECTOR | `img_cov<0.5`, `vis_chars≥50`, `garbage<0.05` | Text layer; OCR only on embedded image regions > 5% of page area | p2, p4, p6–p8, p10–p13, p15–p21, p23 |
| HYBRID | `img_cov≥0.5`, `vis_chars≥50` | Text layer, plus OCR of the raster; drop OCR tokens that overlap text-layer tokens (center-in or IoU > 0.3) | p3, p5 (150-dpi full page), p22, p24 (55 tiles of 464×476) |
| RASTER_SCAN | `img_cov≥0.5`, `vis_chars<50` | Full OCR at native resolution | p14 (2352×3307 px, 200 dpi) |
| RASTER_HIDDEN_OCR | `inv_chars≥50` over an image | Re-OCR; keep the hidden layer as a secondary candidate. Use it only if it agrees with our OCR on a 10% sample (CER < 0.05) | — (common in real scans) |
| VECTOR_OUTLINED_TEXT | `img_cov<0.5`, `vis_chars<50`, `n_paths>2000` | Render at 300 dpi, tiled OCR | **p9** (27,421 paths, 19 visible words = the callout only) |
| BROKEN_ENCODING | `garbage≥0.05` or `dict_hit<0.2` with `vis_chars≥50` | OCR | — |
| EMPTY | No ink | Skip, flag | — |

The page class and text source are stored per page, shown as a badge in the UI, and reported as coverage.

### 3.3 Visible text-layer extraction
- Use `page.get_text("rawdict")` (chars → spans → lines → blocks) with the line direction. Store the unrotated bbox and transform it with §3.14. Keep the font name, size, colour and `dir`: vertical text is common in drawings (side stamps, dimensions).
- **Occlusion.** A text item is `occluded=true` when more than 50% of its bbox lies under:
  - an opaque annotation (Ink/Square/FreeText with a fill, or stroke width ≥ 5 pt in white), or
  - a white filled vector rectangle drawn after it.

  Occluded text is not used as visible evidence. It can still be used as a metadata hint, flagged. In the pilot, the white Ink strokes cover title-block cells with "Стадия/Лист/Листов" values and the object address.
- **Pilot sanitizer (applies to pilot files only, detected by the presence of red markup and a Times New Roman callout).** Ignore red strokes of width 2.5/3/4 and all text inside the width-3.0 callout boxes. Keep the red strokes as the **GOLD geometry source** for the localization harness (§3.6.4). Native red CAD lines (width 0.2 on p15) are preserved.
- **Homoglyph harmonization on the text layer too** (§3.12.4), because CAD authors mix `B25` and `В25`.

### 3.4 OCR subsystem

#### 3.4.1 Engine comparison (Russian printed technical documents, CPU)

| Engine | Measured on pilot proxy (char accuracy, horizontal words) | CPU speed | Licence | Docker/ARM | Verdict |
|---|---|---|---|---|---|
| **PP-OCRv5 mobile det + `cyrillic` rec via RapidOCR 3.9 / ONNX Runtime 1.30** | Clean A4 table 0.980; A0 title block/spec 0.974; CAD explication (ISOCPEUR italic) 0.927–0.951; dense plan labels 0.80–0.88 | 1.12 s per dense 300-dpi A4 page (4 workers × 3 threads) | Apache-2.0 (code and models) | pip wheels for manylinux aarch64 and x86_64; no Paddle runtime | **Primary** |
| PP-OCRv5 `eslav` rec | 0.973 / 0.962 / 0.913 / 0.79–0.86 | Same | Apache-2.0 | Same | Kept as an alternative |
| **Tesseract 5.5.2 LSTM `rus+eng` (`tessdata_best` / `tessdata_fast`)** | 0.90–0.92 / 0.77–0.79 / 0.85–0.89 / 0.56–0.82 | ≈ 1.8 s per page per core (fast), scales across processes | Apache-2.0 | apt `tesseract-ocr-rus` | **Fallback + OSD** (`--psm 0`) + second opinion on key fields |
| EasyOCR (torch CRNN) | Not measured. Older Cyrillic model; literature and experience put it below PP-OCRv5 | Slower on CPU, several s/page | Apache-2.0 | Torch aarch64 is OK but heavy (about 1 GB) | Not selected |
| docTR (Mindee) | Not measured. Strong on Latin; pretrained Cyrillic coverage is limited, so it would need fine-tuning | Moderate | Apache-2.0 | OK | Not selected |
| Surya | Not measured. Accurate and multilingual, with layout and tables | Transformer, GPU-oriented, tens of s/page on CPU | GPL-3.0 code, weights under a commercial-restricted licence | Heavy | **Not acceptable for a government deployment**; at most an offline labeling helper |

Measurement caveat: the probe metric matches OCR tokens to text-layer words by bbox. It penalizes line merges and splits and inherits CAD text-layer artefacts (e.g. `EI601`, `5511 ,65`), so the absolute numbers are **lower bounds**. The ranking is robust across all 5 regions (App. A).

#### 3.4.2 Rendering and resolution
- **Scans with a single full-page image:** extract the embedded image at **native resolution** (no resampling), apply the placement matrix, and map back.
- **Pages below 300 dpi:** upsample small-text crops ×1.5 (Lanczos) only when the text-line height is < 20 px. Set a `LOW_DPI` warning below 250 dpi. Pilot p14: 200 dpi gave mean score 0.95 on the tolerance table, 300-dpi re-rendering gave 0.91, so **do not blindly upsample**.
- **Vector-outlined and hybrid pages:** render at 300 dpi. Tile A1/A0 sheets: 3000-px tiles, 150-px overlap, de-duplicating lines in the overlaps by IoU. The largest pilot sheet, 3370×2384 pt, is 14,043×9,933 px at 300 dpi, which is 16 tiles.
- `Global.max_side_len` (detector resize) = 3000 per tile. Recognition dominates the cost (probe P3), so the detector resize matters little for speed.

#### 3.4.3 Orientation, skew and back-mapping
- **Page level:** Tesseract OSD (`--psm 0`) for 0/90/180/270 on scans. The alternative is the PP-LCNet document-orientation ONNX model.
- **Line level:** PP-OCR `cls` (0/180).
- **Vertical text on scans** (side stamps, vertical dimensions): a second detection pass on the image rotated 90°, keeping only lines not found in the first pass.
- **Deskew:** estimate the angle from the dominant text-line/ruling orientation (Hough), rotate if |angle| > 0.3°.
- **Coordinates are always mapped back to the displayed page:** `p_page = A_render⁻¹ · R_deskew⁻¹ · R_k90⁻¹ · T_tile⁻¹ · p_ocr`. Store a 4-point `polygon_norm` and its axis-aligned `bbox_norm`.

#### 3.4.4 Hybrid merge
For HYBRID pages, first OCR the raster. An OCR line is dropped if its centre falls inside a text-layer word bbox with ≥ 60% character overlap. The surviving lines are "raster-only text" (labels baked into the image) and get `source=OCR`.

#### 3.4.5 Post-correction (deterministic, auditable)
1. **Script harmonization** per token (§3.12.4). The raw text is kept.
2. **Numeric-context repairs**, applied only inside tokens matching a numeric shape: `O/О→0`, `З→3`, `l/I→1`, `S→5` when adjacent to digits; `,`/`.` decimal kept as printed.
3. **Lexicon correction** with a Russian construction lexicon (~20k forms built from the ТЗ, the matrix, ГОСТ 21.xxx terms, and the pilot text layer). Only for words with character confidence < 0.8 and edit distance 1. **Never** for codes, numbers or revisions.

#### 3.4.6 Quality flags and throughput
- **Line-level quality flag:** `OK` if the rec score ≥ τ_ok (default 0.85); `LOW_QUALITY` if τ_abs ≤ score < τ_ok (default τ_abs = 0.60); `ABSTAIN` if score < τ_abs or the detector box has no accepted text. The thresholds are calibrated on the proxy set to maximize the character accuracy of accepted text at ≥ 95% coverage.
- **Throughput** (probe P3, dense A4 page with 164 text lines at 300 dpi, PP-OCRv5 cyrillic mobile):

| workers × threads | s/page | 100 pages | 500 pages |
|---|---|---|---|
| 1 × 12 | 3.04 | 304 s | 25.4 min |
| 2 × 6 | 1.63 | 163 s | 13.6 min |
| 3 × 4 | 1.24 | 124 s | 10.3 min |
| **4 × 3** | **1.12** | **112 s** | **9.3 min** |
| 6 × 2 | 1.18 | 118 s | 9.8 min |

- **Mitigations to keep the 500-page target with margin:**
  1. Text-layer-first: vector pages cost about 10–50 ms, with no OCR.
  2. Skip blank pages and pages that are pure drawings with no detected text.
  3. Recognition batch size 16.
  4. INT8-quantized recognition model (ONNX Runtime dynamic quantization, to be validated on accuracy).
  5. Optional page-chunk fan-out across 2 worker replicas (`ml.extract.pages`, 25-page chunks).
  6. Docker CPU allocation ≥ 8 vCPU for `ml-extractor`.

  Performance tests (T-PERF) run on a generated 100/500-page scan corpus.

### 3.5 Quality zones, LOW_QUALITY/ABSTAIN, coverage, реквизиты

**Zone types:** `HANDWRITING`, `STAMP_SEAL`, `SIGNATURE`, `ILLEGIBLE`, `PREMARKED_ILLEGIBLE`, `OCCLUDED`, `TITLE_BLOCK`, `TABLE`, `DRAWING_VIEWPORT`, `TEXT_BLOCK`.

**Detection:**
- **Blue/violet ink** on colour scans: HSV hue 95–150 (OpenCV scale), S > 60, V < 235, morphological close with 25 px, connected components > 3000 px. On pilot p14 this isolated:
  - handwriting [0.767, 0.677, 0.988, 0.782];
  - the seal plus signature cluster [0.483, 0.836, 0.725, 0.940];
  - a signature strip [0.728, 0.806, 0.929, 0.853].

  Components are classified by shape: near-circular or elliptic, 30–50 mm, aspect ≈ 1 → `STAMP_SEAL`; elongated, near «Подп.» cells → `SIGNATURE`; multi-line irregular → `HANDWRITING`.
- **Grayscale scans:** low-confidence clusters (mean rec score < 0.5 over ≥ 3 lines), high stroke-width variance, no baseline regularity → `ILLEGIBLE/HANDWRITING`.
- **Pre-marked zones:** accepted through the API (`POST …/zones`, `source=PREMARKED`) and in the evaluation input file. Every OCR token intersecting such a zone by more than 50% is forced to `ABSTAIN`, and the zone is reported.

**Outputs:**
- The zone flag is `LOW_QUALITY` (text returned but unreliable, e.g. text inside a seal) or `ABSTAIN` (no text).
- Values extracted from `LOW_QUALITY` tokens carry the flag. Values are never extracted from `ABSTAIN` zones.
- Per page, file and run: `coverage` (accepted-text area ÷ detected-text area, excluding premarked/handwriting zones), `low_quality_ratio`, `abstain_ratio`, `zone_share` (area of LOW_QUALITY/ABSTAIN zones ÷ text area), `mean_conf`.

**Реквизиты check (§5 прим. 2) on ИД scans.** Presence booleans with evidence boxes:
- `signature_present`: SIGNATURE zones near «Подп.» cells;
- `seal_present`: STAMP_SEAL;
- `date_present`: regex `\b\d{2}\.\d{2}\.(\d{2}|\d{4})\b` in the title block or act header;
- `reg_number_present`: `№\s*[\w\-/]+` in the act header.

**Stamps (§5 прим. 3).** Detect rectangular blue-ink or black framed zones; OCR the zone (including a 90° pass); fuzzy-match «В ПРОИЗВОДСТВО РАБОТ» / «ВЫПОЛНЕНО СОГЛАСНО ПРОЕКТУ» (token-set ratio ≥ 85). Pilot p9 has a «В ПРОИЗВОДСТВО РАБОТ» stamp in its lower-left corner. This output feeds B01/Module 2 as the `stamps` attribute of the page.

### 3.6 OCR acceptance measurement (evaluation harness)

#### 3.6.1 Proxy datasets (built now; the hidden test is held by the organizers)
| Set | Content | Ground truth | Size target |
|---|---|---|---|
| DS-A synthetic-from-vector | Text-bearing regions (title blocks, tables, notes) of the 18 vector pilot pages rendered at 300 dpi, plus degradations: Gaussian noise, blur σ = 0.6, JPEG q = 70, skew ±1.5°, binarization, 200-dpi variant | Text-layer words (horizontal and vertical separately), after filtering glyph artefacts and callout text | ~60 crops, ~20k chars × 4 variants |
| DS-B real scans | p14 regions (tolerance table, legend, title block); DOCX scans image1–4 (≈ 96 dpi, **low-DPI robustness only**, excluded from the ≥ 300-dpi metric); raster crops in the explained markup | Manual transcription, OCR pre-filled and human-verified | ~6–8k chars |
| DS-C key fields | Title blocks of all pilot pages (шифр, стадия, лист, листов, изм.) plus room numbers and element marks from explications and tolerance tables | Text layer (vector) + manual (scans) | ~300 fields |
| DS-D abstain zones | p14 handwriting, seal and signatures; synthetic handwriting overlays on DS-A crops | Zone JSON | ~30 zones |

#### 3.6.2 Metrics (script `ocr_eval.py`, the same code the ML-engineer UI runs)
- **Normalization for CER:** `NFC`; collapse runs of whitespace to one space; trim; no case folding except for fields flagged `case_insensitive`; **no character deletion**.
- A "relaxed" variant is reported *in addition* to the strict one: dash variants (U+2010–2015, U+2212 → `-`) and the homoglyph map. Strict is the headline figure.
- `CER = Σ Levenshtein(pred, gt) / Σ len(gt)`; `Character Accuracy = 1 − CER`; `WER` via jiwer over normalized token sequences.
- **Alignment is reading-order independent.** GT and prediction are matched per GT line by geometry (polygon IoU > 0.3 or centre-in). Unmatched GT counts as deletions; spurious prediction as insertions. Full-page sequence alignment is kept as a secondary check.
- `coverage = chars in GT lines for which the system returned OK/LOW_QUALITY text ÷ total GT chars (excluding premarked/handwritten zones)`; `abstention = 1 − coverage`.
- `ExactMatch(field) = 1[norm(pred) == norm(gt)]`. Normalization for key fields: NFC, whitespace collapse, strict case, **no removal of signs** (`-./()`).
- **Abstain-zone compliance:** % of DS-D zones where every token is LOW_QUALITY/ABSTAIN. The target is 100%.
- **95% CI:** bootstrap over pages (2000 resamples), percentile interval. Sample sizes are reported alongside.
- Breakdown by zone type (table, title block, notes, drawing labels), page class, DPI bucket and engine.

#### 3.6.3 Report artifact
`ocr_eval_report.json` holds: dataset_version, set hashes, engine and model versions, metrics with CIs, n_chars, n_fields, per-bucket tables, and the worst 20 errors with crops. It is rendered in the ML-engineer UI and consumed by the weekly report (Module 10).

#### 3.6.4 Localization harness (EXT-56)
- **Seed GOLD:** the 27 red width-4 rectangles, mapped to the (file_id, page) of ПРИМЕРЫ РАЗМЕТКИ. All 27 match the listed bboxes with IoU ≥ 0.997.
- **Metric:** a group is correctly localized when every fragment has the exact file_id and page, and the IoU of the **union of predicted boxes** vs the **union of GOLD boxes** is ≥ 0.5 (union computed with shapely).
- It runs on the sanitized pilot files, so the red markup cannot leak.

### 3.7 Layout: title block (основная надпись)
- **Search region:** the bottom-right corner of the visible displayed page, 185 × 55 mm (form 3), plus the vertical side strip for «Инв. № подл.»/«Взам. инв. №», computed in millimetres from the page size. Text documents use forms 5/6 (a smaller stamp at the bottom). ИД documents often have the ИС form (pilot p10 «Стадия … ИС»).
- **Cell-based reading.** Find the anchor labels «Стадия», «Лист», «Листов», «Изм.», «Кол.уч.», «№ док.», «Подп.», «Дата». The value of a label is the text inside the same grid cell in the next row. Cell boundaries come from vector ruling lines, or from the OpenCV grid on scans. Reading order in the text layer is jumbled (probe P1), so the text stream is never parsed linearly.
- **Шифр.** The code cell is the widest cell with the largest font in the stamp. Regex: `[0-9А-ЯA-Z][0-9А-ЯA-Zа-я./\-]{3,}-(?:[А-ЯA-Z]{1,5}[0-9.]*)(?:[-./][0-9А-ЯA-Z.()]+)*`. Line-joining: a token ending in `-` concatenates with the next line in the same cell. Pilot examples: `133-0820-ОК-1-` + `…`, `130-1222-ОК-1/Н-` + `АР…`.
  - Pilot codes found: `П-2025-04.266-АР` vs `РД-2025-04.266-АР`; `59-0222-П-5Э-АР2`; `305-0294-5Э-Р-АР`; `19-0322-ОК-1/Н-АР`; `04-П.СКБ-ПИР-П` vs `…-Р`; `24-П-ПИР-П` vs `…-Р`.
  - The **stage letter** is often embedded in the code (`-П-` / `-Р-`). This is a cross-check against the «Стадия» cell.
- **Stage mapping:** `П→PD`, `Р→RD`, `ИС/И→ID`, `РП/ЭП → flag`. A title-block stage ≠ registry `doc_stage` → `STAGE_MISMATCH` hint to B01 (CLARIFICATION_REQUIRED is B01/Module 2's call).
- **Revision.** Highest «Изм.» number in the change-registration rows of the stamp (e.g. p7 `1 Зам. - 12.05.2025` → revision 1, change type «Зам.», date), plus «Ведомость изменений» tables (pilot p13).
- **Output per page:** `title_block = {document_code, stage, sheet_label, sheets_total, revision, revision_date, sheet_title, organization, scale_declared[], fields[{name, value_raw, value_norm, bbox_norm, conf, source}]}`.

### 3.8 Tables

- **Vector detection.** `page.find_tables(strategy="lines")` in candidate regions found by header keywords, falling back to `strategy="text"`. Candidate-first matters because `find_tables` took 6.7 s on the 112k-path p19 when run on a large clip.
- **Header classifier.** Regex plus e5-small similarity on the first 1–3 rows and the caption above the table:

| table_type | Header cues | Typical params |
|---|---|---|
| EXPLICATION | «Экспликация помещений», №/Номер, Наименование/Имя, Площадь м², Кат. помещения | M-002, M-003, M-010, M-011; pilot findings ALT79B/POL16/DOO25/SOSH25/POL17 |
| TEP | «Технико-экономические показатели», «ТЭП», Наименование показателя, Ед. изм., Количество | M-001…M-020, M-131 |
| SPEC_21110 | Поз., Обозначение, Наименование, Кол., Масса ед. кг, Примечание (ГОСТ 21.110 form 1; also «Код оборудования…», «Завод-изготовитель») | M-029, M-046, M-055…M-057, M-069, M-072, M-075, M-077, M-079, M-080, M-103, M-109, M-112, M-120, M-130 |
| OPENING_SCHEDULE | «Ведомость заполнения проемов», «Спецификация элементов заполнения проемов» | M-041, M-046, M-103, M-105, M-117 |
| FINISH_SCHEDULE | «Ведомость отделки помещений» (ГОСТ 21.501) | M-050, M-107 |
| REBAR_SCHEDULE | «Ведомость расхода стали» | M-057, M-062, M-067 |
| SHEET_LIST / REF_DOCS | «Ведомость рабочих чертежей…», «Ведомость ссылочных и прилагаемых документов» | B01 completeness, sheet mapping |
| CHANGE_LOG | «Ведомость изменений», «Изм. Лист Содержание изменения Код» | Revisions; pilot LOS3A «В квартире 2.4.1 подвинулась дверь…» |
| DEVIATION_TABLE (ИД) | проект/факт/отклонение, «откл. от проект.», допуск | M-054, M-058…M-061, M-064; pilot OKT103 |
| CALENDAR_PLAN | Наименование этапа, продолжительность, мес./дни | M-082 |
| COORDINATES | X, Y, (Z), № точки | M-034 |

- **Side-by-side splitter.** When a detected table's header row repeats a column pattern (p19: three explications merged into 31 columns), split at the repetition boundaries.
- **False-positive filter.** Drop "tables" with fewer than 3 rows × 2 columns, no header match, or inside a DRAWING_VIEWPORT with a mostly numeric grid (dimension chains on p2).
- **Raster tables.** Binarize, then extract horizontal and vertical rulings with morphological opening (kernels = 1/40 of the width/height), then intersections → grid → merged-cell inference. OCR lines are assigned to cells by centre-in. **Borderless** tables: cluster x-positions into columns, with confidence 0.5.
- **Typed parsers:**
  - EXPLICATION → `rooms[{room_no (as printed, leading zeros kept: «012», «1.109», «2.4.1»), name, area_m2, category, bbox_row, bbox_cells{}}]`, `totals[{label «Итого/Всего/Итого по этажу», value, bbox}]`, `context{floor, section, sheet_title}`.
  - TEP → `indicators[{label, unit, value, bbox}]`.
  - SPEC_21110 → `items[{pos, designation, name, unit, qty, mass, note, grade_tokens[]}]`.
  - DEVIATION_TABLE → `points[{element_id, design, actual, deviation_mm, bbox}]` plus `tolerances[{param, tol_mm, sign(±), source_bbox}]`, parsed from the legend («допускаемое отклонение … 15 мм», «±12 мм»). On p14 the table values +491/+552, +980/+537 were read at confidence ≥ 0.96.
- **Output.** Tables are stored in the page artifact with cell geometry. EXPLICATION, TEP, SPEC and DEVIATION rows are also materialized as `extracted_values` for their params, and as `page_tables` rows (typed JSON) for set-diffs in Module 2.

### 3.9 DOCX
- **Parsing:** python-docx for body paragraphs (with style/heading level), tables (gridSpan/vMerge → merged cells), headers and footers (text documents carry the ГОСТ Р 21.101 form 5/6 stamp as footer tables), and inline/floating images. Images are extracted and OCR'd as RASTER pages. The provided «Перечень» DOCX = 9 paragraphs + 2 tables + 4 scanned images.
- **Displayable geometry.** Convert to PDF with LibreOffice headless (`soffice --headless --convert-to pdf`) inside the container. Map each paragraph and cell to rendered-PDF bboxes by ordered text search (`page.search_for` constrained by expected order). Locator: `{kind:"DOCX", page_basis:"RENDERED_LIBREOFFICE", page_no, bbox_norm, native:{part, paragraph_idx | table_idx,row,col}}`. The pagination caveat is recorded (Word vs LibreOffice may differ).
- **Rejected:** legacy `.doc`, macro-enabled `.docm` (B01). **Zip-bomb guard:** limit uncompressed size to 200 MB and part count to 5,000.

### 3.10 XML
- **Which XML is realistic:**
  1. The **ПЗ XML** of the Минстрой schema, mandatory for state expertise submissions. It carries ТЭП, object data and the section list in structured form — the richest source for M-001…M-023.
  2. The **Заключение экспертизы** XML.
  3. **Electronic ИД** documents under Приказ 344/пр: АОСР, acts of inspection of structures/networks, the общий журнал работ. Минстрой XML schemas exist or are being piloted; *to be confirmed by the organizers*.
  4. The **Технический план** (Росреестр XML), which is the literal ИД source «Технический план БТИ» for M-001…M-012.
- **Design:**
  - Safe parsing: `lxml` with `resolve_entities=False, no_network=True, huge_tree=False`, or `defusedxml`.
  - Detect the schema from the root QName, namespace and version attribute → adapter registry `{schema_id: {xpath → param_code/metadata field, unit, parser}}`.
  - **Generic fallback:** flatten to `(xpath, text, attrs)` leaves → treated as spans for anchors and regex.
  - Optional XSD validation when an XSD is available; errors → «некорректные данные» (Module 12).
- **Display.** Generate a deterministic "XML view" PDF: one leaf per line, indentation by depth, with the xpath shown. Evidence gets a page and bbox on that view. Locator: `{kind:"XML", page_basis:"RENDERED_XML_VIEW", xpath, page_no, bbox_norm}`.
- **MVP:** generic flattener plus **one** adapter. Recommended: ПЗ XML ТЭП, using a synthetic instance built from the public XSD if no sample arrives.

### 3.11 NLP parameter extraction

#### 3.11.1 Extraction profile (per param; stored in DB table `param_extraction_profiles`, keyed by `params.code`, versioned with matrix_version)
```yaml
code: M-055                      # also accepts ТЗ-style alias KR-55 (numbers align: KR-55 = M-055)
data_type: enum                  # number|string|boolean|coordinate|enum (§8.1)
unit_canonical: class_B
value_parser: concrete_class     # → {value:"B30", rank:30}
routes: [TABLE, TOKEN_GRAMMAR, REGEX]
doc_scope: {stages: [PD, RD, ID], disciplines: [КР, КЖ], doc_types: [ОД, СПЕЦИФИКАЦИЯ, ЖБР, ПАСПОРТ_БСГ, ПРОТОКОЛ_ИСПЫТАНИЙ],
            table_types: [SPEC_21110, REBAR_SCHEDULE]}
anchors: ["класс прочности бетона", "бетон класса", "бетон тяжелый", "марка бетона по прочности"]
negative_anchors: ["бетонная подготовка"]      # B7.5 underlayer ≠ structural concrete
regex_pattern: "(?P<value>[BВ]\\s?\\d{1,3}(?:[.,]5)?)(?!\\d)"   # read from Params.regex_pattern (≤255)
context_window: {same_line: true, same_cell_row: true, max_distance_mm: 30}
aggregation: per_element_list    # list of (element, class) pairs; Module 2 compares per element
plausibility: {allowed: [B7.5 … B100]}
priority: HIGH
```
Profiles are auto-drafted for all 132 params from the matrix columns (`Источник в ПД/РД/ИД` → doc_scope; parameter name + unit → anchors; unit → parser). **~35 are then hand-curated deep profiles:**
- ТЗ examples: PZ-01 = M-001, KR-55 = M-055, AR-41 = M-041.
- Parameters the pilot exercises: M-002, M-003, M-010, M-044, M-054, M-058–M-061, M-078/M-079 (ventilation), M-103, M-107.
- Other high-yield table/token parameters.

The remaining parameters use the **generic profile**: anchor search, then typed value next to the anchor. Every run reports honest coverage per parameter.

#### 3.11.2 Algorithm (per file, after F2–F6)
1. **Span index.** All visible spans (text layer and OCR lines), table cells with row/column headers, XML leaves. Dedupe identical strings; embed with e5-small (`"query: "` prefix, measured ≈ 1,000 unique spans/s on CPU; the 24 pilot pages = 1,533 unique spans in 1.5 s). Cached per sha256 + embedder version.
2. **Parameter selection.** Active params (`is_active`) whose `doc_scope` matches the file's (stage, discipline, doc type from title block/registry).
3. **Candidate routes:**
   - **TABLE:** tables of the listed types → row-label similarity (cos ≥ 0.80, calibrated) → parse the value cell.
   - **REGEX:** `Params.regex_pattern` over spans within the context window of anchor hits (named groups `value`, `unit`).
   - **TOKEN_GRAMMAR:** class grammars (§3.12.3) find tokens, then attach them to the nearest anchor context (e.g. «Бетон» on the same line).
   - **CV:** dimension or geometric measurement (§3.13) for M-030, M-040, M-042, M-047, M-048, M-058–M-061, M-104, M-116, M-119, and similar.
   - **PRESENCE:** boolean presence of anchors/legend items/spec positions (M-039, M-053, M-063, M-092, M-115, M-120, M-122, M-123, M-129).
4. **Scoring:** `s = 0.35·anchor_sim + 0.25·regex_or_grammar_match + 0.15·table_type_prior + 0.10·doc_scope_prior + 0.15·text_conf`, minus penalties (occluded, LOW_QUALITY, plausibility fail, negative anchor). Keep the top-k (k = 3) candidates per (param, file). When two candidates with different values are within 0.05 → `is_ambiguous=true`. Module 2 must then emit NOT_COMPARABLE/CLARIFICATION, not a violation.
5. **Evidence geometry.** `token_boxes` (tight), `evidence_boxes` (region: the table row across value + label cells, or the anchor + value line, padded 1 mm), and the anchor box. See §5 R2 for why region boxes matter for IoU.
6. **Per-param extraction status per file:** `FOUND`, `NOT_FOUND`, `OUT_OF_SCOPE`, `LOW_QUALITY_ONLY`, `AMBIGUOUS`. Module 2 uses it for MISSING_EVIDENCE/NOT_APPLICABLE decisions.

#### 3.11.3 Embedder choice (probe P6)
Query set: 40 realistic Russian table/row labels ("Бетон класса В30 W8 F150", "Ширина коридора в свету 1,4 м", …). Target: the matrix M-code. Anchors: "parameter name (unit)".

| Model | Params | Top-1 | Top-3 | Query latency p50 (CPU, 4 threads) | Note |
|---|---|---|---|---|---|
| **intfloat/multilingual-e5-small** | 118 M | **34/40** | **38/40** | **8.3 ms** | Selected (MIT) |
| cointegrated/LaBSE-en-ru | 129 M | 34/40 | 38/40 | 23.9 ms | Same quality, 3× slower |
| intfloat/multilingual-e5-base | 278 M | 34/40 | 35/40 | 23.2 ms | — |
| cointegrated/rubert-tiny2 | 29 M | 29/40 | 32/40 | 1.5 ms | Fallback for extreme latency |
| sentence-transformers/all-MiniLM-L6-v2 (ТЗ name) | 23 M | 27/40 | 32/40 | 4.5 ms | English-only; wins only on shared sub-tokens (units, codes) |
| paraphrase-multilingual-MiniLM-L12-v2 | 118 M | 22/40 | 31/40 | 7.8 ms | Surprisingly weak here |
| Lexical baseline (rapidfuzz token_set) | — | 29/40 | 34/40 | < 1 ms | — |
| e5-small + lexical hybrid (w_sem 0.6) | — | 31/40 | 36/40 | — | Hybrid did not help; enriched anchors (+sources) 33/40 |

`ai-forever/sbert_large_nlu_ru` (427 M params, ≈ 1.7 GB) was not run. It is about 3× larger than e5-base and has no quality reason to beat it at this latency budget; it remains an option if a Russian-only model is demanded. `deepvk/USER-base` failed to load with the current sentence-transformers and can be retried in ONNX.

**Runtime:** export e5-small to ONNX (optimum), run it with onnxruntime + tokenizers (no torch in the image). **Latency budget per parameter:** query embedding ≈ 8 ms + dot product over ≤ 30k spans < 5 ms + regex/grammar on ≤ 200 candidate spans < 20 ms + table parse < 20 ms → **≈ 50 ms p95 ≪ 500 ms** (§11 п.7). This is measured by a benchmark test on every build.

### 3.12 Normalization (library `norm/`, ≥ 150 golden tests)

#### 3.12.1 Numbers
- Decimal comma or point (`6234,1`, `8.99`).
- Thousands separators: space, NBSP, U+2009, U+202F (`6 234,1`).
- Signs `+ − (U+2212) ±`.
- Ranges `1,5–1,8`.
- Elevations `±0,000=+123,350`, `-3.950` (metres, 3 decimals, from context).
- Deviations `+491` (mm).
- Room numbers and marks are **strings, not numbers** (`1.109`, `012`). The column type decides.

#### 3.12.2 Units → canonical
- Area: `м²|м2|кв\.?\s?м` → m2.
- Volume: `м³|м3|куб\.?\s?м` → m3.
- Length: `мм|см|м|км`.
- Power: `Вт|кВт`, `Гкал/ч`.
- Flow: `м³/ч`, `м³/сут`, `л/с`.
- Pressure: `Па`.
- Slope and angle: `‰`, `%`, `°`.
- Counts: `шт.|компл.`; people: `чел.`; time: `дни`; money: `тыс. руб.`.
- Thermal: `Вт/(м·°С)`, `м²·°С/Вт`; electrical: `Ом`, `А`, `мм²`.

Each value stores `{raw, value, unit_raw, unit_canonical, factor}`, and the canonical unit follows `Params.unit`.

#### 3.12.3 Class systems (value + ordinal `rank` so Module 2 can detect «понижение»)
| System | Pattern (after harmonization) | Rank rule |
|---|---|---|
| Concrete strength | `[BВ]\s?(\d{1,3}([.,]5)?)`; legacy `М\d{3}` → B via ГОСТ 26633 table (e.g. М300 ≈ B22,5) | numeric ↑ better |
| W / F | `W\s?\d{1,2}`, `F\d?\s?\d{2,4}` (F150, F1 150) | numeric ↑ |
| Rebar | `[AА]\s?-?\s?(240|400|500|600|800|1000)\s?[CС]?П?`; legacy A-I→A240, A-III→A400 | numeric ↑; `C` (weldable) flag |
| Steel | `С\s?(235|245|255|275|285|325|345|355|375|390|440|590)`; grades `09Г2С`, `Ст3пс` | numeric ↑ |
| Fire resistance | `(R|RE|REI|EI|EIW|E)\s?-?\s?(15|30|45|60|90|120|150|180|240)` | minutes ↑; letters must be ⊇ |
| Material fire hazard | `КМ\s?[0-5]` | КМ0 best (rank inverted) |
| Construction fire hazard | `[СC]\s?[0-3]` near «класс конструктивной пожарной опасности» | С0 best |
| Fire-resistance degree | `I|II|III|IV|V` (Roman, Latin I vs Cyrillic І folded) | I best |
| Energy class | `A\+\+|A\+|A|B\+|B|C\+|C|C-|D|E` (also Cyrillic А/В/С) | A++ best |
| Power reliability category | `I|II|III` (also «1-й»…) | I best |
| Cable marks | `нг\(А\)(-[A-Z]+)*`, flags FR, LS, HF, LTx | Contains FR required for ПЗ circuits |
| Pipe/duct size | `(Ду|DN|Ø|⌀|d\s?=)\s?\d{2,4}`; `\d{2,4}\s?[xх×]\s?\d{2,4}` → area mm² | numeric |
| Door marks | Sizes from marks («ДГ 21-9» → 2,1×0,9 m in dm-coded legacy marks; ГОСТ 475-2016 marks with mm sizes) | width in m |

#### 3.12.4 Script harmonization (homoglyphs)
- **Token-level decision:** if a token has ≥ 1 Cyrillic-only letter, or matches a Cyrillic-context code pattern (шифр segments АР/КЖ/КР/ОВ/ВК/ЭОМ/ОК/ПИР/ИС, «Лист», room words), map the Latin look-alikes `A B C E H K M O P T X a c e o p x y` → Cyrillic. The reverse (Cyrillic→Latin) applies to allow-listed Latin tokens (EI, REI, FRLS, LS, HF, W, F, DN, RAL, B-class canonical form).
- **Canonical forms:** concrete class `B30` (Latin B, by convention); document codes keep Cyrillic. Raw text is always stored. Evidence cards show the raw text; comparisons use the normalized text.

### 3.13 CV module (realistic MVP)

#### 3.13.1 Vector drawings (primary; most CAD PDFs)
- **Segments** come from `get_drawings()`: `l` items, plus decomposed `re`/`qu`. Measured 0.1–0.7 s per sheet up to 112k paths.
- **Dimension detection:** numeric text (`\d{3,5}`, or decimals in m) + a parallel segment of matching orientation within 2.5 text heights + extension lines or tick/arrow marks at the ends.
- **Scale per viewport:** each dimension votes `ratio = value_mm / (L_pt · 25.4/72)`, snapped to the standard scales {1, 2, 5, 10, 20, 25, 50, 75, 100, 200, 250, 400, 500, 1000} with |log error| < 0.03. Votes are clustered spatially: one sheet can hold several viewports at different scales, as pilot p2 has «М1:100» plus fragments «1:50».
- **Cross-check** with declared scales found in text (`М\s*1\s*:\s*(\d+)`, `1\s*:\s*\d{2,3}` near viewport captions) and the title block. Output: `viewport{bbox, scale, votes, declared, agreement}`.
  - Probe P7 results: p2 → 100 (declared 100/50); p4 → 100 (declared 100); p21 → 100 (declared 100); p15 → 100 (43 votes); p19 → 200.
- **Distance measurement:** `d_mm = |P1−P2|_pt · 25.4/72 · scale`, between two points/segments, or as the orthogonal distance between parallel wall lines at a probe location. Exposed as `POST /internal/measure` for Module 2 and the UI "ruler". Values measured this way carry `method=CV_MEASURE` and the confidence of the scale agreement.
- **Room zones and label sets.** Room-number texts (from explications and plan labels) are seeds. Every other label on the plan (system marks `В2.4`, `П2/ВЕ`, door marks `Д-1`, equipment positions) is assigned to the nearest room seed. Voronoi partition, refined by enclosing closed wall polylines when they exist. Output `room_labels{room_no: [labels…]}` supports pilot-style configuration diffs:
  - ventilation branches in rooms 140/142/147/198/314 (explained markup);
  - door move (LOS3A);
  - room function changes (ALT79B, DOO25).

  On the explained-markup raster crops, OCR recovered `B2.4…B2.10`, `П2/BE` with the Latin-B homoglyph. That is expected and harmonized.

#### 3.13.2 Raster drawings (scans)
- LSD (`cv2.createLineSegmentDetector`) or probabilistic Hough on a deskewed binary image → segments.
- Dimension text via OCR + nearby parallel segments → the same voting → scale with `confidence ≤ 0.6`.
- Distances are reported with a pixel-quantization error bound, `±(2 px · 25.4/dpi · scale)` mm.

#### 3.13.3 What CV can and cannot do in the MVP
| Capability | Vector | Raster | MVP |
|---|---|---|---|
| Scale per viewport | High | Medium | Yes |
| Dimension values (text) | High | Medium (OCR) | Yes |
| Geometric distance between chosen lines | High | Low–medium | Yes (flagged on raster) |
| Room label sets / configuration diff by labels | Medium–high | Medium (OCR) | Yes |
| Stamps / seals / signatures / handwriting | n/a | Medium | Yes (§3.5) |
| Symbol counting (detectors, sprinklers, radiators) | Low (block identity lost in PDF) | Low | **No**: use spec tables and text marks instead |
| Hatch/contour semantics (warm-floor loops) | Low | Low | **No**: label/legend-based only |
| DWG parsing | — | — | **No** (§6 C1) |

### 3.14 Coordinates (§9.1 step 4): exact math and tests

**Canonical space `PDF_VISIBLE_ROTATED_TL_V1`** is defined as follows:
- normalized to the **visible area V = CropBox ∩ MediaBox** (CropBox defaults to MediaBox), **after /Rotate**;
- origin at the top-left of the page *as displayed*; x to the right, y downward; values in [0;1].

The pilot GOLD boxes follow exactly this convention (27/27 IoU ≥ 0.997).

Given a point (X, Y) in PDF default user space (after the content-stream CTM, bottom-left origin, y up):
```
vx0 = max(M.x0, C.x0); vy0 = max(M.y0, C.y0); vx1 = min(M.x1, C.x1); vy1 = min(M.y1, C.y1)
W0 = vx1 − vx0;  H0 = vy1 − vy0;  r = Rotate mod 360  (Rotate must be a multiple of 90; −90 ≡ 270)
u = (X − vx0) / W0          # unrotated, left→right
v = (vy1 − Y) / H0          # unrotated, top→down
r =   0: (x, y) = (u,     v)
r =  90: (x, y) = (1 − v, u)          # page shown rotated 90° clockwise
r = 180: (x, y) = (1 − u, 1 − v)
r = 270: (x, y) = (v,     1 − u)
Displayed size: (Wd, Hd) = (W0, H0) for r ∈ {0,180}; (H0, W0) for r ∈ {90,270}.   /UserUnit cancels out.
```
- **bbox:** transform the 4 corners, then take min/max (a multiple-of-90 rotation keeps boxes axis-aligned).
- **polygon:** transform each vertex. Order: clockwise starting at the top-left vertex in displayed space.
- Values are clipped to [0;1] and stored as float8, API rounding to 6 decimals.
- **Multi-box geometry:** `geometry = {"boxes": [[x0,y0,x1,y1],…], "polygons": [[[x,y],…],…]}`. The pilot uses 2 boxes per page for several findings.

**Library equivalences (verified):**
- **PyMuPDF.** Text and drawing rects are in unrotated, top-left, CropBox-relative space, so `norm = (rect * page.rotation_matrix) / (page.rect.width, page.rect.height)`.
- **Raster OCR.** Pixel (px, py) on the image rendered by `get_pixmap()` (which applies CropBox and Rotate) → `(px/Wpx, py/Hpx)`. Deskew, tile and k·90 corrections are inverted first (§3.4.3).
- **PDF.js (front end).** `page.view` = CropBox ∩ MediaBox and `getViewport({scale, rotation: page.rotate})` gives the displayed frame, so `x_px = x·viewport.width`, `y_px = y·viewport.height`. The shared fixtures run in a Playwright test (EXT-31).

**Test vectors (probe P5; black rectangle at user-space X∈[M.x0+100, M.x0+200], Y∈[M.y0+600, M.y0+700] or [M.y0+500, M.y0+600] for short pages):**

| Fixture | MediaBox | CropBox | Rotate | Expected bbox_norm (formula = PyMuPDF = rendered) |
|---|---|---|---|---|
| A4_plain | [0 0 595 842] | — | 0 | [0.1681, 0.1686, 0.3361, 0.2874] |
| offset_crop_r0 | [0 0 600 800] | [50 100 550 750] | 0 | [0.1000, 0.0769, 0.3000, 0.2308] |
| offset_crop_r90 | [0 0 600 800] | [50 100 550 750] | 90 | [0.7692, 0.1000, 0.9231, 0.3000] |
| offset_crop_r180 | [0 0 600 800] | [50 100 550 750] | 180 | [0.7000, 0.7692, 0.9000, 0.9231] |
| offset_crop_r270 | [0 0 600 800] | [50 100 550 750] | 270 | [0.0769, 0.7000, 0.2308, 0.9000] |
| neg_origin_mediabox_r90 | [−300 −400 300 400] | [−250 −300 250 350] | 90 | [0.7692, 0.1000, 0.9231, 0.3000] |
| rot_minus90_as_270 | [0 0 600 800] | — | −90 | [0.1250, 0.6667, 0.2500, 0.8333] |

**Additional fixtures to add in B02-T02:**
- a CropBox extending beyond the MediaBox (the intersection rule);
- a Form XObject with its own `/Matrix`;
- a scanned page image placed with a rotation `cm`;
- a scan rotated by content (OSD 90°) with `/Rotate 0`;
- a 1.2° skewed scan (polygon back-mapping);
- a DOCX rendered page;
- the XML view.

**Page numbering:** `page_no` is the **1-based PDF page**, matching the pilot «стр.N». `sheet_label` is the printed «Лист» value and is stored separately.

### 3.15 Persistence: data model (PostgreSQL; names aligned with §10)

```sql
-- B02-owned
extraction_runs(id uuid pk, file_id fk→files, file_sha256 char(64), process_id, pipeline_version text, ocr_engine text,
  ocr_model_version text, embed_model_version text, matrix_version text, status text, attempt int, cache_hit bool,
  started_at, finished_at, duration_ms int, pages_total int, pages_ocr int, error_code text, metrics jsonb)  -- coverage, low_quality_ratio, abstain_ratio, mean_conf, zone_share
document_pages(id uuid pk, run_id fk, file_id fk, page_no int, sheet_label text, mediabox float8[4], cropbox float8[4],
  rotate int, disp_w_pt float8, disp_h_pt float8, page_class text, text_source text, native_dpi int, render_dpi int,
  mean_conf real, coverage real, low_quality_ratio real, abstain_ratio real, title_block jsonb, stamps jsonb,
  artifact_uri text, unique(file_id, page_no, run_id))
page_zones(id uuid pk, page_id fk, zone_type text, geometry jsonb, quality_flag text /*OK|LOW_QUALITY|ABSTAIN*/,
  confidence real, source text /*AUTO|PREMARKED|INSPECTOR*/, attrs jsonb, created_by uuid null, created_at)
page_tables(id uuid pk, page_id fk, table_type text, geometry jsonb, header jsonb, rows jsonb /*typed rows with cell boxes*/, confidence real)
extracted_values(id uuid pk, run_id fk, file_id fk, file_sha256 char(64), object_id fk, doc_stage text, discipline text,
  document_code text, revision text, approval_status text, page_id fk null, page_no int, sheet_label text,
  param_id fk→params, param_code text, data_type text, value_raw text, value_norm jsonb /*{type,value,unit,rank,qualifiers}*/,
  unit_raw text, unit_norm text, geometry jsonb /*{token_boxes, evidence_boxes, polygons}*/, anchor jsonb, context_text text,
  table_ref jsonb, locator jsonb /*DOCX/XML native locators*/, method text /*TEXT_LAYER|OCR|TABLE|REGEX|TOKEN_GRAMMAR|SEMANTIC|CV_MEASURE|XML_XPATH|DOCX|VLM_ASSIST*/,
  source_engine text, confidence real, quality_flag text, is_ambiguous bool, candidate_rank smallint,
  pipeline_version text, matrix_version text, created_at)
param_extraction_status(run_id, file_id, param_code, status /*FOUND|NOT_FOUND|OUT_OF_SCOPE|LOW_QUALITY_ONLY|AMBIGUOUS*/, n_candidates, primary key(run_id,param_code))
param_extraction_profiles(param_code pk, matrix_version, profile jsonb, updated_at, updated_by)
-- indexes: extracted_values(object_id, param_code, doc_stage), (file_sha256, pipeline_version, matrix_version), GIN(value_norm)
```
**Proposed additions to Module-2-owned tables:**
- `evidence_fragments.extracted_value_id` (FK), `file_sha256`, `document_code`, `revision`, `approval_status`. The evidence card then needs no joins across the registry at render time, and it is immutable per protocol version.
- `bbox_polygon_norm` uses the multi-box `geometry` JSON.

**Checks skeleton.** To satisfy «Выход: таблица Checks» literally, B02 upserts one `checks` row per (object_id, active param) with `completeness_status` pre-filled from `param_extraction_status` (e.g. `MISSING_EVIDENCE` candidate when no in-scope file yielded a value), and pre-creates the `evidence_group_id`. Module 2 fills expected/actual/delta and `finding_status`. *To be agreed with the Module 2 block.*

### 3.16 Redis cache and artifacts
| Key | Value | TTL |
|---|---|---|
| `parse:v{P}:{sha256}` | `{run_id, artifact_uri, pages, page_classes, engine_versions, created_at}` (≤ 4 KB) | 30 d |
| `parse:page:v{P}:{sha256}:{page_no}` | pointer + page summary (class, coverage) | 30 d |
| `values:v{P}:m{matrix_version}:{sha256}` | extracted_values run id (NLP layer depends on the matrix) | 30 d |
| `emb:v{E}:{sha256}` | pointer to the span-embedding matrix (npy in the object store) | 30 d |
| `lock:parse:{sha256}` | `SET NX PX 900000`, dedupes concurrent parses of the same file | 15 min |

- `P` = pipeline version (semver + git sha; it covers OCR model and parameter versions). `E` = embedder version.
- When the matrix changes, only F7 (NLP) re-runs: text, OCR and tables are reused. This is what makes the **incremental update ≤ 1 min** (§11 п.9) realistic.
- Heavy payloads (spans, tables, drawings summaries, embeddings) go to the object store: a local FS volume in dev, MinIO in Docker. Keys: `artifacts/{sha256}/v{P}/page-{n}.json.zst`. They are encrypted at rest (AES-GCM, key from secret; SIMPLIFIED: encrypted volume).
- Redis runs with AUTH, bound to the internal network, `appendonly no` (a cache only). The Postgres rows are the source of truth.

### 3.17 REST endpoints (Node public API, OpenAPI 3.0 validated; Python internal)
| Method | Path | Role | Request / response (sketch) |
|---|---|---|---|
| GET | `/api/v1/files/{fileId}/extraction` | inspector+ | `{run_id, status, attempt, cache_hit, versions{pipeline, ocr, embed, matrix}, metrics{coverage, low_quality_ratio, abstain_ratio, mean_conf}, pages_total, pages_ocr, error_code?}` |
| GET | `/api/v1/files/{fileId}/pages` | inspector+ | `[{page_no, sheet_label, disp_w_pt, disp_h_pt, rotate, page_class, text_source, quality{…}, title_block{…}, stamps{…}}]` |
| GET | `/api/v1/files/{fileId}/pages/{pageNo}/text?level=line\|word` | inspector+ | `[{text, text_raw, geometry, conf, quality_flag, source}]` |
| GET | `/api/v1/files/{fileId}/pages/{pageNo}/zones` | inspector+ | `[{zone_id, zone_type, geometry, quality_flag, source, attrs}]` |
| POST | `/api/v1/files/{fileId}/pages/{pageNo}/zones` | inspector, ml_engineer | `{zone_type:"PREMARKED_ILLEGIBLE", geometry}` → 201; triggers re-evaluation of affected values |
| GET | `/api/v1/files/{fileId}/pages/{pageNo}/tables` | inspector+ | `[{table_id, table_type, geometry, header, rows[{cells[{text, geometry}]}]}]` |
| GET | `/api/v1/files/{fileId}/content` | inspector+ | Original PDF, or the rendered PDF for DOCX/XML (`X-Page-Basis` header) |
| GET | `/api/v1/files/{fileId}/render?page=&dpi=&bbox=` | inspector+ | PNG crop (evidence thumbnails for protocol PDF/DOCX export) |
| GET | `/api/v1/processes/{processId}/extractions?param_code=&stage=&quality=` | inspector+ | Paged extracted_values |
| GET | `/api/v1/processes/{processId}/extraction-coverage` | inspector+ | `{params:[{code, PD:{status,n}, RD:{…}, ID:{…}}]}` |
| POST | `/api/v1/files/{fileId}/reextract` | admin, ml_engineer | `{reason, bypass_cache:true}` → 202 `{run_id}` (audited) |
| POST | `/api/v1/ml/ocr-evaluations` | ml_engineer | `{dataset_id, engines[]}` → 202 `{evaluation_id}` |
| GET | `/api/v1/ml/ocr-evaluations/{id}` | ml_engineer | `ocr_eval_report.json` |
| — | Python internal: `GET /health`, `GET /metrics`, `POST /internal/render`, `POST /internal/measure {file_sha256,page_no,p1,p2}`, `POST /internal/extract-sync` (tests only) | service | — |

Rendering for the UI is done client-side with PDF.js on `/content`. The server renders only crops and non-PDF sources, which keeps API p95 ≤ 200 ms (§11 п.10).

### 3.18 RabbitMQ
- **Exchanges:** `insp.cmd` (direct), `insp.evt` (topic), `insp.dlx` (dead-letter).
- **Queues:**
  - `ml.extract.file` (rk `extract.file`, DLX → `ml.extract.file.retry` with TTL 30 s/120 s, `x-death` count ≤ 2 then → `ml.extract.file.dlq`);
  - optional `ml.extract.pages` (chunk fan-out).
- **Command `extract.file` v1:**
```json
{"schema":"extract.file/1","job_id":"uuid","run_id":"uuid","process_id":"uuid","object_id":"uuid","file_id":"uuid",
 "sha256":"…64hex…","storage_uri":"s3://files/…","mime":"application/pdf","size_bytes":123,
 "doc_stage":"RD","discipline":"АР","document_code":"РД-2025-04.266-АР","revision":"1","approval_status":"FOR_CONSTRUCTION",
 "pipeline_version":"1.0.0+abc123","matrix_version":"1.1","bypass_cache":false,"priority":5,"attempt":0,
 "request_id":"…","user_id":"…","deadline_s":900}
```
- **Events** (`insp.evt`, rk `extraction.<type>`):
  - `extraction.started {run_id, file_id, pages_total}`
  - `extraction.progress {run_id, pages_done, pages_total, stage}` (throttled to 1/s)
  - `extraction.completed {run_id, file_id, sha256, cache_hit, pages_total, pages_ocr, values_count, params_touched:["M-002",…], metrics{…}, duration_ms}`
  - `extraction.failed {run_id, error_code:"OCR_TIMEOUT|RENDER_ERROR|INTERNAL", attempt, retryable, will_retry}`
  - `extraction.rejected {run_id, error_code:"CORRUPTED_PDF|ENCRYPTED_PDF|EMPTY_DOCUMENT|UNSUPPORTED_CONTENT|XML_MALFORMED|DOCX_INVALID", user_message_ru}`
  - `admin.alert {source:"ml-extractor", reason:"EXTRACTION_FAILED_AFTER_RETRIES", run_id}` (→ Module 11 e-mail/Telegram)
- **Idempotency:** `message_id = run_id`; a completed run for the same (sha256, P, matrix_version) short-circuits to CACHE_HIT.

### 3.19 State machine (extraction run)
```
QUEUED ──cache hit──▶ CACHE_HIT ──▶ COMPLETED
QUEUED ─▶ RUNNING[INVENTORY→TEXT→OCR→LAYOUT→TABLES→CV→NLP→PERSIST] ─▶ COMPLETED
RUNNING ─(corrupted/encrypted/empty/malformed)─▶ REJECTED        (event → B01 sets file rejected, UI: «повторите загрузку»)
RUNNING ─(timeout/transient)─▶ FAILED_RETRYABLE ─▶ QUEUED (attempt+1, ≤2) ─▶ … ─▶ FAILED_FINAL (DLQ, admin.alert)
```
Process-level status (owned by B01/Module 2): `PARSING` while any file of the process is QUEUED/RUNNING; comparison starts when all are terminal. REJECTED and FAILED_FINAL files produce `NOT_COMPARABLE` signals.

**Timeouts:** per page 60 s (OCR), per file `min(900 s, 30 s + 3 s·pages_vector + 6 s·pages_ocr)`.

### 3.20 UI touchpoints (implemented by the front-end block, contract from B02)
- **Document viewer (PDF.js)** with toggleable layers:
  - text-layer spans;
  - OCR lines, coloured by quality (green OK, amber LOW_QUALITY, grey-hatched ABSTAIN);
  - zones (seal/signature/handwriting);
  - tables (cell grid);
  - evidence boxes, and CV viewports with the inferred scale.
- Page badges: `ВЕКТОР` / `OCR` / `ГИБРИД` / `КОНТУРНЫЙ ТЕКСТ`.
- Per-file «Качество распознавания» panel (coverage, share of LOW_QUALITY/ABSTAIN, engine, DPI warnings).
- «Извлечённые значения» explorer: param → candidates → jump to bbox. Raw vs normalized value, method, confidence.
- ML-engineer page «Оценка OCR»: CER/WER/CA/EM/coverage with 95% CI, engine comparison, worst errors.
- «Отметить нечитаемую зону» tool (draws PREMARKED zone).

### 3.21 Libraries (versions verified on the dev box where marked ✓)
| Purpose | Library | Version | Licence | Note |
|---|---|---|---|---|
| PDF text/geometry/render | PyMuPDF | 1.26–1.28 (✓ 1.28.2) | **AGPL-3.0** / commercial | Alternative if AGPL is unacceptable: pypdfium2 (Apache/BSD) + pdfplumber (MIT) |
| OCR primary | rapidocr + onnxruntime + PP-OCRv5 models | ✓ 3.9.2 / ✓ 1.30.0 | Apache-2.0 | CPU, arm64/amd64 |
| OCR fallback/OSD | Tesseract + tessdata_best rus | ✓ 5.5.2 | Apache-2.0 | apt `tesseract-ocr-rus` |
| CV | opencv-python-headless | 4.10+ (✓ 5.0 in probe) | Apache-2.0 | LSD, morphology, HSV |
| Embeddings | multilingual-e5-small (ONNX) + tokenizers + onnxruntime | — | MIT / Apache | torch only for export |
| DOCX | python-docx | ✓ 1.2.0 | MIT | — |
| DOCX render | LibreOffice headless | 24.x (Debian pkg) | MPL-2.0 | Optional profile (+~350 MB) |
| XML | lxml / defusedxml | ✓ 6.x / 0.7 | BSD / PSF | XXE-safe |
| Levenshtein/WER | rapidfuzz / jiwer | ✓ 3.x / 3.x | MIT / Apache | — |
| Geometry | shapely | 2.x | BSD | Union IoU |
| Units (optional) | pint | 0.24 | BSD | Or own table |
| Service | aio-pika, redis-py, SQLAlchemy 2 + asyncpg, pydantic 2, FastAPI, structlog, prometheus-client | current | permissive | — |
| Front-end | pdfjs-dist | 4.x/5.x | Apache-2.0 | Overlay contract |

### 3.22 Optional LLM/VLM assist (EXT-54)
- **Interface:**
  - `AssistProvider.extract(crop_png, page_text_tokens, param_profile) -> [{value_raw, unit, bbox_norm, rationale}]`
  - `AssistProvider.describe_diff(crop_pd, crop_rd, context) -> text` (for Module 5 SUSPICION wording)

  Providers: `NoneProvider` (default), `OllamaProvider` (local), `RuCloudProvider` (GigaChat/YandexGPT; only if authorized).
- **Grounding rule.** An assist value is accepted only if its `value_raw` is found (after normalization) among page tokens (text layer/OCR) inside the returned bbox, expanded by 2 mm. Otherwise it is discarded. Assist output **never** sets statuses; it only adds `method=VLM_ASSIST` candidates with confidence capped at 0.6. Prompts and responses are audit-logged (hashes plus text in a secured store).
- **Use cases:** HIGH-priority params with `NOT_FOUND` after the deterministic routes; semantic «диссонанс» of room function names (Module 5).
- **Local option:** Qwen2.5-VL-7B / Qwen3-VL-8B class at Q4 (≈ 6 GB), in Ollama or llama.cpp with Metal on the M2 Max host. Expect roughly 10–30 s per crop, so it is feasible only for a handful of targeted crops, never for all pages. Docker on macOS has no GPU passthrough, so Ollama runs **natively on the host** and containers call `http://host.docker.internal:11434`. On a Linux server with NVIDIA, it runs as a container.
- **Cloud:** foreign APIs are **not recommended** for government documents (152-ФЗ localization, sensitive objects such as the MVD building UNDMS). Russian-hosted APIs are possible only with written approval.

### 3.23 Security, privacy, observability
- The ML container has no internet egress (models baked in). It runs as a non-root user with a read-only root filesystem and tmp cleanup after each job.
- Guards: max pages per file 1000 (configurable), max render megapixels per tile, DOCX zip-bomb limits, XML XXE/billion-laughs protection.
- **Personal data.** Title blocks contain engineers' names and signatures. Extracted person names are not logged; logs carry only ids and hashes (§12.6, 152-ФЗ).
- **Metrics (Prometheus):** `extract_runs_total{status}`, `extract_pages_total{page_class}`, `extract_page_seconds{stage}` (histogram), `ocr_pages_total{engine}`, `ocr_line_conf` (histogram), `extract_low_quality_ratio`, `extract_cache_hits_total`, `extract_failures_total{error_code}`, `nlp_param_seconds` (histogram), `cv_sheet_seconds` (histogram). Queue depth comes from the RabbitMQ exporter.
- **Logs:** JSON with `timestamp, level, service="ml-extractor", message, request_id, user_id, run_id, file_id, sha256`.

---

## 4. Interfaces with other blocks

| Counterpart | B02 consumes | B02 produces | Contract |
|---|---|---|---|
| B01 Module 1A (upload, registry, completeness) | `extract.file` command; file record (file_id, sha256, storage_uri, mime, object_id, doc_stage, discipline, document_code, revision, approval_status/date, predecessor) | `title_block` per page (шифр/стадия/лист/изм.), `sheet_label` ↔ page_no map, `STAGE_MISMATCH`/`CODE_MISMATCH` hints, readability (REJECTED/FAILED_FINAL/page-level unreadable), stamps and requisites (§5 notes 2–3), doc-type hints (explication, АОСР, исполнительная схема…) | §3.18 events; `document_pages.title_block` JSON |
| Module 2 (comparison/protocol) | matrix_version, active params | `extracted_values` (typed, located, versioned); `page_tables` (EXPLICATION/TEP/SPEC/DEVIATION rows) for set-diffs; `room_labels` per plan; `param_extraction_status`; `params_touched` (incremental); Checks skeleton; evidence geometry (token and region boxes) | Tables in §3.15; event `extraction.completed` |
| Module 3 (verification UI) / Module 7 (dashboard) | — | Page geometry and layers, `/content`, `/render` crops, OCR text + confidence, zones; raw vs normalized values; engine per value (supports reason codes OCR_ERROR, «ошибка привязки») | §3.17 |
| Module 4 (GOLD/retraining) | Rejection_Log reason statistics (OCR_ERROR, binding errors) | Component versions for model_version; OCR evaluation reports; error crops | `extraction_runs`, `ocr_eval_report.json` |
| Module 5 (hypotheses) | — | Span index + embeddings (semantic dissonance of room names PD vs RD, e.g. «Техническое» → «Склад ГСМ»); tables for logical rules (floors → lift) | Artifact store + `extracted_values` |
| Module 8 (normative base/Params admin) | `params` (regex_pattern, data_type, unit, min/max, is_active), `param_extraction_profiles` edits, matrix_version bumps | Profile validation (regex compiles, test samples) | Hot reload on `matrix.updated` event |
| Module 9 (audit) | — | Audit events for `reextract`, zone marking, profile edits | Audit_Log |
| Module 10 (weekly ML report) | — | OCR metrics, LOW_QUALITY/ABSTAIN shares, engine disagreement stats | Eval reports + run metrics |
| Module 11 (monitoring) | — | Prometheus metrics, JSON logs, `admin.alert` | §3.23 |
| Module 12 (negative scenarios) | — | Error codes and user messages: CORRUPTED_PDF, ENCRYPTED_PDF, EMPTY_DOCUMENT, XML_MALFORMED, DOCX_INVALID, OCR_TIMEOUT, LOW_DPI | §3.18 |
| Front-end block | — | Coordinate contract + fixtures + TS twin `normalizeBox()` | EXT-31 test |

**Evidence card contract (what B02 guarantees per value, the §9.2 step-4 card fields):**
`file_id, file_sha256, doc_stage, document_code, revision, approval_status, page_no, sheet_label, geometry{token_boxes, evidence_boxes, polygons}, value_raw, value_norm, unit, method, source_engine, confidence, quality_flag, anchor{text, geometry}, context_text, pipeline_version, matrix_version`.

---

## 5. Too complex / risky items and simplifications that still meet the letter of the ТЗ

| # | Item | Why it is hard | Simplification (still compliant) |
|---|---|---|---|
| R1 | Accurate extraction for **all 132 params** on arbitrary documents | Sources range from ТЭП tables to drawings, external systems (АИС ОСИГ, РНИС logs for M-098…M-101) and acts; no full document sets are available | Auto-drafted profiles for all 132 (literal compliance: «поиск по 132 параметрам»), **~35 hand-curated deep profiles**, per-param `param_extraction_status`; NOT_FOUND → Module 2 MISSING_EVIDENCE/NOT_APPLICABLE rather than guesses. The ООС external-system params are marked data-source-external (evidence = uploaded passports/logs only) |
| R2 | **Localization IoU ≥ 0.5 against expert region boxes** | Pilot GOLD boxes are region-level: a set of explication rows, a whole door area, a tolerance table, a room zone, and often 2 boxes per page. Tight token boxes give IoU ≪ 0.5 | Store both token and **evidence-region** boxes; region conventions per evidence type (table row span across label+value; room zone polygon; whole table for tolerance tables); IoU on the union of boxes; tune the conventions on the 27 pilot boxes |
| R3 | CV on drawings (widths, counts, contours) | PDF exports lose block identity; SHX text arrives as outlines; raster scans are noisy | Vector geometry + dimension texts + label sets; door widths from door marks/schedules; symbol counting and hatch semantics out of scope; raster CV only lines/scale/stamps |
| R4 | OCR 500 pages ≤ 10 min on CPU | 1.12 s/page leaves only ≈ 7% margin on dense pages | Text-layer-first, blank-page skip, INT8 rec, chunk fan-out to 2 replicas, ≥ 8 vCPU; the test corpus is realistic (mostly scans of acts, not A0 drawings) |
| R5 | Handwriting | Not recognizable reliably on CPU; excluded from the metric by the ТЗ | Detect + ABSTAIN + report share |
| R6 | Scanned borderless tables | Structure recognition models are heavy | ГОСТ forms are ruled, so the grid method works; borderless → column clustering with confidence 0.5 |
| R7 | XML variety | Schemas unknown, no samples | Generic XPath flattener + 1 adapter + rendered view |
| R8 | DOCX geometry | DOCX has no fixed pages | LibreOffice render + text-matched boxes; page basis recorded |
| R9 | Hidden-test OCR ≥ 0.95 | Unknown documents and normalization | Proxy set with CI, strict + relaxed reporting, confidence-calibrated abstention, lexicon post-correction; key fields from the text layer whenever it exists (exact) |
| R10 | Homoglyph ambiguity | OCR and CAD both mix scripts; "signs must not be removed" | Map, never delete; raw kept; strict and relaxed metrics; ask organizers (§7 D6) |
| R11 | Graphic configuration diffs (ventilation branches, warm floor) | Real CV/graph matching is research-grade | Room-zone label-set diff (text/OCR labels); explicit CANDIDATE only with a located label difference; warm-floor contours only via legend labels, otherwise NOT_COMPARABLE |

---

## 6. ТЗ contradictions / ambiguities for this block (with recommended interpretation)

| # | Issue | ТЗ ref | Recommended interpretation |
|---|---|---|---|
| C1 | «CV-анализ одного чертежа (DWG)», but inputs are PDF/DOCX/XML | §11 п.8 vs §9.1 Вход, errors table | "One drawing sheet in PDF"; DWG is rejected with the supported-format message (B01). The 30 s target is applied per PDF sheet |
| C2 | all-MiniLM-L6-v2 is English-only; «или её совместимые аналоги» | §9.1 п.2 | Use multilingual-e5-small (same SBERT family API, 384-dim like MiniLM); document the benchmark (§3.11.3) as justification |
| C3 | «масштабирование по размерной линейке»: scale bar or dimension lines? | §9.1 п.3 | Both: dimension-line voting (primary; Russian drawings rarely have scale bars except генпланы) + graphic scale bar if detected + declared «М 1:N»; report agreement |
| C4 | Which fields are case-insensitive? Are dash variants/homoglyphs "signs"? | §9.1 п.1 | Strict case for шифр/редакция/лист/помещение; case-insensitive only for free text; publish strict (headline) and relaxed (dash+homoglyph folding) metrics; ask organizers |
| C5 | «номер листа/страницы»: printed «Лист» or PDF page? | §9.1 п.1, §14.3 | Output both (`sheet_label`, `page_no` 1-based as in pilot «стр.»); EM evaluated on whichever the GT specifies |
| C6 | Format and origin of «заранее размеченные нечитаемые зоны» | §9.1 п.1 | Accept a JSON zone list (page_no + normalized geometry) via API/eval input; forced ABSTAIN inside; ask organizers for their format |
| C7 | Origin/orientation of normalized coordinates not stated | §9.1 п.4 | Top-left of the displayed (rotated) visible area, y down; proven by 27/27 pilot boxes |
| C8 | Module 1 output = "таблица Checks", while §10 Checks holds comparison results | §9.1 Выход vs §10 | Module 1 writes extracted_values + a Checks skeleton (completeness pre-fill, evidence_group_id); Module 2 completes |
| C9 | bbox/page for DOCX/XML values is undefined | §9.1 п.4 | Rendered-page locators + native locators (§3.9, §3.10) |
| C10 | Performance hardware not specified | §11 | State the reference hardware (≥ 8 vCPU, 16 GB for ml-extractor); publish the measurement protocol |
| C11 | Acceptance is at ≥ 300 dpi, but real ИД scans can be lower (pilot p14 = 200 dpi) | §9.1 п.1 | Process anyway, add a LOW_DPI flag; exclude from the ≥ 300-dpi metric bucket, report separately |
| C12 | Multi-box evidence (pilot «bbox [..];[..]») vs singular «bbox/polygon» | §9.1 п.4, МАТРИЦА «ПРИМЕРЫ» | Geometry = list of boxes/polygons; IoU on unions; ask organizers how IoU is computed for multi-box |
| C13 | Matrix codes M-001… vs ТЗ examples PZ-01/KR-55/AR-41 | §8.1–8.2 vs Приложение 1 | Canonical `M-xxx`, alias table with section prefixes (numbers align) accepted in API/profiles |
| C14 | Pilot is a composite (one page per original file, with expert markup baked in) | §14.1 | Pilot sanitizer; treat pilot pages as single-page documents with an external page offset for GOLD mapping |

---

## 7. Decisions needed from the user

| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | OCR engine | (a) PP-OCRv5 via RapidOCR + Tesseract fallback; (b) Tesseract only; (c) heavy transformer OCR (Surya etc.) | **(a)**: measured +6–20 pp over Tesseract, CPU and ARM friendly, Apache-2.0 |
| D2 | LLM/VLM usage | (a) none; (b) local only (Ollama on host), off by default; (c) Russian cloud (GigaChat/YandexGPT) with approval; (d) foreign cloud | **(b)**: deterministic by default; an optional grounded assist shows "AI" without 152-ФЗ risk; (d) not acceptable |
| D3 | Embedding model naming deviation from ТЗ | (a) multilingual-e5-small; (b) literally all-MiniLM-L6-v2 | **(a)**, with the benchmark table in the documentation; keep MiniLM switchable for a "letter-of-ТЗ" demo |
| D4 | PyMuPDF AGPL licence | (a) accept for the hackathon (publish source); (b) switch to pypdfium2 + pdfplumber | **(a)**, with a note on the licence path for production |
| D5 | Depth of parameter coverage | (a) ~35 deep + 97 generic; (b) all 132 shallow; (c) fewer, deeper | **(a)**: the ТЗ letter plus demo quality where the pilot and jury look |
| D6 | Ask organizers about OCR/EM normalization (dash, homoglyph, case), pre-marked zone format, multi-box IoU, reference hardware | yes/no | **Yes**: one e-mail, 5 questions (list in §8) |
| D7 | Human time for the OCR labeled set (≈ 3 h: verify OCR pre-fill of ~6–8k chars and ~300 key fields) | user / teammate / skip (synthetic only) | **User or teammate for 3 h**: a real-scan subset makes the CA/EM claims credible to the jury |
| D8 | DOCX rendering via LibreOffice inside the ML image (+~350 MB) | include / skip (no bbox for DOCX) | **Include** (optional compose profile) |
| D9 | Demo hardware for §11 figures | (a) Docker on the Mac (allocate ≥ 8 CPU/12 GB); (b) native Python workers on the Mac | **(a)** for the letter "в докер"; measure both, show the native numbers as the upper bound |

---

## 8. Data needed

| What | Why | Fallback if never received |
|---|---|---|
| Full ПД/РД/ИД sets for ≥ 2–3 objects (ideally the originals behind the pilot ids, e.g. ALT79B-000015, SOSH25-003562) | Real title blocks, ТЭП, specs, multi-page flows; realistic performance numbers; profile tuning | Synthetic sets: pilot pages + generated ТЭП/spec/АОСР PDFs and DOCX (templates from 344/пр forms), rotated/cropped variants; clearly labeled as synthetic |
| Printed scans ≥ 300 dpi with transcription (АОСР, journals, passports) | OCR acceptance proxy closer to the hidden test | DS-A synthetic degradations + our own print-and-scan of generated acts (office scanner at 300 dpi) + manual GT |
| XML samples and schema ids (ПЗ XML, electronic ИД, Технический план) | Adapters and XPath mappings | Generic flattener + one adapter from the public XSD with a synthetic instance |
| Format of pre-marked illegible zones and how LOW_QUALITY/ABSTAIN is scored | EXT-10/11 compliance in the hidden test | Our JSON format + API; document assumptions |
| Normalization rules for EM (dashes, homoglyphs, case) and multi-box IoU method | Avoid losing points on conventions | Report strict + relaxed |
| Reference hardware for §11 | Performance acceptance | Publish our hardware + protocol |
| Приложение № 2 (sample protocol) | Evidence-card fields and crop format (mostly Module 2/7) | Card per §9.2 п.4 field list |
| Authoritative `regex_pattern`, `data_type`, `min/max` for Params (missing in the xlsx) | §8.1 completeness | We author them in `param_extraction_profiles` and seed Params (flagged "draft, executor-authored") |
| Example of documents with SHX-outlined text and scanner OCR layers | Classifier thresholds | Pilot p9 + synthetic outlined-text PDFs |

Questions for the organizers (D6): (1) EM/CER normalization for dashes, homoglyphs and case; (2) format of pre-marked zones and scoring of LOW_QUALITY/ABSTAIN; (3) IoU for multi-box evidence; (4) reference hardware for §11; (5) whether XML inputs will appear and which schemas.

---

## 9. Jury demo scenario and acceptance tests

### 9.1 Demo (≈ 6 min for this block)
1. **Upload the pilot package.** Show the page-class badges: ВЕКТОР (p2), ГИБРИД (p3), КОНТУРНЫЙ ТЕКСТ (p9), OCR-скан (p14). Say: «текстовый слой там, где он есть; OCR — только там, где нужно».
2. **SOSH25 PD стр.49 vs RD стр.34.** The explication is parsed into rooms. Show added room 1.109 = 18,2 м² and totals 6234,1 → 6252,3, located by bbox. The GOLD overlay shows IoU ≥ 0.5.
3. **OKT103 scan (200 dpi).** The tolerance table is read (15 мм, ±12 мм, 20 мм vs +491/+552, +980/+537, +201/+349) with confidence badges. The handwriting zone is grey-hatched as ABSTAIN. The seal and signatures are detected («реквизиты: подпись ✓, печать ✓, дата ✓»). The LOW_DPI warning is visible.
4. **p9 RD КЖ02.1.** Text drawn as outlines is recovered: «Железобетонная плита В30 W6 F150 – 900 мм». Show the M-055 value B30 (rank 30) and M-058 900 мм. The «В ПРОИЗВОДСТВО РАБОТ» stamp is detected.
5. **Rotation proof.** Upload the synthetic fixtures (offset CropBox, Rotate 90/180/270). The overlays land pixel-exact in the viewer; the test table is shown.
6. **CV.** On ALT79B PD стр.19: inferred scale 1:100 (N votes), agreeing with «М 1:100». Measure between two axes and match the dimension text.
7. **Cache.** Re-upload the same file: a cache hit in under 1 s, with the log line shown.
8. **Quality report.** CER/WER/CA/EM/coverage with 95% CI; PP-OCRv5 vs Tesseract bars; NLP latency p95 ≈ 50 ms per parameter.

### 9.2 Acceptance tests (automated; CI gates)
| ID | Test | Pass criterion |
|---|---|---|
| T-COORD-01…07 | Synthetic fixtures (App. E): formula vs PyMuPDF vs rendered pixels | max abs error ≤ 0.005 |
| T-COORD-08 | Same fixtures in PDF.js + overlay (Playwright screenshot) | Box edges within 2 px at 1× |
| T-COORD-09 | OCR back-mapping on a scan rotated 90° by content and skewed 1.2° | polygon IoU vs GT ≥ 0.9 |
| T-LOC-01 | Pilot GOLD harness: extractor evidence for groups with extractable evidence (SOSH25, POL16, DOO25, ALT79B explications; OKT103 table; UNDMS layer note; LOS3A change log) | file+page exact and union IoU ≥ 0.5 on ≥ 0.95 of these groups |
| T-OCR-01 | DS-A + DS-B printed ≥ 300 dpi | CA ≥ 0.95 (strict), CI and n reported |
| T-OCR-02 | DS-C key fields | EM ≥ 0.90 |
| T-OCR-03 | DS-D zones (handwriting + premarked) | 100% LOW_QUALITY/ABSTAIN; share reported |
| T-OCR-04 | Report completeness | CER, WER, coverage, abstention, CI, n present |
| T-CLS-01 | Page classifier on 24 pilot pages | Classes as in App. B (p9 outlined, p14 scan, p3/p5/p22/p24 hybrid) |
| T-VIS-01 | Occlusion/sanitizer | No callout text and no white-ink-occluded text in extracted_values |
| T-TAB-01 | Explication parsing on p2, p17, p19 (split 3 tables), p24 | Room number/name/area F1 ≥ 0.95 vs text-layer GT |
| T-NORM-01 | ≥ 150 golden normalization cases (numbers, units, classes, homoglyphs) | 100% |
| T-NLP-01 | 40-query anchor test + profile tests for the 35 deep params | top-3 ≥ 0.9; value exact on the fixture set ≥ 0.9 |
| T-PERF-01 | 100-page scanned PDF (generated corpus) | ≤ 180 s (+30) on reference hardware |
| T-PERF-02 | 500-page scanned PDF | ≤ 600 s (+60) |
| T-PERF-03 | NLP per parameter | p95 ≤ 500 ms (target ≤ 100 ms) |
| T-PERF-04 | CV per A0 sheet (p19) | ≤ 30 s |
| T-CACHE-01 | Second parse of the same sha256 | No OCR invocation; ≤ 1 s; `cache_hit=true` |
| T-INC-01 | Matrix change → only NLP layer rerun | Duration ≤ 60 s for the pilot package |
| T-ERR-01 | Truncated/corrupted PDF; password-protected PDF | `extraction.rejected` with CORRUPTED_PDF / ENCRYPTED_PDF; Russian user message |
| T-ERR-02 | Forced timeout | 2 retries, then DLQ + `admin.alert` |
| T-DOCX-01 | Перечень DOCX | 2 tables parsed, 4 images OCR'd, rendered-page locators present |
| T-XML-01 | Synthetic ПЗ XML + malformed XML + XXE payload | Values with xpath locators; XML_MALFORMED; XXE blocked |

---

## 10. Work breakdown

Suggested implementation agents:
- **ml-extraction:** Python ingestion/OCR/service.
- **ml-nlp-cv:** tables, NLP, normalization, CV.
- **ml-eval:** evaluation harnesses and fixtures.
- **backend:** Node API.
- **frontend:** viewer.

| ID | Task | Size | Depends on | Owner |
|---|---|---|---|---|
| B02-T01 | ML service skeleton: aio-pika consumer, FastAPI health/metrics/internal, config, structlog JSON logs, Prometheus, multi-arch Dockerfile with tesseract-rus + baked ONNX models | M | infra compose (RabbitMQ/Redis/Postgres/MinIO) | ml-extraction |
| B02-T02 | Coordinate library (Python) + TS twin + fixture generator (7+7 cases) + tests | S | — | ml-eval |
| B02-T03 | PDF intake and page inventory: open/repair/encrypted/corrupted guards, geometry capture, page classifier, visibility-aware text layer (occlusion, invisible text), pilot sanitizer | M | T01, T02 | ml-extraction |
| B02-T04 | OCR subsystem: RapidOCR PP-OCRv5 pool, native-image extraction, tiling, OSD/cls/deskew with back-mapping, hybrid merge, post-correction, quality flags, Tesseract fallback, §11 tuning | L | T03 | ml-extraction |
| B02-T05 | Quality zones and requisites: blue-ink/shape detection, premarked zones, coverage metrics, stamp detection («В производство работ», «Выполнено согласно проекту»), date/reg-number checks | M | T04 | ml-extraction |
| B02-T06 | Title-block parser (ГОСТ Р 21.101 forms 3/5/6 + ИС) with cell grid, code line-joining, stage/revision, sheet↔page map | M | T03 (T04 for scans) | ml-nlp-cv |
| B02-T07 | Tables: vector detection + header classifier + side-by-side splitter + FP filter; raster ruled grid + cell OCR; DOCX tables; typed parsers (EXPLICATION, TEP, SPEC_21110, OPENING, FINISH, REBAR, SHEET_LIST, CHANGE_LOG, DEVIATION, CALENDAR, COORDINATES) | L | T03, T04, T08 | ml-nlp-cv |
| B02-T08 | Normalization library (numbers, units, class systems with ranks, homoglyphs) + ≥ 150 golden tests | M | — | ml-nlp-cv |
| B02-T09 | Parameter extraction engine: profile schema/loader from Params (hot reload), auto-drafted 132 profiles + ~35 deep profiles, e5-small ONNX embedder + span index, routes (TABLE/REGEX/TOKEN/CV/PRESENCE), scoring, evidence region boxes, `param_extraction_status`, Checks skeleton | L | T06, T07, T08, Params table (Module 8 block) | ml-nlp-cv |
| B02-T10 | CV module: vector segments, dimension pairing, per-viewport scale voting + declared cross-check, distance API, room-zone label sets; raster LSD + OCR-dimension scale (flagged) | M | T03, T04 | ml-nlp-cv |
| B02-T11 | Redis cache + artifact store (keys, locks, versioning, invalidation, encryption) | S | T01 | ml-extraction |
| B02-T12 | DOCX and XML adapters: python-docx (tables, footers, images→OCR), LibreOffice render + locator mapping, XML safe parse, generic flattener + 1 adapter + rendered view, XSD hook | M | T03, T07 | ml-extraction |
| B02-T13 | OCR evaluation harness: DS-A builder with degradations, DS-B/C/D labeling format and pre-fill, metrics (CA/CER/WER/EM/coverage/abstention, bootstrap CI), report JSON | M | T04, T05, T06 | ml-eval |
| B02-T14 | Localization harness: pilot GOLD from red rectangles, union IoU, evidence-region convention tuning | S | T02, T09 | ml-eval |
| B02-T15 | Node API endpoints (§3.17) + OpenAPI schemas + extraction event consumer → process status | M | T01, backend skeleton | backend |
| B02-T16 | Front-end overlay contract: PDF.js viewport mapping, layers, Playwright pixel test on fixtures | S | T02, frontend skeleton | frontend |
| B02-T17 | Optional VLM assist interface + Ollama provider (off by default) + grounding validator + audit logging | S | T09 | ml-nlp-cv |
| B02-T18 | Performance suite: generate 100/500-page scan corpora, measure §11 п.2/3/7/8/9, tune workers/INT8/fan-out | S | T04, T09, T10 | ml-extraction |

**Critical path:** T01 → T03 → T04 → T07 → T09 → T14/T18, about 9–11 agent-days serial. The other tasks run in parallel. T02 and T08 can start immediately with no dependencies.

---

## Appendix A — Probe P2 detail (character accuracy on horizontal words / word exact match)

| Region (pilot page, content) | Tess fast psm11 | Tess best psm11 | Tess fast psm3 | PP-OCRv5 eslav | PP-OCRv5 cyrillic |
|---|---|---|---|---|---|
| p13 ведомость изменений (A4, DOCX-origin font), 165 words | 0.897 / 0.776 | 0.904 / 0.788 | 0.919 / 0.861 | 0.973 / 0.927 | **0.980 / 0.945** |
| p19 экспликация (A0, ISOCPEUR italic), 357 words | 0.890 / 0.641 | 0.852 / 0.552 | 0.856 / 0.611 | 0.913 / 0.683 | **0.927 / 0.734** (0.951/0.793 with det resize 1500) |
| p2 spec + title block (A0), 55 words | 0.774 / 0.527 | 0.791 / 0.545 | 0.747 / 0.509 | 0.962 / 0.836 | **0.974 / 0.873** |
| p16 plan region (dense labels), 289 words | 0.555 / 0.370 | 0.563 / 0.367 | 0.390 / 0.246 | 0.787 / 0.453 | **0.801 / 0.512** |
| p22 plan over raster tiles, 368 words | 0.821 / 0.660 | 0.818 / 0.622 | 0.658 / 0.476 | 0.862 / 0.690 | **0.876 / 0.720** |

Time per region: PP-OCRv5 0.9–3.2 s with all threads; Tesseract fast 0.8–3.5 s single-thread.

**Real scan p14 (no GT, qualitative):**
- Tolerance-table numbers read at 0.95–1.00.
- Table headers at 0.5–0.8.
- Handwriting at 0.30–0.46.
- Title block: document code `23.009-Р-П-KЖ0.2` (Latin K homoglyph), address line correct at 0.88–0.98.

Pitfall found during the probe: a custom `TESSDATA_PREFIX` without the `configs/` folder silently disables `tsv` output. A wrong prefix silently falls back to English-only (0.08 accuracy). The Docker image must include `configs/` and must fail fast if `rus` is not listed.

## Appendix B — Pilot page inventory (24-page «Комплект предметной разметки»)

| Pilot page | Source (ПРИМЕРЫ РАЗМЕТКИ) | Size (mm) | Class | Notes |
|---|---|---|---|---|
| p1 | Cover | 297×210 | VECTOR | White-ink redaction strip at the bottom |
| p2 | ALT79B PD стр.19 | 1189×841 | VECTOR | «Спецификация помещений» table; «М1:100» + «1:50» |
| p3 | ALT79B RD стр.4 | 1189×842 | HYBRID | 150-dpi full-page raster + 409-word text layer |
| p4 | ALT79B PD стр.20 | 1189×841 | VECTOR | — |
| p5 | ALT79B RD стр.5 | 1189×842 | HYBRID | 150-dpi raster |
| p6 | UNDMS PD стр.16 | 420×297 | VECTOR | ArchiCAD (GSPublisher) |
| p7 | UNDMS RD стр.10 | 420×297 | VECTOR | Change record «1 Зам. 12.05.2025» |
| p8 | UNDMS RD стр.4 | 210×297 | VECTOR | — |
| p9 | IZM12 RD стр.4 (КЖ02.1) | 1189×841 | **VECTOR_OUTLINED_TEXT** | 27,421 paths, 19 text-layer words (callout only); «В ПРОИЗВОДСТВО РАБОТ» stamp |
| p10 | IZM12 ID стр.15 | 210×297 | VECTOR | Stage «ИС» |
| p11 | LOS3A PD стр.41 | 841×594 | VECTOR | — |
| p12 | LOS3A RD стр.15 | 841×594 | VECTOR | — |
| p13 | LOS3A RD стр.8 | 210×297 | VECTOR | «Ведомость изменений» table |
| p14 | OKT103 ID стр.1 | 299×420 | **RASTER_SCAN** 200 dpi | Handwriting, seal, signatures; CONFIRMED_VIOLATION |
| p15 | POL16 PD стр.62 | 1188×420 | VECTOR | Native red CAD lines (width 0.2) |
| p16 | POL16 RD стр.21 | 594×420 | VECTOR | — |
| p17 | DOO25 PD стр.27 | 841×594 | VECTOR | Explication (text-layer glitch «5511 ,65») |
| p18 | DOO25 RD стр.12 | 841×594 | VECTOR | — |
| p19 | SOSH25 PD стр.49 | 1189×420 | VECTOR | 3 side-by-side explications; scale 1:200 inferred |
| p20 | SOSH25 RD стр.34 | 1189×841 | VECTOR | — |
| p21 | POL17 PD стр.26 | 901×420 | VECTOR | NEGATIVE_VERIFIED group; no red markup |
| p22 | POL17 RD стр.7 | 901×420 | HYBRID | 55 raster tiles + text layer |
| p23 | POL17 PD стр.27 | 901×420 | VECTOR | — |
| p24 | POL17 RD стр.8 | 901×420 | HYBRID | 55 raster tiles |

All pages: `Rotate=0`, `CropBox=MediaBox=[0 0 W H]`. The only annotations are white Ink strokes (widths 9.75/18) over title-block cells, with the text still present underneath. Expert markup is red vector content: width 4.0 = evidence box (27 boxes, IoU ≥ 0.997 vs GOLD), 3.0 = callout box, 2.5 = leader line. The explained 6-page markup (ReportLab) embeds raster crops of the ventilation sheets. OCR on them recovered branch labels `B2.4…B2.10`, `П2/BE`.

## Appendix C — Sample deep profiles (abridged)
```yaml
- code: M-001   # PZ-01 Площадь застройки, м²
  routes: [TABLE, REGEX]; table_types: [TEP]; doc_scope: {stages:[PD,RD,ID], disciplines:[ПЗ,ПЗУ,ГП,ПП]}
  anchors: ["площадь застройки"]; value_parser: area_m2; aggregation: single; plausibility: {min: 1, max: 1e6}
- code: M-002   # Общая площадь здания
  routes: [TABLE]; table_types: [TEP, EXPLICATION]; anchors: ["общая площадь здания","общая площадь"]
  aggregation: single_or_explication_total   # explication «Итого»/«Всего» rows accepted as corroboration
- code: M-041   # AR-41 Ширина эвакуационных выходов (дверей), м
  routes: [TABLE, TOKEN_GRAMMAR, CV]; table_types: [OPENING_SCHEDULE, SPEC_21110]
  value_parser: door_width_from_mark_or_size; aggregation: per_element_min; anchors: ["эвакуационный выход","дверь","ДН","ДГ"]
- code: M-055   # KR-55 (see §3.11.1)
- code: M-058   # Толщина фундаментной плиты, мм
  routes: [REGEX, TABLE, CV]; anchors: ["фундаментная плита","ростверк"]
  regex_pattern: "(?i)плит\\w*[^\\n]{0,60}?[-–—]\\s?(?P<value>\\d{3,4})\\s?(?P<unit>мм)"   # «Железобетонная плита В30 W6 F150 – 900 мм»
- code: M-103   # Пределы огнестойкости дверей (EI), мин
  routes: [TABLE, TOKEN_GRAMMAR]; value_parser: fire_rating; anchors: ["противопожарная дверь","EI"]
- code: M-107   # Класс пожарной опасности отделочных материалов (КМ)
  routes: [TABLE, TOKEN_GRAMMAR]; table_types: [FINISH_SCHEDULE]; value_parser: km_class (rank inverted)
```

## Appendix D — Normalization golden examples (excerpt)
| Raw | Normalized |
|---|---|
| `6 234,1 м²` | `{value: 6234.1, unit: m2}` |
| `8.99 м²` | `{value: 8.99, unit: m2}` |
| `В25` / `B25` / `B 25` | `{class: B25, rank: 25}` |
| `А500С` / `A500C` / `А-III` | `{class: A500C, rank: 500, weldable: true}` / legacy `A-III → A400` |
| `EI-60` / `EI 60` / `EI60` | `{rating: EI60, minutes: 60, letters: EI}` |
| `КМ1` / `KM1` | `{class: КМ1, rank: 1, better_is_lower: true}` |
| `±0,000=+123,350` | `{zero_abs_elevation_m: 123.350}` (M-009) |
| `+491` (DEVIATION_TABLE, mm column) | `{deviation_mm: 491}` |
| `ВВГнг(А)-FRLS 5х10` | `{mark: ВВГнг(А)-FRLS, flags: [FR, LS], cores: 5, section_mm2: 10}` |
| `Ду25` / `DN25` / `Ø25` | `{dn_mm: 25}` |
| `500х300` (duct) | `{a_mm: 500, b_mm: 300, area_mm2: 150000}` |
| `KP-4.1` (OCR, Cyrillic context) | `КР-4.1` (raw kept) |
| `1.109` (room column) | string `1.109` (not a number) |

## Appendix E — Coordinate test vectors
See the table in §3.14. The generator script (probe P5) builds each fixture from a raw content stream (`q 0 0 0 rg X Y W H re f Q`) with explicit `/MediaBox`, `/CropBox`, `/Rotate`. It compares (1) the canonical formula, (2) PyMuPDF `rect * page.rotation_matrix / page.rect`, and (3) the bbox of dark pixels in `get_pixmap()` output. All 7 cases passed with error < 0.005.
