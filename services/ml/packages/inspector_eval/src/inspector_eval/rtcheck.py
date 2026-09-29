"""RT-01…RT-10: recognition regression checks on the Тюменская run (95 §3.8, ``95_tyumen_dev_fixtures.json``).

The fixture states each check in prose (``recognition_tests[].assert``); this module turns them into machine
checks over the run artifacts, in the contract shapes of ``run_layout.yaml``:

| RT | Reads | Owner |
|---|---|---|
| RT-01 | ``layout/F0201.json`` sheet_page_map, pages 14–34 | AG-02B |
| RT-02, RT-03 | ``tokens/F0201/p00017``, ``p00018`` (OCR of the drawing zones) | AG-02A |
| RT-04 | ``layout/F0202.json`` revision_clouds + rooms, page 17 | AG-02B |
| RT-05 | ``tokens/F0171/p00011`` (ПЗ sentence) | AG-02A |
| RT-06 | ``tokens/F0202/p00001…p00036`` (absence of a warm floor, outlined pages OCRed) | AG-02A |
| RT-07 | ``layout/F0198.json`` qr_links (+ tokens of F0198 p1 and F0202 p17 when present) | AG-02B |
| RT-08 | ``tokens/F0146`` pages 1–31, 147–175 (BROKEN_ENCODING) | AG-02A |
| RT-09 | ``tokens/F0171/p00104`` (supply units in the 012 interval) | AG-02A |
| RT-10 | ``tables/F0195.json``, ``tables/F0196.json`` (АОСР п.2, п.4) | AG-02C |

Each check is PASS, FAIL or NOT_EVALUATED (its artifact is absent: the owner has not produced it yet). Text is
compared after homoglyph folding (Latin look-alikes → Cyrillic), casefolding and dash/space normalisation, so an
OCR «B2.1» matches the printed «В2.1». Zones are the fixture's normalised boxes, widened by ``ZONE_MARGIN``;
a token belongs to a zone when its bbox centre does.

The expected values are the organizers' train fixture (T-GOLD), used as a must-pass regression set (95 §5.1:
recognition unit tests, «learned from T»); nothing here is tuned on any other object.
"""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspector_common.runlayout import RunLayout

ZONE_MARGIN = 0.02  # fixture zones were registered by hand on 110-dpi renders
IOU_MIN = 0.5  # revision-cloud box vs the fixture box

_HOMOGLYPHS = str.maketrans(
    {
        "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
        "X": "Х", "Y": "У", "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    }
)  # fmt: skip
_DASHES = str.maketrans({"–": "-", "—": "-", "‐": "-", "−": "-", " ": " "})


def fold(text: str) -> str:
    """Homoglyph-folded, casefolded, NFC text with unified dashes and single spaces."""
    text = unicodedata.normalize("NFC", str(text)).translate(_DASHES).translate(_HOMOGLYPHS)
    return re.sub(r"\s+", " ", text).strip().casefold().replace("ё", "е")


# ── artifacts ────────────────────────────────────────────────────────────────────────────────


class RunArtifacts:
    """Lazy, cached reader of one run directory's recognition artifacts."""

    def __init__(self, run_dir: Path) -> None:
        self.layout_paths = RunLayout(run_dir)
        self._cache: dict[tuple[str, str, int], Any] = {}

    def _read(self, kind: str, file_id: str, page: int = 0) -> Any:
        key = (kind, file_id, page)
        if key not in self._cache:
            fields: dict[str, Any] = {"file_id": file_id}
            if page:
                fields["page"] = page
            path = self.layout_paths.path(kind, **fields)
            if not path.is_file():
                self._cache[key] = None
            elif path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    self._cache[key] = json.load(fh)
            else:
                self._cache[key] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[key]

    def tokens(self, file_id: str, page: int) -> Mapping[str, Any] | None:
        return self._read("PAGE_TOKENS", file_id, page)

    def layout(self, file_id: str) -> Mapping[str, Any] | None:
        return self._read("LAYOUT", file_id)

    def tables(self, file_id: str) -> Mapping[str, Any] | None:
        return self._read("TABLES", file_id)


def _center(bbox: Sequence[float]) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def _in_zone(bbox: Sequence[float] | None, zone: Sequence[float], margin: float = ZONE_MARGIN) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    cx, cy = _center(bbox)
    return zone[0] - margin <= cx <= zone[2] + margin and zone[1] - margin <= cy <= zone[3] + margin


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def page_text(page: Mapping[str, Any], sources: Iterable[str] | None = None) -> str:
    wanted = set(sources) if sources is not None else None
    parts = [
        str(t.get("text", "")) for t in page.get("tokens", []) if wanted is None or t.get("source") in wanted
    ]
    return " ".join(parts)


def zone_tokens(page: Mapping[str, Any], zone: Sequence[float]) -> list[str]:
    return [fold(t["text"]) for t in page.get("tokens", []) if _in_zone(t.get("bbox"), zone)]


_TAG_PART = re.compile(r"[а-яa-z]+\d+(?:\.\d+)?(?:/[а-яa-z]+)?", re.IGNORECASE)


def tags_in(texts: Iterable[str]) -> set[str]:
    """Tag-like parts of folded tokens («п17.1,» → «п17.1»; «в2.3,4» → «в2.3», «в2.4»; «п2/ве» kept)."""
    out: set[str] = set()
    for text in texts:
        for match in _TAG_PART.finditer(text):
            out.add(match.group(0))
        # enumerations after a tag: «в2.7,8,9» → в2.8, в2.9
        head = re.match(r"([а-я]+\d+\.)(\d+)((?:,\d+)+)$", text)
        if head:
            for n in head.group(3).strip(",").split(","):
                out.add(f"{head.group(1)}{n}")
    return out


# ── results ──────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RTResult:
    rt_id: str
    owner: str
    title_ru: str
    status: str = "PASS"  # PASS | FAIL | NOT_EVALUATED
    details: list[str] = field(default_factory=list)
    measured: dict[str, Any] = field(default_factory=dict)

    def fail(self, detail: str) -> None:
        self.status = "FAIL"
        self.details.append(detail)

    def missing(self, detail: str) -> None:
        if self.status == "PASS":
            self.status = "NOT_EVALUATED"
        self.details.append(detail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.rt_id,
            "owner": self.owner,
            "title_ru": self.title_ru,
            "status": self.status,
            "details": self.details,
            "measured": self.measured,
        }


Check = Callable[[RunArtifacts, RTResult], None]


def _rt01(a: RunArtifacts, r: RTResult) -> None:
    layout = a.layout("F0201")
    if layout is None:
        return r.missing("нет layout/F0201.json")
    # 95 page_facts: stamp = page − 13 up to p28; p29/p30 repeat sheets 14/15; then page − 15 (p32 → 17).
    expected = {p: p - 13 for p in range(14, 29)} | {29: 14, 30: 15} | {p: p - 15 for p in range(31, 35)}
    entries = {
        int(e["pdf_page_number"]): e for e in layout.get("sheet_page_map", []) if "pdf_page_number" in e
    }
    wrong = []
    for page, sheet in expected.items():
        got = entries.get(page, {}).get("sheet_number")
        if str(got).strip() != str(sheet):
            wrong.append(f"с.{page}: {got!r} вместо {sheet}")
    r.measured["pages_ok"] = len(expected) - len(wrong)
    r.measured["pages"] = len(expected)
    if wrong:
        r.fail("номера листов: " + "; ".join(wrong[:8]))
    for dup, orig in ((29, 27), (30, 28)):
        marks = {
            entries.get(dup, {}).get("duplicate_of_page"),
            entries.get(orig, {}).get("duplicate_of_page"),
        }
        if not marks & {orig, dup}:
            r.fail(f"с.{dup} и с.{orig} (лист {expected[dup]}) не отмечены как дубликаты")


def _zone_check(
    a: RunArtifacts, r: RTResult, page_no: int, zone: Sequence[float], expected: Sequence[str]
) -> None:
    page = a.tokens("F0201", page_no)
    if page is None:
        return r.missing(f"нет tokens/F0201/p{page_no:05d}")
    found = tags_in(zone_tokens(page, zone))
    wanted = {fold(t) for t in expected}
    if wanted - found:  # marks the recogniser misread are repaired by the layout stage (closed vocabulary)
        layout = a.layout("F0201")
        if layout is not None:
            found |= tags_in(
                fold(t.get("tag_norm") or "")
                for t in layout.get("tags", [])
                if t.get("pdf_page_number") == page_no and _in_zone(t.get("bbox"), zone)
            )
    missing = sorted(wanted - found)
    r.measured.update(found=len(wanted) - len(missing), expected=len(wanted))
    if missing:
        r.fail(f"в зоне {list(zone)} нет: {', '.join(missing)}")


def _rt02(a: RunArtifacts, r: RTResult) -> None:
    _zone_check(a, r, 17, (0.80, 0.40, 0.96, 0.60), ("П9", "П15", "П17.1", "П18", "В2.1"))


def _rt03(a: RunArtifacts, r: RTResult) -> None:
    _zone_check(
        a, r, 18, (0.83, 0.10, 0.99, 0.32), ("В2.2", "В2.3", "В2.4", "В2.7", "В2.8", "В2.9", "В2.10", "П2/ВЕ")
    )
    page = a.tokens("F0201", 18)
    if page is not None:
        rooms = {fold(t["text"]) for t in page.get("tokens", []) if t.get("source") == "TEXT_LAYER"}
        missing = sorted({"140", "142", "147"} - rooms)
        if missing:
            r.fail(f"номера помещений не из текстового слоя: {', '.join(missing)}")


def _rt04(a: RunArtifacts, r: RTResult) -> None:
    layout = a.layout("F0202")
    if layout is None:
        return r.missing("нет layout/F0202.json")
    target = (0.337, 0.687, 0.423, 0.73)
    clouds = [
        c for c in layout.get("revision_clouds", []) if c.get("pdf_page_number") == 17 and c.get("bbox")
    ]
    best = max(clouds, key=lambda c: _iou(c["bbox"], target), default=None)
    if best is None:
        return r.fail("на с.17 нет облаков изменений")
    iou = _iou(best["bbox"], target)
    r.measured.update(iou=round(iou, 3), layer=best.get("layer"))
    if iou < IOU_MIN:
        r.fail(
            f"облако {best['bbox']} не совпадает с [0.337, 0.687, 0.423, 0.73] (IoU {iou:.2f} < {IOU_MIN})"
        )
    if best.get("layer") and "изм" not in fold(best["layer"]):
        r.fail(f"слой облака «{best['layer']}» не является слоем изменений")
    covered = {fold(x) for x in best.get("rooms_covered") or []}
    covered |= {
        fold(room["room_token"])
        for room in layout.get("rooms", [])
        if room.get("pdf_page_number") == 17 and _in_zone(room.get("bbox"), best["bbox"], 0.0)
    }
    missing = sorted({"270", "272"} - covered)
    if missing:
        r.fail(f"облако не покрывает помещения {', '.join(missing)}")


def _rt05(a: RunArtifacts, r: RTResult) -> None:
    page = a.tokens("F0171", 11)
    if page is None:
        return r.missing("нет tokens/F0171/p00011")
    text = fold(page_text(page))
    for phrase in ("пом. 267, 270, 271, 272", "теплые полы"):
        if fold(phrase) not in text:
            r.fail(f"нет фразы «{phrase}»")


_WARM_FLOOR = re.compile(r"тепл\w*\s+пол|multibox|мультибокс")


def _rt06(a: RunArtifacts, r: RTResult) -> None:
    missing_pages, outlined_without_ocr, hits = [], [], []
    for page_no in range(1, 37):
        page = a.tokens("F0202", page_no)
        if page is None:
            missing_pages.append(page_no)
            continue
        if _WARM_FLOOR.search(fold(page_text(page))):
            hits.append(page_no)
        sources = {t.get("source") for t in page.get("tokens", [])}
        if page.get("page_class") == "VECTOR_OUTLINED_TEXT" and not sources & {"OCR", "OCR_LAYER_ISOLATED"}:
            outlined_without_ocr.append(page_no)
    r.measured.update(pages_read=36 - len(missing_pages), hits=hits)
    if hits:
        r.fail(f"найдено «тёплый пол»/Multibox на с. {hits}")
    if outlined_without_ocr:
        r.fail(f"страницы в кривых без OCR (отсутствие не доказано): {outlined_without_ocr}")
    if missing_pages:
        r.missing(
            f"нет токенов для {len(missing_pages)} из 36 страниц ({missing_pages[:5]}…): отсутствие не доказано"
        )


def _rt07(a: RunArtifacts, r: RTResult) -> None:
    layout = a.layout("F0198")
    if layout is None:
        return r.missing("нет layout/F0198.json")
    links = [q for q in layout.get("qr_links", []) if q.get("pdf_page_number") == 1]
    good = [
        q
        for q in links
        if "87cc1a16" in str(q.get("payload", "")) and str(q.get("doc_page")) == "17"
        and q.get("target_file_id") == "F0202" and q.get("target_pdf_page_number") == 17
    ]  # fmt: skip
    if not good:
        r.fail(f"QR с.1 не ведёт на F0202 с.17 (найдено {len(links)} ссылок)")
    left, right = a.tokens("F0198", 1), a.tokens("F0202", 17)
    if left is not None and right is not None:
        words_l = sorted(fold(t["text"]) for t in left["tokens"] if t.get("source") == "TEXT_LAYER")
        words_r = sorted(fold(t["text"]) for t in right["tokens"] if t.get("source") == "TEXT_LAYER")
        r.measured.update(words_f0198=len(words_l), words_f0202=len(words_r))
        if words_l != words_r:
            r.fail(f"текстовые слои различаются ({len(words_l)} и {len(words_r)} слов)")


def _rt08(a: RunArtifacts, r: RTResult) -> None:
    pages = [*range(1, 32), *range(147, 176)]
    read = [(p, a.tokens("F0146", p)) for p in pages]
    present = [(p, d) for p, d in read if d is not None]
    if not present:
        return r.missing("нет токенов F0146")
    wrong = [p for p, d in present if d.get("page_class") != "BROKEN_ENCODING"]
    r.measured.update(pages_read=len(present), broken_encoding=len(present) - len(wrong))
    if wrong:
        r.fail(f"класс не BROKEN_ENCODING на с. {wrong[:10]}")
    first = dict(present).get(1)
    if first is not None and fold("АНО/150321/1-П-ПЗ1.2") not in fold(page_text(first)):
        r.fail("на с.1 после восстановления/OCR нет шифра «АНО/150321/1-П-ПЗ1.2»")
    if len(present) < len(pages):
        r.missing(f"нет токенов для {len(pages) - len(present)} из {len(pages)} страниц")


def _rt09(a: RunArtifacts, r: RTResult) -> None:
    page = a.tokens("F0171", 104)
    if page is None:
        return r.missing("нет tokens/F0171/p00104")
    expected = {fold(t) for t in ("П2", "П2.1", "П3", "П8", "П9", "П10", "П15", "П17", "П18")}
    found = set()
    for t in page.get("tokens", []):
        text = fold(t["text"])
        if re.fullmatch(r"п\d+(?:\.\d+)?", text) and t.get("bbox"):
            cx, _ = _center(t["bbox"])
            if 0.665 <= cx <= 0.871:
                found.add(text)
    r.measured.update(found=sorted(found))
    if found != expected:
        r.fail(f"лишние {sorted(found - expected)}, не найдены {sorted(expected - found)}")


def _rt10(a: RunArtifacts, r: RTResult) -> None:
    wanted = {
        "F0195": ["АНО/150321/1-РД-ОВ2.1 - изм. 3"],
        "F0196": ["АНО/150321/1-РД-ОВ1 - изм. 3", "АНО1301211-Р-ОВ1"],
    }
    for file_id, phrases in wanted.items():
        tables = a.tables(file_id)
        if tables is None:
            r.missing(f"нет tables/{file_id}.json")
            continue
        aosr = [t for t in tables.get("tables", []) if t.get("table_type") == "AOSR"]
        if not aosr:
            r.fail(f"{file_id}: нет таблицы АОСР")
            continue
        text = fold(
            " ".join(
                str(c.get("raw", ""))
                for t in aosr
                for row in t.get("rows", [])
                for c in row.get("cells", {}).values()
            )
        )
        squeezed = text.replace(" ", "")
        for phrase in phrases:
            if fold(phrase).replace(" ", "") not in squeezed:
                r.fail(f"{file_id}: не найдено «{phrase}»")


RT_CHECKS: tuple[tuple[str, str, str, Check], ...] = (
    ("RT-01", "AG-02B", "Лист по штампу = странице (F0201 с.14–34), дубликаты листов 14/15", _rt01),
    ("RT-02", "AG-02A", "OCR зоны 012 на F0201 с.17: П9, П15, П17.1, П18, В2.1", _rt02),
    ("RT-03", "AG-02A", "OCR зоны 140–198 на F0201 с.18; номера помещений из текстового слоя", _rt03),
    ("RT-04", "AG-02B", "Облако изменений «Изм. №3» над помещениями 270, 272 (F0202 с.17)", _rt04),
    ("RT-05", "AG-02A", "Фраза ПЗ о тёплых полах в пом. 267, 270, 271, 272 (F0171 с.11)", _rt05),
    ("RT-06", "AG-02A", "Отсутствие тёплого пола в РД F0202 доказано (текст + OCR страниц в кривых)", _rt06),
    ("RT-07", "AG-02B", "QR F0198 с.1 = F0202 с.17 (та же страница)", _rt07),
    ("RT-08", "AG-02A", "F0146: страницы с искажённой кодировкой распознаны и восстановлены", _rt08),
    ("RT-09", "AG-02A", "Приточные установки в интервале 012 на F0171 с.104", _rt09),
    ("RT-10", "AG-02C", "АОСР п.2 и п.4 разобраны (F0195, F0196)", _rt10),
)


def run_checks(run_dir: Path, only: Iterable[str] | None = None) -> list[RTResult]:
    artifacts = RunArtifacts(run_dir)
    wanted = set(only) if only else None
    results = []
    for rt_id, owner, title, check in RT_CHECKS:
        if wanted is not None and rt_id not in wanted:
            continue
        result = RTResult(rt_id, owner, title)
        check(artifacts, result)
        results.append(result)
    return results


def summary(results: Sequence[RTResult]) -> dict[str, Any]:
    counts = {s: sum(1 for r in results if r.status == s) for s in ("PASS", "FAIL", "NOT_EVALUATED")}
    status = "FAIL" if counts["FAIL"] else ("NOT_EVALUATED" if counts["NOT_EVALUATED"] else "PASS")
    return {
        "status": status,
        **{k.lower(): v for k, v in counts.items()},
        "checks": [r.as_dict() for r in results],
    }


def render(results: Sequence[RTResult]) -> str:
    mark = {"PASS": "✓", "FAIL": "✗", "NOT_EVALUATED": "—"}
    lines = []
    for r in results:
        lines.append(f"  {mark[r.status]} {r.rt_id} [{r.owner}] {r.title_ru}: {r.status}")
        lines.extend(f"        {d}" for d in r.details[:4])
    return "\n".join(lines)
