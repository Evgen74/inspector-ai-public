"""Inventory on the two TRAIN objects of the organizer package (marker ``data``; skipped without data).

Only TRAIN objects are used here. The hidden-test object is never part of a test (97 §2.17).
Expected values come from 93 §1.2–§2.6 and 95 §2–§3 (manifest facts and the RD_ID_MIXED ruling).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from inspector_common.contracts.enums import LocalFileStatus
from inspector_registry.cache import RegistryCache
from inspector_registry.inventory import Inventory, InventoryOptions
from inspector_registry.manifest import Registry
from inspector_registry.report import validate_report
from inspector_registry.resolver import PathResolver

pytestmark = pytest.mark.data

TYUMEN = "OBJ-TYUMENSKAYA-5-GOLD-SEED"
NOVOSLOB = "OBJ-NOVOSLOBODSKAYA"


@pytest.fixture(scope="module")
def registry(real_paths) -> Registry:
    return Registry.load(real_paths)


def _inventory(registry: Registry, real_paths, object_id: str, *, verify: bool = False) -> dict[str, Any]:
    resolver = PathResolver(registry, real_paths, RegistryCache(None), hash_workers=8)
    inv = Inventory(registry, resolver, InventoryOptions(verify_sha256=verify), RegistryCache(None))
    return inv.run_object(object_id, run_id="pytest").report


@pytest.fixture(scope="module")
def tyumen(registry: Registry, real_paths) -> dict[str, Any]:
    return _inventory(registry, real_paths, TYUMEN)


@pytest.fixture(scope="module")
def novoslob(registry: Registry, real_paths) -> dict[str, Any]:
    return _inventory(registry, real_paths, NOVOSLOB)


def test_manifest_registry_facts(registry: Registry) -> None:
    assert registry.manifest_checksum_ok is True
    assert len(registry) == 416 and registry.rows_read == 416
    assert registry.policy.excluded_file_ids == frozenset({"F0149", "F0418"})
    assert "F0149" not in registry and "F0418" not in registry
    assert [f.code for f in registry.flags] == []
    assert registry.unknown_open_values == {}
    assert registry.stages(TYUMEN) == {"PD": 47, "RD_ID_MIXED": 10, "UNKNOWN": 1}
    assert registry.stages(NOVOSLOB) == {"ID": 99, "PD": 36, "RD": 10}
    assert registry.duplicate_group_representatives == {"f4a34324aaf6": "F0165"}
    assert registry.is_citable("F0165")
    assert not registry.is_citable("F0194")  # GROUND_TRUTH_INDEX «Перечень нарушений.txt»


def test_tyumen_inventory(tyumen: dict[str, Any]) -> None:
    assert validate_report(tyumen) == []
    c = tyumen["counts"]
    assert (c["files_total"], c["files_present"], c["files_missing_on_disk"]) == (58, 58, 0)
    assert c["pdf_files"] == 57 and c["pdf_pages_actual_total"] == c["pdf_pages_manifest_total"] == 5863
    assert c["pdf_page_count_mismatches"] == 0
    assert c["citable_files"] == 57
    assert c["stage_resolution"] == {
        "needed": 11,
        "resolved": 10,
        "unresolved": 1,
        "conflicts_with_manifest": 0,
    }
    files = {f["file_id"]: f for f in tyumen["files"]}
    # 93 §2.6: F0201/F0202 full RD sections → RD; АОСР and «Исполнительный чертеж» → ID.
    expected = {f"F0{n}": "ID" for n in range(195, 201)} | {f"F0{n}": "RD" for n in range(201, 205)}
    assert {fid: files[fid]["stage_resolved"] for fid in expected} == expected
    assert all(files[fid]["stage"]["source"] == "EXTRACTED_UNCONFIRMED" for fid in expected)
    assert files["F0194"]["stage_resolved"] is None and files["F0194"]["citable"] is False
    assert files["F0194"]["media_type"] is None  # the ground-truth file is never read
    assert files["F0165"]["citable"] is True
    # 95 §3.6: the ПЗУ original and its «ИЗМ ПО ЗАМЕЧАНИЯМ» revision share page 1 and the page count.
    assert {"F0154", "F0155"} <= {fid for g in tyumen["duplicates"]["near"] for fid in g["file_ids"]}
    assert tyumen["duplicates"]["exact"] == []


def test_novoslob_inventory(novoslob: dict[str, Any]) -> None:
    assert validate_report(novoslob) == []
    c = novoslob["counts"]
    # The 19 files lost to the case-insensitive APFS merge (93 §1.3) are restored and in the ledger.
    assert (c["files_total"], c["files_present"], c["files_recovered"], c["files_missing_on_disk"]) == (
        145,
        126,
        19,
        0,
    )
    recovered = sorted(
        f["file_id"] for f in novoslob["files"] if f["local_status"] == LocalFileStatus.RECOVERED.value
    )
    assert recovered[:3] == ["F0015", "F0018", "F0021"] and recovered[-1] == "F0080"
    assert c["pdf_pages_actual_total"] == c["pdf_pages_manifest_total"]
    assert c["by_stage_resolved"] == {"ID": 99, "PD": 36, "RD": 10}
    assert c["stage_resolution"]["conflicts_with_manifest"] == 0
    assert c["integrity_flags_by_code"].get("FILE_MISSING_ON_DISK", 0) == 0


def test_stage_signals_agree_with_manifest_on_train(tyumen: dict[str, Any], novoslob: dict[str, Any]) -> None:
    """Where the manifest states PD/RD/ID, the generic signals never contradict it on train."""
    rows = [f for f in tyumen["files"] + novoslob["files"] if f["manifest_stage"] in ("PD", "RD", "ID")]
    disagreements = [
        f["file_id"] for f in rows if f["stage"]["signals_stage"] not in (None, f["manifest_stage"])
    ]
    assert disagreements == []
    agreeing = sum(1 for f in rows if f["stage"]["signals_stage"] == f["manifest_stage"])
    assert agreeing / len(rows) >= 0.9


def test_inventory_is_fast(registry: Registry, real_paths) -> None:
    started = time.perf_counter()
    _inventory(registry, real_paths, TYUMEN)
    assert time.perf_counter() - started < 20


@pytest.mark.slow
def test_full_sha256_verification_of_train_objects(registry: Registry, real_paths) -> None:
    for object_id in (TYUMEN, NOVOSLOB):
        report = _inventory(registry, real_paths, object_id, verify=True)
        c = report["counts"]
        assert c["sha256_verified"] == c["files_total"] and c["sha256_mismatch"] == 0, object_id
