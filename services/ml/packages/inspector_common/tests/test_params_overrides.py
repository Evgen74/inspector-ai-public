"""Admin overrides from /admin/normative applied over the seed (module 8, «без перекодирования»). Owner: AG-03."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from inspector_common import params


def _write(tmp_path: Path, rows: list[dict[str, Any]], version: str = "1.1.1+ovr.3") -> Path:
    path = tmp_path / "matrix_overrides.json"
    path.write_text(json.dumps({"matrix_version": version, "overrides": rows}), encoding="utf-8")
    return path


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch):
    def _use(value: str | Path | None) -> params.ParamRegistry:
        if value is None:
            monkeypatch.delenv(params.MATRIX_OVERRIDES_ENV, raising=False)
        else:
            monkeypatch.setenv(params.MATRIX_OVERRIDES_ENV, str(value))
        return params.load_params()

    return _use


def test_disabled_by_env_is_the_seed_and_recorded(use) -> None:
    reg = use("off")
    info = reg.overrides
    assert info["applied"] is False and info["reason"] == "disabled_by_env" and info["path"] is None
    assert reg.matrix_version == info["base_matrix_version"]
    assert params.overrides_summary(info) == "none (disabled_by_env)"


def test_applies_thresholds_and_activity_over_the_seed(tmp_path: Path, use) -> None:
    base = use("off")
    rows = [
        {"param_code": "AR-040", "min_value": 1.5, "max_value": None, "is_active": True},
        {"param_code": "AR-048", "min_value": None, "max_value": 140, "is_active": None},
        {"param_code": "KR-058", "min_value": None, "max_value": None, "is_active": False},
    ]
    reg = use(_write(tmp_path, rows))
    assert reg.matrix_version == "1.1.1+ovr.3" != base.matrix_version
    assert reg.content_sha256 != base.content_sha256
    ar40 = reg.get("AR-040")
    assert (ar40.min_value, ar40.max_value, ar40.is_active) == (1.5, None, True)
    assert (
        reg.get("AR-048").max_value == 140.0 and reg.get("AR-048").is_active is True
    )  # null is_active → seed
    assert reg.get("KR-058").is_active is False
    info = reg.overrides
    assert info["applied"] is True and info["count"] == 3
    assert info["changed"] == ["AR-040", "AR-048", "KR-058"] or set(info["changed"]) == {
        "AR-040",
        "AR-048",
        "KR-058",
    }
    assert len(info["sha256"]) == 64 and info["reason"] == "env"
    assert "changed=3" in params.overrides_summary(info)
    # the seed is untouched and every one of the 132 parameters is still there
    assert len(reg) == len(base) == 132
    assert use("off").get("AR-040").min_value == base.get("AR-040").min_value == 1.2


def test_comparison_rules_follow_the_effective_thresholds(tmp_path: Path, use) -> None:
    base = use("off")
    rows = [
        {"param_code": "AR-040", "min_value": 1.5},
        {"param_code": "AR-048", "max_value": 140},
        {"param_code": "ODI-118", "max_value": 0.02},
        {"param_code": "SPZU-034", "max_value": 0.75},
        {"param_code": "SPZU-038", "min_value": 0.2},
    ]
    reg = use(_write(tmp_path, rows))

    def bounds(r: params.ParamRegistry, code: str) -> list[dict[str, Any]]:
        rule = r.get(code).comparison_rule
        subs = rule.get("sub_checks") or [rule]
        return [s["bounds"] for s in subs if "bounds" in s]

    assert bounds(reg, "AR-040")[0]["min"] == 1.5
    # a conditional bound that is not the matrix threshold (1.0 m for ≤ 50 people) stays as authored
    assert bounds(reg, "AR-040")[0]["conditional"] == bounds(base, "AR-040")[0]["conditional"]
    assert any(b.get("max") == 140.0 for b in bounds(reg, "AR-048"))
    assert bounds(reg, "ODI-118") == [{"max": 0.02}]
    assert reg.get("SPZU-034").comparison_rule["max_distance_m"] == 0.75
    ratio = next(s for s in reg.get("SPZU-038").comparison_rule["sub_checks"] if "min_ratio" in s)
    assert ratio["min_ratio"] == 0.2
    # the base registry keeps the original rule objects
    assert bounds(base, "AR-040")[0]["min"] == "$min_value"
    assert bounds(base, "ODI-118") == [{"max": "$max_value"}]


@pytest.mark.parametrize(
    "rows",
    [
        [{"param_code": "NO-999", "is_active": False}],
        [{"param_code": "AR-040", "min_value": "1.5"}],
        [{"param_code": "AR-040", "min_value": 5, "max_value": 2}],
        [{"param_code": "AR-040", "is_active": "no"}],
        ["AR-040"],
    ],
)
def test_malformed_overrides_are_refused_not_half_applied(tmp_path: Path, use, rows: list[Any]) -> None:
    path = _write(tmp_path, rows)
    with pytest.raises(params.SeedError):
        use(path)


def test_missing_explicit_file_and_bad_json_raise(tmp_path: Path, use) -> None:
    with pytest.raises(params.SeedError):
        use(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(params.SeedError):
        use(bad)


def test_cache_follows_the_file(tmp_path: Path, use) -> None:
    path = _write(tmp_path, [{"param_code": "AR-040", "min_value": 1.6}])
    assert use(path).get("AR-040").min_value == 1.6
    path.write_text(
        json.dumps(
            {"matrix_version": "1.1.1+ovr.4", "overrides": [{"param_code": "AR-040", "min_value": 1.7}]}
        ),
        encoding="utf-8",
    )
    reg = use(path)
    assert reg.get("AR-040").min_value == 1.7 and reg.matrix_version == "1.1.1+ovr.4"


def test_empty_overrides_keep_the_seed_thresholds(tmp_path: Path, use) -> None:
    base = use("off")
    reg = use(_write(tmp_path, [], version="1.1.1"))
    assert reg.overrides["applied"] is False and reg.overrides["count"] == 0
    assert reg.content_sha256 == base.content_sha256
    assert reg.matrix_version == base.matrix_version


def test_custom_seed_directory_never_reads_overrides(tmp_path: Path, use) -> None:
    use(_write(tmp_path, [{"param_code": "AR-040", "min_value": 9}]))
    reg = params.load_params(params.seed_dir())
    assert reg.get("AR-040").min_value == 1.2 and reg.overrides["reason"] == "custom_seed_dir"
