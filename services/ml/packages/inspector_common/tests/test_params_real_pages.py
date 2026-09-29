"""All seed regexes (with gates) over real text layers of TRAIN_PUBLIC documents: no timeouts, bounded time.

Owner: AG-03. Slow + data: `make test-slow` (skips without the organizer data). Objects come from split_policy.json
TRAIN_PUBLIC only; the hidden test object is never opened (hidden-test integrity, CLAUDE.md rule 4).
"""

from __future__ import annotations

import json
import random
import time

import pytest

from inspector_common import params

pytestmark = [pytest.mark.slow, pytest.mark.data]

PAGES = 200


def test_seed_regexes_on_train_pages(data_paths) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pymupdf.TOOLS.mupdf_display_errors(False)
    with open(data_paths.split_policy_path, encoding="utf-8") as fh:
        split = json.load(fh)
    train, excluded = set(split["TRAIN_PUBLIC"]), set(split["excluded_file_ids"])
    with open(data_paths.manifest_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    rows = [
        r
        for r in rows
        if r.get("object_id") in train
        and r["file_id"] not in excluded
        and str(r.get("relative_path", "")).lower().endswith(".pdf")
    ]
    rng = random.Random(3)
    rng.shuffle(rows)
    reg = params.load_params()
    per_page: list[float] = []
    for row in rows:
        path = data_paths.document_path(row["relative_path"])
        if not path.is_file():
            continue
        with pymupdf.open(path) as doc:
            order = list(range(doc.page_count))
            rng.shuffle(order)
            for index in order[:4]:
                text = params.normalize_regex_input(doc[index].get_text())
                if not text.strip():
                    continue
                t0 = time.perf_counter()
                for spec in reg:
                    reg.extract(spec.code, text)  # RegexTimeout fails the test
                per_page.append(time.perf_counter() - t0)
        if len(per_page) >= PAGES:
            break
    assert len(per_page) >= PAGES // 2
    per_page.sort()
    assert per_page[int(len(per_page) * 0.95)] < 0.15, per_page[-5:]
    assert per_page[-1] < 1.0
