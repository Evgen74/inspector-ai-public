"""Contracts-lite: loaders, validators, generated enums and pydantic models for packages/contracts.

Contracts are law (CLAUDE.md): add enum values, fields or error codes only through AG-00.
"""

from inspector_common.contracts.loader import (
    ContractValidationError,
    is_valid,
    load_codes,
    load_enums,
    load_errors,
    load_schema,
    schema_names,
    validate,
    validation_errors,
)

__all__ = [
    "ContractValidationError",
    "is_valid",
    "load_codes",
    "load_enums",
    "load_errors",
    "load_schema",
    "schema_names",
    "validate",
    "validation_errors",
]
