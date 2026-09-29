# N-GOLD labelling protocol (N-GOLD-AGENT-v1)

Owner: AG-10. Applies to our own labels of the unlabeled train object (Новослободская), dev set **N-GOLD**,
badged «разметка команды». The labels are for measuring precision, the false-positive rate and status accuracy
before the hidden run (95 §5.1–5.3, 97 §3.2 M2). They are never organizer gold and never touch the hidden object.

## 1. Roles

| Role | Who | What they see | What they write |
|---|---|---|---|
| Item author | Seed (95 §4.4), the system's candidate list, the random/stratified generators | Everything | The item: code, location, pages to start from, optional `system_hypothesis` |
| Independent labeller | An agent that did not build the item or the system output (preferred), or AG-10 | **Only the blind packet** (§2) | One annotation per item (§3) |
| Spot-checker | The user (≈25–30 items, 25–40 min) | The spot-check bundle: questions and page images; the agent labels only after filling the sheet | `sheet.csv` → HUMAN annotations |
| Double labeller | A teammate, 15 % of the items (optional) | Blind packets | HUMAN annotations |
| Adjudicator | The tool (§4), then the user for disagreements | All annotations | The adjudicated `label` |

## 2. The blind packet

`inspector-score ngold packet ID [--tiles 3x2] [--extra FILE:PAGE[:x0,y0,x1,y1] …]` writes
`runs/ngold/packets/<ID>/` (git-ignored; organizer pages never leave the machine):

- `question.json`: object, parameter code, catalog name, unit, trigger, criticality and sources, the location as
  asked, the pages to start from, the label vocabulary, the task text;
- `<file>_p<page>.png`: the page at 100 dpi, optional tiles at 200 dpi, optional clips;
- `<file>_p<page>.txt`: the page's own text layer (organizer data, not a system output).

The packet never contains `system_hypothesis`, `why_interesting`, the item's stage values, earlier labels or
adjudication (`ngold.BLIND_HIDDEN_FIELDS`; a unit test pins it). The labeller may request any other page of the
same object with `--extra`, for example the act's first page to read the work name and axes, or a certificate scan.

## 3. How to label one item

1. Read the question: the parameter's trigger decides what a violation is. Triggers are directional
   («понижение», «уменьшение»): an improvement is not a violation.
2. Open every page to start from, as an image. Read the value **as printed** at each stage (ПД, РД, ИД) and write
   it down; do not copy values from anywhere else.
3. Check that the pages are the right evidence. Replace or add pages when needed: for an act, the page that names
   the element (p1) and the реестр page with the material; for a drawing, the sheet with the element.
4. Fix the code and the location when they are wrong. Locations follow 93 §2.7: a room number exactly as printed;
   `OBJECT` for object-level parameters; an element as printed in the act or drawing, with its axes
   («БСС-1н в/о 4-2.8/А-Х1», «Стена в грунте, захватка №8»).
5. Decide the label with the stage-availability rules of 93 §3.3:
   - `VIOLATION_PRESENT`: an available stage pair differs in the violating direction of the trigger;
   - `NO_VIOLATION`: the available pairs agree (or differ only in the non-violating direction);
   - `MISSING_DOCUMENT`: the pairs agree but a stage the parameter requires at this phase is absent
     (give `protocol_status`: `ID_MISSING`, `RD_MISSING` or `PD_MISSING`);
   - `COMPARISON_IMPOSSIBLE`: at most one required stage is available, or the value cannot be read;
   - `UNSURE`: you cannot decide; say why. UNSURE items are listed but not scored.
6. Mark `scorable: false` when the item is not a submission check at all (no catalog parameter applies, a data
   note, a document-quality remark). It stays in the file with its label and reasoning but is never scored.
7. Write the reasoning: the quotes you relied on (file, page, the printed words), the rule applied, and anything
   outside the key that matters (for example an F/W mark reduction that belongs to a FREE-* finding). Give a
   confidence: HIGH (the pages settle it), MEDIUM (the facts are clear, the mapping or status rule is a judgement),
   LOW (guess).
8. List `pages_viewed` with how each page was read (`image`, `text layer`, `tiles`, `clip`).
9. Set `blind: true` only when you saw nothing but the packet. If you saw the seed or any system output
   first, set `blind: false` and say so in `blind_note`.

Record with `inspector-score ngold record ID --label … --labeller … --reasoning … --confidence …` or a batch file
`--json FILE` (`[{"id": …, "annotation": {…}}]`, fields as in `devsets/n_gold_label_set.schema.json`).

## 4. Adjudication (automatic, recomputed on every write)

- One labeller: `SINGLE`. Several labellers of one kind that agree: `AGREEMENT`.
- A human label wins over a disagreeing agent label: `HUMAN_PRECEDENCE` (the disagreement is kept and counted).
- Labellers of the same kind disagree: `UNRESOLVED`, the label becomes UNSURE until someone adds a deciding label.
- The deciding annotation's code, location, evidence, values and status replace the item's fields; the first
  replaced seed value is kept under `seed_original`.

## 5. The user's spot-check

`inspector-score ngold sample --n 28` exports `runs/ngold/spotcheck-seed<seed>/`: `sheet.csv` (fill `user_label`,
optionally `user_parameter_code`, `user_location`, `user_comment`), `index.html` (the questions with page images)
and `key.json` (the agent labels; open it only after the sheet is filled). The sample is deterministic for a
seed and stratified by (label, fold). Import with `inspector-score ngold import-spotcheck SHEET.csv --labeller user`:
the tool adds HUMAN annotations and prints the agreement (raw and Cohen's κ) and every disagreement.

Acceptance before the freeze: every scorable item has a label other than UNSURE or is consciously left UNSURE;
agent–user agreement on the spot-check ≥ 0.8 raw (otherwise relabel the disagreeing class of items); no
UNRESOLVED items.

## 6. Freeze

`inspector-score devset freeze N-GOLD` pins the canonical sha256 of the labelled scorable items (`labels_sha256`)
and the sha256 of the file (`file_sha256`) in `devsets/registry.json`. From then on, rows carry
`gold_status = TEAM_LABEL_FROZEN`, every `ngold` write refuses, and loading a changed file fails with
TEST_SET_HASH_MISMATCH. Freeze before any threshold is tuned on N-GOLD (95 §5.2: labels are never changed after
seeing tuned outputs).
