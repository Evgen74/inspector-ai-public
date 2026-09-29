from __future__ import annotations

import pytest

from inspector_batch import runinfo
from inspector_common.contracts import loader


def test_run_id_and_versions() -> None:
    assert runinfo.new_run_id("inventory").endswith("-inventory")
    v = runinfo.versions()
    assert v["pipeline_version"] and v["contract_version"] == loader.contract_version()


@pytest.mark.data
def test_input_hashes_match_package_checksums(data_paths_or_skip) -> None:
    hashes = runinfo.input_hashes(data_paths_or_skip)
    assert (
        hashes["submission_schema_sha256"]
        == "75c58bef6b580528e7e4af8e4fdcdf5a5d40599b8966dae90df38b3a5f04a8d7"
    )
    assert hashes["manifest_sha256"] == "853225daec1888fbed19bbeb45e958154135f069799cea883dcd3c754c6c4ee7"


def test_run_manifest_skeleton_validates(tmp_path) -> None:
    """A RunManifest assembled from the CLI context plus minimal object/file entries satisfies the schema."""
    sha = "a" * 64
    manifest = {
        "schema_version": 1,
        "run_id": "20260927T230000Z-inventory",
        "producer": "inspector-batch",
        "started_at": runinfo.utc_now(),
        "status": "SUCCEEDED",
        "config_hash": sha,
        "versions": {k: v for k, v in runinfo.versions().items() if v is not None},
        "inputs": {"manifest_sha256": sha, "catalog_sha256": sha, "submission_schema_sha256": sha},
        "host": runinfo.host_info(),
        "objects": [
            {
                "object_id": "OBJ-TRAIN-A",
                "split": "TRAIN_PUBLIC",
                "input_manifest_hash": sha,
                "files_total": 1,
                "files_present": 1,
                "missing_on_disk": [],
            }
        ],
        "files": [
            {
                "file_id": "F0001",
                "object_id": "OBJ-TRAIN-A",
                "sha256": sha,
                "manifest_stage": "PD",
                "local_status": "PRESENT",
            }
        ],
    }
    assert loader.validation_errors("run_manifest", manifest) == []


def test_run_context_records_the_matrix_overrides_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Module 8: every run records which admin overrides it read (or that none were), in versions and context."""
    import json

    from inspector_common.params import overrides_summary

    monkeypatch.setenv("INSPECTOR_MATRIX_OVERRIDES", "off")
    off = runinfo.matrix_overrides_info()
    assert off["applied"] is False and off["reason"] == "disabled_by_env"
    assert runinfo.versions()["engine_versions"]["matrix_overrides"] == "none (disabled_by_env)"

    path = tmp_path / "matrix_overrides.json"
    path.write_text(
        json.dumps(
            {"matrix_version": "1.1.1+ovr.7", "overrides": [{"param_code": "AR-040", "min_value": 1.4}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("INSPECTOR_MATRIX_OVERRIDES", str(path))
    v = runinfo.versions()
    assert v["matrix_version"] == "1.1.1+ovr.7"
    assert v["engine_versions"]["matrix_overrides"] == overrides_summary(runinfo.matrix_overrides_info())
    assert runinfo.matrix_overrides_info()["changed"] == ["AR-040"]
