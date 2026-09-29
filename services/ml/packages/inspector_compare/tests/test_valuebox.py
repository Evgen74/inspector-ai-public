"""Locating an extracted value's words on a page (valuebox) and attaching the box to protocol card sources."""

from __future__ import annotations

import gzip
import json
from types import SimpleNamespace

from inspector_compare.protocol.builder import ProtocolBuilder
from inspector_compare.valuebox import ValueLocator, locate_value, normalize


def _tok(i: int, text: str, x0: float, y0: float = 0.2, line: int = 1) -> dict:
    return {"id": i, "text": text, "bbox": [x0, y0, x0 + 0.05, y0 + 0.02], "line_id": line}


def _page(words: list[str], y0: float = 0.2, line: int = 1, start: int = 0) -> list[dict]:
    return [_tok(start + i, w, 0.1 + 0.06 * i, y0, line) for i, w in enumerate(words)]


def test_normalize_lookalikes_yo_comma():
    assert normalize("Ёж, C0 %") == normalize("еж. С0%")  # Latin C == Cyrillic С, ё == е, «,» == «.»
    assert normalize("1,7 %") == "1.7%"


def test_found_with_label_extension():
    toks = _page(["водостоком,", "уклон", "кровли", "1,7%", "в", "сторону"])
    boxes = locate_value(toks, "1,7 %", "с водостоком, уклон кровли 1,7% в сторону воронок.")
    assert boxes == [[toks[1]["bbox"][0], 0.2, toks[3]["bbox"][2], 0.22]]


def test_value_split_over_tokens_without_context():
    toks = _page(["уклон", "1,7", "%", "в"])
    assert locate_value(toks, "1,7%") == [[toks[1]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]]


def test_lookalike_letters_and_sentence_end():
    toks = _page(["опасности", "-", "C0."])  # Latin C in the PDF, Cyrillic С in the value
    assert locate_value(toks, "С0", "опасности - С0.") == [
        [toks[0]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]
    ]


def test_code_before_a_numbered_list_item():
    # «…опасности - С0. 4. По функциональной…»: «.4» is the next list item, not a decimal of the code «С0».
    toks = _page(["опасности", "-", "С0.", "4.", "По"])
    assert locate_value(toks, "С0", "опасности - С0. 4. По") == [
        [toks[0]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]
    ]
    assert locate_value(_page(["уклон", "1.", "5", "%"]), "1 %") == []  # a plain number still is «1.5»


def test_punctuation_separates_digits_but_a_space_inside_a_number_does_not():
    toks = _page(["опасности", "–", "С1;", "9)", "Наличие"])  # «С1; 9)» is not «С19»
    assert locate_value(toks, "С1", "опасности – С1; 9) Наличие") == [
        [toks[0]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]
    ]
    assert locate_value(_page(["площадь", "11", "500", "м2"]), "500") == []  # «11 500» is one number
    assert locate_value(_page(["этажей", "С1", "9"]), "С1") != []  # a code is not glued to the next word


def test_plus_is_part_of_a_class_value():
    toks = _page(["класс", "эффективности", "А+", "мощность", "А"])
    assert locate_value(toks, "А+", "эффективности А+") == [
        [toks[1]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]
    ]
    assert locate_value(_page(["класс", "А", "здания"]), "А+") == []


def test_context_position_picks_the_right_repeat_of_a_one_letter_value():
    # «С» of «°С)» comes first in the context; the extractor's position points at the class letter
    ctx = "Вт/(м3 °С) ≤ 0,255 Зданию присваивается Класс энергетической эффективности С (нормальный)."
    at = sum(1 for ch in ctx[: ctx.rindex(" С ") + 1] if not ch.isspace())
    toks = _page(["0,194", "Вт/(м3", "°С)", "≤", "0,255"]) + _page(
        ["Класс", "энергетической", "эффективности", "С", "(нормальный)."], y0=0.4, line=2, start=5
    )
    want = [[toks[6]["bbox"][0], 0.4, toks[8]["bbox"][2], 0.42]]
    assert locate_value(toks, "С", ctx, at) == want
    assert locate_value(toks, "С", ctx) != want  # without the position the first «С» wins (the old behaviour)


def test_extractors_record_the_value_position():
    from inspector_tables.energy import class_facts
    from inspector_tables.pzparams import ctx_at

    flat = "q = 0,194 Вт/(м3 °С) ≤ 0,255. Зданию присваивается Класс энергетической эффективности С (нормальный)."
    (f,) = class_facts(flat)
    assert f.clause.replace(" ", "")[: f.ctx_at + 1].endswith("эффективностиС")
    assert ctx_at("a  b C", 0, 5) == 2


def test_not_found_and_not_a_number_fragment():
    toks = _page(["уклон", "кровли", "11,7%", "и", "1,75%"])
    assert locate_value(toks, "1,7 %") == []
    assert locate_value(toks, "9 %", "уклон 9 %") == []


def test_ambiguous_occurrences_give_no_box_but_context_disambiguates():
    toks = _page(["корпус", "А", "II", "корпус", "Б", "II"])
    assert locate_value(toks, "II") == []
    boxes = locate_value(toks, "II", "корпус Б II")
    assert boxes == [[toks[3]["bbox"][0], 0.2, toks[5]["bbox"][2], 0.22]]  # label words «корпус Б» included


def test_multiline_gives_one_box_per_line():
    toks = _page(["уклон", "кровли"], 0.2, 1) + _page(["1,7%"], 0.3, 2, start=2)
    boxes = locate_value(toks, "1,7%", "уклон кровли 1,7%")
    assert len(boxes) == 2


def _write_page(run_dir, file_id: str, page: int, tokens: list[dict]) -> None:
    from inspector_common.runlayout import RunLayout

    path = RunLayout(run_dir).path("PAGE_TOKENS", file_id=file_id, page=page)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"tokens": tokens}, fh)


def test_locator_reads_run_tokens_and_missing_page_is_empty(tmp_path):
    toks = _page(["уклон", "кровли", "1,7%"])
    _write_page(tmp_path, "F1", 16, toks)
    loc = ValueLocator(tmp_path)
    assert loc.boxes("F1", 16, [("1,7 %", "уклон кровли 1,7%")]) == [
        [toks[0]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]
    ]
    assert loc.boxes("F1", 17, [("1,7 %", None)]) == []
    assert ValueLocator(None).boxes("F1", 16, [("1,7 %", None)]) == []


def test_builder_attaches_box_to_value_conflict_card(tmp_path):
    toks = _page(["уклон", "кровли", "1,7%"])
    _write_page(tmp_path, "F1", 16, toks)
    value = SimpleNamespace(
        file_id="F1", page_no=16, stage="PD", param_code="AR-045", value_raw="1,7 %",
        context_text="уклон кровли 1,7%", location=None, quality_flag="OK",
    )  # fmt: skip
    b = ProtocolBuilder.__new__(ProtocolBuilder)
    b.ctx = SimpleNamespace(run_dir=tmp_path, values=[value], files={})
    b._locator = ValueLocator(tmp_path)
    b._values_by_page = None
    b.params = None
    suspicion = {
        "card_ref": "Б.1",
        "description": "d",
        "explanation": {
            "matrix_parameter_code": "AR-045",
            "values": {
                "PD": [
                    {
                        "value": "1,7 %",
                        "files": 1,
                        "mentions": [{"file_id": "F1", "page": 16, "raw": "1,7 %"}],
                    }
                ]
            },
        },
        "evidence": [{"stage": "PD", "file_id": "F1", "pdf_page_number": 16}],
    }
    b._ai_cache = {"suspicions": [suspicion]}
    b._param = lambda code: SimpleNamespace(short_name="Уклоны", criticality="X")
    cards = b._suspicion_cards()
    src = cards[0]["sources"][0]
    assert src["geometry"] == {"boxes": [[toks[0]["bbox"][0], 0.2, toks[2]["bbox"][2], 0.22]]}
    assert src["geometry_space"] == "PDF_VISIBLE_ROTATED_TL_V1"
    # the same page without tokens: the page stays without a box
    b._locator = ValueLocator(tmp_path / "none")
    assert "geometry" not in b._suspicion_cards()[0]["sources"][0]
