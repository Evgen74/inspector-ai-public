"""Model registry: pinned ONNX models from ``.models/`` (tools/models/manifest.json) and ORT sessions.

- Every model is resolved by its manifest ``role`` and verified (size + sha256) before first use in a
  process; a missing file raises ``OCR_MODEL_MISSING``, a modified one ``MODEL_ARTIFACT_INTEGRITY_FAILED``.
- Sessions use the fastest executor of the host, chosen by :func:`resolve_provider_mode`: CoreML (macOS),
  else CUDA (an NVIDIA GPU that really works, verified by creating a session), else CPU.
  CoreML runs with **static input shapes** (free-dimension overrides), one compiled model per shape,
  cached on disk under ``.cache/coreml/<model sha>/<shape>``: with dynamic shapes CoreML is slower than
  the CPU on this model family (measured: 3200² detector tile 2.8 s dynamic vs 0.1 s static vs 1.4 s CPU).
  CUDA runs both models with dynamic shapes (no canvases, no compiled-model cache).
- No network, ever: model files come only from the manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from inspector_common.errors import InspectorError
from inspector_common.paths import ensure_dir, repo_root

log = logging.getLogger("inspector_docproc.models")

ROLE_DET_PRIMARY = "ocr_detector_primary"
ROLE_DET_FALLBACK = "ocr_detector_fallback"
ROLE_REC_PRIMARY = "ocr_recognizer_primary"

COREML = "CoreMLExecutionProvider"
CUDA = "CUDAExecutionProvider"
CPU = "CPUExecutionProvider"

PROVIDER_MODES = ("auto", "cpu", "coreml", "cuda")
EXPLICIT_MODES = ("cpu", "coreml", "cuda")
CUDA_DEVICE_ENV = "INSPECTOR_CUDA_DEVICE"  # GPU index (default 0)
CUDA_MEM_LIMIT_ENV = "INSPECTOR_CUDA_MEM_LIMIT_MB"  # optional ONNX Runtime arena cap per session, MiB


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str  # file name, e.g. PP-OCRv6_det_small.onnx
    path: Path
    sha256: str
    size_bytes: int
    role: str
    required: bool

    @property
    def stem(self) -> str:
        return self.name.removesuffix(".onnx")


def default_manifest_path() -> Path:
    env = os.environ.get("INSPECTOR_MODELS_MANIFEST")
    return Path(env).expanduser().resolve() if env else repo_root() / "tools" / "models" / "manifest.json"


def coreml_available() -> bool:
    try:
        import onnxruntime as ort
    except ImportError:  # pragma: no cover - workspace dependency
        return False
    return platform.system() == "Darwin" and COREML in ort.get_available_providers()


_CUDA_LOCK = threading.Lock()
_CUDA_PROBE: dict[str, Any] = {}  # per process: {"usable": bool, "reason": str}
_PRELOADED = False
_LOGGED_DECISIONS: set[tuple[str, str]] = set()


def _preload_cuda_libs() -> None:
    """Load the CUDA/cuDNN shared libraries from the pip ``nvidia-*`` wheels (no system toolkit needed).
    ``onnxruntime.preload_dlls`` exists from ONNX Runtime 1.21; it is a no-op without those wheels."""
    global _PRELOADED
    if _PRELOADED:
        return
    _PRELOADED = True
    try:
        import onnxruntime as ort

        preload = getattr(ort, "preload_dlls", None)
        if preload is not None:
            preload()
    except Exception as exc:  # a missing library shows up as an unusable CUDA session, not here
        log.info("ocr.cuda_preload_failed", extra={"detail": f"{type(exc).__name__}: {exc}"})


def cuda_provider_options() -> dict[str, str]:
    """CUDA EP options: dynamic shapes (variable page sizes) must not trigger a cuDNN benchmark per new shape
    (``HEURISTIC`` instead of the default ``EXHAUSTIVE``), and the arena grows by what is asked, not by
    powers of two, so several worker processes share one GPU without hoarding memory."""
    opts = {
        "device_id": os.environ.get(CUDA_DEVICE_ENV, "0"),
        "arena_extend_strategy": "kSameAsRequested",
        "cudnn_conv_algo_search": "HEURISTIC",
    }
    limit = os.environ.get(CUDA_MEM_LIMIT_ENV)
    if limit and limit.isdigit():
        opts["gpu_mem_limit"] = str(int(limit) * 1024 * 1024)
    return opts


def cuda_usable(model_path: Path | None = None) -> bool:
    """True when a CUDA session really runs on this machine (probed once per process).

    ``onnxruntime-gpu`` lists ``CUDAExecutionProvider`` even without a driver or cuDNN and then falls back to
    the CPU silently, so the listing proves nothing: a session is created on the primary detector (or
    ``model_path``) and its first active provider must be CUDA.
    """
    with _CUDA_LOCK:
        if "usable" in _CUDA_PROBE:
            return bool(_CUDA_PROBE["usable"])
        try:
            import onnxruntime as ort
        except ImportError:  # pragma: no cover - workspace dependency
            return False
        if CUDA not in ort.get_available_providers():
            _CUDA_PROBE.update(
                usable=False, reason="в сборке ONNX Runtime нет CUDA (установлен onnxruntime без GPU)"
            )
            return False
        _preload_cuda_libs()
        try:
            if model_path is None:
                reg = ModelRegistry()
                spec = reg.by_role(ROLE_DET_PRIMARY)
                reg.verify(spec)
                model_path = spec.path
        except InspectorError as exc:  # no model to probe with: undecided, do not cache
            log.warning("ocr.cuda_probe_no_model", extra={"detail": str(exc)})
            return False
        try:
            so = ort.SessionOptions()
            so.log_severity_level = 3
            sess = ort.InferenceSession(str(model_path), so, providers=[(CUDA, cuda_provider_options()), CPU])
            active = sess.get_providers()
            ok = bool(active) and active[0] == CUDA
            reason = "" if ok else f"сессия CUDA перешла на CPU (активны: {', '.join(active)})"
        except Exception as exc:
            ok, reason = False, f"{type(exc).__name__}: {str(exc)[:200]}"
        _CUDA_PROBE.update(usable=ok, reason=reason)
        return ok


def cuda_probe_reason() -> str:
    """Why CUDA was judged unusable (Russian), empty when it is usable or was not probed."""
    return str(_CUDA_PROBE.get("reason", ""))


def _reset_probe_cache() -> None:
    """Forget the per-process probe results and logged decisions (tests)."""
    global _PRELOADED
    with _CUDA_LOCK:
        _CUDA_PROBE.clear()
    _LOGGED_DECISIONS.clear()
    _PRELOADED = False


def _decided(requested: str, chosen: str, why: str) -> str:
    """Log the executor decision once per (requested, chosen) pair per process; returns ``chosen``."""
    key = (requested, chosen)
    if key not in _LOGGED_DECISIONS:
        _LOGGED_DECISIONS.add(key)
        log.info(
            "ocr.provider_resolved",
            extra={"requested": requested, "chosen": chosen, "detail": why},
        )
    return chosen


def describe_provider_decision(requested: str, chosen: str) -> str:
    """One Russian line for the CLI: what was requested, what runs and why."""
    names = {"coreml": "CoreML (macOS)", "cuda": "CUDA (видеокарта NVIDIA)", "cpu": "CPU"}
    line = f"Исполнитель распознавания: {names.get(chosen, chosen)}"
    if requested == "auto":
        line += " — выбран автоматически"
        if chosen == "cpu":
            reason = cuda_probe_reason()
            line += f" (ускорителей нет{'; CUDA: ' + reason if reason else ''})"
    elif requested != chosen:
        reason = cuda_probe_reason() if requested == "cuda" else ""
        line += f" — запрошен {requested}, недоступен{'; ' + reason if reason else ''}"
    return line


def _reason_suffix() -> str:
    reason = cuda_probe_reason()
    return f": {reason}" if reason else ""


def resolve_provider_mode(mode: str, strict: bool = False) -> str:
    """``auto`` → ``coreml`` (macOS host with the CoreML EP) → ``cuda`` (a CUDA session that really runs) → ``cpu``.

    ``strict`` (frozen runs, ``ExecutionConfig.strict_providers``): the provider decides the PageTokens (CoreML,
    CUDA and CPU differ in the last float digits) and is part of the pipeline version, so it must be named and
    is never replaced: ``auto`` and an unavailable executor raise ``CONFIG_INVALID`` instead of falling back.
    """
    if strict:
        if mode not in EXPLICIT_MODES:
            raise InspectorError(
                "CONFIG_INVALID",
                field="--providers",
                reason=f"замороженный прогон требует явного исполнителя cpu, coreml или cuda, указано «{mode}»",
            )
        if mode == "coreml" and not coreml_available():
            raise InspectorError(
                "CONFIG_INVALID", field="--providers", reason="исполнитель CoreML недоступен на этой машине"
            )
        if mode == "cuda" and not cuda_usable():
            raise InspectorError(
                "CONFIG_INVALID",
                field="--providers",
                reason="исполнитель CUDA недоступен на этой машине" + _reason_suffix(),
            )
        return mode
    if mode == "cpu":
        return "cpu"
    if mode == "coreml":
        if not coreml_available():
            log.warning("ocr.coreml_unavailable", extra={"fallback": "cpu"})
            return "cpu"
        return "coreml"
    if mode == "cuda":
        if not cuda_usable():
            log.warning("ocr.cuda_unavailable", extra={"fallback": "cpu", "detail": cuda_probe_reason()})
            return "cpu"
        return "cuda"
    if mode != "auto":
        raise ValueError(f"unknown provider mode {mode!r} ({', '.join(PROVIDER_MODES)})")
    if coreml_available():
        return _decided(mode, "coreml", "macOS, CoreML доступен")
    if cuda_usable():
        return _decided(mode, "cuda", "сессия CUDA создана и работает")
    return _decided(mode, "cpu", cuda_probe_reason() or "ускорителей нет")


class ModelRegistry:
    """Resolves pinned models by role and creates verified ONNX Runtime sessions."""

    _verified: ClassVar[dict[tuple[str, int, int], str]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        manifest_path: Path | None = None,
        models_root: Path | None = None,
        cache_root: Path | None = None,
        *,
        strict: bool = False,
    ) -> None:
        # strict: a CoreML session that ONNX Runtime silently moves to the CPU is an error (frozen runs)
        self.strict = strict
        self.manifest_path = manifest_path or default_manifest_path()
        if not self.manifest_path.is_file():
            raise InspectorError("OCR_MODEL_MISSING", model=str(self.manifest_path))
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        root = models_root
        if root is None:
            env = os.environ.get("INSPECTOR_MODELS_ROOT")
            root = Path(env).expanduser() if env else repo_root() / raw.get("models_root", ".models")
        self.models_root = root.resolve()
        self.cache_root = (cache_root or repo_root() / ".cache").resolve()
        self._by_role: dict[str, ModelSpec] = {}
        self._by_name: dict[str, ModelSpec] = {}
        for entry in raw.get("files", []):
            rel = str(entry["path"])
            spec = ModelSpec(
                name=Path(rel).name,
                path=self.models_root / rel,
                sha256=str(entry["sha256"]),
                size_bytes=int(entry["size_bytes"]),
                role=str(entry.get("role", "")),
                required=bool(entry.get("required", False)),
            )
            self._by_name.setdefault(spec.name, spec)
            if spec.role and spec.role not in self._by_role:
                self._by_role[spec.role] = spec

    # ── lookup ──────────────────────────────────────────────────────────────────────────────────
    def by_role(self, role: str) -> ModelSpec:
        try:
            return self._by_role[role]
        except KeyError:
            raise InspectorError("OCR_MODEL_MISSING", model=role) from None

    def by_name(self, name: str) -> ModelSpec:
        try:
            return self._by_name[name]
        except KeyError:
            raise InspectorError("OCR_MODEL_MISSING", model=name) from None

    # ── integrity ───────────────────────────────────────────────────────────────────────────────
    def verify(self, spec: ModelSpec) -> None:
        """Size + sha256 against the manifest; each file is hashed once per process."""
        path = spec.path
        if not path.is_file():
            raise InspectorError("OCR_MODEL_MISSING", model=spec.name)
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        with self._lock:
            known = self._verified.get(key)
        if known is None:
            if st.st_size != spec.size_bytes:
                raise InspectorError("MODEL_ARTIFACT_INTEGRITY_FAILED", model_version=spec.name)
            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                while chunk := fh.read(1 << 20):
                    digest.update(chunk)
            known = digest.hexdigest()
            with self._lock:
                self._verified[key] = known
        if known != spec.sha256:
            raise InspectorError("MODEL_ARTIFACT_INTEGRITY_FAILED", model_version=spec.name)

    # ── sessions ────────────────────────────────────────────────────────────────────────────────
    def session(
        self,
        spec: ModelSpec,
        *,
        mode: str = "cpu",
        threads: int = 1,
        static_dims: dict[int, int] | None = None,
    ) -> Any:
        """A verified ``onnxruntime.InferenceSession``.

        ``mode`` is ``cpu``, ``coreml`` or ``cuda`` (already resolved). ``cuda`` runs the model with dynamic
        shapes on the GPU (a silent fall-back to the CPU is reported and, when strict, refused). With ``coreml``,
        ``static_dims`` maps input axis positions to fixed sizes; the model's symbolic dimension names at those positions are
        overridden, so CoreML compiles a static-shape program (cached on disk per shape).
        """
        import onnxruntime as ort

        _warn_if_telemetry_active()
        self.verify(spec)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.enable_cpu_mem_arena = False
        so.intra_op_num_threads = max(1, int(threads))
        so.inter_op_num_threads = 1
        providers: list[Any] = [CPU]
        shape_tag = "dynamic"
        if mode == "cuda":
            _preload_cuda_libs()
            providers = [(CUDA, cuda_provider_options()), CPU]
        if mode == "coreml":
            if not static_dims:
                raise ValueError("CoreML sessions need static_dims (dynamic shapes are slower than CPU)")
            names = _symbolic_input_dims(spec.path)
            for axis, size in sorted(static_dims.items()):
                dim_name = names.get(axis)
                if dim_name:
                    so.add_free_dimension_override_by_name(dim_name, int(size))
            shape_tag = "x".join(str(static_dims[a]) for a in sorted(static_dims))
            cache_dir = ensure_dir(self.cache_root / "coreml" / spec.sha256[:16] / shape_tag)
            coreml_opts = {
                "ModelFormat": "MLProgram",
                "MLComputeUnits": "ALL",
                "RequireStaticInputShapes": "1",
                "EnableOnSubgraphs": "0",
                "SpecializationStrategy": "FastPrediction",
                "ModelCacheDirectory": str(cache_dir),
            }
            providers = [(COREML, coreml_opts), CPU]
        sess = ort.InferenceSession(str(spec.path), so, providers=providers)
        active = sess.get_providers()
        extra = {"model": spec.name, "mode": mode, "providers": active, "shape": shape_tag}
        if mode == "coreml" and COREML not in active:  # ORT fell back silently: say so, it halves speed
            log.warning("ocr.coreml_session_fell_back_to_cpu", extra=extra)
            if self.strict:
                raise InspectorError(
                    "CONFIG_INVALID",
                    field="--providers",
                    reason=f"сессия CoreML модели {spec.name} перешла на CPU, результат не совпадёт с заявленным",
                )
        elif mode == "cuda" and active[:1] != [CUDA]:  # the probe passed once, but this session fell back
            log.warning("ocr.cuda_session_fell_back_to_cpu", extra=extra)
            if self.strict:
                raise InspectorError(
                    "CONFIG_INVALID",
                    field="--providers",
                    reason=f"сессия CUDA модели {spec.name} перешла на CPU, результат не совпадёт с заявленным",
                )
        else:
            log.info("ocr.session_created", extra=extra)
        return sess


_TELEMETRY_WARNED = False


def _warn_if_telemetry_active() -> None:
    """Log once when ``onnxruntime`` was imported before ``inspector_docproc`` could disable its telemetry
    (see the package docstring): the process then makes network calls and can abort at exit."""
    global _TELEMETRY_WARNED
    import inspector_docproc

    if inspector_docproc.ORT_TELEMETRY_PREIMPORTED and not _TELEMETRY_WARNED:
        _TELEMETRY_WARNED = True
        log.warning(
            "ocr.ort_telemetry_active",
            extra={
                "detail": "onnxruntime imported before ORT_DISABLE_TELEMETRY=1; set it at the entry point"
            },
        )


_SYMBOLIC_DIMS: dict[str, dict[int, str]] = {}


def _symbolic_input_dims(path: Path) -> dict[int, str]:
    """Axis → symbolic dimension name of the model's first input (read once per model file)."""
    key = str(path)
    if key not in _SYMBOLIC_DIMS:
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.log_severity_level = 3
        probe = ort.InferenceSession(str(path), so, providers=[CPU])
        shape = probe.get_inputs()[0].shape
        _SYMBOLIC_DIMS[key] = {i: d for i, d in enumerate(shape) if isinstance(d, str) and d and d != "?"}
    return _SYMBOLIC_DIMS[key]
