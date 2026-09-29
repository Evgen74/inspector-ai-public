"""Room-token and tag grammar (AG-02B-2): exact tokens, OCR look-alikes, lists, flows, sizes, gates."""

from __future__ import annotations

import pytest

from inspector_layout.rooms.grammar import (
    LIST_SEP,
    Vocabulary,
    floor_from_room_number,
    floor_from_title,
    is_room_token,
    mark_elements,
    ocr_diameter,
    ocr_flow,
    parse_room_label,
    parse_tags,
)


def norms(line: str, **kw) -> list[tuple[str, str]]:
    return [(t.tag_norm, t.tag_kind) for t in parse_tags(line, **kw)]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("B2.7,8,9", ["В2.7", "В2.8", "В2.9"]),  # OCR Latin «B», a branch list
        ("П17.1, 17.2", ["П17.1", "П17.2"]),
        ("П2.1, П8, П18", ["П2.1", "П8", "П18"]),
        ("B2.3,4", ["В2.3", "В2.4"]),
        ("П2/BЕ", ["П2", "ВЕ"]),
        ("ВЕ13", ["ВЕ13"]),
        ("П1,2", ["П1", "П2"]),
    ],
)
def test_vent_tags_expand_and_fold(line: str, expected: list[str]) -> None:
    got = [n for n, k in norms(line) if k == "VENT_SYSTEM"]
    assert got == expected


def test_vent_tag_is_not_a_quantity_or_a_concrete_class() -> None:
    assert norms("B25 F150 W6") == []  # concrete class, not a vent system
    assert norms("П2 400x200") == [("П2", "VENT_SYSTEM"), ("400×200", "OTHER")]
    assert [k for _, k in norms("ВЕ 400")] == ["VENT_SYSTEM"]  # «ВЕ» then a number, never «ВЕ400»
    assert norms("АНО/150321/1-РД-ОВ1") == []  # a document code


def test_vent_grammar_is_gated() -> None:
    assert norms("В2.4", vent=False) == []
    assert norms("Ст19", heating=False) == []


@pytest.mark.parametrize(
    ("line", "norm", "kind"),
    [
        ("AMH-K 400x150", "АМН-К 400×150", "AIR_TERMINAL"),
        ("PCH-K 500x500", "РСН-К 500×500", "AIR_TERMINAL"),
        ("M.O. поз.160", "М.О. поз.160", "EQUIPMENT"),
        ("Зонт из оц. стали", "Зонт", "EQUIPMENT"),
        ("PRADO Universal 22-500-700", "PRADO Universal 22-500-700", "EQUIPMENT"),
        ("22-500-700", "22-500-700", "EQUIPMENT"),
        ("Cm19", "Ст19", "PIPE_RISER"),
        ("Ст.Т1", "Ст.Т1", "PIPE_RISER"),
        ("T11", "Т11", "HEATING_SYSTEM"),
        ("теплые полы", "тёплый пол", "HEATING_SYSTEM"),
        ("-950 м³/ч", "L=-950", "OTHER"),
        ("L 400", "L=400", "OTHER"),
        ("Ø200", "Ø200", "OTHER"),
        ("±0.000", "±0.000", "LEVEL_MARK"),
        ("700 Bm", "Q=700 Вт", "OTHER"),
    ],
)
def test_marks(line: str, norm: str, kind: str) -> None:
    assert (norm, kind) in norms(line)


def test_ocr_only_forms() -> None:
    assert ocr_diameter("0200") == "Ø200"
    assert ocr_diameter("012") is None  # a room, never a diameter
    assert ocr_flow("950M") == 950.0
    assert ocr_flow("-140M") == -140.0
    assert ocr_flow("140") is None


@pytest.mark.parametrize("token", ["012", "140", "012.1", "258.1", "1001", "1.109", "101а", "2.2.1"])
def test_room_tokens_kept(token: str) -> None:
    assert is_room_token(token)


@pytest.mark.parametrize("token", ["12", "-0.014", "0.150", "+3.900", "П1", "400x150", "1", "12345"])
def test_not_room_tokens(token: str) -> None:
    assert not is_room_token(token)


@pytest.mark.parametrize(
    ("line", "rooms", "name"),
    [
        ("142 Астрономии", ("142",), "Астрономии"),
        ("147 Лаборантская тип АВ", ("147",), "Лаборантская тип АВ"),  # «Л…» is a name, not litres
        ("143 моделирования", ("143",), "моделирования"),  # «м…» is a name, not metres
        ("007 Техническое подполье", ("007",), "Техническое подполье"),
        ("267, 270", ("267", "270"), None),
        ("012", ("012",), None),
    ],
)
def test_room_label_lines(line: str, rooms: tuple, name: str | None) -> None:
    parsed = parse_room_label(line)
    assert parsed is not None and parsed.rooms == rooms and parsed.name == name


@pytest.mark.parametrize(
    "line", ["на 600 мест", "600 мест", "140 мм", "400 x 200", "700 Вт", "L 140", "12 шт."]
)
def test_quantities_are_not_room_labels(line: str) -> None:
    assert parse_room_label(line) is None


def test_floor_from_titles() -> None:
    assert floor_from_title("План 1-го этажа (вентиляция)") == "1"
    assert floor_from_title("План подвала") == "подвал"
    assert floor_from_title("Экспликация помещений 2 этажа") == "2"
    assert floor_from_title("План -3-го этажа. М 1:200") == "-3"
    assert floor_from_title("Спецификация оборудования") is None


def test_vocabulary_repairs_one_slip_only_when_known() -> None:
    v = Vocabulary({"В2.2", "В2.1", "П9"})
    assert v.repair("B22") == "В2.2"
    assert v.repair("82.1") == "В2.1"
    assert v.repair("B2.2") is None  # already a known tag
    assert Vocabulary({"В2.2", "В22.0"}).repair("В33") is None


def test_weak_heads_need_evidence() -> None:
    """«32.1» (outlined «В2.1») and «119» («П9») are numbers too: repaired only when the caller has evidence."""
    v = Vocabulary({"В2.1", "П9", "П17.1"})
    assert v.repair("32.1") is None and v.repair("119") is None
    assert v.repair("32.1", weak_heads=True) == "В2.1"
    assert v.repair("119", weak_heads=True) == "П9"
    assert v.repair("11171", weak_heads=True) == "П17.1"  # «11» + lost dot
    assert v.repair("32.5", weak_heads=True) is None  # «В2.5» unknown: an area stays an area
    assert v.repair("11", weak_heads=True) is None  # the head alone is no mark


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("T11", ["Т11"]),
        ("T11 T21", ["Т11", "Т21"]),  # supply and return side by side on one visual line
        ("T11T21", ["Т11", "Т21"]),  # glued by OCR
        ("Т11=+85 °С", ["Т11"]),
        ("-T21-", ["Т21"]),  # cut by the pipe drawn through the label
        ("ø16х2,2 Т11", ["Т11"]),
        ("СТ11", []),
        ("КТ12", []),
        ("1.Т11", []),
    ],
)
def test_pipelines_anywhere_in_a_line(line: str, expected: list[str]) -> None:
    assert [n for n, k in norms(line) if k == "HEATING_SYSTEM"] == expected


def test_pipelines_need_the_heating_context() -> None:
    assert norms("T11", heating=False) == []


def test_supply_exhaust_pair_head() -> None:
    """«12/BE» is «П2/ВЕ» (outlined «П» read as «1»); a bare «12» is not."""
    assert [n for n, k in norms("12/BE") if k == "VENT_SYSTEM"] == ["П2", "ВЕ"]
    assert [n for n, k in norms("N2/BE -150 м³/ч") if k == "VENT_SYSTEM"] == ["П2", "ВЕ"]
    assert [n for n, k in norms("12 BE") if k == "VENT_SYSTEM"] == ["ВЕ"]
    assert [n for n, k in norms("12/ВЕ13") if k == "VENT_SYSTEM"] == ["ВЕ13"]
    # the print is «П2/ВЕ»: the repaired reading is what a consumer of ``tag`` sees
    assert [(t.tag, t.tag_norm) for t in parse_tags("12/BE")] == [("П2", "П2"), ("BE", "ВЕ")]


def test_mark_elements_of_a_printed_list() -> None:
    assert mark_elements(LIST_SEP.join(["В2.7", "В2.8", "В2.9"]), "VENT_SYSTEM") == ["В2.7", "В2.8", "В2.9"]
    assert mark_elements("PRADO Universal 22-500-700", "EQUIPMENT") == ["PRADO Universal 22-500-700"]
    assert mark_elements(None, "VENT_SYSTEM") == []


@pytest.mark.parametrize(
    ("token", "floor"),
    [
        ("012", "0"),
        ("012.1", "0"),
        ("142", "1"),
        ("331б", "3"),
        ("1.109", "1"),
        ("2.05", "2"),
        ("1001", None),
    ],
)
def test_floor_from_room_number(token: str, floor: str | None) -> None:
    assert floor_from_room_number(token) == floor


def test_repair_confusables_closed_vocabulary():
    v = Vocabulary({"В10.3", "В6.3", "П10"})
    assert v.repair_confusables("П10/B1Q.3") == "П10/В10.3"
    assert v.repair_confusables("R6.3") == "В6.3"
    assert v.repair_confusables("R66") == "R66"  # not a mark of the vocabulary
    assert v.repair_confusables("В10.3") == "В10.3"
    assert Vocabulary().repair_confusables("R6.3") == "R6.3"
