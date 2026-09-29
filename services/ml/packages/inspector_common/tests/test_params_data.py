"""Matrix seed against the organizer package (skips without it): catalog, build drift, Приложение 2, train gold.

Owner: AG-03. Only TRAIN_PUBLIC material is read here (catalog, Приложение 2 sample, Тюменская gold).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from inspector_common import params
from inspector_common.contracts import codes
from inspector_common.contracts.loader import enum_mappings

pytestmark = pytest.mark.data

APPENDIX2 = "ПРИЛОЖЕНИЕ 2. ПРИМЕР ПРОТОКОЛА СРАВНЕНИЯ.docx"
CODE_IN_PARENS = re.compile(r"^(?P<name>.+?)\s*\((?P<code>[A-ZА-Я0-9]+-\d{1,3})\)$")


@pytest.fixture(scope="module")
def reg() -> params.ParamRegistry:
    return params.load_params()


def test_seed_matches_the_catalog(data_paths, reg: params.ParamRegistry) -> None:
    rows = params.load_catalog()
    assert len(rows) == 132
    assert params.load_catalog(data_paths.catalog_path) == rows
    for row in rows:
        spec = reg.get(row.parameter_id)
        assert spec.to_catalog_row() == row, row.parameter_code


def _load_builder():
    path = params.seed_dir() / "src" / "build_seed.py"
    spec = importlib.util.spec_from_file_location("inspector_seed_build", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_committed_seed_equals_a_fresh_build(data_paths) -> None:
    builder = _load_builder()
    outputs = builder.build_all(Path(data_paths.catalog_path))
    for name, text in outputs.items():
        assert (params.seed_dir() / name).read_text(encoding="utf-8") == text, (
            f"{name} is stale: run build_seed.py"
        )


@pytest.fixture(scope="module")
def appendix2_tables(data_paths) -> list[list[list[str]]]:
    docx = pytest.importorskip("docx")
    path = data_paths.package_root / "ТЗ_И_ПРИЛОЖЕНИЯ" / APPENDIX2
    if not path.is_file():
        pytest.skip("Приложение 2 docx not found")
    document = docx.Document(str(path))
    return [[[cell.text.strip() for cell in row.cells] for row in table.rows] for table in document.tables]


def test_appendix2_section3_codes_and_short_names(appendix2_tables, reg: params.ParamRegistry) -> None:
    section3 = appendix2_tables[2]
    assert section3[0][:4] == ["№", "Код", "Раздел", "Параметр"]
    for _, code, section, name, _file in section3[1:]:
        res = reg.resolve(code, name=name)
        spec = reg.get(res.code)
        assert res.warnings == (), (code, res.warnings)
        assert (
            spec.section == section
            and spec.short_name == name
            and spec["text_sources"]["short_name"] == "APPENDIX2"
        )


def test_appendix2_violation_tables_resolve(appendix2_tables, reg: params.ParamRegistry) -> None:
    resolved = []
    for table in (appendix2_tables[3], appendix2_tables[4]):
        for row in table[1:]:
            section, named = row[1], row[2]
            m = CODE_IN_PARENS.match(named)
            assert m, named
            res = reg.resolve(m.group("code"), name=m.group("name"))
            spec = reg.get(res.code)
            assert spec.section == section
            assert m.group("name") in (spec.short_name, *spec.name_variants)
            resolved.append((m.group("code"), res.code, bool(res.warnings)))
    assert ("AR-14", "AR-040", True) in resolved  # the organizer typo, resolved by name with a warning
    assert sum(w for *_, w in resolved) == 1


def test_appendix2_work_types(appendix2_tables, reg: params.ParamRegistry) -> None:
    for row in appendix2_tables[6][1:]:
        m = CODE_IN_PARENS.match(row[1])
        spec = reg.get(reg.resolve(m.group("code"), name=None).code)
        assert spec["work_type"] == m.group("name") and spec["text_sources"]["work_type"] == "APPENDIX2"


def _docx_rows(appendix2_tables) -> dict[str, dict[str, str]]:
    """Per catalog code: the Разделы 4–5 row and the Раздел 7 cells of the Приложение 2 sample."""
    reg = params.load_params()
    rows: dict[str, dict[str, str]] = {}
    for table in (appendix2_tables[3], appendix2_tables[4]):
        for row in table[1:]:
            m = CODE_IN_PARENS.match(row[2])
            code = reg.resolve(m.group("code"), name=m.group("name")).code
            rows.setdefault(code, {})["row"] = " | ".join(row[:7])
    for section, table in (("7.1", appendix2_tables[6]), ("7.2", appendix2_tables[7])):
        for row in table[1:]:
            m = CODE_IN_PARENS.match(row[1])
            code = reg.resolve(m.group("code"), name=m.group("name") if section == "7.1" else None).code
            key = "work_type" if section == "7.1" else "violation_kind"
            rows.setdefault(code, {}).update({key: row[1], "recommendation": row[2]})
    return rows


def test_appendix2_samples_in_the_templates_are_verbatim(appendix2_tables) -> None:
    """recommendation_templates.json keeps the Приложение 2 rows verbatim (app2_sample), the basis of text_origin."""
    rows = _docx_rows(appendix2_tables)
    tpl = params.load_recommendation_templates()
    assert len(rows) == 12
    for code, docx_row in rows.items():
        sample = tpl.get(code).data["app2_sample"]
        assert sample is not None, code
        assert sample["row"] == docx_row["row"], code
        assert sample["recommendation"] == docx_row["recommendation"], code
        for key in ("work_type", "violation_kind"):
            if key in docx_row:
                assert sample[key].replace("ё", "е") == docx_row[key].replace("ё", "е"), code


def test_appendix2_recommendations_render_verbatim_where_claimed(appendix2_tables) -> None:
    """A template marked APPENDIX2 reproduces the docx text with the sample's values; the others document why."""
    rows = _docx_rows(appendix2_tables)
    tpl = params.load_recommendation_templates()
    verbatim = 0
    for code, docx_row in rows.items():
        t = tpl.get(code)
        cells = docx_row["row"].split(" | ")
        r = tpl.render(code, pd_value=cells[3], rd_value=cells[4], id_value=cells[5], preliminary=False)
        if t.data["text_origin"]["recommendation"] == "APPENDIX2":
            assert r.recommendation_text == docx_row["recommendation"], code
            assert params.load_params().get(code)["text_sources"]["recommendation_template"] == "APPENDIX2"
            verbatim += 1
        else:
            differences = t.data["app2_sample"]["differences"]
            assert differences and not differences.lower().startswith("нет"), code
    assert verbatim == 3  # SPZU-025, POS-082, POD-093; the other nine are verified norm corrections


def test_appendix2_deviation_verbs(appendix2_tables, reg: params.ParamRegistry) -> None:
    expected = {
        "KR-055": ("CLASS_DOWNGRADED", "Понижение класса"),
        "IOS1-069": ("VALUE_DECREASED", "Занижение сечения"),
        "PPM-103": ("CLASS_DOWNGRADED", "Снижение предела"),
        "ODI-122": ("ELEMENT_MISSING", "Полное отсутствие"),
    }
    printed = {}
    for table in (appendix2_tables[3], appendix2_tables[4]):
        for row in table[1:]:
            m = CODE_IN_PARENS.match(row[2])
            printed[reg.resolve(m.group("code"), name=m.group("name")).code] = row[6]
    for code, (dt, verb) in expected.items():
        assert reg.get(code)["deviation_verb"][dt] == verb
        assert printed[code].endswith(verb)


@pytest.fixture(scope="module")
def gold(data_paths) -> tuple[list[dict], dict[str, dict]]:
    with open(data_paths.train_checks_path, encoding="utf-8") as fh:
        checks = [json.loads(line) for line in fh if line.strip()]
    with open(data_paths.train_groups_path, encoding="utf-8") as fh:
        groups = {g["finding_group_id"]: g for g in (json.loads(line) for line in fh if line.strip())}
    return checks, groups


GOLD_ROUTES = {  # finding group → (element family, discrepancy type); learned from T, 97 §2.10
    "G-TR-001": ("VENT_SUPPLY_UNIT", "CONFIGURATION_CHANGED"),
    "G-TR-002": ("WARM_FLOOR", "ELEMENT_MISSING"),
    "G-TR-003": ("VENT_EXHAUST_BRANCH", "ELEMENT_MISSING"),
    "G-TR-004": ("VENT_EXHAUST_BRANCH", "CONFIGURATION_CHANGED"),
}
RD_PLAN_MARK = {"G-TR-001": "ОВ1"}  # the plan name printed in the gold rd_value («на плане ОВ1»)


def test_train_gold_codes_and_criticality(gold, reg: params.ParamRegistry) -> None:
    checks, _ = gold
    free = enum_mappings()["free_search"]
    for chk in checks:
        code = chk["parameter_code"]
        if codes.is_free_code(code):
            topic, n = codes.parse_free_code(code)
            assert topic in params.load_free_topics() and n == 1
            assert (
                chk["criticality"] == free["criticality_string"]
                and chk["protocol_status"] == free["protocol_status"]
            )
        else:
            spec = reg.get(code)
            assert spec.param_id == chk["parameter_id"] and spec.criticality == chk["criticality"]


def test_train_gold_is_reproduced_by_the_change_map(gold) -> None:
    checks, groups = gold
    cmap = params.load_change_map()
    for chk in checks:
        gid = chk["finding_group_id"]
        route = cmap.route(*GOLD_ROUTES[gid])
        code = route.parameter_code + "-001" if route.is_free else route.parameter_code
        assert code == chk["parameter_code"], gid
        assert route.comparison_result == chk["comparison_result"]
        assert route.parameter_mapping_status.value == groups[gid]["parameter_mapping_status"]
        pd_sheet = next(e["document_sheet_number"] for e in chk["evidence"] if e["stage"] == "PD")
        values = {
            "pd_sheet": pd_sheet,
            "location": chk["location"],
            "rd_plan_mark": RD_PLAN_MARK.get(gid, ""),
        }
        templates = route.data["value_templates"]
        assert templates["pd"].format(**values) == chk["pd_value"], gid
        assert templates["rd"].format(**values) == chk["rd_value"], gid
        assert templates["id"] is None and chk["id_value"] is None
