"""Test helpers (no organizer data involved in the builders): synthetic ruled tables drawn with PyMuPDF and
lookups of TRAIN files / cached PageTokens for the data tests. Never used by product code."""

from __future__ import annotations

import itertools
import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "tests" / "data"


@lru_cache(maxsize=1)
def _manifest() -> dict[str, dict]:
    from inspector_common.settings import Settings

    paths = Settings().paths
    if not paths.manifest_path.is_file():
        return {}
    rows = [
        json.loads(line)
        for line in paths.manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {r["file_id"]: r for r in rows if r.get("split") == "TRAIN_PUBLIC"}


def train_row(file_id: str) -> dict | None:
    """Manifest row of a TRAIN file (None when the organizer data is absent or the file is not TRAIN)."""
    return _manifest().get(file_id)


def train_path(file_id: str) -> Path | None:
    from inspector_common.settings import Settings

    row = train_row(file_id)
    if row is None:
        return None
    path = Settings().paths.document_path(row["relative_path"])
    return path if path.is_file() else None


def cached_token_dir(file_id: str, pages: Sequence[int]) -> Path | None:
    """A token-cache directory holding all ``pages`` (newest recognition version first); None otherwise."""
    from inspector_common.settings import Settings
    from inspector_tables.batch import token_plan

    row = train_row(file_id)
    if row is None:
        return None
    s = Settings()
    plan = token_plan(Path("/nonexistent"), [], s.cache_root, file_id, row["sha256"], True)
    for d in plan.cache_dirs:
        if all((Path(d) / f"p{p:05d}.json.gz").is_file() for p in pages):
            return Path(d)
    return None


def load_gt(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def draw_table(page, x0: float, y0: float, widths: Sequence[float], heights: Sequence[float],
               cells: Sequence[Sequence[str]], merged: Sequence[int] = (), fontsize: float = 8.0) -> None:  # fmt: skip
    """Ruled table: vertical borders at the column edges (interrupted on ``merged`` rows, which get one
    full-width centred cell), horizontal rules between rows, text left-aligned in each cell ("\\n" wraps, a leading "^" centres)."""
    import pymupdf

    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    ys = [y0]
    for h in heights:
        ys.append(ys[-1] + h)
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    for i, (ya, yb) in enumerate(itertools.pairwise(ys)):
        inner = [xs[0], xs[-1]] if i in merged else xs
        for x in inner:
            page.draw_line((x, ya), (x, yb), width=0.8)
    tw = pymupdf.TextWriter(page.rect)
    font = pymupdf.Font("tiro")
    for i, row in enumerate(cells):
        ya, yb = ys[i], ys[i + 1]
        if i in merged:
            text = row[0]
            tw.append(((xs[0] + xs[-1]) / 2 - font.text_length(text, fontsize) / 2, (ya + yb) / 2 + fontsize / 3), text,
                      font=font, fontsize=fontsize)  # fmt: skip
            continue
        for j, text in enumerate(row):
            if not text:
                continue
            centred = text.startswith("^")
            lines = text.lstrip("^").split("\n")
            for k, ln in enumerate(lines):
                yy = (ya + yb) / 2 + fontsize / 3 + (k - (len(lines) - 1) / 2) * fontsize * 1.15
                x = (xs[j] + xs[j + 1]) / 2 - font.text_length(ln, fontsize) / 2 if centred else xs[j] + 2.5
                tw.append((x, yy), ln, font=font, fontsize=fontsize)
    tw.write_text(page)


def write_text(page, x: float, y: float, text: str, fontsize: float = 10.0) -> None:
    import pymupdf

    tw = pymupdf.TextWriter(page.rect)
    tw.append((x, y), text, font=pymupdf.Font("tiro"), fontsize=fontsize)
    tw.write_text(page)
