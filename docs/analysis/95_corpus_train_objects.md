# B95 — Train corpora profile, Тюменская gold fixtures and the dev/validation protocol

Scope: the two TRAIN_PUBLIC objects of package v2.0. These are **OBJ-TYUMENSKAYA-5-GOLD-SEED** («Пример нарушений на чертежах», АНО/150321, «Школа на 600 мест, р-н Богородское, ул. Тюменская, вл. 5») and **OBJ-NOVOSLOBODSKAYA** («Жилой дом с подземной автостоянкой…», ул. Новослободская, шифр НВС-2025/03). OBJ-RECHNIKOV-7-7 (TEST_HIDDEN) was not opened.

Deliverables written by this block:

| File | What it is |
|---|---|
| `docs/analysis/95_corpus_train_objects.md` | This report |
| `docs/analysis/corpus_train_profile.json` | Per-file profile of all 203 train manifest rows: page classes, text-layer share, scan DPI, formats, codes, revisions, CAD layers, QR, page maps, OCR samples. Also per object/stage summaries, the 19 missing files, sheet maps, revision-pair diffs and the АОСР parse summary |
| `docs/analysis/95_tyumen_dev_fixtures.json` | Тюменская gold turned into fixtures: expected submission (10 checks), page facts and anchors per evidence page, 12 zone bboxes registered from the organizers' 6-page markup, 10 recognition tests, gold quirks, known unlabeled differences |
| `docs/analysis/95_novoslob_label_seed.json` | 14 seed candidates for the self-labelled check on Новослободская, each with PD/RD/ID evidence pages and our hypothesis. The `label` field is left empty for the user |

Read with: `93_scoring_contract_appendix2.md` (scoring hypotheses, evidence anchoring, value templates, FREE-* codes, the hidden-test integrity rules), `02_extraction_ocr_nlp_cv.md` (recognition design) and `90_consistency_and_canonical_model.md` §3.12 (pilot routing). Where this report and 93 overlap, 93 owns scoring and export, and this report owns corpus facts and recognition requirements.

---

## 0. Executive summary

1. **Every gold violation is detectable from signals that exist in the files, but the RD side needs OCR of outlined CAD text.** On all six gold pages, PD system tags such as В2.4 and П17 are in the text layer. On the RD pages, room numbers and explications are text, but system tags, air-flow labels, dimensions and the whole title block are drawn as vector strokes (SHX text). Examples: F0201 p17 has 233 words against 66k paths, and F0202 pages 19–36 carry 3–13 words each. An RD-side comparison without OCR therefore sees rooms with no equipment.
2. **The PDFs keep their CAD layers, and the layers are the strongest recognition lever we have found.** 42 of 57 Тюменская PDFs and 83 of 126 Новослободская PDFs carry optional-content groups (OCGs). PyMuPDF attributes every path to its layer. Examples: `DUCT-Приток`, `DUCT-Вытяжка-TEXT`, `ОВ-Вентиляция-Выноски`, `ОВ-Архитектура`, `ОВ-Отопление-Изм. №3`. Three uses were measured:
   - **Layer-isolated OCR.** Hide every non-text layer through `layer_ui_configs()`, then OCR the clean render. On the vent chamber 012 zone this took 1.1 s instead of 2.8 s, and it recovered «П9», which a full render misread as «6U» at 300 dpi and missed at 500 dpi.
   - **Revision-cloud layers localise changes.** The only CAD revision cloud on the gold warm-floor RD page (`ОВ-Отопление-Изм. №3`, F0202 p17) covers rooms 270/272, which is the gold location.
   - **Wall and duct layers** give room polygons and system membership.
3. **Title-block QR codes identify documents and pages.** OpenCV decodes them at 300 dpi at a fixed title-block position. On Тюменская RD they are Exon URLs `…/document-status/<doc-uuid>/1/wd/<page>`. They prove that the ИД «Исполнительный чертеж. План 2 этажа Отопление» (F0198) is page 17 of РД ОВ2.1 (F0202). They also show that F0197, F0199 and F0200 come from a newer ОВ1 issue with a one-page offset. Новослободская RD carries `qr.sgnl.pro` links on 8 of 10 files. This serves `document_integrity_and_split_handling`.
4. **The gold's sheet numbers are not reliable, but its PDF page numbers are.** For F0201 the gold `document_sheet_number` is stamp − 1: p17 is gold «3» but stamp «4», and p18 is gold «4» but stamp «5». F0171 and F0202 match their stamps. Room 314 is drawn on F0201 **p20**, yet TRAIN-0010 cites p18. The organizers' own 6-page markup, which we registered onto the pages, puts 314 on p20. Localisation must follow the group-anchor rule of 93 §2.8, and sheet→page mapping must come from our own title-block OCR, never from gold.
5. **10 % of Тюменская PD pages have a broken text layer (mojibake), and the planned detector would miss them.** Our first profiling pass flagged only 8 pages with the planned `garbage_ratio` (U+FFFD/PUA); a lexicon or mojibake-ratio check finds 508. Examples: 255 pages of «Том 1.2 Книга 1» (F0146) and 242 of its revision F0150, where «ȺɇɈ/150321/1-ɉ-ɉɁ1.2» should read «АНО/150321/1-П-ПЗ1.2». Other variants appear in F0153, F0166 («ǷȘȖȚȖȒȖȓ») and F0204 («IJHLHDHE»). Such pages must go to OCR, or through a per-font glyph remap.
6. **Revisions and binders are messy in ways the pipeline must handle explicitly:**
   - Three «ИЗМ ПО ЗАМЕЧАНИЯМ» volumes (ОПЗ, ПЗУ, АР) coexist with their originals. The revised volumes carry «(КОРРЕКТИРОВКА 1)» and a «Сопоставительная ведомость внесенных изменений», and 596 of 614, 27 of 39 and 13 of 27 pages are unchanged.
   - F0201 holds sheets 14 and 15 **twice** (p27/p29 and p28/p30); p29 carries the `ОВ-Вентиляция-Изм. №2` cloud.
   - The RD «Полные разделы» are 36–676-page binders. F0201 contains front matter, scanned approval sheets, a «Разрешение на внесение изменений», 159 drawings, about 420 equipment-selection printouts and VRF calculations.
   - The ИД АОСР №1/ОВ cites «РД-ОВ1 изм. 3» although изм. 4 (11.08.2024) is the supplied file, and it cites «АНО1301211-Р-ОВ1» (130121 instead of 150321).
7. **Новослободская is a good unlabeled development object for КР and for the ИД котлована, and weak for everything else.**
   - PD is a full ПД set: 36 volumes, 2,067 pages, 88 % text layer.
   - RD is 10 КЖ/pit documents with a 93 % text layer: СВГ, РС, ВП, ДР, КЖ1.1.1–1.1.5 and 1.1.8, plus an «усиление фундаментов» of the neighbouring building.
   - ИД is 99 electronic АОСР, of which 80 are on disk. Their text layer parses at **100 % field coverage** (9 fields × 80 acts). Their attachments (паспорта, сертификаты, протоколы) are scans, mostly at 300 dpi.
   - About 12 matrix parameters have real PD↔RD(↔ID) pairs: KR-054…061, KR-067, PZ-009, SPZU-039 and POS-087. The rest can only be MISSING_DOCUMENT / RD_MISSING / ID_MISSING, which is itself a good test of status accuracy and document integrity.
8. **Новослободская already shows a real discrepancy candidate and several false-positive traps:**
   - *Candidate.* For the unreinforced БСС piles, the ИД реестры list concrete «БСТ В15 П4 F150(I) W8», with one batch at W6. RD СВГ requires «В15, F200, W8». The PD contradicts itself: F200 W8 on p17 and F100 W6 in the ведомость on p24.
   - *Traps.* Площадь застройки 1225,8 in ПЗ vs 767,0 in ПЗУ (the ПЗУ figure is the ground part). Slab thickness 1000/1200 in PD vs 1200/1500 in RD (an increase, and the trigger says «уменьшение»). Cage and concrete tops above the design top in the исполнительные схемы.
9. **19 Новослободская files are missing locally, and one change fixes it.** They are 16 АОСР «…РЗ…» and 3 «…РФ…», 192 pages in total. The cause is the case-insensitive APFS merge described in 93 §1.3. We need a re-extract (§7, Q1) before labelling.
10. **Pilot mapping.** Only the 6-page «пояснения» (VENT) maps to these corpora: it is Тюменская groups G-TR-001…004 one-to-one. None of the other eight pilot objects (Алтуфьевское 79Б, УНДМС, Изумрудная 12, Лосевская 3А, Октябрьская 103, Полярная 16/25/17) appears in any train or hidden file name or train text. They remain page-level recognition fixtures and demo material.
11. **Development and validation protocol (§5).**
   - Тюменская gold is a must-pass acceptance fixture: all 10 checks with exact file+page, and no critical miss.
   - Новослободская is the unlabeled development object. A self-labelled check of about 110 items is recommended (≈2 h of the user's time, or ≈40 min for a 30-item minimum), frozen before threshold tuning and used in two folds by discipline.
   - Речников runs exactly once with a frozen config hash.

---

## 1. Method and tools

- **Profiling.** PyMuPDF 1.28.2 over all 9,950 pages that are present. Per page: text length, Cyrillic, Latin and mojibake counts, image coverage and native DPI (image pixels ÷ placement inches), content-stream size, format (ГОСТ 2.301 including A3x3 and A4x4), document-kind keywords, and a content type. Per file: metadata, OCG and CAD layer names, revision layers, ciphers, stamp revision rows, АОСР references and page-map runs. The cost was about 10 ms per page (94 s summed for the whole train set). Scripts are in the scratchpad `c95/` (`profile2.py`, `build_json.py`).
- **OCR.** RapidOCR 3.9.2 with PP-OCRv5 cyrillic (mobile det/rec) on ONNX Runtime, 4 threads. The scratch venv already had it. Three uses:
  - 80 randomly sampled scan pages (`ocr_sample.py`);
  - title blocks of F0201 p14–40 and F0202 p14–36;
  - all outlined RD ОВ2.1 pages, to prove that warm-floor text is absent.
- **QR codes.** OpenCV `QRCodeDetector` on a fixed 40×33 mm window at 300 dpi (`qr_scan.py`), about 170 s for all drawing pages.
- **Markup registration.** SIFT with a RANSAC partial affine transform mapped each of the 12 crops in «Комплект_предметной_разметки_с_пояснениями_.pdf» onto its source page (48–907 inliers, uniform scale 0.764). We then transformed the blue (PD) and red (RD) zone rectangles into normalised page bboxes.
- **Machine load.** Other agents were busy, with load averages of 8–33. OCR timings here are therefore pessimistic.

Classes used (thresholds from 02 §3.2, one class added):

| Class | Rule |
|---|---|
| VECTOR_TEXT | Visible text ≥ 50 chars, image cover < 0.5 |
| RASTER_SCAN | Image cover ≥ 0.5 and < 50 visible chars |
| HYBRID | Image cover ≥ 0.5 with a text layer |
| VECTOR_OUTLINED_TEXT | < 50 chars and content stream > 100 KB |
| BROKEN_ENCODING (**changed**) | Mojibake ratio ≥ 0.12 and Cyrillic share < 0.35. The mojibake ratio is (Latin Ext-A/B + `<>=?@[]^_{}|`) ÷ visible chars |
| EMPTY_OR_STAMP | No text, image cover < 5 % |
| `partial_outline` (flag) | A VECTOR_TEXT page with > 400 KB of content and < 1 char per KB. This is the typical CAD sheet: room numbers as text, tags as strokes |

---

## 2. Corpus overview

| Object · stage | Files (on disk) | Pages | MB | Text layer | Scan | Hybrid | Outlined | Broken enc. | Partial-outline pages | Scan DPI (pages) |
|---|---|---|---|---|---|---|---|---|---|---|
| Тюменская · PD | 47 | 5,026 | 753 | 64 % | 17 % | 4.4 % | 4.2 % | **10.1 %** | 115 | 120: 655, 150: 162, 200: 119, 400: 47, 300: 38, 96: 26 |
| Тюменская · RD_ID_MIXED | 10 | 837 | 101 | 75 % | 1.4 % | 0.1 % | **22.6 %** | 0.1 % | 21 | 200: 6, 400: 3, 96: 3 |
| Тюменская · UNKNOWN | 1 (txt) | — | — | — | — | — | — | — | — | — |
| Новослободская · PD | 36 | 2,067 | 269 | 88 % | 3.2 % | 3.6 % | 3.0 % | 2.2 % (F0107) | 86 | 200: 73, 150: 21, 96: 15, 300: 15 |
| Новослободская · RD | 10 | 194 | 35 | 93 % | 0 | 0.5 % | 6.7 % | 0 | 0 | — |
| Новослободская · ID | 99 (**80**) | 1,826 | 545 | 16 % | **40 %** | 2.1 % | 8.3 % | 0 | 15 | 300: 404, 150: 207, 400: 96, 200: 45 |

Formats: Тюменская has 4,833 A4, 559 A3 and 110 each of A1 and A0, plus 114 elongated sheets (A4x3, A3x3, A2x4, A4x4…). Новослободская has 2,779 A4, 689 Letter or narrow A4 (mostly ИД separator and stamp pages), 225 A3, 163 A1, 159 A2 and 16 A0.

Local data problem (details in 93 §1.3): 19 Новослободская manifest rows (192 pages) have no file on disk. They are F0015, F0018, F0021, F0024, F0027, F0030, F0033, F0036, F0039, F0042, F0045, F0049, F0052, F0055, F0064, F0067 (АОСР «…РЗ…») and F0071, F0077, F0080 (АОСР «…РФ…»). Two further files, F0070 and F0072, exist under «…ДФ_…» and «…С_…» names; we verified them by sha256. Ingestion must resolve by sha256, and a missing file must never be reported as MISSING_DOCUMENT for the object.

---

## 3. Part A — OBJ-TYUMENSKAYA-5-GOLD-SEED

### 3.1 What the object contains

| Group | Files | Notes |
|---|---|---|
| ПД (47 volumes, stage П, АНО/150321/1-П-…) | F0146–F0193 (F0149 excluded) | Pairs of originals and revisions: ОПЗ F0146 → «ИЗМ ПО ЗАМЕЧАНИЯМ» F0150; ПЗУ F0154 → F0155; АР F0156 → F0157. `V2_` prefix on most volumes. F0165 is the kept representative of `duplicate_group f4a34324aaf6`; the excluded F0149 sat in the ПЗ folder between F0148 and F0150 and was presumably its duplicate (not verifiable, the file is not shipped). Scans: ИРД books F0146/F0150 (42 % scans at ~120 dpi), F0148 (40 %, 150 dpi), F0182 (32 %), F0164/F0165 (22–24 %, 300 dpi). Heavily outlined volumes: ЭОМ F0160 (63 %), НВ F0163 (48 %), ВК F0167–F0169 (35–39 %) |
| RD «Полные разделы» (stage RD) | F0201 ОВ1 изм.4 (676 p), F0202 ОВ2.1 изм.3 (36 p), F0203 ВВ изм.3 (45 p), F0204 ВК изм.2 (71 p) | Binders. Each opens with 4 text pages: cover and «Состав» by ООО «БратКом-групп» and ООО «ТСП». Scanned approval pages follow (F0201/F0202 p5, p7–9), then a «Разрешение на внесение изменений» (p6: F0201 «839-24», F0202 «861-24»), the «Состав РД» (p10–13) and the drawings. F0201 then continues with ~420 A4 «подбор оборудования» printouts (p173–595) and 80 VRF calculation pages (p596–676) |
| ИД (stage ID inside RD_ID_MIXED) | F0195 АОСР №1-ОВ2.1 (20.12.2024), F0196 АОСР №1/ОВ (07.04.2025), F0197–F0200 «Исполнительный чертеж» (1 page each: план 1, 2 (отопление), 3 этажа, подвала) | The АОСР are Word/Aspose text. The as-built drawings are single-page extracts; their QR codes point to their source documents (§3.6 R7) |
| Ground truth | F0194 «Перечень нарушений.txt» | Three items. Item 3 becomes G-TR-003 and G-TR-004 |

Page map of the gold RD binder F0201: `1-4 TEXT · 5 SCAN · 6 TABLE(Разрешение на изм.) · 7-9 SCAN · 10-13 TEXT(Состав РД) · 14-172 DRAWING · 173-595 equipment-selection printouts · 596-676 VRF`. OCR of the sheet sequence (title blocks, `extras.sheet_map_F0201_title_block_ocr`) gives:

| pdf page | 14 | 15–16 | **17** | **18** | 19 | **20** | 21 | 22–26 | 27/29 | 28/30 | 31–33 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Stamp sheet | 1 | 2–3 | **4** | **5** | 6 | **7** | 8 | 9–13 | 14 (twice) | 15 (twice) | 16–18 |
| Title | Общие данные | — | План подвала (вентиляция) | План 1-го этажа (вент.) | План 2-го этажа | План 3-го этажа | План кровли | Планы (кондиционирование) | Разрезы (p29 with изм.2 cloud) | — | План и разрезы венткамеры (p32 = axes 16-18/К-Н, vent chamber 012) |

### 3.2 Gold, Перечень and the 6-page markup: one-to-one

| Group (checks) | Перечень item | 6-page markup page | Code / mapping status | Type | Rooms | PD evidence (file p · stamp sheet) | RD evidence (file p · gold sheet / stamp) |
|---|---|---|---|---|---|---|---|
| G-TR-001 (TRAIN-0001) | 1 | p2 «Венткамера 012» | IOS4-079 · PROVISIONAL_DOMAIN_MAPPING | CONFIGURATION_MISMATCH | 012 | F0171 p104 · л.26 | F0201 p17 · 3 / **4** |
| G-TR-002 (0002–0005) | 2 | p3 «Помещения МГН» | **FREE-HEATING-001** · MATRIX_GAP_CONFIRMED | MISSING_DESIGN_ELEMENT | 267, 270, 271, 272 | F0171 p99 · л.21 | F0202 p17 · 4 / 4 |
| G-TR-003 (0006–0007) | 3 | p4 «140 и 142» | IOS4-078 · PROVISIONAL | MISSING_DESIGN_ELEMENT | 140, 142 | F0171 p88 · л.10 | F0201 p18 · 4 / **5** |
| G-TR-004 (0008–0010) | 3 | p5 «147 и 198», p6 «314» | IOS4-078 · PROVISIONAL | CONFIGURATION_MISMATCH | 147, 198, 314 | F0171 p88 · л.10 | F0201 p18 · 4 / 5 (**314 is on p20**, stamp 7 = markup «лист 6») |

Every check has `id_value = null` and `document_status = PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK`, even though an ИД copy exists (F0198 is identical to F0202 p17). The markup numbers RD sheets the way the gold does («ОВ1, лист 3», «листы 4 и 6»), so the stamp − 1 offset is organizer-side and consistent.

### 3.3 Evidence-page anatomy (measured)

| Page | Size, class | Text layer | Vector / layers | What is on it |
|---|---|---|---|---|
| F0171 p104 (PD л.26) | 841×297 mm (A4x4), VECTOR_TEXT | 273 words, ISOCPEUR; П-tags, rooms 006/007/012 as text | 4,542 paths, `ОВ-*` layers | «Принципиальная схема системы теплоснабжения приточных установок». A section-like band of rooms separated by vertical walls; 012 spans x ∈ [0.665, 0.871]. Supply units inside 012: **П2, П2.1, П3, П8, П9, П10, П15, П17, П18**. П20 sits in 007 |
| F0201 p17 (RD, stamp 4) | A0 portrait, VECTOR_TEXT + outlined | 233 words: explication, room numbers | 66,206 paths, 108 CAD layers used, QR `3eb2aa9d…/wd/17` | «План подвала (вентиляция)». The vent chamber 012 zone is [0.81, 0.47, 0.95, 0.60]. Tags are **outlined**: П9, П15, П17.1/17.2, П18, В2.1, «Пароувлажнитель (П2)» ×2. A 2914×2381 raster inset («Таблица противопожарных клапанов», [0.77, 0.82, 0.99, 0.95]) sits inside the vector page |
| F0201 p32 (RD, stamp 17; not cited) | A1 | — | — | «План Венткамеры в осях 16-18 / К-Н», M1:50. OCR: П2, П2.1, П3, П8, П9, П10, П15, **П17.1, П17.2**, П18, plus humidifiers «Пароувлажнитель (П2/П3)» ЭПГ-25/35/45 |
| F0171 p99 (PD л.21) | 1486×420 mm, VECTOR_TEXT | 824 words; «267, 270 / 271, 272 Раздевальная и санузел для МГН», leader «Регулятор для системы “теплый пол” Multibox C/RTL» | 3,865 paths; warm-floor loops are nested rectangular spirals on `ОВ-Отопление-Схема` | Heating schematic |
| F0171 p11, p136 (PD text) | A4 | ПЗ: «В помещениях раздевальных, санузлов и душевых для МГН (пом. 267, 270, 271, 272) предусмотрена система подогрева полов (теплые полы)…». Спецификация: «Регулятор для системы “теплый пол” Multibox C/RTL — компл. 2» | — | The textual ground for G-TR-002 |
| F0202 p17 (RD, stamp 4) | A0 portrait | 817 words (explication, rooms) | 164,576 paths; **`ОВ-Отопление-Изм. №3` cloud [0.337, 0.687, 0.423, 0.73] over rooms 270/272**; QR `87cc1a16…/wd/17` | Heating plan of the 2nd floor. Radiators «PRADO Universal 22-500-700», heat-loss tags «+22 °C 700/690 Вт», no loops. OCR of all 23 outlined drawing and specification pages (p14–36): no «тепл* пол», Multibox or RTL. Only «коллектор» and «кронштейн для напольного монтажа» appear |
| F0171 p88 (PD л.10) | 891×420 mm (A3x3), VECTOR_TEXT | 364 words; all tags as text | 2,299 paths | «Принципиальная схема систем общеобменной вентиляции (продолжение №3)». Floors are horizontal bands and rooms are columns. Local exhausts «М.О. поз.…» with branch tags: **142 → В2.4–В2.6; 140 → В2.7–В2.9; 147 → В2.10; 198 → В2.2, В2.3; 314 → В3.1, В3.2** |
| F0201 p18 (RD, stamp 5) | A0 portrait | 1,222 words (explications, rooms) | 152,410 paths; `DUCT-Вытяжка(-TEXT)`, `ОВ-Воздухообмены`, `ОВ-Вентиляция-Выноски` | «План 1-го этажа (вентиляция)». OCR on text layers only: 140 and 142 show only «П2/ВЕ ±400 м³/ч»; В2.7,8,9 (−950 м³/ч) now serve **141**; 147 has В2.2, В2.3, В2.4 («В2.3,4 −150 м³/ч»); 198 has В2.8, В2.9, В2.10 (М.О. поз.159/162) |
| F0201 p20 (RD, stamp 7) | A0 portrait | 572 words | — | «План 3-го этажа». 314: one branch В3.1 (−600 м³/ч, «над 3D-принтером, поз.133») and П3/ВЕ ±350. The PD had two branches |

**The evidence PNGs are plain page renders.** `evidence_pages/*.png` are full-page renders at 100 dpi: 3312×1170, 3312×4681, 5850×1655 and 3509×1655 px, pixel-identical in geometry to a PyMuPDF 100-dpi render. The mean absolute difference is 3.7–7.2 grey levels. That comes from anti-aliasing and heavier thin lines (33–60 % more red pixels), not from added markup. Localisation in the gold is therefore page-level only (`PAGE_LEVEL_VISUALLY_VERIFIED`).

**The markup gives region-level zones.** The only region-level truth for this object is the 6-page markup. We registered its 12 crops (§1) and stored the zones in `95_tyumen_dev_fixtures.json → markup_zone_bboxes`:

| Group | PD zone | RD zone |
|---|---|---|
| G-TR-001 (012) | F0171 p104 [0.697, 0.274, 0.888, 0.574] | F0201 p17 [0.809, 0.475, 0.951, 0.604] |
| G-TR-002 (267/270/271/272) | F0171 p99 [0.283, 0.350, 0.341, 0.508] | F0202 p17 [0.336, 0.653, 0.443, 0.709] |
| G-TR-003 (140/142) | F0171 p88 [0.167, 0.575, 0.264, 0.688] | F0201 p18 [0.863, 0.107, 0.959, 0.224] |
| G-TR-004 (147) | F0171 p88 [0.318, 0.575, 0.386, 0.681] | F0201 p18 [0.836, 0.263, 0.936, 0.322] |
| G-TR-004 (198) | F0171 p88 [0.693, 0.569, 0.754, 0.686] | F0201 p18 [0.692, 0.128, 0.805, 0.178] |
| G-TR-004 (314) | F0171 p88 [0.712, 0.292, 0.782, 0.414] | **F0201 p20** [0.684, 0.051, 0.785, 0.109] |

### 3.4 What distinguishes each violation, and what a detector needs

| Group | Distinguishing signal (PD vs RD) | Channels that carry it | Detector requirements | Hardness |
|---|---|---|---|---|
| **G-TR-001 IOS4-079, 012** | The supply-unit set assigned to vent chamber 012 differs. PD л.26 has {П2, П2.1, П3, П8, П9, П10, П15, **П17**, П18} grouped on three heat-supply branches. RD has **П17 → П17.1 + П17.2**, plus steam-humidifier sections (ЭПГ-25/35/45) and a different layout. The organizers call this «конфигурация приточных установок… не соответствует» | PD text layer (tags); RD outlined tags (OCR); RD vent-chamber detail sheet p32; the equipment «подбор» printouts p173–595 (unit parameters as text, for IOS4-079 values) | (1) Room zone for 012 on a *schematic* sheet: an interval between vertical wall lines inside the floor band. On a *plan*: a wall-layer flood fill from the room label. (2) Layer-isolated OCR of RD tags, then tag grammar `^[ПВ][ЕД]?\d+(\.\d+)?$` and homoglyph folding (B→В, N→П, E→Е). (3) Set diff with split and merge detection (П17 ↔ П17.1/П17.2). (4) Choose the **plan** sheet (p17) as the RD anchor over the detail sheet (p32), as gold does | Medium–high. It is the only group without a textual statement. Expect CANDIDATE with medium confidence |
| **G-TR-002 FREE-HEATING-001, 267/270/271/272** | The PD says warm floors are present in four named rooms: ПЗ text p11 lists the rooms, the spec p136 has Multibox ×2, and л.21 shows loops and a leader. The RD has no warm-floor element anywhere: text layer plus OCR of 23 outlined pages. Radiators stand in the same rooms, and an **RD revision cloud (изм. 3) covers 270/272** | PD text (strongest); PD drawing (localisation); RD absence (needs full OCR coverage of outlined pages); RD revision layer | (1) Element–room assertion extractor from PD text: «в помещениях … (пом. N, N…) предусмотрен…». (2) **Absence proof**: element dictionary search over the RD text layer **and** OCR tokens, with a coverage flag. Absence is claimed only when every RD page of the discipline was read (text or OCR). (3) Room localisation on the RD plan via room labels, with the revision cloud as confirmation. (4) Routing to FREE-HEATING (no matrix parameter covers floor heating) | Low for detection, medium for provable absence. This is the best «text channel» example |
| **G-TR-003 IOS4-078, 140/142** | PD л.10 draws three local exhausts (М.О. поз.169) with branches В2.4–2.6 in 142 and В2.7–2.9 in 140. On RD л.5 both rooms show only the general exchange «П2/ВЕ ±400 м³/ч»; the В2.7–2.9 group now serves 141 | PD text tags + «М.О.» symbols; RD outlined tags and air-flow boxes (`ОВ-Воздухообмены`) | Per-room *local exhaust count*: tags `В\d+\.\d+` plus «М.О.» next to the room, compared PD vs RD. Missing in RD means MISSING_DESIGN_ELEMENT. Tag identity must **not** be the key, because RD renumbers branches (В2.2–2.4 moved to 147) | Medium |
| **G-TR-004 IOS4-078, 147/198/314** | Branch count and composition per room differ. 147: PD В2.10 (1) vs RD В2.2–2.4 (3). 198: PD В2.2–2.3 (2) vs RD В2.8–2.10 (3). 314: PD В3.1–3.2 (2) vs RD В3.1 (1, −600 м³/ч) | Same as G-TR-003; 314 is on another RD sheet (p20) | Per-room branch multiset diff; the multi-sheet room index (a room can sit on any floor plan); the group-anchor evidence rule (93 §2.8) | Medium |

What does **not** carry the signal: page-level pixel diff (the PD sheets are schematics while the RD sheets are plans), symbol counting, and the matrix numeric triggers. IOS4-078's literal trigger is «уменьшение площади сечения воздуховода». The organizers nevertheless map *missing or changed branches* to IOS4-078 as a «provisional domain mapping». The mapping table must therefore route by element family, not by trigger wording (see 93 §3.8).

### 3.5 Recognition requirements derived from the train corpora (for B02, top priority)

| # | Requirement | Evidence here | Effect |
|---|---|---|---|
| R1 | **BROKEN_ENCODING by mojibake or lexicon ratio**, not only U+FFFD. Route to OCR, or build a per-font glyph→Unicode remap (render each glyph code once, OCR it, apply to the whole file) | 508 pages (10.1 %) of Тюменская PD; F0146 p1–31, 147–175…; F0153, F0166, F0204; Новослободская F0107 (45 SCAD printout pages) | Otherwise ПЗ text, ТЭП and title pages read as garbage and are silently skipped |
| R2 | **Layer-aware rendering (OCG).** Toggle layers with `layer_ui_configs()` / `set_layer_ui_config()`. Render text-only layers (`*-TEXT`, `*Выноски`, `*Текст`, `*Подписи`, `*Воздухообмены`, `*Маркировка`, `*Теплопотери`) for OCR; render wall layers (`ОВ-Архитектура`, `A-DOORS`, `S_перегородки`) for room masks; use `DUCT-Приток/Вытяжка/Дымоудаление` for system membership | 42/57 and 83/126 PDFs have OCGs; F0201 has 157 layer names in 3,128 OCGs | Cleaner OCR (П9 recovered, ~2.5× faster per zone), room polygons, system classification |
| R3 | **Outlined-text OCR on CAD sheets** at 300 dpi, tiled, on layer-isolated renders; add a **closed-vocabulary tag spotter** seeded from the PD tag set of the same system | RD ОВ: 22.6 % outlined pages + 21 partial; room numbers are text while tags are strokes | Without it, RD rooms look empty and every PD element becomes a false MISSING_DESIGN_ELEMENT |
| R4 | **Revision-cloud layers** (`…Изм. №N`, `…Изм.N`) → change zones with rooms inside; store per sheet | F0202 p15–31, F0201 p14/16/23/29/34/39/40, ИД F0197/F0199 (изм. 5), F0198 | Precise localisation; a second vote for candidates; a demo «wow» |
| R5 | **Title-block OCR** (sheet, листов, шифр, стадия, change rows «N Зам. NNN-YY дата») with **sequence smoothing** and duplicate-sheet detection | F0201 sheets read correctly on 26/27 pages, one missed; F0202 p19 read «9» for 6; sheets 14/15 duplicated in F0201 | Sheet↔page maps; per-sheet revision; superseded pages inside binders |
| R6 | **Rotated text lines** (180° and 90° blocks in specifications): enable the angle classifier and a 180° retry for lines with a low lexicon hit | F0202 p29: «доодни хншпиошо…» is an upside-down «Всего…» | Specification totals are otherwise lost |
| R7 | **QR decoding** in title blocks (fixed window 40×33 mm at 300 dpi; fallback: bottom-right quarter at 200 dpi, multi-detect) → `doc_uuid`, `page_index`, host; store in the registry | Exon QR decoded on every sampled drawing page of F0201 (40/40), F0202 (23/23), F0203 (7/7) and on all four ИД extracts F0197–F0200; none on F0204 or on PD volumes; `qr.sgnl.pro` on 8/10 Новослободская RD files | Split handling (ИД extract = RD page), version linking, integrity score |
| R8 | **Room index across sheets**: every room label with its sheet, zone (schematic column or plan polygon), explication row (name, area, category) and floor | 314 on p20; 012 on p17 and p32; explications are text on RD plans | Correct location tokens, group anchors, multi-page evidence |
| R9 | **Embedded rasters inside vector pages** above 5 % of the area → OCR | F0201 p17 fire-damper table (2914×2381 px) | Tables otherwise invisible |
| R10 | **Scan resolution handling**: upsample ×2 below 200 dpi before OCR; keep native at 300–400 dpi | Тюменская ИРД at ~120 dpi (655 pages); Новослободская ИД 300 dpi (404) / 150 dpi (207) / 400 dpi (96) | OCR confidence stays ≥ 0.93 (sample median) |
| R11 | **Separator and stamp pages** («КОПИЯ ВЕРНА» stamp on blank Letter pages) → class `STAMP_PAGE`, skipped but counted | 606 of 1,826 Новослободская ИД pages (33 %) | Prevents «empty/corrupt page» false alarms and wasted OCR |
| R12 | **Binder segmentation** into front matter, approvals (scan), change permit, «Состав», drawings, specifications, calculation printouts, attachments | F0201 (676 p), F0202, F0203, F0204; every Новослободская АОСР | Correct document type per page; RD vs ИД per page for RD_ID_MIXED |
| R13 | **АОСР form parser** (text layer): act №, works (п.1), design docs with изм. (п.2), materials or реестр (п.3), attachments (п.4), dates (п.5), norms (п.6), next works (п.7); plus the **реестр приложений** table (materials with class, F/W marks, certificate numbers) | 80/80 acts, 9/9 fields; Тюменская F0195/F0196 too | ИД values for KR-055/057, linkage, date-order rules |
| R14 | **Cipher normalisation** across slash, dot, underscore and hyphen, with fuzzy matching and a typo flag | «НВС-2025/03-КР1» (АОСР) = file «НВС-2025.03-4.1-КР1»; «17_ПД/25-СВГ» (АОСР) vs «17_ПД/25-СГ» (RD title); «АНО1301211-Р-ОВ1» (typo) vs «АНО/150321/1-РД-ОВ1»; foreign cipher «СГ-2404-63-П-ИОС5.5.3» inside Новослободская ТХ3 (F0110 p28) | Linkage and integrity checks |
| R15 | Robustness: MuPDF «missing font descriptor» warnings; 0×0 pages; 1000+ mm long sheets; Word-generated АОСР with iText page stamps (1–2 visible chars on scan pages) | F0204, F0106, F0113 | No crash; the text-layer threshold ignores page-number stamps |

### 3.6 Revisions inside Тюменская (for B01)

| Pair / file | Finding | Rule for the registry |
|---|---|---|
| F0154 → F0155 (ПЗУ) | 13/27 pages identical. p5–6 text: «исключено благоустройство за границами ГПЗУ; исключены 2 подзоны». p18–27 drawings: ГПЗУ № «-77-53-3-01-2023-0970» → «-77-4-53-3-01-2023-0970», site boundary by lease «№И-03-002759» | The «ИЗМ ПО ЗАМЕЧАНИЯМ» file is CURRENT and the original SUPERSEDED. The page-hash diff lists the changed sheets |
| F0156 → F0157 (АР) | New p5 «Сопоставительная ведомость внесенных изменений», title «(КОРРЕКТИРОВКА 1)». p7→8 and p33–38→34–39 differ only in axis naming («в/о Ю-А» → «между осями АЖ-А») | Parse the ведомость as a change log (sheet → change text) |
| F0146 → F0150 (ОПЗ Том 1.2 Книга 1) | 596/614 pages identical. The ведомость page is added. p15–27 re-issued with a clean text layer (the original was mojibake) | Same |
| F0201 (ОВ1 изм. 4) | CAD layers «Изм. №1/2/4»; change permit 839-24; sheets 14/15 present twice | Page-level currency: when a sheet number repeats, prefer the copy with the newest revision layer or row |
| ИД vs RD | АОСР №1/ОВ (07.04.2025) cites «РД-ОВ1 изм. 3» while изм. 4 is dated 11.08.2024. As-built plans F0197/F0199 carry `ОВ-Вентиляция-Изм. №5` (newer than the supplied RD) | Document-integrity candidates; ИД may be built on a different RD issue |

### 3.7 Differences on Тюменская that are not in the gold (and our policy)

The gold is «FINAL_GOLD_EXISTENCE» for three Перечень items and is not guaranteed exhaustive. Our system will see more than the gold. How we treat these matters for precision:

| Observed | Where | Policy |
|---|---|---|
| Local exhausts added in room 141 (the В2.7–2.9 group moved from 140) | RD F0201 p18 | Do not emit a separate finding for **additions or relocations**; attach them to the source room's finding as context |
| ИД ≠ RD изм. 4 in rooms 114, 115, 154, 166 (изм. 5 clouds) | ИД F0197, F0199 | Unknown label on train. Emit only if a matrix trigger fires in the violating direction; on train, count them as «unlabeled», neither FP nor TP |
| АОСР cites изм. 3, and a cipher typo | F0196 | Document-integrity suspicion, not a matrix check |
| Unit parameters of П17.1/П17.2 vs П17 (IOS4-079 values) | F0201 p173–595 printouts vs the PD ОВ table | Use as `pd_value/rd_value` enrichment if extracted, not as a separate check |

### 3.8 Development fixtures (`95_tyumen_dev_fixtures.json`)

- `expected_submission`: the exact `submission_schema.json` object for OBJ-TYUMENSKAYA-5-GOLD-SEED (10 checks), used by `inspector-score` as the must-pass case.
- `page_facts`: for the 6 gold pages plus F0201 p20/p32 and F0171 p11/p136: stamp vs gold sheet, format, class, anchors (room-label coordinates, PD tag sets, RD OCR tag sets, revision-cloud bbox, QR).
- `markup_zone_bboxes`: the 12 registered zones (§3.3).
- `recognition_tests` RT-01…RT-10. These are CI unit tests for B02: sheet sequence, layer-isolated OCR tokens in zone 012 and near 140–198, the revision cloud over 270/272, the ПЗ warm-floor sentence, absence over OCR, QR identity F0198 = F0202 p17, BROKEN_ENCODING on F0146, the PD supply-unit set of 012, and АОСР п.2/п.4 parsing.
- `unlabeled_known_differences` and `gold_quirks`: §3.7 and §3.2 in machine form.

Acceptance on this object (CI gate, run on every change to B02/B04/B07):
1. All 10 keys (code, location) are found with VIOLATION_PRESENT.
2. Evidence for each key contains the gold PD and RD pages, following the group-anchor rule.
3. The critical-miss gate never trips.
4. Values and statuses follow the 93 §3.5 templates.
5. At most 5 extra VIOLATION_PRESENT keys on the object. This is reported as a volume metric, not as precision.
6. RT-01…RT-10 are green.

---

## 4. Part B — OBJ-NOVOSLOBODSKAYA

### 4.1 Contents

| Stage | Documents | Recognition profile |
|---|---|---|
| ПД (НВС-2025/03, ООО «Архитектурный диалог с мегаполисом») | 36 volumes: СП, ПЗ, ИРД (215 p), ПЗУ, АР (48), КР1 «Ограждающие конструкции котлована и распорная система» (29), КР2 (139), КР3 (209, calculations), ТХ1–4, ПОС1 (82), ПОС2 «Строительное водопонижение» (47), ООС, ТР, ПЭ, МОПБ, ИОС1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3, 5.1–5.6, ТБЭ, ОДИ, ДИ, АТЗ | 88 % text layer. Drawings A1/A2 with text (86 partial-outline pages). ИРД and certificate scans at 200 dpi. F0107 has 45 SCAD printout pages with a broken encoding. No CAD revision layers |
| РД | КЖ1.1.1 фундаментная плита, 1.1.2 вертикальные −3, 1.1.3 плита −3, 1.1.4 вертикальные −2, 1.1.5 плита −2, 1.1.8 лестницы (Изм.1) — ООО «Стандартпроект», НСЛ-17-02/2026-1,2; СВГ (17_ПД/25-СГ, ООО «Велес»); РС распорная система изм. 1; ВП (17_ПД-25-КР «Усиление фундаментов здания … ул. Новослободская, д. 19, стр. 1», a neighbouring building); 2451.Р.ДР защита подземной части от подтопления | 93 % text layer, drawings A1/A2. `qr.sgnl.pro` QR on 8 files; OCGs on 7 |
| ИД | 99 АОСР (80 on disk): СВГ захватки 1–18 (АЗ армирование, БЗ бетонирование, РЗ ×16 missing), БСС (А/Н), форшахта (АФ/БФ/РФ, 3 missing, ДФШ, СШ), обвязочный пояс (АОП/БОП), технологическая дорога (БТ, ДТД), водопонижение (ВП/П/СБ ×19) | Page 1–2 is an electronic act (text; signature slots `CUSTOMER$uuid`, `GENERAL_CONTRACTOR$uuid`, `BUILD_CONTROL$…`), then the реестр приложений (text), исполнительные схемы (vector A3 with text and a raster insert, ООО «МегаСтрой»), then scanned паспорта/документы о качестве, сертификаты, протоколы ВИК/УЗК. Each scan is followed by a Letter-size «КОПИЯ ВЕРНА» stamp page |

OCR sample (80 random scan pages across both objects, `extras.ocr_sample_summary`):

| Subset | Pages | Median mean-confidence | Min | Lines < 0.8 (median) | s/page (median, 4 threads, loaded machine) | Kinds seen |
|---|---|---|---|---|---|---|
| Новослободская ИД | 40 | 0.930 | 0.823 | 9.7 % | 2.2 | паспорт/документ о качестве 18, договор 7, сертификат 7, протокол 6 |
| Новослободская ПД | 10 | 0.929 | 0.850 | 9.8 % | 1.7 | сертификаты, экспертиза |
| Тюменская ПД | 24 | 0.946 | 0.801 | 7.8 % | 2.0 | ТУ, сертификаты, изыскания, a 120-dpi ИРД scan at 0.96–0.97 |
| Тюменская RD/ИД | 6 | 0.908 | 0.834 | 16.9 % | 1.0 | approval sheets, drawings |

These are confidence proxies, not character accuracy. The labelled OCR set (U-24) still has to measure CA/EM.

### 4.2 АОСР as structured data

- **Parsing.** All 80 АОСР parse from the text layer: act №, works, design docs, materials, п.4 attachments, dates, norms and next works (80/80 each).
- **Design references (п.2).** «17_ПД/25-СВГ» 61 times, «НВС-2025/03-КР1» 42 times, «НВС-2025/03-ПОС2» 19 times. The PD is cited directly, and the RD cipher in the СВГ title block is «17_ПД/25-СГ». Normalisation is needed (R14).
- **Date and sequence rules.** For all 18 захватки, АЗ ends before БЗ starts: 0 violations. Start ≤ end holds in all 80 acts. These are ID-internal logical rules, good as negative controls.
- **Materials.** Materials sit mostly in the реестр page. The concrete strings are machine-readable. Example: «Документ о качестве бетонной смеси заданного качества партии БСТ В15 П4 F150(I) W8 №18-000002143 от 14.02.2026 ООО "Бетолюкс"».

### 4.3 Matrix parameters with PD↔RD↔ID pairs in Новослободская

| Code | Parameter | PD source (file p) | RD source | ID source | Pair status | Example values |
|---|---|---|---|---|---|---|
| KR-055 | Класс бетона | КР1 F0105 p13/17/24; КР2 F0106 p49 | СВГ F0137 p1; КЖ1.1.1–1.1.5 (B10 подготовка, B40 плиты, B60 стены); КЖ1.1.8 B30 F150 W6 | АОСР реестры (F0004/F0005/F0014/F0069 p5–7) + scanned паспорта | **FULL** for pit elements; PD↔RD for the frame | Сваи БСС армированные В25 П4 F200 W8 everywhere; «пустышки»: PD p17 F200 W8, PD p24 F100 W6, RD F200 W8, ИД F150 W8 |
| KR-057 | Класс арматуры | КР1 p13–14, p29 | СВГ p1…; КЖ (А500С dominant, А240) | АОСР АЗ/АФ/АОП + сертификаты (Северсталь, scans) | FULL | А500С / А240 vs «А240С» (normalisation) |
| KR-056 | Сталь проката | КР1 (трубы ∅630×7) | РС F0145, СВГ (Ст20, С235) | — | PD↔RD | Ст20 / С235 |
| KR-058 | Толщина фундаментной плиты | КР2 F0106 p53: 1000/1200 мм | КЖ1.1.1 F0140 p3: 1200/1500 мм, низ −14.950/−15.250 | — | PD↔RD | Increase: NO_VIOLATION under the «уменьшение» trigger |
| KR-059 | Толщина перекрытий | КР2 p52–53: −2/−1 floors 250 мм, капители 500 | КЖ1.1.3/1.1.5 p3: 250 мм, капители 500 | — | PD↔RD | Equal |
| KR-060/061/062 | Пилоны, стены, арматура пилонов | КР2 (стены 200–300, «пилоны… В60») | КЖ1.1.2 / 1.1.4 | — | PD↔RD | To extract (drawings, text layer) |
| KR-061 (СВГ as a retaining wall; mapping debatable) | Толщина стены | КР1 p13/17: 600 мм; ПОС1 F0112 p23 | СВГ p1: 600 мм | Исполнительные схемы захваток (vector) | FULL | 600 / 600 |
| KR-054 | Оси | КР/АР | КЖ, СВГ plans | Исполнительные схемы («в/о 4-2.8/А-Х1»), most «РЗ» acts missing | RD↔ID | Partial until re-extract |
| KR-067 | Ведомости расхода | КР1 p24 (551,9 м³ В25…) | СВГ «Ведомость расхода материалов» | — | PD↔RD | Volumes |
| PZ-009 | Отметка 0.000 | ПЗ F0101 p13, АР, КР2, ПОС: 159,95 | СВГ p1–2, КЖ1.1.1 p4, РС p4: 159,95 | Схемы with absolute marks (159.45/134.50/159.50) | FULL | Consistent: NO_VIOLATION |
| SPZU-039 | Инженерная подготовка / дренаж, водопонижение | ПОС2 F0113; ПЗУ | ВП F0136, ДР F0138 | 19 АОСР ВП/П/СБ (wells С-1…С-5, П-1/П-2, ЭЦВ 6-4-70) | FULL | Well counts and pump models |
| POS-087 | Технологическая последовательность | ПОС1 p23 «в следующей последовательности» | СВГ p1 | АОСР dates and п.7 chain | FULL (logic) | No order violations found |
| POS-082 | Продолжительность этапов | ПОС1 calendar | — | АОСР dates | PD↔ID | Duration check possible |
| PZ-001…023, AR-*, PPM-*, ODI-*, IOS*, ZU-* | ТЭП, архитектура, пожарка… | ПД volumes | **none** | **none** | PD only | Expect RD_MISSING / ID_MISSING; PD-internal consistency only (e.g. ПЗ vs ПЗУ vs АР) |

So about 12 of 132 parameters can be compared across stages. The remaining ~120 exercise the MISSING_DOCUMENT and status logic, which is exactly what `normalized_value_and_status_accuracy` and `document_integrity_and_split_handling` will probe on Речников too (93 §1.4: Речников has no RD for ОВ, СС or ПБ).

### 4.4 Candidates and false-positive traps found during profiling (`95_novoslob_label_seed.json`)

| id | Code | Location | Why it matters |
|---|---|---|---|
| NS-C01…C03 | KR-055 / FREE | БСС-1н «пустышки» (3 АОСР) | ИД F150 W8 (one batch W6) vs RD F200 W8, with the PD self-contradictory. The strength class В15 is unchanged, so the literal KR-055 trigger is **not** met. This is a routing test: KR-055 NO_VIOLATION vs a FREE-STRUCTURE finding vs CLARIFICATION |
| NS-C04, C05, C06 | KR-055 | Армированные сваи, СВГ, форшахта | Expected NO_VIOLATION (the ИД meets or exceeds the requirement). Negative controls with evidence on all three stages |
| NS-C07 | PZ-009 | Здание | NO_VIOLATION across 6 documents |
| NS-C08, C11 | KR-061, KR-057 | СВГ, армирование | NO_VIOLATION; «А240С» ≡ «А240» normalisation |
| NS-C09 | Elevations | Захватка №8 | Expert call: cage top 159.45 and concrete to 159.50 vs design top 158.90 is normal over-pour. A trap for naive elevation diffs |
| NS-C10 | PZ-001 | Здание | 1225,8 (ПЗ, of which 767,0 is the ground part) vs 767,0* (ПЗУ): **component matching** needed |
| NS-C14 | KR-058 | Фундаментная плита | RD thicker than PD: the **directional trigger** gives NO_VIOLATION |
| NS-C12 | Integrity | ТХ3 F0110 p28 | Ciphers of another project («СГ-2404-63-П-ИОС5.5.x»): a suspicion only |
| NS-C13 | Integrity | 19 АОСР | Missing locally: a data problem, not MISSING_DOCUMENT |

---

## 5. Part C — Development and validation protocol

### 5.1 Data roles (consistent with 93 §4.8–4.9)

| Set | Content | Labels | Allowed use | Forbidden |
|---|---|---|---|---|
| **T-GOLD** | Тюменская, 10 checks / 4 groups | Organizer gold (positives only) | Must-pass acceptance (§3.8); mapping and anchor-rule seeding (declared as «learned from T»); recognition unit tests RT-01…10 | Reporting T scores as generalisation; tuning thresholds on T alone |
| **T-REST** | Everything else our system emits on Тюменская | Unknown | Volume metric (VIOLATION_PRESENT keys per 1,000 pages); spot review of 10–15 extras by the user (they go into N-style labels as «T-self») | Treating extras as FP in precision |
| **N-DEV** | Новослободская, all outputs | None | Free iteration: extraction coverage, crash-free runs, timing, status logic, АОСР linking | — |
| **N-GOLD (self)** | ~110 labelled items from Новослободская (§5.3) | Team labels, badged «разметка команды» | Precision / FPR estimate, status accuracy, value templates; **2-fold by discipline** (fold A: КР/КЖ/СВГ; fold B: ПОС/ВП/ДР/integrity), tune on A and report B, then swap | Relabelling after seeing the tuned outputs (labels are frozen with a hash) |
| **P-PILOT** | 24-page «Комплект предметной разметки» (8 objects) + the 6-page markup | Organizer candidates (v1.1 vintage) | Recognition fixtures (explications, 200-dpi scan with handwriting, outlined-text page), demo | End-to-end scoring (no registry, not in package v2.0) |
| **S-SYN** | Synthetic perturbations of T and N copies, badged | Generated | Unit tests of detectors: delete the warm-floor sentence from a PD copy → expect NO_VIOLATION; change «В25» to «В20» in an RD copy → KR-055 violation; drop an RD sheet → RD_MISSING | Mixing into N-GOLD metrics |
| **R-HIDDEN** | Речников | Withheld | One run with the frozen config; content-agnostic crash fixes only (93 §4.9) | Any threshold, dictionary, prompt or anchor change after seeing R outputs; reading R documents |

### 5.2 Loop

1. **Unit level (daily CI).** RT-01…RT-10 plus B02 golden tests on P-PILOT pages. Target: 100 % green.
2. **Object level on T.** `inspector-batch` → `inspector-score` with the scorer defaults from 93 §2.2. Target: 10/10 keys, localisation 1.0 under the anchor rule, gate OK. Record the extras volume.
3. **N-DEV.** A full run on each checkpoint build. Watch the MISSING_DOCUMENT matrix: 132 parameters × stage availability must reproduce the §4.3 table.
4. **Label freeze (after CP1).** The user labels N-GOLD in the verification UI (§5.3). Freeze the `labels_hash`.
5. **Tuning.** Tune the emission thresholds, the hedge rule, FREE-* limits and value templates with the 2-fold protocol on N-GOLD, plus the must-pass T. Report fold-held-out numbers with 95 % CIs (Wilson).
6. **Freeze.** Record `config_hash` and the git tag `hidden-run-freeze`. Run R once. Produce `OBJ-RECHNIKOV-7-7.json` and the protocol.

### 5.3 Self-labelled internal check on Новослободская: size and effort

| Option | Items | Composition | User time | What it buys |
|---|---|---|---|---|
| Minimum | 30 | 14 seeds (§4.4) + 16 system candidates | 35–45 min | Sanity check of routing, directional triggers and FP traps; no usable precision estimate |
| **Recommended** | **~110** | 14 seeds + ~40 system VIOLATION_PRESENT/ambiguous + 30 random NO_VIOLATION + 20 MISSING_DOCUMENT/COMPARISON_IMPOSSIBLE + 6 FREE/integrity | **≈ 1.75–2 h** (≈ 60 s per item in the side-by-side viewer with pre-cropped PD/RD/ID zones) + 20 min for a teammate to double-label 15 % (agreement check) + ≈ 30 min domain consult for the КР/F-W items | Precision ± ~9 pp (95 % CI at n≈50 positives), FPR on negatives, status accuracy, value-template accuracy |
| Extended | ~200 | + all АОСР-level material checks | ≈ 3.5 h | Only if the recommended set shows unstable numbers |

Label schema: `violation_label` (4 values) + `UNSURE`, `parameter_code` override, `location` override, correct evidence pages, and a comment. It is stored as `labels_novoslob_v1.jsonl` and badged. UNSURE items are excluded from metrics but listed.

### 5.4 Metrics tracked on train (mirroring the package weights)

- F1 on keys with VIOLATION_PRESENT (T: recall only; N-GOLD: P/R/F1).
- Exact file+page localisation (T: gold pages; N-GOLD: labelled pages).
- Value and status accuracy (templates of 93 §3.5).
- Document integrity checks (93 §2.6): excluded ids, stage per file, current revision, duplicate groups, missing-on-disk vs missing-document.
- Gate simulation.
- Extraction coverage per parameter: share of the ~12 pairable parameters where PD, RD and ID values were extracted.
- Recognition KPIs: OCR confidence distribution per page class, sheet-map accuracy (T: F0201/F0202 against the stamp OCR ground truth), QR decode rate, BROKEN_ENCODING recall.

### 5.5 Pilot objects mapping

| Pilot (earlier 9-object markup) | In train/hidden corpora? | Use |
|---|---|---|
| VENT-P01/P02/P03 (6-page «пояснения», АНО/150321) | **Yes: Тюменская = G-TR-001/002/003+004** | Gold. Routing changes: P02 → FREE-HEATING-001 (was M-077); P03 splits into MISSING_DESIGN_ELEMENT (140/142) and CONFIGURATION_MISMATCH (147/198/314) |
| ALT79B, UNDMS, IZM12, LOS3A, OKT103, POL16, DOO25, SOSH25, POL17 (24-page «Комплект») | No (no match in file names or train text; only incidental «МВД»/«Полярн» words) | P-PILOT: recognition fixtures (explication tables, OKT103 200-dpi scan with handwriting, IZM12 outlined-text page) and demo. Never in train metrics |

---

## 6. Plan changes

1. **B02 (recognition): add the CAD-layer toolkit.** It covers layer-isolated rendering for OCR, wall-layer masks for room polygons, `DUCT-*` system membership and revision-cloud extraction (R2–R4). This is the single biggest quality gain for RD drawings.
2. **B02: redefine BROKEN_ENCODING** with a mojibake/lexicon ratio, and add an optional per-font glyph remap (R1).
3. **B02/B01: title-block pipeline.** OCR the sheet, листов, шифр and change rows with sequence smoothing. Decode QR codes. Store `document_sheet_number` (stamp), `qr_doc_uuid` and `qr_page`. Detect duplicate sheets (R5, R7).
4. **B02: an element–room assertion extractor from PD text, with provable absence** (full text+OCR coverage flag) for MISSING_DESIGN_ELEMENT (G-TR-002 pattern).
5. **B02/B04: the per-room equipment multiset comparator.** Tag grammar, homoglyph folding, a closed-vocabulary spotter and split/merge detection. Compare counts and composition, not tag identity (G-TR-001/003/004 pattern).
6. **B01: binder segmentation and per-page stage** for RD_ID_MIXED. Parse the «Сопоставительная ведомость» and «КОРРЕКТИРОВКА N» markers. Hash pages to diff revisions. Mark the page-level currency of duplicate sheets.
7. **B01: a STAMP_PAGE class** («КОПИЯ ВЕРНА» separators); **missing-on-disk ≠ MISSING_DOCUMENT**; sha256 resolution.
8. **B02: the АОСР and реестр parser** (R13), with concrete strings split into class, П, F and W, and rebar classes normalised.
9. **B03/B04: enforce directional triggers** («понижение», «уменьшение»). Keep F/W marks as separate attributes, and route their reductions to FREE-STRUCTURE (pending Q4). Match components for ТЭП (наземная vs общая).
10. **B04/B07: the addition/relocation policy.** Do not emit additions; emit ИД≠РД only with a violating direction.
11. **B06/B10: adopt the §5 protocol,** with `95_tyumen_dev_fixtures.json` as the CI gate, N-GOLD labelling after CP1 and the freeze before Речников.
12. **B08: in the evidence viewer, add a layer toggle and revision-cloud highlight.** It is also a strong demo moment: the RD cloud sits exactly over the gold rooms.
13. **B10: re-extract the 19 missing files** before N-GOLD labelling.
14. **90 §3.12: update pilot routing** for VENT-P02 and VENT-P03 as in §5.5.

---

## 7. Questions for the user

| # | Question | Options | Recommendation | Why it matters |
|---|---|---|---|---|
| Q1 | Can you give us the original organizer archive (or re-download it) so we can recover the 19 missing Новослободская АОСР (РЗ ×16, РФ ×3)? | a) the original zip → we re-extract onto a case-sensitive disk image with cp866 names; b) proceed without them | **a** | KR-054 axes and the ID coverage of the СВГ захватки live mostly in the «РЗ» acts; labelling without them biases N-GOLD |
| Q2 | Who labels N-GOLD, and how much? | 30 items (~40 min) / **~110 items (~2 h) + 15 % double-label by a teammate** / 200 items (~3.5 h) | ~110 items, right after the CP1 build, in our verification UI | It is the only source of precision and FPR numbers before the hidden run |
| Q3 | Confirm the precision policy for differences the gold does not list | a) report additions/relocations and ИД≠РД changes too; **b) do not emit additions; emit ИД≠РД only when a trigger fires in the violating direction** | b | F1 carries 60 points; on Тюменская the extras would be counted as FP if the hidden gold is built like the train gold |
| Q4 | Domain call: concrete delivered with a lower F/W mark than the RD requires (F150 vs F200) but the same strength class | a) KR-055 violation; **b) FREE-STRUCTURE finding (Существенное, требует утверждения)**; c) ignore | b, and only with PD+RD+ID evidence | The KR-055 trigger text is about «класс прочности»; misrouting a critical code risks FP on a critical parameter |
| Q5 | Keep the 9 pilot objects out of the train metrics (recognition fixtures and demo only)? | yes / no | Yes | They are v1.1-vintage, without registries, and not in package v2.0 |

---

## 8. Install needs

Nothing new is needed for this analysis. For the build:
- `rapidocr` ≥ 3.9 + `onnxruntime` ≥ 1.20 + the PP-OCRv5 cyrillic models in the **main** ML environment. Today they are only in the scratch `ocrvenv`. They are used for outlined-text OCR, scans and title blocks.
- `opencv-python-headless` ≥ 5.0: QR decoding (`QRCodeDetector`), SIFT registration of the markup crops, and the raster room masks.
- Already present: `pymupdf` 1.28.2 (OCG/`layer_ui_configs`, `get_drawings()['layer']`), `py7zr` and `rarfile` (Речников archives), Homebrew `tesseract` (OSD fallback).
- For Q1: no new tools. Python `zipfile` with cp866 names, or `hdiutil create -fs "Case-sensitive APFS"`, is enough.

---

## Appendix A — Key per-file facts (Тюменская RD/ИД)

| file | pages | classes | CAD rev. layers | QR | codes / refs |
|---|---|---|---|---|---|
| F0195 АОСР №1-ОВ2.1 | 2 | text | — | — | п.2 «АНО/150321/1-РД-ОВ2.1 - изм. 3»; п.4 «Исполнительные чертежи №АНО/150321/1-РД-ОВ2.1, листы 1-36 от 20.12.2024»; works 20.12.2023–20.12.2024 |
| F0196 АОСР №1/ОВ | 3 | text | — | — | п.2 «…РД-ОВ1 - изм. 3»; п.4 «АНО1301211-Р-ОВ1 от 09.01.2025»; works 20.12.2024–07.04.2025 |
| F0197 ИЧ план 1 эт. | 1 (A0) | vector+outlined | Изм. №5 | exon a95715d1…/19 | differs from F0201 p18 (fewer duct paths, no `ОВ-Воздухообмены`) |
| F0198 ИЧ план 2 эт. отопл. | 1 (A0) | vector+outlined | Изм. №3 | exon 87cc1a16…/17 | **identical** to F0202 p17 (817 words, 164,576 paths) |
| F0199 ИЧ план 3 эт. | 1 (A0) | vector+outlined | Изм. №5 | exon a95715d1…/21 | differs from F0201 p20 |
| F0200 ИЧ план подвала | 1 (A0) | vector+outlined | — | exon a95715d1…/18 | differs from F0201 p17 (3,271 vs 10,041 `DUCT-Приток` paths) |
| F0201 РД ОВ1 изм.4 | 676 | 517 text, 147 outlined, 4 scan | Изм. №1/2/4, Спека-Изм.1–3 | exon 3eb2aa9d…/p | — |
| F0202 РД ОВ2.1 изм.3 | 36 | 14 text, 18 outlined, 4 scan | Отопление-Изм. №1/№3, Изм.1–3 | exon 87cc1a16…/p | — |
| F0203 РД ВВ изм.3 | 45 | — | — | exon 84969893…/p | stamp row «1 Зам. 583-23» |
| F0204 РД ВК изм.2 | 71 | 1 broken encoding | — | — | — |

## Appendix B — Where the numbers come from

- Profile: `corpus_train_profile.json` (`files[*]`, `summary_by_object_stage`, `extras`).
- Evidence anchors and zones: `95_tyumen_dev_fixtures.json`.
- Seed candidates: `95_novoslob_label_seed.json`.
- Scratch scripts (reproducible, not part of the product): `…/scratchpad/c95/{profile2.py, build_json.py, oc_ocr.py, tb_ocr.py, qr.py, qr_scan.py, register2.py, aosr_parse.py, revdiff.py, f0202_ocr.py, ocr_sample.py}`.
