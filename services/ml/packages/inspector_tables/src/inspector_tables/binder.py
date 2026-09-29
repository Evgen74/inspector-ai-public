"""ИД binder typing (96 R-09, 97 §2.13 F6 «binder segmentation»): page kind from the header band.

An ИД file is a binder of logical documents: the act (АОСР), its «Реестр приложений», executive schemes,
then scanned quality documents, test protocols and certificates, each scan followed by a «КОПИЯ ВЕРНА»
stamp page (95 §4.1). M1 types every page from its header band (top 30 % of the text, then the title-block
zone for drawings) and cuts segments where the kind changes or a new title starts; the registry
(:mod:`inspector_tables.registry`) is the table of contents a later step (M2) reconciles against.

Kinds are AG-03's seed ``doc_kind`` codes where one exists (AOSR, ISP_GEO_SCHEME, QUALITY_DOCS,
LAB_OR_MEASUREMENT, AKT_ISPYTANIY, JOURNAL_OZHR…) plus ID_REGISTRY (TableType) and STAMP_PAGE (PageClass);
UNREAD marks a scan without OCR tokens (typing needs text), UNKNOWN a read page nothing matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inspector_tables.pagesource import PageData
from inspector_tables.text import fold, group_lines

# (kind, regex on the folded, space-free header band) — first match wins. Space-free because OCR of a two-line
# title interleaves its words («ЗАДАННОГОДОКУМЕНТКАЧЕСТВАО КАЧЕСТВЕ»).
HEADER_RULES: tuple[tuple[str, str], ...] = (
    ("ID_REGISTRY", r"^.{0,40}реестр(приложени|исполнительн|документ)"),
    ("AOSR", r"актосвидетельствовани\w{0,4}скрыт"),
    ("AKT_ISPYTANIY", r"акт\w{0,4}(гидравлическ|испытани|промывк|продувк|приемк)"),
    (
        "LAB_OR_MEASUREMENT",
        r"протокол\w{0,4}(испытани|лабораторн|контрол|измерени|№)|заключени\w{0,4}(лаборатор|порезультат)"
        r"|результат\w{0,4}испытани|визуальногоиизмерительногоконтрол",
    ),
    (
        "QUALITY_DOCS",
        r"документ.{0,24}качеств|паспорт(?!ныеданн)|сертификат.{0,12}соответстви|декларац.{0,12}соответстви"
        r"|свидетельств\w{0,4}оприемк",
    ),
    ("ISP_GEO_SCHEME", r"исполнительн\w{0,4}(геодезическ\w{0,4})?(схем|чертеж|съемк)"),
    ("JOURNAL_OZHR", r"общ\w{0,4}журнал|журнал\w{0,4}(бетонных|сварочн|входного|работ)"),
    ("CONTRACT", r"^.{0,60}договор\w{0,4}(№|возмездн|оказани|подряд|поставк)"),
)
# a contract's later pages carry no title: its clause vocabulary identifies them
CONTRACT_BODY = re.compile(
    r"обязанност\w{0,4}сторон|стоимост\w{0,4}услуг|порядок\w{0,4}расчет|заказчик\w{0,4}обязу|исполнитель\w{0,4}обязу"
    r"|настоящ\w{0,4}договор|сторон\w{0,4}договор|ответственност\w{0,4}сторон"
)
SIGNATURES = re.compile(r"подписанэлектроннойподпись|представитель(лица|застройщик)|[a-z_]+\$[0-9a-f]{8}")
STAMP = re.compile(r"копияверна")
AOSR_BODY = re.compile(
    r"работывыполненыпопроектнойдокументации|привыполненииработприменены|предъявленыдокументы"
    r"|разрешаетсяпроизводствопоследующихработ|работывыполненывсоответствиис|дополнительныесведения"
)
MIN_TEXT = 25


def _ns(text: str) -> str:
    return fold(text).replace(" ", "")


@dataclass(slots=True)
class PageKind:
    page_no: int
    kind: str
    title: str
    source: str  # TEXT_LAYER | TOKENS | NONE
    confidence: float


@dataclass(slots=True)
class Segment:
    kind: str
    start: int
    end: int
    title: str
    pages: list[int] = field(default_factory=list)


def classify_page(
    page: PageData | None, page_no: int, has_text: bool, raw_text: str | None = None
) -> PageKind:
    """``raw_text`` (the whole text layer, invisible text included) only serves as a hint: electronic acts
    carry their signature slots as invisible «CONTRACTOR$<uuid>» placeholders on otherwise image-only pages."""
    if page is None or not has_text:
        return PageKind(page_no, "UNREAD", "", "NONE", 0.0)
    lines = group_lines(page.words)
    text = " ".join(ln.text for ln in lines)
    src = "TOKENS" if page.from_tokens else "TEXT_LAYER"
    ns_all = _ns(text)
    letters = sum(ch.isalpha() for ch in ns_all)
    if STAMP.search(ns_all) and len(ns_all) < 200:
        return PageKind(page_no, "STAMP_PAGE", text[:80], src, 0.8)
    raw_ns = re.sub(r"\s+", "", (text + " " + (raw_text or ""))).lower()
    if SIGNATURES.search(raw_ns) and letters < 400 and not re.search(HEADER_RULES[1][1], ns_all):
        return PageKind(page_no, "UNKNOWN", "подписи", src, 0.4)  # the signature block continuing a document
    if letters < 200 and _is_drawing_sheet(page):
        # the drawings bound into an ИД binder are executive schemes (their title may be drawn as curves)
        return PageKind(page_no, "ISP_GEO_SCHEME", "", src, 0.6)
    if letters < MIN_TEXT:
        # a scan with only a page number or a scanner watermark («AnyScanner 5») in its text layer: unread
        if page.from_tokens:
            return PageKind(page_no, "STAMP_PAGE", text[:80], src, 0.6)
        return PageKind(page_no, "UNREAD", text[:80], "NONE", 0.0)
    if not page.from_tokens and _garbled(text):
        return PageKind(page_no, "UNREAD", text[:80], "NONE", 0.0)  # a junk scanner OCR layer (95: F0083 p5)
    # an act names itself mid-page, under the parties block («к акту освидетельствования» does not match)
    if re.search(HEADER_RULES[1][1], ns_all):
        title = next((ln.text for ln in lines if re.search(r"освидетельствовани", fold(ln.text))), "АОСР")
        return PageKind(page_no, "AOSR", title[:160], src, 0.9)
    if len(AOSR_BODY.findall(ns_all)) >= 2:
        return PageKind(page_no, "AOSR", "", src, 0.7)  # the act's second page (п. 2–7, signatures)
    top = [ln for ln in lines if ln.y1 <= 0.30 * page.height]
    band = _ns(" ".join(ln.text for ln in top))
    for kind, rx in HEADER_RULES:
        if kind == "ID_REGISTRY":
            hit = next((ln for ln in top if re.search(rx, _ns(ln.text))), None)
            if hit is not None:
                return PageKind(page_no, kind, hit.text[:160], src, 0.9)
            continue
        m = re.search(rx, band)
        if m:
            title = next(
                (ln.text for ln in top if re.search(rx, _ns(ln.text))), " ".join(ln.text for ln in top[:2])
            )
            return PageKind(page_no, kind, title[:160], src, 0.9)
    # drawings name themselves in the title block (bottom right): executive schemes
    tb = [ln for ln in lines if ln.y0 >= 0.70 * page.height and ln.x0 >= 0.40 * page.width]
    if re.search(HEADER_RULES[5][1], _ns(" ".join(ln.text for ln in tb))):
        return PageKind(page_no, "ISP_GEO_SCHEME", " ".join(ln.text for ln in tb)[:160], src, 0.8)
    for kind, rx in HEADER_RULES:
        if kind != "ID_REGISTRY" and re.search(rx, ns_all[:800]):
            return PageKind(page_no, kind, text[:160], src, 0.6)
    if CONTRACT_BODY.search(ns_all):
        return PageKind(page_no, "CONTRACT", "", src, 0.6)
    if _is_drawing_sheet(page):
        # the drawings bound into an ИД binder are executive schemes (their title may be drawn as curves)
        return PageKind(page_no, "ISP_GEO_SCHEME", "", src, 0.6)
    return PageKind(page_no, "UNKNOWN", text[:80], src, 0.3)


def _garbled(text: str) -> bool:
    from inspector_docproc.lexicon import load_lexicon

    ratio, n = load_lexicon().hit_ratio(text.split())
    return n >= 12 and ratio < 0.5


def _is_drawing_sheet(page: PageData) -> bool:
    """A vector drawing (many paths, mostly short labels) on a landscape or large sheet."""
    if page._page is None or not page.words:
        return False
    try:
        n_paths = len(page._page.get_cdrawings())
    except Exception:
        return False
    short = sum(1 for w in page.words if len(w.text) <= 6)
    landscape_or_large = page.width > page.height or page.width * page.height > 1.5e6
    return n_paths > 400 and short / len(page.words) > 0.6 and landscape_or_large


def segments(kinds: list[PageKind]) -> list[Segment]:
    """Consecutive pages of one kind form a segment; a stamp page closes the scan it certifies; a page whose
    header band carries a title (confidence ≥ 0.8) starts a new document even when the kind repeats."""
    out: list[Segment] = []
    for pk in kinds:
        # an untitled page right after a document (not after its stamp page) continues that document
        if (
            pk.kind == "UNKNOWN"
            and out
            and out[-1].kind not in ("UNREAD", "UNKNOWN")
            and kinds[pk.page_no - 2 if pk.page_no >= 2 else 0].kind != "STAMP_PAGE"
        ):
            out[-1].end = pk.page_no
            out[-1].pages.append(pk.page_no)
            continue
        if pk.kind == "STAMP_PAGE" and out:
            out[-1].end = pk.page_no
            out[-1].pages.append(pk.page_no)
            continue
        new_title = pk.confidence >= 0.8 and pk.kind not in ("UNKNOWN", "UNREAD")
        if (
            out
            and out[-1].kind == pk.kind
            and not (
                new_title
                and pk.kind in ("QUALITY_DOCS", "LAB_OR_MEASUREMENT", "AOSR")
                and pk.title != out[-1].title
            )
        ):
            out[-1].end = pk.page_no
            out[-1].pages.append(pk.page_no)
        else:
            out.append(Segment(pk.kind, pk.page_no, pk.page_no, pk.title, [pk.page_no]))
    return out
