"""Tag grammar used by the room comparators (96 R-15; 95 §3.4): homoglyph folding, compound expansion, families.

A drawing mark as printed may carry OCR look-alikes («B2.1» for «В2.1»), several branch numbers
(«В2.7,8,9», «П17.1, 17.2») and trailing air-flow text («В3.1 −600 м³/ч»). The comparators need one normalised
label per element («В2.7», «В2.8», «В2.9»), so a tag is folded and expanded here, then classified into the
change-map element families by the seed ``tag_patterns`` (labels) or ``anchors`` (phrases).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

# Latin look-alikes (and the OCR confusion N → П) inside drawing marks → Cyrillic (95 §3.4 (2)).
_LAT_TO_CYR = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
        "N": "П",
    }
)
_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
_HEAD = re.compile(r"^([А-ЯЁ]{1,4})-?(\d{1,3})(?:\.(\d{1,3}))?$")
_NUMERIC_PART = re.compile(r"^(\d{1,3})(?:\.(\d{1,3}))?$")


def fold_text(text: str) -> str:
    """Case-insensitive matching form for phrases: NFC, casefold, ё→е, collapsed spaces."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().replace("ё", "е").split())


def fold_mark(text: str) -> str:
    """One mark in canonical spelling: NFC, upper case, Latin look-alikes → Cyrillic, typographic dashes → «-»,
    decimal comma → point, no inner spaces around separators."""
    s = unicodedata.normalize("NFC", text).strip().upper().translate(_DASHES)
    s = s.translate(_LAT_TO_CYR)
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\s*\.\s*", ".", s)
    return s


def expand_mark(raw: str) -> list[str]:
    """«В2.7,8,9 −950 м³/ч» → [«В2.7», «В2.8», «В2.9»]; «П17.1, 17.2» → [«П17.1», «П17.2»]; «П2/ВЕ» → [«П2/ВЕ»].

    Only the first whitespace-delimited chunk is read (the rest is air flow, position or comment). A chunk that
    is not a mark stays as one folded token, so that family patterns decide whether it counts.
    """
    folded = fold_mark(raw)
    if not folded:
        return []
    chunk = folded.split()[0]
    parts = [p for p in chunk.split(",") if p]
    if not parts:
        return []
    head = _HEAD.match(parts[0])
    if head is None:
        return [chunk]
    prefix, major, minor = head.group(1), head.group(2), head.group(3)
    out = [f"{prefix}{major}" + (f".{minor}" if minor else "")]
    for part in parts[1:]:
        m = _HEAD.match(part)
        if m is not None:
            prefix, major = m.group(1), m.group(2)
            out.append(part.replace("-", ""))
            continue
        n = _NUMERIC_PART.match(part)
        if n is None:
            break
        if n.group(2) is not None:  # «17.2» after «П17.1»
            out.append(f"{prefix}{n.group(1)}.{n.group(2)}")
        elif minor is not None:  # «8» after «В2.7»
            out.append(f"{prefix}{major}.{n.group(1)}")
        else:  # «3» after «П2» → П3
            out.append(f"{prefix}{n.group(1)}")
    return list(dict.fromkeys(out))


def system_prefix(label: str) -> str:
    """Branch «В2.4» → system «В2»; a label without a branch part is its own system."""
    return label.split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class FamilySpec:
    """What the tag grammar needs from one change-map element family (seed ``change_matrix_map.json``)."""

    family: str
    topic: str | None
    patterns: tuple[re.Pattern[str], ...]
    anchors: tuple[str, ...]  # folded phrases
    anchor_patterns: tuple[re.Pattern[str], ...] = ()  # inflection-tolerant forms of the anchors
    disciplines: tuple[str, ...] = ()  # discipline marks of the documents that design the family (ОВ)

    def matches_label(self, label: str) -> bool:
        return any(p.fullmatch(label) for p in self.patterns)

    def matches_phrase(self, text: str) -> bool:
        folded = fold_text(text)
        return any(p.search(folded) for p in self.anchor_patterns)


def _clean_anchor(anchor: str) -> str:
    return fold_text(anchor.strip("«»\"' "))


def _stem(word: str) -> str:
    """A crude inflection-tolerant stem: drop up to two final letters of words longer than 4 characters
    («теплый» → «тепл», «полы» → «пол», «радиатор» → «радиат»)."""
    if len(word) <= 3 or not word.isalpha():
        return re.escape(word)
    cut = 2 if len(word) > 5 else 1
    return re.escape(word[: len(word) - cut])


def anchor_pattern(anchor: str) -> re.Pattern[str]:
    """«теплый пол» → «(?<!\\w)тепл\\w*\\s+пол\\w*» (matches «тёплые полы», «теплого пола»)."""
    words = [w for w in re.split(r"\s+", anchor) if w]
    body = r"\s+".join(_stem(w) + r"\w*" for w in words)
    return re.compile(r"(?<!\w)" + body)


@lru_cache(maxsize=8)
def _family_specs_cached(
    key: tuple[tuple[str, str | None, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...],
) -> dict[str, FamilySpec]:
    out: dict[str, FamilySpec] = {}
    for family, topic, patterns, anchors, disciplines in key:
        cleaned = tuple(dict.fromkeys(a for a in (_clean_anchor(x) for x in anchors) if len(a) >= 3))
        out[family] = FamilySpec(
            family=family,
            topic=topic,
            patterns=tuple(re.compile(p) for p in patterns),
            anchors=cleaned,
            anchor_patterns=tuple(anchor_pattern(a) for a in cleaned),
            disciplines=disciplines,
        )
    return out


def family_specs(families: Iterable[Mapping[str, object]]) -> dict[str, FamilySpec]:
    """FamilySpec per family from the change-map ``element_families`` records."""
    key = tuple(
        (
            str(f["family"]),
            f.get("topic") if isinstance(f.get("topic"), str) else None,  # type: ignore[misc]
            tuple(str(p) for p in (f.get("tag_patterns") or ())),  # type: ignore[union-attr]
            tuple(str(a) for a in (f.get("anchors") or ())),  # type: ignore[union-attr]
            tuple(str(d) for d in (f.get("disciplines") or ())),  # type: ignore[union-attr]
        )
        for f in families
    )
    return _family_specs_cached(key)


def classify_tag(
    raw: str,
    tag_kind: str | None,
    specs: Mapping[str, FamilySpec],
    kinds_by_family: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    """Family → element labels this printed tag contributes.

    Label families (with ``tag_patterns``) take the expanded marks that fully match a pattern; phrase families
    (no patterns, e.g. WARM_FLOOR) take the anchor phrase once. A family also requires the tag kind to be one it
    accepts (config ``families[*].tag_kinds``); a tag without a kind is accepted by label families only.
    """
    out: dict[str, list[str]] = {}
    labels = expand_mark(raw)
    for family, spec in specs.items():
        kinds = kinds_by_family.get(family)
        if kinds is None:
            continue
        if spec.patterns:
            if tag_kind is not None and kinds and tag_kind not in kinds:
                continue
            hits = [label for label in labels if spec.matches_label(label)]
            if hits:
                out[family] = hits
        elif spec.anchors:
            if tag_kind is None or (kinds and tag_kind not in kinds):
                continue
            if spec.matches_phrase(raw):
                # Presence families carry one element per room: the family's first anchor as its label.
                out[family] = [spec.anchors[0]]
    return out
