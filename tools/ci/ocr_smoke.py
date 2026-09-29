#!/usr/bin/env python3
"""OCR smoke test for CI and for a fresh machine: recognise one synthetic Russian page with the pinned models.

    cd services/ml && uv run --locked python ../../tools/ci/ocr_smoke.py [--providers auto|cpu|coreml|cuda]

Needs the models in .models/ocr (``make fetch-models``). Prints the executor that was chosen and the recognised
text; exits 0 when every probe string is found, 1 otherwise, 3 when the models are missing (the CI step turns that
into a visible «skipped» message instead of a failure).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

LINES = [
    (60, 90, "ПРОТОКОЛ ИСПЫТАНИЙ № 284", 16),
    (60, 130, "Шифр проекта АНО/150321/1-РД-ОВ1", 13),
    (60, 165, "Фактический класс бетона В25", 13),
    (60, 200, "Дата испытаний 20.02.2026 г.", 13),
    (60, 235, "Прочность образца 22,6 МПа", 13),
]
PROBES = ("ПРОТОКОЛ", "20.02.2026", "22,6", "бетона")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--providers", default="auto", choices=["auto", "cpu", "coreml", "cuda"])
    args = parser.parse_args()

    from inspector_docproc.models import describe_provider_decision, resolve_provider_mode
    from inspector_docproc.testing import models_available, text_image

    if not models_available():
        print("Модели OCR не найдены в .models/ocr: выполните `make fetch-models`", file=sys.stderr)
        return 3
    from inspector_docproc.bench.metrics import norm_relaxed
    from inspector_docproc.ocr.engine import OcrEngine
    from inspector_docproc.ocr.pipeline import ocr_image

    mode = resolve_provider_mode(args.providers)
    print(describe_provider_decision(args.providers, mode))
    image = text_image(LINES, dpi=200)[:, :, ::-1].copy()  # BGR, like the pipeline
    with OcrEngine(providers=args.providers, threads=2) as engine:
        engine.warmup(medium=False)
        t0 = time.perf_counter()
        lines, _stats = ocr_image(engine, image)
        wall = time.perf_counter() - t0
        print(f"Распознано строк: {len(lines)} за {wall:.2f} с; исполнитель: {engine.provider_name}")
    text = " ".join(ln.text for ln in lines if ln.score >= 0.5)
    print(text)
    missing = [p for p in PROBES if norm_relaxed(p) not in norm_relaxed(text)]
    if missing:
        print(f"Не найдено в распознанном тексте: {missing}", file=sys.stderr)
        return 1
    print("OCR smoke: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
