"""T-GOLD must-pass gate, end to end (97 §3.2 M1, 95 §3.8).

``inspector-batch run --object OBJ-TYUMENSKAYA-5-GOLD-SEED --keep-going`` (recognize → layout → tables → compare →
export → score in one run directory), then the gate of ``inspector_eval.tgold_gate`` on that run: every hard
criterion G1–G7 must pass and the RT checks (G8) must not fail.

- Marked ``slow`` (the first run recognises the whole object; later runs hit the sha256 token cache under
  ``.cache/``) and ``data`` (needs the organizer package).
- Skips while a step that produces the answer (recognize, compare, export, score) is still a stub; ``layout`` and
  ``tables`` stubs do not block (``--keep-going``), and G8 then reports their RT checks as NOT_EVALUATED.
- ``INSPECTOR_TGOLD_RUN_ID=<run_id>`` evaluates an existing run instead of starting one;
  ``INSPECTOR_TGOLD_TIMEOUT_S`` caps the pipeline (default 3 h); ``INSPECTOR_WORKERS`` (default 3 here, the host
  is shared) sets the recognition workers.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from inspector_common.exitcodes import ExitCode
from inspector_eval import tgold_gate
from inspector_eval.fixtures import T_GOLD_OBJECT

ANSWER_STEPS = ("recognize", "compare", "export", "score")
HARD_NOW = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")


def _batch_executable() -> Path:
    exe = Path(sys.executable).parent / "inspector-batch"
    if not exe.is_file():
        pytest.skip("inspector-batch console script not installed in this environment")
    return exe


@pytest.mark.slow
@pytest.mark.data
def test_tgold_end_to_end_must_pass(request, real_paths, real_ctx, real_gold) -> None:
    reuse = os.environ.get("INSPECTOR_TGOLD_RUN_ID")
    runtime_s = None
    if not reuse and "slow" not in (request.config.getoption("markexpr") or "").replace("not slow", ""):
        # Launching a whole-object pipeline needs an explicit slow selection (make test-slow: -m slow), never a
        # plain `pytest packages/inspector_eval/tests`.
        pytest.skip(
            "T-GOLD E2E starts the pipeline only under `-m slow` (or INSPECTOR_TGOLD_RUN_ID=<run_id>)"
        )
    if reuse:
        run_dir = real_paths.runs_root / reuse
        if not run_dir.is_dir():
            pytest.fail(f"INSPECTOR_TGOLD_RUN_ID={reuse}: {run_dir} not found")
    else:
        stubs = tgold_gate.pipeline_stubs()
        blocking = {step: owner for step, owner in stubs.items() if step in ANSWER_STEPS}
        if blocking:
            pytest.skip(
                "T-GOLD E2E not runnable yet, stub steps: "
                + ", ".join(f"{s} ({o})" for s, o in blocking.items())
            )
        run_id = "tgold-e2e-" + datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = real_paths.runs_root / run_id
        started = time.monotonic()
        # Shared 12-core host: recognition workers default to 3 unless the caller sets INSPECTOR_WORKERS.
        env = {**os.environ, "INSPECTOR_WORKERS": os.environ.get("INSPECTOR_WORKERS", "3")}
        proc = subprocess.run(
            [str(_batch_executable()), "--run-id", run_id, "run", "--object", T_GOLD_OBJECT, "--keep-going"],
            capture_output=True,
            text=True,
            env=env,
            timeout=float(os.environ.get("INSPECTOR_TGOLD_TIMEOUT_S", "10800")),
            check=False,
        )
        runtime_s = time.monotonic() - started
        allowed = {int(ExitCode.OK), int(ExitCode.GATE_TRIGGERED), int(ExitCode.NOT_IMPLEMENTED)}
        assert proc.returncode in allowed, f"exit {proc.returncode}\n{proc.stderr[-4000:]}"

    result = tgold_gate.evaluate(run_dir, real_ctx, real_gold, runtime_s=runtime_s)
    path = tgold_gate.write(result, run_dir)
    report = tgold_gate.render(result)
    print(report, f"\nОтчёт: {path}")  # visible with -s; the file stays in the run directory
    assert result.hard_ok(HARD_NOW), report
    assert result.criteria["G8"].status != "FAIL", report
    assert result.criteria["G9"].status == "PASS", report
