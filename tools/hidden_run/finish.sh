#!/bin/bash
# Final frozen hidden run, part 2: layout → tables → compare → export → checks → deliverables.
# Part 1 (recognize) was started with:
#   inspector-batch recognize --object <hidden> --hidden-run --providers coreml --workers 10 \
#     --config tools/hidden_run/recognize.config.json      (run id in $RUN)
# The hidden object id is read from the organizers' split_policy.json, never hard-coded (make guard).
# Usage: RUN=<recognize run id> WORKERS=10 tools/hidden_run/finish.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
RUN="${RUN:?set RUN to the hidden recognize run id}"
WORKERS="${WORKERS:-10}"
PKG="$REPO/data_utf8/ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0/data"
RUN_DIR="$REPO/runs/$RUN"
cd "$REPO/services/ml"

OBJ="$(uv run --locked python -c "import json,sys; print(json.load(open(sys.argv[1]))['TEST_HIDDEN'][0])" "$PKG/split_policy.json")"
export INSPECTOR_MATRIX_OVERRIDES=off   # the frozen run never uses admin threshold overrides
export PYTHONUNBUFFERED=1

step() { echo "== $(date +%H:%M:%S) $*"; }

step "layout";  uv run --locked inspector-batch --run-id "$RUN" layout  --object "$OBJ" --hidden-run --workers "$WORKERS"
step "tables";  uv run --locked inspector-batch --run-id "$RUN" tables  --object "$OBJ" --hidden-run --workers "$WORKERS"
step "compare"; uv run --locked inspector-batch --run-id "$RUN" compare --object "$OBJ" --hidden-run
step "export";  uv run --locked inspector-batch --run-id "$RUN" export  --object "$OBJ" --hidden-run

step "schema check against the organizers' submission_schema.json"
uv run --locked python - "$PKG/submission_schema.json" "$RUN_DIR" "$OBJ" <<'PY'
import json, sys, pathlib, jsonschema
schema = json.load(open(sys.argv[1]))
run_dir, obj = pathlib.Path(sys.argv[2]), sys.argv[3]
files = sorted(p for p in run_dir.rglob(f"{obj}.json") if "submission" in str(p.parent))
assert files, f"no submission file for {obj} under {run_dir}"
for f in files:
    data = json.load(open(f))
    jsonschema.validate(data, schema)
    labels = {}
    for c in data["checks"]:
        labels[c["violation_label"]] = labels.get(c["violation_label"], 0) + 1
    print(f"OK {f.relative_to(run_dir)}: {len(data['checks'])} checks, labels={labels}")
PY

step "integrity rules R1–R15 and packaging P1–P6"
uv run --locked inspector-score integrity --pred "$RUN_DIR" --require-packaging --out "$RUN_DIR/integrity" || {
  echo "!! integrity check reported problems — see $RUN_DIR/integrity"; }

step "deliverables"
OUT="$REPO/deliverables/hidden_$(date +%Y%m%d_%H%M)"
mkdir -p "$OUT"
find "$RUN_DIR" -path "*submission*" -name "*.json" -exec cp {} "$OUT/" \;
find "$RUN_DIR" \( -iname "protocol*.json" -o -iname "*.docx" -o -iname "*.pdf" \) -path "*protocol*" -exec cp {} "$OUT/" \; || true
cp "$REPO/tools/hidden_run/recognize.config.json" "$OUT/"
( cd "$OUT" && shasum -a 256 * > SHA256SUMS.txt )
echo "Deliverables: $OUT"; ls -la "$OUT"
