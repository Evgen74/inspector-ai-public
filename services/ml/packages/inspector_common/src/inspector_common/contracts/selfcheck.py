"""Consistency checks over packages/contracts, run by `inspector-contracts check` and by the tests.

Each function returns a list of human-readable problems; an empty list means OK.
"""

from __future__ import annotations

import json
import re
import string
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from inspector_common.contracts import codegen, loader
from inspector_common.hashing import sha256_file
from inspector_common.paths import contracts_dir

LOWERCASE_ENUMS = {"DataType", "ExportFormat", "SubmissionVariant"}
_UPPER = re.compile(r"^[A-Z][A-Z0-9_]*$")
_LOWER = re.compile(r"^[a-z][a-z0-9_]*$")


def check_generated() -> list[str]:
    changed = codegen.generate(write=False)
    return [f"generated file is stale, run `make contracts`: {path}" for path, did in changed.items() if did]


def _iter_refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def check_schemas() -> list[str]:
    problems: list[str] = []
    registry = loader.registry()
    for name in loader.schema_names():
        doc = loader.load_schema(name)
        try:
            Draft202012Validator.check_schema(doc)
        except Exception as exc:  # pragma: no cover - reported, not raised
            problems.append(f"{name}: not a valid 2020-12 schema: {exc}")
            continue
        if name != "submission.organizer" and doc.get("$id") != loader.schema_uri(name):
            problems.append(f"{name}: $id must be {loader.schema_uri(name)}")
        resolver = registry.resolver(base_uri=loader.schema_uri(name))
        for ref in sorted(set(_iter_refs(doc))):
            try:
                resolver.lookup(ref)
            except Exception as exc:
                problems.append(f"{name}: unresolvable $ref {ref!r}: {type(exc).__name__}")
    return problems


def check_vendored() -> list[str]:
    problems: list[str] = []
    with open(contracts_dir() / "vendored.yaml", encoding="utf-8") as fh:
        vendored = yaml.safe_load(fh)
    for rel, meta in vendored["files"].items():
        path = contracts_dir() / rel
        if not path.is_file():
            problems.append(f"vendored file missing: {rel}")
        elif sha256_file(path) != meta["sha256"]:
            problems.append(f"vendored file modified (must stay byte-identical): {rel}")
    return problems


def check_examples() -> list[str]:
    problems: list[str] = []
    root = contracts_dir() / "examples"
    names = set(loader.schema_names())
    for schema_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        name = schema_dir.name
        if name not in names:
            problems.append(f"examples/{name}: no schema {name}.schema.json")
            continue
        for kind in ("valid", "invalid"):
            for file in sorted((schema_dir / kind).glob("*.json")):
                doc = json.loads(file.read_text(encoding="utf-8"))
                ok = loader.is_valid(name, doc)
                if kind == "valid" and not ok:
                    problems.append(
                        f"{file.relative_to(root)}: expected valid: {loader.validation_errors(name, doc)[:3]}"
                    )
                if kind == "invalid" and ok:
                    problems.append(f"{file.relative_to(root)}: expected invalid but it validates")
    return problems


def check_enums() -> list[str]:
    problems: list[str] = []
    specs = loader.load_enums()
    for name, spec in specs.items():
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
            problems.append(f"enum name not PascalCase: {name}")
        if not spec.owner.startswith("AG-"):
            problems.append(f"{name}: owner must be an agent id (AG-xx), got {spec.owner!r}")
        pattern = _LOWER if name in LOWERCASE_ENUMS else _UPPER
        codes = [v.code for v in spec.values]
        for code, count in Counter(codes).items():
            if count > 1:
                problems.append(f"{name}: duplicate value {code}")
        for value in spec.values:
            if not pattern.fullmatch(value.code):
                problems.append(f"{name}: bad value spelling {value.code!r}")
            for alias in value.aliases:
                if alias in codes:
                    problems.append(f"{name}: alias {alias} collides with a value")
    mappings = loader.enum_mappings()
    comparison = set(specs["ComparisonResult"].codes)
    for discrepancy, result in mappings["discrepancy_to_comparison_result"].items():
        if discrepancy not in specs["DiscrepancyType"].codes:
            problems.append(
                f"mappings.discrepancy_to_comparison_result: unknown DiscrepancyType {discrepancy}"
            )
        if result not in comparison:
            problems.append(f"mappings.discrepancy_to_comparison_result: unknown ComparisonResult {result}")
    missing = set(specs["DiscrepancyType"].codes) - set(mappings["discrepancy_to_comparison_result"])
    if missing:
        problems.append(f"mappings.discrepancy_to_comparison_result: unmapped {sorted(missing)}")
    labels = set(specs["ViolationLabel"].codes)
    statuses = set(specs["ProtocolParamStatus"].codes)
    by_label = mappings["protocol_status_by_label"]
    if set(by_label) != labels:
        problems.append("mappings.protocol_status_by_label must cover every ViolationLabel")
    for label, allowed in by_label.items():
        for status in allowed:
            if status not in statuses:
                problems.append(f"mappings.protocol_status_by_label.{label}: unknown status {status}")
    for value in specs["ManifestSplit"].values:
        if value.attrs.get("maps_to_split") not in specs["Split"].codes:
            problems.append(f"ManifestSplit.{value.code}: maps_to_split must be a Split value")
    for value in specs["CompletenessBasis"].values:
        if value.attrs.get("maps_to") not in specs["CompletenessStatus"].codes:
            problems.append(f"CompletenessBasis.{value.code}: maps_to must be a CompletenessStatus value")
    return problems


def check_codes() -> list[str]:
    problems: list[str] = []
    codes = loader.load_codes()
    expected_next = codes["param_id_range"][0]
    for prefix in codes["prefixes"]:
        if prefix["first"] != expected_next:
            problems.append(
                f"codes.yaml: prefix {prefix['latin']} starts at {prefix['first']}, expected {expected_next}"
            )
        expected_next = prefix["last"] + 1
    if expected_next - 1 != codes["param_id_range"][1]:
        problems.append("codes.yaml: prefixes do not cover the whole id range")
    free_topics = set(loader.load_enums()["FreeTopic"].codes)
    free_in_schema = re.search(
        r"FREE-\(([^)]*)\)", json.dumps(loader.load_schema("common")["$defs"]["FreeParameterCode"])
    )
    if not free_in_schema or set(free_in_schema.group(1).split("|")) != free_topics:
        problems.append("common.schema.json FreeParameterCode topics differ from enums.FreeTopic")
    return problems


def _placeholders(template: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


def check_errors() -> list[str]:
    problems: list[str] = []
    raw = loader.load_errors_raw()
    vocab = raw["vocabularies"]
    seen_codes: Counter[str] = Counter(e["code"] for e in raw["errors"])
    for code, count in seen_codes.items():
        if count > 1:
            problems.append(f"errors.yaml: duplicate code {code}")
    details_templates: Counter[str] = Counter()
    for code, entry in loader.load_errors().items():
        for required in ("http", "domain", "severity", "title_ru", "detail_ru"):
            if required not in entry:
                problems.append(f"{code}: missing {required}")
        if not _UPPER.fullmatch(code):
            problems.append(f"{code}: code must be UPPER_SNAKE")
        if entry.get("severity") == "error" and not entry.get("hint_ru"):
            problems.append(f"{code}: severity=error needs hint_ru")
        http = entry.get("http")
        if http is not None and not (400 <= int(http) <= 599):
            problems.append(f"{code}: http {http} out of 4xx/5xx")
        for key in ("domain", "scope", "severity", "log_level", "alert", "user_notification"):
            if key in entry and entry[key] not in vocab[key]:
                problems.append(f"{code}: {key}={entry[key]!r} not in vocabulary")
        declared = set((entry.get("details") or {}).keys())
        for field_name in ("title_ru", "detail_ru", "hint_ru"):
            text = entry.get(field_name) or ""
            undeclared = _placeholders(text) - declared
            if undeclared:
                problems.append(
                    f"{code}.{field_name}: placeholders not declared in details: {sorted(undeclared)}"
                )
            if re.search(r"[А-Яа-яЁё][A-Za-z]|[A-Za-z][А-Яа-яЁё]", text):
                problems.append(f"{code}.{field_name}: Latin look-alike letter inside a Russian word")
        details_templates[entry["detail_ru"]] += 1
        for action in (entry.get("ui") or {}).get("actions", []):
            if action not in vocab["actions"]:
                problems.append(f"{code}: unknown UI action {action}")
    for template, count in details_templates.items():
        if count > 1:
            problems.append(f"errors.yaml: detail_ru shared by {count} codes: {template[:60]}…")
    return problems


_PLACEHOLDERS = {"object_id", "file_id", "page05", "command"}


def check_run_layout() -> list[str]:
    """run_layout.yaml covers exactly ArtifactKind, and every entry names known formats, scopes and schemas."""
    problems: list[str] = []
    layout = loader.load_run_layout()
    specs = loader.load_enums()
    kinds = set(specs["ArtifactKind"].codes)
    entries = layout.get("artifacts", {})
    if set(entries) != kinds:
        problems.append(
            f"run_layout.yaml artifacts must equal enums.ArtifactKind: only in yaml {sorted(set(entries) - kinds)}, "
            f"only in enum {sorted(kinds - set(entries))}"
        )
    schemas = set(loader.schema_names())
    run_artifacts = loader.load_schema("run_artifacts")["properties"]["layout_version"]["const"]
    if str(layout.get("layout_version")) != run_artifacts:
        problems.append(
            "run_layout.yaml layout_version differs from run_artifacts.schema.json layout_version"
        )
    for kind, entry in entries.items():
        if entry.get("format") not in specs["ArtifactFormat"].codes:
            problems.append(f"run_layout.{kind}: unknown format {entry.get('format')!r}")
        if entry.get("scope") not in specs["ArtifactScope"].codes:
            problems.append(f"run_layout.{kind}: unknown scope {entry.get('scope')!r}")
        schema = entry.get("schema")
        if schema is not None and schema not in schemas:
            problems.append(f"run_layout.{kind}: unknown schema {schema!r}")
        path = str(entry.get("path", ""))
        if not path or path.startswith("/") or ".." in path or "\\" in path:
            problems.append(f"run_layout.{kind}: path must be relative POSIX inside the run: {path!r}")
        undeclared = _placeholders(path) - _PLACEHOLDERS
        if undeclared:
            problems.append(f"run_layout.{kind}: unknown placeholders {sorted(undeclared)}")
        agent = str((entry.get("producer") or {}).get("agent", ""))
        if not re.fullmatch(r"AG-[0-9]{2}[A-Z]?", agent):
            problems.append(f"run_layout.{kind}: producer.agent must be an agent id, got {agent!r}")
    return problems


def check_table_columns() -> list[str]:
    """table_artifacts.schema.json pins the same cell keys per TableType as enums.yaml `columns`."""
    problems: list[str] = []
    expected = {v.code: list(v.attrs.get("columns") or []) for v in loader.load_enums()["TableType"].values}
    typed = loader.load_schema("table_artifacts")["$defs"]["TypedTable"]
    pinned: dict[str, list[str]] = {}
    for branch in typed.get("allOf", []):
        code = branch["if"]["properties"]["table_type"]["const"]
        props = branch["then"]["properties"]
        row_keys = props["rows"]["items"]["properties"]["cells"]["propertyNames"]["enum"]
        column_keys = props["columns"]["items"]["properties"]["key"]["enum"]
        if row_keys != column_keys:
            problems.append(f"table_artifacts {code}: row cell keys differ from column keys")
        pinned[code] = row_keys
    for code, columns in expected.items():
        if not columns:
            problems.append(f"TableType.{code}: `columns` must be a non-empty list")
        if pinned.get(code) != columns:
            problems.append(f"table_artifacts.schema.json columns of {code} differ from enums.yaml TableType")
    for code in set(pinned) - set(expected):
        problems.append(f"table_artifacts.schema.json pins unknown TableType {code}")
    return problems


_PERMISSION = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")


def check_rbac() -> list[str]:
    """rbac.yaml: unique dotted permission codes, Role grants with PermissionScope values, Russian labels."""
    problems: list[str] = []
    raw = loader.load_rbac()
    specs = loader.load_enums()
    roles = set(specs["Role"].codes)
    scopes = set(specs["PermissionScope"].codes)
    seen: Counter[str] = Counter()
    for entry in raw.get("permissions") or []:
        code = str(entry.get("code", ""))
        seen[code] += 1
        if not _PERMISSION.fullmatch(code):
            problems.append(f"rbac.yaml: bad permission code {code!r} (expected dotted lowercase)")
        if not entry.get("label_ru"):
            problems.append(f"rbac.yaml {code}: label_ru is required")
        grants = entry.get("grants") or {}
        if not grants:
            problems.append(f"rbac.yaml {code}: no role is granted")
        for role, scope in grants.items():
            if role not in roles:
                problems.append(f"rbac.yaml {code}: unknown Role {role}")
            if scope not in scopes:
                problems.append(f"rbac.yaml {code}: {role} has unknown PermissionScope {scope}")
    for code, count in seen.items():
        if count > 1:
            problems.append(f"rbac.yaml: duplicate permission {code}")
    return problems


def check_openapi() -> list[str]:
    """packages/contracts/openapi/openapi.yaml exists, is OAS 3.0.x and names only catalogued error codes,
    rbac.yaml permissions (`x-permission`) and AuditAction values (`x-audit-action`).

    Route ↔ operation conformance and `x-contract-enum` equality are checked by the API tests."""
    path = contracts_dir() / "openapi" / "openapi.yaml"
    if not path.is_file():
        return ["openapi/openapi.yaml is missing (the API contract lives in packages/contracts since M1)"]
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    problems: list[str] = []
    if not re.fullmatch(r"3\.0\.\d+", str(doc.get("openapi", ""))):
        problems.append(f"openapi.yaml: expected OpenAPI 3.0.x, got {doc.get('openapi')!r}")
    known = set(loader.load_errors())
    permissions = {str(p.get("code")) for p in loader.load_rbac().get("permissions") or []}
    actions = set(loader.load_enums()["AuditAction"].codes)
    for route, item in (doc.get("paths") or {}).items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            for code in operation.get("x-error-codes", []) or []:
                if code not in known:
                    problems.append(f"openapi.yaml {method.upper()} {route}: unknown error code {code}")
            permission = operation.get("x-permission")
            if permission is not None and permission not in permissions:
                problems.append(f"openapi.yaml {method.upper()} {route}: unknown x-permission {permission}")
            action = operation.get("x-audit-action")
            if action is not None and action not in actions:
                problems.append(f"openapi.yaml {method.upper()} {route}: unknown x-audit-action {action}")
    return problems


def run_selfcheck() -> list[str]:
    problems: list[str] = []
    for check in (
        check_generated,
        check_schemas,
        check_vendored,
        check_examples,
        check_enums,
        check_codes,
        check_errors,
        check_run_layout,
        check_table_columns,
        check_rbac,
        check_openapi,
    ):
        problems.extend(check())
    return problems


def examples_root() -> Path:
    return contracts_dir() / "examples"
