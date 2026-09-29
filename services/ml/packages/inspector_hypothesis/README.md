# inspector_hypothesis — Module 5 «свободный поиск гипотез»

Owner: **AG-07** (see CLAUDE.md). Design: `docs/analysis/07_free_hypothesis_search.md`, with the rulings of 97 §2.10
(routing, FREE only for matrix gaps), 93 §3.7 (FREE codes), 90 C-53/C-55 (Logical_Rules, IAI-Logic).

It delivers, per object:

1. **FREE-<TOPIC>-<NNN> findings**: evidence-bound element changes outside the matrix, as contract `FindingGroup` and
   atomic `Finding` objects (`matrix_scope FREE_SEARCH`, `protocol_status WARNING`, criticality «Существенное
   (предписание) — требует утверждения»). On Тюменская this is the gold group G-TR-002, FREE-HEATING-001.
2. **Logical_Rules** in IAI-Logic v1, three-valued, with 12 seed rules (`data/logical_rules.json`).
3. **SUSPICION records** (ТЗ §9.5 fields verbatim) and their protocol rows: Приложение 2 Раздел 6 (`SuspicionRow`)
   and Приложение А.5 (`HypothesisRow`). A suspicion is never a violation: it is not counted in «Выявлено
   нарушений», never a training label, never sent to РиН.

There is no batch command: AG-04 calls the engine from `compare`/`export`.

## API (for AG-04)

```python
from inspector_hypothesis import HypothesisInputs, run_hypotheses

inputs = HypothesisInputs.from_run(ctx.run_dir, object_id)  # PageTokens, layout, tables, values via RunLayout
result = run_hypotheses(inputs)
result.free_groups  # list[FindingGroup] → findings/<object_id>.groups.jsonl (with the matrix groups)
result.free_findings  # list[Finding]      → findings/<object_id>.jsonl
result.section6_rows(first_card_no)  # list[SuspicionRow], Раздел 6, cards Б.<n>… in the same order
result.a5_rows(first_card_no)  # list[HypothesisRow], Приложение А.5
result.ai_suspicions_count  # Раздел 2 «Подозрений ИИ (свободный поиск)»
result.suspicions  # list[Suspicion] (§9.5 + 90 §3.3 #8), .dump() for JSON
result.stats, result.versions  # detector status, timings, counts; rules sha256, config hash
```

For the protocol builder (Приложение 2 Раздел 6 lists **every** suspicion, 93 §5.4; А.5 is its superset), after the
rows AG-04 renders from FREE finding groups:

```python
from inspector_hypothesis import compare_hook

extra = compare_hook.protocol_suspicions(
    ctx=ctx,
    run_dir=run_dir,
    rendered_free_groups=free_group_dicts,
    start_no=len(section6_rows) + 1,
    first_card_no=next_card_no,
)
# contract SuspicionRow / HypothesisRow dicts: Logical_Rules suspicions and unexported FREE candidates
section6_rows += extra["section6_rows"]
a5_rows += extra["a5_rows"]
# the §9.5 records themselves (a SUSPICIONS artifact)
records = compare_hook.suspicion_records(ctx=ctx, run_dir=run_dir)
```

Both reuse the result `compare` computed in the same process and never raise (`extra["error"]` says why a list is
empty). Verified against AG-04's real `ObjectContext` on the Тюменская integration run (7 rows after the FREE one).

- The FREE rows project to the submission like any Finding (the tests validate them against
  `submission.organizer` and `submission.strict`). They are exported as VIOLATION_PRESENT/WARNING (97 §2.6: an
  evidence-bound SUSPICION); in the protocol they belong to Раздел 6, as in the contracts' protocol example.
- A detector failure never fails the run (`stats.detector_status`, CON-39).
- `inspector_hypothesis.testing` builds synthetic inputs (the Тюменская warm-floor scenario, tables, layouts) for
  tests without organizer data.

Developer tool (writes nothing unless `--out`; refuses the hidden object):

```bash
cd services/ml
uv run --locked python -m inspector_hypothesis ../../runs/<run_id> --object OBJ-TYUMENSKAYA-5-GOLD-SEED
```

## FREE path (detector HR-SEM-005, method SEMANTIC_DISSONANCE)

For every element family whose ELEMENT_MISSING change routes to FREE-* in the seed change map (a matrix gap:
WARM_FLOOR, HEAT_POINT, SANITARY_FIXTURE, LIGHTING_FIXTURE, PASSENGER_LIFT):

1. **PD assertion**: a PD sentence names the element (seed anchors, light stemming: «теплые полы», «“теплый пол”»,
   «Multibox») and lists rooms («(пом. 267, 270, 271, 272)», tokens as printed). Negated sentences and table rows /
   label soup (`textmatch.is_prose`: Russian words must dominate codes and symbols) are skipped; a room list closer
   to another family's anchor is left to that family. Drawings confirm but never assert alone: plan labels next to
   a leader are not reliable (on F0171 p99, rooms 266/268/277 sit as close as the asserted ones).
   **Two channels**: our PageTokens and AG-02C's `pd.element_room` values (97 §3.3). AG-02C's TEXT assertions pass
   the same negation, prose and nearest-family checks and keep only the rooms both readings agree on (or, without a
   parseable list, the rooms printed in the sentence); TABLE rows are taken as they are; LABEL and SPEC values only
   confirm (a LABEL page competes as the PD anchor and can confirm the drawing). A twin on the same page
   corroborates without raising the confidence; `decision_trace.assertion_sources` records the channels.
2. **RD absence**, three-valued: the anchors are searched in every recognised page of the RD of the family's
   discipline (ManifestSection labels, e.g. ОВ → OV) and in RD files of an unknown section. An anchor next to a
   room label (nearest room within 0.1 × the shorter page side) keeps the element in that room. Absence is
   `DOCUMENT` (every page of the discipline RD read, no anchor), `COUNTERPART` (only the RD document holding the
   anchor page read in full), `ROOM` (the element occurs elsewhere in the RD), or `UNKNOWN`. Unread pages never
   prove absence. A mention inside a removal statement (a negation within 60 characters in the same sentence:
   «Исключены теплые полы в пом. 267…») is not presence: it supports the absence (+0.05, quoted in the rationale).
3. **Anchor pages**, one per stage per group (97 §2.5): the page with the most rooms of the group; ties are broken by
   drawing format, the page's and document's topic keywords (a heating plan beats the ventilation plan of the same
   floor: «отопление» vs «вентиляция» in the OCR tokens) and a CAD revision cloud over the rooms (AG-02B layout).
4. **Confidence**: 0.55 + 0.15 (PD sentence) + 0.10 (the PD anchor is a large-format drawing showing the element
   and most rooms) + 0.05 (several PD pages) → × 1.0 / 0.85 / 0.7 for DOCUMENT / COUNTERPART / ROOM absence
   (× 0.9 when the RD anchor shows a minority of the rooms) + 0.10 for a revision cloud + 0.05 for an RD removal
   statement; cap 0.95. Evidence carries the cited page's own cipher and sheet (`HypothesisInputs.page_code`).
5. **Export**: only BOUND groups with DOCUMENT or COUNTERPART absence and confidence ≥ 0.7; at most 5 groups per
   object (seed policy `max_free_groups_per_object`), the most confident kept. Numbered per topic in the order
   (PD file_id, PD anchor page, first location): one heating group is exactly FREE-HEATING-001. Values come from
   the change map templates («Тёплый пол предусмотрен» / «Тёплый пол отсутствует»), the recommendation from the
   FREE templates (`data/free_recommendations.json`, vendored from the review-phase staging, text origin
   AG03_DRAFT). Candidates with proven absence that are not exported stay SUSPICIONs of Раздел 6 with the reason;
   PRESENT, NO_RD and UNKNOWN candidates stay in `stats.free.not_exported`.

## Logical_Rules (IAI-Logic v1)

A JSONLogic subset (`var missing missing_some and or ! !! if == != < <= > >= in some all none filter map count sum
merge + - * / min max abs round`) evaluated by a safe interpreter with Kleene three-valued logic: a missing fact is
UNKNOWN; a rule emits only when its condition is TRUE and its expected clause is FALSE. `^path` reads the root facts
inside an iteration. Rules are data (ТЗ §10 #9 fields `id, rule_name, condition, expected, normative_base,
is_active` plus ours) and are evaluated per object or per item of a fact collection.

| Code | Rule | Facts |
|---|---|---|
| HR-LOG-001 | Лифт при этажности более 10 (пример ТЗ §9.5) | PZ-007; lift / lift-shaft presence in RD (full coverage) |
| HR-LOG-002 | Ссылка ИД на документ, отсутствующий в составе документации | АОСР references × registry codes |
| HR-LOG-003 | Σ поэтажных итогов = общая площадь (PZ-002.b) | floor totals of explications, PZ-002 |
| HR-LOG-004 | Коэффициент застройки согласован с площадями (PZ-019.c) | PZ-001, PZ-019, ТЭП plot area |
| HR-LOG-005 | Σ площадей экспликации = итог (PZ-003.c) | EXPLICATION sum blocks |
| HR-LOG-006 | Количество квартир = Σ квартирографии (PZ-010.b) | PZ-010, PZ-011 |
| HR-LOG-007 | Работы в ИД без основания в РД (пилот IZM12) | UNDOCUMENTED_WORK families: ИД hits vs RD presence |
| HR-LOG-008 | Отклонение на исполнительной схеме в пределах допуска | DEVIATION rows not mapped to a matrix code |
| HR-LOG-009 | Акт ссылается на неактуальную редакцию РД | АОСР «изм. N» × title-block revisions and dates |
| HR-LOG-010 | Акт не ранее выпуска редакции РД | act date × change-row date |
| HR-LOG-011 | Подзона «в том числе» не учитывается в итоге повторно | EXPLICATION sum blocks with SUBZONE rows |
| HR-LOG-012 | Высота здания правдоподобна при этажности | PZ-007, PZ-008 |

Facts come from contract artifacts only (`facts.py`):

- **EXPLICATION** sum blocks closed by SUBTOTAL/TOTAL rows, «в том числе» rows apart. Tables split across columns
  (F0201 p17: «ИТОГО: 524,0» closes the rows of two side-by-side tables) are chained by title and page. A TOTAL over
  group totals («ИТОГО 1-ый этаж») becomes a GRAND block checked against the groups; when those do not add up the
  block is `hierarchy_unresolved` and no sum rule applies. HR-LOG-005 also stands down on gaps > 10 % of the total
  (a recognition gap, not arithmetic).
- **AOSR** acts with every cipher of п.2 and the project ciphers of п.4 (codes with a stage part; certificates are
  not documents of the set), one citation per cipher, the revisioned one kept; a glued «No»/«№» is dropped.
- **Registry** per stage: every code of a file's title blocks with its own revisions, dates and the page of each
  «Изм.» row (a PDF may bundle documents: F0201 holds «…-РД-ОВ1» and «…-РД-ОВ1.С»); a title block whose code was not
  read belongs to the nearest preceding page's document; file names prove membership only, never a revision. Dates
  in «dd.mm.yyyy», «dd.mm.yy» and ISO (AG-02C writes acts' dates in ISO).
- DEVIATION, TEP, PROJECT_COMPOSITION tables, ExtractedValue by catalog code, element presence.

**Normative references** were checked against the review-phase norm verification (`docs/analysis/norms_staging`,
2026-09-27): each rule carries `norm_check` (CONFIRMED / DOCUMENT_CONFIRMED / CORRECTED / NOT_IN_STAGING).
HR-LOG-004 now cites СП 42.13330.2026 (the 2016 edition was replaced on 12.07.2026); a test fails if any rule or
FREE template cites an edition the verification marks outdated. `verified` stays false until expert review (U-18).

**Dedup** (ТЗ §9.5 «объединяются только внутри одного объекта и сопоставимых редакций»): by subject within the cited
revisions, or by content when the rule declares `scope.dedup` — the same explication reprinted on the plans of ОВ1
and ОВ2.1 is one suspicion with every copy as evidence (`explanation.copies`).

## Tests

`make test` runs them (fast, ~4 s): IAI-Logic truth tables and safety, anchor/room/number/code matching, the 12 rules
on contract artifacts, the FREE path on the synthetic Тюменская scenario (gold shape, anchor choice, guards, cap
and numbering, contract and submission schema validation), both assertion channels and removal statements
(`test_free_channels.py`), the real Тюменская table and act structures with their real values
(`test_real_structures.py`), suspicion records against the proposed schema, the compare/protocol hooks, run
directory loading. Tests marked `data` use the organizer package when present: HR-LOG-005 on the real ALT79B
pilot explication (Σ 2795,04 vs 2797,27), HR-LOG-011 on the real Тюменская F0201 p18 explication
(1049,5 + 30,4 = 1079,9), and gold parity of FREE-HEATING-001 on the real F0171/F0202 text layers. The slow E2E
test reads a run directory: `INSPECTOR_HYP_E2E_RUN=runs/<run_id> make test-slow`.

## Real data (Тюменская, 2026-09-28)

Integration run `runs/m1-ag07-integ` (git-ignored): PageTokens of F0171 (177 pages), F0202 (36) and F0201 p17–20,
AG-02B layouts (57 files), AG-02C tables and values (6 files). `python -m inspector_hypothesis` takes 0.9 s
(217 pages scanned). Result: FREE-HEATING-001 on rooms 267/270/271/272, anchors PD F0171 p99 (л.21) and RD F0202 p17
(л.4), confidence 0.723 (COUNTERPART: F0201 not fully recognised; DOCUMENT gives 0.85, a revision cloud +0.10),
plus 7 Раздел 6 suspicions, all real: the act 1/ОВ citing РД-ОВ1 изм. 3 while изм. 4 of 11.08.2024 is current
(HR-LOG-009); its п.4 cipher typo «АНО1301211-Р-ОВ1» (HR-LOG-002); four «в том числе» double counts (30,4; 65,8;
100,0; 103,6 м², HR-LOG-011, each merged over its 3 copies); the F0202 basement total 532,10 against rows of
536,59 м² (HR-LOG-005). `inspector-batch compare → export → score` on that run: the hook's group is exported,
4 TP / 0 FP, values, statuses and pages correct.

## Proposed contract additions (for AG-00)

- `schemas/suspicion.proposed.schema.json`: the SUSPICION record, for adoption as `packages/contracts/schemas/
  suspicion.schema.json` with an artifact kind `SUSPICIONS` → `findings/{object_id}.suspicions.jsonl` (written by
  AG-04's export from `compare_hook.suspicion_records`, imported by the web into `suspicions`).
- `EvidenceCard.parameter_code` is required and must be a catalog or FREE code, so a Logical_Rules suspicion (no
  parameter) cannot get the card its `SuspicionRow.card_ref` points to: make `parameter_code` nullable for
  suspicion cards and add `rule_code` / `suspicion_key`.
