"""Check parameters: the `params` header key and `{{name}}` placeholders
(docs/decisions/D-DBA-24-check-parameters.md).

This module is the only code that fills placeholders, and it fills one only with
a value that fully matches its type's pattern.
"""

import dataclasses
import re
from dataclasses import dataclass

NAME = re.compile(r"[a-z][a-z0-9_]*")
TYPES = {"sql_id": re.compile(r"[0-9a-z]{13}"), "int": re.compile(r"[0-9]{1,9}")}
ITEM = re.compile(r"([^:=]*):([^:=]*)(?:=(.*))?")
# `{{name}}`, or a bare `{{` (no group 1) that names nothing
PLACEHOLDER = re.compile(rf"\{{\{{(?:({NAME.pattern})\}}\}})?")


class ParamError(ValueError):
    """A malformed `params` list, or a parameter value that cannot be bound."""


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    default: str | None  # the default's text, e.g. "60"


def parse_params(text: str) -> tuple[Param, ...]:
    """The `params` header value `name:type[=default], ...` as Params, in order."""
    params: dict[str, Param] = {}
    for item in text.split(","):
        match = ITEM.fullmatch(item.strip())
        if not match:
            raise ParamError(f"params item {item.strip()!r} is not name:type or name:type=default")
        name, type_, default = match.groups()
        if not NAME.fullmatch(name):
            raise ParamError(f"parameter name {name!r} does not match {NAME.pattern}")
        if name in params:
            raise ParamError(f"parameter {name} is declared twice")
        if type_ not in TYPES:
            raise ParamError(f"parameter {name}: type {type_!r} is not one of {', '.join(TYPES)}")
        if type_ == "sql_id" and default is not None:
            raise ParamError(f"parameter {name}: a sql_id parameter has no default")
        if type_ == "int" and default is None:
            raise ParamError(f"parameter {name}: an int parameter needs a default")
        if type_ == "int" and not TYPES["int"].fullmatch(default):
            raise ParamError(f"parameter {name}: default {default!r} is not an int")
        params[name] = Param(name, type_, default)
    return tuple(params.values())


def _checked(check, values: dict[str, str]) -> dict[str, str]:
    """`values` plus defaults, each value matched against its parameter's type."""
    declared = {p.name for p in check.params}
    for name in values:
        if name not in declared:
            raise ParamError(f"unknown parameter {name} for check {check.id}")
    filled = {}
    for p in check.params:
        value = values.get(p.name, p.default)
        if value is None:
            raise ParamError(f"parameter {p.name} is required for check {check.id}")
        if not TYPES[p.type].fullmatch(value):
            raise ParamError(f"parameter {p.name}: {value!r} is not a {p.type}")
        filled[p.name] = value
    return filled


def _fill(text: str, filled: dict[str, str]) -> str:
    # An undeclared name is left as written: lint reports it (L016).
    return PLACEHOLDER.sub(lambda m: filled.get(m[1], m[0]), text)


def bind(check, values: dict[str, str]):
    """`check` with every placeholder in its SQL filled from `values` and defaults."""
    return dataclasses.replace(check, sql=_fill(check.sql, _checked(check, values)))


def render_file(check, values: dict[str, str]) -> str:
    """The check's whole file, header included, with placeholders filled as by `bind`."""
    return _fill(check.path.read_text(encoding="utf-8"), _checked(check, values))
