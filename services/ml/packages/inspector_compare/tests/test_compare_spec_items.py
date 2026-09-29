"""ЭОМ/ВК specification items PD↔RD: a cable cross-section or pipe diameter decrease at the same position and
product stem, only when the PD size disappears from the RD specification (IOS1-069, IOS2-071, IOS3-074)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_compare.engine import compare_object
from inspector_compare.specitems import parse_item, spec_diffs

FILES = {"PD": "F9011", "RD": "F9012"}


def _item(syn: Any, stage: str, pos: str, name: str, *, section: str | None = None, n: int = 0,
          file_id: str | None = None) -> dict[str, Any]:  # fmt: skip
    fid = file_id or FILES[stage]
    return {
        "value_id": f"s-{stage}-{fid}-{pos}-{n}-{name[:10]}",
        "object_id": syn.OBJ,
        "file_id": fid,
        "file_sha256": syn.sha(int(fid[1:])),
        "stage": stage,
        "page_no": 4 if stage == "PD" else 2,
        "fact_key": "spec.item",
        "value_raw": "100",
        "value_norm": {
            "type": "number",
            "value": 100,
            "unit": "м",
            "qualifiers": {"position": pos, "name": name, "type_mark": None, "section": section},
        },
        "method": "TABLE",
        "confidence": 1.0,
        "quality_flag": "OK",
        "pipeline_version": "test",
    }


def _files(marks: tuple[str, ...]) -> dict[str, Any]:
    return {fid: SimpleNamespace(marks=marks) for fid in FILES.values()}


def _m(vals: list[dict[str, Any]]) -> list[ExtractedValue]:
    return [ExtractedValue.model_validate(v) for v in vals]


def test_item_grammar(syn: Any) -> None:
    v = _m([_item(syn, "PD", "3", "Кабель силовой, 1кВ ВВГнг(А)-LSLTx (5x10)")])[0]
    it = parse_item(v, ("ЭОМ",))
    assert it is not None and (it.code, it.stem, it.size, it.label) == (
        "IOS1-069",
        "ВВГНГ(А)-LSLTX 5×",
        10.0,
        "5×10 мм²",
    )
    assert parse_item(v, ("ОВ",)) is None  # not the ЭОМ specification
    pairs = _m([_item(syn, "PD", "16", "Кабель управления КПСВВнг(А)-LSLTx 1х2х0.5")])[0]
    assert parse_item(pairs, ("ЭОМ",)) is None  # signal pairs are not power cross-sections
    pipe = _m([_item(syn, "PD", "5", "Труба стальная водогазопроводная Ду 50", section="Водопровод В1")])[0]
    assert parse_item(pipe, ("ВК",)).code == "IOS2-071"
    sewer = _m([_item(syn, "PD", "7", "Труба ПВХ канализационная d110")])[0]
    assert parse_item(sewer, ("ВК",)).code == "IOS3-074"
    heat = _m([_item(syn, "PD", "8", "Труба стальная Ду 50", section="Отопление")])[0]
    assert parse_item(heat, ("ВК",)) is None


def test_decrease_needs_the_pd_size_to_disappear(syn: Any) -> None:
    pd = _item(syn, "PD", "3", "Кабель ВВГнг(А)-LS 5х10")
    rd = _item(syn, "RD", "3", "Кабель ВВГнг(А)-LS 5х6")
    (d,) = spec_diffs(_m([pd, rd]), _files(("ЭОМ",)))
    assert (d.code, d.outcome, d.discrepancy_type, d.room) == (
        "IOS1-069",
        "VIOLATION",
        "VALUE_DECREASED",
        "OBJECT",
    )
    assert d.texts == {"pd_value": "5×10 мм²", "rd_value": "5×6 мм²"}
    # the 5×10 cable is still in RD at another position → renumbering, not a decrease
    moved = _item(syn, "RD", "4", "Кабель ВВГнг(А)-LS 5х10", n=1)
    assert spec_diffs(_m([pd, rd, moved]), _files(("ЭОМ",))) == []
    # an increase or another brand never fires
    assert spec_diffs(_m([pd, _item(syn, "RD", "3", "Кабель ВВГнг(А)-LS 5х16")]), _files(("ЭОМ",))) == []
    assert spec_diffs(_m([pd, _item(syn, "RD", "3", "Кабель АВВГ 5х6")]), _files(("ЭОМ",))) == []
    # another position never fires
    assert spec_diffs(_m([pd, _item(syn, "RD", "9", "Кабель ВВГнг(А)-LS 5х6")]), _files(("ЭОМ",))) == []


def test_engine_emits_pipe_decrease(tmp_path: Path, cfg: Any, syn: Any) -> None:
    rows = [
        syn.manifest_row("F9011", "PD", "VK", "syn/ПД/5.2 ИОС2/Том 5.2 Водоснабжение.pdf", 20),
        syn.manifest_row("F9012", "RD", "VK", "syn/РД/SYN-РД-ВК1.pdf", 20),
    ]
    values = [
        _item(syn, "PD", "5", "Труба стальная водогазопроводная Ду 50", section="Водопровод В1"),
        _item(syn, "RD", "5", "Труба стальная водогазопроводная Ду 40", section="Водопровод В1"),
    ]
    result = compare_object(syn.make_context(tmp_path, [], rows=rows, values=values), cfg)
    viol = [f for f in result.findings if f["violation_label"] == "VIOLATION_PRESENT"]
    assert [(f["parameter_code"], f["location"]) for f in viol] == [("IOS2-071", "OBJECT")]
    f = viol[0]
    assert (f["pd_value"], f["rd_value"]) == ("Ду 50", "Ду 40")
    assert {(e["stage"], e["file_id"], e["pdf_page_number"]) for e in f["evidence"]} == {
        ("PD", "F9011", 4),
        ("RD", "F9012", 2),
    }
    for doc in result.findings:
        assert not validation_errors("finding", doc)
