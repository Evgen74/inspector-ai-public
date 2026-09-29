# inspector_layout

Owner: **AG-02B** Drawings & Layout (see CLAUDE.md). Two halves share this package:
- **title blocks, QR, sheet ↔ page map, code gate** (AG-02B-1): `codes.py`, `titleblock.py`, `words.py`, `qr.py`,
  `sheetmap.py`, `pagescan.py`, `pipeline.py`, `batch.py`, `bench.py`, `testing.py`;
- **rooms, tags, CAD layers, revision clouds** (AG-02B-2): `rooms/`, `cad/` (see `rooms/__init__.py`).

Scope (97 §2.13 F6, 96 R-06/R-07/R-10/R-15): code corrector with the registry prior (codes EM ≥ 0.95), title block
(шифр, лист, листов, стадия, Изм. rows) + QR, the sheet↔page map with smoothing and duplicate detection
(sheet = stamp ≥ 0.95), CAD layer (OCG) toolkit, revision clouds, the room index and the tag grammar.

## Batch command

```bash
cd services/ml
uv run --locked inspector-batch --run-id m1-layout layout --object OBJ-TYUMENSKAYA-5-GOLD-SEED
uv run --locked inspector-batch layout --object OBJ-TYUMENSKAYA-5-GOLD-SEED --file F0201 --pages 14-48
```

Options: `--file` (repeat), `--pages «14-48,120»`, `--tokens-run RUN_ID` (PageTokens of a recognition run; the
current run's `tokens/` is used when present), `--inventory-run RUN_ID` (AG-01's per-file stage for RD_ID_MIXED
rows; the current run's inventory when present), `--workers 3`, `--threads 2`, `--providers cpu|coreml|auto`,
`--ocr-dpi 300`, `--no-ocr`, `--ocr-scans`, `--no-qr-render`, `--no-sections` (title blocks, QR and the sheet map
only, without the AG-02B-2 room/CAD provider). Exit codes: 0, 4 (a document still failed its schema after
salvage), 6 (no PDF selected). The hidden object needs the CLI's `--hidden-run` (policy «confirm»).

Output: one `LayoutArtifacts` per PDF at `RunLayout(run_dir).path("LAYOUT", file_id=…)` →
`runs/<run_id>/layout/<file_id>.json` (schema `layout_artifacts`, validated before writing), plus
`runs/<run_id>/layout_summary.json` (per-file counts and wall time; not a contract artifact). The CLI rebuilds
`artifacts.json` afterwards. A list item the schema rejects (e.g. an unforeseen QR payload) is dropped rather than
the whole file: warning `CONTRACT_VALIDATION_FAILED`, details in `ext.dropped_invalid`. Per-file
`timings_ms`: `scan_wall_ms`, `words_ms`, `grid_ms`, `ocr_ms`, `cell_ms`, `qr_ms` (+ `sections_ms`);
`ext.title_block`: pages scanned, stamps found, forms, word sources, OCR pages, QR-hidden OCR pages, cells re-read,
code basis, stamp stages and stage conflicts (META_CONFLICT).

## How a page is read (`pagescan.py`)

1. Words of the stamp window (bottom-right 215 × 85 mm of the displayed page) from the run's PageTokens when
   present (path through `RunLayout("PAGE_TOKENS")`), else the PDF text layer. A garbled layer (constant glyph
   shift, «ȺɇɈ/150321» for «АНО/150321», F0153) is repaired with AG-02A's `repair_words`; when a font is left
   unrepaired although the page confirmed one offset, that offset is applied to the words still garbled (kept
   only if they come out clean). Words still garbled are kept at confidence 0.5 for label matching («Л̛ст») and
   never give a value (шифр, title, organisation).
2. `titleblock.read_title_block`: anchor labels («Изм.|Кол.уч.|Лист|№ док.|Подп.|Дата», «Стадия|Лист|Листов», the
   lone «Лист» of form 6; OCR spellings «Луст», «Лисm», «№gok.», split cells «Лис|т»), a least-squares fit of the
   ГОСТ Р 21.101 change-table grid (offset and scale). «Стадия» must be the row right under the change-table
   header (header + 5 mm; «на стадии строительства» in the notes is not a label). Values: under their own label
   (labels are centred in their cells; a cell reaches at most half-way to the next label, because non-standard
   stamps compress the right block, Новослободская F0104), a «Лист» label lost to OCR is placed between «Стадия»
   and «Листов» by the ГОСТ ratio; Изм. rows above the header (kind «3ам.» → «Зам.» for OCR); шифр = the tallest
   code-shaped line inside the stamp (words joined by geometry: OCR «АНО» + «/150321/1-П-ИОС» + «5.1.4»; text-layer
   runs overlapping by a fraction of a glyph; a leading «Шифр:» dropped; drawing text above the stamp top is
   ignored); graph 2/4/9 → object, sheet title, organisation (OCR quotes balanced: «ООО ТСП»» → «ООО «ТСП»»).
   Forms 3, 5 and 6; page fields printed «- 4 -» read as 4.
3. OCR fallback when no key field was read, the stamp core (right 190 × bottom 60 mm) holds < 20 text-layer
   characters and a ruled stamp grid is drawn there: AG-02A's `PageRecognizer.ocr_region` on 200 × 72 mm at
   300 dpi, v6-small detector only (`medium_mode="off"`: −55 % time, same fields). The Exon QR image is pasted
   over the sheet title of the Тюменская RD stamps («План по|двала»): square images of the window are removed from
   a one-page in-memory copy before the OCR (the source page keeps its QR for decoding). Raster scans are skipped
   unless `--ocr-scans`.
4. OCR fallback on cell crops (`PageScanner.reread_cells`, after any OCR-sourced read): a «Лист»/«Стадия» value
   whose label was read but whose value was not is re-read on its cell crop at 400 dpi (F0204 p15, F0164); the
   sheet title under a QR image is re-read on the QR-free copy when the words came from a recognition run's
   tokens (27 of 50 F0201/F0202 titles restored on `m1-ag02b2-tokens`, ≈ 0.6 s a page).
5. QR (`qr.py`): square image xrefs from the page resources (`get_images`, ≈ 1 ms; `get_image_info(xrefs=True)`
   hashes every image, 1.3 s on a site plan), a two-tone test before decoding (raster tiles are skipped), OpenCV
   `QRCodeDetector` then `QRCodeDetectorAruco` at native resolution, placement from `get_image_rects` for decoded
   codes only. Pages ≥ A3 without one fall back to a 150 dpi grayscale render of the right edge and the stamp
   window from one display list; only solid QR-like squares (`square_blobs`) go to the detector (full detector if
   a square does not decode). Same result as the full detector on 95/95 Новослободская vector-QR pages.
   Payloads: Exon `…/document-status/<uuid>/<ver>/wd/<page>` (doc key + page; keys seen with page 0 are 0-based
   and reported + 1, Новослободская F0136), Signal `qr.sgnl.pro/d/<key>`, others kept raw. `link_targets`
   resolves an ИД extract's QR to the RD page carrying the same (key, page) in the key's home file (F0198 → F0202
   p17). No new dependency (opencv 5.0 is pinned; zxing-cpp is not needed on the train data).

## Code gate (`codes.py`)

`CodeRegistry.from_manifest_rows(rows, object_id)` collects code segments and letter heads from the object's own
file and folder names (never a fixed list). `resolve(raw, stage=…)` = AG-02A's corrector (`codefix.fix_code`) →
per-segment confusion readings accepted only into registry segments («Р3» → «ПЗ») → stage-letter fold of a
one-letter П/Р segment to the file stage → one-substitution patch against a registry code. `fold_stage` folds
the «Стадия» cell («P» → «Р», «PД» → «РД»). `gate_text` applies the gate to every code-shaped token of a text.
`looks_like_code` wants ≥ 2 separators, digits and capital letters («4,01л/с.», «п.3.6.4» are not codes). A text
layer is what the document prints: text-layer codes are never corrected.

## Sheet ↔ page map (`sheetmap.py`)

Per document code group: readings supported by a linear neighbour, OCR misreads or gaps between supported
pages smoothed (`SEQUENCE_SMOOTHED`), stamps without a readable sheet filled from the Exon QR page offset
(`QR`), a one-sheet document («Лист» blank, «Листов 1», ГОСТ Р 21.101) mapped to sheet 1, duplicates flagged with
`duplicate_of_page` (F0201 p29/p30 repeat 14/15), never dropped. A new document starts inside one шифр at a first
sheet with «Листов» after numbered sheets (F0204 specification after the drawings, F0190 drawings after the text
part) or at a restart to «1» (text layer, or OCR «1» followed by «2»; Новослободская F0104). Text-layer readings
are exact and never overridden. The map keeps the **printed** stamp number: the organizers' gold numbers F0201
sheets one lower than the stamps (p17: gold 3, stamp 4); the «Ведомость рабочих чертежей» on F0201 p14 agrees
with the stamps (sheet 4 = «План подвала (вентиляция)»), so the offset is the organizers' own. Localisation
always uses the PDF page; `document_sheet_number` is an optional, unscored extra (93 §2).

## Room/CAD provider

After the title-block half, `pipeline.run_section_provider` calls
`inspector_layout.rooms.fileproc.layout_sections(path=, file_id=, object_id=, pages=, tokens_dir=, title_blocks=,
sheet_page_map=)` when it exists and merges `rooms`, `tags`, `cad_layers`, `revision_clouds`, `warnings`,
`timings_ms`, `ext`. A provider failure is logged and never costs the title blocks.

## Benchmarks and gates

```bash
uv run --locked python -m inspector_layout.bench --suite codes    # 17 benchmark stamps, ≈ 85 s
uv run --locked python -m inspector_layout.bench --suite sheets   # 182 F0201/F0202 drawing pages, ≈ 100 s
uv run --locked pytest -m slow packages/inspector_layout/tests/test_layout_data.py
```

- Codes: the 11 vector codes of the group-A regions (AG-02A metric) + the 6 outlined stamps (A04, A05, A06, D01,
  D02, D04) through the full reader. Measured 2026-09-28: **17/17 = 1.000** (vector: raw 0.091 → corrector 0.909
  → gate 1.000; outlined: codes 6/6, key fields стадия/лист/листов 19/19, Изм. rows exact on A04 and A06).
- Sheets: `tests/data/sheet_stamp_gt.json` — the printed «Лист» of every drawing page of F0201 (p14–172) and
  F0202 (p14–36), verified visually on rendered stamps (31 pages re-checked against the ink on 2026-09-28, all
  correct), with the two duplicate pairs. Measured: **sheet = stamp 182/182 = 1.000**, readings before smoothing
  1.000, duplicates 2/2.

## Tests

`tests/` — fast by default (synthetic stamps from `inspector_layout.testing.make_stamp_pdf`, a synthetic OCR
check when the models are present), `@pytest.mark.data` for organizer data (skipped without it: text-layer stamps,
QR link F0198 → F0202 p17, garbled F0153, F0148 nomenclature, one-sheet F0161), `@pytest.mark.slow` for the two
gates. CPU etiquette: at most 3 workers while other agents share the host.

## Rooms, tags, CAD layers and revision clouds (AG-02B-2: `rooms/`, `cad/`)

Per drawing page (`rooms/page.py`; pages larger than 1.5 × A4 or referencing CAD layers):

1. **Tokens**: the run's PageTokens (text layer + OCR of outlined CAD text), else the text layer (`OCR_PARTIAL`).
   OCR tokens get their CAD layer from the small vector paths inside their box (`cad/layers.attribute_tokens`),
   text-layer tokens from their span (`get_texttrace`). A page with no room-like token, no vent/heating wording
   and no revision/duct/heating layer skips the vector pass (`ext.rooms_stage.pages[].skipped = NO_ANCHORS`:
   text-less sheets such as F0160 p63 with 867 k paths took 30 s for nothing).
2. **One pass over the vector paths** (`cad/geometry.index_drawings`): label circles, cubic arcs, segments of
   label/leader layers, revision-layer paths.
3. **Room labels** (`rooms/labels.py`): a number in a circle of the sheet's label radius (plans), the first
   word(s) of a caption «142 Астрономии…» with its continuation lines («140 Физического» / «эксперимента»),
   «267, 270» + a name under it (left-, right- or centre-aligned: «012» over «Венткамера»), the number column of
   «Экспликация помещений». An explication needs room rows: captioned — half of the rows with an area or a
   room-type name; uncaptioned — 80 % areas and half room names (the «Характеристика систем» tables list served
   rooms next to fan types and are not explications; sub-zones «331а -зона …» are rooms). Tokens stay exact
   («012», «012.1», «331б»); numbers on duct/heating layers (Ø, flows, node numbers), levels and bare dimensions
   on circled sheets are never rooms.
4. **Room zones** (`rooms/zones.py`): the page rendered with only wall/door/window layers, seeded marker
   watershed from every label (geodesic Voronoi through door gaps); label Voronoi (confidence 0.4) when a sheet
   has no wall layers. `RoomEntry.zone` = the polygon.
5. **Marks** (`rooms/grammar.py`, `rooms/tags.py`): vent systems and branch lists, air terminals, «М.О.»,
   equipment, radiators, risers, pipelines «Т11»/«Т21» anywhere in a line (side by side, glued «T11T21», with
   «=+85 °С»), warm floors, flows, sizes, levels. **One TagInstance per printed mark** (contract): «В2.7,8,9» is
   one instance, `tag` = the print, `tag_norm` = «В2.7, В2.8, В2.9» (`grammar.mark_elements` splits it; consumers
   should classify `tag_norm`). OCR repairs: Latin look-alikes; the outlined «П» read «1»/«N» before «/ВЕ»
   («12/BE» → П2 + ВЕ); the **closed vocabulary** — the vent tags printed as text on the drawings of the
   object's vent/heating documents (ОВ, ИОС 5.4 by name; 124 tags on Тюменская, cached per file in
   `.cache/inspector_layout/vocab`) plus the run's PageTokens text layers — repairs one-slip OCR («B22» →
   «В2.2») and, only with evidence (a vent label layer or OCR confidence < 0.8), the weak heads «3» → «В»,
   «11» → «П» («32.1» on «ОВ-Вентиляция-Выноски» → В2.1, «119» at 0.69 → П9). A red «В2» on the room-category
   layer is a fire category, not a system. Room link: `LEADER`, else `INSIDE`, else `NEAREST`; a label with
   several leaders reaches several rooms; a mark on a «267, 270» label is emitted once per room.
6. **Revision clouds** (`cad/clouds.py`): clusters on «…Изм. №N» layers (arcs → cloud, lines → weak change zone),
   closed scalloped arc chains elsewhere (`VECTOR_SHAPE`); `rooms_covered` from labels and zones.

Consumers:

- `rooms/inventory.py` — per-room multisets: `inventories(layout)`, `room_inventories(layouts, "147")`,
  `tag_elements(tag)`; empty inventories are kept («no local exhaust in 140» is the G-TR-003 finding).
- `rooms/index.py` — `RoomIndex.from_layouts(...)`: `pages_of("314")`; `match_sheets("PD", "RD")` with
  **floor-partitioned overlap** (a scheme of floors 1–3 matches each floor plan: rooms grouped by the floor of
  their number, «142» → 1, «012» → 0, «1.109» → 1); `counterparts(room, file_id, page)` ranks the pages of the
  other stage that label the room by the room's topic on the source page (vent/heating from its own marks),
  the sheet overlap, plans before details and the room's marks there.

```bash
cd services/ml
uv run --locked python -m inspector_layout.rooms.cli --object OBJ-TYUMENSKAYA-5-GOLD-SEED \
  --files F0171 F0201 F0202 --pages F0171:88,99,104 --pages F0201:14-40 --pages F0202:14-36 \
  --tokens-run m1-ag02b2-tokens --run-id m1-ag02b2-layout --workers 3 --report /tmp/rooms_report.json
uv run --locked python -m inspector_layout.rooms.cli --object OBJ-TYUMENSKAYA-5-GOLD-SEED \
  --tokens-run m1-ag02b2-tokens --run-id m1-ag02b2-object --workers 3      # every PDF of the object
uv run --locked pytest -m "not slow" packages/inspector_layout/tests/test_rooms_*.py packages/inspector_layout/tests/test_cad_toolkit.py
uv run --locked pytest -m slow packages/inspector_layout/tests/test_rooms_data.py   # RD pages (PageTokens)
```

The report (`rooms/bench.py`) gives: the gold rooms located (cited page, or another page of the file — the
group-anchor rule, 314 on p20); **room-token EM** on the benchmark room set (the 21 hand-registered label
anchors of `95_tyumen_dev_fixtures.json` + every explication row of the fully read plans, matched by an exact plan
label; text-layer-only pages are reported as coverage); plan-label precision against the explications;
**fixture tag checks** (`page_facts`: PD local-exhaust branches per room, the supply units of 012, RD marks per
room, the 012 zone, the F0202 p17 cloud over 270/272); **tag spotting on the adjudicated OCR GT** drawing pages
(`gt_staging/ocr_gt_v2.json`: D01 = F0201 p15, D02 = F0202 p19; the grammar on the GT text is the reference);
**PD→RD counterparts** of the gold rooms (top-1 = the cited RD page, or the page the room is drawn on); per-room
PD vs RD inventories of the gold rooms; PD↔RD sheet matches; clouds and timings. Synthetic sheet for tests:
`rooms/synth.vent_plan_pdf`.

Measured on the gold pages (F0171 p88/99/104, F0201 p14–40, F0202 p14–36; PageTokens `m1-ag02b2-tokens`):
gold rooms located 20/20 (19 on the cited page, 314 on p20); room-token EM 0.9957 on 698 (misses: «1006», in the
explication but not printed on the plan); plan-label precision 0.9926; fixture tag checks 13/14 (element recall
0.978; the miss is «ВЕ» of «П3/ВЕ» in 314, hidden under the «Зонт из оц. стали» leader text); GT tag spotting
recall 0.925 / precision 0.985 on 439 elements; counterparts 10/10 (9 cited pages + 314 drawn on p20).
