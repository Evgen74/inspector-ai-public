"""Exact duplicates (sha256) and near-duplicates (page count + first-page fingerprint).

Near-duplicate keys (97 §2.12, «near-duplicates by text hash»):
- text: (pages, sha256 of the normalised page-1 text layer) — strong;
- image: (pages, sha256 of the page-1 image streams) — for scans without a text layer.
A pair that is already an exact duplicate is not repeated as a near-duplicate. Files whose page-1
text is identical but whose page counts differ are listed separately as ``first_page_matches``
(typical of an original and its revision); they are hints for the revision resolver, not duplicates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DupInput:
    file_id: str
    sha256: str
    pages: int | None
    text_hash: str | None
    image_hash: str | None


def find_duplicates(items: Iterable[DupInput]) -> dict[str, list[dict[str, Any]]]:
    items = list(items)
    exact: dict[str, list[str]] = defaultdict(list)
    for it in items:
        exact[it.sha256].append(it.file_id)
    exact_groups = [
        {"sha256": sha, "file_ids": sorted(ids)} for sha, ids in sorted(exact.items()) if len(ids) > 1
    ]
    exact_of = {fid: sha for sha, ids in exact.items() for fid in ids}

    near: dict[tuple[str, int, str], list[str]] = defaultdict(list)
    by_text: dict[str, list[DupInput]] = defaultdict(list)
    for it in items:
        if it.pages is None:
            continue
        if it.text_hash:
            near[("text", it.pages, it.text_hash)].append(it.file_id)
            by_text[it.text_hash].append(it)
        elif it.image_hash:
            near[("image", it.pages, it.image_hash)].append(it.file_id)
    near_groups: list[dict[str, Any]] = []
    for (basis, pages, digest), ids in sorted(near.items()):
        if len(ids) < 2 or len({exact_of[i] for i in ids}) < 2:
            continue  # a single sha256 behind all members: already an exact duplicate
        near_groups.append({"basis": basis, "pages": pages, "fingerprint": digest, "file_ids": sorted(ids)})
    first_page_matches: list[dict[str, Any]] = []
    for digest, group in sorted(by_text.items()):
        pages = {it.pages for it in group}
        if len(group) > 1 and len(pages) > 1:
            first_page_matches.append(
                {
                    "fingerprint": digest,
                    "files": sorted(
                        ({"file_id": it.file_id, "pages": it.pages} for it in group),
                        key=lambda d: d["file_id"],
                    ),
                }
            )
    return {"exact": exact_groups, "near": near_groups, "first_page_matches": first_page_matches}
