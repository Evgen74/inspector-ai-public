"""Russian word lexicon for text-layer quality checks and garbled-layer repair (96 §4.10, 95 R1).

The lexicon is a plain list of lowercase Cyrillic word forms. It is built from the visible text layers
of clean pages of the TRAIN objects only (never the hidden object): words that occur in at least two
files. Build: ``uv run --locked python -m inspector_docproc.lexicon build``; the result is committed
as ``resources/ru_lexicon.txt.gz`` (a vocabulary, not organizer documents).
"""

from __future__ import annotations

import gzip
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

RESOURCE = Path(__file__).with_name("resources") / "ru_lexicon.txt.gz"
# document frequency (number of TRAIN files) of every lexicon word: tie-break between OCR readings that are
# both words (italic «m» = «т» or «м»: «Cm» → «Ст» / «См»). Same builder, same files, «word<TAB>files».
FREQ_RESOURCE = Path(__file__).with_name("resources") / "ru_wordfreq.txt.gz"

CYR_WORD = re.compile(r"[а-яё]+")
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-z]")
# 95 §2 «mojibake ratio»: Latin Extended-A/B + IPA + these ASCII symbols, over visible characters.
_MOJIBAKE_CHARS = set("<>=?@[]^_{}|")


def is_cyrillic_letter(ch: str) -> bool:
    return "А" <= ch <= "я" or ch in "Ёё"


def is_mojibake_char(ch: str) -> bool:
    o = ord(ch)
    return 0x0100 <= o <= 0x02AF or ch in _MOJIBAKE_CHARS or (o < 0x20 and ch not in "\t\n\r")


class Lexicon:
    def __init__(self, words: Iterable[str]) -> None:
        self.words = frozenset(words)

    def __contains__(self, word: str) -> bool:
        return word in self.words

    def __len__(self) -> int:
        return len(self.words)

    def hit_ratio(self, text_words: Iterable[str], min_len: int = 3) -> tuple[float, int]:
        """Share of Cyrillic words (≥ ``min_len`` letters) found in the lexicon, and their count."""
        n = hits = 0
        for w in text_words:
            for m in CYR_WORD.finditer(w.lower().replace("ё", "е")):
                token = m.group(0)
                if len(token) < min_len:
                    continue
                n += 1
                hits += token in self.words
        return (hits / n if n else 0.0), n


@lru_cache(maxsize=1)
def load_wordfreq(path: str | None = None) -> dict[str, int]:
    """Word → number of TRAIN files it occurs in (empty when the resource is absent)."""
    p = Path(path) if path else FREQ_RESOURCE
    if not p.is_file():
        return {}
    out: dict[str, int] = {}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            word, _, n = line.rstrip("\n").partition("\t")
            if word and n.isdigit():
                out[word] = int(n)
    return out


@lru_cache(maxsize=1)
def load_lexicon(path: str | None = None) -> Lexicon:
    p = Path(path) if path else RESOURCE
    if not p.is_file():
        return Lexicon(())
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return Lexicon(line.strip() for line in fh if line.strip())


def text_stats(words: Iterable[str]) -> dict[str, float | int]:
    """Script and mojibake statistics of visible text (95 §2 definitions)."""
    n_chars = cyr = lat = moj = 0
    n_letter_words = mixed = 0
    for w in words:
        w = unicodedata.normalize("NFC", w)
        has_c = has_l = False
        for ch in w:
            if ch.isspace():
                continue
            n_chars += 1
            if is_cyrillic_letter(ch):
                cyr += 1
                has_c = True
            elif "A" <= ch <= "Z" or "a" <= ch <= "z":
                lat += 1
                has_l = True
            if is_mojibake_char(ch):
                moj += 1
        if has_c or has_l:
            n_letter_words += 1
            mixed += has_c and has_l
    return {
        "chars": n_chars,
        "cyrillic": cyr,
        "latin": lat,
        "mojibake": moj,
        "mojibake_ratio": round(moj / n_chars, 4) if n_chars else 0.0,
        "cyrillic_share": round(cyr / (cyr + lat), 4) if (cyr + lat) else 0.0,
        "letter_words": n_letter_words,
        "mixed_script_ratio": round(mixed / n_letter_words, 4) if n_letter_words else 0.0,
    }


# ── Builder (dev-time; TRAIN objects only) ───────────────────────────────────────────────────


def _file_words(path: str) -> tuple[Counter[str], int]:
    import pymupdf

    words: Counter[str] = Counter()
    pages = 0
    try:
        doc = pymupdf.open(path)
    except Exception:
        return words, 0
    with doc:
        for page in doc:
            try:
                text = page.get_text("text")
            except Exception:
                continue
            tokens = text.split()
            st = text_stats(tokens)
            if st["chars"] < 200 or st["mojibake_ratio"] > 0.02 or st["cyrillic_share"] < 0.6:
                continue
            pages += 1
            for tok in tokens:
                for m in CYR_WORD.finditer(tok.lower().replace("ё", "е")):
                    if len(m.group(0)) >= 2:
                        words[m.group(0)] += 1
    return words, pages


def _write_gz_deterministic(path: Path, text: str) -> None:
    """gzip without a timestamp in the header: the same words give the same bytes (the digest of the
    resources is part of the pipeline version)."""
    import io

    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, compresslevel=9, mtime=0) as gz:
        gz.write(text.encode("utf-8"))
    path.write_bytes(buf.getvalue())


def build(
    out: Path | None = RESOURCE,
    min_files: int = 2,
    workers: int = 8,
    freq_out: Path | None = FREQ_RESOURCE,
) -> dict[str, int]:
    """Build the lexicon (``out``) and the document frequencies (``freq_out``) from clean text-layer pages
    of the TRAIN objects (split_policy.json); ``None`` skips a file."""
    import json
    from concurrent.futures import ProcessPoolExecutor

    from inspector_common.settings import Settings

    paths = Settings().paths
    policy = json.loads(paths.split_policy_path.read_text(encoding="utf-8"))
    train = set(policy.get("TRAIN_PUBLIC", []))
    excluded = set(policy.get("excluded_file_ids", []))
    files = []
    for line in paths.manifest_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["object_id"] in train and row["extension"] == ".pdf" and row["file_id"] not in excluded:
            p = paths.document_path(row["relative_path"])
            if p.is_file():
                files.append(str(p))
    df: Counter[str] = Counter()
    pages = 0
    with ProcessPoolExecutor(workers) as pool:
        for words, n in pool.map(_file_words, files):
            df.update(words.keys())
            pages += n
    keep = sorted(w for w, c in df.items() if c >= min_files)
    if out is not None:
        _write_gz_deterministic(out, "\n".join(keep) + "\n")
    if freq_out is not None:
        _write_gz_deterministic(freq_out, "".join(f"{w}\t{df[w]}\n" for w in keep))
    return {"files": len(files), "clean_pages": pages, "distinct_words": len(df), "kept": len(keep)}


if __name__ == "__main__":  # pragma: no cover - dev tool
    import sys

    if sys.argv[1:] == ["build"]:
        print(build())
    elif sys.argv[1:2] == ["build-freq"]:  # frequencies only; the committed lexicon stays byte-identical
        print(build(out=None, workers=int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    else:
        print("usage: python -m inspector_docproc.lexicon build | build-freq [workers]")
