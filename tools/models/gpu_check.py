#!/usr/bin/env python3
"""Print the ONNX executor that ``--providers auto`` chooses on this machine (coreml | cuda | cpu) and why.

    cd services/ml && uv run --locked python ../../tools/models/gpu_check.py

The CUDA probe creates a real session on the primary detector (models must be in .models/ocr): the provider list of
onnxruntime-gpu proves nothing without a working driver. Exit code 0 always; the answer is the printed line.
"""

from __future__ import annotations

import os

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

import onnxruntime as ort

from inspector_docproc.models import (
    cuda_probe_reason,
    describe_provider_decision,
    resolve_provider_mode,
)


def main() -> int:
    print(f"onnxruntime {ort.__version__}, доступные исполнители: {', '.join(ort.get_available_providers())}")
    chosen = resolve_provider_mode("auto")
    print(describe_provider_decision("auto", chosen))
    if chosen == "cpu" and cuda_probe_reason():
        print("Подробнее: docs/runbook/LINUX.md, раздел «Видеокарта NVIDIA»")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
