"""Executor choice (auto: CoreML → CUDA → CPU) with a mocked onnxruntime: no GPU, no models needed."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from inspector_common.errors import InspectorError
from inspector_docproc import models
from inspector_docproc.config import ExecutionConfig
from inspector_docproc.runner import _keep_awake_command

CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"
COREML = "CoreMLExecutionProvider"


class FakeOrt:
    """Stands in for the ``onnxruntime`` module: which EPs are listed and what a session really runs on."""

    def __init__(self, listed: list[str], active: list[str] | None = None, error: Exception | None = None):
        self.listed = listed
        self.active = active if active is not None else [CPU]
        self.error = error
        self.sessions: list[dict] = []

    GraphOptimizationLevel = SimpleNamespace(ORT_ENABLE_ALL=99)

    def get_available_providers(self) -> list[str]:
        return list(self.listed)

    def SessionOptions(self) -> SimpleNamespace:
        return SimpleNamespace(log_severity_level=0)

    def InferenceSession(self, path, options=None, providers=None):
        self.sessions.append({"path": path, "providers": providers})
        if self.error:
            raise self.error
        active = self.active
        return SimpleNamespace(get_providers=lambda: list(active))


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    models._reset_probe_cache()
    yield
    models._reset_probe_cache()


@pytest.fixture
def fake_ort(monkeypatch):
    def install(**kw) -> FakeOrt:
        fake = FakeOrt(**kw)
        monkeypatch.setitem(sys.modules, "onnxruntime", fake)
        return fake

    monkeypatch.setattr(models, "coreml_available", lambda: False)
    monkeypatch.setattr(models, "_preload_cuda_libs", lambda: None)
    # the probe model comes from the registry: a stub with a path is enough for a fake session
    stub = SimpleNamespace(
        by_role=lambda role: SimpleNamespace(path=Path("det.onnx")), verify=lambda spec: None
    )
    monkeypatch.setattr(models, "ModelRegistry", lambda *a, **k: stub)
    return install


def test_auto_prefers_coreml_and_never_probes_cuda(monkeypatch, fake_ort) -> None:
    fake = fake_ort(listed=[COREML, CUDA, CPU], active=[CUDA, CPU])
    monkeypatch.setattr(models, "coreml_available", lambda: True)
    assert models.resolve_provider_mode("auto") == "coreml"
    assert fake.sessions == []  # macOS behaviour is untouched: no CUDA session is even attempted


def test_auto_picks_cuda_when_a_cuda_session_really_runs(fake_ort) -> None:
    fake = fake_ort(listed=[CUDA, CPU], active=[CUDA, CPU])
    assert models.resolve_provider_mode("auto") == "cuda"
    assert models.resolve_provider_mode("auto") == "cuda"
    assert len(fake.sessions) == 1  # the probe result is cached per process
    first = fake.sessions[0]["providers"][0]
    assert first[0] == CUDA and first[1]["cudnn_conv_algo_search"] == "HEURISTIC"


def test_cuda_listed_but_unusable_falls_back_to_cpu(fake_ort) -> None:
    """onnxruntime-gpu lists the CUDA EP without a working driver and then silently runs on the CPU."""
    fake_ort(listed=[CUDA, CPU], active=[CPU])
    assert models.resolve_provider_mode("auto") == "cpu"
    assert "перешла на CPU" in models.cuda_probe_reason()
    assert models.resolve_provider_mode("cuda") == "cpu"  # explicit, non-strict: warn and fall back
    with pytest.raises(InspectorError) as exc:
        models.resolve_provider_mode("cuda", strict=True)
    assert exc.value.code == "CONFIG_INVALID"


def test_session_creation_failure_means_cpu(fake_ort) -> None:
    fake_ort(listed=[CUDA, CPU], error=RuntimeError("libcudnn.so.9: cannot open shared object file"))
    assert models.resolve_provider_mode("auto") == "cpu"
    assert "libcudnn" in models.cuda_probe_reason()


def test_cpu_only_build_is_not_probed(fake_ort) -> None:
    fake = fake_ort(listed=[CPU])
    assert models.resolve_provider_mode("auto") == "cpu"
    assert fake.sessions == []
    assert "без GPU" in models.cuda_probe_reason()


def test_missing_model_leaves_the_probe_undecided(monkeypatch, fake_ort) -> None:
    fake_ort(listed=[CUDA, CPU], active=[CUDA, CPU])

    def boom(role):
        raise InspectorError("OCR_MODEL_MISSING", model=role)

    stub = SimpleNamespace(by_role=boom, verify=lambda spec: None)
    monkeypatch.setattr(models, "ModelRegistry", lambda *a, **k: stub)
    assert models.resolve_provider_mode("auto") == "cpu"
    assert "usable" not in models._CUDA_PROBE  # not cached: it can succeed once the models are installed


def test_strict_run_accepts_an_explicit_cuda_only_when_it_works(fake_ort) -> None:
    fake_ort(listed=[CUDA, CPU], active=[CUDA, CPU])
    assert models.resolve_provider_mode("cuda", strict=True) == "cuda"
    with pytest.raises(InspectorError):
        models.resolve_provider_mode("auto", strict=True)


def test_decision_text_is_russian_and_says_why(fake_ort) -> None:
    fake_ort(listed=[CPU])
    chosen = models.resolve_provider_mode("auto")
    text = models.describe_provider_decision("auto", chosen)
    assert text.startswith("Исполнитель распознавания: CPU") and "автоматически" in text
    assert "CUDA (видеокарта NVIDIA)" in models.describe_provider_decision("auto", "cuda")


def test_registry_session_is_created_on_cuda_and_strict_refuses_a_fallback(monkeypatch, fake_ort) -> None:
    fake = fake_ort(listed=[CUDA, CPU], active=[CUDA, CPU])
    monkeypatch.undo()  # the real ModelRegistry for this test; the fake onnxruntime is installed again below
    fake = fake_ort(listed=[CUDA, CPU], active=[CUDA, CPU])
    reg = models.ModelRegistry()
    monkeypatch.setattr(reg, "verify", lambda spec: None)
    monkeypatch.setattr(models, "_warn_if_telemetry_active", lambda: None)
    monkeypatch.setattr(models, "_preload_cuda_libs", lambda: None)
    spec = reg.by_role(models.ROLE_DET_PRIMARY)
    monkeypatch.setenv(models.CUDA_DEVICE_ENV, "1")
    monkeypatch.setenv(models.CUDA_MEM_LIMIT_ENV, "512")
    reg.session(spec, mode="cuda")
    ep, opts = fake.sessions[-1]["providers"][0]
    assert ep == CUDA and opts["device_id"] == "1" and opts["gpu_mem_limit"] == str(512 * 1024 * 1024)
    assert fake.sessions[-1]["providers"][1] == CPU
    fake.active = [CPU]  # this session silently fell back
    reg.session(spec, mode="cuda")  # tolerated when not strict (logged)
    reg.strict = True
    with pytest.raises(InspectorError) as exc:
        reg.session(spec, mode="cuda")
    assert exc.value.code == "CONFIG_INVALID"


def test_engine_pools_use_the_gpu_session_in_cuda_mode() -> None:
    from inspector_docproc.ocr.engine import _SessionPool

    made: list[str] = []
    registry = SimpleNamespace(session=lambda spec, mode, threads: made.append(mode) or "S")
    assert _SessionPool(registry, SimpleNamespace(), "cuda", 1).cpu() == "S"
    assert _SessionPool(registry, SimpleNamespace(), "cpu", 1).cpu() == "S"
    assert _SessionPool(registry, SimpleNamespace(), "coreml", 1).cpu() == "S"
    assert made == [
        "cuda",
        "cpu",
        "cpu",
    ]  # the dynamic-shape session follows the mode; CoreML keeps a CPU one


def test_cuda_worker_pool_is_capped(monkeypatch) -> None:
    from inspector_common import resources

    monkeypatch.setattr(resources, "available_cpus", lambda root=None: 16)
    monkeypatch.setattr(resources, "total_memory_bytes", lambda root=None: 64 * 1024**3)
    monkeypatch.delenv("INSPECTOR_RESOURCE_CAP", raising=False)
    cfg = ExecutionConfig(max_gpu_workers=3)
    assert cfg.resolved_workers("cuda") == 3
    assert cfg.resolved_workers("coreml") == 12 and cfg.resolved_workers() == 12  # 75 % of 16 CPUs
    assert (
        ExecutionConfig(workers=8, max_gpu_workers=3).resolved_workers("cuda") == 3
    )  # also an explicit --workers
    assert ExecutionConfig(workers=2, max_gpu_workers=3).resolved_workers("cuda") == 2
    monkeypatch.setenv("INSPECTOR_CUDA_MAX_WORKERS", "6")
    assert ExecutionConfig().max_gpu_workers == 6


def test_keep_awake_command_per_platform(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert _keep_awake_command("Darwin", 42)[:2] == ["/usr/bin/caffeinate", "-i"]
    linux = _keep_awake_command("Linux", 42)
    assert linux[0] == "/usr/bin/systemd-inhibit" and "--pid=42" in linux
    assert _keep_awake_command("Windows", 42) is None
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert _keep_awake_command("Linux", 42) is None  # a server without systemd simply does not suspend
