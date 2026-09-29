# inspector_compare

Owner: **AG-04** (see CLAUDE.md). Comparators, the element-family router, the atomic split, anchor pages, the
132-row precedence, the submission exporter (full, strict, sidecar) and the Приложение 2 protocol (JSON, DOCX,
PDF). Implements `inspector-batch compare` and `inspector-batch export`.

```bash
cd services/ml
# development fixture (hand-made layout artifacts of Тюменская 5, see fixtures/tyumen)
uv run --locked inspector-batch --run-id m1-dev compare --object OBJ-TYUMENSKAYA-5-GOLD-SEED --fixture tyumen
uv run --locked inspector-batch --run-id m1-dev export  --object OBJ-TYUMENSKAYA-5-GOLD-SEED
uv run --locked inspector-batch --run-id m1-dev-score score --object OBJ-TYUMENSKAYA-5-GOLD-SEED --pred ../../runs/m1-dev/submission
# real run: compare reads runs/<run_id>/layout, tables, values written by AG-02B/AG-02C in the same run
make run-train OBJECT=OBJ-TYUMENSKAYA-5-GOLD-SEED
```

## compare

Inputs (run_layout.yaml paths of the run, or `--fixture` / `--layout-dir` / `--tables-dir` / `--values`):
`layout/<file_id>.json` (layout_artifacts), `tables/<file_id>.json` (table_artifacts), `values/<object_id>.jsonl`
(extracted_value). Artifacts of another object or with a sha256 that differs from the manifest are ignored.

Outputs: `findings/<object_id>.groups.jsonl` (finding_group) and `findings/<object_id>.jsonl` (finding).

Pipeline (`engine.py`):

1. **Room observations** (`observe.py`): per stage and element family, the labels attributed to each room token
   (tag grammar in `tags.py`: homoglyph folding «B2.1» → «В2.1», compounds «В2.7,8,9», «П17.1, 17.2»), and the
   family-relevant sheets where each room is drawn (sheet titles by topic, or sheets that carry the family's tags).
   Room names come from the room index and the EXPLICATION tables of AG-02C (`tables/<file_id>.json`); the name a
   token carries most often is printed in the rationale («пом. 147 (Лаборантская тип АВ)»), and every name feeds
   the room rules (a system mark counts as a unit only in a room named a vent chamber). A tag instance (page, box,
   labels) that the layout links to two or more rooms is *ambiguous* for per-element families.
2. **Comparators** (`comparators.py`) per room and axis (PD→RD, RD→ID, PD→ID):
   `LABEL_MULTISET` (supply units in a vent chamber), `SYSTEM_COUNT` (branches per system prefix: RD renumbers
   branches), `PRESENCE` (warm floors by anchor phrases). Outcomes: ELEMENT_MISSING, CONFIGURATION_CHANGED (emitted),
   ELEMENT_ADDED / RENUMBERED (context, never findings), UNRESOLVED (room not drawn on any relevant actual sheet:
   abstain — absence is never concluded without coverage). **Directional rule for rooms**: the actual side keeping
   every expected label and adding others is an addition for units and branches alike (97 §2.10). **Ambiguous
   attribution**: a violation must also hold on the firmly attributed tags; otherwise the room abstains
   (AMBIGUOUS_VALUE). **Evidence rules from the whole-object run** (compare-rules-m1.3, each with a positive-twin
   test in `tests/test_compare_evidence_rules.py`):
   - *title-authoritative coverage* (`title_authoritative_coverage`): a sheet whose title names configured topics
     proves absence only for those topics — a heating plan with a vent-shaft layer or a stray vent mark never
     proves «no ventilation» (ИД F0198 «План 2-го этажа (отопление)» had made 30 floor-2 rooms «missing»);
   - *stable marks* (`stable_mark_axes: [RD_ID]`): the ИД executive drawing is a copy of the RD sheet with the same
     marks, so a mark missing from a room but printed elsewhere on the room's ИД sheet is an attribution
     disagreement (abstain AMBIGUOUS_VALUE, note MARK_ELSEWHERE_ON_SHEET). PD→RD is not a stable axis: RD
     renumbers branches by design (the gold rooms 140/142 lose В2.7–В2.9 while RD reuses those marks in 198);
   - *bridged axis* (`bridged_axes: {PD_ID: RD}`): with RD present, a room that RD covers is compared on PD→RD and
     RD→ИД only; the direct PD→ИД comparison would count the RD renumbering twice;
   - *anchor present*: an ELEMENT_MISSING whose actual room still shows the element by its family anchor phrase
     («М.О.», местный отсос) abstains (AMBIGUOUS_VALUE, note ANCHOR_PRESENT) — the ИД copy omits the room
     air-balance boxes that carry «В17.1» but keeps the «М.О.» units;
   - *discipline scoping* (`discipline_scoped_families`): a family's elements and coverage come only from the
     documents of its disciplines (change map `element_families[].disciplines`, file marks from `disciplines.py`):
     the automation volume ИОС5.5.5 (СС) prints the fans of vent chamber 403 and had made 403 a «changed» room
     under both IOS4-078 and IOS4-079;
   - *vent-chamber marks are units* (`VENT_EXHAUST_BRANCH.exclude_room_name_pattern`): in a vent chamber «В9.1» is
     the fan standing there, compared by the unit family, never again as a local-exhaust branch;
   - *unit relocation* (`RELOCATED`, context): a unit mark the actual stage shows in another room of the unit
     family (another vent chamber) was moved (97 §2.10). No room of Тюменская triggers it (0 rooms); kept because
     the change map treats relocations as context and the unit comparator had no such branch.
   Ablation on the whole-object run `runs/m1-e2e-tyumen-m13` (57 layouts on real OCR; TP stays 10/10 in every
   row): all rules → 3 extra keys; without title coverage 17; without stable marks 27; without the PD→ИД bridge 6;
   without discipline scoping 5; without the vent-chamber exclusion 3 (no effect alone). On the 11-file run
   `m1-e2e-rec-prio` the anchor rule removed 2 (RD→ИД 189, 192) and the differing-label ambiguity rule removed
   the IOS4-078 hedge twin of room 012. The 3 remaining extras are recognition errors (see the M1 report).
   **Value comparators** (`valuecmp.py`) evaluate the seed
   rules PAIRWISE_DELTA / ORDINAL_COMPARE / ENUM_CHANGE on extracted values with **directional triggers**
   (DECREASE/INCREASE/DOWNGRADE; the opposite direction is an IMPROVEMENT, context only).
3. **Router**: seed `change_matrix_map.json` (element family × DiscrepancyType → catalog code or FREE-<TOPIC>,
   parameter_mapping_status, comparison_result, value templates, hedge codes). Non-emitting routes are context.
4. **Groups and the atomic split**: one group per (axis, code, comparison result, family), one atomic finding per
   room with the exact printed token («012»). A key (code, room) is emitted once (axis priority PD↔RD first, so
   id_value stays null for pairwise PD↔RD checks as in the gold).
5. **Anchor-page rule** (93 §2.8): one page per stage per group — among the pages depicting the group's rooms, the
   page depicting most rooms of the whole finding (axis × code × family, `anchor_scope: system`; declared as learned
   from the gold: both groups of «пункт 3» share RD p18), then most of the group's own rooms; ties by the strength
   of the discrepancy, layer purity, the sheet title, then the page order. Per-room pages are kept in
   `location_pages` (room 314 of the gold: drawn on RD p20, anchored on p18).
6. **FREE-* groups**: router FREE groups plus AG-07's hook, evidence-bound only (PD and RD anchors), capped by the
   seed policy (5), numbered per group within object and topic by (PD file, page, first room) → FREE-HEATING-001.
7. **Bounded top-2 hedge** (97 §1.6): a twin with the runner-up code when p(runner-up) ≥ 0.1, within 20 % of the
   emitted approved-critical checks (counted as inspector-score counts hedges). Room findings take the route's
   hedge code (prior by route basis: GOLD/MATRIX 0.05, ANALOGY 0.25, plus 0.15 when the element family is
   ambiguous — the room's *differing* labels are read by two families of the topic, e.g. «В2.1» in a vent chamber
   is an exhaust unit and a branch; a chamber that merely holds supply units and branches is not ambiguous); value findings take the next code of the parameter's seed hedge group (prior by group kind:
   DUPLICATE 0.30 — AR-040/PPM-104/ODI-116, AR-041/PPM-105 …; PARTIAL_DUPLICATE 0.15; SAME_SYSTEM 0.05). The
   highest p is hedged first; the gold routes of Тюменская stay unhedged (p 0.05).
8. **132-row precedence** (`precedence.py`, 97 §2.6): one OBJECT row per catalog parameter without a violation row:
   no sufficient stage set → COMPARISON_IMPOSSIBLE; violation rows win; a missing required stage →
   MISSING_DOCUMENT (RD > PD > ID); a declared but unreadable stage → COMPARISON_IMPOSSIBLE; verified by a comparator
   → NO_VIOLATION; otherwise COMPARISON_IMPOSSIBLE (value not extracted; config `unverified_status`). Stage
   availability uses discipline marks (`disciplines.py`) from title-block марки, manifest sections and file names.

Config (`--config`, JSON/YAML, keys of `CompareConfig`): families, topic page patterns, axes, hedge policy, FREE cap,
negatives (`emit_object_rows`, `object_row_when_violated`, `unverified_status`), `add_location_pages`,
`anchor_scope` (`system` | `group`), `stable_mark_axes`, `title_authoritative_coverage`, `bridged_axes`, `discipline_scoped_families`, confidence thresholds (critical 0.30, substantial 0.50). The seed policy (hedge threshold, budget, FREE cap) is read from
AG-03's seed. `config_hash` covers the config, the rule version and the seed/template hashes; every finding
records it in `decision_trace.compare_config_hash`.

## export

`submission/<object_id>.json` (organizer schema + gold-named extras), `submission-strict/<object_id>.json`
(organizer fields only), `submission/<object_id>.sidecar.json` (a RunManifest of one object: input_manifest_hash,
config hashes, versions, per-file status, missing-on-disk list, freeze_tag). Nothing is written unless the
submission passes the organizer, strict and extended schemas, unique keys, 132-parameter coverage and
inspector-score's integrity rules R1–R14 (exit 4 otherwise). `--emit-negatives none` exports the violations only.

Protocol (`protocol/`): `builder.py` → `protocol/<object_id>.json` (contract `protocol`: Приложение 2 sections 1–7
verbatim with the «Тип проверки» line and the added summary rows, Приложения А/Б/В, submission checks, a
date-independent `content_sha256`); `docx_render.py` → DOCX in the Приложение 2 look (A4 portrait, margins
20/20/30/15 mm, Segoe UI, emoji markers); `html_render.py` + `pdf.py` → PDF by headless Chromium when installed
(the engine the Gotenberg route would use) or by PyMuPDF Story (always available; emoji mapped to symbols).
Texts come from AG-03's `seed/recommendation_templates.json` (rules R1–R8), printed with «Проект рекомендации (до
подтверждения инспектором): » in a preliminary protocol. «Объект:» / «Адрес:» come from the object name printed
most often in the title blocks (split at the address), else the manifest corpus name; «на плане ОВ1» takes the марка
from the title-block шифр, else from the шифр in the file name. Evidence cards list every source on its own line
with the ТЗ §9.2 fields (stage and role, file, page and sheet, шифр, редакция, approval status, full SHA-256,
regions). Under each card, `protocol/thumbs.py` embeds crops of the cited pages (each page rendered once with
PyMuPDF, 900 px wide, 62-colour palette) with a blue frame on the expected regions and a red frame on the actual
ones: pictures in the DOCX, data URIs in the HTML/Chromium PDF (the PyMuPDF fallback omits them). They are views,
never separate run files (`CardSource.thumbnail` stays null); `--no-thumbnails` turns them off, and a page that
cannot be read is skipped. Room geometry comes from plan and schematic labels and tags, never from explication rows.
Empty sections print «Не выявлено.». `export` reads the same layout/table inputs as `compare` (from the
groups' `decision_trace.inputs`), so stage resolution and the header match.

PDF route: LibreOffice and Gotenberg (Docker) are not available on this host, so DOCX → PDF is not used. The PDF is
printed from the same HTML view: headless Chrome/Chromium when found (`--pdf-engine auto|chromium`), else PyMuPDF
Story (`--pdf-engine pymupdf`, a Python library already in the lock; emoji become symbols). Fonts: the view declares
Segoe UI → Selawik → system sans; Selawik and Noto Color Emoji are not installed here (see open issues).

## Integration points

- **AG-07 (FREE-*)**: expose `inspector_hypothesis.compare_hook.free_finding_groups(*, ctx, observations, config)`
  returning finding_group dicts (matrix_scope FREE_SEARCH, evidence_bind_status BOUND, anchor_evidence PD and RD);
  compare validates, de-duplicates against its own FREE groups, caps and renumbers them.
- **AG-02B (layout)**: units in rooms as `EQUIPMENT`, branch/system marks as `VENT_SYSTEM`, air terminals as
  `AIR_TERMINAL`, warm-floor loops/labels as `HEATING_SYSTEM`, each with `room_token`; sheet titles, document
  codes, sheet numbers and `object_name` in `title_blocks`; revision clouds with `rooms_covered` raise the
  confidence of absences under them. One tag instance linked to several rooms is treated as ambiguous (never
  evidence of a per-room change); link it to one room when the leader is resolved.
- **AG-02C (tables)**: `tables/<file_id>.json` EXPLICATION rows (`room_no` raw as printed, `name`, kind DATA) name
  the rooms.
- **AG-02C (values)**: `values/<object_id>.jsonl` with `param_code`, `location`, `value_norm` (`unit`, `rank` for
  ordinal classes) and `quality_flag` OK; the first candidate per stage is compared.

Tests: `tests/` (fast; organizer-data tests are marked `data`, the Chromium PDF test `slow`).
`fixtures/tyumen/build_layout.py` regenerates the Тюменская layout fixture from the 95 page facts;
`fixtures/tyumen/build_tables.py` regenerates its tables fixture (explications of F0201 p17–18 and F0202 p17 from
the text layer). A data test checks every table row and the PD title-block cells against the PDF text layer.
