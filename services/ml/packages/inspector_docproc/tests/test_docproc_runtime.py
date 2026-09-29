"""Native runtime hygiene (M1): ONNX Runtime telemetry off (root cause of the exit-134 abort), sessions
released, execution provider pinned for frozen runs."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from inspector_common.errors import InspectorError
from inspector_docproc import models
from inspector_docproc.batch import frozen_providers_problem, run_recognize
from inspector_docproc.testing import models_available

_THREADS = textwrap.dedent(
    """
    import os, subprocess, sys
    if sys.argv[1] == "docproc-first":
        import inspector_docproc
        import onnxruntime
    else:
        import onnxruntime
        import inspector_docproc
    def native_threads():
        if sys.platform == "darwin":
            out = subprocess.run(["ps", "-M", "-p", str(os.getpid())], capture_output=True, text=True).stdout
            return len(out.strip().splitlines()) - 1
        return len(os.listdir("/proc/self/task"))
    print(os.environ.get("ORT_DISABLE_TELEMETRY"), inspector_docproc.ORT_TELEMETRY_PREIMPORTED, native_threads())
    sys.stdout.flush()
    os._exit(0)  # never run the native static destructors in this probe
    """
)


def _probe(order: str) -> tuple[str, bool, int]:
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    out = subprocess.run(
        [sys.executable, "-c", _THREADS, order],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=True,
    ).stdout.split()
    return out[0], out[1] == "True", int(out[2])


def test_importing_docproc_first_disables_ort_telemetry() -> None:
    """ORT ≥ 1.2x starts its 1DS telemetry client at import (extra native threads, an HTTPS upload ~8 s later,
    and the «recursive_mutex lock failed» abort at exit). ``inspector_docproc`` sets ORT_DISABLE_TELEMETRY
    before any onnxruntime import; a process that imported onnxruntime first is detected and reported."""
    env_first, pre_first, threads_first = _probe("docproc-first")
    _env_late, pre_late, threads_late = _probe("ort-first")
    assert env_first == "1" and not pre_first
    assert (
        pre_late
    )  # too late: telemetry already running in that process (logged as ocr.ort_telemetry_active)
    if sys.platform == "darwin":  # the Linux build of ONNX Runtime starts no 1DS telemetry threads at import
        assert threads_first < threads_late, (threads_first, threads_late)


@pytest.mark.slow
@pytest.mark.skipif(not models_available(), reason="OCR models not found")
def test_long_lived_session_process_exits_cleanly_without_network() -> None:
    """The exit-134 reproduction: a process with an ORT session living past the telemetry upload (~8 s) used to
    abort in ``DebugEventSource::DispatchEvent`` at interpreter exit. With the fix it exits 0 and opens no
    socket (checked with lsof on macOS)."""
    code = textwrap.dedent(
        """
        import os, subprocess, sys, time
        from inspector_docproc.models import ModelRegistry, ROLE_REC_PRIMARY
        reg = ModelRegistry()
        s = reg.session(reg.by_role(ROLE_REC_PRIMARY), mode="cpu", threads=1)
        time.sleep(11)
        if sys.platform == "darwin":
            out = subprocess.run(["lsof", "-a", "-i", "-p", str(os.getpid())], capture_output=True, text=True)
            print("sockets", max(0, len(out.stdout.strip().splitlines()) - 1))
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "ORT_DISABLE_TELEMETRY"}
    t0 = time.perf_counter()
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=180)
    assert res.returncode == 0, (res.returncode, res.stderr[-500:])
    assert "recursive_mutex" not in res.stderr
    if sys.platform == "darwin":
        assert "sockets 0" in res.stdout, res.stdout
    assert time.perf_counter() - t0 >= 11


def test_engine_close_releases_sessions(ocr_engine) -> None:
    import numpy as np

    ocr_engine.rec([np.full((48, 200, 3), 255, np.uint8)])
    assert ocr_engine.rec.pool._cpu is not None
    ocr_engine.close()
    assert ocr_engine.rec.pool._cpu is None and all(d.pool._cpu is None for d in ocr_engine._det.values())
    assert ocr_engine.rec([np.full((48, 200, 3), 255, np.uint8)])  # usable again: sessions come back lazily


# ── Execution provider of frozen runs ─────────────────────────────────────────────────────────


def test_frozen_run_needs_an_explicit_provider() -> None:
    assert frozen_providers_problem("auto", strict=True)
    assert "--providers coreml" in frozen_providers_problem("auto", strict=True)
    assert frozen_providers_problem("coreml", strict=True) is None
    assert frozen_providers_problem("cpu", strict=True) is None
    assert (
        frozen_providers_problem("cuda", strict=True) is None
    )  # an explicit GPU executor is a frozen choice too
    assert frozen_providers_problem("auto", strict=False) is None


def test_recognize_refuses_auto_on_a_hidden_run(capsys, monkeypatch) -> None:
    import inspector_docproc.inputs as inputs
    import inspector_docproc.runner as runner

    monkeypatch.setattr(inputs, "select_files", lambda *a, **k: (["job"], []))
    monkeypatch.setattr(runner, "run_recognition", lambda *a, **k: pytest.fail("no page may be read"))
    args = SimpleNamespace(providers="auto", strict_providers=False, files=None)
    ctx = SimpleNamespace(hidden_run=True, settings=SimpleNamespace(paths=None), objects=("OBJ-X",))
    assert run_recognize(args, ctx) == 2  # refused before any page is read
    assert "Замороженный прогон" in capsys.readouterr().err
    args = SimpleNamespace(providers="auto", strict_providers=True, files=None)
    assert run_recognize(args, SimpleNamespace(**{**vars(ctx), "hidden_run": False})) == 2


def test_strict_resolution_never_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(models, "coreml_available", lambda: False)
    monkeypatch.setattr(models, "cuda_usable", lambda *a, **k: False)
    assert models.resolve_provider_mode("coreml") == "cpu"  # dev runs: warn and fall back
    assert models.resolve_provider_mode("auto") == "cpu"
    for mode in ("coreml", "cuda", "auto"):
        with pytest.raises(InspectorError) as exc:
            models.resolve_provider_mode(mode, strict=True)
        assert exc.value.code == "CONFIG_INVALID"
    assert models.resolve_provider_mode("cpu", strict=True) == "cpu"


@pytest.mark.skipif(not models_available(), reason="OCR models not found")
def test_strict_registry_refuses_a_silent_coreml_fallback(monkeypatch) -> None:
    """ONNX Runtime may create a «CoreML» session that runs on the CPU only (a warning so far): strict = error."""
    import onnxruntime as ort

    class _CpuOnly:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def get_providers(self) -> list[str]:
            return ["CPUExecutionProvider"]

    reg = models.ModelRegistry(strict=True)
    spec = reg.by_role(models.ROLE_DET_PRIMARY)
    models._symbolic_input_dims(spec.path)  # read the real input names before the session class is replaced
    monkeypatch.setattr(ort, "InferenceSession", _CpuOnly)
    with pytest.raises(InspectorError) as exc:
        reg.session(spec, mode="coreml", static_dims={0: 1, 2: 1600, 3: 1600})
    assert exc.value.code == "CONFIG_INVALID"
    reg.strict = False
    assert isinstance(reg.session(spec, mode="coreml", static_dims={0: 1, 2: 1600, 3: 1600}), _CpuOnly)
