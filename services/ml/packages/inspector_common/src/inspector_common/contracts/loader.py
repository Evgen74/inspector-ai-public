"""Load and validate the contracts in packages/contracts (enums.yaml, codes.yaml, errors.yaml, schemas/).

    from inspector_common.contracts.loader import validate, load_enums
    validate("finding", finding_dict)             # raises ContractValidationError
    errors = validation_errors("submission.strict", doc)

Schemas reference each other by relative ``$ref``; they are resolved from a local registry built
from the files on disk. Nothing is ever fetched from the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from inspector_common.paths import contracts_dir

SCHEMA_BASE_URI = "https://contracts.inspector-ai.local/schemas/"


class ContractValidationError(ValueError):
    """A document does not satisfy its contract schema."""

    def __init__(self, schema: str, errors: list[str]):
        self.schema = schema
        self.errors = errors
        preview = "; ".join(errors[:5]) + (f"; … (+{len(errors) - 5})" if len(errors) > 5 else "")
        super().__init__(f"{schema}: {preview}")


@dataclass(frozen=True, slots=True)
class EnumValue:
    code: str
    label_ru: str | None = None
    aliases: tuple[str, ...] = ()
    status: str = "canonical"
    attrs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EnumSpec:
    name: str
    owner: str
    source: str
    values: tuple[EnumValue, ...]
    open: bool = False
    status: str = "canonical"
    description: str | None = None

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(v.code for v in self.values)

    def value(self, code: str) -> EnumValue:
        for v in self.values:
            if v.code == code or code in v.aliases:
                return v
        raise KeyError(f"{self.name}: unknown value {code!r}")

    def canonical(self, code: str) -> str:
        """Resolve an alias (e.g. v1.0 CONFIRMED) to the canonical code."""
        return self.value(code).code


def _contracts_path(*parts: str) -> Path:
    return contracts_dir().joinpath(*parts)


@cache
def _load_yaml(name: str) -> dict[str, Any]:
    with open(_contracts_path(name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_enums_raw() -> dict[str, Any]:
    return _load_yaml("enums.yaml")


def load_codes() -> dict[str, Any]:
    return _load_yaml("codes.yaml")


def load_errors_raw() -> dict[str, Any]:
    return _load_yaml("errors.yaml")


def load_run_layout() -> dict[str, Any]:
    """run_layout.yaml: path template, scope, format, schema and producer per ArtifactKind."""
    return _load_yaml("run_layout.yaml")


def load_rbac() -> dict[str, Any]:
    """rbac.yaml: permission → {Role: PermissionScope} grants enforced by the API (90 §3.10)."""
    return _load_yaml("rbac.yaml")


@lru_cache(maxsize=1)
def load_enums() -> dict[str, EnumSpec]:
    raw = load_enums_raw()
    specs: dict[str, EnumSpec] = {}
    for name, body in raw["enums"].items():
        values = []
        for item in body["values"]:
            if isinstance(item, str):
                values.append(EnumValue(code=item))
            else:
                known = {"code", "label_ru", "aliases", "status"}
                values.append(
                    EnumValue(
                        code=str(item["code"]),
                        label_ru=item.get("label_ru"),
                        aliases=tuple(item.get("aliases", ())),
                        status=item.get("status", "canonical"),
                        attrs={k: v for k, v in item.items() if k not in known},
                    )
                )
        specs[name] = EnumSpec(
            name=name,
            owner=body["owner"],
            source=body.get("source", ""),
            values=tuple(values),
            open=bool(body.get("open", False)),
            status=body.get("status", "canonical"),
            description=body.get("description"),
        )
    return specs


def enum_mappings() -> dict[str, Any]:
    return load_enums_raw().get("mappings", {})


@lru_cache(maxsize=1)
def load_errors() -> dict[str, dict[str, Any]]:
    """Error catalogue keyed by code, with `defaults` applied."""
    raw = load_errors_raw()
    defaults = dict(raw.get("defaults", {}))
    level_by_severity = defaults.pop("log_level_by_severity", {})
    catalogue: dict[str, dict[str, Any]] = {}
    for entry in raw["errors"]:
        merged = {**defaults, **entry}
        merged.setdefault("log_level", level_by_severity.get(merged["severity"], "INFO"))
        catalogue[merged["code"]] = merged
    return catalogue


def schema_names() -> list[str]:
    """Schema stems, e.g. ``finding``, ``submission.strict``."""
    return sorted(
        p.name.removesuffix(".schema.json") for p in _contracts_path("schemas").glob("*.schema.json")
    )


@cache
def load_schema(name: str) -> dict[str, Any]:
    path = _contracts_path("schemas", f"{name}.schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def schema_uri(name: str) -> str:
    return f"{SCHEMA_BASE_URI}{name}.schema.json"


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources = []
    for name in schema_names():
        doc = load_schema(name)
        resources.append((schema_uri(name), Resource.from_contents(doc, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Draft202012Validator:
    doc = load_schema(name)
    if "$id" not in doc:
        # The vendored organizer schema has no $id; anchor it at its registry URI.
        doc = {**doc, "$id": schema_uri(name)}
    return Draft202012Validator(doc, registry=registry())


def iter_validation_errors(name: str, instance: Any) -> Iterator[ValidationError]:
    return validator(name).iter_errors(instance)


def validation_errors(name: str, instance: Any) -> list[str]:
    errors = sorted(iter_validation_errors(name, instance), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def is_valid(name: str, instance: Any) -> bool:
    return validator(name).is_valid(instance)


def validate(name: str, instance: Any) -> None:
    errors = validation_errors(name, instance)
    if errors:
        raise ContractValidationError(name, errors)


def contract_version() -> str:
    return str(load_enums_raw()["contract_version"])


def clear_caches() -> None:
    """Drop every cached contract (tests that point INSPECTOR_CONTRACTS_DIR elsewhere)."""
    for fn in (_load_yaml, load_enums, load_errors, load_schema, registry, validator):
        fn.cache_clear()
