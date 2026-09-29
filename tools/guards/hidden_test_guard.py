#!/usr/bin/env python3
"""Hidden-test integrity guard (97 §2.17, 93 §4.9): fail if code or config mentions the hidden object.

Scans our code and configuration (not docs/, not tools/prototypes/, not organizer data) for:
- manifest file ids of the hidden object (F0205–F0417; the exact set is also read from the manifest
  when the organizer data is present),
- the hidden object's name, its residential-complex name and its project codes (patterns below are
  stored in escaped form so that this file does not trip itself).

A line may opt out with the marker ``hidden-guard: allow`` (use sparingly, with a reason).
Stdlib only. Exit 0 = clean, 1 = findings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = ("services", "packages", "apps", "tools")
SCAN_ROOT_FILES = (
    "Makefile",
    "README.md",
    "CLAUDE.md",
    ".env.example",
    "package.json",
    "pnpm-workspace.yaml",
)
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".turbo",
    ".cache",
    "runs",
    ".models",
    "data",
    "data_utf8",
    "ТЗ",
    "docs",
}
EXCLUDE_PREFIXES = ("tools/prototypes/", "tools/guards/")
TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".sql",
    ".sh",
    ".cfg",
    ".ini",
    ".csv",
    ".html",
    ".css",
    ".env",
    ".example",
}
MAX_BYTES = 5 * 1024 * 1024
ALLOW_MARKER = "hidden-guard: allow"

# Escaped so that the guard source does not contain the literal strings it forbids.
PATTERNS: dict[str, re.Pattern[str]] = {
    "hidden_file_id_range": re.compile(r"\bF0(?:20[5-9]|2[1-9]\d|3\d\d|40\d|41[0-7])\b"),
    "hidden_object_name": re.compile("речников", re.IGNORECASE),
    "hidden_complex_name": re.compile("ривер\\s*парк", re.IGNORECASE),
    "hidden_project_code": re.compile(r"01-07/2[23]-14"),
}


def hidden_file_ids_from_manifest(manifest: Path) -> set[str]:
    ids: set[str] = set()
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("split") == "TEST_HIDDEN":
                    ids.add(row["file_id"])
    return ids


def iter_files(root: Path) -> Iterator[Path]:
    for name in SCAN_ROOT_FILES:
        path = root / name
        if path.is_file():
            yield path
    for top in SCAN_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or any(part in EXCLUDE_PARTS for part in path.relative_to(root).parts):
                continue
            if rel.startswith(EXCLUDE_PREFIXES):
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Makefile", "Dockerfile"}:
                continue
            if path.stat().st_size > MAX_BYTES:
                continue
            yield path


def scan(root: Path, extra_ids: Iterable[str] = ()) -> list[str]:
    extra = set(extra_ids)
    extra_re = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, extra))) + r")\b") if extra else None
    findings: list[str] = []
    for path in iter_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            hits = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
            if extra_re is not None and extra_re.search(line):
                hits.append("hidden_file_id_manifest")
            if hits:
                findings.append(
                    f"{path.relative_to(root).as_posix()}:{lineno}: {', '.join(sorted(set(hits)))}"
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка: код и конфигурация не содержат сведений о скрытом объекте."
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="document_manifest.jsonl (по умолчанию из data_utf8/, если есть)",
    )
    args = parser.parse_args(argv)
    manifest = args.manifest or (
        args.root / "data_utf8" / "ПАКЕТ_УЧАСТНИКАМ_БЕЗ_ОТВЕТОВ_v2.0" / "data" / "document_manifest.jsonl"
    )
    findings = scan(args.root, hidden_file_ids_from_manifest(manifest))
    for finding in findings:
        print(f"НАРУШЕНИЕ: {finding}", file=sys.stderr)
    if findings:
        print(
            f"Найдено упоминаний скрытого объекта: {len(findings)}. Уберите их (правила: CLAUDE.md).",
            file=sys.stderr,
        )
        return 1
    print("Проверка скрытой выборки: чисто.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
