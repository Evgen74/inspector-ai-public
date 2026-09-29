from __future__ import annotations

from inspector_registry.duplicates import DupInput, find_duplicates
from inspector_registry.manifest import ManifestFile
from inspector_registry.pdfprobe import normalize_text
from inspector_registry.stages import RULES, collect_signals, resolve_stage
from inspector_registry.twins import link_archive, link_loose, similarity

MIXED = "Объект/Рабочая и исполнительная документация"


def _text(s: str) -> str:
    return normalize_text(s)


# ── stages ───────────────────────────────────────────────────────────────────────────────────


def test_act_in_mixed_folder_resolves_to_id_despite_rd_references() -> None:
    text = _text(
        "АКТ освидетельствования скрытых работ № 3\nв соответствии с рабочей документацией ОБЪ-РД-ОВ1"
    )
    r = resolve_stage("RD_ID_MIXED", f"{MIXED}/Акт №3.pdf", text)
    assert r.stage_resolved == "ID" and r.source == "EXTRACTED_UNCONFIRMED"
    assert r.candidates == ("RD", "ID")
    assert r.confidence is not None and 0.5 < r.confidence < 1


def test_rd_binder_in_mixed_folder_resolves_to_rd() -> None:
    r = resolve_stage(
        "RD_ID_MIXED", f"{MIXED}/Полные разделы/ОБЪ-РД-ОВ1 изм. 4.pdf", _text("РАБОЧАЯ ДОКУМЕНТАЦИЯ")
    )
    assert r.stage_resolved == "RD"


def test_executive_drawing_by_name_only() -> None:
    r = resolve_stage("RD_ID_MIXED", f"{MIXED}/Исполнительный чертеж. План 1 этажа.pdf", None)
    assert r.stage_resolved == "ID"


def test_folder_alone_is_ambiguous() -> None:
    r = resolve_stage("RD_ID_MIXED", f"{MIXED}/Документ 17.pdf", None)
    assert r.stage_resolved is None and r.source is None and r.confidence is None
    assert r.scores["RD"] == r.scores["ID"] > 0


def test_genitive_forms_do_not_vote() -> None:
    # An RD «Общие данные» lists «актов освидетельствования»; an act cites «рабочей документации».
    rd_general_data = _text(
        "Перечень видов работ, для которых необходимо составление актов освидетельствования скрытых работ"
    )
    assert not [s for s in collect_signals("x/y.pdf", rd_general_data) if s.stage == "ID"]
    act_refs = _text("выполнены в соответствии с проектной документацией и рабочей документацией")
    assert not [s for s in collect_signals("x/y.pdf", act_refs) if s.rule.endswith("documentation")]


def test_initial_data_is_pd_not_executive_documentation() -> None:
    r = resolve_stage("UNKNOWN", "Объект/ПД/П-ИД Книга 3 Исходные данные.pdf", None)
    assert r.stage_resolved == "PD" and r.candidates == ("PD", "RD", "ID")
    assert not [s for s in r.signals if s.stage == "ID"]


def test_registry_stage_is_authoritative_and_conflicts_are_reported() -> None:
    same = resolve_stage(
        "ID", "Объект/Исполнительная документация/АОСР №1.pdf", _text("АКТ освидетельствования")
    )
    assert same.stage_resolved == "ID" and same.source == "REGISTRY" and not same.conflict
    clash = resolve_stage(
        "PD",
        "Объект/Исполнительная документация/АОСР №1.pdf",
        _text("АКТ освидетельствования скрытых работ\nИсполнительная схема"),
    )
    assert clash.stage_resolved == "PD" and clash.signals_stage == "ID" and clash.conflict


def test_skip_reason_reads_nothing() -> None:
    r = resolve_stage(
        "UNKNOWN", "Объект/Перечень.txt", "акт освидетельствования", skip_reason="служебный файл"
    )
    assert r.stage_resolved is None and r.signals == [] and r.skipped_reason == "служебный файл"


def test_redaction_drops_matched_text() -> None:
    r = resolve_stage("RD_ID_MIXED", f"{MIXED}/Акт.pdf", _text("АКТ освидетельствования скрытых работ"))
    assert any("match" in s for s in r.to_json()["signals"])
    assert not any("match" in s for s in r.to_json(redact=True)["signals"])


def test_rule_ids_are_unique() -> None:
    assert len({r.rule_id for r in RULES}) == len(RULES)


# ── twins ────────────────────────────────────────────────────────────────────────────────────


def _mf(file_id: str, rel: str, pages: int | None = None) -> ManifestFile:
    ext = "." + rel.rsplit(".", 1)[-1].lower()
    return ManifestFile(
        row_no=int(file_id[1:]),
        file_id=file_id,
        object_id="OBJ",
        corpus="c",
        dataset_role="UNLABELED_POOL",
        split="TRAIN_PUBLIC",
        relative_path=rel,
        extension=ext,
        size_bytes=1,
        sha256="0" * 64,
        stage="RD",
        section="OTHER",
        pdf_pages=pages if ext == ".pdf" else None,
        annotation_status="UNLABELED",
        exclusion_reason=None,
        duplicate_group=None,
        distribution_status="INCLUDE",
        label_visibility="PUBLIC_TRAIN",
        raw={},
    )


def test_loose_dwg_exact_twin() -> None:
    files = [
        _mf("F0001", "РД/АР/АР-5.dwg"),
        _mf("F0002", "РД/АР/АР-5.pdf", 3),
        _mf("F0003", "РД/АР/АР-6.pdf", 3),
    ]
    link = link_loose(files[0], files)
    assert link is not None and link.file_id == "F0002" and link.confidence == 0.98
    assert link.basis["keys_equal"] is True and link.basis["sheet_number"] == 5


def test_twin_must_be_in_the_same_folder() -> None:
    files = [_mf("F0001", "РД/АР/АР-5.dwg"), _mf("F0002", "РД/КЖ/АР-5.pdf", 3)]
    assert link_loose(files[0], files) is None


def test_only_pdf_in_folder_is_a_weak_twin() -> None:
    files = [_mf("F0001", "РД/АР/Чертёж.dwg"), _mf("F0002", "РД/АР/Комплект.pdf", 3)]
    link = link_loose(files[0], files)
    assert link is not None and link.confidence == 0.5 and link.basis["only_pdf_in_folder"]


def test_ambiguous_candidates_lower_confidence() -> None:
    files = [
        _mf("F0001", "РД/ЭОМ/ЭОМ-1.docx"),
        _mf("F0002", "РД/ЭОМ/ЭОМ-1 ЭМ.pdf", 3),
        _mf("F0003", "РД/ЭОМ/ЭОМ-1 ЭО.pdf", 3),
    ]
    link = link_loose(files[0], files)
    assert link is not None and "ambiguous_with" in link.basis
    assert link.confidence < 0.9


def test_archive_twin_with_page_hints() -> None:
    files = [_mf("F0001", "РД/КЖ1/ОБЪ-РД-КЖ1.zip"), _mf("F0002", "РД/КЖ1/ОБЪ-РД-КЖ1.pdf", 5)]
    members = {0: "КЖ1/ОБЪ-РД-КЖ1 Лист 1.dwg", 1: "КЖ1/ОБЪ-РД-КЖ1 Лист 2.dwg", 2: "КЖ1/ОБЪ-РД-КЖ1 Лист 3.dwg"}
    twins = link_archive(files[0], members, files, {"F0002": 5})
    assert twins.archive_link is not None and twins.archive_link.file_id == "F0002"
    assert twins.archive_link.confidence == 0.99 and twins.page_offset == 2
    assert [twins.members[i].page_hint for i in range(3)] == [3, 4, 5]
    assert all(twins.members[i].sheet_explicit for i in range(3))


def test_archive_without_consistent_sheets_gives_no_page_hints() -> None:
    files = [_mf("F0001", "РД/КЖ1/КЖ1.zip"), _mf("F0002", "РД/КЖ1/КЖ1.pdf", 4)]
    members = {0: "Лист 1.dwg", 1: "Лист 1 (копия).dwg", 2: "Узлы.dwg"}
    twins = link_archive(files[0], members, files, {"F0002": 4})
    assert twins.archive_link is not None
    assert twins.page_offset is None and all(m.page_hint is None for m in twins.members.values())


def test_more_drawings_than_pages_lowers_confidence() -> None:
    files = [_mf("F0001", "РД/КЖ1/КЖ1.zip"), _mf("F0002", "РД/КЖ1/КЖ1.pdf", 2)]
    members = {i: f"Лист {i + 1}.dwg" for i in range(5)}
    twins = link_archive(files[0], members, files, {"F0002": 2})
    assert twins.archive_link is not None and twins.archive_link.confidence == 0.88


def test_similarity_is_symmetric_and_bounded() -> None:
    a, b = "ОБЪ-РД-КЖ1 изм.2.pdf", "ОБЪ_РД_КЖ1.dwg"
    assert similarity(a, b) == similarity(b, a)
    assert 0 <= similarity(a, b) <= 100


# ── duplicates ───────────────────────────────────────────────────────────────────────────────


def test_exact_near_and_first_page_matches() -> None:
    items = [
        DupInput("F0001", "a" * 64, 10, "t1", None),
        DupInput("F0002", "a" * 64, 10, "t1", None),  # exact copy of F0001
        DupInput("F0003", "b" * 64, 10, "t1", None),  # same pages + first page → near
        DupInput("F0004", "c" * 64, 12, "t1", None),  # same first page, other length → hint
        DupInput("F0005", "d" * 64, 3, None, "i1"),  # scans: image fingerprint
        DupInput("F0006", "e" * 64, 3, None, "i1"),
        DupInput("F0007", "f" * 64, None, None, None),
    ]
    out = find_duplicates(items)
    assert out["exact"] == [{"sha256": "a" * 64, "file_ids": ["F0001", "F0002"]}]
    near = {tuple(g["file_ids"]): g["basis"] for g in out["near"]}
    assert near == {("F0001", "F0002", "F0003"): "text", ("F0005", "F0006"): "image"}
    assert [f["file_id"] for f in out["first_page_matches"][0]["files"]] == [
        "F0001",
        "F0002",
        "F0003",
        "F0004",
    ]


def test_exact_duplicates_alone_are_not_near_duplicates() -> None:
    items = [DupInput("F0001", "a" * 64, 2, "t", None), DupInput("F0002", "a" * 64, 2, "t", None)]
    out = find_duplicates(items)
    assert len(out["exact"]) == 1 and out["near"] == []
