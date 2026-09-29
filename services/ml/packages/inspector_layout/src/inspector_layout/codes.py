"""Code gate for document codes (шифры), 96 §7.2 and R-06: code corrector + registry prior + stage-letter fold.

OCR reads the Cyrillic capitals of a шифр as Latin letters or digits («HBC-2025/03-P3» for «НВС-2025/03-ПЗ»,
«AHO/150321/1-PД-OB1» for «АНО/150321/1-РД-ОВ1»). The deterministic corrector of AG-02A
(:mod:`inspector_docproc.codefix`) fixes the visual look-alikes; what it cannot fix is a letter that OCR read as
a *different* letter or digit (П → P, З → 3). This module adds the object's own registry as a prior:

1. **Registry vocabulary.** The code-shaped parts of the manifest file names and folder names of the object
   being processed («АНО-150321-1-РД-ОВ1 изм. 4_в1.pdf» → segments АНО, 150321, 1, РД, ОВ1; «НВС-2025.03-1.2-ПЗ»
   → НВС, 2025, 03, 1, 2, ПЗ) plus the discipline dictionary of the corrector. Built at run time from the
   inputs of that object only — never a fixed list of object names.
2. **Segment readings.** Each letter-bearing segment of the corrected code is re-read through a small
   confusion table (P → Р/П, 3 → З, 0 → О, N → П …). A reading replaces the corrected segment only when it
   is a known registry segment and the corrected one is not; ties keep the corrector's result.
3. **Stage-letter fold.** A one-letter stage segment (П or Р, «1-П-ИОС5.4.2», «1-Р-ОВ») follows the stage of
   the file when the manifest knows it (PD → П, RD → Р); «РД» stays «РД».
4. **Whole-code prior.** A registry code whose separator-free, homoglyph-folded key is within edit distance 1
   of the result replaces a single substituted character (the printed separators are kept: file names cannot
   hold «/»).

The raw string is always kept by the caller (``document_code_raw``); the gated value is the match key.
Stamp «Стадия» values are folded by :func:`fold_stage` («P» → «Р», «PД» → «РД», «N» → «П»).
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from inspector_docproc.codefix import DISCIPLINES, fix_code

# Characters OCR confuses inside code segments (after the look-alike map of the corrector): each maps to
# the alternatives tried when the corrected segment is not a registry segment.
_CONFUSION: dict[str, tuple[str, ...]] = {
    "Р": ("П",),
    "П": ("Р",),
    "P": ("П", "Р"),
    "N": ("П",),
    "3": ("З",),
    "З": ("3",),
    "0": ("О",),
    "О": ("0",),
    "D": ("Д",),
    "Д": ("Л",),
    "Л": ("Д",),
    "I": ("1", "Г"),
    "l": ("1",),
    "1": ("Г",),
    "Г": ("1",),
    "Б": ("6",),
    "6": ("Б",),
    "Ш": ("Щ",),
    "Щ": ("Ш",),
    "Ц": ("Щ",),
    "Ч": ("Ц",),
}
_MAX_READINGS = 64

_SEP_SPLIT = re.compile(r"([-/._\s])")
_LETTERS = re.compile(r"[A-Za-zА-Яа-яЁё]")
_CYR_HEAD = re.compile(r"^([А-ЯЁA-Z]+)(.*)$")
# Code-shaped chunks of a file or folder name: runs of letters/digits joined by - . _ / (spaces end a code).
_NAME_CODE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-._/][0-9A-Za-zА-Яа-яЁё]+)+")
# Suffixes of file names that are not part of the code: «изм. 4», «_в1», «(1)», «Изм.1».
_NAME_NOISE = re.compile(r"(?i)(?:[\s_]*изм\.?\s*\d+.*$)|(?:\s*\(\d+\)\s*$)|(?:_в\d+$)")

_FOLD_KEY = str.maketrans(
    {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
     "X": "Х", "Y": "У", "0": "О", "3": "З", "N": "П"}
)  # fmt: skip
_STAGE_LETTER = {"PD": "П", "RD": "Р"}


def code_key(code: str) -> str:
    """Separator-free, homoglyph-folded key: «AHO/150321/1-PД-OB1» and «АНО-150321-1-РД-ОВ1» compare equal."""
    s = unicodedata.normalize("NFC", code).upper()
    s = re.sub(r"[\s\-/._]+", "", s)
    return s.translate(_FOLD_KEY)


def looks_like_code(text: str) -> bool:
    """A шифр-shaped string: letters and digits joined by at least two of - / . (e.g. «2451.Р.ДР.ГИ»)."""
    t = text.strip()
    if len(t) < 5 or " " in t:
        return False
    seps = len(re.findall(r"[-/.]", t))
    if seps < 2 or not re.search(r"\d", t) or not _LETTERS.search(t):
        return False
    if re.fullmatch(r"[\d.,:/\-]+", t):  # dates, numbers
        return False
    # a шифр is written in capitals: «4,01л/с.» (a flow), «п.3.6.4» (a clause) are not codes
    letters = _LETTERS.findall(t)
    if len(letters) < 2 or sum(c.isupper() for c in letters) < 0.5 * len(letters):
        return False
    # A date or decimal with a unit («20.03.2024г», «0,003м»): letters only at the tail, one segment long.
    return not re.fullmatch(r"[\d.,/\-]+[A-Za-zА-Яа-яЁё]{1,3}\.?", t)


def name_codes(name: str) -> list[str]:
    """Code-shaped chunks of one file or folder name (extension and revision suffixes stripped)."""
    stem = PurePosixPath(name).name
    for ext in (".pdf", ".PDF", ".docx", ".dwg", ".zip", ".7z", ".rar"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
    stem = _NAME_NOISE.sub("", stem).strip()
    return [m.group(0) for m in _NAME_CODE.finditer(stem) if _LETTERS.search(m.group(0))]


def _segments(code: str) -> list[str]:
    return [p for p in _SEP_SPLIT.split(code) if p and not _SEP_SPLIT.fullmatch(p)]


@dataclass(frozen=True, slots=True)
class CodeResolution:
    """Result of the gate for one code-shaped string."""

    raw: str
    code: str
    basis: str  # "unchanged" | "corrector" | "registry_segment" | "stage_fold" | "registry_code"
    changed_segments: tuple[tuple[str, str], ...] = ()
    registry_match: str | None = None  # the registry code the result agrees with (key-equal), if any
    confidence: float = 1.0


@dataclass(slots=True)
class CodeRegistry:
    """Registry prior of one object: code segments and full codes from its manifest names and folders."""

    segments: Counter[str] = field(default_factory=Counter)  # full segments («ПЗ», «ОВ1», «150321»)
    heads: Counter[str] = field(default_factory=Counter)  # letter heads («ОВ» of «ОВ1»)
    codes: dict[str, str] = field(default_factory=dict)  # code_key → code as written in the name
    code_files: dict[str, set[str]] = field(default_factory=dict)  # code_key → file ids
    file_stage: dict[str, str] = field(default_factory=dict)  # file_id → DocStage code (PD/RD/ID)

    @classmethod
    def from_names(
        cls,
        names: Iterable[tuple[str | None, str]],
        stages: Mapping[str, str] | None = None,
    ) -> CodeRegistry:
        """``names`` are (file_id or None, relative path); every path component contributes segments."""
        reg = cls()
        for file_id, rel in names:
            parts = PurePosixPath(rel).parts
            for i, part in enumerate(parts):
                is_file = i == len(parts) - 1
                for code in name_codes(part):
                    for seg in _segments(code):
                        seg_u = seg.upper() if seg.isascii() else seg
                        reg.segments[seg_u] += 1
                        m = _CYR_HEAD.match(seg_u)
                        if m and _LETTERS.search(m.group(1)):
                            reg.heads[m.group(1)] += 1
                    if is_file and len(_segments(code)) >= 3:
                        key = code_key(code)
                        reg.codes.setdefault(key, code)
                        if file_id:
                            reg.code_files.setdefault(key, set()).add(file_id)
                # Stand-alone capital words of folder/file names («Стадия П», «Том 5.4.2 ОВ», «ИОС5.1.4»)
                for m in re.finditer(r"(?<![А-ЯЁа-яё])([А-ЯЁ]{2,6})(\d[\d.]*)?(?![А-ЯЁа-яё])", part):
                    reg.heads[m.group(1)] += 1
                    if m.group(2):
                        reg.segments[m.group(1) + m.group(2).split(".")[0]] += 1
        if stages:
            reg.file_stage.update(stages)
        return reg

    @classmethod
    def from_manifest_rows(cls, rows: Iterable[Mapping[str, object]], object_id: str) -> CodeRegistry:
        rows = [r for r in rows if r.get("object_id") == object_id]
        return cls.from_names(
            [(str(r.get("file_id") or ""), str(r.get("relative_path") or "")) for r in rows],
            {str(r["file_id"]): str(r.get("stage") or "") for r in rows if r.get("file_id")},
        )

    # ── scoring ─────────────────────────────────────────────────────────────────────────────────
    def known_segment(self, seg: str) -> bool:
        return seg in self.segments

    def _segment_score(self, seg: str) -> float:
        score = 0.0
        if seg in self.segments:
            score += 3.0
        m = _CYR_HEAD.match(seg)
        head = m.group(1) if m else ""
        if head and head in self.heads:
            score += 2.0
        if head and (head in DISCIPLINES or seg in DISCIPLINES):
            score += 1.0
        if re.search(r"[A-Za-z]", seg) and re.search(r"[А-Яа-яЁё]", seg):
            score -= 2.0  # mixed script inside one segment is an OCR artefact
        return score

    def extras(self) -> frozenset[str]:
        """Letter heads for the corrector's dictionary rule (codefix rule 3)."""
        return frozenset(h for h in self.heads if re.fullmatch(r"[А-ЯЁ]{2,6}", h))

    # ── the gate ────────────────────────────────────────────────────────────────────────────────
    def resolve(self, raw: str, *, stage: str | None = None) -> CodeResolution:
        """Gate one code-shaped string. ``stage`` is the DocStage of the file (PD/RD/ID) when known."""
        text = unicodedata.normalize("NFC", raw).strip()
        fixed = fix_code(text, self.extras())
        basis = "corrector" if fixed != text else "unchanged"
        parts = _SEP_SPLIT.split(fixed)
        changed: list[tuple[str, str]] = []
        conf = 1.0
        for i in range(0, len(parts), 2):
            seg = parts[i]
            if not seg or not _LETTERS.search(seg):
                continue
            best = self._best_reading(seg)
            if best != seg:
                changed.append((seg, best))
                parts[i] = best
                basis = "registry_segment"
                conf = min(conf, 0.9)
        # Stage-letter fold: a one-letter segment П/Р follows the file stage.
        want = _STAGE_LETTER.get(stage or "")
        if want:
            for i in range(0, len(parts), 2):
                if parts[i] in ("П", "Р") and parts[i] != want and self._stage_position(parts, i):
                    changed.append((parts[i], want))
                    parts[i] = want
                    basis = "stage_fold"
                    conf = min(conf, 0.85)
        out = "".join(parts)
        match = self.codes.get(code_key(out))
        if match is None and self.codes:
            near = self._near_code(out)
            if near is not None:
                patched = _patch_one(out, near)
                if patched is not None and patched != out:
                    changed.append((out, patched))
                    out = patched
                    basis = "registry_code"
                    conf = min(conf, 0.8)
                    match = near
        return CodeResolution(text, out, basis, tuple(changed), match, conf)

    def _stage_position(self, parts: list[str], i: int) -> bool:
        """The segment sits where stage letters go: after a digit segment and before a discipline segment."""
        prev_seg = parts[i - 2] if i >= 2 else ""
        next_seg = parts[i + 2] if i + 2 < len(parts) else ""
        return bool(re.search(r"\d", prev_seg)) and bool(_LETTERS.search(next_seg))

    def _best_reading(self, seg: str) -> str:
        base = self._segment_score(seg)
        if seg in self.segments:
            return seg
        options: list[tuple[str, ...]] = []
        n_alt = 1
        for ch in seg:
            alts = _CONFUSION.get(ch, ())
            options.append((ch, *alts))
            n_alt *= 1 + len(alts)
            if n_alt > _MAX_READINGS:
                return seg
        best, best_score = seg, base
        for combo in itertools.product(*options):
            cand = "".join(combo)
            if cand == seg:
                continue
            subs = sum(a != b for a, b in zip(cand, seg, strict=True))
            if cand not in self.segments and cand not in DISCIPLINES:
                continue
            score = self._segment_score(cand) - 0.5 * subs
            if score > best_score + 1e-9:
                best, best_score = cand, score
        return best

    def _near_code(self, code: str) -> str | None:
        from rapidfuzz.distance import Levenshtein

        key = code_key(code)
        if len(key) < 6:
            return None
        hits = [
            v
            for k, v in self.codes.items()
            if Levenshtein.distance(key, k, score_cutoff=1) <= 1 and len(k) == len(key)
        ]
        return hits[0] if len(hits) == 1 else None


def _patch_one(printed: str, registry_code: str) -> str | None:
    """Replace the one substituted character of ``printed`` by the registry's (separators kept)."""
    src = [(i, c) for i, c in enumerate(printed) if not re.match(r"[\s\-/._]", c)]
    ref = [c for c in registry_code if not re.match(r"[\s\-/._]", c)]
    if len(src) != len(ref):
        return None
    diffs = [(i, r) for (i, c), r in zip(src, ref, strict=True) if code_key(c) != code_key(r)]
    if len(diffs) != 1:
        return None
    i, r = diffs[0]
    return printed[:i] + r + printed[i + 1 :]


_CODE_IN_TEXT = re.compile(r"[0-9A-Za-zА-Яа-яЁё][0-9A-Za-zА-Яа-яЁё./_\-]{4,}")


def gate_text(text: str, registry: CodeRegistry, *, stage: str | None = None) -> str:
    """Apply the gate to every code-shaped token of an OCR text; other tokens are returned unchanged."""

    def rep(m: re.Match[str]) -> str:
        tok = m.group(0)
        trail = ""
        while tok and tok[-1] in ".,;:":
            trail = tok[-1] + trail
            tok = tok[:-1]
        if not looks_like_code(tok):
            return m.group(0)
        return registry.resolve(tok, stage=stage).code + trail

    return _CODE_IN_TEXT.sub(rep, text)


# ── «Стадия» values ─────────────────────────────────────────────────────────────────────────────

_STAGE_FOLD = str.maketrans({"P": "Р", "D": "Д", "N": "П", "C": "С", "Л": "Д"})
STAGE_VALUES: dict[str, str] = {"П": "PD", "Р": "RD", "РД": "RD", "ИД": "ID", "ИС": "ID"}


def fold_stage(raw: str | None) -> tuple[str | None, str | None]:
    """Stamp «Стадия» → (printed value with homoglyphs folded, DocStage code). «P» → («Р», RD)."""
    if not raw:
        return None, None
    t = unicodedata.normalize("NFC", raw).strip().strip(".,:;").replace(" ", "")
    t = re.sub(r"^(II|ll|Il|lI|П|Π)$", "П", t)
    t = t.upper().translate(_STAGE_FOLD)
    if t in STAGE_VALUES:
        return t, STAGE_VALUES[t]
    return (t or None), None
