# inspector_registry

Owner: **AG-01** (Ingestion, Registry & Integrity). The registry of the batch mode: the organizers'
`document_manifest.jsonl` is the registry, files are identified by sha256 (97 §2.12).

## What it does (M0)

| Module | Content |
|---|---|
| `manifest.py` | `Registry`: manifest + `split_policy.json`; rows validated against `manifest_row`; objects, files, stages, sections; excluded ids (F0149, F0418) dropped at load and refused on lookup (`EXCLUDED_FILE_REFERENCED`); citability (`is_citable`, `page_in_range` = R6, `stage_accepts` = R7); duplicate-group representatives; `input_manifest_hash` |
| `resolver.py` | `PathResolver`: manifest row → local path (NFC, then NFD, then NFC+casefold per path component), `LocalFileStatus` (PRESENT / RECOVERED / MISSING_ON_DISK — never MISSING_DOCUMENT), lazy sha256 cached by path+size+mtime, search by sha256 in the recovery ledger (`data_utf8/_recovered_files.txt`), `data_recovered/` and unclaimed files; altered files → `REGISTRY_HASH_MISMATCH`; two rows with different sha256 on one inode → `REGISTRY_AMBIGUOUS_MATCH` |
| `archives.py` | zip (Python `zipfile`: UTF-8 flag, cp437→cp866, Info-ZIP Unicode Path field) and 7z/RAR4/RAR5 (libarchive-c, the library behind `bsdtar`; never `unrar`); bidi/Cf stripping; guards: ≤ 5,000 members, ≤ 2 GiB declared *and* actually read, ratio limits, traversal/absolute/link names; member sha256, magic-byte type, DWG header version; `extract_member` for safe single-member extraction |
| `pdfprobe.py` | page count, encryption/repair, page-1 text and image fingerprints, text of the first pages (for stage signals) |
| `stages.py` | stage of RD_ID_MIXED / UNKNOWN files from folder names, file name and first-pages text (nominative-form rules; «П-ИД»/«Исходные данные» → ПД); MetaSource `EXTRACTED_UNCONFIRMED`; for PD/RD/ID rows the manifest wins and a strong disagreement is reported (`META_CONFLICT`, info) |
| `twins.py` | DWG/DOCX ↔ same-folder PDF twin by name similarity, sheet number and member/page counts, with confidence; per-member page hints when unambiguous |
| `duplicates.py` | exact (sha256) and near duplicates (page count + page-1 text or image fingerprint); page-1 matches with different lengths as revision hints |
| `inventory.py` | the per-object report behind `inspector-batch inventory` |
| `report.py` | report validation (draft schema `schemas/inventory_report.schema.json`) and `run_manifest.json` (contract `run_manifest`) |
| `api.py` | `open_registry()` for other packages |
| `flags.py` | `IntegrityFlag`: every flag is a code from `packages/contracts/errors.yaml` rendered in Russian |

## CLI

```bash
cd services/ml
uv run --locked inspector-batch inventory --object OBJ-TYUMENSKAYA-5-GOLD-SEED   # one object
uv run --locked inspector-batch inventory                     # TRAIN objects (default)
uv run --locked inspector-batch inventory --all --verify-sha256   # all objects incl. hidden (inventory is allowed)
```

Outputs in `runs/<run_id>/`: `inventory/<object_id>.json` (one per object), `inventory/index.json`
(counts, timings, cache stats) and `run_manifest.json` (merged with an existing one of the same run id).
`--verify-sha256` hashes every file once; later runs reuse `.cache/registry/registry_cache.sqlite`.
`--no-cache` disables the cache. Reports of TEST_HIDDEN objects omit the text snippets behind stage signals.

## Tests

- `uv run --locked pytest packages/inspector_registry -m "not slow"` — synthetic fixtures (zip with raw cp866
  names, 7z with bidi names, a hand-built RAR4 with OEM names, Cyrillic PDFs) plus fast `data` tests on the two
  TRAIN objects (skipped without organizer data).
- `uv run --locked pytest packages/inspector_registry -m slow` — full sha256 of both TRAIN objects (also run by
  `make test-slow`).
- The hidden-test object is never used in tests.

## Proposals for packages/contracts (owner AG-00)

- Adopt `schemas/inventory_report.schema.json` (a test keeps its enums equal to `enums.yaml`).
- Error codes that would describe inventory findings more precisely than the current reuse:
  `PAGE_COUNT_MISMATCH` (now `MANIFEST_ROW_INVALID`), `NEAR_DUPLICATE` (now data only),
  `STAGE_UNRESOLVED` (now data only), `DWG_TWIN_NOT_FOUND` (now data only),
  `ARCHIVE_MEMBER_UNSAFE_PATH` (now `FILENAME_INVALID`, whose template has no file name).
- Enums for values the report uses as plain strings: signal source (`folder`/`name`/`text`), resolver
  `found_via`, member `name_encoding`, duplicate basis (`text`/`image`).
