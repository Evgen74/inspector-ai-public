"""Discipline marks of files and of parameter sources (stage availability for the 132-row precedence).

A file covers one or more *discipline marks* (АР, КР, ОВ, ВК, ЭОМ, СС, ГП, ПЗ, ПОС, ПОД, ООС, ПБ, ОДИ, ЭЭ, СМ,
ТХ). They come, in this order, from the RD марка of the title block (layout artifacts), the manifest ``section``
and generic name/folder vocabulary. A parameter needs, per stage, the marks named by its matrix sources
(``params.json → source_docs.<stage>[].discipline``), falling back to its matrix section.

This is a transparent stand-in until the registry (AG-01) and the title blocks (AG-02B) carry a resolved
discipline per logical document; only public manifest metadata and title blocks are used (97 §2.17).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import PurePosixPath

MARKS: tuple[str, ...] = (
    "ПЗ",
    "ГП",
    "АР",
    "КР",
    "ЭОМ",
    "ВК",
    "ОВ",
    "СС",
    "ПОС",
    "ПОД",
    "ООС",
    "ПБ",
    "ОДИ",
    "ЭЭ",
    "СМ",
    "ТХ",
)

# Manifest `section` (organizer vocabulary) → marks.
MANIFEST_SECTION_MARKS: Mapping[str, tuple[str, ...]] = {
    "AR": ("АР",),
    "KR": ("КР",),
    "EOM": ("ЭОМ",),
    "VK": ("ВК",),
    "OV": ("ОВ",),
    "SS": ("СС",),
    "GP": ("ГП",),
    "PB": ("ПБ",),
    "POS": ("ПОС",),
}

# Matrix section (params.json `section`) → marks of the documents that carry it.
SECTION_MARKS: Mapping[str, tuple[str, ...]] = {
    "ПЗ": ("ПЗ",),
    "СПЗУ": ("ГП",),
    "АР": ("АР",),
    "КР": ("КР",),
    "ИОС1": ("ЭОМ",),
    "ИОС2": ("ВК",),
    "ИОС3": ("ВК",),
    "ИОС4": ("ОВ",),
    "ИОС5": ("СС",),
    "ПОС": ("ПОС",),
    "ПОД": ("ПОД",),
    "ООС": ("ООС",),
    "ППМ": ("ПБ",),
    "ОДИ": ("ОДИ",),
    "ЗУ": ("ЭЭ",),
    "СМ": ("СМ",),
}

# Discipline names used in params.json source_docs → marks.
SOURCE_DISCIPLINE_MARKS: Mapping[str, tuple[str, ...]] = {
    "ПЗ": ("ПЗ",),
    "СПЗУ": ("ГП",),
    "ГП": ("ГП",),
    "ГСН": ("ГП",),
    "АР": ("АР",),
    "КР": ("КР",),
    "КЖ": ("КР",),
    "КМД": ("КР",),
    "ИОС1": ("ЭОМ",),
    "ЭОМ": ("ЭОМ",),
    "ИОС2": ("ВК",),
    "ИОС3": ("ВК",),
    "ВК": ("ВК",),
    "НВК": ("ВК",),
    "ИОС4": ("ОВ",),
    "ОВ": ("ОВ",),
    "ИОС5": ("СС",),
    "СС": ("СС",),
    "ПОС": ("ПОС",),
    "ППР": ("ПОС",),
    "ПОД": ("ПОД",),
    "ООС": ("ООС",),
    "ППМ": ("ПБ",),
    "ОДИ": ("ОДИ", "АР"),
    "ЭЭ": ("ЭЭ",),
    "СМ": ("СМ",),
    "ТХ": ("ТХ",),
    "ТРПО": ("ТХ",),
}

_B = r"(?<![0-9a-zа-я])"  # token start
_E = r"(?![a-zа-я])"  # token end (digits may follow: ОВ1, КЖ2)
# ПД subsection codes «ИОС1.1», «ИОС4.2», «ИОС5.5.1» (Постановление № 87): the digit after ИОС names the discipline.
_IOS = r"(?<![0-9a-zа-я])иос"
NAME_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (mark, re.compile(pattern))
    for mark, pattern in (
        ("ПЗ", rf"пояснительн|{_B}(?:о?пз){_E}(?!у)"),
        ("ГП", rf"планировочн\w* организац|{_B}(?:пзу|спозу|спзу|гп){_E}"),
        ("АР", rf"архитектурн|{_B}ар\d*{_E}"),
        (
            "КР",
            rf"конструктивн|{_B}(?:кр|кж|км|кмд)\d*(?:\.\d+)?{_E}|ограждени\w* котлован|стен\w* в грунте"
            rf"|{_B}(?:свг|бсс){_E}|форшахт|{_B}сва[ия]|{_B}свай|железобетонн|фундаментн\w* плит|бетонн\w* работ",
        ),
        ("ЭОМ", rf"электроснабж|электрооборуд|{_B}(?:эом|эм|эо|эн|эс)\d*(?:\.\d+)?{_E}|{_IOS}1(?!\d)"),
        (
            "ВК",
            rf"водоснабж|водоотвед|канализац|водосток|дренаж|{_B}(?:вк|нв|нк|вв|нвк|нс|аупт)\d*(?:\.\d+)?{_E}|{_IOS}[23](?!\d)",
        ),
        ("ОВ", rf"отоплен|вентиляц|кондиционир|теплоснабж|{_B}(?:ов|тм|итп)\d*(?:\.\d+)?{_E}|{_IOS}4(?!\d)"),
        ("СС", rf"сети связи|сетей связи|{_B}(?:сс|апс|соуэ|скс)\d*(?:\.\d+)?{_E}|{_IOS}5(?!\d)"),
        ("ПОС", rf"организац\w* строительства|{_B}пос\d*(?:\.\d+)?{_E}"),
        ("ПОД", rf"работ по сносу|демонтаж\w* объект|{_B}под{_E}"),
        ("ООС", rf"окружающей среды|{_B}оос\d*(?:\.\d+)?{_E}"),
        ("ПБ", rf"пожарной безопасност|{_B}(?:пб|мпб)\d*{_E}"),
        ("ОДИ", rf"доступа инвалидов|маломобильн|{_B}(?:оди|мгн){_E}"),
        ("ЭЭ", rf"энергетическ\w* эффективност|приборами учета|{_B}ээ{_E}"),
        ("СМ", rf"сметн|{_B}см{_E}"),
        ("ТХ", rf"технологическ\w* решени|{_B}тх\d*{_E}|{_IOS}7(?!\d)"),
    )
)

# RD марка at the end of a document code: «АНО-150321-1-РД-ОВ1» → «ОВ1», «…-КЖ2.1» → «КЖ2.1».
_MARK_IN_CODE = re.compile(r"(?:^|[-_/.\s])([А-ЯЁ]{1,4})(\d{0,2}(?:\.\d{1,2})?)\s*$")
_MARK_PREFIX_MARKS: Mapping[str, str] = {
    "ОВ": "ОВ",
    "ТМ": "ОВ",
    "ИТП": "ОВ",
    "ВК": "ВК",
    "НВ": "ВК",
    "НК": "ВК",
    "ВВ": "ВК",
    "НВК": "ВК",
    "АР": "АР",
    "АС": "АР",
    "КР": "КР",
    "КЖ": "КР",
    "КМ": "КР",
    "КМД": "КР",
    "ЭОМ": "ЭОМ",
    "ЭМ": "ЭОМ",
    "ЭО": "ЭОМ",
    "ЭН": "ЭОМ",
    "ЭС": "ЭОМ",
    "СС": "СС",
    "АПС": "СС",
    "СОУЭ": "СС",
    "ГП": "ГП",
    "ПЗУ": "ГП",
    "ПОС": "ПОС",
    "ПОД": "ПОД",
    "ООС": "ООС",
    "ПБ": "ПБ",
    "ОДИ": "ОДИ",
    "ЭЭ": "ЭЭ",
    "ТХ": "ТХ",
    "ОПЗ": "ПЗ",
    "ПЗ": "ПЗ",
}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().replace("ё", "е")


def plan_mark(document_code: str | None) -> str | None:
    """The RD марка printed at the end of a шифр («АНО-150321-1-РД-ОВ1» → «ОВ1»); None when absent."""
    if not document_code:
        return None
    match = _MARK_IN_CODE.search(unicodedata.normalize("NFC", document_code).strip().upper())
    if not match:
        return None
    prefix, number = match.group(1), match.group(2)
    if prefix not in _MARK_PREFIX_MARKS:
        return None
    return prefix + number


# «…-РД-ОВ1 изм. 4_в1 (1).pdf» → «ОВ1»: the RD марка after the stage token of a шифр printed in the file name.
_MARK_IN_NAME = re.compile(r"(?:^|[-_/.\s])(?:Р|РД)[-_/.]([А-ЯЁ]{1,4})(\d{0,2}(?:\.\d{1,2})?)(?![А-ЯЁа-яё])")


def plan_mark_of_name(relative_path: str | None) -> str | None:
    """The RD марка of the шифр in a file name (a weak prior: display only, when no title block was read)."""
    if not relative_path:
        return None
    stem = unicodedata.normalize("NFC", PurePosixPath(relative_path).stem).upper()
    for match in _MARK_IN_NAME.finditer(stem):
        prefix, number = match.group(1), match.group(2)
        if prefix in _MARK_PREFIX_MARKS:
            return prefix + number
    return None


def marks_of_code(document_code: str | None) -> tuple[str, ...]:
    mark = plan_mark(document_code)
    if mark is None:
        return ()
    prefix = re.match(r"[А-ЯЁ]+", mark)
    return (_MARK_PREFIX_MARKS[prefix.group(0)],) if prefix else ()


def marks_of_name(relative_path: str) -> tuple[str, ...]:
    """Marks named by the file name and its folders (generic vocabulary)."""
    path = PurePosixPath(relative_path)
    text = " " + _fold(" / ".join(path.parts[:-1]) + " / " + path.stem) + " "
    found = [mark for mark, pattern in NAME_RULES if pattern.search(text)]
    return tuple(dict.fromkeys(found))


def file_marks(
    relative_path: str, manifest_section: str | None, document_codes: Iterable[str | None] = ()
) -> tuple[str, ...]:
    """Discipline marks of one file: title-block марки first, then the manifest section, then the name."""
    out: list[str] = []
    for code in document_codes:
        out.extend(marks_of_code(code))
    out.extend(MANIFEST_SECTION_MARKS.get(manifest_section or "", ()))
    if not out:
        out.extend(marks_of_name(relative_path))
    return tuple(m for m in dict.fromkeys(out) if m in MARKS)


def required_marks(section: str, sources: Sequence[Mapping[str, object]] | None) -> tuple[str, ...]:
    """Marks a parameter needs on one stage: its matrix sources' disciplines, else its matrix section."""
    out: list[str] = []
    for src in sources or ():
        discipline = src.get("discipline") if isinstance(src, Mapping) else None
        if isinstance(discipline, str):
            out.extend(SOURCE_DISCIPLINE_MARKS.get(discipline, ()))
    if not out:
        out.extend(SECTION_MARKS.get(section, ()))
    return tuple(dict.fromkeys(out))
