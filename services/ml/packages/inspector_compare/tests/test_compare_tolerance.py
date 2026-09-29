"""ИД-internal TOLERANCE_CHECK (axis NORM_ID) on ИГС facts: the pilot OKT103 pattern fires KR-054 with both
anchors on the one ИД page; schemes within tolerance verify the code; the code follows the scheme."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_compare.engine import compare_object
from inspector_compare.tolerance import fires, page_verdicts, route, tolerance_diffs


def _v(syn: Any, key: str, value: float, *, page: int = 5, file_id: str = "F9003", kind: str | None = None,
       element: str | None = "COLUMN", conf: float = 0.9, n: int = 0) -> dict[str, Any]:  # fmt: skip
    raw = f"{value:+g}" if key == "id.deviation" else f"{value:g} мм"
    return {
        "value_id": f"t-{key}-{file_id}-{page}-{n}-{value}",
        "object_id": syn.OBJ,
        "file_id": file_id,
        "file_sha256": syn.sha(int(file_id[1:])),
        "stage": "ID",
        "page_no": page,
        "fact_key": key,
        "location": "OBJECT",
        "location_type": "OBJECT",
        "value_raw": raw,
        "value_norm": {
            "type": "number",
            "value": value,
            "unit": "мм",
            "qualifiers": {"source": "IGS_ANNOTATION", "element_kind": element, "kind": kind},
        },
        "method": "REGEX",
        "confidence": conf,
        "quality_flag": "OK",
        "pipeline_version": "test",
        "geometry": {"boxes": [[0.1, 0.1 + n / 100, 0.2, 0.12 + n / 100]]},
        "geometry_space": "PDF_VISIBLE_ROTATED_TL_V1",
    }


def _pilot(syn: Any, page: int = 5, file_id: str = "F9003") -> list[dict[str, Any]]:
    tols = [_v(syn, "id.tolerance", t, page=page, file_id=file_id, n=i) for i, t in enumerate((15, 12, 20))]
    devs = [
        _v(syn, "id.deviation", d, page=page, file_id=file_id, n=10 + i)
        for i, d in enumerate((491, 552, 980, 537, 201, 349))
    ]
    return tols + devs


def _models(vals: list[dict[str, Any]]) -> list[ExtractedValue]:
    return [ExtractedValue.model_validate(v) for v in vals]


def test_route_follows_the_scheme() -> None:
    assert route("COLUMN", {None}) == ("KR-054", "ANY")
    assert route(None, {"PLAN", "ELEVATION"}) == ("KR-054", "ANY")
    assert route("WALL", {"THICKNESS"}) == ("KR-061", "DECREASE")
    assert route("FOUNDATION_SLAB", {"ELEVATION"}) == ("KR-058", "DECREASE")
    assert route("FLOOR_SLAB", {"THICKNESS"}) == ("KR-059", "DECREASE")
    assert route("PILE", {"ELEVATION"})[0] is None  # elevation of piles: no catalog row → abstain


def test_pilot_breach_is_read_at_the_largest_tolerance(syn: Any) -> None:
    diffs, verdicts = tolerance_diffs(_models(_pilot(syn)))
    assert len(verdicts) == 1 and fires(verdicts[0])
    (d,) = diffs
    assert (d.code, d.sub_id, d.axis, d.room, d.outcome) == (
        "KR-054",
        "KR-054.b",
        "NORM_ID",
        "OBJECT",
        "VIOLATION",
    )
    assert d.discrepancy_type == "TOLERANCE_EXCEEDED"
    assert d.expected.value_norm.value == 20 and d.actual.value_norm.value == 980
    assert d.delta_abs == 960


def test_conservative_triggers(syn: Any) -> None:
    # one small breach (21 mm vs 20 mm) among in-tolerance points: an OCR slip is not a finding
    vals = [_v(syn, "id.tolerance", 20), _v(syn, "id.deviation", 5, n=1), _v(syn, "id.deviation", -21, n=2)]
    (v,) = page_verdicts(_models(vals))
    assert v.breaches == 1 and not fires(v)
    diffs, _ = tolerance_diffs(_models(vals))
    assert [d.outcome for d in diffs] == ["EQUAL"]  # verified, not violated
    # a single deviation read → abstain (VALUE_NOT_FOUND)
    (v,) = page_verdicts(_models([_v(syn, "id.tolerance", 10), _v(syn, "id.deviation", 50, n=1)]))
    assert v.reason == "VALUE_NOT_FOUND" and not fires(v)
    # thickness on a wall: only thinner (negative) deviations count
    vals = [
        _v(syn, "id.tolerance", 5, kind="THICKNESS", element="WALL"),
        _v(syn, "id.deviation", 30, n=1, element="WALL"),
        _v(syn, "id.deviation", 40, n=2, element="WALL"),
    ]
    (v,) = page_verdicts(_models(vals))
    assert v.code == "KR-061" and not fires(v)
    vals[1]["value_norm"]["value"] = -30
    vals[2]["value_norm"]["value"] = -12
    (v,) = page_verdicts(_models(vals))
    assert v.code == "KR-061" and fires(v)
    # no tolerance on the page → nothing at all
    assert (
        page_verdicts(_models([_v(syn, "id.deviation", 500, n=1), _v(syn, "id.deviation", 600, n=2)])) == []
    )


def test_engine_emits_kr054_on_the_id_page(tmp_path: Path, cfg: Any, syn: Any) -> None:
    values = [
        *_pilot(syn, page=5),
        # a second scheme within tolerance: verified, no second finding
        _v(syn, "id.tolerance", 10, page=6, n=1),
        _v(syn, "id.deviation", 4, page=6, n=2),
        _v(syn, "id.deviation", -7, page=6, n=3),
    ]
    result = compare_object(syn.make_context(tmp_path, [], values=values), cfg)
    kr = [f for f in result.findings if f["parameter_code"] == "KR-054"]
    assert len(kr) == 1
    f = kr[0]
    assert f["violation_label"] == "VIOLATION_PRESENT" and f["location"] == "OBJECT"
    assert f["axis"] == "NORM_ID" and f["discrepancy_type"] == "TOLERANCE_EXCEEDED"
    assert f["comparison_result"] == "TOLERANCE_EXCEEDED"
    assert f["protocol_status"] == "CRITICAL" and f["criticality"].startswith("Критическое")
    assert (f["pd_value"], f["rd_value"]) == (None, None)
    assert f["id_value"] == "+980 мм при допуске 20 мм"
    assert {(e["stage"], e["file_id"], e["pdf_page_number"], e["role"]) for e in f["evidence"]} == {
        ("ID", "F9003", 5, "ACTUAL")
    }
    assert len(f["evidence"][0]["geometry"]["boxes"]) == 2  # the tolerance note and the worst deviation
    g = next(g for g in result.groups if g["parameter_code"] == "KR-054")
    assert "допуске 20 мм" in g["title"] and g["rule_code"] == "KR-054.b"
    for doc in result.groups:
        assert not validation_errors("finding_group", doc)
    for doc in result.findings:
        assert not validation_errors("finding", doc)
