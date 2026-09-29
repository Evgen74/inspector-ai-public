"""Dev-set registry: T-GOLD, N-GOLD (seed format of 95), label freeze and hidden-object refusal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.errors import InspectorError
from inspector_common.paths import repo_root
from inspector_common.settings import Settings
from inspector_eval import devset
from inspector_eval.data import InputError


def _registry(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"schema_version": 1, "devsets": entries}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _seed_set(tmp_path: Path, candidates: list[dict], object_id: str = "OBJ-B") -> dict:
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps({"meta": {}, "candidates": candidates}, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "id": "N-TEST",
        "object_id": object_id,
        "split": "TRAIN_PUBLIC",
        "format": "label_seed_json",
        "path": {"base": "repo", "relative": str(labels)},
        "badge_ru": "Разметка команды",
        "frozen": False,
        "labels_sha256": None,
        "folds": {"A": ["KR"], "B": ["*"]},
    }


def _item(item_id: str, code: str, label: str | None, **extra) -> dict:
    return {
        "id": item_id,
        "parameter_code": code,
        "location": extra.pop("location", "OBJECT"),
        "pd_value": extra.pop("pd_value", "B25"),
        "rd_value": extra.pop("rd_value", "B25"),
        "id_value": extra.pop("id_value", "B25"),
        "evidence": extra.pop(
            "evidence",
            [
                {"stage": "PD", "file_id": "F0005", "pdf_page_number": 1},
                {"stage": "RD", "file_id": "F0006", "pdf_page_number": 2},
            ],
        ),
        "system_hypothesis": "…",
        "label": label,
        "label_comment": None,
        **extra,
    }


CANDIDATES = [
    _item("NS-1", "КР-55", "VIOLATION_PRESENT", rd_value="B20", location="БСС-1н в/о 4-2.8/А-Х1"),
    _item("NS-2", "PZ-001", "NO_VIOLATION"),
    _item("NS-3", "KR-055", "MISSING_DOCUMENT", id_value=None, location="Корпус 1"),
    _item("NS-4", "SPZU-025", "COMPARISON_IMPOSSIBLE"),
    _item("NS-5", "FREE-STRUCTURE-001", "VIOLATION_PRESENT", location="012"),
    _item("NS-6", "AR-040", "UNSURE"),
    _item("NS-7", "AR-040", None),
]


@pytest.fixture()
def paths(fake_data_root: Path):
    return Settings(data_root=fake_data_root).paths


def test_package_registry_has_t_gold_and_n_gold() -> None:
    sets = {d.id: d for d in devset.load_registry()}
    assert set(sets) == {"T-GOLD", "N-GOLD"}
    assert sets["T-GOLD"].frozen and sets["T-GOLD"].format == "gold_checks_jsonl"
    assert sets["N-GOLD"].format == "label_seed_json" and sets["N-GOLD"].folds == {"A": ["KR"], "B": ["*"]}


@pytest.mark.data
def test_package_n_gold_labels_convert_with_the_real_catalog(real_paths, real_ctx) -> None:
    """The 14 seed items labelled by the agent protocol: every scorable one is a valid gold_check row."""
    n_gold_set = devset.get_devset("N-GOLD")
    rows = devset.load_devset(n_gold_set, real_paths, real_ctx)
    assert len(rows.gold_rows) + len(rows.excluded) >= 14
    assert all(r["object_id"] == "OBJ-NOVOSLOBODSKAYA" for r in rows.gold_rows)
    if not n_gold_set.frozen:
        assert rows.hash_ok is None and all("gold_status" not in r for r in rows.gold_rows)
    by_id = {r["check_id"]: r for r in rows.gold_rows}
    # Directional-trigger traps from 95 §4.4 stay negatives (the RD slab is thicker; the class is unchanged).
    assert by_id["NS-C14"]["violation_label"] == "NO_VIOLATION"
    assert by_id["NS-C01"]["violation_label"] == "NO_VIOLATION"
    assert {e["id"] for e in rows.excluded} >= {"NS-C09", "NS-C12", "NS-C13"}  # not scorable


def test_seed_items_convert_to_valid_gold_rows(tmp_path, paths, ctx) -> None:
    registry = _registry(tmp_path, [_seed_set(tmp_path, CANDIDATES)])
    rows = devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    by_id = {r["check_id"]: r for r in rows.gold_rows}
    assert set(by_id) == {"NS-1", "NS-2", "NS-3", "NS-4", "NS-5"}
    assert [e["id"] for e in rows.excluded] == ["NS-6", "NS-7"]  # UNSURE and unlabeled are listed, not scored
    assert by_id["NS-1"]["parameter_code"] == "KR-055" and by_id["NS-1"]["protocol_status"] == "CRITICAL"
    assert by_id["NS-1"]["location_type"] == "AXES"
    assert by_id["NS-2"]["protocol_status"] == "OK"
    assert by_id["NS-3"]["protocol_status"] == "ID_MISSING" and by_id["NS-3"]["location_type"] == "BUILDING"
    assert by_id["NS-4"]["protocol_status"] == "COMPARISON_IMPOSSIBLE"
    assert by_id["NS-4"]["criticality"] == "Существенное (предписание)"
    assert by_id["NS-5"]["matrix_scope"] == "FREE_SEARCH" and by_id["NS-5"]["protocol_status"] == "WARNING"
    assert rows.positives == 2


def test_missing_document_without_a_missing_stage_needs_a_status(tmp_path, paths, ctx) -> None:
    item = _item("NS-X", "KR-055", "MISSING_DOCUMENT")
    registry = _registry(tmp_path, [_seed_set(tmp_path, [item])])
    with pytest.raises(InputError, match="protocol_status"):
        devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    item["protocol_status"] = "RD_MISSING"
    registry = _registry(tmp_path, [_seed_set(tmp_path, [item])])
    rows = devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    assert rows.gold_rows[0]["protocol_status"] == "RD_MISSING"


def test_freeze_pins_labels_and_relabelling_fails(tmp_path, paths, ctx) -> None:
    entry = _seed_set(tmp_path, CANDIDATES)
    registry = _registry(tmp_path, [entry])
    digest = devset.freeze("N-TEST", paths, ctx, registry, now="2026-09-27T00:00:00Z")
    frozen = devset.get_devset("N-TEST", registry)
    assert frozen.frozen and frozen.labels_sha256 == digest
    assert devset.load_devset(frozen, paths, ctx).hash_ok is True
    with pytest.raises(InputError, match="уже заморожен"):
        devset.freeze("N-TEST", paths, ctx, registry, now="x")
    # relabel after the freeze
    labels = Path(entry["path"]["relative"])
    doc = json.loads(labels.read_text(encoding="utf-8"))
    doc["candidates"][1]["label"] = "VIOLATION_PRESENT"
    labels.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InspectorError) as info:
        devset.load_devset(frozen, paths, ctx)
    assert info.value.code == "TEST_SET_HASH_MISMATCH"
    assert devset.load_devset(frozen, paths, ctx, verify=False).hash_ok is False


def test_unlabelled_items_do_not_change_the_hash(tmp_path) -> None:
    used, _ = devset.labelled_items({"candidates": CANDIDATES})
    more, _ = devset.labelled_items({"candidates": [*CANDIDATES, _item("NS-8", "AR-040", None)]})
    assert devset.labels_hash(used) == devset.labels_hash(more)
    assert devset.labels_hash(list(reversed(used))) == devset.labels_hash(used)


def test_freeze_refuses_an_empty_set(tmp_path, paths, ctx) -> None:
    registry = _registry(tmp_path, [_seed_set(tmp_path, [])])
    with pytest.raises(InputError, match="пуст"):
        devset.freeze("N-TEST", paths, ctx, registry, now="x")


def test_registry_refuses_a_hidden_object(tmp_path, paths, ctx) -> None:
    registry = _registry(tmp_path, [_seed_set(tmp_path, CANDIDATES, object_id="OBJ-Z")])
    with pytest.raises(InspectorError) as info:
        devset.load_registry(registry, ctx.split_policy)
    assert info.value.code == "HIDDEN_TEST_ACCESS_DENIED"
    with pytest.raises(InspectorError):
        devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)


def test_registry_rejects_duplicate_ids(tmp_path) -> None:
    entry = _seed_set(tmp_path, [])
    with pytest.raises(InputError, match="повторяются"):
        devset.load_registry(_registry(tmp_path, [entry, entry]))


def test_the_95_seed_file_is_in_the_n_gold_format(paths, ctx) -> None:
    """docs/analysis/95_novoslob_label_seed.json: 14 candidates, all unlabeled → 0 rows, 14 listed."""
    seed = repo_root() / "docs" / "analysis" / "95_novoslob_label_seed.json"
    if not seed.is_file():
        pytest.skip("seed file not present")
    entry = devset.DevSet(
        id="SEED",
        object_id="OBJ-B",
        split="TRAIN_PUBLIC",
        format="label_seed_json",
        path_base="repo",
        path=str(seed),
        badge_ru="",
        positives_only=False,
        frozen=False,
        labels_sha256=None,
    )
    rows = devset.load_devset(entry, paths, ctx)
    assert rows.gold_rows == [] and len(rows.excluded) == 14


@pytest.mark.data
def test_t_gold_loads_with_a_matching_hash(real_paths, real_ctx) -> None:
    rows = devset.load_devset(devset.get_devset("T-GOLD"), real_paths, real_ctx)
    assert len(rows.gold_rows) == 10 and rows.positives == 10 and rows.hash_ok is True
    summary = [d.summary() for d in devset.load_all(real_paths, real_ctx)]
    assert [s["id"] for s in summary] == ["T-GOLD", "N-GOLD"]
