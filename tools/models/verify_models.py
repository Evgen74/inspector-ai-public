#!/usr/bin/env python3
"""Verify (or regenerate) tools/models/manifest.json, which pins every model file in .models/ by sha256.

    python tools/models/verify_models.py                 # required files: existence + size + sha256
    python tools/models/verify_models.py --all           # every pinned file, including benchmark candidates
    python tools/models/verify_models.py --quick         # existence + size only (no hashing)
    python tools/models/verify_models.py --update        # AG-00 only: rewrite the manifest from .models/

Stdlib only, no network. Exit 0 = OK, 1 = missing or modified files, 2 = usage error.
Models are never committed (.gitignore); this manifest is.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).resolve().with_name("manifest.json")
DEFAULT_MODELS_ROOT = REPO_ROOT / ".models"

# HF cache bookkeeping files: not model content.
_SKIP_SUFFIXES = (".lock", ".refs")
_SKIP_NAMES = {".huggingface-shared-blobs", ".DS_Store"}

# Roles of the OCR files (96 §16, 97 §2.13 / §5). Anything not listed is a benchmark candidate.
OCR_ROLES = {
    "PP-OCRv6_det_small.onnx": (
        "ocr_detector_primary",
        True,
        "PP-OCRv6-small detector, tiles 3200/400 (97 §2.13 F2/F3)",
    ),
    "PP-OCRv6_det_medium.onnx": (
        "ocr_detector_fallback",
        True,
        "v6-medium fallback when mean line score < 0.9 or seal zone",
    ),
    "cyrillic_PP-OCRv5_rec_mobile.onnx": ("ocr_recognizer_primary", True, "PP-OCRv5 cyrillic recogniser"),
    "ch_PP-OCRv5_det_mobile.onnx": ("ocr_detector_alternative", False, "optional detector (96 §16)"),
}
OCR_CANDIDATE_NOTES = {
    "cyrillic_PP-OCRv5_rec_mobile_int8.onnx": "INT8 is not used (97 §2.13)",
    "ch_PP-LCNet_x0_25_textline_ori_cls_mobile.onnx": "no text-line classifier in the pipeline (97 §2.16)",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": "no text-line classifier in the pipeline (97 §2.16)",
    "PP-OCRv6_rec_medium.onnx": "PP-OCRv6 rec has no Cyrillic (96 §16)",
    "PP-OCRv6_rec_small.onnx": "PP-OCRv6 rec has no Cyrillic (96 §16)",
    "PP-OCRv6_rec_tiny.onnx": "PP-OCRv6 rec has no Cyrillic (96 §16)",
}
E5_REPO_DIR = "hf/models--intfloat--multilingual-e5-small"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _is_model_file(rel: Path) -> bool:
    parts = rel.parts
    if ".no_exist" in parts or (len(parts) >= 2 and parts[-2] == "refs"):
        return False
    return rel.name not in _SKIP_NAMES and not rel.name.endswith(_SKIP_SUFFIXES)


def _classify(rel: str, models_root: Path, aliases: list[str]) -> dict[str, object]:
    name = Path(rel).name
    if rel.startswith("ocr/"):
        if name in OCR_ROLES:
            role, required, note = OCR_ROLES[name]
            return {"role": role, "required": required, "note": note}
        return {
            "role": "benchmark_candidate",
            "required": False,
            "note": OCR_CANDIDATE_NOTES.get(name, "evaluated in 96, not in the runtime"),
        }
    if any(a.startswith(E5_REPO_DIR + "/snapshots/") for a in aliases) or rel.startswith(E5_REPO_DIR + "/"):
        return {
            "role": "embedder_e5_small",
            "required": True,
            "note": "multilingual-e5-small (97 §2.13 F8; ONNX export pending)",
        }
    refs_file = models_root / (rel + ".refs")
    refs = refs_file.read_text(encoding="utf-8").split() if refs_file.is_file() else []
    models = sorted({r.split("/blobs/")[0].removeprefix("models--").replace("--", "/") for r in refs})
    return {
        "role": "unreferenced_candidate",
        "required": False,
        "note": "shared HF blob of an embedder evaluated in the analysis: "
        + (", ".join(models) or "unknown"),
    }


def build_manifest(models_root: Path) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    aliases: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(models_root):
        for filename in filenames:
            path = Path(dirpath) / filename
            rel = path.relative_to(models_root)
            if not _is_model_file(rel):
                continue
            if path.is_symlink():
                target = path.resolve().relative_to(models_root.resolve()).as_posix()
                aliases.setdefault(target, []).append(rel.as_posix())
                continue
            files[rel.as_posix()] = {"size_bytes": path.stat().st_size}
    entries = []
    for rel in sorted(files):
        entry: dict[str, object] = {
            "path": rel,
            "size_bytes": files[rel]["size_bytes"],
            "sha256": sha256_file(models_root / rel),
        }
        entry.update(_classify(rel, models_root, sorted(aliases.get(rel, []))))
        if aliases.get(rel):
            entry["aliases"] = sorted(aliases[rel])
        entries.append(entry)
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "models_root": ".models",
        "note": "Pinned by AG-00. Regenerate only with --update after a deliberate model change; commit the diff.",
        "files": entries,
    }


def verify(
    manifest: dict[str, object],
    models_root: Path,
    *,
    include_optional: bool,
    quick: bool,
    ocr_only: bool = False,
) -> list[str]:
    problems: list[str] = []
    for entry in manifest["files"]:  # type: ignore[union-attr]
        if not include_optional and not entry["required"]:
            continue
        if ocr_only and not str(entry["path"]).startswith("ocr/"):
            continue
        path = models_root / entry["path"]
        if not path.is_file():
            problems.append(f"отсутствует: {entry['path']}")
            continue
        if path.stat().st_size != entry["size_bytes"]:
            problems.append(
                f"размер изменён: {entry['path']} ({path.stat().st_size} ≠ {entry['size_bytes']})"
            )
            continue
        if not quick and sha256_file(path) != entry["sha256"]:
            problems.append(f"sha256 изменён: {entry['path']}")
        for alias in entry.get("aliases", []):
            alias_path = models_root / alias
            if not alias_path.exists() or alias_path.resolve() != path.resolve():
                problems.append(f"ссылка снимка не указывает на файл: {alias} → {entry['path']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка файлов моделей по tools/models/manifest.json (sha256)."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--models-root", type=Path, default=Path(os.environ.get("INSPECTOR_MODELS_ROOT", DEFAULT_MODELS_ROOT))
    )
    parser.add_argument(
        "--all", action="store_true", help="проверить и необязательные файлы (кандидаты бенчмарка)"
    )
    parser.add_argument("--quick", action="store_true", help="только наличие и размер, без sha256")
    parser.add_argument(
        "--ocr-only",
        action="store_true",
        help="только модели распознавания (ocr/…): всё, что нужно конвейеру; без эмбеддера e5",
    )
    parser.add_argument(
        "--update", action="store_true", help="перезаписать манифест по содержимому .models/ (AG-00)"
    )
    args = parser.parse_args(argv)

    if not args.models_root.is_dir():
        print(f"Каталог моделей не найден: {args.models_root}", file=sys.stderr)
        return 1
    if args.update:
        manifest = build_manifest(args.models_root)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        required = sum(1 for f in manifest["files"] if f["required"])  # type: ignore[index]
        print(
            f"Манифест обновлён: {len(manifest['files'])} файлов, обязательных: {required} → {args.manifest}"
        )  # type: ignore[arg-type]
        return 0
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Не удалось прочитать манифест {args.manifest}: {exc}", file=sys.stderr)
        return 2
    problems = verify(
        manifest, args.models_root, include_optional=args.all, quick=args.quick, ocr_only=args.ocr_only
    )
    checked = [
        f
        for f in manifest["files"]
        if (args.all or f["required"]) and (not args.ocr_only or str(f["path"]).startswith("ocr/"))
    ]
    for problem in problems:
        print(f"ОШИБКА: {problem}", file=sys.stderr)
    if problems:
        return 1
    mode = "размер" if args.quick else "sha256"
    total = sum(int(f["size_bytes"]) for f in checked)
    print(f"Модели в порядке: {len(checked)} файлов ({total / 1e6:.0f} МБ), проверка: {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
