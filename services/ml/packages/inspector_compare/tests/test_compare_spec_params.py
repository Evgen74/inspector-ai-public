"""Engineering-system parameters through specification items: breaker ratings (IOS1-068), pumps (IOS2-073), heating
pipe diameters (IOS4-076), radiators (IOS4-077), fire alarm composition (IOS5-080)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from inspector_common.contracts.loader import validation_errors
from inspector_common.contracts.models import ExtractedValue
from inspector_compare.engine import compare_object
from inspector_compare.specparams import parse_item, spec_param_diffs

FILES = {"PD": "F9011", "RD": "F9012"}


def _item(syn: Any, stage: str, pos: str | None, name: str, *, qty: float = 1, type_mark: str | None = None,
          section: str | None = None, file_id: str | None = None, n: int = 0) -> dict[str, Any]:  # fmt: skip
    fid = file_id or FILES[stage]
    return {
        "value_id": f"s-{stage}-{fid}-{pos}-{n}-{name[:12]}",
        "object_id": syn.OBJ,
        "file_id": fid,
        "file_sha256": syn.sha(int(fid[1:])),
        "stage": stage,
        "page_no": 4 if stage == "PD" else 2,
        "fact_key": "spec.item",
        "value_raw": str(qty),
        "value_norm": {
            "type": "number",
            "value": qty,
            "unit": "шт.",
            "qualifiers": {"position": pos, "name": name, "type_mark": type_mark, "section": section},
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


def _diffs(vals: list[dict[str, Any]], marks: tuple[str, ...]) -> list[Any]:
    return spec_param_diffs(_m(vals), _files(marks))


# ── IOS1-068 ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_breaker_rating_change(syn: Any) -> None:
    pd = _item(syn, "PD", "5", "Автоматический выключатель 3п ВА47-29 3P C25 А 4,5 кА")
    rd = _item(syn, "RD", "5", "Автоматический выключатель 3п ВА47-29 3P C32 А 4,5 кА")
    (d,) = _diffs([pd, rd], ("ЭОМ",))
    assert (d.code, d.outcome, d.axis, d.discrepancy_type) == (
        "IOS1-068",
        "VIOLATION",
        "PD_RD",
        "VALUE_INCREASED",
    )
    assert d.texts == {"pd_value": "Поз. 5: 25 А", "rd_value": "Поз. 5: 32 А"}
    down = _item(syn, "RD", "5", "Автоматический выключатель 3п ВА47-29 3P C16 А 4,5 кА")
    (d2,) = _diffs([pd, down], ("ЭОМ",))
    assert d2.discrepancy_type == "VALUE_DECREASED" and d2.delta_abs == -9


def test_breaker_equal_and_short_circuit_rating_is_not_nominal(syn: Any) -> None:
    pd = _item(syn, "PD", "5", "Автоматический выключатель ВА47-29 1P C16 А 4.5 кА")
    rd = _item(syn, "RD", "5", "Автоматический выключатель ВА47-29 1P C16А 6 кА")
    (d,) = _diffs([pd, rd], ("ЭОМ",))
    assert d.outcome == "EQUAL"


def test_breaker_renumbered_or_ambiguous_or_unpositioned_is_none(syn: Any) -> None:
    pd = [
        _item(syn, "PD", "5", "Автоматический выключатель ВА47-29 1P C16 А"),
        _item(syn, "PD", "6", "Автоматический выключатель ВА47-29 1P C25 А"),
    ]
    swapped = [
        _item(syn, "RD", "5", "Автоматический выключатель ВА47-29 1P C25 А"),
        _item(syn, "RD", "6", "Автоматический выключатель ВА47-29 1P C16 А"),
    ]
    assert [d for d in _diffs([*pd, *swapped], ("ЭОМ",)) if d.outcome == "VIOLATION"] == []
    twice = [
        _item(syn, "RD", "5", "Автоматический выключатель ВА47-29 1P C10 А", n=1),
        _item(syn, "RD", "5", "Автоматический выключатель ВА47-29 1P C20 А", n=2),
    ]
    assert [d for d in _diffs([pd[0], *twice], ("ЭОМ",)) if d.outcome == "VIOLATION"] == []
    nopos = [
        _item(syn, "PD", None, "Автоматический выключатель ВА47-29 1P C16 А"),
        _item(syn, "RD", None, "Автоматический выключатель ВА47-29 1P C25 А"),
    ]
    assert _diffs(nopos, ("ЭОМ",)) == []


def test_breaker_element_mismatch_and_grammar(syn: Any) -> None:
    pd = _item(syn, "PD", "5", "Автоматический выключатель 1п ВА47-29 C16 А")
    rd = _item(
        syn, "RD", "5", "Автоматический выключатель 3п ВА47-29 C25 А"
    )  # another pole count = another element
    assert [d for d in _diffs([pd, rd], ("ЭОМ",)) if d.outcome == "VIOLATION"] == []
    sock = _m([_item(syn, "PD", "1", "Блок на 3 розетки с автоматическим выключателем на 6 А")])[0]
    assert parse_item(sock, ("ЭОМ",)) == []
    rng = _m([_item(syn, "PD", "1", "Автоматический выключатель с тепловой защитой 0,63-1,0А 3п АПД-32")])[0]
    assert parse_item(rng, ("ЭОМ",)) == []
    assert parse_item(sock, ("АР",)) == []


# ── IOS2-073 ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_pump_decrease(syn: Any) -> None:
    pd = _item(
        syn,
        "PD",
        "2.2.",
        "Насос циркуляционный системы отопления G=15,6 м³/ч, Н=11 м.в.ст., N=1,1 кВт TOP-S 50/15",
    )
    rd = _item(
        syn,
        "RD",
        "2.2.",
        "Насос циркуляционный системы отопления G=15,6 м³/ч, Н=8 м.в.ст., N=1,1 кВт TOP-S 50/15",
    )
    (d,) = _diffs([pd, rd], ("ВК",))
    assert (d.code, d.outcome, d.discrepancy_type) == ("IOS2-073", "VIOLATION", "VALUE_DECREASED")
    assert d.texts == {"pd_value": "H=11 м", "rd_value": "H=8 м"}


def test_pump_increase_equal_and_ocr_power_letter(syn: Any) -> None:
    pd = _item(syn, "PD", "1", "Дренажный насос ГНоМ подачей 10.0 м3/ч, мощностью 0,55 кВт")
    up = _item(syn, "RD", "1", "Дренажный насос ГНоМ подачей 12.0 м3/ч, мощностью 0,55 кВт")
    (d,) = _diffs([pd, up], ("ВК",))
    assert d.outcome == "EQUAL"  # an increase is not a violation
    ocr = _item(syn, "PD", "3", "Насос для удаления, №=1,5 кВт НМС 605")
    ocr_rd = _item(syn, "RD", "3", "Насос для удаления, N=1,1 кВт НМС 605")
    (d2,) = _diffs([ocr, ocr_rd], ("ВК",))
    assert d2.outcome == "VIOLATION" and d2.texts["rd_value"] == "N=1,1 кВт"


def test_pump_without_parameters_or_position_is_none(syn: Any) -> None:
    pd = _item(syn, "PD", "1", "Насос погружной CNP 50 WQ 12 - 15 - 1.5 W")
    rd = _item(syn, "RD", "1", "Насос погружной CNP 50 WQ 12 - 15 - 1.1 W")
    assert _diffs([pd, rd], ("ВК",)) == []
    cond = _m([_item(syn, "PD", "1", "Насос для удаления конденсата, N=0,016 кВт, Q=14,0 л/ч")])[0]
    assert parse_item(cond, ("ВК",)) == []
    lid = _m([_item(syn, "PD", "1", "Металлическая крышка насосной станции размером 1,7 х 1,7 м")])[0]
    assert parse_item(lid, ("ВК",)) == []
    a = _item(syn, "PD", None, "Насос циркуляционный G=3,2 м³/ч")
    b = _item(syn, "RD", None, "Насос циркуляционный G=2,0 м³/ч")
    assert _diffs([a, b], ("ВК",)) == []


# ── IOS4-076 ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_heating_pipe_diameter_change(syn: Any) -> None:
    pd = _item(
        syn, "PD", "4", "Труба стальная водогазопроводная Ду 50 ГОСТ 3262", section="Отопление Т1", qty=120
    )
    rd = _item(
        syn, "RD", "4", "Труба стальная водогазопроводная Ду 40 ГОСТ 3262", section="Отопление Т1", qty=120
    )
    (d,) = _diffs([pd, rd], ("ОВ",))
    assert (d.code, d.outcome, d.discrepancy_type) == ("IOS4-076", "VIOLATION", "VALUE_DECREASED")
    assert d.texts == {"pd_value": "Ду 50", "rd_value": "Ду 40"}
    bigger = _item(syn, "RD", "4", "Труба стальная водогазопроводная Ду 65 ГОСТ 3262", section="Отопление Т1")
    (d2,) = _diffs([pd, bigger], ("ОВ",))
    assert d2.discrepancy_type == "VALUE_INCREASED"  # «изменение диаметров» is a change in any direction


def test_heating_pipe_other_system_or_other_discipline_is_none(syn: Any) -> None:
    pd = _item(syn, "PD", "4", "Труба стальная Ду 50", section="Отопление Т1")
    rd = _item(syn, "RD", "4", "Труба стальная Ду 40", section="Отопление Т2")  # another system
    assert [d for d in _diffs([pd, rd], ("ОВ",)) if d.outcome == "VIOLATION"] == []
    water_pd = _item(syn, "PD", "4", "Труба стальная Ду 50", section="Водопровод В1")
    water_rd = _item(syn, "RD", "4", "Труба стальная Ду 40", section="Водопровод В1")
    assert _diffs([water_pd, water_rd], ("ОВ",)) == []
    assert [
        d
        for d in _diffs([pd, _item(syn, "RD", "4", "Труба стальная Ду 40", section="Отопление Т1")], ("ЭОМ",))
    ] == []


# ── IOS4-077 ────────────────────────────────────────────────────────────────────────────────────────────────────

RAD = 'Стальной панельный радиатор "PRADO Classic" в комплекте с пробками, 33-500-800'


def test_radiator_power_and_count(syn: Any) -> None:
    pd = _item(syn, "PD", None, RAD + ", 1200 Вт", qty=6, type_mark="PRADO Classic")
    rd = _item(syn, "RD", None, RAD + ", 900 Вт", qty=6, type_mark="PRADO Classic")
    (d,) = _diffs([pd, rd], ("ОВ",))
    assert (d.code, d.sub_id, d.outcome, d.unit) == ("IOS4-077", "IOS4-077.b", "VIOLATION", "Вт")
    assert d.texts == {"pd_value": "1200 Вт", "rd_value": "900 Вт"}
    pd2 = _item(syn, "PD", None, RAD, qty=44, type_mark="PRADO Classic")
    rd2 = _item(syn, "RD", None, RAD, qty=40, type_mark="PRADO Classic")
    (d2,) = _diffs([pd2, rd2], ("ОВ",))
    assert (d2.sub_id, d2.outcome) == ("IOS4-077.a", "VIOLATION")
    assert "44" in d2.texts["pd_value"] and "40" in d2.texts["rd_value"]


def test_radiator_other_mark_fittings_and_split_files_are_none(syn: Any) -> None:
    pd = _item(syn, "PD", None, RAD, qty=6, type_mark="PRADO Classic")
    other = _item(syn, "RD", None, RAD.replace("33-500-800", "22-500-800"), qty=1, type_mark="PRADO Classic")
    assert _diffs([pd, other], ("ОВ",)) == []
    valve = _m([_item(syn, "PD", None, "Клапан запорный радиаторный прямой Ду15", qty=69)])[0]
    assert parse_item(valve, ("ОВ",)) == []
    a = _item(syn, "RD", None, RAD, qty=3, type_mark="PRADO Classic")
    b = _item(syn, "RD", None, RAD, qty=1, type_mark="PRADO Classic", file_id="F9013")
    files = {**_files(("ОВ",)), "F9013": SimpleNamespace(marks=("ОВ",))}
    out = spec_param_diffs(_m([pd, a, b]), files)
    assert [d for d in out if d.outcome == "VIOLATION"] == []  # two RD files print the mark: ambiguous
    # increase is not a violation
    up = _item(syn, "RD", None, RAD, qty=9, type_mark="PRADO Classic")
    assert [d.outcome for d in _diffs([pd, up], ("ОВ",))] == ["EQUAL"]


# ── IOS5-080 ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_aps_detector_count(syn: Any) -> None:
    pd = _item(
        syn,
        "PD",
        None,
        "Извещатель пожарный дымовой адресный ДИП-34А-03",
        qty=337,
        section="Основное оборудование АПС",
    )
    rd = _item(
        syn,
        "RD",
        None,
        "Извещатель пожарный дымовой адресный ДИП-34А-03",
        qty=300,
        section="Основное оборудование АПС",
    )
    (d,) = _diffs([pd, rd], ("СС",))
    assert (d.code, d.sub_id, d.outcome, d.discrepancy_type) == (
        "IOS5-080",
        "IOS5-080.a",
        "VIOLATION",
        "VALUE_DECREASED",
    )
    assert "337" in d.texts["pd_value"] and "300" in d.texts["rd_value"]


def test_aps_other_type_security_and_increase_are_none(syn: Any) -> None:
    pd = _item(syn, "PD", None, "Извещатель пожарный дымовой адресный ДИП-34А-03", qty=337)
    other = _item(syn, "RD", None, "Извещатель пожарный тепловой адресный С2000-ИП-03", qty=3)
    assert _diffs([pd, other], ("СС",)) == []  # a set difference without a shared mark is not a finding
    sec = _m([_item(syn, "PD", None, "Извещатель охранный магнитоконтактный ИО102-20", qty=383)])[0]
    assert parse_item(sec, ("СС",)) == []
    kozh = _m([_item(syn, "PD", None, "Защитный сетчатый кожух для ручных пожарных извещателей", qty=3)])[0]
    assert parse_item(kozh, ("СС",)) == []
    more = _item(syn, "RD", None, "Извещатель пожарный дымовой адресный ДИП-34А-03", qty=400)
    assert [d.outcome for d in _diffs([pd, more], ("СС",))] == ["EQUAL"]
    assert _diffs([pd, more], ("АР",)) == []


def test_engine_emits_pump_and_breaker_findings(tmp_path: Any, cfg: Any, syn: Any) -> None:
    rows = [
        syn.manifest_row("F9011", "PD", "EOM", "syn/ПД/5.1 ИОС1/Том 5.1 Электроснабжение.pdf", 20),
        syn.manifest_row("F9012", "RD", "EOM", "syn/РД/SYN-РД-ЭОМ1.pdf", 20),
    ]
    values = [
        _item(syn, "PD", "5", "Автоматический выключатель 3п ВА47-29 3P C25 А"),
        _item(syn, "RD", "5", "Автоматический выключатель 3п ВА47-29 3P C32 А"),
    ]
    result = compare_object(syn.make_context(tmp_path, [], rows=rows, values=values), cfg)
    viol = [f for f in result.findings if f["violation_label"] == "VIOLATION_PRESENT"]
    assert [(f["parameter_code"], f["location"]) for f in viol] == [("IOS1-068", "OBJECT")]
    assert (viol[0]["pd_value"], viol[0]["rd_value"]) == ("Поз. 5: 25 А", "Поз. 5: 32 А")
    assert {(e["stage"], e["file_id"]) for e in viol[0]["evidence"]} == {("PD", "F9011"), ("RD", "F9012")}
    for doc in result.findings:
        assert not validation_errors("finding", doc)
