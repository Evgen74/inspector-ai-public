# inspector_tables

Owner: **AG-02C** Tables, ИД & NLP (see CLAUDE.md). Scope: 97 §2.13 F7–F8, 96 R-08/R-09/R-13 — typed
header-anchored tables, ИД binder typing, PD element–room assertions, absence proof, value extraction.

## Command

```bash
cd services/ml
uv run --locked inspector-batch --run-id <run> tables --object OBJ-TYUMENSKAYA-5-GOLD-SEED \
    [--file F0201 …] [--table-type EXPLICATION …] [--workers 3] [--tokens-from <recognize run> …] \
    [--no-cache-tokens] [--pages 1-20]
```

Writes, validated against the contracts before writing:

* `tables/<file_id>.json` — TableArtifacts (`schemas/table_artifacts.schema.json`), one per PDF (empty
  `tables` when none), `ext.pages_read/pages_unread`, per-stage `timings_ms`;
* `values/<object_id>.jsonl` — ExtractedValue (`schemas/extracted_value.schema.json`), one fact per line.

Words come from PageTokens (the run's `tokens/<file_id>/`, then `--tokens-from` runs, then the token cache
`.cache/tokens/<latest docproc version>/…`), else from the PDF text layer. Scanned pages without tokens are
counted as unread (`OCR_PARTIAL` / `NO_TEXT_LAYER` warnings): tables need text. Stage: manifest PD/RD/ID;
RD_ID_MIXED/UNKNOWN resolved per file with AG-01's rules (`inspector_registry.stages`), never guessed.

## Modules

| Module | What |
|---|---|
| `pagesource` | PageData (words in displayed points, content-rotation to upright), vector rulings (`get_cdrawings`, fast path), raster rulings for scans/embedded rasters (OpenCV), PageTokens loading with OCR↔text-layer and OCR↔OCR dedupe |
| `grid` | Header-anchored engine: header band from the anchor's cell, column borders crossing it (continuing past a merged row), table growth by canonical column order (splits side-by-side tables sharing a border), key inference from body content for outlined headers, row separators on the key column, merged-row detection, outer-border cutoff, aligned-row fallback, continuation blocks/pages |
| `explication` | EXPLICATION: row kinds (SECTION_HEADER, DATA, SUBZONE «в том числе», TOTAL, SUBTOTAL incl. stacked «Σ + title» bands), side-by-side continuation, Σ checks with SUBZONE_DOUBLE_COUNT, grand total vs Σ group totals / Σ rooms |
| `tep` | TEP: «№ п/п» hierarchy (SUBZONE children, unnumbered «Корпус N»), ГПЗУ vs ПД columns, number re-join, param mapping (PZ-001/002/004–008/010/012/019/020, SPZU-025…028), Σ of children at printed precision, UNIT_CONSISTENT against the catalog unit |
| `spec21110` | SPEC_21110: multi-row items (first-line or last-line quantity), centred section titles, column-number row skipped; pages joined by the batch |
| `changelog` | CHANGE_LOG: «Разрешение на внесение изменений» (permit №, document code) and the ГОСТ registration form; title blocks rejected |
| `deviation` | DEVIATION / ИГС: design / actual / deviation / tolerance, tolerance verdict per row (values) |
| `registry` | ID_REGISTRY «Реестр приложений»: sections as blocks, continuation pages, «№ … от …» split |
| `aosr` | AOSR form п.1–7, dates, cited documents with «изм. N» (RT-10) |
| `airx` | PD «Таблица воздухообменов» (raster inset, OCR): per-room supply / exhaust / compensation / М.О. systems |
| `assertions` | PD element–room assertions — TEXT (sentence + «пом. N, N»), LABEL (leader lines followed to the room cell), SPEC, TABLE; element families and anchors from AG-03's change map |
| `absence` | Absence proof over a document set: every page read (tokens, or a real text page) or the answer is «not provable» |
| `binder` | ИД page kind from the header band (AG-03 doc_kind codes + ID_REGISTRY, STAMP_PAGE, UNREAD) and segments |
| `artifacts`, `values` | Contract output (TableArtifacts, ExtractedValue) |
| `evaluate` | Row-exact accuracy vs hand GT; `python -m inspector_tables.evaluate` |

## Measured (M1, 2026-09-28)

* EXPLICATION rows exact on 3 hand-GT pages (224 rows; `tests/data/gt_explication_*.json`, visual transcriptions):
  text layer **223/224 = 0.996**, with PageTokens **224/224 = 1.000** (target ≥ 0.98). Reproduce:
  `uv run --locked python -m inspector_tables.evaluate`.
* F0201 p18: the two «в том числе» double counts (30,4 m² in «Группа начальных классов», 65,8 m² in the
  «Вестибюльная группа»); F0101 p9 ТЭП: «Строительный объем» printed in «кв. м.» and Σ 69 186,0 ≠ 69 201,0.
* G-TR-002 PD evidence: WARM_FLOOR in rooms 267/270/271/272 from F0171 p11 (text), p99 (two leaders), p136 (spec,
  ×2); RD F0202 proven absent over 36/36 pages with OCR (not provable without). G-TR-003/004: the PD air-exchange
  table gives 140 → В2.7–2.9, 142 → В2.4–2.6, 147 → В2.10, 198 → В2.2/2.3, 314 → В3.1/3.2.

* ИД binder page kinds on 46 visually labelled Новослободская pages (`tests/data/gt_binder_kinds_novoslobodskaya.json`):
  0.891 after segmentation (0.804 page-level); every miss is an abstention (UNREAD scan without OCR, or UNKNOWN),
  never a wrong kind. Reproduce: `uv run --locked python -m inspector_tables.evaluate binder`.
* Full train runs (3 workers): Тюменская 57 PDFs → 135 tables, 15 930 values in 110.7 s; Новослободская 145 PDFs →
  315 tables (99 АОСР with 9/9 fields, 43 registries), 13 966 values in 50.5 s; 0 page failures.

## Tests

`tests/` — fast synthetic tables (PyMuPDF-drawn, no organizer data) and `@pytest.mark.data` real TRAIN pages
(skip without data; token-based checks skip when the token cache lacks the pages). ~11 s on an idle host.
