"""Garbled text-layer repair (97 §2.13 F1, §2.16; 95 R1): constant per-font glyph shift.

Some CAD/Office exports write glyph codes instead of Unicode for a font subset, e.g. «ɨɪɝаɧɢɡаɰɢя» for
«организация» (U+0268 → U+043E: +0x1D6). The shift is constant per font, so it can be estimated from the
page itself: for every font whose characters fall outside Basic Latin/Cyrillic, candidate offsets map its
frequent suspicious characters onto frequent Russian letters; each candidate is applied to the font's
suspicious characters only, and the one with the best lexicon hit ratio wins. A repair is accepted only
when the lexicon confirms it (hit ≥ ``repair_min_hit`` and a gain ≥ ``repair_min_gain``); otherwise the
layer is left untouched and the page goes to OCR. Raw text is always kept (``text_raw``).

Control characters that stand for digits (a second, digit-specific offset) are mapped the same way.
Nothing here is specific to any object: offsets are searched, not configured.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from inspector_docproc.config import RouterConfig
from inspector_docproc.lexicon import Lexicon, is_cyrillic_letter, load_lexicon
from inspector_docproc.textlayer import TextWord

# Frequent Russian letters (lower and upper case) used to propose offsets.
_TARGETS = "оеаинтсрвлкмдпуяыгзбчйьжшхюцщэфъОЕАИНТСРВЛКМДПУЯЫГЗБЧЙЖШХЮЦЩЭФ"


def is_suspicious(ch: str) -> bool:
    """A character that should not appear in Russian/ASCII technical text: a garble candidate."""
    o = ord(ch)
    if o < 0x20:
        return ch not in "\t\n\r"
    if o < 0x80:
        return False
    if o == 0xFFFD:  # replacement character: no glyph information left, never shifted
        return True
    if 0x0400 <= o <= 0x04FF:  # Cyrillic
        return False
    if o in (0xA0, 0xAB, 0xBB, 0xB0, 0xB1, 0xB2, 0xB3, 0xD7, 0xF7, 0xA7, 0xB5, 0xB7, 0xA9, 0xAE, 0xBC, 0xBD):
        return False
    if 0x2000 <= o <= 0x206F or 0x2100 <= o <= 0x22FF or 0x2460 <= o <= 0x24FF:  # punct, symbols, ①
        return False
    # ⌀ ∅ Ø ø Φ φ α β λ δ Δ Σ are ordinary in engineering text
    return o not in (
        0x2300,
        0x2205,
        0x00D8,
        0x00F8,
        0x03A6,
        0x03C6,
        0x03B1,
        0x03B2,
        0x03BB,
        0x03B4,
        0x0394,
        0x03A3,
    )


@dataclass(slots=True)
class FontRepair:
    font: str
    offset: int | None
    digit_offset: int | None
    hit_before: float
    hit_after: float
    n_words: int
    accepted: bool


@dataclass(slots=True)
class RepairReport:
    garbled_words: int = 0
    repaired_words: int = 0
    unrepaired_words: int = 0
    fonts: list[FontRepair] | None = None

    @property
    def fully_repaired(self) -> bool:
        return self.garbled_words > 0 and self.unrepaired_words == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "garbled_words": self.garbled_words,
            "repaired_words": self.repaired_words,
            "unrepaired_words": self.unrepaired_words,
            "fonts": [
                {
                    "font": f.font,
                    "offset": f.offset,
                    "digit_offset": f.digit_offset,
                    "hit_before": round(f.hit_before, 3),
                    "hit_after": round(f.hit_after, 3),
                    "words": f.n_words,
                    "accepted": f.accepted,
                }
                for f in (self.fonts or [])
            ],
        }


def shift_text(text: str, offset: int, digit_offset: int | None = None) -> str:
    out = []
    for ch in text:
        if is_suspicious(ch) and ch != "\ufffd":
            o = ord(ch)
            if o < 0x20 and digit_offset is not None:
                c2 = chr(o + digit_offset)
                out.append(c2 if c2 in _CTRL_TARGETS else ch)
                continue
            if 0 <= o + offset <= 0x10FFFF:
                c2 = chr(o + offset)
                out.append(c2 if is_cyrillic_letter(c2) else ch)
                continue
        out.append(ch)
    return "".join(out)


def word_is_garbled(text: str) -> bool:
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return False
    sus = sum(is_suspicious(c) for c in letters)
    return sus >= 1 and sus / len(letters) >= 0.25


def _best_offset(texts: list[str], lexicon: Lexicon) -> tuple[int | None, float, float, int]:
    """(offset, hit before, hit after, lexicon-checkable words after) of the best candidate shift."""
    sus = Counter(c for t in texts for c in t if is_suspicious(c) and 0x20 <= ord(c) != 0xFFFD)
    if not sus:
        return None, 0.0, 0.0, 0
    before, _ = lexicon.hit_ratio(texts)
    votes: Counter[int] = Counter()
    for ch, n in sus.most_common(12):
        for tgt in _TARGETS:
            votes[ord(tgt) - ord(ch)] += n
    best: tuple[int | None, float, int] = (None, before, 0)
    for off, _ in votes.most_common(24):
        hit, n = lexicon.hit_ratio([shift_text(t, off) for t in texts])
        if n and hit > best[1]:
            best = (off, hit, n)
    return best[0], before, best[1], best[2]


_CTRL_TARGETS = frozenset(" 0123456789.,-:;()/%№+=")


def _digit_offset(texts: list[str]) -> int | None:
    """Offset that maps control characters onto digits, spaces and punctuation (e.g. +0x1D, +0x1F)."""
    ctrl = Counter(c for t in texts for c in t if ord(c) < 0x20 and c not in "\t\n\r")
    if not ctrl:
        return None
    total = sum(ctrl.values())
    best: tuple[float, int] | None = None
    for off in range(0x10, 0x40):
        share = sum(n for c, n in ctrl.items() if chr(ord(c) + off) in _CTRL_TARGETS) / total
        if best is None or share > best[0]:
            best = (share, off)
    return best[1] if best and best[0] >= 0.9 else None


def repair_words(
    words: list[TextWord], cfg: RouterConfig | None = None, lexicon: Lexicon | None = None
) -> RepairReport:
    """Repair garbled visible words in place (per font); returns what was found and fixed."""
    cfg = cfg or RouterConfig()
    lexicon = lexicon or load_lexicon()
    report = RepairReport(fonts=[])
    by_font: dict[str, list[TextWord]] = defaultdict(list)
    for w in words:
        if w.visible and word_is_garbled(w.text):
            w.garbled = True
            by_font[w.font].append(w)
    report.garbled_words = sum(len(v) for v in by_font.values())
    if not report.garbled_words or not len(lexicon):
        report.unrepaired_words = report.garbled_words
        return report
    # Pass 1: best offset per font. A font needs ``repair_min_words`` lexicon-checkable words to stand on
    # its own; a thinly supported font is accepted only when a well-supported font of the same page
    # found the same offset (two words can hit the lexicon by luck under a wrong shift).
    cands = {}
    for font in by_font:
        # estimate on every visible word of the font: correct words anchor the lexicon test
        texts = [w.text for w in words if w.visible and w.font == font]
        offset, before, after, n_after = _best_offset(texts, lexicon)
        good = offset is not None and after >= cfg.repair_min_hit and after - before >= cfg.repair_min_gain
        cands[font] = (offset, before, after, n_after, good, _digit_offset(texts))
    trusted = {c[0] for c in cands.values() if c[4] and c[3] >= cfg.repair_min_words}
    for font, garbled in by_font.items():
        offset, before, after, n_after, good, dig = cands[font]
        accepted = good and (n_after >= cfg.repair_min_words or offset in trusted)
        report.fonts.append(FontRepair(font, offset, dig, before, after, len(garbled), accepted))  # type: ignore[union-attr]
        if not accepted:
            report.unrepaired_words += len(garbled)
            continue
        for w in garbled:
            fixed = shift_text(w.text, offset, dig)  # type: ignore[arg-type]
            if fixed != w.text:
                w.text_raw = w.text
                w.text = fixed
                w.repaired = True
            w.garbled = word_is_garbled(w.text)
            if w.garbled:
                report.unrepaired_words += 1
            else:
                report.repaired_words += 1
    return report


def split_repaired(words: list[TextWord]) -> list[TextWord]:
    """Split words whose repaired text contains spaces (fonts that encode the space as a control
    character); sub-word boxes are apportioned by character count along the reading direction."""
    out: list[TextWord] = []
    for w in words:
        if not w.repaired or " " not in w.text.strip():
            out.append(w)
            continue
        parts = w.text.split(" ")
        n = max(len(w.text), 1)
        pos = 0
        x0, y0, x1, y1 = w.bbox
        for part in parts:
            a, b = pos / n, (pos + len(part)) / n
            pos += len(part) + 1
            if not part:
                continue
            if w.angle == 0:
                box = [x0 + a * (x1 - x0), y0, x0 + b * (x1 - x0), y1]
            elif w.angle == 180:
                box = [x1 - b * (x1 - x0), y0, x1 - a * (x1 - x0), y1]
            elif w.angle == 90:
                box = [x0, y0 + a * (y1 - y0), x1, y0 + b * (y1 - y0)]
            else:
                box = [x0, y1 - b * (y1 - y0), x1, y1 - a * (y1 - y0)]
            out.append(
                TextWord(part, [round(v, 5) for v in box], w.font, w.size, w.angle, w.block, w.line,
                         w.visible, w.text_raw, True, False)
            )  # fmt: skip
    return out
