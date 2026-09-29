# B96 — Recognition on the real corpora: benchmark, measurements, hardened design and work plan

**Block:** Module 1 part B (recognition: text layer, OCR, tables, title blocks, NLP anchors, DWG/DOCX/archives). It updates `02_extraction_ocr_nlp_cv.md` and the title-block part of `01_ingestion_registry_revisions.md`. Where this report disagrees with 02 on a measured number, this report wins: 02 measured 5 pilot crops, this report measures 45 real pages.
**Date:** 2026-09-27. **Phase:** analysis. No application code was written; all probes are throw-away scripts in the session scratchpad (`recog/`, `dwg/`).
**Read with:** `93_scoring_contract_appendix2.md` (what is scored, evidence rules, the hidden-test integrity rules §4.9) and `95_corpus_train_objects.md` (corpus facts, the Тюменская gold anatomy, recognition requirements R1–R15). This report measures what 95 describes and does not repeat its corpus profile.
**Benchmark definition:** `docs/analysis/recognition_benchmark.json`. It holds 39 pages, their regions, the GT method per page, the key fields and the hand-checked transcriptions (6 pages, 7,510 characters).

Machine: Apple M2 Max (8P + 4E cores, 32 GB), CPU only unless stated. Other agents were running at the same time: load average was 3–45 during the measurements. Wall-clock numbers are therefore pessimistic, and I report CPU-seconds wherever the comparison matters.

---

## 0. Executive summary

1. **The out-of-the-box OCR is much worse on real pages than 02 assumed, and three cheap fixes bring it above the ТЗ threshold.**
   - The default RapidOCR pipeline (PP-OCRv5 mobile det + text-line classifier + cyrillic rec) scores **0.870** character accuracy on the vector-rendered benchmark: 30 regions, 32,263 characters, text-layer GT.
   - Most of the loss comes from a single component, the text-line orientation classifier. It flips long lines, and the recogniser then returns blanks. On one dense АОСР page, removing it moves accuracy from 0.780 to 0.996.
   - The hardened pipeline ("v2") changes three things. It drops the classifier, which is replaced by a score-driven 180° retry. It runs detection on overlapping tiles of 3,200 px (400 px overlap) and merges lines cut at the tile seams. It swaps in the newer **PP-OCRv6-small multilingual detector** with the PP-OCRv5 cyrillic recogniser. Result: **0.967 [0.952–0.978]**, or **0.972 at 200 dpi**.
   - On the same set Tesseract 5.5 `rus` scores 0.79–0.80.
2. **Real scans pass as well.** Six hand-transcribed pages (7,316 scored characters) include a seal-covered form, a 90°-rotated protocol, a skewed 150-dpi page and an outlined-text page. With v2, PP-OCRv6-small and native resolution:
   - **0.968 [0.955–0.983]** strict, 0.976 with homoglyph folding, about 11 CPU-s per page;
   - the medium detector reaches 0.973 at 2.5× the cost;
   - Tesseract reaches 0.898.
   - Key-field exact match on these scans (dates, act and protocol numbers, concrete classes, strengths) is **0.905 strict and 0.952 relaxed** (n = 42). Tesseract gets 0.738.
3. **Document codes need a dedicated post-corrector.** The ТЗ key field «шифр» fails raw: PP-OCR reads Cyrillic capitals as Latin letters or digits, so «АНО/150321/1-РД-ОВ1» comes back as «AHO/150321/1-PД-OB1». Raw exact match is 0.09–0.18.
   - A deterministic, code-aware corrector gets **0.91** (10/11) on the vector title blocks and **6/6** on the outlined title blocks of the gold RD sheets. It maps Latin look-alikes to Cyrillic in code segments and turns 0/3 into О/З between letters, with a discipline dictionary.
   - A registry prior fixes the rest. The manifest file name encodes the code.
4. **"Vector with a text layer" is not a sufficient reason to skip OCR.** On the gold RD ventilation plans F0201 p17/p18 (and F0202 p17), **65 % of the text lines are drawn as curves**: system tags ВЕ1, В22, ПЕ/ВЕ, grilles «АМР-К 350x300», flows «L 340», duct sizes «Ø160». The whole title block is curves as well. This is exactly the IOS4-078/079 evidence.
   - The page router must work per word, not per page. Run a detection pass on every drawing sheet, compare the boxes with the text layer, and OCR the uncovered boxes. Layer-isolated renders make this cleaner (95 R2).
5. **Tables need purpose-built parsers.** PyMuPDF `find_tables()` fails on the real sheets:
   - four side-by-side explications merge into a 57×14 grid, and with per-table clips the «Площадь» column is lost in 2 of 4 tables;
   - the ТЭП page returns the whole page frame as a 37×27 table.
   - A header-anchored parser (about 100 lines of prototype code) extracted 116 rows from the four explications of F0201 p18 in 3.8 s. The visually checked table was **32/32 rows exact**.
   - Area-sum checks against the «ИТОГО» rows also surfaced a real inconsistency in the document itself: the «в том числе» sub-zone of room 102 is counted twice in the group total.
6. **Scans should be read at native resolution, not upsampled.** Scans read at 150–300 dpi score within 0.6 pp of the 300-dpi upsample, at half the CPU. Deskew adds nothing, because the rotated-rectangle crops already absorb skew up to about 3.5°. Vector outlines read as well at 200 dpi as at 300 dpi (0.972 vs 0.967) at 0.75× the CPU.
   - Page-level rotation detection is required: 32 % of the sampled Речников pages carry /Rotate 90/270, and some scans are rotated inside the image. Given the wrong orientation, Tesseract scores 0.17 on B04.
7. **DWG: use the PDF twin; DWG is optional enrichment.** Of the 366 DWG whose header was read (5 loose + zip members), 300 are AC1027 (2013), 64 AC1032 (2018), 1 AC1024, 4 AC1021 and 1 AC1015; the 7z/rar members were not header-checked. Every archive has a PDF twin (93 §1.4); the two twins checked (F0330 АР1, F0341 ОК) have full text layers, and evidence must cite a manifest PDF page anyway.
   - For enrichment, **`ezdwg` (MIT, `pip install`, Rust core; R13–R2018) read the AC1024, AC1027 and AC1032 samples without any converter**. It returned MTEXT (the explication with «20,5 м²» and room ids), DIMENSION with `actual_measurement`, INSERT blocks and layers in 2–15 s per sheet. Neither LibreDWG nor ODA is needed.
8. **Scale.** The hidden object has about 8.2k pages that need full OCR (ИД scans) plus about 1.5k drawing sheets that need the coverage check.
   - At the measured 5–17 CPU-s per page, one frozen batch run takes **about 2–4 h** on the Mac, or less with CoreML detection (2× faster detector on the host) and page triage.
   - Big binders are cheap to open: the 658 MB PDF opens in 0.01 s, triage costs 2 ms per page and memory grows by 95 MB.
   - §11 (100 pages ≤ 3 min) holds on an idle machine but not under the load we observed. The demo must run on an idle host with CoreML.
9. **Semantic anchors work, and they find labels, not values.** multilingual-e5-small embeds 107,690 real text lines at 817 lines/s, and a per-parameter query takes 26 ms.
   - The top hits are the right *row labels* («Общая площадь здания, в т.ч.:», «Высота здания», «Степень огнестойкости здания – I;»).
   - The values sit in other cells, however, so fewer than 60 % of the top-10 lines contain a value.
   - The matrix regexes find values for 29 of the 38 tier-A parameters, but they also match normative limits («не более 20 000 кв.м»), title-block lines («Школа на 600 мест», 1,020×) and panel names («ЩСКЗ»).
   - Extraction must therefore be table- and geometry-first, with role filtering.
10. **The work plan (§14)** has 15 recognition tasks, ranked by score impact. Each has an acceptance test on this benchmark. P0 covers the OCR core, the router, orientation, the code corrector, the title-block reader, the room index and the batch runner.

---

## 1. Benchmark: pages, ground truth and metric

### 1.1 Page set (39 pages; full list with sha256 and regions in `recognition_benchmark.json`)

| Group | Pages | What they cover | GT |
|---|---|---|---|
| A: vector with text layer (17) | Тюменская gold pages F0171 p88/p99/p104 (PD ОВ) and F0201 p17/p18, F0202 p17 (RD ОВ). F0156 p27 (PD АР plan + explication, /Rotate 270). F0104 p22 (Новослободская АР). ТЭП F0101 p9 and F0154 p13. Spec ГОСТ 21.110 F0171 p105. RD общие данные F0201 p6. КЖ title page with «В производство работ» F0140 p2. Electronic АОСР F0001 p1. Исполнительная схема F0012 p3. КЖ sheet F0140 p5. ПЗ text F0106 p20 | Title blocks, dense tables, plan labels, rotated sheets, A4 text | **Text layer.** Page rendered at 300 (and 200) dpi and OCR'd. GT = visible text-layer glyphs (texttrace, render mode ≠ 3, not white) inside the region. A4/A3 pages are scored whole. Larger sheets use 3 automatic regions: title block (bottom-right 200×70 mm), densest 25 %×25 % window, and the window with the most room-number-like tokens. Regions with < 50 GT characters are excluded (outlined title blocks) |
| B: real scans (8) | F0001 p5 документ о качестве бетонной смеси (299 dpi, seal, QR); F0001 p15 протокол испытаний (150 dpi); F0012 p21 протокол (/Rotate 270); **F0004 p25 content rotated 90° inside the image**; F0001 p3 colour исполнительная схема; **F0201 p7 анкета абонента (424 dpi, two seals)**; **F0146 p40 skewed 150-dpi text**; F0202 p5 RD cover with approval stamps | ИД attachments, rotation, skew, seals, low DPI | **Hand transcription** (6 pages, §1.2) |
| C: hybrid (4) | F0083 p5 scan under a visible garbage scanner layer; F0081 p16 scan with an invisible OCR layer; F0116 p5 hybrid PD text; F0146 p200 colour scanned plan | Routing and layer-trust tests | Qualitative |
| D: text as curves (4) | F0201 p15 (spec A1, fully outlined); F0202 p19 (axonometry A0); **F0107 p4 (A4 text page as curves)**; F0138 p3 (RD sheet) | Outlined text | Hand transcription (D03) and title-block key fields (D01, D02, D04) |
| R: Речников (6) | F0232 p1/p250 (658 MB binder), F0205 p10, F0253 p20, F0341 p1 (PDF twin of a DWG), F0240 p100 | Format and speed only | **None.** No labels and no tuning (93 §4.9) |

### 1.2 How the hand ground truth was made and checked

- **Prefill.** Each scan page was OCR'd with the v2 pipeline, which gives lines, polygons and text.
- **Review.** The page was rendered at 150–220 dpi in 3–5 horizontal bands. Each band was viewed and **every prefill line was adjudicated** as verified, corrected or excluded; the builder script refuses a page with an unadjudicated line. Missing lines were added with a hand-set bbox. D03 and B07 were typed from scratch.
- **Excluded zones.** Seals, rectangular ink stamps, QR codes, signatures and a page-number overlay are recorded (19 zones) and excluded from the character metric. This follows the ТЗ: «рукописные и заранее размеченные нечитаемые зоны не включаются в OCR-метрику».
- **Homoglyph convention.**
  - Cyrillic for class and certificate letters («В15», «РОСС», «Д-RU.РА01.В»).
  - Latin where the object is Latin: «F(I)150W6», «Matest C040PN132», «HW-10KGV», «IT-полигон».
  - The strict metric keeps this distinction. The relaxed metric folds it.
- **Status.** This GT was made by the analysis agent, not by a human. It is good enough to rank engines, but it needs **one human re-check pass of about 40 minutes** before any number is quoted to the jury as acceptance evidence (§15, Q3).

| GT page | Content | Scored chars | Excluded zones |
|---|---|---|---|
| B01 F0001 p5 | Документ о качестве бетонной смеси, 299 dpi colour | 1,206 | blue rect stamp ×2, round seal over the second address block, QR, cert logo |
| B02 F0001 p15 | Протокол испытаний, 150 dpi landscape, ruled table | 1,861 | seal+signature, logo, signature |
| B04 F0004 p25 | Протокол, **content rotated 90°**, 200 dpi | 1,967 | seal, logo, signature |
| B06 F0201 p7 | Анкета абонента (heat loads), 424 dpi, /Rotate 270 | 823 | 2 seals, 2 signatures, QR |
| B07 F0146 p40 | ИРД text, 150 dpi, **1.2° skew**, justified | 769 (region) | page-number overlay |
| D03 F0107 p4 | «Справка главного конструктора», **text as curves** | 690 | signature |

### 1.3 Metric

- **Character accuracy** = 1 − (edits + deletions) / N_gt, after Unicode NFC. Insertions (OCR text with no GT underneath) are reported separately.
  - *strict*: whitespace removed on both sides, because CAD text layers have unreliable spacing; no case or homoglyph folding.
  - *relaxed*: adds dash unification and Latin→Cyrillic look-alike folding.
  - *relaxed_ci*: also folds case. The ТЗ allows ignoring case only «для полей, где он не несёт смысла».
- **Alignment is reading-order and segmentation independent.**
  - For text-layer GT, every GT glyph is assigned to the OCR polygon that contains its centre.
  - For line GT, each GT line is compared, by semi-global edit distance, with the overlapping OCR lines or their same-row concatenation.
- **Lines with an OCR score below 0.5 count as not returned.**
- **Key-field exact match** requires the GT token to appear, with word boundaries, in the OCR text of the lines over the field box. Normalisation is NFC with whitespace collapsed; signs are never removed.
- **95 % CI** comes from a bootstrap over pages or regions, weighted by characters.

---

## 2. Corpus facts that drive recognition (measured on all 9,963 present train pages + a 1,775-page Речников sample)

| Fact | Numbers | Consequence |
|---|---|---|
| Page classes, Новослободская (4,100 pages) | VECTOR_TEXT 2,346 · SCAN 792 · near-blank «КОПИЯ ВЕРНА» stamp pages 749 · HYBRID 91 · OUTLINED 74 · scanner-OCR layer 11 | Stamp pages must be skipped as `STAMP_PAGE`, not OCR'd (95 R11) |
| Page classes, Тюменская (5,863 pages) | VECTOR_TEXT 4,421 · SCAN 841 · OUTLINED 403 · HYBRID 166 | Plus 10 % mojibake text layers (95 R1) |
| Page classes, Речников sample | ИД: 92 % SCAN (326/353). PD: 92 % VECTOR_TEXT. RD: 97 % VECTOR_TEXT. Scale by stage page counts: ИД 8,324, PD 6,799, RD 838 | **About 8.2k pages need full OCR**, almost all ИД binders |
| /Rotate | Train: 843 of 9,942 pages have Rotate ≠ 0 (426 × 270°, 358 × 90°, 59 × 180°). Речников sample: 565/1,775 (32 %); 271 of 375 scans have Rotate 270 | Render in displayed space; coordinates via `rotation_matrix`; plus content-rotation detection (§4.2) |
| Scan resolution | Train scans: P10/P25/P50/P75/P90 = 120/143/169/299/299 dpi. Речников scans mostly 300–424 dpi A3/A4 JPEG | Adaptive DPI (§5.1) |
| Outlined text inside "vector" drawings | Gold RD F0201 p17: 551 OCR lines, **359 (65 %) not in the text layer**. F0201 p18: 1,342 of 2,053 (65 %). PD gold pages F0171 p88/p104: 4–8 % | Word-level coverage routing (§4.1) |
| Title blocks drawn as curves | All Тюменская RD sheets checked (F0201 p15/p17/p18, F0202 p17/p19) and Новослободская F0138 p3: 0–1 text-layer characters in the stamp | Title-block OCR is mandatory (§7) |
| Garbage text layers | F0083 p5: visible scanner layer «АIМЕfАЛЛ /&::СЕРВИС… lVШТАЛЛОПРОКАТНЬIЙ» gives lexicon hit 0.74, mixed-script ratio 0.22 (OCR: «МЕТАЛЛСЕРВИС… МЕТАЛЛОПРОКАТНЫЙ»). F0081 p16: invisible layer of good quality (lexicon 0.89; our OCR 0.91). F0099: invisible layer is English garbage «glElsgsEEfuiii…» | Trust a scanner layer only after a lexicon and mixed-script check; OCR image pages anyway |
| Missing local files | 21 Новослободская manifest rows are not at their path (19 missing, 2 renamed); cause in 93 §1.3 | Resolve by sha256; benchmark avoids these files |

---

## 3. OCR results

### 3.1 Vector-rendered set (group A: 17 pages, 30 scored regions, 32,263 characters, text-layer GT, 300 dpi unless stated)

| Engine / pipeline | CA strict [95 % CI] | relaxed | relaxed_ci | title | dense | A4/A3 page | plan labels («rooms») | CPU-s per MP* |
|---|---|---|---|---|---|---|---|---|
| RapidOCR 3.9.2 default: PP-OCRv5 mobile det + cls + cyrillic rec | 0.870 [0.835–0.908] | 0.876 | 0.887 | 0.876 | 0.919 | 0.843 | 0.878 | 1.1 |
| v2 + PP-OCRv5 mobile det, cyrillic rec | 0.952 [0.933–0.969] | 0.959 | 0.969 | 0.965 | 0.942 | 0.962 | 0.924 | 1.6 |
| v2 + PP-OCRv5 mobile det, **eslav** rec | 0.944 [0.922–0.962] | 0.952 | 0.963 | 0.934 | 0.925 | 0.960 | 0.921 | 1.7 |
| v2 + PP-OCRv5 **server** det | 0.966 [0.949–0.977] | 0.972 | 0.978 | 0.970 | 0.970 | 0.971 | 0.936 | 11.4 |
| **v2 + PP-OCRv6 small det (multi), cyrillic rec** | **0.967 [0.952–0.978]** | 0.972 | 0.976 | 0.960 | 0.976 | 0.970 | 0.944 | 1.7 |
| same at **200 dpi** | **0.972 [0.957–0.982]** | 0.977 | 0.980 | 0.966 | 0.980 | 0.975 | 0.950 | ×0.75 per page |
| v2 + PP-OCRv6 medium det | 0.969 [0.954–0.980] | 0.974 | 0.978 | 0.972 | 0.976 | 0.972 | 0.946 | 5.3 |
| Tesseract 5.5.2 `rus+eng` best, psm 3 | 0.793 [0.671–0.875] | 0.801 | 0.805 | 0.612 | 0.764 | 0.901 | 0.530 | 0.5 |
| Tesseract best, psm 11 | 0.804 [0.674–0.890] | 0.812 | 0.817 | 0.702 | 0.702 | 0.927 | 0.578 | 0.5 |

\* Process CPU with 3 ONNX threads; this includes thread spin, so single-thread cost is about 35 % lower (§10).

**Notes.**
- The PP-OCRv6 multilingual recogniser has no Cyrillic in its dictionary: 18,708 symbols, 0 Cyrillic. The v6 **detector** is the useful part.
- `eslav` is weaker than `cyrillic`, so the choice stays as in 02.
- Tesseract is competitive only on clean A4 text (0.90–0.93). It collapses on rotated sheets (A07 0.38–0.57) and on dense plan labels.
- The system Tesseract has only `eng` and `osd`. The `rus` model used here was downloaded into the scratchpad.

### 3.2 Real scans and outlined text (hand GT, 6 pages, 7,316 scored characters)

| Engine | Render | CA strict [95 % CI] | relaxed | relaxed_ci | CPU-s/page |
|---|---|---|---|---|---|
| **v2 + PP-OCRv6 small** | native (150–300 dpi) | **0.968 [0.955–0.983]** | 0.976 | 0.982 | 10.9 |
| v2 + PP-OCRv6 medium | native | 0.973 [0.962–0.986] | 0.981 | 0.987 | 27.6 |
| v2 + PP-OCRv5 mobile | native | 0.951 [0.928–0.966] | 0.960 | 0.968 | 10.0 |
| Tesseract best psm 3 (given the right orientation) | native | 0.898 [0.861–0.935] | 0.901 | 0.906 | 3.1 |
| Tesseract best psm 6 | native | 0.898 [0.845–0.940] | 0.902 | 0.906 | 4.0 |

Per page (v6-small / v6-medium / Tesseract psm 3):

| Page | v6-small | v6-medium | Tesseract psm 3 |
|---|---|---|---|
| B01 | 0.990 | 0.990 | 0.904 |
| B02 | 0.959 | 0.954 | 0.895 |
| B04 | 0.966 | 0.971 | 0.887 (0.17 with the wrong orientation) |
| B06 seals | **0.928** | **0.974** | 0.787 |
| B07 skew | 0.982 | 0.978 | 0.986 |
| D03 outlined | 0.994 | 0.991 | 0.959 |

The medium detector is worth its cost only on seal-heavy pages. It is the fallback when the mean line score of a page is low (§4.8).

### 3.3 Key fields (the ТЗ «Exact Match ≥ 0,90» fields)

| Field set | n | Raw EM strict / relaxed (PP-OCRv6 small) | After post-correction | Tesseract (raw) |
|---|---|---|---|---|
| Scan values: dates, act/protocol №, concrete class, strength, %, volume, heat load | 42 | **0.905 / 0.952** | — | 0.738 / 0.762 |
| Room and element numbers (3–4 digit tokens) in vector-rendered regions | 507 | 0.919 (v6-medium 0.933) | text layer when present = exact | 0.44 |
| Document codes (шифр) in vector-rendered title blocks | 11 | 0.09 / 0.36 (v5-mobile 0.18 / 0.55) | **0.91** (10/11) with the code corrector; the last one («ПЗ» read as «P3») needs the registry prior | 0.45 (0.55 after correction) |
| Outlined title blocks of RD sheets (F0201 p15/p17/p18, F0202 p17/p19, F0138 p3): шифр, стадия, лист, листов | 19 | 14/19 (all 5 misses are АНО codes) | **19/19** (codes 6/6, stages 6/6, sheets 6/6, листов 1/1) | — |

The two scan failures are mixed-script codes: the concrete mark «БСТ В15П4F(I)150W6» and the certificate «РОСС RU Д-RU.РА01.В.44924/25». Both need the same code corrector with a Latin/Cyrillic grammar per segment.

---

## 4. Failure modes found on real pages and their fixes (all measured)

| # | Failure | Where | Effect | Fix (in the v2 prototype unless marked) |
|---|---|---|---|---|
| 4.1 | **Text drawn as curves inside "vector" sheets** | Gold RD F0201 p17/p18, F0202 p17 | 65 % of the lines (system tags, flows, grilles, duct sizes) and the whole title block are missing from the text layer | Word-level coverage map: run detection on every drawing sheet at 200 dpi, keep text-layer words where they exist, and OCR the uncovered boxes. Layer-isolated render (95 R2) where OCGs exist. *Design, not yet prototyped as a router* |
| 4.2 | **Text-line classifier breaks long lines** (RapidOCR default `use_cls`) | Dense A4 АОСР F0001 p1 | CA 0.780 → **0.996** without it (v5 det). With the v6 det the damage disappears, but the risk remains | Drop the classifier. Use a **score-driven 180° retry** for vertical crops and lines scoring < 0.75. It also reads the upside-down «Всего радиаторы:» on F0202 p29 (95 R6). The newer PP-LCNet textline model failed to load in RapidOCR 3.9.2 and was not evaluated |
| 4.3 | **Page content rotated inside a scan** (/Rotate 0) | F0004 p25; Речников F0205 p299, F0228 p124–283 | Tesseract 0.17; PP-OCR 0.83 at 2× CPU (rescued only by the 180° retries) | Page orientation detector: share of vertical detection boxes on a 1,000–1,600 px thumbnail, then a mean rec-score probe of the 6–12 largest boxes read both ways. 6/6 correct (1.1–2.9 s) once its 90/270 sign bug was fixed; the bug was the cause of the 0.83. Tesseract OSD agreed on 6/6 (0.6 s; «Rotate: 270» for F0004) and serves as the tie-breaker |
| 4.4 | **Short vertical tokens misread** (single digits taller than wide get rotated by the cropper) | Column numbers of the rotated protocol B04 | 6→9, 7→L, 10→01 | A three-way reading (rot 90, rot 270, unrotated) for short "vertical" crops; best score wins |
| 4.5 | **Long, slightly curved lines on scans** | B02/B04 «Вывод: …» lines (page curvature) | Garbled output at score 0.57–0.77 | Flagged LOW_QUALITY by score. Rescue by **local re-detection**: split the band at word gaps into windows of about 10 line heights and re-detect per window, so boxes follow the local baseline. That fixed the B02 v6s «Вывод» line (score 0.97). Chunking without re-detection did not help, and chunking always cost 0.4 pp, so it runs only as a low-score fallback |
| 4.6 | **Cyrillic capitals read as Latin or digits in codes** | Every АНО/НВС шифр; «РД», «ОВ1», «ПЗУ» | Code EM 0.09–0.18 raw | Code-aware corrector (§7.2): 0.91; the rest via the registry prior |
| 4.7 | **Homoglyphs in running text** | «кв.м»→«KB.M», «сут»→«CYT», «в/с/и/на» in justified text → Latin | −0.5 to −1 pp strict | Relaxed metric for reporting. A lexicon post-fix for words with rec confidence < 0.8 (as in 02 §3.4.5); never applied to codes and numbers |
| 4.8 | **Seals over text** | B06 (two round seals over the approval block and the title) | 0.928 with v6-small; the title «АНКЕТА АБОНЕНТА…» next to a seal was not detected at all | Seal/stamp zone mask (HSV blue, from 02 §3.5) → zone excluded or LOW_QUALITY. **Medium-detector fallback** on pages whose mean line score is < 0.9 or that have a seal zone: 0.974 on B06 |
| 4.9 | **Detector instability with image size** | v5-mobile det on B01: 0.902 at 299 dpi vs 0.988 at 300 dpi; a bold paragraph missed in a 3,000-px tile and found in a 3,600-px render | Random line drops | The v6-small det was stable on the same cases (0.990/0.990). Keep tile size fixed (3,200/400) and render at a fixed DPI |
| 4.10 | **Garbage or occluded text layers** | F0083 p5, F0099, Тюменская mojibake (95 R1) | Silent garbage values | Lexicon hit < 0.8 or mixed-script tokens > 5 % → treat as no text layer |
| 4.11 | **Upsampling low-DPI scans** | B02, B04, B07 | 150/200 → 300 dpi: +0.6 / 0 / 0 pp for 1.5–2.1× CPU | Native resolution clamped to [150, 300] |
| 4.12 | **Skew** | B07 1.1°, B02 0.8° | Deskew changed CA by −0.4 / −0.2 pp | No deskew for PP-OCR. Keep it only for ruling-line table grids |
| 4.13 | **INT8 recogniser** (dynamic quantisation) | 5 pages | Rec 1.3–1.6× faster, but CA −0.3 … −3.3 pp (F0171 p105: 0.971 → 0.938) | Rejected as the default; emergency mode only |

---

## 5. Improvements that were tested (summary)

| Improvement | Result | Decision |
|---|---|---|
| Adaptive DPI (native for scans, 200 for vector outlines) | Same or better CA; −25 % CPU on vectors and −50 % on low-DPI scans | **Adopt** |
| Deskew | No gain for PP-OCR (§4.12) | Only for table grids and Tesseract |
| Table-cell OCR (crop cells, rec only) | Not needed for the ruled protocols: their numeric cells were read (key-field EM 0.905 includes merged vertical cells «13,9», «73», «11») | Keep for scanned tables with handwriting-filled cells only |
| Rotation detection | 6/6, including a 90° content rotation | **Adopt** (§4.3) |
| Text-layer-first, OCR only for image regions or uncovered boxes | Needed on RD sheets (65 % uncovered), not needed on PD schematics (4–8 %) | **Adopt** as word-level coverage routing |
| Detector choice | v6-small ≥ v5-server at 1/7 the cost; v6-medium +0.5 pp at 3× | v6-small default, v6-medium fallback |
| CoreML execution provider (macOS host) | Detector 1.05 → 0.52 s per 3,200² tile (4 threads) | **Adopt for the native batch run**; unavailable in Docker |

---

## 6. Tables

| Table | Tool | Result |
|---|---|---|
| 4 side-by-side explications, RD F0201 p18 (A0) | `find_tables(strategy="lines")` on the region | 6.6 s; one 57×14 "table" with merged columns; unusable |
| same | `find_tables` per caption clip | 3 of 4 tables found; the «Площадь» column lost in 2; first table missed |
| same | **Header-anchored parser.** Find the caption «Экспликация…» and the header «Наименование». Take the vertical rulings that cross the header row as column borders (номер / наименование / площадь / кат.). Horizontal rulings are row separators. Assign words to cells | 3.8 s, 4 tables, 116 rows (99 with room numbers). Visual check of table 1: **32/32 rows exact** (number, name incl. two-line names, area, category). A room numbered «10» for the «Зоны ожидания» sub-zone is printed that way in the source |
| Area-sum self-check (Σ rooms vs «ИТОГО») | on the parsed rows | 2 of 7 groups match. The first mismatch is **in the document**: ИТОГО 1079.9 = Σ numbered rooms 1049.5 + the «в том числе» sub-zone 30.4 (double counting). The same table appears in PD АР F0156 p27. Parser rules: «в том числе» rows are children, not rooms; groups continue across side-by-side tables |
| ТЭП A4, PD ПЗ F0101 p9 | `find_tables` | The whole ГОСТ frame and stamp become one 37×27 grid |
| same | Row alignment (words grouped by y, columns from header x-positions «Ед. изм. / по ГПЗУ / по ПД») | All rows readable. Numbers are split into words and must be re-joined: «17» + «140,2» = 17 140,2; «13» + «812,0». Values exist per column (ГПЗУ vs ПД): «Площадь застройки, в т.ч.: кв. м 1225,8», «Абсолютная высота … м 233,7», «Высота объекта … 74,5 / 74,5» |
| Spec ГОСТ 21.110, PD F0171 p105 | OCR only (text layer present) | OCR CA 0.95–0.97; the parser is the same row-alignment family |
| Scanned protocol tables B02/B04 | OCR lines + row alignment | Numeric cells, including merged vertical cells, read correctly (key-field EM 0.905); a ruling grid is not required |

**Rule:** no generic table extractor in the hot path. Build typed parsers anchored on header keywords and rulings: EXPLICATION, TEP, SPEC_21110, DEVIATION (ИД), CHANGE_LOG and the АОСР реестр. Each is self-checked (sums, row counts, known column grammars). A self-check failure becomes a SUSPICION or a LOW_QUALITY flag, never silent data.

---

## 7. Title blocks, codes and sheets

### 7.1 What the real stamps look like

- **Тюменская RD.** The whole stamp is curves.
  - OCR with v6-small reads every field: code, «РД», sheet, «Изм.» rows («2 Зам. 690-23 20.03.2024», «1 Зам. 582-23 27.11.2023»), names, «Формат: A0».
  - The printed sheet number is **stamp = gold `document_sheet_number` + 1 for F0201** (p17 prints 4, gold says 3; p18 prints 5, gold says 4). F0202 p17 matches its stamp (4 = 4). This confirms 95 §0.4: never localise by sheet number; `pdf_page_number` is the key.
- **Новослободская.** Stamps are text on most RD sheets, but F0138 is curves («2451.Р.ДР.ГИ», stage in Latin «P», «Лист 1 / Листов 13»).
- **PD volumes** mostly have text-layer stamps; Тюменская mojibake pages excepted (95 R1).

### 7.2 Code corrector (prototype `codefix.py`, 50 lines, deterministic)

1. **Tokenise** on `- / . _` for code-shaped tokens (≥ 2 separators, letters and digits present).
2. **Letter segments.** In a segment that has letters, map the Latin look-alikes `A B C E H K M O P T X Y` to Cyrillic.
3. **Digits between letters.** Turn `0` into `О` and `3` into `З` when they sit between letters.
4. **Leading or trailing digit glued to letters.** Accept the О/З version only if the result is in a discipline dictionary. The dictionary holds ПЗ, ПЗУ, АР, КР, КЖ, ОВ, ИОС, РД, ГП, ЭОМ, ТХ, ПОС, ООС, ПБ, ОДИ, ТБЭ, ВОР, СП, ОК, ДР … and the org prefixes АНО, НВС, НСЛ taken from the manifest.
5. **Results.**
   - Fixed: «АН0/150321/1-П-И0C5.4.2» → «АНО/150321/1-П-ИОС5.4.2»; «AHO/150321/1-PД-OB1» → «АНО/150321/1-РД-ОВ1»; «АHO/150321/1-П3У-П3» → «АНО/150321/1-ПЗУ-ПЗ».
   - Not fixed: «HBC-2025/03-P3» → «НВС-2025/03-Р3», because П was misread as P. The **registry prior** fixes it: the manifest name «НВС-2025.03-1.2-ПЗ.pdf» gives the expected tail, and the stamp is accepted when the homoglyph-aware distance is ≤ 1.
6. **Raw is always kept.** The corrected value is the match key; the raw string is what the evidence card shows (01 §3.9, normaliser).

### 7.3 Title-block reader requirements (update of 01 §3.9 and 02 §3.7)

- **Source.** Text layer when the stamp zone holds ≥ 20 characters. Otherwise OCR of the stamp region at 300 dpi; this is the only place where 300 dpi is kept, for the small «Изм.» cells.
- **Cell assignment.** Anchor labels «Стадия / Лист / Листов / Изм. / Кол. / №док. / Подпись / Дата» plus rulings. OCR returns labels and values as separate lines with clean geometry, so cell assignment works on OCR output too.
- **Stage values seen:** «П», «Р», «РД», «ИС». Map them via a dictionary and fold homoglyphs.
- **Sequence smoothing** of sheet numbers within a file, and duplicate-sheet detection (95 R5).
- **QR decode** in the stamp (95 R7).
- **Revision rows** parsed as (Изм., Кол.уч., Лист, № док., date, kind Зам./Нов./Аннул.) for B01.

---

## 8. DWG (Речников archives)

| Question | Finding |
|---|---|
| How many and which versions | 38 archives (20 zip, 11 7z, 7 rar) hold 793 members: **662 DWG**, 75 BMP, 24 PNG, 17 DOCX, 6 PDF, 6 BAK, 2 JPG, 1 LOG. There are also 5 loose DWG. Header bytes: loose files AC1024 (2010) ×1 and AC1027 (2013) ×4; zip members AC1027 ×296, **AC1032 (2018) ×64** (e.g. АР первый этаж, extracted from a 7z), AC1021 ×4, AC1015 ×1. 7z/rar members were not header-checked (only extracted samples) |
| Names | Zip entries have no UTF-8 flag, and their names are **cp866**: decode `cp437 → cp866`. 7z names are fine. Many names carry Unicode bidi controls (U+202A–U+202E), which must be stripped. RAR needs `unrar` (present at `/opt/homebrew/bin/unrar`) or libarchive |
| Can we read DWG without brew | **Yes: `ezdwg` 0.12.9** (PyPI, MIT, Rust core; wheels for macOS universal2 and manylinux x86_64; no linux-aarch64 wheel, so build from sdist with Rust or run the ML image as amd64) |
| What a DWG contains | • F0374 КЖ4.2 sheet 6 (AC1027): 4,477 model-space entities in 1.8 s, including LINE, MTEXT (663), INSERT (286), HATCH and DIMENSION (80, with exact `actual_measurement`, e.g. 22 550 mm).<br>• Paper space holds the stamp as MTEXT fragments («01-07/23-14-», «РД», «-», «К1 -», «Схема расположения нижнего армирования… на отм. +10,100…+45,600»).<br>• АР «Экспликация полов» sheet (AC1032): room ids «21.2», «22.1», areas «20,5 м²», «137,0 м²», fire-hazard classes, finish layers as MTEXT.<br>• ОК (AC1024): 441 dimensions, 553 inserts, leaders, «С245 (поз. 3)», «ГОСТ 5264-80».<br>• **Defects:** FIELD values decode as binary junk; СПДС symbols come as Private Use Area glyphs (U+E729 …); MTEXT is split into words |
| Does the PDF twin carry the same | Yes. RD АР1 PDF F0330 has a full text layer (262–18,644 characters per page), and «Экспликация» appears on pages 4, 7, 8, 10, 11 and 13. The ОК PDF F0341 has 351–8,231 characters per page |
| Options | • **(a) PDF twin only.** Evidence must be a manifest PDF page anyway (93 §2.8), and the twin has the text.<br>• **(b) ezdwg enrichment**, for exact dimension values, block names and attributes (doors, openings), layers and room polygons. No system install.<br>• **(c) LibreDWG `dwg2dxf`** (GPL-3; `brew install libredwg`, or build in Docker) → ezdxf. More mature for odd objects, but it adds a GPL binary and an install.<br>• **(d) ODA File Converter** (free, proprietary; macOS build via GUI installer, CLI `ODAFileConverter in out ACAD2018 DXF 0 1`; licence terms restrict redistribution) → ezdxf |
| Recommendation | **(a) for extraction and evidence, with (b) as an optional P2 enrichment.** Map a DWG sheet to its PDF twin page by (1) the sheet number in the DWG file name («Лист - 10 - …»), (2) the paper-space stamp «Лист», and (3) Jaccard similarity of paper-space text vs the PDF page text. Do not install (c) or (d) unless (b) fails on a needed file |

---

## 9. DOCX, archives and the evidence contract

- **The 6 manifest DOCX** (all RD):
  - Five are change notes, one per КЖ volume: «Паркинг. КЖ2.1 — Изменение высоты конструкций в связи с опуском ФП; Добавление отверстий по заданию от инженеров…»; «Корпус 1. КЖ2.2. Ревизия В / Ревизия С»; «14.09.2023 – ревизия не оформлялась… 27.12.2023 – оформление ревизии В».
  - One is «Ответы на замечания Заказчика» for ГП: a 12×3 table with 5 embedded screenshots.
  - They are **revision metadata for B01** (which RD issue is current and why), not parameter sources. python-docx reads all six.
- **17 more DOCX inside archives** (titles «Ривер парк 14 Титул РД», «Разрешение на внесение изменений АР1», «ЭН_СО»). They have no manifest `file_id`, so they are context only.
- **6 PDFs inside archives** (e.g. «01-0723-14-РД-ЭН.pdf» inside F0409, «МССЗ_ТУ Моссвет № 25056 …», «Приложение Б Расчёт.pdf») are likewise not citable. They can confirm a value found in a citable file.
- **Evidence contract.** `pdf_page_number` is required.
  1. Cite a **manifest PDF** whenever one carries the fact: the PDF twin for DWG, the RD PDF for a DOCX change note.
  2. If a finding truly rests on a manifest DOCX, cite its `file_id` with `pdf_page_number` = the page in our deterministic LibreOffice rendering. For these 1-page notes that is 1. Record `page_basis=RENDERED_LIBREOFFICE` in the sidecar.
  3. Never cite archive members, DWG or BAK.
  4. Internal traceability uses virtual ids `F0331!DWG/…` with the member sha256.
- **Archive guards.** Uncompressed size ≤ 2 GB per archive and ≤ 5,000 members. Refuse path traversal. Extract into a sandbox. Hash every member.

---

## 10. Scale: the hidden object in reasonable time

### 10.1 Measured costs

| Operation | Cost |
|---|---|
| Open the 658 MB / 507-page F0232 | 0.01 s; RSS +95 MB |
| Page triage (text, image info, geometry) | 1–3 ms per page; whole train set (9,963 pages) in 37 s with 8 processes |
| Render an A4 page at 300 dpi / extract a native JPEG | 0.05–0.09 s / ≈ 0 s |
| OCR v6-small, 1 thread, idle core: A4 scan 300 dpi (65 lines) | 9.8 CPU-s (det 4.1, rec 2.9, orientation probe + crops 2.8) |
| OCR v6-small, 1 thread: A4 dense manual page at 200 dpi (76 lines) | 5.3 CPU-s (det 1.6, rec 3.6) |
| OCR v6-small, 1 thread: A3 «Кладка» binder page 300 dpi | 7.5–12.5 CPU-s |
| Parallel, 10 processes × 1 thread, machine under load (load avg 5–17) | A3 «Кладка» (≈100 lines/page): 25.8 pages/min @300 dpi, **37.5 @200**. A4 ЭОМ manuals (≈120 lines/page): 16.2 @300, **23.1 @200**. With 6 processes: 19.6; with 4: 14.4 |
| Full-page OCR of a gold A0 sheet (F0201 p18, 20 tiles, 6 threads) | 39 s wall |
| CoreML EP detector | 2× faster (host only) |
| e5-small ONNX-equivalent embedding | 817 lines/s; 26 ms per parameter query over 107k lines |

### 10.2 Plan for OBJ-RECHNIKOV-7-7 (15,961 pages; run once with a frozen config, 93 §4.9)

1. **Stage 0: inventory.** About 1 min. All pages get their class, rotation, DPI, text-layer quality and `STAMP_PAGE`/blank flags. Archives are listed and DOCX parsed.
2. **Stage 1: text layer and cheap structure.** About 10 min. Covers the 7.6k PD/RD vector pages: text layer, stamps, tables, explications and the anchor index.
3. **Stage 2: coverage check on drawing sheets.** About 1.5k sheets ≥ A3 in PD/RD, plus sheets with a high glyph-path ratio. Run detection at 200 dpi and OCR the uncovered boxes, on layer-isolated renders where OCGs exist. About 25–40 CPU-h in the worst case → **30–60 min** on 9–10 effective cores with CoreML detection.
4. **Stage 3: ИД binders.** About 8.2k scan pages.
   - (a) Orientation + header band at 100–150 dpi → document type. Target ≤ 1 CPU-s per page; the prototype took 7 s because it probed rotation at full size.
   - (b) Full OCR at native DPI (≤ 300) for the types that feed parameters or integrity: АОСР, реестры, протоколы, документы о качестве, сертификаты/паспорта on concrete, rebar and cable, исполнительные схемы, журналы.
   - (c) Header only for equipment manuals and product catalogues (seen in F0228 p215–283).
   - (d) Skip stamp and blank pages.
   - Estimate: 6–7k pages × 6–12 CPU-s ≈ 12–20 CPU-h → **1.5–2.5 h** wall.
5. **Stage 4: extraction, comparison, export.** Minutes.

**Total about 2–4 h wall on the M2 Max.** Everything is cached by `sha256 + pipeline version`, so a crash resumes. Work is split per file and per 50-page chunk, with at most 10 workers. The limits are 1 open document per worker (RSS ≈ 100–250 MB) and ≤ 60 MP of rendered image in memory at a time; an A0 at 200 dpi is about 62 MP, and tiles are rendered by clip. Run it **natively on the host**, not in Docker, to use CoreML and all cores; Docker on macOS has no GPU and pays VM overhead.

### 10.3 §11 targets (100 pages ≤ 3 min; 500 pages ≤ 10 min)

- **Idle host.** Single-process cost is 5–10 CPU-s per A4 scan page, so 10 workers give about 60–110 pages/min. That is ✓ for 100 pages and borderline ✓ for 500.
- **Under the load we saw** (other agents), 16–37 pages/min, which fails.
- **Demo conditions:** idle machine, native run, CoreML detector, 200 dpi. The test PDF is a realistic ИД scan binder (the Новослободская ИД attachments), not A0 drawings.
- **Report honestly:** publish the hardware, the load and the per-stage timing, as 02 §3.4.6 planned.

---

## 11. Semantic extraction on real text

- **Corpus.** Train text layers: 323,606 lines, 109,233 unique. The 38 tier-A parameters of `matrix_enriched.json` are the practical "deep" set.
- **Regex profiles** (`regex_pattern`, applied per line):
  - Hits for 29 of 38. Zero for PZ-005/006/010/018, SPZU-026, ZU-131 and SM-132; their values sit in table cells or are absent.
  - False-positive families: normative limits («Общая площадь объекта защиты не более - 20 000 кв.м.», «с этажностью свыше 10 до 16 включительно»); title-block lines (PZ-013 matched «Школа на 600 мест» 1,020 times); substring collisions (PZ-019 «КЗ» inside «ЩСКЗ»).
  - Needed rules: exclude title-block zones; tag each value as normative or object (words «не более / не менее / допускается / свыше … до»); require the anchor in the same row or cell context.
- **e5-small anchors.**
  - The retrieved top lines are the right row labels for most parameters, e.g. PZ-01 «Площадь застройки» (0.94), PZ-02 «Общая площадь здания, в т.ч.:», PZ-08 «Высота здания», PZ-22 «Степень огнестойкости здания – I;», KR-55 «Класс бетона по прочности на сжатие В40, марка по морозостойкости…», ZU-131 «Удельный расход тепловой энергии на отопление и…».
  - A manual judgement of the top-3 for 12 parameters gave about 2/3 correct labels.
  - Failures are short generic lines («надземной части» for PZ-04) and system names instead of values (PPM-112).
  - Scores cluster at 0.89–0.95, so use ranks, not absolute thresholds.
  - **Values are in other cells:** fewer than 60 % of the top-10 lines contain a number. Embed **row-context strings** (row label + parent label + unit + value cells) and fetch values geometrically.
- **Real phrasings to seed the ~35 deep profiles** (verbatim from Новослободская/Тюменская text layers):

| Param | Real phrasings |
|---|---|
| PZ-001/002 | «Площадь застройки, в т.ч.: кв. м 1225,8» (ТЭП row, value in the ПД column); «Площадь застройки - 9067,1 кв.м»; «Общая площадь здания, в т.ч.:» |
| PZ-004 | «Строительный объем здания V=60997,93 куб.м;»; scanned «Строительный объем здания 60997,93м³» (анкета B06) |
| PZ-008/009 | «Высота здания h=73.6м»; «За относительную отметку ±0.000 принята абсолютная отметка 159.95 м.»; «Абсолютная отметка ноля 0,00 принята 159,95м.»; «отметка 0,000 принята 138,00;» |
| PZ-014/017 | «Расчетная мощность энергопринимающих устройств 462,55 кВт.»; «Расчётная мощность: Рр=462,5 кВт»; «Максимальная тепловая нагрузка: 1,7686 Гкал/час.»; scanned «389,893 кВт (0,335 Гкал/час)» |
| PZ-022/023 | «Степень огнестойкости здания - I;»; «Класс конструктивной пожарной опасности здания - С0;» |
| SPZU-037/038 | «требуется 61 машино-место. Проектом предусмотрено 64»; «количество машино-мест для МГН - 2 м/м, в т.ч. 2 м/м для М4.» |
| KR-055 | «Для бетонирования применяется бетон класса В15 (F и W не регламентируются)»; «бетона-В25;»; ИД: «БСТ В15П4F(I)150W6 (ПМД до -10)», «образцы-кубы бетона проектного класса В15», «соответствует бетону класса В11 ( ГОСТ 18105-2018 "схема Г" )» |
| KR-056/057 | «из стали С245 по ГОСТ 27772-2021»; «Арматура Д=12мм(А400)»; «Прокат арматурный свариваемый … классов А500С»; ИД «форма А500С по ГОСТ 34028-2016» |
| KR-058/059/061 | «Железобетонная фундаментная плита h=1200 мм»; «Фундаментная плита - 500мм»; «плиты перекрытия и покрытия толщиной 200 мм»; «Типовое армирование стен толщиной 250мм» |
| AR-041 / PPM-105 | «фактическая ширина каждого эвакуационного выхода не менее 1,4 м»; «ширина дверей принята не менее 1,2 м в свету» |
| IOS1-069 / PPM-109 | «Кабель огнестойкий типа КПСнг(А)-FRLS 1х2х1,0»; «ВВГнг(А)-LSLTx 3х2,5»; «ПуГВнг(А)-LS 1х4мм²» |
| PPM-103 | «противопожарных нормально открытых клапанов с пределом огнестойкости не менее EI 90»; «Огнестойкость дверей лифтов принята EI 60.» |
| PPM-112 | «Итого по ПД1 (L=8600 м³/ч, Pc=500 Па)»; «Итого по ВД6 (L=13300 м³/ч, Pc=600 Па)» |
| ZU-125/126 | «БАТТС … λ Б = 0,041 Вт/(м), группа горючести НГ - 50 мм»; «Теплоизоляция δ=30мм» |
| IOS4-078/079 (drawings, OCR) | RD outlined: «АМР-К 350x300», «L 340», «В22», «ВЕ1», «П2/ВЕ ±400 м³/ч»; PD text: «В2.4», «М.О. поз.169»; supply units «П2, П2.1 … П18» (95 §3.3) |

- **Latency** is 26 ms per parameter over 107k lines on CPU, well inside §11 п.7 (≤ 500 ms).

---

## 12. Optional VLM (local and cloud)

**What it could add.**
- On G-TR-001/003/004, the gold differences are per-room sets of system tags and local exhausts; see 95 §3.4.
- The deterministic path is OCR tags → room zones → set diff. A VLM helps where that path is weakest:
  - (a) assigning outlined labels and leaders to the right room on a busy plan;
  - (b) recognising symbols without text (local exhaust hoods «М.О.», grilles, fan units);
  - (c) writing the SUSPICION rationale in inspector language («в помещении 142 отсутствуют местные отсосы В2.4–2.6, предусмотренные листом 10 ПД»).
- It should **never be the evidence source**. Its output is accepted only when every tag it names is present in the OCR/text tokens inside the zone (the grounding rule of 02 §3.22). Its confidence is capped at 0.6, and it cannot set statuses.

**Local option (32 GB M2 Max, no install done).**
- Model: Qwen2.5-VL-7B-Instruct or Qwen3-VL-8B at 4-bit through MLX-VLM or Ollama (`qwen2.5vl:7b`), about 5–7 GB of memory.
- Expected speed: a 1–1.5 MP crop pair is about 2–3k visual tokens; roughly 5–15 s prefill and 20–35 tok/s decode, so **15–40 s per question**. That suits targeted crops (tens to a few hundred per object), not pages.
- Expected quality on dense A0 CAD crops is moderate: small outlined labels are misread or invented. Give it the OCR token list as text and ask for **set comparison and room assignment, not reading**.

**Cloud option.**
- Frontier multimodal models (Claude, GPT-4.1/5-class, Gemini 2.5-class) read dense drawings far better and do the PD↔RD comparison with reasoning. Cost is about $0.01–0.05 per crop pair, so a few dollars per object.
- It sends organizer documents off the machine. 93 §4.9 and U-01 forbid that for Речников unless you approve it explicitly, and then only as a frozen pipeline step.

**Recommendation.** Deterministic core first. Add a local VLM as a P2 "second opinion" only after the per-room comparator exists and has been measured on Тюменская. Ask the user about the cloud (§15, Q2).

---

## 13. Updated recognition architecture

```
FILE (manifest row, sha256)
 ├─ PDF ─► F0 inventory (1–3 ms/page): class, /Rotate, DPI, text-layer quality (lexicon, mixed-script, mojibake),
 │                                    occlusion, OCG layers, glyph-path ratio, STAMP_PAGE / blank, QR window
 │         F1 text layer (visible, de-occluded, NFC)            ─┐
 │         F2 coverage map: det (PP-OCRv6-small, 200 dpi,        │  drawing sheets ≥ A3 or glyph-path ratio high,
 │            tiles 3200/400, seam merge) on layer-isolated      │  all image/outlined pages
 │            render; boxes not covered by F1 words → F3         │
 │         F3 OCR v2: orientation detector → native DPI (150–300)│
 │            → det (v6-small; v6-medium fallback if mean score  │
 │            < 0.9 or seal zone) → crops (rotated rect) → rec   │
 │            (PP-OCRv5 cyrillic) → retries (180° for vertical /  │
 │            low score; 3-way for short vertical; local          │
 │            re-detection for long low-score lines)             │
 │            → quality flags (OK ≥ 0.85, LOW_QUALITY ≥ 0.6,      │
 │            ABSTAIN) → zones (seal/stamp/QR/handwriting)       │
 │         F4 merge F1 ∪ F3 → page tokens with source, score, polygon (displayed-page space, 02 §3.14)
 │         F5 post-correction: code corrector + registry prior; numeric context; lexicon (words only)
 │         F6 layout: title block (cells, QR, Изм. rows, sheet↔page), room index (labels, zones, explication rows,
 │            floors), revision clouds (OCG «Изм. №N»), binder segmentation
 │         F7 typed tables: EXPLICATION, TEP, SPEC_21110, DEVIATION, CHANGE_LOG, АОСР + реестр (self-checks)
 │         F8 NLP: row-context span index (e5-small) → anchor → geometric value fetch → role filter → typed values
 ├─ DOCX ─► python-docx (paragraphs, tables, footers, images→F3) + LibreOffice render for page numbers
 ├─ archive ─► list (cp866 / bidi strip, guards) → members: DWG → (optional) ezdwg dump + PDF-twin page map;
 │            PDF/DOCX members → context only (no file_id)
 └─ DWG (loose) ─► PDF twin in the same folder (evidence); ezdwg enrichment optional
```

Defaults that change from 02:
- no text-line classifier;
- PP-OCRv6-small detector;
- 200 dpi for vector outlines and native resolution for scans;
- word-level coverage routing instead of page-level text-layer-first;
- title blocks are OCR'd whenever the stamp has no text;
- Tesseract `rus` is no longer a runtime dependency; OSD only, as a tie-breaker;
- DWG is readable (ezdwg) but not required.

---

## 14. Prioritised work plan (AG-02 recognition, with the AG-01 touch-points)

Sizes: S ≈ 0.5–1 agent-day, M ≈ 1–2, L ≈ 3–4. "Bench" means `recognition_benchmark.json` together with the metric code ported to `tools/ocr_eval`.

| # | Prio | Task | Size | Acceptance test (real data) |
|---|---|---|---|---|
| R-01 | P0 | Port the benchmark harness: metric (text-layer and line GT, key-field EM, bootstrap CI), page set, hand GT; CI job; JSON report | S | Reproduces the §3 numbers within ±0.5 pp |
| R-02 | P0 | **OCR core v2**: RapidOCR components (v6-small det, v5 cyrillic rec, v6-medium fallback), tiled det with seam merge, no cls, 180°/3-way retries, long-line re-detection, quality flags, batch rec, CoreML switch on macOS, pinned model sha256 | M | Bench A ≥ 0.965 strict (CI low ≥ 0.95); bench B+D ≥ 0.965; F0001 p1 ≥ 0.99; F0202 p29 reads «Всего радиаторы:» |
| R-03 | P0 | Orientation: det-geometry + rec-probe detector, OSD tie-break; /Rotate rendering; back-mapping of polygons | S | 100 % on B03, B04, B06, A07 and a hand-checked 50-page sample of Новослободская ИД scans |
| R-04 | P0 | **Router v2**: inventory classes + mojibake/lexicon/mixed-script test + occlusion + STAMP_PAGE/blank + glyph-path ratio + det coverage map → OCR of uncovered boxes; OCG layer-isolated render (95 R2) | M | F0201 p17/p18: ≥ 90 % of OCR-only lines captured, and 012/140/142/147/198 tags present; C01 routed to OCR; mojibake pages of F0146 routed to OCR; no STAMP_PAGE OCR'd |
| R-05 | P1 | Render policy: native DPI clamp [150, 300]; 200 dpi for outlines; embedded rasters > 5 % of the page (95 R9) | S | −25 % CPU on bench vs a fixed 300 dpi, CA loss ≤ 0.5 pp |
| R-06 | P0 | **Key-field post-correction**: code corrector + registry prior (manifest names, per-file code), numeric context, room-number grammar (leading zeros «012»), homoglyph policy | M | Codes EM ≥ 0.95 on 11 vector + 6 outlined stamps; scan key fields relaxed EM ≥ 0.93; room tokens EM ≥ 0.95 where a text layer exists |
| R-07 | P0 | **Title-block reader**: text or OCR, cells, stage/sheet/sheets, Изм. rows, QR (95 R7), sheet↔page map with smoothing and duplicates (95 R5) → `document_pages.title_block` | M | All F0201/F0202 drawing pages: sheet = stamp ≥ 0.95, code 100 %; F0138 p3 fields exact |
| R-08 | P1 | Typed tables: header-anchored EXPLICATION (with «в том числе», multi-table, Σ checks), TEP row aligner (number re-join, ГПЗУ/ПД columns), SPEC_21110, DEVIATION, CHANGE_LOG | L | F0201 p18: 116 rows, hand check ≥ 0.98 row-exact; F0101 p9 and F0154 p13: every row label→value exact; F0171 p105: pos/name/qty ≥ 0.95 |
| R-09 | P1 | ИД binder typing (header band) + parsers: АОСР/реестр (95 R13), протокол испытаний, документ о качестве, сертификат | M | Doc type ≥ 0.9 on 80 hand-labelled Новослободская ИД pages; key fields of B01/B02/B04 ≥ 0.93 relaxed |
| R-10 | P1 | Zones: seal/stamp/QR/handwriting masks, excluded-zone logic, LOW_QUALITY/ABSTAIN reporting and coverage metrics | M | All 19 GT excluded zones hit (IoU ≥ 0.3); the lines inside are flagged |
| R-11 | P2 | DOCX adapter (python-docx + LibreOffice render + locator) and archive adapter (cp866, 7z, rar, bidi strip, guards, virtual ids, PDF-twin map) — shared with AG-01 | S | All 38 Речников archives list without error (format test only); 6 DOCX parsed; F0327 table 12×3 |
| R-12 | P2 | DWG enrichment via ezdwg: text/dimension/insert/layer dump, FIELD/PUA filtering, DWG→PDF-twin page map | S | 20 DWG from 4 archives parse; 10 hand-checked sheet→page mappings correct |
| R-13 | P1 | NLP v1: row-context span index, e5-small ONNX, anchor → geometric value fetch, normative/object role filter, title-block exclusion, 35 deep profiles seeded from §11 | M | Top-3 anchor ≥ 0.9 on the 40-query test rebuilt with row-context strings; value exact ≥ 0.9 on 35 fixtures from Новослободская/Тюменская |
| R-14 | P0 | **Batch runner** for the hidden object: per-file jobs, page chunks, sha256 cache and resume, frozen config hash, CoreML, progress log, stage timing; §11 perf tests | M | A full Новослободская run (4.1k pages) finishes and logs per-stage timing; a 100-page ИД scan PDF ≤ 180 s on an idle host |
| R-15 | P0 | **Room index across sheets** (labels, schematic columns or plan zones, explication rows, floors) for per-room tag sets (95 R8) — feeds B04/B07 | M | Тюменская rooms 012, 140, 142, 147, 198, 314, 267, 270, 271 and 272 located on the right PD and RD pages, including 314 on RD p20 |

**Critical path:** R-01 → R-02 → R-04 → R-15 → B04 comparator → R-14 dry run on Новослободская. R-03, R-06 and R-07 run in parallel with R-04. The P0 set is 8 tasks and about 9–11 agent-days.

**AG-01 touch-points:**
- sha256 identity and missing-on-disk handling (93 §1.3);
- archive/DOCX registration as non-citable members;
- binder segmentation and per-page stage for RD_ID_MIXED (95 R12);
- consuming `title_block` and the sheet↔page map;
- DOCX change notes → revision chain.

---

## 15. Questions for you

| # | Question | Options | Recommendation | Why it matters |
|---|---|---|---|---|
| Q1 | Run the hidden-object batch natively on the Mac rather than in Docker? It is one frozen run of about 2–4 h | a) native Python with CoreML on the host; b) inside Docker | **a**; the demo stack stays in Docker | CoreML halves detector time, and Docker on macOS has no GPU. It decides whether the run fits in one evening |
| Q2 | May a VLM or LLM see organizer documents? | a) never; b) local model only (Ollama/MLX on the Mac); c) a cloud model, train objects only; d) cloud on Речников too | **b** as an optional P2 second opinion; decide on c/d once the deterministic comparator is measured | 152-ФЗ and the 93 §4.9 integrity rules; cloud quality on drawings is much higher |
| Q3 | Human time for OCR ground truth | a) re-check the 6 hand-GT pages (~40 min); b) a) plus 8 more Новослободская ИД scans (~1.5 h); c) none | **b** | Makes the «CA ≥ 0.95 / EM ≥ 0.90» claims defensible with n ≈ 15k characters |
| Q4 | Install LibreOffice for DOCX→PDF page numbers? | yes (`brew install --cask libreoffice`; in Docker `libreoffice-writer-nogui`) / no | Yes, P2 | Only needed if a DOCX must be cited or rendered in the viewer |
| Q5 | Accept `ezdwg` (MIT, pip) as an optional dependency instead of LibreDWG/ODA? | yes / no | Yes | No system install; the PDF twin stays the source of truth |

---

## 16. Install needs

- **ML environment (pip):**
  - `rapidocr` ≥ 3.9.2 and `onnxruntime` ≥ 1.20 (1.30 tested; the macOS wheel includes the CoreML EP).
  - Models, pinned by sha256: `PP-OCRv6_det_small.onnx` (9.9 MB, 090f04ab…), `PP-OCRv6_det_medium.onnx` (62 MB, 92078b73…), `cyrillic_PP-OCRv5_rec_mobile.onnx` (8 MB), and optionally `ch_PP-OCRv5_det_mobile.onnx`. Bake them into the image; no runtime download.
  - `opencv-python-headless`, `rapidfuzz`, `shapely`, `python-docx`, `py7zr`, `rarfile`.
  - `ezdwg` (optional; on linux-aarch64 build from sdist with Rust or use an amd64 image).
  - e5-small exported to ONNX (`optimum`/`onnx` at build time only).
- **System:** `unrar` (present on the host) or libarchive in Docker; LibreOffice (Q4); Tesseract with `osd` only (present). Tesseract `rus` is **not** needed (`brew install tesseract-lang` only if the Tesseract fallback is wanted).
- **Not needed:** LibreDWG, ODA File Converter, torch at runtime, PP-OCRv6 rec (it has no Cyrillic).
- **Scratch installs made for this analysis:** `ezdwg`, `ezdxf`, `onnx` and `onnxruntime` into the scratch `venv`, and the RapidOCR model downloads into the scratch `rapid_models/`.

---

## Appendix A — Where the numbers come from (scratchpad `recog/`)

| Script | Output |
|---|---|
| `inventory.py`, `classify.py` | Page classes, DPI, rotation (train: all pages; Речников: 12 pages per file) |
| `bench_lib.py` | Rendering, GT extraction, engines, `ocr_v2`, rotation detector, metric |
| `run_bench.py`, `score_bench.py` | §3.1 (results in `results/*_300.json` and `*_200.json`) |
| `make_gt.py`, `gt_*.py`, `scan_eval.py`, `run_scans.py` | Hand GT and §3.2 (`gt_scans.json`, `scan_results_final.json`) |
| `keyfields.py`, `scan_keyfields.py`, `codefix.py` | §3.3, §7.2 |
| `expl_parse.py`, `expl_check.py`, `tables_probe.py` | §6 |
| `arch_inv.py`, `../dwg/dwgprobe.py` | §8 |
| `speed.py`, `throughput.py`, `header_probe.py` | §10 |
| `spans.py`, `regex_eval.py`, `emb_eval.py` | §11 |
