"""The developer CLI (hidden-object refusal, output) and the package data files (rules, vendored templates)."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path

import pytest

from inspector_common.paths import repo_root
from inspector_hypothesis import __main__ as cli
from inspector_hypothesis.testing import OBJECT_ID, tyumen_warm_floor


class _FakeRegistry:
    def __init__(self, hidden: set[str]):
        self.hidden = hidden

    def split_of(self, object_id):
        return "TEST_HIDDEN" if object_id in self.hidden else "TRAIN_PUBLIC"

    def files(self, object_id):
        return []

    def is_citable(self, file_id):
        return True


def test_cli_refuses_the_hidden_object(monkeypatch, tmp_path, capsys):
    import inspector_registry.api

    monkeypatch.setattr(inspector_registry.api, "open_registry", lambda: (_FakeRegistry({"OBJ-Z"}), None))
    assert cli.main([str(tmp_path), "--object", "OBJ-Z"]) == cli.EXIT_REFUSED
    assert "скрытой" in capsys.readouterr().err


def test_cli_prints_a_summary_and_writes_the_result(monkeypatch, tmp_path, capsys):
    import inspector_registry.api
    from inspector_hypothesis import inputs as inputs_mod

    sc = tyumen_warm_floor()
    monkeypatch.setattr(inspector_registry.api, "open_registry", lambda: (_FakeRegistry(set()), None))
    real_from_run = inputs_mod.HypothesisInputs.from_run

    def fake_from_run(run_dir, object_id, **kw):
        base = real_from_run(run_dir, object_id, documents=sc.documents)
        base.pages = sc.pages
        return base

    monkeypatch.setattr(inputs_mod.HypothesisInputs, "from_run", staticmethod(fake_from_run))
    out = tmp_path / "hyp.json"
    assert cli.main([str(tmp_path), "--object", OBJECT_ID, "--out", str(out)]) == cli.EXIT_OK
    summary = json.loads(capsys.readouterr().out)
    assert [g["parameter_code"] for g in summary["free_groups"]] == ["FREE-HEATING-001"]
    full = json.loads(out.read_text(encoding="utf-8"))
    assert full["free_groups"][0]["locations"] == ["267", "270", "271", "272"]


def test_vendored_free_templates_match_the_staging_file():
    doc = json.loads(
        resources.files("inspector_hypothesis")
        .joinpath("data/free_recommendations.json")
        .read_text(encoding="utf-8")
    )
    staging = repo_root() / doc["source"]["path"]
    if not staging.is_file():
        pytest.skip("staging templates not present")
    raw = staging.read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc["source"]["sha256"]:
        # the staging file moved on: the vendored topics must still be identical, else re-vendor them
        assert json.loads(raw)["free_topics"] == doc["free_topics"], (
            "re-vendor data/free_recommendations.json"
        )
    topics = {t["topic"] for t in doc["free_topics"]}
    from inspector_common.contracts.enums import FreeTopic

    missing = {t.value for t in FreeTopic} - topics
    assert missing <= {"OTHER"} and "GENERIC" in topics  # OTHER resolves through the GENERIC template


def test_rule_file_is_utf8_json_with_the_documented_header():
    doc = json.loads(
        resources.files("inspector_hypothesis")
        .joinpath("data/logical_rules.json")
        .read_text(encoding="utf-8")
    )
    assert doc["language"] == "IAI-Logic v1" and doc["owner"] == "AG-07" and len(doc["rules"]) == 12


_DESIGNATION = r"(?:СП|ГОСТ Р|ГОСТ)\s\d+(?:\.\d+)*-?(?:\.\d+)*[.-]\d{2,4}"


def _outdated_designations() -> set[str]:
    """Editions the review-phase norm verification marks as replaced («X заменён Y», «X → 2026», OUTDATED)."""
    import glob
    import re

    out: set[str] = set()
    for path in glob.glob(str(repo_root() / "docs/analysis/norms_staging/norms_*.json")):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        for finding in doc.get("key_findings") or []:
            for m in re.finditer(rf"({_DESIGNATION})\s*(?:заменён|→)", finding):
                out.add(m.group(1))
        for p in doc.get("params") or []:
            for ref in p.get("references") or []:
                if ref.get("status") == "OUTDATED":
                    m = re.match(_DESIGNATION, ref.get("cited") or "")
                    if m:
                        out.add(m.group(0))
    return out


def test_no_rule_or_free_template_cites_an_outdated_edition():
    import re

    outdated = _outdated_designations()
    if not outdated:
        pytest.skip("norm verification staging not present")
    assert "СП 42.13330.2016" in outdated  # the edition HR-LOG-004 cited before the 2026 edition
    from inspector_hypothesis.rules import load_seed_rules

    texts = []
    for r in load_seed_rules().rules:
        texts += [r.normative_base, *r.normative_refs]
    free = json.loads(
        resources.files("inspector_hypothesis").joinpath("data/free_recommendations.json").read_text("utf-8")
    )
    texts += [
        ref.get("designation") or "" for t in free["free_topics"] for ref in t.get("norm_refs_used", [])
    ]
    for text in texts:
        cited = re.sub(rf"взамен\s+{_DESIGNATION}", "", text)  # «взамен ГОСТ Р 21.101-2020» names the old one
        stale = [d for d in outdated if d in cited]
        assert not stale, f"{text!r} cites {stale}"


def test_every_rule_records_its_norm_check():
    from inspector_hypothesis.rules import load_seed_rules

    rules = load_seed_rules().rules
    assert all(r.norm_check is not None for r in rules)
    assert not any(r.verified for r in rules)  # expert review pending (U-18): never claimed
    assert load_seed_rules().get("HR-LOG-004").norm_check.status == "CORRECTED"
    assert "СП 42.13330.2026" in load_seed_rules().get("HR-LOG-004").normative_base
