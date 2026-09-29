# inspector_docproc — recognition

Owner: **AG-02A (recognition lead)**; AG-02B (drawings, title blocks, room index) and AG-02C (tables, ИД, NLP)
add their modules here (sub-ownership below). Design: `docs/analysis/96_recognition_real_data.md` (measured
pipeline), `97_plan_delta_real_data.md` §2.13 (F0–F5), `02_extraction_ocr_nlp_cv.md` §3.14 (geometry).

It turns every page of a manifest PDF into one **PageTokens** document
(`packages/contracts/schemas/page_tokens.schema.json`): text-layer and OCR word tokens with provenance
(`TEXT_LAYER`, `TEXT_LAYER_REPAIRED`, `OCR`, `OCR_LAYER_ISOLATED`), confidences, quality flags, lines, the
page class and the route taken. Every bbox and polygon is in `PDF_VISIBLE_ROTATED_TL_V1`: normalised [0, 1]
over the visible page (CropBox ∩ MediaBox) after /Rotate, origin at the top left.

## Pipeline (per page)

```
text layer (visible words, font, reading direction)              textlayer.py
  → router: page class + plan                                     router.py, lexicon.py, repair.py
      EMPTY ......................... nothing (counted)
      STAMP_PAGE .................... OCR of the placed images only (separators, e-signature sheets)
      VECTOR (A4 text) .............. text layer only
      VECTOR (≥ A3, raster inserts) . text layer + word-level coverage OCR of the uncovered boxes
      VECTOR_OUTLINED_TEXT .......... full OCR at 200 dpi (+ CAD-layer-isolated pass)
      BROKEN_ENCODING ............... constant glyph-shift repair → TEXT_LAYER_REPAIRED, verified by an OCR
                                      probe; unrepairable or rejected → full OCR
      RASTER_SCAN / RASTER_HIDDEN_OCR / untrusted HYBRID → orientation + full OCR at native dpi [150, 300]
  → OCR v2                                                        ocr/engine.py, ocr/pipeline.py
      PP-OCRv6-small det on 3200-px tiles (400 px overlap) + seam merge; no text-line classifier;
      PP-OCRv5 cyrillic rec; 180° retry (vertical / score < 0.75); 3-way read of short vertical tokens;
      chunking and local re-detection of long weak lines; PP-OCRv6-medium second detector («union»)
  → orientation (0/90/180/270): det geometry + rec-score probe, Tesseract OSD tie-break   orientation.py
  → zones (R-10): seals, colour stamps, QR (payload decoded), colour handwriting/signatures  zones.py
      → PageTokens `zones` with `attrs.token_ids`; handwritten OCR tokens ABSTAIN
  → post-correction of OCR words (raw kept in `text_raw`): document-code corrector, diameter
      sign (φ15 → Ø15), script context (homoglyphs follow line/page script; italic ГОСТ
      Cyrillic read as Latin → Cyrillic when the result is a TRAIN-lexicon word)          codefix.py
  → PageTokens (contract), cached as gzip JSON by file sha256 + pipeline version          recognize.py, cache.py
```

Models come only from `.models/ocr`, pinned by `tools/models/manifest.json` and checked by sha256 before
first use (`models.py`; `OCR_MODEL_MISSING` / `MODEL_ARTIFACT_INTEGRITY_FAILED`). On a macOS host the
detectors run on the CoreML execution provider through one detection server process (static canvases
1600² and 3200², shared memory); the recogniser runs on the CPU (faster than CoreML for this model). The
provider actually used is logged and stored in `engine_versions` and in the pipeline version. No network.

## Commands

```bash
cd services/ml
# recognise pages (train objects; the hidden object only in the frozen run with --hidden-run)
uv run --locked inspector-batch recognize --object OBJ-NOVOSLOBODSKAYA --files F0006 F0007 --pages 1-100
#   --workers N (default cpu-2), --providers auto|cpu|coreml, --page-timeout 900, --no-cache,
#   --config overrides.json ({"ocr": {"medium_mode": "off"}}), --allow-sleep
# benchmark (report 96 set; 33 train pages, hand GT for 6 scans)
make bench-ocr                                  # = inspector-batch bench --suite ocr (CoreML when available)
uv run --locked inspector-batch bench --suite ocr --providers cpu --baseline
#   suites: ocr (all) | vector | scans | orientation | drawings
```

Outputs: `runs/<run_id>/tokens/<file_id>/p00001.json.gz` (hard links into
`.cache/tokens/<pipeline_version>/…`), `tokens/index.json` (contract `tokens_index`: per file the pages with
class, text sources, quality, rotation), `tokens/index.jsonl` (one summary per page: class, source, quality,
timings, zones, warnings or error), `recognize_summary.json` (counts, page classes, zones, throughput, stage
timings, supervision events), `bench_<suite>.json`. Full-page renders are never written to disk. Paths come
from `inspector_common.runlayout` (`PAGE_TOKENS`, `TOKENS_INDEX`, `RECOGNIZE_SUMMARY`).

**Stable read API for AG-02B/AG-02C** (`api.py`): PageTokens and region OCR by `(file_id, page)`, from the run
directory, else the PageTokens cache (file sha256 from the manifest + the run's pipeline version), else
(opt-in) recognised now and cached:

```python
from inspector_docproc.api import TokenStore

with TokenStore.for_run(ctx.run_dir) as store:  # on_miss="recognize" to fill gaps
    doc = store.page("F0201", 17)  # PageTokens dict or None
    words = store.words("F0201", 17)  # quality ≥ LOW_QUALITY; HANDWRITING/QR zone tokens dropped
    seals = store.zones("F0201", 17, kinds={"SEAL"})
    tb = store.ocr_region("F0201", 17, [0.75, 0.9, 1.0, 1.0], dpi=300)  # page coords
```

`run_recognition(..., pages_by_file={"F0201": "17-20", "F0202": "17"})` recognises selected pages of several
files in one worker pool.

**Native runtime.** `import inspector_docproc` sets `ORT_DISABLE_TELEMETRY=1` before ONNX Runtime is imported:
ORT's 1DS telemetry client was the root cause of the M0 exit-134 abort (its worker thread locks a destroyed
`recursive_mutex` during static destruction) and made an HTTPS call from every process. Engines and
recognisers also release their sessions explicitly (`close()` / context managers; workers and the bench do).
Frozen runs pin the provider: `--hidden-run` or `--strict-providers` require `--providers cpu|coreml` (never
`auto`), and a CoreML session that ORT silently moves to the CPU is an error instead of a warning.

## Batch runner and supervision (the frozen hidden run must finish)

Tasks of ≤ 8 pages go to supervised worker processes over private pipes; the supervisor knows each worker's
current page. A worker crash costs only its page, which is retried once in a fresh worker (then
`WORKER_CRASHED`); a page longer than `--page-timeout` is killed (`PROCESSING_TIMEOUT`); a Python error is
`PAGE_UNREADABLE` for that page; a dead CoreML detection server is rebuilt (≤ 3 times). Every page is cached
as soon as it is done, so a rerun resumes. `caffeinate` keeps the Mac awake during a run.

## Tests

- `make test` (fast, synthetic pages): geometry contract on rotated/cropped/offset PDFs, router classes,
  glyph-shift repair, OCR probe, OCR + orientation on synthetic scans, schema validity, cache/resume,
  CLI end to end, supervision (injected crash / hang / page error), detection-server protocol.
- `pytest -m data` (fast, organizer data): routes of the real routing pages, text-layer boxes on the ink
  of a real /Rotate 270 A0 sheet.
- `make test-slow`: the benchmark quality gates (`tests/test_docproc_bench_slow.py`, ~5 min), the real-page
  identical-output check of the recogniser batching and the exit-134 reproduction.

Benchmark definition: `tests/data/recognition_benchmark.json` (copy of `docs/analysis/recognition_benchmark.json`
v0.1 without the hidden-object pages). Line GT: **v2** `tests/data/ocr_gt_v2.json` (current: 14 pages, 46,987
chars, two independent visual transcriptions + adjudication, sha256-pinned in `gt_sets.v2`; scored by
`metrics.score_line_gt_v2`: every line except `exclude_from_scoring`, excluded zones mask OCR insertions only,
ø-family and the multiplication sign between digits folded) and v1 (`hand_gt`, history, 6 pages). The lexicon
(`resources/ru_lexicon.txt.gz`) and its document frequencies (`resources/ru_wordfreq.txt.gz`) are built from the
TRAIN objects only (`python -m inspector_docproc.lexicon build` | `build-freq`).

## Measured results M1 (pipeline `docproc-2.3.0+coreml.493231d510`, 2026-09-28, M2 Max, machine shared with other agents)

`inspector-batch bench --suite ocr --threads 3` → `runs/ag02a-m1-bench-final/bench_ocr.json` (327 s). GT v2 numbers
are the production output (PageTokens text after post-correction); «raw» = recogniser output before it.

| Measure | M0 (GT v1 / M0 code) | M1 | Gate |
|---|---|---|---|
| Scans + outlined text, **GT v2** 14 pages / 46,914 chars, CA strict | — (M0 code on GT v2: 0.945 [0.915–0.967]) | **0.967 [0.952–0.976]**; raw 0.945; relaxed 0.970 | ≥ 0.965 |
| — scans (10 pages) / outlined (4 pages) | — | 0.958 / 0.971 | — |
| — the 6 GT v1 pages scored with GT v2 | 0.967 (raw) | 0.974 | — |
| Key fields GT v2 (n = 77) EM strict / relaxed | 0.831 / 0.844 | 0.844 / 0.844 | — |
| Scans + outlined, GT v1 6 pages (history) | 0.974 raw / 0.976 corrected | 0.974 raw / 0.981 corrected | ≥ 0.965 |
| Key fields GT v1 (n = 42) EM strict / relaxed | 0.905 / 0.952 | **0.952 / 0.952** | relaxed ≥ 0.93 |
| Group A vector, 30 regions | 0.971 [0.957–0.980] | 0.971 [0.957–0.980] | ≥ 0.965 |
| Outlined RD stamps (n = 19) EM strict | 0.947 (D04 stage «P») | **1.000** | — |
| Codes after corrector (n = 11) / room numbers (n = 507) | 0.909 / 0.917 | 0.909 / 0.917 | registry prior (AG-02B) |
| Orientation / routing / text-gap lines | 48/48, 11/11, 0.971 | 48/48, 11/11, 0.971 | — |
| Zones vs GT v2 (IoU ≥ 0.3): seal / QR / handwriting, false alarms | — | 7/8, 9/9, 13/25; 0 / 0 / 3 | — |
| 100 pages F0006 (10 workers, cold) | 76.2–77.0 s | 89.0 s (+39 stamp pages now read, zones) | ≤ 180 s |

Hidden object, authorised AG-02A timing smoke only (50 random pages of 36 files, content never looked at, all
outputs deleted): 55.9 s, 53.7 pages/min, 35 of 50 pages with OCR, 0 failures; ≈ 5 h for its 15,961 PDF pages at
this rate (10 workers, load ≈ 9 from other agents).

## Measured results M0 (pipeline `docproc-2.2.0`, 2026-09-28, M2 Max 12 cores; no other heavy jobs, an idle emulator/simulator running)

Benchmark `tests/data/recognition_benchmark.json`; runs `runs/ag02a-final2-bench-{coreml,cpu}`,
`runs/ag02a-final2-medium-modes.json`. Character accuracy (CA) = 1 − (edits + deletions) / N, strict
(whitespace removed only); 95 % CI by bootstrap over regions/pages.

| Measure | CoreML det + CPU rec | CPU only | Report 96 | Gate (97 §3.6) |
|---|---|---|---|---|
| A: vector pages, 30 regions, 32,263 chars | **0.971** [0.957–0.980] | 0.971 [0.955–0.980] | 0.967 [0.952–0.978] | ≥ 0.965, CI low ≥ 0.95 |
| B+D: real scans + outlined text, 6 pages, 7,316 chars (hand GT) | **0.974** [0.967–0.986] | 0.974 [0.965–0.989] | 0.968 [0.955–0.983] | ≥ 0.965 |
| Scan key fields EM strict / relaxed (n = 42) | 0.905 / 0.952 | 0.929 / 0.976 | 0.905 / 0.952 | relaxed ≥ 0.93 |
| Document codes after the corrector, vector stamps (n = 11) | 0.909 | 0.909 | 0.91 | ≥ 0.95 with the registry prior (AG-02B) |
| Outlined RD stamps: code/stage/sheet/sheets (n = 19) strict / relaxed | 0.947 / 1.000 | 0.947 / 1.000 | 19/19 after correction | — |
| Orientation, 12 pages × 4 turns | 48/48 | 48/48 | 6/6 | 100 % |
| Text in text-layer gaps captured, gold RD sheets F0201 p17/p18, F0202 p17 | 0.971 (2,640/2,718 lines) | 0.972 | — | ≥ 0.90 |
| Gold rooms on their cited RD pages | 9/10 (314 is drawn on p20, not the cited p18) | 9/10 | — | — |
| Page routing of the routing-test pages | 11/11 | 11/11 | — | — |
| Scan page, 1 process × 4 threads | 1.89 s | 3.65 s | 10.9 CPU-s | — |

Second detector: `union` (production) vs the 96 proposals, CoreML — A 0.971 / 0.964 (`fallback`) / 0.964 (`off`);
B+D 0.974 / 0.967 / 0.967; B06 (seals) 0.982 / 0.927 / 0.927; time per scan page 1.89 / 1.70 / 1.67 s. The
96 page-level fallback never fires on this set (B06's mean line score stays above 0.9).

Throughput (`inspector-batch recognize`, 10 workers, cold cache):

| Input | CoreML | CPU |
|---|---|---|
| F0006 pp. 1–100, Новослободская ИД binder (55 scans, 39 stamp separators, 6 vector; 19 pages at 90°) | **76.2 s** (78.7 p/min) | 146.3 s (41.0 p/min) |
| F0006 + F0007 + F0008, 340 pages (177 OCR pages) | 183.4 s (111 p/min; 57.9 OCR p/min) | — |

§11 target: 100 pages ≤ 180 s — met on both providers. Stage split of OCR time (340-page run): recognition
78 %, orientation 12 %, detection 9 %, render 1 %.

## Sub-ownership inside the package

| Area | Owner | Modules |
|---|---|---|
| Recognition core, router, repair, orientation, runner, cache, bench | AG-02A | everything present today |
| Code corrector (rules + registry prior), title blocks, QR, room index, CAD layers, tags | AG-02B | `codefix.py` (shared with AG-02A), new `layout/…` |
| Typed tables, ИД binders and parsers, NLP | AG-02C | new `tables/…`, `id/…`, `nlp/…` |
