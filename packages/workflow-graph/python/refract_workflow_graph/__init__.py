"""Refract Workflow Graph IR — Python validator.

Single source of truth is the shared JSON Schema at
``packages/workflow-graph/schema/workflow-graph.schema.json``. This module loads
that schema and validates graphs against it. Keep every producer/consumer keyed
off ``steps[].id`` — never renumber steps between pipeline stages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_HERE = Path(__file__).resolve().parent

# When installed as a wheel the schema is bundled at _schema/; in the source tree
# it lives two levels up under schema/. Try both.
_SCHEMA_CANDIDATES = [
    _HERE / "_schema" / "workflow-graph.schema.json",
    _HERE.parent.parent / "schema" / "workflow-graph.schema.json",
]
_EXAMPLE_CANDIDATES = [
    _HERE / "_examples" / "valid-example.json",
    _HERE.parent.parent / "examples" / "valid-example.json",
]


def _first_existing(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"None of the expected paths exist: {candidates}")


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Return the Workflow Graph JSON Schema as a dict."""
    return json.loads(_first_existing(_SCHEMA_CANDIDATES).read_text())


@lru_cache(maxsize=1)
def load_example() -> dict[str, Any]:
    """Return the canonical (master §2) example graph."""
    return json.loads(_first_existing(_EXAMPLE_CANDIDATES).read_text())


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]


def validate(data: Any) -> ValidationResult:
    """Validate ``data`` against the Workflow Graph schema (non-throwing)."""
    errors = [
        f"{'/' + '/'.join(map(str, e.path)) if e.path else '/'}: {e.message}"
        for e in sorted(_validator().iter_errors(data), key=lambda e: list(e.path))
    ]
    return ValidationResult(valid=not errors, errors=errors)


def assert_valid(data: Any) -> None:
    """Raise ``ValueError`` if ``data`` is not a valid Workflow Graph."""
    result = validate(data)
    if not result.valid:
        raise ValueError("Invalid Workflow Graph: " + "; ".join(result.errors))


__all__ = ["load_schema", "load_example", "validate", "assert_valid", "ValidationResult"]
