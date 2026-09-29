"""IAI-Logic v1: the rule-expression language of Logical_Rules (90 C-55), with Kleene three-valued semantics.

A JSONLogic subset, so the admin UI can preview rules with json-logic-js, evaluated here by a small safe
interpreter (no ``eval``, an operator whitelist, depth and size limits):

- data: ``var`` (dotted path, optional default), ``missing``, ``missing_some``;
- logic: ``and``, ``or``, ``!``, ``!!``, ``if``;
- comparison: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=`` (``<``/``<=`` also take three arguments: between);
- membership: ``in`` (list membership or substring);
- arrays: ``some``, ``all``, ``none``, ``filter``, ``map``, ``count``, ``sum``, ``merge``;
- arithmetic: ``+``, ``-``, ``*``, ``/``, ``min``, ``max``, ``abs``, ``round``.

Three-valued semantics (07 §3.3.1): a missing fact is ``UNKNOWN``. Comparisons and arithmetic with an
``UNKNOWN`` operand are ``UNKNOWN``; ``and`` is FALSE if any operand is FALSE, else UNKNOWN if any is UNKNOWN;
``or`` dually; ``!`` keeps UNKNOWN. Array operators are strict: an UNKNOWN array, or an UNKNOWN element result
that could change the answer, gives UNKNOWN. A rule emits a suspicion only when its condition is TRUE and its
expected clause is FALSE; UNKNOWN never emits.

Extensions over JSONLogic (documented, rejected by json-logic-js previews only where noted):
- inside ``some``/``all``/``none``/``filter``/``map``/``count``/``sum`` the data is the element (JSONLogic
  scoping); a ``var`` path starting with ``^`` reads the rule's root facts instead (``{"var": "^rd.code_keys"}``);
- ``count`` and ``sum`` take ``[array]`` or ``[array, expression]``; ``abs`` and ``round`` are ours;
- ``all`` over an empty array is FALSE (JSONLogic parity), ``none`` over an empty array is TRUE;
- ``merge`` skips UNKNOWN arguments (it only collects, e.g. evidence of several facts).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

MAX_DEPTH: Final = 48
MAX_NODES: Final = 20_000
MAX_ITEMS: Final = 100_000

LANGUAGE: Final = "IAI-Logic v1"


class _UnknownType:
    """The third truth value. Never usable as a Python bool: that would silently turn UNKNOWN into FALSE."""

    _instance: _UnknownType | None = None

    def __new__(cls) -> _UnknownType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:
        raise TypeError("UNKNOWN has no Python truth value; use logic.truth()")

    def __reduce__(self) -> str:
        return "UNKNOWN"


UNKNOWN: Final = _UnknownType()
Truth = bool | _UnknownType


class LogicError(ValueError):
    """A malformed expression (unknown operator, wrong arity, too deep or too large)."""


def is_unknown(value: Any) -> bool:
    return value is UNKNOWN


def truth(value: Any) -> Truth:
    """JSONLogic truthiness, three-valued: None/UNKNOWN → UNKNOWN; 0, "", [] → FALSE."""
    if value is UNKNOWN or value is None:
        return UNKNOWN
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str | list | tuple | dict):
        return len(value) > 0
    return True


def truth_label(value: Truth) -> str:
    return "UNKNOWN" if value is UNKNOWN else ("TRUE" if value else "FALSE")


def _kleene_and(values: Sequence[Truth]) -> Truth:
    if any(v is False for v in values):
        return False
    if any(v is UNKNOWN for v in values):
        return UNKNOWN
    return True


def _kleene_or(values: Sequence[Truth]) -> Truth:
    if any(v is True for v in values):
        return True
    if any(v is UNKNOWN for v in values):
        return UNKNOWN
    return False


def _kleene_not(value: Truth) -> Truth:
    return UNKNOWN if value is UNKNOWN else not value


def _num(value: Any) -> float | _UnknownType:
    if value is UNKNOWN or value is None or isinstance(value, bool):
        return UNKNOWN
    if isinstance(value, int | float):
        return UNKNOWN if isinstance(value, float) and math.isnan(value) else float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ".").replace("−", "-"))
        except ValueError:
            return UNKNOWN
    return UNKNOWN


def _lookup(data: Any, path: str) -> Any:
    if path == "":
        return data
    cur = data
    for part in path.split("."):
        if isinstance(cur, Mapping):
            if part not in cur:
                return UNKNOWN
            cur = cur[part]
        elif isinstance(cur, list | tuple) and part.lstrip("-").isdigit():
            idx = int(part)
            if not -len(cur) <= idx < len(cur):
                return UNKNOWN
            cur = cur[idx]
        else:
            return UNKNOWN
        if cur is None:
            return UNKNOWN
    return cur


# Operator arities: (min, max); None = unbounded.
_ARITY: Final[dict[str, tuple[int, int | None]]] = {
    "var": (0, 2),
    "missing": (0, None),
    "missing_some": (2, 2),
    "and": (1, None),
    "or": (1, None),
    "!": (1, 1),
    "!!": (1, 1),
    "if": (1, None),
    "==": (2, 2),
    "!=": (2, 2),
    "<": (2, 3),
    "<=": (2, 3),
    ">": (2, 2),
    ">=": (2, 2),
    "in": (2, 2),
    "some": (2, 2),
    "all": (2, 2),
    "none": (2, 2),
    "filter": (2, 2),
    "map": (2, 2),
    "count": (1, 2),
    "sum": (1, 2),
    "merge": (0, None),
    "+": (1, None),
    "-": (1, 2),
    "*": (1, None),
    "/": (2, 2),
    "min": (1, None),
    "max": (1, None),
    "abs": (1, 1),
    "round": (1, 2),
}
OPERATORS: Final = frozenset(_ARITY)
_ARRAY_OPS: Final = frozenset({"some", "all", "none", "filter", "map", "count", "sum"})


def _args(node: Mapping[str, Any]) -> tuple[str, list[Any]]:
    if len(node) != 1:
        raise LogicError(f"an operation must have exactly one operator key, got {sorted(node)}")
    ((op, raw),) = node.items()
    return op, list(raw) if isinstance(raw, list) else [raw]


def validate_expression(expr: Any) -> list[str]:
    """Problems of an expression (empty = valid): unknown operators, wrong arity, depth and size limits."""
    problems: list[str] = []
    nodes = 0

    def walk(node: Any, depth: int, path: str) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES:
            if nodes == MAX_NODES + 1:
                problems.append(f"expression larger than {MAX_NODES} nodes")
            return
        if depth > MAX_DEPTH:
            problems.append(f"{path}: nested deeper than {MAX_DEPTH}")
            return
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, depth + 1, f"{path}[{i}]")
            return
        if not isinstance(node, dict):
            return
        if len(node) != 1:
            problems.append(f"{path}: an operation needs exactly one operator key, got {sorted(node)}")
            return
        op, args = _args(node)
        if op not in _ARITY:
            problems.append(f"{path}: unknown operator {op!r}")
            return
        lo, hi = _ARITY[op]
        if len(args) < lo or (hi is not None and len(args) > hi):
            problems.append(
                f"{path}: {op!r} takes {lo}..{hi if hi is not None else 'n'} arguments, got {len(args)}"
            )
        if op == "var" and args and not isinstance(args[0], str | int | dict):
            problems.append(f"{path}: 'var' needs a path string")
        for i, a in enumerate(args):
            walk(a, depth + 1, f"{path}.{op}[{i}]")

    walk(expr, 0, "$")
    return problems


class Evaluator:
    """Evaluates expressions over one root fact document; records the root facts it read (``used``)."""

    def __init__(self, root: Mapping[str, Any]):
        self.root = root
        self.used: dict[str, Any] = {}
        self._nodes = 0

    # public API ------------------------------------------------------------------------------------
    def evaluate(self, expr: Any) -> Any:
        self._nodes = 0
        return self._eval(expr, self.root, 0, True)

    def truth(self, expr: Any) -> Truth:
        return truth(self.evaluate(expr))

    # internals -------------------------------------------------------------------------------------
    def _eval(self, node: Any, data: Any, depth: int, at_root: bool) -> Any:
        self._nodes += 1
        if self._nodes > MAX_NODES * 50:
            raise LogicError("evaluation budget exceeded")
        if depth > MAX_DEPTH:
            raise LogicError(f"nested deeper than {MAX_DEPTH}")
        if isinstance(node, list):
            return [self._eval(x, data, depth + 1, at_root) for x in node]
        if not isinstance(node, dict):
            return node
        op, args = _args(node)
        handler = self._HANDLERS.get(op)
        if handler is None:
            raise LogicError(f"unknown operator {op!r}")
        return handler(self, args, data, depth + 1, at_root)

    def _e(self, node: Any, data: Any, depth: int, at_root: bool) -> Any:
        return self._eval(node, data, depth, at_root)

    def _var(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        if not args:
            return data
        path = self._e(args[0], data, depth, at_root)
        default = self._e(args[1], data, depth, at_root) if len(args) > 1 else UNKNOWN
        if path is UNKNOWN or path is None:
            return UNKNOWN
        path = str(path)
        if path.startswith("^"):
            path, scope, root_read = path[1:].lstrip("."), self.root, True
        else:
            scope, root_read = data, at_root
        value = _lookup(scope, path)
        if value is UNKNOWN:
            value = default
        if root_read and path:
            self.used[path] = _summarise(value)
        return value

    def _missing(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        keys = args[0] if len(args) == 1 and isinstance(args[0], list) else args
        out = []
        for k in keys:
            path = self._e(k, data, depth, at_root)
            if _lookup(data, str(path)) is UNKNOWN:
                out.append(path)
        return out

    def _missing_some(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        need = _num(self._e(args[0], data, depth, at_root))
        keys = self._e(args[1], data, depth, at_root)
        if need is UNKNOWN or not isinstance(keys, list):
            return UNKNOWN
        missing = [k for k in keys if _lookup(data, str(k)) is UNKNOWN]
        return [] if len(keys) - len(missing) >= need else missing

    def _and(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        values: list[Truth] = []
        for a in args:
            v = truth(self._e(a, data, depth, at_root))
            if v is False:
                return False
            values.append(v)
        return _kleene_and(values)

    def _or(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        values: list[Truth] = []
        for a in args:
            v = truth(self._e(a, data, depth, at_root))
            if v is True:
                return True
            values.append(v)
        return _kleene_or(values)

    def _not(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return _kleene_not(truth(self._e(args[0], data, depth, at_root)))

    def _notnot(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return truth(self._e(args[0], data, depth, at_root))

    def _if(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        i = 0
        while i + 1 < len(args):
            cond = truth(self._e(args[i], data, depth, at_root))
            if cond is UNKNOWN:
                return UNKNOWN
            if cond:
                return self._e(args[i + 1], data, depth, at_root)
            i += 2
        return self._e(args[i], data, depth, at_root) if i < len(args) else None

    @staticmethod
    def _equal(a: Any, b: Any) -> Truth:
        if a is UNKNOWN or b is UNKNOWN:
            return UNKNOWN
        na, nb = _num(a), _num(b)
        if (
            na is not UNKNOWN
            and nb is not UNKNOWN
            and not isinstance(a, str | bool)
            and not isinstance(b, str | bool)
        ):
            return math.isclose(na, nb, rel_tol=0.0, abs_tol=1e-9)
        return a == b

    def _eq(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        a, b = (self._e(x, data, depth, at_root) for x in args)
        return self._equal(a, b)

    def _ne(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        a, b = (self._e(x, data, depth, at_root) for x in args)
        return _kleene_not(self._equal(a, b))

    def _compare(
        self, args: list[Any], data: Any, depth: int, at_root: bool, fn: Callable[[Any, Any], bool]
    ) -> Truth:
        values = [self._e(x, data, depth, at_root) for x in args]
        if any(v is UNKNOWN or v is None for v in values):
            return UNKNOWN
        if all(isinstance(v, str) for v in values):
            ordered: list[Any] = values
        else:
            nums = [_num(v) for v in values]
            if any(n is UNKNOWN for n in nums):
                return UNKNOWN
            ordered = nums
        return all(fn(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1))

    def _lt(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return self._compare(args, data, depth, at_root, lambda a, b: a < b)

    def _le(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return self._compare(args, data, depth, at_root, lambda a, b: a <= b)

    def _gt(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return self._compare(args, data, depth, at_root, lambda a, b: a > b)

    def _ge(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        return self._compare(args, data, depth, at_root, lambda a, b: a >= b)

    def _in(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        needle, hay = (self._e(x, data, depth, at_root) for x in args)
        if needle is UNKNOWN or hay is UNKNOWN or needle is None:
            return UNKNOWN
        if isinstance(hay, str):
            return isinstance(needle, str) and needle in hay
        if isinstance(hay, list | tuple):
            return any(self._equal(needle, h) is True for h in hay)
        return UNKNOWN

    # arrays ----------------------------------------------------------------------------------------
    def _array(self, node: Any, data: Any, depth: int, at_root: bool) -> list[Any] | _UnknownType:
        arr = self._e(node, data, depth, at_root)
        if arr is UNKNOWN or arr is None:
            return UNKNOWN
        if not isinstance(arr, list | tuple):
            return UNKNOWN
        if len(arr) > MAX_ITEMS:
            raise LogicError(f"array longer than {MAX_ITEMS} items")
        return list(arr)

    def _each(
        self, args: list[Any], data: Any, depth: int, at_root: bool
    ) -> tuple[list[Any], list[Truth]] | _UnknownType:
        arr = self._array(args[0], data, depth, at_root)
        if arr is UNKNOWN:
            return UNKNOWN
        return arr, [truth(self._e(args[1], item, depth, False)) for item in arr]

    def _some(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        res = self._each(args, data, depth, at_root)
        return UNKNOWN if res is UNKNOWN else _kleene_or(res[1])

    def _all(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        res = self._each(args, data, depth, at_root)
        if res is UNKNOWN:
            return UNKNOWN
        return False if not res[0] else _kleene_and(res[1])

    def _none(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Truth:
        res = self._each(args, data, depth, at_root)
        return UNKNOWN if res is UNKNOWN else _kleene_not(_kleene_or(res[1]))

    def _filter(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        res = self._each(args, data, depth, at_root)
        if res is UNKNOWN:
            return UNKNOWN
        items, flags = res
        if any(f is UNKNOWN for f in flags):
            return UNKNOWN
        return [x for x, f in zip(items, flags, strict=True) if f]

    def _map(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        arr = self._array(args[0], data, depth, at_root)
        if arr is UNKNOWN:
            return UNKNOWN
        return [self._e(args[1], item, depth, False) for item in arr]

    def _count(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        if len(args) == 1:
            arr = self._array(args[0], data, depth, at_root)
            return UNKNOWN if arr is UNKNOWN else len(arr)
        res = self._each(args, data, depth, at_root)
        if res is UNKNOWN or any(f is UNKNOWN for f in res[1]):
            return UNKNOWN
        return sum(1 for f in res[1] if f)

    def _sum(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        arr = self._array(args[0], data, depth, at_root)
        if arr is UNKNOWN:
            return UNKNOWN
        values = arr if len(args) == 1 else [self._e(args[1], item, depth, False) for item in arr]
        total = 0.0
        for v in values:
            n = _num(v)
            if n is UNKNOWN:
                return UNKNOWN
            total += n
        return total

    def _merge(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        out: list[Any] = []
        for a in args:
            v = self._e(a, data, depth, at_root)
            if v is UNKNOWN or v is None:
                continue
            if isinstance(v, list | tuple):
                out.extend(v)
            else:
                out.append(v)
        return out

    # arithmetic ------------------------------------------------------------------------------------
    def _nums(self, args: list[Any], data: Any, depth: int, at_root: bool) -> list[float] | _UnknownType:
        out: list[float] = []
        for a in args:
            n = _num(self._e(a, data, depth, at_root))
            if n is UNKNOWN:
                return UNKNOWN
            out.append(n)
        return out

    def _add(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        return UNKNOWN if nums is UNKNOWN else math.fsum(nums)

    def _sub(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        if nums is UNKNOWN:
            return UNKNOWN
        return -nums[0] if len(nums) == 1 else nums[0] - nums[1]

    def _mul(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        return UNKNOWN if nums is UNKNOWN else math.prod(nums)

    def _div(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        if nums is UNKNOWN or nums[1] == 0:
            return UNKNOWN
        return nums[0] / nums[1]

    def _min(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        return UNKNOWN if nums is UNKNOWN else min(nums)

    def _max(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        return UNKNOWN if nums is UNKNOWN else max(nums)

    def _abs(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        return UNKNOWN if nums is UNKNOWN else abs(nums[0])

    def _round(self, args: list[Any], data: Any, depth: int, at_root: bool) -> Any:
        nums = self._nums(args, data, depth, at_root)
        if nums is UNKNOWN:
            return UNKNOWN
        return round(nums[0], int(nums[1]) if len(nums) > 1 else 0)

    _HANDLERS: Final[dict[str, Callable[..., Any]]] = {
        "var": _var,
        "missing": _missing,
        "missing_some": _missing_some,
        "and": _and,
        "or": _or,
        "!": _not,
        "!!": _notnot,
        "if": _if,
        "==": _eq,
        "!=": _ne,
        "<": _lt,
        "<=": _le,
        ">": _gt,
        ">=": _ge,
        "in": _in,
        "some": _some,
        "all": _all,
        "none": _none,
        "filter": _filter,
        "map": _map,
        "count": _count,
        "sum": _sum,
        "merge": _merge,
        "+": _add,
        "-": _sub,
        "*": _mul,
        "/": _div,
        "min": _min,
        "max": _max,
        "abs": _abs,
        "round": _round,
    }


def _summarise(value: Any) -> Any:
    """A compact, JSON-ready copy of a fact for explanations (lists of records are counted)."""
    if value is UNKNOWN:
        return "UNKNOWN"
    if isinstance(value, list | tuple):
        return (
            value
            if len(value) <= 8 and all(not isinstance(v, dict) for v in value)
            else f"<{len(value)} items>"
        )
    if isinstance(value, dict):
        return f"<{len(value)} keys>"
    return value


def evaluate(expr: Any, facts: Mapping[str, Any]) -> Any:
    """One-shot evaluation (value, not truth)."""
    return Evaluator(facts).evaluate(expr)


if set(Evaluator._HANDLERS) != OPERATORS:  # every whitelisted operator has exactly one handler
    raise RuntimeError("IAI-Logic operator table and handlers disagree")
