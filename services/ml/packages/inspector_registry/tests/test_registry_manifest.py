from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspector_common.errors import InspectorError
from inspector_registry.manifest import Registry, SplitPolicy, UnknownFileError


def _registry(fake) -> Registry:
    return Registry.load(fake.paths)


def test_loads_objects_files_stages_sections(fake, build) -> None:
    reg = _registry(fake)
    assert reg.objects()[:1] == [build.TRAIN]
    assert (
        build.HIDDEN in reg.objects() and build.TRAIN_B in reg.objects()
    )  # policy objects without files too
    files = reg.files(build.TRAIN)
    assert len(files) == 17  # F0001…F0017; the excluded F0999 is dropped
    assert reg.stages(build.TRAIN) == {"PD": 4, "RD_ID_MIXED": 2, "UNKNOWN": 1, "RD": 7, "ID": 3}
    assert reg.sections(build.TRAIN) == {"OTHER": 17}
    assert reg.split_of(build.HIDDEN) == "TEST_HIDDEN"
    assert reg.policy.is_hidden(build.HIDDEN) and not reg.policy.is_hidden(build.TRAIN)
    assert reg.rows_read == 19


def test_excluded_ids_are_dropped_flagged_and_refused(fake) -> None:
    reg = _registry(fake)
    assert "F0999" not in reg
    assert reg.is_excluded("F0999")
    codes = [(f.code, f.file_id) for f in reg.flags]
    assert ("EXCLUDED_FILE_REFERENCED", "F0999") in codes
    with pytest.raises(InspectorError) as info:
        reg.get("F0999")
    assert info.value.code == "EXCLUDED_FILE_REFERENCED"
    assert "исключён" in info.value.detail
    assert reg.not_citable_reasons("F0999")
    with pytest.raises(UnknownFileError):
        reg.get("F0555")


def test_exact_duplicate_rows_are_flagged(fake) -> None:
    reg = _registry(fake)
    dup = [f for f in reg.flags if f.code == "DUPLICATE_IN_PACKAGE"]
    assert [f.file_id for f in dup] == ["F0016"]
    assert "F0015" in dup[0].detail
    assert sorted(reg.by_sha256[reg.get("F0015").sha256]) == ["F0015", "F0016"]


def test_citability_rules(fake) -> None:
    reg = _registry(fake)
    assert reg.is_citable("F0001")
    assert not reg.is_citable("F0004")  # GROUND_TRUTH_INDEX
    assert any("GROUND_TRUTH_INDEX" in r for r in reg.not_citable_reasons("F0004"))
    assert not reg.is_citable("F0006")  # archive: evidence only from PDF pages
    assert not reg.is_citable("F0011")  # DOCX
    assert reg.page_in_range("F0001", 1) and reg.page_in_range("F0001", 3)
    assert not reg.page_in_range("F0001", 4) and not reg.page_in_range("F0001", 0)
    assert not reg.page_in_range("F0006", 1)


def test_stage_acceptance(fake) -> None:
    reg = _registry(fake)
    assert reg.stage_accepts("F0001", "PD") and not reg.stage_accepts("F0001", "RD")
    assert reg.stage_accepts("F0002", "RD") and reg.stage_accepts("F0002", "ID")
    assert not reg.stage_accepts("F0002", "PD")
    assert reg.stage_accepts("F0002", "ID", resolved="ID") and not reg.stage_accepts(
        "F0002", "RD", resolved="ID"
    )
    assert not reg.stage_accepts("F0004", "PD")  # UNKNOWN never


def test_duplicate_group_representative(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    fake.add("F0001", build.TRAIN, "a/x.pdf", builder=lambda p: build.pdf(p, ["one"]), duplicate_group="g1")
    fake.add("F0002", build.TRAIN, "a/y.pdf", builder=lambda p: build.pdf(p, ["two"]), duplicate_group="g1")
    fake.write_manifest()
    reg = Registry.load(fake.paths)
    assert reg.duplicate_group_representatives == {"g1": "F0001"}
    assert reg.is_citable("F0001")
    assert any("дубликат группы" in r for r in reg.not_citable_reasons("F0002"))


def test_invalid_rows_are_reported_not_fatal(build, tmp_path: Path) -> None:
    fake = build.new_fake(tmp_path)
    fake.add("F0001", build.TRAIN, "a/x.pdf", builder=lambda p: build.pdf(p, ["one"]))
    bad_split = fake.add(
        "F0002", build.TRAIN, "a/y.pdf", builder=lambda p: build.pdf(p, ["two"]), split="TEST_HIDDEN"
    )
    assert bad_split["split"] == "TEST_HIDDEN"
    dup = dict(fake.rows[0])
    unsafe = dict(fake.rows[0], file_id="F0003", relative_path="../outside.pdf")
    wrong_ext = dict(fake.rows[0], file_id="F0004", extension=".zip")
    new_vocab = dict(fake.rows[0], file_id="F0005", section="NEW_SECTION")
    fake.write_manifest(
        extra_lines=[
            "{not json",
            json.dumps({"file_id": "F0006"}),
            json.dumps(dup, ensure_ascii=False),
            json.dumps(unsafe, ensure_ascii=False),
            json.dumps(wrong_ext, ensure_ascii=False),
            json.dumps(new_vocab, ensure_ascii=False),
        ]
    )
    reg = Registry.load(fake.paths)
    codes = [f.code for f in reg.flags]
    # json, schema, unsafe path, split, and two for F0004 (extension and pdf_pages on a non-PDF row)
    assert codes.count("MANIFEST_ROW_INVALID") == 6
    assert codes.count("REGISTRY_DUPLICATE_FILE_ID") == 1
    assert "F0003" not in reg and "F0006" not in reg
    assert "F0004" in reg and "F0005" in reg  # kept, but flagged / reported
    assert reg.unknown_open_values == {"section": ["NEW_SECTION"]}
    reasons = " | ".join(f.detail for f in reg.flags if f.code == "MANIFEST_ROW_INVALID")
    assert "split_policy.json" in reasons and "не является JSON" in reasons and "pdf_pages" in reasons


def test_manifest_checksum_against_package_sums(fake) -> None:
    sums = fake.paths.package_sha256sums_path
    sums.write_text("0" * 64 + "  data/document_manifest.jsonl\n", encoding="utf-8")
    reg = Registry.load(fake.paths)
    assert reg.manifest_checksum_ok is False
    assert any(f.code == "CHECKSUM_MISMATCH" for f in reg.flags)
    sums.write_text(f"{reg.manifest_sha256}  data/document_manifest.jsonl\n", encoding="utf-8")
    assert Registry.load(fake.paths).manifest_checksum_ok is True


def test_input_manifest_hash_is_order_independent(fake, build) -> None:
    reg = _registry(fake)
    h = reg.input_manifest_hash(build.TRAIN)
    fake.rows.reverse()
    fake.write_manifest()
    assert Registry.load(fake.paths).input_manifest_hash(build.TRAIN) == h


def test_missing_split_policy_is_data_root_not_found(tmp_path: Path) -> None:
    from inspector_common.paths import DataPaths

    paths = DataPaths(tmp_path / "nope", tmp_path, tmp_path, tmp_path)
    with pytest.raises(InspectorError) as info:
        Registry.load(paths)
    assert info.value.code == "DATA_ROOT_NOT_FOUND"


def test_split_policy_objects(tmp_path: Path) -> None:
    p = tmp_path / "split_policy.json"
    p.write_text(
        json.dumps({"TRAIN_PUBLIC": ["A", "B"], "TEST_HIDDEN": ["Z"], "excluded_file_ids": ["F0001"]})
    )
    policy = SplitPolicy.load(p)
    assert policy.objects == ("A", "B", "Z")
    assert policy.split_of("Z") == "TEST_HIDDEN" and policy.split_of("Q") is None
    assert policy.excluded_file_ids == frozenset({"F0001"})
