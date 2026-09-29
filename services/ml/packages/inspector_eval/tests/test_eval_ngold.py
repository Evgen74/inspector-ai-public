"""N-GOLD labelling tooling: format 2, blind packets, adjudication, spot-check sample/import, freeze."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from inspector_common.contracts.loader import load_enums
from inspector_common.errors import InspectorError
from inspector_common.settings import Settings
from inspector_eval import cli, devset, ngold
from inspector_eval.data import InputError
from inspector_eval.scoring import is_approved_checkpoint

AT1, AT2, AT3 = "2026-09-28T10:00:00Z", "2026-09-28T11:00:00Z", "2026-09-28T12:00:00Z"


def _item(item_id: str, code: str = "KR-055", **extra) -> dict:
    return {
        "id": item_id,
        "parameter_code": code,
        "location": extra.pop("location", "БСС-1н в/о 4-2.8/А-Х1"),
        "pd_value": "В15 П4 F200 W8",
        "rd_value": "В15, F200, W8",
        "id_value": "БСТ В15 П4 F150 W8",
        "evidence": [
            {"stage": "PD", "file_id": "F0005", "pdf_page_number": 1},
            {"stage": "RD", "file_id": "F0006", "pdf_page_number": 2},
        ],
        "system_hypothesis": "SECRET-HYPOTHESIS",
        "why_interesting": "SECRET-WHY",
        "label": None,
        "label_comment": None,
        **extra,
    }


def _seed(n: int = 3) -> dict:
    return {"meta": {"purpose": "test"}, "candidates": [_item(f"NS-C{i:02d}") for i in range(1, n + 1)]}


def _note(label: str, labeller: str = "agent-1", kind: str = "AGENT", at: str = AT1, **extra) -> dict:
    return {"labeller": labeller, "labeller_kind": kind, "label": label, "labelled_at": at, **extra}


@pytest.fixture()
def doc() -> dict:
    return ngold.upgrade(_seed(), "OBJ-B")


# ── format ───────────────────────────────────────────────────────────────────────────────────


def test_label_vocabulary_is_pinned_to_the_contract() -> None:
    assert list(ngold.vocabulary("Label")) == [*load_enums()["ViolationLabel"].codes, "UNSURE"]
    assert ngold.label_values() == ngold.vocabulary("Label")
    assert "TEAM_LABEL_FROZEN" in load_enums()["GoldStatus"].codes
    assert devset.TEAM_LABEL_FROZEN == "TEAM_LABEL_FROZEN"


def test_upgrade_keeps_seed_fields_and_is_idempotent(doc) -> None:
    assert doc["meta"]["format_version"] == 2 and doc["meta"]["object_id"] == "OBJ-B"
    first = doc["candidates"][0]
    assert first["source"] == "SEED" and first["scorable"] is True and first["annotations"] == []
    assert first["system_hypothesis"] == "SECRET-HYPOTHESIS"
    assert ngold.upgrade(doc) == doc
    ngold.validate_label_set(doc)


def test_the_package_seed_upgrades_and_validates() -> None:
    from inspector_common.paths import repo_root

    seed = json.loads((repo_root() / "docs/analysis/95_novoslob_label_seed.json").read_text(encoding="utf-8"))
    upgraded = ngold.upgrade(seed, "OBJ-NOVOSLOBODSKAYA")
    ngold.validate_label_set(upgraded)
    assert len(upgraded["candidates"]) == 14


def test_the_package_label_file_validates() -> None:
    path = devset.DEVSET_DIR / "n_gold_novoslob_v1.json"
    document = ngold.load_label_set(path)
    assert document["meta"]["object_id"] == "OBJ-NOVOSLOBODSKAYA"
    labelled = [i for i in document["candidates"] if i.get("annotations")]
    # every recorded annotation carries its reasoning and the pages it was based on (protocol §3)
    for item in labelled:
        for note in item["annotations"]:
            assert note.get("reasoning") and "labelled_at" in note
            if note["labeller_kind"] == "AGENT" and item.get("evidence"):
                assert note.get("pages_viewed"), item["id"]


def test_schema_rejects_bad_labels_and_duplicates(doc) -> None:
    bad = copy.deepcopy(doc)
    bad["candidates"][0]["label"] = "MAYBE"
    with pytest.raises(InputError):
        ngold.validate_label_set(bad)
    dup = copy.deepcopy(doc)
    dup["candidates"][1]["id"] = dup["candidates"][0]["id"]
    with pytest.raises(InputError, match="повторяются"):
        ngold.validate_label_set(dup)


# ── blind packets ────────────────────────────────────────────────────────────────────────────


def test_blind_question_never_leaks_system_outputs(doc, ctx) -> None:
    item = doc["candidates"][0]
    ngold.record(doc, item["id"], _note("NO_VIOLATION", reasoning="SECRET-REASONING"))
    question = ngold.blind_question(item, ctx)
    text = json.dumps({k: v for k, v in question.items() if k != "labels"}, ensure_ascii=False)
    for secret in ("SECRET-HYPOTHESIS", "SECRET-WHY", "SECRET-REASONING", "В15", "NO_VIOLATION"):
        assert secret not in text
    assert question["labels"] == list(ngold.label_values())  # the vocabulary, not the item's label
    assert not set(ngold.BLIND_HIDDEN_FIELDS) & set(question)
    assert question["catalog"]["criticality"] == "Критическое (приостановка работ)"
    assert [p["file_id"] for p in question["pages_to_start_from"]] == ["F0005", "F0006"]


def test_render_packet_with_a_stub_source(doc, ctx, tmp_path) -> None:
    import pymupdf

    pdf_path = tmp_path / "src.pdf"
    with pymupdf.open() as pdf:
        for n in range(3):
            page = pdf.new_page(width=300, height=200)
            page.insert_text((20, 50), f"page {n + 1} Бетон B25")
        pdf.save(pdf_path)
    source = SimpleNamespace(object_id="OBJ-B", path=lambda file_id: pdf_path)
    out = tmp_path / "packet"
    packet = ngold.render_packet(
        doc["candidates"][0],
        out,
        source,
        ctx,
        dpi=40,
        tiles="2x1",
        tile_dpi=50,
        extra=["F0005:3:0,0,0.5,0.5"],
    )
    names = sorted(p.name for p in out.iterdir())
    assert "question.json" in names and "F0005_p0001.png" in names and "F0005_p0001_t12.png" in names
    assert "F0005_p0003_clip_0_0_0.5_0.5.png" in names
    assert "page 1" in (out / "F0005_p0001.txt").read_text(encoding="utf-8")
    written = json.loads((out / "question.json").read_text(encoding="utf-8"))
    assert written["question"]["object_id"] == "OBJ-B" and "SECRET" not in json.dumps(written)
    assert len(packet["rendered"]) == 3
    with pytest.raises(InputError, match="страницы 9"):
        ngold.render_packet(doc["candidates"][0], out, source, ctx, extra=["F0005:9"])


@pytest.mark.parametrize("bad", ["F0005", "F0005:1:0,0,2,1", "F0005:1:0.5,0,0.5,1"])
def test_page_request_parse_rejects_bad_input(bad) -> None:
    with pytest.raises(ValueError):
        ngold.PageRequest.parse(bad)


def test_page_source_refuses_a_hidden_object(ctx) -> None:
    with pytest.raises(InspectorError) as err:
        ngold.PageSource("OBJ-Z", ctx)
    assert err.value.code == "HIDDEN_TEST_ACCESS_DENIED"


# ── adjudication ─────────────────────────────────────────────────────────────────────────────


def test_single_agent_label_adopts_corrections_and_keeps_the_seed(doc) -> None:
    item = ngold.record(
        doc,
        "NS-C01",
        _note("NO_VIOLATION", location="БСС-1н в/о 4-2.8/А.1-Х1", id_value=None, reasoning="class unchanged"),
    )
    assert item["label"] == "NO_VIOLATION" and item["adjudication"]["method"] == "SINGLE"
    assert item["location"] == "БСС-1н в/о 4-2.8/А.1-Х1" and item["id_value"] is None  # explicit null adopted
    assert item["seed_original"] == {"location": "БСС-1н в/о 4-2.8/А-Х1", "id_value": "БСТ В15 П4 F150 W8"}
    assert item["label_comment"] == "class unchanged"


def test_agents_agree_then_a_human_overrides(doc) -> None:
    ngold.record(doc, "NS-C01", _note("NO_VIOLATION", "agent-1", at=AT1))
    item = ngold.record(doc, "NS-C01", _note("NO_VIOLATION", "agent-2", at=AT2))
    assert item["adjudication"]["method"] == "AGREEMENT" and not item["adjudication"]["disagreement"]
    item = ngold.record(
        doc, "NS-C01", _note("VIOLATION_PRESENT", "user", "HUMAN", at=AT3, parameter_code="KR-057")
    )
    assert item["label"] == "VIOLATION_PRESENT" and item["parameter_code"] == "KR-057"
    assert item["adjudication"] == {
        "method": "HUMAN_PRECEDENCE",
        "decided_by": "user",
        "labellers": ["agent-1", "agent-2", "user"],
        "disagreement": True,
    }


def test_disagreeing_agents_are_unresolved_and_the_latest_note_of_a_labeller_counts(doc) -> None:
    ngold.record(doc, "NS-C02", _note("NO_VIOLATION", "agent-1", at=AT1))
    item = ngold.record(doc, "NS-C02", _note("VIOLATION_PRESENT", "agent-2", at=AT2))
    assert item["label"] == "UNSURE" and item["adjudication"]["method"] == "UNRESOLVED"
    item = ngold.record(
        doc, "NS-C02", _note("VIOLATION_PRESENT", "agent-1", at=AT3)
    )  # agent-1 changes its mind
    assert item["label"] == "VIOLATION_PRESENT" and item["adjudication"]["method"] == "AGREEMENT"
    assert item["adjudication"]["disagreement"] is False


def test_record_validates_its_input(doc) -> None:
    with pytest.raises(InputError, match="недопустимая метка"):
        ngold.record(doc, "NS-C01", _note("MAYBE"))
    with pytest.raises(InputError, match="нет полей"):
        ngold.record(doc, "NS-C01", {"label": "NO_VIOLATION"})
    with pytest.raises(InputError, match="не найден"):
        ngold.record(doc, "NS-C99", _note("NO_VIOLATION"))


def test_not_scorable_items_are_listed_not_scored(doc, tmp_path, paths, ctx) -> None:
    ngold.record(doc, "NS-C01", _note("NO_VIOLATION"))
    ngold.record(doc, "NS-C02", _note("NO_VIOLATION", scorable=False))
    ngold.record(doc, "NS-C03", _note("UNSURE"))
    registry, _ = _registry_with(tmp_path, doc)
    rows = devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    assert [r["check_id"] for r in rows.gold_rows] == ["NS-C01"]
    assert [e["id"] for e in rows.excluded] == ["NS-C02", "NS-C03"]
    summary = ngold.status(doc, {"A": ["KR"], "B": ["*"]})
    assert summary["scorable"] == 2 and summary["not_scorable"] == ["NS-C02"]
    assert summary["by_label"] == {"NO_VIOLATION": 1, "UNSURE": 1} and summary["by_fold"] == {"A": 2}


# ── spot-check sample, export and import ─────────────────────────────────────────────────────


def _big_doc(n: int = 60) -> dict:
    items = []
    labels = ["NO_VIOLATION"] * 36 + ["VIOLATION_PRESENT"] * 12 + ["MISSING_DOCUMENT"] * 9 + ["UNSURE"] * 3
    for i in range(n):
        code = "KR-055" if i % 2 else "PZ-001"
        item = _item(f"NS-X{i:03d}", code)
        item["label"] = labels[i]
        items.append(item)
    return ngold.upgrade({"meta": {}, "candidates": items}, "OBJ-B")


def test_sample_is_deterministic_sized_and_covers_every_stratum() -> None:
    document = _big_doc()
    folds = {"A": ["KR"], "B": ["*"]}
    first = ngold.sample_ids(document, 28, seed=7, folds=folds)
    assert first == ngold.sample_ids(document, 28, seed=7, folds=folds)
    assert first != ngold.sample_ids(document, 28, seed=8, folds=folds)
    assert len(first) == 28 and len(set(first)) == 28
    chosen = [i for i in document["candidates"] if i["id"] in first]
    assert {i["label"] for i in chosen} == {"NO_VIOLATION", "VIOLATION_PRESENT", "MISSING_DOCUMENT", "UNSURE"}
    by_label = {
        lab: sum(1 for i in chosen if i["label"] == lab) for lab in ("NO_VIOLATION", "VIOLATION_PRESENT")
    }
    assert 14 <= by_label["NO_VIOLATION"] <= 19 and 4 <= by_label["VIOLATION_PRESENT"] <= 7  # ≈ proportional
    assert ngold.sample_ids(_seed_doc_small(), 28, seed=1) == ["NS-C01", "NS-C02", "NS-C03"]  # small set: all
    with pytest.raises(ValueError):
        ngold.sample_ids(document, 0, seed=1)


def _seed_doc_small() -> dict:
    return ngold.upgrade(_seed(), "OBJ-B")


def test_export_and_import_spotcheck(doc, ctx, tmp_path) -> None:
    for item_id, label in (
        ("NS-C01", "NO_VIOLATION"),
        ("NS-C02", "NO_VIOLATION"),
        ("NS-C03", "VIOLATION_PRESENT"),
    ):
        ngold.record(doc, item_id, _note(label, reasoning=f"agent says {label}"))
    out = tmp_path / "spot"
    written = ngold.export_spotcheck(doc, ["NS-C01", "NS-C02", "NS-C03"], out, ctx, seed=5)
    sheet_text = written["sheet"].read_text(encoding="utf-8-sig")
    assert "agent says" not in sheet_text and "SECRET" not in sheet_text  # the sheet is blind
    assert "agent says NO_VIOLATION" in written["key"].read_text(encoding="utf-8")
    assert "NS-C03" in written["index"].read_text(encoding="utf-8")
    rows = list(csv.DictReader(sheet_text.splitlines()))
    assert list(rows[0]) == list(ngold.SPOTCHECK_COLUMNS)
    rows[0]["user_label"] = "no_violation"
    rows[1]["user_label"] = "VIOLATION_PRESENT"
    rows[1]["user_comment"] = "F150 < F200"
    rows[2]["user_label"] = ""  # skipped
    with written["sheet"].open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ngold.SPOTCHECK_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    added, agr = ngold.import_spotcheck(doc, written["sheet"], labeller="user", labelled_at=AT3)
    assert added == 2 and agr.n == 2 and agr.agree == 1
    assert agr.as_dict()["disagreements"] == [
        {"id": "NS-C02", "agent": "NO_VIOLATION", "human": "VIOLATION_PRESENT"}
    ]
    item = ngold.item_by_id(doc, "NS-C02")
    assert item["label"] == "VIOLATION_PRESENT" and item["adjudication"]["method"] == "HUMAN_PRECEDENCE"
    assert item["label_comment"] == "F150 < F200"
    rows[0]["user_label"] = "PERHAPS"
    with written["sheet"].open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ngold.SPOTCHECK_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(InputError, match="недопустимая метка"):
        ngold.import_spotcheck(doc, written["sheet"], labeller="user", labelled_at=AT3)


def test_cohen_kappa_values() -> None:
    assert ngold.cohen_kappa([]) is None
    assert ngold.cohen_kappa([("A", "A"), ("B", "B")]) == pytest.approx(1.0)
    assert ngold.cohen_kappa([("A", "A"), ("A", "A")]) == pytest.approx(1.0)
    # 2x2: agree 7/10, marginals A 5/5 vs 6/4 → pe = 0.5·0.6 + 0.5·0.4 = 0.5, κ = 0.4
    pairs = [("A", "A")] * 4 + [("A", "B")] + [("B", "A")] * 2 + [("B", "B")] * 3
    assert ngold.cohen_kappa(pairs) == pytest.approx(0.4)


# ── freeze ───────────────────────────────────────────────────────────────────────────────────


def _registry_with(tmp_path: Path, document: dict) -> tuple[Path, Path]:
    labels = tmp_path / "labels.json"
    ngold.save_label_set(labels, document)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "devsets": [
                    {
                        "id": "N-TEST",
                        "object_id": "OBJ-B",
                        "split": "TRAIN_PUBLIC",
                        "format": "label_seed_json",
                        "path": {"base": "repo", "relative": str(labels)},
                        "badge_ru": "Разметка команды",
                        "frozen": False,
                        "labels_sha256": None,
                        "folds": {"A": ["KR"], "B": ["*"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, labels


@pytest.fixture()
def paths(fake_data_root: Path):
    return Settings(data_root=fake_data_root).paths


def test_freeze_pins_labels_and_file_and_marks_rows(doc, tmp_path, paths, ctx) -> None:
    ngold.record(doc, "NS-C01", _note("VIOLATION_PRESENT"))
    ngold.record(doc, "NS-C02", _note("NO_VIOLATION"))
    registry, labels = _registry_with(tmp_path, doc)
    digest = devset.freeze("N-TEST", paths, ctx, registry, now=AT3)
    entry = json.loads(registry.read_text(encoding="utf-8"))["devsets"][0]
    assert entry["frozen"] and entry["labels_sha256"] == digest and len(entry["file_sha256"]) == 64
    rows = devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    assert rows.hash_ok and rows.file_hash_ok
    assert {r["gold_status"] for r in rows.gold_rows} == {"TEAM_LABEL_FROZEN"}
    positive = next(r for r in rows.gold_rows if r["violation_label"] == "VIOLATION_PRESENT")
    assert is_approved_checkpoint(positive)  # frozen team labels simulate the gate
    assert not is_approved_checkpoint({**positive, "gold_status": "DRAFT"})
    # a write through the tool is refused; a manual edit of an unscored item breaks the file hash
    with pytest.raises(InspectorError):
        ngold.save_label_set(labels, doc, frozen=True)
    edited = json.loads(labels.read_text(encoding="utf-8"))
    edited["candidates"][2]["label_comment"] = "edited after the freeze"
    labels.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InspectorError) as err:
        devset.load_devset(devset.get_devset("N-TEST", registry), paths, ctx)
    assert err.value.code == "TEST_SET_HASH_MISMATCH"


def test_freeze_refuses_unresolved_items(doc, tmp_path, paths, ctx) -> None:
    ngold.record(doc, "NS-C01", _note("NO_VIOLATION", "agent-1", at=AT1))
    ngold.record(doc, "NS-C01", _note("VIOLATION_PRESENT", "agent-2", at=AT2))
    ngold.record(doc, "NS-C02", _note("NO_VIOLATION"))
    registry, _ = _registry_with(tmp_path, doc)
    with pytest.raises(InputError, match="спорные"):
        devset.freeze("N-TEST", paths, ctx, registry, now=AT3)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def test_cli_init_record_status_sample_import(fake_data_root, tmp_path, capsys) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(_seed(), ensure_ascii=False), encoding="utf-8")
    registry, labels = _registry_with(tmp_path, ngold.upgrade({"meta": {}}, "OBJ-B"))
    common = ["--devset", "N-TEST", "--registry", str(registry), "--data-root", str(fake_data_root)]

    assert cli.main(["ngold", "init", "--seed", str(seed), *common]) == 0
    assert cli.main(["ngold", "init", "--seed", str(seed), *common]) == 0  # idempotent: nothing added twice
    assert len(ngold.load_label_set(labels)["candidates"]) == 3
    capsys.readouterr()

    code = cli.main(
        [
            "ngold",
            "record",
            "NS-C01",
            "--label",
            "NO_VIOLATION",
            "--labeller",
            "agent-x",
            "--confidence",
            "HIGH",
            "--reasoning",
            "В15 everywhere",
            "--evidence",
            "PD:F0005:1",
            "ID:F0003:2",
            "--id-value",
            "null",
            "--pages-viewed",
            "F0005:1",
            *common,
        ]
    )
    assert code == 0 and "NS-C01: метка NO_VIOLATION" in capsys.readouterr().out
    item = ngold.item_by_id(ngold.load_label_set(labels), "NS-C01")
    assert item["id_value"] is None and item["evidence"][1] == {
        "stage": "ID",
        "file_id": "F0003",
        "pdf_page_number": 2,
    }
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps([{"id": i, "annotation": _note("NO_VIOLATION", "agent-x")} for i in ("NS-C02", "NS-C03")]),
        encoding="utf-8",
    )
    assert cli.main(["ngold", "record", "--json", str(batch), *common]) == 0
    capsys.readouterr()

    assert cli.main(["ngold", "status", "--json", *common]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["by_label"] == {"NO_VIOLATION": 3} and summary["annotated_by_kind"] == {"AGENT": 3}
    assert len(summary["file_sha256"]) == 64 and summary["frozen"] is False

    out = tmp_path / "spot"
    assert cli.main(["ngold", "sample", "--n", "25", "--out", str(out), "--no-images", *common]) == 0
    assert "выгружены все" in capsys.readouterr().out
    assert cli.main(["ngold", "sample", "--n", "5", "--out", str(out), "--no-images", *common]) == 2  # 25…30
    sheet = out / "sheet.csv"
    rows = list(csv.DictReader(sheet.read_text(encoding="utf-8-sig").splitlines()))
    for r in rows:
        r["user_label"] = "NO_VIOLATION"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ngold.SPOTCHECK_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    capsys.readouterr()
    assert cli.main(["ngold", "import-spotcheck", str(sheet), "--labeller", "user", *common]) == 0
    assert "3/3" in capsys.readouterr().out


def test_cli_ngold_refuses_writes_to_a_frozen_set(fake_data_root, tmp_path, capsys, paths, ctx) -> None:
    document = ngold.upgrade(_seed(), "OBJ-B")
    ngold.record(document, "NS-C01", _note("NO_VIOLATION"))
    registry, _ = _registry_with(tmp_path, document)
    raw = json.loads(registry.read_text(encoding="utf-8"))
    raw["devsets"][0].update(frozen=True, labels_sha256="0" * 64)
    registry.write_text(json.dumps(raw), encoding="utf-8")
    common = ["--devset", "N-TEST", "--registry", str(registry), "--data-root", str(fake_data_root)]
    code = cli.main(["ngold", "record", "NS-C02", "--label", "NO_VIOLATION", "--labeller", "x", *common])
    assert code == 1 and "Изменён тестовый набор" in capsys.readouterr().err


@pytest.mark.data
def test_packet_of_a_real_item_is_blind(real_ctx, tmp_path) -> None:
    document = ngold.load_label_set(devset.DEVSET_DIR / "n_gold_novoslob_v1.json")
    item = ngold.item_by_id(document, "NS-C07")
    source = ngold.PageSource("OBJ-NOVOSLOBODSKAYA", real_ctx)
    packet = ngold.render_packet(item, tmp_path / "p", source, real_ctx, dpi=30)
    assert {r["file_id"] for r in packet["rendered"]} >= {"F0101", "F0137"}
    written = json.loads((tmp_path / "p" / "question.json").read_text(encoding="utf-8"))
    question = {k: v for k, v in written["question"].items() if k != "labels"}
    text = json.dumps(question, ensure_ascii=False)
    assert "system_hypothesis" not in text and "annotations" not in text and "NO_VIOLATION" not in text
    assert "159,95" not in text  # the item's values are not in the question
    assert "159,95" in (tmp_path / "p" / "F0101_p0013.txt").read_text(encoding="utf-8")
