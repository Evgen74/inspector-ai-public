"""Generate derived contract artifacts from packages/contracts/{enums,errors}.yaml.

Outputs (committed; `make test` fails on drift, `make contracts` regenerates):
- packages/contracts/schemas/enums.schema.json — one ``$defs`` entry per enum.
- services/ml/packages/inspector_common/src/inspector_common/contracts/enums.py — StrEnums + ErrorCode.

TypeScript generation belongs to AG-08 (apps/web, apps/api) and reads the same YAML.
"""

from __future__ import annotations

import json
import keyword
import re
from pathlib import Path

from inspector_common.contracts.loader import (
    SCHEMA_BASE_URI,
    contract_version,
    load_enums,
    load_errors_raw,
)
from inspector_common.paths import contracts_dir

GENERATED_NOTE = "GENERATED from packages/contracts/{src} by `inspector-contracts gen`. Do not edit."


def enums_schema_path() -> Path:
    return contracts_dir() / "schemas" / "enums.schema.json"


def enums_py_path() -> Path:
    return Path(__file__).with_name("enums.py")


def member_name(code: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]", "_", code).upper()
    if name[0].isdigit() or keyword.iskeyword(name):
        name = f"V_{name}"
    return name


def render_enums_schema() -> str:
    defs: dict[str, dict[str, object]] = {}
    for name, spec in load_enums().items():
        description = (
            f"{spec.description + ' ' if spec.description else ''}Owner: {spec.owner}. Source: {spec.source}."
        )
        if spec.open:
            defs[name] = {
                "description": f"OPEN vocabulary (unknown values allowed and kept raw). {description}",
                "type": "string",
                "minLength": 1,
                "examples": list(spec.codes),
            }
        else:
            defs[name] = {"description": description, "enum": list(spec.codes)}
    doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE_URI}enums.schema.json",
        "title": "Enums",
        "description": GENERATED_NOTE.format(src="enums.yaml") + f" Contract version {contract_version()}.",
        "$defs": defs,
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def render_enums_py() -> str:
    lines = [
        f'"""{GENERATED_NOTE.format(src="enums.yaml and errors.yaml")}"""',
        "",
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "",
        f'CONTRACT_VERSION = "{contract_version()}"',
        "",
    ]
    specs = load_enums()
    for name, spec in specs.items():
        seen: set[str] = set()
        lines.append("")
        lines.append(f"class {name}(StrEnum):")
        flag = " OPEN vocabulary: unknown values may occur in data; keep them raw." if spec.open else ""
        lines.append(f'    """Owner: {spec.owner}.{flag}"""')
        lines.append("")
        for value in spec.values:
            member = member_name(value.code)
            if member in seen:
                raise ValueError(f"{name}: duplicate member name {member}")
            seen.add(member)
            comment = f"  # {value.label_ru}" if value.label_ru else ""
            lines.append(f'    {member} = "{value.code}"{comment}')
        lines.append("")
    errors = [e["code"] for e in load_errors_raw()["errors"]]
    lines.append("")
    lines.append("class ErrorCode(StrEnum):")
    lines.append('    """Codes of packages/contracts/errors.yaml."""')
    lines.append("")
    for code in errors:
        lines.append(f'    {member_name(code)} = "{code}"')
    lines.append("")
    lines.append("")
    lines.append("ENUMS: dict[str, type[StrEnum]] = {")
    for name in specs:
        lines.append(f'    "{name}": {name},')
    lines.append("}")
    open_names = ", ".join(f'"{n}"' for n, s in specs.items() if s.open)
    lines.append(f"OPEN_ENUMS: frozenset[str] = frozenset({{{open_names}}})")
    lines.append("")
    return "\n".join(lines)


def generate(write: bool = True) -> dict[Path, bool]:
    """Render every artifact; write it when ``write`` is true. Returns {path: changed}."""
    outputs = {enums_schema_path(): render_enums_schema(), enums_py_path(): render_enums_py()}
    changed: dict[Path, bool] = {}
    for path, content in outputs.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        changed[path] = current != content
        if write and changed[path]:
            path.write_text(content, encoding="utf-8")
    return changed
