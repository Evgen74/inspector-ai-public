"""IAI-Logic v1: Kleene three-valued semantics, operators, scoping, safety (AT-HYP-11)."""

from __future__ import annotations

import itertools

import pytest

from inspector_hypothesis.logic import (
    OPERATORS,
    UNKNOWN,
    Evaluator,
    LogicError,
    evaluate,
    truth,
    validate_expression,
)

TV = [True, False, UNKNOWN]


def _lit(v):
    return {"var": "u"} if v is UNKNOWN else v


@pytest.mark.parametrize(("a", "b"), list(itertools.product(TV, TV)))
def test_kleene_and_or_truth_tables(a, b):
    facts = {}  # «u» is missing → UNKNOWN
    got_and = Evaluator(facts).truth({"and": [_lit(a), _lit(b)]})
    got_or = Evaluator(facts).truth({"or": [_lit(a), _lit(b)]})
    exp_and = False if False in (a, b) else (UNKNOWN if UNKNOWN in (a, b) else True)
    exp_or = True if True in (a, b) else (UNKNOWN if UNKNOWN in (a, b) else False)
    assert got_and is exp_and
    assert got_or is exp_or


@pytest.mark.parametrize(("a", "expected"), [(True, False), (False, True), (UNKNOWN, UNKNOWN)])
def test_kleene_not(a, expected):
    assert Evaluator({}).truth({"!": _lit(a)}) is expected


def test_unknown_has_no_python_truth_value():
    with pytest.raises(TypeError):
        bool(UNKNOWN)


def test_missing_fact_makes_comparisons_and_arithmetic_unknown():
    f = {"a": 3, "n": None}
    assert Evaluator(f).truth({">": [{"var": "a"}, 2]}) is True
    assert Evaluator(f).truth({">": [{"var": "missing"}, 2]}) is UNKNOWN
    assert Evaluator(f).truth({">": [{"var": "n"}, 2]}) is UNKNOWN  # None is not a value
    assert evaluate({"+": [{"var": "a"}, {"var": "missing"}]}, f) is UNKNOWN
    assert evaluate({"/": [1, 0]}, f) is UNKNOWN
    assert evaluate({"var": ["missing", 7]}, f) == 7  # default


def test_between_and_string_comparison():
    assert Evaluator({"x": 3.1}).truth({"<=": [2.4, {"var": "x"}, 6.0]}) is True
    assert Evaluator({"x": 7}).truth({"<=": [2.4, {"var": "x"}, 6.0]}) is False
    assert (
        Evaluator({"d1": "2025-04-07", "d2": "2024-08-11"}).truth({">=": [{"var": "d1"}, {"var": "d2"}]})
        is True
    )
    assert Evaluator({"s": "abc"}).truth({"<": [{"var": "s"}, 3]}) is UNKNOWN  # type mismatch is not FALSE


def test_equality_is_numeric_for_numbers_and_strict_for_strings():
    assert Evaluator({}).truth({"==": [1, 1.0]}) is True
    assert Evaluator({}).truth({"==": ["012", "12"]}) is False  # room tokens keep leading zeros
    assert Evaluator({}).truth({"!=": [{"var": "m"}, 1]}) is UNKNOWN


def test_array_operators_are_strict_about_unknown():
    rows = [{"k": "DATA", "a": 1.5}, {"k": "DATA", "a": 2.25}, {"k": "SUB", "a": 9}]
    f = {"rows": rows, "bad": [{"a": 1}, {"a": None}], "empty": []}
    ev = Evaluator(f)
    data_rows = {"filter": [{"var": "rows"}, {"==": [{"var": "k"}, "DATA"]}]}
    assert ev.evaluate({"sum": [data_rows, {"var": "a"}]}) == pytest.approx(3.75)
    assert ev.evaluate({"count": [{"var": "rows"}, {">": [{"var": "a"}, 2]}]}) == 2
    assert ev.evaluate({"sum": [{"var": "bad"}, {"var": "a"}]}) is UNKNOWN
    assert ev.truth({"some": [{"var": "bad"}, {">": [{"var": "a"}, 0]}]}) is True  # one TRUE decides
    assert ev.truth({"all": [{"var": "bad"}, {">": [{"var": "a"}, 0]}]}) is UNKNOWN
    assert ev.truth({"all": [{"var": "empty"}, True]}) is False  # JSONLogic parity
    assert ev.truth({"none": [{"var": "empty"}, True]}) is True
    assert ev.truth({"some": [{"var": "nope"}, True]}) is UNKNOWN
    assert ev.evaluate({"merge": [{"var": "rows.0.k"}, {"var": "nope"}, ["x"]]}) == ["DATA", "x"]


def test_root_scope_inside_iteration_and_trace_of_used_facts():
    f = {"codes": ["A", "B"], "refs": ["A", "C"]}
    ev = Evaluator(f)
    expr = {"all": [{"var": "refs"}, {"in": [{"var": ""}, {"var": "^codes"}]}]}
    assert ev.truth(expr) is False
    assert "refs" in ev.used and "codes" in ev.used


def test_if_and_in():
    ev = Evaluator({"x": 5, "s": "Отопление"})
    assert ev.evaluate({"if": [{">": [{"var": "x"}, 3]}, "big", "small"]}) == "big"
    assert ev.evaluate({"if": [{"var": "nope"}, 1, 2]}) is UNKNOWN
    assert ev.truth({"in": ["топл", {"var": "s"}]}) is True
    assert ev.truth({"in": [2, [1, 2, 3]]}) is True


def test_truthiness():
    assert truth(0) is False and truth("") is False and truth([]) is False
    assert truth(1) is True and truth("a") is True
    assert truth(None) is UNKNOWN


def test_validation_rejects_unknown_operators_arity_and_depth():
    assert validate_expression({"and": [True, {"var": "a"}]}) == []
    assert any("unknown operator" in p for p in validate_expression({"eval": ["os.system('x')"]}))
    assert any("takes" in p for p in validate_expression({"!": [1, 2]}))
    deep: object = True
    for _ in range(60):
        deep = {"!": deep}
    assert any("deeper" in p for p in validate_expression(deep))
    with pytest.raises(LogicError):
        Evaluator({}).evaluate({"nope": [1]})


def test_operator_whitelist_is_the_documented_subset():
    assert {
        "var",
        "and",
        "or",
        "!",
        "==",
        "<=",
        "some",
        "all",
        "sum",
        "count",
        "missing",
        "merge",
        "abs",
    } <= OPERATORS
    assert "eval" not in OPERATORS and "method" not in OPERATORS
