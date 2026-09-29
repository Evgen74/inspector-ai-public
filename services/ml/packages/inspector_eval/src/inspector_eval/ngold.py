"""N-GOLD labelling tooling (95 §5.3, 97 §3.2 M2; protocol: ``LABELLING_PROTOCOL.md`` of this package).

N-GOLD is our own label set for the unlabeled train object (Новослободская), badged «разметка команды».
The file (``devsets/n_gold_novoslob_v1.json``, format 2, schema ``devsets/n_gold_label_set.schema.json``)
extends ``docs/analysis/95_novoslob_label_seed.json``: every seed field is kept, and each item gains

- ``annotations``: one entry per labeller pass (an independent agent, the user's spot-check, a teammate),
  with the label, the corrected code/location/evidence/values, the reasoning and the pages viewed;
- ``label`` + ``adjudication``: the label the scorer uses, derived from the annotations (a human label takes
  precedence over an agent label; disagreeing labellers of the same kind make it UNSURE);
- ``source`` and ``scorable`` (integrity notes and data problems are listed, never scored).

The workflow (all commands are ``inspector-score ngold …``):

1. ``packet ID``: the blind packet of one item — the question (parameter, trigger, location, pages to start
   from) plus rendered page images and the pages' own text layer. System outputs (``system_hypothesis``,
   ``why_interesting``, stage values, earlier labels) are never written into a packet.
2. ``record``: store an annotation (``--json FILE`` for a batch); the adjudicated label is recomputed.
3. ``sample``: a deterministic, stratified random sample (25–30 items) exported for the user's spot-check:
   ``sheet.csv`` to fill, ``index.html`` with the page images, and ``key.json`` with the agent labels
   (kept apart so that the spot-check stays blind).
4. ``import-spotcheck``: read the filled sheet back as HUMAN annotations and report the agreement
   (raw and Cohen's κ) between the agent and the user.
5. ``inspector-score devset freeze N-GOLD``: pin the labels (canonical sha256 + file sha256). After the
   freeze every write through this module fails (TEST_SET_HASH_MISMATCH on load if the file was edited).

Nothing here reads a TEST_HIDDEN object: the label set's object must be a TRAIN_PUBLIC object of
split_policy.json, and page rendering refuses files of any other object.
"""

from __future__ import annotations

import csv
import html
import json
import os
import random
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from inspector_common.contracts.loader import load_enums
from inspector_common.errors import InspectorError
from inspector_common.hashing import sha256_file
from inspector_eval.data import InputError, ScoringContext, read_json

DEVSET_DIR = Path(__file__).resolve().parent / "devsets"
SCHEMA_PATH = DEVSET_DIR / "n_gold_label_set.schema.json"
FORMAT = "n_gold_label_set"
FORMAT_VERSION = 2
PROTOCOL_ID = "N-GOLD-AGENT-v1"
UNSURE = "UNSURE"

# Fields that carry system outputs or earlier labels: never shown to a blind labeller.
BLIND_HIDDEN_FIELDS: tuple[str, ...] = (
    "system_hypothesis",
    "why_interesting",
    "pd_value",
    "rd_value",
    "id_value",
    "label",
    "label_comment",
    "protocol_status",
    "comparison_result",
    "annotations",
    "adjudication",
    "seed_original",
)
# Annotation fields that, when given, replace the item's value on adoption (the seed value is kept in
# ``seed_original`` the first time it changes).
ADOPTABLE_FIELDS: tuple[str, ...] = (
    "parameter_code",
    "location",
    "location_type",
    "evidence",
    "pd_value",
    "rd_value",
    "id_value",
    "protocol_status",
    "comparison_result",
)
SPOTCHECK_MIN, SPOTCHECK_MAX = 25, 30
SPOTCHECK_COLUMNS: tuple[str, ...] = (
    "id",
    "parameter_code",
    "parameter_name",
    "location",
    "pages",
    "question_ru",
    "user_label",
    "user_parameter_code",
    "user_location",
    "user_comment",
)


# ── schema and vocabularies ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def label_set_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def vocabulary(name: str) -> tuple[str, ...]:
    """Values of a local vocabulary of the label-set schema (Label, LabelItemSource, LabellerKind, …)."""
    return tuple(label_set_schema()["$defs"][name]["enum"])


def label_values() -> tuple[str, ...]:
    """ViolationLabel codes (contract) plus UNSURE."""
    return (*load_enums()["ViolationLabel"].codes, UNSURE)


def schema_errors(document: Any) -> list[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(label_set_schema())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<корень>'}: {e.message}" for e in errors]


def validate_label_set(document: Any) -> None:
    errors = schema_errors(document)
    if errors:
        raise InputError("Файл разметки N-GOLD не соответствует схеме: " + "; ".join(errors[:5]))
    ids = [str(i["id"]) for i in document["candidates"]]
    dupes = sorted(k for k, n in Counter(ids).items() if n > 1)
    if dupes:
        raise InputError(f"Файл разметки N-GOLD: повторяются идентификаторы {', '.join(dupes)}")


# ── file I/O ─────────────────────────────────────────────────────────────────────────────────


def upgrade(document: Mapping[str, Any], object_id: str | None = None) -> dict[str, Any]:
    """A seed-format (format 1) document → format 2. Idempotent on format-2 documents."""
    meta = dict(document.get("meta") or {})
    meta.setdefault("object_id", object_id or meta.get("object_id"))
    if not meta.get("object_id"):
        raise InputError("Не указан объект разметки (meta.object_id)")
    meta["format"] = FORMAT
    meta["format_version"] = FORMAT_VERSION
    meta["label_values"] = list(label_values())
    meta.setdefault("protocol", f"services/ml/packages/inspector_eval/LABELLING_PROTOCOL.md ({PROTOCOL_ID})")
    items = []
    for raw in document.get("candidates", []):
        item = dict(raw)
        item.setdefault("source", "SEED")
        item.setdefault("scorable", True)
        item.setdefault("annotations", [])
        item.setdefault("adjudication", None)
        item.setdefault("label", None)
        items.append(item)
    return {"meta": meta, "candidates": items}


def load_label_set(path: Path) -> dict[str, Any]:
    document = read_json(path)
    if not isinstance(document, dict):
        raise InputError(f"Файл разметки {path} должен быть JSON-объектом")
    if (document.get("meta") or {}).get("format_version") != FORMAT_VERSION:
        document = upgrade(document)
    validate_label_set(document)
    return document


def dump_label_set(document: Mapping[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def save_label_set(path: Path, document: Mapping[str, Any], *, frozen: bool = False) -> None:
    """Validate and write atomically. ``frozen`` (the registry says so) refuses every write."""
    if frozen:
        raise InspectorError("TEST_SET_HASH_MISMATCH", test_set=path.name)
    validate_label_set(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(dump_label_set(document))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def item_by_id(document: Mapping[str, Any], item_id: str) -> dict[str, Any]:
    for item in document["candidates"]:
        if item["id"] == item_id:
            return item
    raise InputError(f"Элемент {item_id!r} не найден в разметке N-GOLD")


# ── adjudication ─────────────────────────────────────────────────────────────────────────────


def adjudicate(item: dict[str, Any]) -> dict[str, Any]:
    """Recompute ``label`` (+ adopted fields) and ``adjudication`` from the item's annotations.

    - no annotations: the item keeps its label (a seed may carry one) and ``adjudication`` is None;
    - humans present: the latest annotation of each human counts; they must agree (else UNRESOLVED/UNSURE);
      a human label beats a disagreeing agent label (HUMAN_PRECEDENCE);
    - agents only: the latest annotation of each agent; all agree → SINGLE/AGREEMENT, else UNRESOLVED.
    The deciding annotation (the latest of the winning kind) supplies the adopted fields.
    """
    notes = [a for a in item.get("annotations", []) if isinstance(a, Mapping)]
    if not notes:
        return item
    latest: dict[str, Mapping[str, Any]] = {}
    for note in sorted(notes, key=lambda a: str(a.get("labelled_at", ""))):
        latest[str(note["labeller"])] = note
    humans = [a for a in latest.values() if a.get("labeller_kind") == "HUMAN"]
    agents = [a for a in latest.values() if a.get("labeller_kind") == "AGENT"]
    deciding_pool = humans or agents
    labels = {a["label"] for a in deciding_pool}
    all_labels = {a["label"] for a in latest.values()}
    decider = max(deciding_pool, key=lambda a: str(a.get("labelled_at", "")))
    if len(labels) > 1:
        method, label = "UNRESOLVED", UNSURE
    elif humans and len(all_labels) > 1:
        method, label = "HUMAN_PRECEDENCE", decider["label"]
    elif len(latest) > 1:
        method, label = "AGREEMENT", decider["label"]
    else:
        method, label = "SINGLE", decider["label"]
    if method != "UNRESOLVED":
        for name in ADOPTABLE_FIELDS:
            # A key present in the annotation is adopted even when null (e.g. «no ИД value»).
            if name in decider and decider[name] != item.get(name):
                original = item.setdefault("seed_original", {})
                original.setdefault(name, item.get(name))
                item[name] = decider[name]
        if "scorable" in decider:
            item["scorable"] = bool(decider["scorable"])
    item["label"] = label
    item["label_comment"] = decider.get("reasoning") if method != "UNRESOLVED" else item.get("label_comment")
    item["adjudication"] = {
        "method": method,
        "decided_by": str(decider["labeller"]),
        "labellers": sorted(latest),
        "disagreement": len(all_labels) > 1,
    }
    return item


def record(document: dict[str, Any], item_id: str, annotation: Mapping[str, Any]) -> dict[str, Any]:
    """Append one annotation to an item and re-adjudicate it. Returns the item."""
    # Unset optional fields are dropped; explicit nulls of the stage values mean «no value at this stage».
    note = {k: v for k, v in annotation.items() if v is not None or k in ("pd_value", "rd_value", "id_value")}
    note.setdefault("protocol", PROTOCOL_ID)
    missing = [k for k in ("labeller", "labeller_kind", "label", "labelled_at") if not note.get(k)]
    if missing:
        raise InputError(f"{item_id}: в аннотации нет полей {', '.join(missing)}")
    if note["label"] not in label_values():
        raise InputError(f"{item_id}: недопустимая метка {note['label']!r}")
    item = item_by_id(document, item_id)
    item.setdefault("annotations", []).append(note)
    adjudicate(item)
    validate_label_set(document)
    return item


# ── blind packets ────────────────────────────────────────────────────────────────────────────


def blind_question(item: Mapping[str, Any], ctx: ScoringContext | None) -> dict[str, Any]:
    """The labeller's view of an item: the question only, no system output and no earlier label."""
    code = str(item.get("parameter_code"))
    catalog = ctx.catalog.get(code) if ctx is not None else None
    question: dict[str, Any] = {
        "id": item["id"],
        "object_id": None,
        "parameter_code": code,
        "location": item.get("location"),
        "pages_to_start_from": [
            {"stage": e["stage"], "file_id": e["file_id"], "pdf_page_number": e["pdf_page_number"]}
            for e in item.get("evidence", [])
        ],
        "labels": list(label_values()),
        "task_ru": (
            "Определите по изображениям страниц (и их текстовому слою), есть ли нарушение по параметру "
            "в указанном месте. Выпишите значения ПД/РД/ИД так, как они напечатаны, укажите правильные "
            "страницы-доказательства, метку и обоснование. Если код или место указаны неверно — исправьте."
        ),
    }
    if catalog is not None:
        question["catalog"] = {
            k: catalog.get(k)
            for k in (
                "parameter_name",
                "unit",
                "trigger",
                "criticality",
                "source_pd",
                "source_rd",
                "source_id",
            )
        }
    leaked = [k for k in BLIND_HIDDEN_FIELDS if k in question]
    assert not leaked, leaked  # construction guarantees it; kept as a tripwire for future edits
    return question


@dataclass(frozen=True, slots=True)
class PageRequest:
    file_id: str
    page: int
    clip: tuple[float, float, float, float] | None = None  # normalised x0, y0, x1, y1

    @classmethod
    def parse(cls, text: str) -> PageRequest:
        """``F0105:17`` or ``F0105:17:0.5,0,1,0.5`` (normalised clip)."""
        parts = text.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"ожидается FILE:PAGE[:x0,y0,x1,y1], получено {text!r}")
        clip = None
        if len(parts) == 3:
            values = tuple(float(v) for v in parts[2].split(","))
            if len(values) != 4 or not all(0 <= v <= 1 for v in values):
                raise ValueError(f"клип задаётся четырьмя числами 0…1: {text!r}")
            if values[0] >= values[2] or values[1] >= values[3]:
                raise ValueError(f"пустой клип: {text!r}")
            clip = (values[0], values[1], values[2], values[3])
        return cls(parts[0].strip().upper(), int(parts[1]), clip)


def _parse_tiles(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    cols, _, rows = text.lower().partition("x")
    grid = (int(cols), int(rows))
    if not (1 <= grid[0] <= 6 and 1 <= grid[1] <= 6):
        raise ValueError("сетка плиток от 1x1 до 6x6")
    return grid


class PageSource:
    """Opens manifest PDFs of one train object (registry resolver: PRESENT or RECOVERED files only)."""

    def __init__(self, object_id: str, ctx: ScoringContext, settings: Any | None = None) -> None:
        if ctx.split_policy.split_of(object_id) != "TRAIN_PUBLIC":
            raise InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id=object_id)
        from inspector_registry.api import open_registry

        self.object_id = object_id
        self.registry, self.resolver = open_registry(settings)

    def path(self, file_id: str) -> Path:
        manifest_file = self.registry.get(file_id)
        if manifest_file.object_id != self.object_id:
            raise InputError(
                f"Файл {file_id} относится к объекту {manifest_file.object_id}, а не {self.object_id}"
            )
        if manifest_file.extension != ".pdf":
            raise InputError(f"Файл {file_id} не PDF ({manifest_file.extension})")
        resolved = self.resolver.resolve(manifest_file)
        if not resolved.readable or resolved.path is None:
            raise InputError(f"Файл {file_id} отсутствует локально ({resolved.local_status})")
        return resolved.path


def render_packet(
    item: Mapping[str, Any],
    out_dir: Path,
    source: PageSource,
    ctx: ScoringContext | None,
    *,
    dpi: int = 100,
    tiles: str | None = None,
    tile_dpi: int = 200,
    extra: Sequence[str] = (),
) -> dict[str, Any]:
    """Write ``question.json``, page PNGs (full page, optional tiles and clips) and page text into ``out_dir``."""
    import pymupdf

    grid = _parse_tiles(tiles)
    out_dir.mkdir(parents=True, exist_ok=True)
    requests = [PageRequest(e["file_id"], int(e["pdf_page_number"])) for e in item.get("evidence", [])]
    requests += [PageRequest.parse(x) for x in extra]
    rendered: list[dict[str, Any]] = []
    seen: set[tuple[str, int, tuple[float, float, float, float] | None]] = set()
    for req in requests:
        if (req.file_id, req.page, req.clip) in seen:
            continue
        seen.add((req.file_id, req.page, req.clip))
        with pymupdf.open(source.path(req.file_id)) as pdf:
            if not 1 <= req.page <= pdf.page_count:
                raise InputError(f"{req.file_id}: страницы {req.page} нет (всего {pdf.page_count})")
            page = pdf[req.page - 1]
            stem = f"{req.file_id}_p{req.page:04d}"
            files: list[str] = []
            rect = page.rect
            if req.clip is None:
                pix = page.get_pixmap(dpi=dpi)
                pix.save(out_dir / f"{stem}.png")
                files.append(f"{stem}.png")
                text = page.get_text("text")
                (out_dir / f"{stem}.txt").write_text(text, encoding="utf-8")
                files.append(f"{stem}.txt")
                if grid is not None:
                    cols, rows = grid
                    for r in range(rows):
                        for c in range(cols):
                            clip = pymupdf.Rect(
                                rect.x0 + rect.width * c / cols,
                                rect.y0 + rect.height * r / rows,
                                rect.x0 + rect.width * (c + 1) / cols,
                                rect.y0 + rect.height * (r + 1) / rows,
                            )
                            name = f"{stem}_t{r + 1}{c + 1}.png"
                            page.get_pixmap(dpi=tile_dpi, clip=clip).save(out_dir / name)
                            files.append(name)
            else:
                x0, y0, x1, y1 = req.clip
                clip = pymupdf.Rect(
                    rect.x0 + rect.width * x0,
                    rect.y0 + rect.height * y0,
                    rect.x0 + rect.width * x1,
                    rect.y0 + rect.height * y1,
                )
                name = f"{stem}_clip_{x0:g}_{y0:g}_{x1:g}_{y1:g}.png"
                page.get_pixmap(dpi=tile_dpi, clip=clip).save(out_dir / name)
                files.append(name)
            rendered.append(
                {
                    "file_id": req.file_id,
                    "pdf_page_number": req.page,
                    "page_size_pt": [round(rect.width, 1), round(rect.height, 1)],
                    "clip": list(req.clip) if req.clip else None,
                    "files": files,
                }
            )
    question = blind_question(item, ctx)
    question["object_id"] = source.object_id
    packet = {"question": question, "rendered": rendered, "dpi": dpi, "tile_dpi": tile_dpi, "tiles": tiles}
    (out_dir / "question.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return packet


# ── spot-check sample ────────────────────────────────────────────────────────────────────────


def fold_of(code: str, folds: Mapping[str, Sequence[str]] | None) -> str:
    """Code-prefix fold of an item (registry ``folds``, e.g. A = KR, B = the rest)."""
    if not folds:
        return "-"
    prefix = code.split("-", 1)[0].upper()
    for name, prefixes in folds.items():
        if prefix in {p.upper() for p in prefixes}:
            return name
    for name, prefixes in folds.items():
        if "*" in prefixes:
            return name
    return "-"


def sample_ids(
    document: Mapping[str, Any],
    n: int,
    *,
    seed: int,
    folds: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Deterministic stratified sample of labelled items for the user's spot-check.

    Strata are (label, fold). Every stratum gets ⌊n·share⌋ items, the remainder goes to the strata with the
    largest fractional parts (ties: rarer stratum first), and each stratum keeps at least one item when
    n allows. Items with an unresolved label (UNSURE, null) are sampled too: the user resolves them.
    """
    if n < 1:
        raise ValueError("размер выборки должен быть положительным")
    items = [i for i in document["candidates"] if i.get("scorable", True)]
    if len(items) <= n:
        return sorted(i["id"] for i in items)
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for i in items:
        strata[(str(i.get("label") or UNSURE), fold_of(str(i["parameter_code"]), folds))].append(i["id"])
    rng = random.Random(seed)
    for ids in strata.values():
        ids.sort()
        rng.shuffle(ids)
    total = len(items)
    quota = {k: n * len(v) / total for k, v in strata.items()}
    take = {k: min(len(strata[k]), max(1, int(q))) for k, q in quota.items()}
    while sum(take.values()) > n:  # too many strata for n: drop from the largest
        k = max(take, key=lambda s: (take[s], s))
        take[k] -= 1
    order = sorted(strata, key=lambda k: (-(quota[k] - int(quota[k])), len(strata[k]), k))
    while sum(take.values()) < n:
        grown = False
        for k in order:
            if take[k] < len(strata[k]) and sum(take.values()) < n:
                take[k] += 1
                grown = True
        if not grown:
            break
    return sorted(i for k, ids in strata.items() for i in ids[: take[k]])


def _pages_text(item: Mapping[str, Any]) -> str:
    return "; ".join(
        f"{e['stage']} {e['file_id']} с.{e['pdf_page_number']}" for e in item.get("evidence", [])
    )


def export_spotcheck(
    document: Mapping[str, Any],
    ids: Sequence[str],
    out_dir: Path,
    ctx: ScoringContext | None,
    *,
    source: PageSource | None = None,
    dpi: int = 100,
    seed: int | None = None,
) -> dict[str, Path]:
    """Write the spot-check bundle: ``sheet.csv`` (to fill), ``index.html``, ``key.json``, page images."""
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen = [item_by_id(document, i) for i in ids]
    rows = []
    for item in chosen:
        q = blind_question(item, ctx)
        rows.append(
            {
                "id": item["id"],
                "parameter_code": item["parameter_code"],
                "parameter_name": (q.get("catalog") or {}).get("parameter_name") or "",
                "location": item["location"],
                "pages": _pages_text(item),
                "question_ru": (q.get("catalog") or {}).get("trigger") or "",
                "user_label": "",
                "user_parameter_code": "",
                "user_location": "",
                "user_comment": "",
            }
        )
    sheet = out_dir / "sheet.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SPOTCHECK_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    key = out_dir / "key.json"
    key.write_text(
        json.dumps(
            {
                "note": "Метки агента. Не открывайте до заполнения sheet.csv (проверка должна быть слепой).",
                "seed": seed,
                "items": {
                    i["id"]: {
                        "label": i.get("label"),
                        "adjudication": i.get("adjudication"),
                        "label_comment": i.get("label_comment"),
                    }
                    for i in chosen
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    images: dict[str, list[str]] = {}
    if source is not None:
        for item in chosen:
            packet = render_packet(item, out_dir / "pages" / item["id"], source, ctx, dpi=dpi)
            images[item["id"]] = [
                f"pages/{item['id']}/{f}"
                for r in packet["rendered"]
                for f in r["files"]
                if f.endswith(".png")
            ]
    index = out_dir / "index.html"
    index.write_text(_spotcheck_html(rows, images), encoding="utf-8")
    return {"sheet": sheet, "key": key, "index": index}


def _spotcheck_html(rows: Sequence[Mapping[str, str]], images: Mapping[str, Sequence[str]]) -> str:
    labels = ", ".join(label_values())
    parts = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>N-GOLD: выборочная проверка</title>",
        "<style>body{font:15px/1.45 system-ui,sans-serif;margin:16px;max-width:1200px;background:#fff;color:#111}"
        "section{border-top:1px solid #ccc;padding:12px 0}img{max-width:100%;border:1px solid #ddd;margin:4px 0}"
        "code{background:#f4f4f4;padding:0 4px}</style></head><body>",
        "<h1>N-GOLD: выборочная проверка разметки (разметка команды)</h1>",
        f"<p>Заполните <code>sheet.csv</code>: столбец <code>user_label</code> — одна из меток {html.escape(labels)}; "
        "при необходимости исправьте код и место, добавьте комментарий. Метки агента лежат в "
        "<code>key.json</code>: откройте его только после заполнения.</p>",
    ]
    for row in rows:
        parts.append(
            f"<section id='{html.escape(row['id'])}'><h2>{html.escape(row['id'])}: "
            f"{html.escape(row['parameter_code'])} — {html.escape(row['parameter_name'])}</h2>"
        )
        parts.append(
            f"<p><b>Место:</b> {html.escape(row['location'])}<br><b>Страницы:</b> "
            f"{html.escape(row['pages'])}<br><b>Условие нарушения (каталог):</b> "
            f"{html.escape(row['question_ru'])}</p>"
        )
        for src in images.get(row["id"], []):
            parts.append(f"<img loading='lazy' src='{html.escape(src)}' alt='{html.escape(src)}'>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class Agreement:
    n: int
    agree: int
    kappa: float | None
    pairs: tuple[tuple[str, str, str], ...]  # (id, agent label, human label)

    @property
    def raw(self) -> float | None:
        return self.agree / self.n if self.n else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "agree": self.agree,
            "raw_agreement": self.raw,
            "cohen_kappa": self.kappa,
            "disagreements": [{"id": i, "agent": a, "human": h} for i, a, h in self.pairs if a != h],
        }


def cohen_kappa(pairs: Iterable[tuple[str, str]]) -> float | None:
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    expected = sum(left[k] * right.get(k, 0) for k in left) / (n * n)
    if expected >= 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def agreement(document: Mapping[str, Any]) -> Agreement:
    """Agent vs human labels on items that have both (latest annotation of each kind)."""
    pairs: list[tuple[str, str, str]] = []
    for item in document["candidates"]:
        latest: dict[str, Mapping[str, Any]] = {}
        for note in sorted(item.get("annotations", []), key=lambda a: str(a.get("labelled_at", ""))):
            latest[str(note.get("labeller_kind"))] = note
        if "AGENT" in latest and "HUMAN" in latest:
            pairs.append((item["id"], str(latest["AGENT"]["label"]), str(latest["HUMAN"]["label"])))
    agree = sum(1 for _, a, h in pairs if a == h)
    return Agreement(len(pairs), agree, cohen_kappa((a, h) for _, a, h in pairs), tuple(pairs))


def import_spotcheck(
    document: dict[str, Any], sheet: Path, *, labeller: str, labelled_at: str
) -> tuple[int, Agreement]:
    """Filled ``sheet.csv`` → HUMAN annotations (rows without ``user_label`` are skipped)."""
    try:
        text = sheet.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError(f"Файл не найден: {sheet}") from None
    reader = csv.DictReader(text.splitlines())
    missing = [c for c in ("id", "user_label") if c not in (reader.fieldnames or [])]
    if missing:
        raise InputError(f"В {sheet} нет столбцов: {', '.join(missing)}")
    added = 0
    for row in reader:
        label = (row.get("user_label") or "").strip().upper()
        if not label:
            continue
        if label not in label_values():
            raise InputError(
                f"{row.get('id')}: недопустимая метка {label!r} (допустимы {', '.join(label_values())})"
            )
        note: dict[str, Any] = {
            "labeller": labeller,
            "labeller_kind": "HUMAN",
            "protocol": PROTOCOL_ID,
            "blind": True,
            "label": label,
            "spot_check": True,
            "labelled_at": labelled_at,
        }
        if (row.get("user_parameter_code") or "").strip():
            note["parameter_code"] = row["user_parameter_code"].strip()
        if (row.get("user_location") or "").strip():
            note["location"] = row["user_location"].strip()
        if (row.get("user_comment") or "").strip():
            note["reasoning"] = row["user_comment"].strip()
        record(document, str(row["id"]).strip(), note)
        added += 1
    return added, agreement(document)


# ── status ───────────────────────────────────────────────────────────────────────────────────


def status(document: Mapping[str, Any], folds: Mapping[str, Sequence[str]] | None = None) -> dict[str, Any]:
    items = document["candidates"]
    scorable = [i for i in items if i.get("scorable", True)]
    by_label = Counter(str(i.get("label")) for i in scorable)
    by_source = Counter(str(i.get("source")) for i in items)
    by_fold = Counter(fold_of(str(i["parameter_code"]), folds) for i in scorable)
    annotated = Counter()
    for i in items:
        kinds = {a.get("labeller_kind") for a in i.get("annotations", [])}
        for kind in kinds:
            annotated[str(kind)] += 1
    unresolved = [i["id"] for i in items if (i.get("adjudication") or {}).get("method") == "UNRESOLVED"]
    return {
        "object_id": document["meta"].get("object_id"),
        "items": len(items),
        "scorable": len(scorable),
        "not_scorable": [i["id"] for i in items if not i.get("scorable", True)],
        "by_label": dict(sorted(by_label.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_fold": dict(sorted(by_fold.items())),
        "annotated_by_kind": dict(sorted(annotated.items())),
        "unresolved": unresolved,
        "unlabelled": [i["id"] for i in scorable if i.get("label") is None],
        "agreement": agreement(document).as_dict(),
    }


def file_sha256(path: Path) -> str:
    return sha256_file(path)
