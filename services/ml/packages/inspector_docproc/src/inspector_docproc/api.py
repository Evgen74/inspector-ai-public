"""Stable read API over recognition for AG-02B (layout) and AG-02C (tables, ИД, NLP): page tokens and region
OCR addressed by ``(file_id, page)``.

    from inspector_docproc.api import TokenStore

    with TokenStore.for_run(ctx.run_dir) as store:            # a run written by `inspector-batch recognize`
        doc = store.page("F0201", 17)                          # PageTokens dict (contract page_tokens) or None
        words = store.words("F0201", 17)                       # tokens usable for extraction (see words())
        seals = store.zones("F0201", 17, kinds={"SEAL"})
        for page_no in store.pages("F0201"): ...               # pages recognized in this run (tokens/index.json)
        tb = store.ocr_region("F0201", 17, [0.75, 0.90, 1.0, 1.0], dpi=300)   # title block at 300 dpi

Where a page comes from (first hit wins):
1. the run directory: ``tokens/<file_id>/p<NNNNN>.json.gz`` (run_layout.yaml ``PAGE_TOKENS``);
2. the PageTokens cache ``.cache/tokens/<pipeline_version>/…`` by the file's sha256 (from the manifest) and the
   run's pipeline version (``tokens/index.json``) or, without a run, the version of the current configuration;
3. with ``on_miss="recognize"``: recognized now with the production pipeline and written to the cache.

Everything returned is plain contract data (dicts); nothing here writes into a run directory. Region OCR uses
the same OCR v2 engine as full pages (:meth:`PageRecognizer.ocr_region`), on the CPU by default (small images,
deterministic, no GPU memory in the caller's process). ``close()`` (or the context manager) releases the
ONNX Runtime sessions and open PDFs.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import orjson

from inspector_common.paths import DataPaths
from inspector_common.runlayout import RunLayout
from inspector_docproc.cache import TokenCache, load_gz
from inspector_docproc.config import ExecutionConfig, RecognitionConfig

QUALITY_RANK = {"ABSTAIN": 0, "LOW_QUALITY": 1, "OK": 2}
EXCLUDED_ZONE_KINDS = frozenset({"HANDWRITING", "QR"})  # their text is not document text


class UnknownFileError(KeyError):
    """The file id is neither registered nor in the manifest (or is not a PDF on disk)."""


class TokenStore:
    """PageTokens and region OCR by ``(file_id, page)``; see the module docstring."""

    def __init__(
        self,
        *,
        run_dir: Path | None = None,
        paths: DataPaths | None = None,
        cfg: RecognitionConfig | None = None,
        exec_cfg: ExecutionConfig | None = None,
        pipeline_version: str | None = None,
        on_miss: Literal["none", "recognize"] = "none",
        max_open_docs: int = 4,
    ) -> None:
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self._paths = paths
        self.cfg = cfg or RecognitionConfig()
        self.exec_cfg = exec_cfg or ExecutionConfig(providers="cpu", threads=1)
        self.on_miss = on_miss
        self._pipeline_version = pipeline_version
        self._index: dict[str, Any] | None = None
        self._files: dict[str, dict[str, Any]] | None = None
        self._registered: dict[str, dict[str, Any]] = {}
        self._docs: OrderedDict[str, Any] = OrderedDict()
        self._max_docs = max(1, max_open_docs)
        self._recognizers: dict[str, Any] = {}
        self._fresh: dict[tuple[str, int], dict[str, Any]] = {}  # pages recognized on a miss by this store

    @classmethod
    def for_run(cls, run_dir: Path, **kwargs: Any) -> TokenStore:
        return cls(run_dir=run_dir, **kwargs)

    # ── files ───────────────────────────────────────────────────────────────────────────────────
    @property
    def paths(self) -> DataPaths:
        if self._paths is None:
            from inspector_common.settings import Settings

            self._paths = Settings().paths
        return self._paths

    def register(self, file_id: str, path: Path, sha256: str, **meta: Any) -> None:
        """Make a file addressable without the manifest (tests, ad-hoc documents)."""
        self._registered[file_id] = {"file_id": file_id, "path": Path(path), "sha256": sha256, **meta}

    def file(self, file_id: str) -> dict[str, Any]:
        """``{"file_id", "path", "sha256", "object_id", "stage", "relative_path", …}`` of a PDF file."""
        if file_id in self._registered:
            return self._registered[file_id]
        if self._files is None:
            from inspector_docproc.inputs import load_manifest

            has = self.paths.manifest_path.is_file()
            self._files = {r["file_id"]: r for r in load_manifest(self.paths)} if has else {}
        row = self._files.get(file_id)
        if row is None or str(row.get("extension", "")).lower() != ".pdf":
            raise UnknownFileError(file_id)
        path = self.paths.document_path(row["relative_path"])
        return {**row, "path": path}

    def open_page(self, file_id: str, page: int) -> Any:
        """The PyMuPDF page (1-based ``page``); documents stay open in a small LRU until :meth:`close`."""
        import pymupdf

        doc = self._docs.get(file_id)
        if doc is None:
            path = self.file(file_id)["path"]
            if not Path(path).is_file():
                raise UnknownFileError(f"{file_id}: {path} is missing on disk")
            doc = pymupdf.open(path)
            self._docs[file_id] = doc
            while len(self._docs) > self._max_docs:
                _, old = self._docs.popitem(last=False)
                old.close()
        else:
            self._docs.move_to_end(file_id)
        return doc[page - 1]

    # ── pages ───────────────────────────────────────────────────────────────────────────────────
    def tokens_index(self) -> dict[str, Any] | None:
        """The run's ``tokens/index.json`` (contract ``tokens_index``), or None without a run/index."""
        if self._index is None and self.run_dir is not None:
            p = RunLayout(self.run_dir).path("TOKENS_INDEX")
            if p.is_file():
                self._index = orjson.loads(p.read_bytes())
        return self._index

    def pipeline_version(self) -> str:
        if self._pipeline_version is None:
            idx = self.tokens_index()
            if idx is not None:
                self._pipeline_version = str(idx["pipeline_version"])
            else:
                from inspector_docproc.recognize import PageRecognizer

                self._pipeline_version = PageRecognizer(self.cfg, self.exec_cfg).pipeline_version()
        return self._pipeline_version

    def pages(self, file_id: str) -> list[int]:
        """Pages of ``file_id`` recognized in the run (from ``tokens/index.json``, else the run directory)."""
        idx = self.tokens_index()
        if idx is not None:
            for f in idx.get("files", []):
                if f["file_id"] == file_id:
                    return [int(p["pdf_page_number"]) for p in f["pages"]]
            return []
        if self.run_dir is None:
            return []
        d = RunLayout(self.run_dir).path("PAGE_TOKENS", file_id=file_id, page=1).parent
        return sorted(int(p.name[1:6]) for p in d.glob("p*.json.gz")) if d.is_dir() else []

    def page(self, file_id: str, page: int) -> dict[str, Any] | None:
        """PageTokens of one page: run directory, then cache, then (``on_miss="recognize"``) recognition."""
        if self.run_dir is not None:
            p = RunLayout(self.run_dir).path("PAGE_TOKENS", file_id=file_id, page=page)
            if p.is_file():
                return load_gz(p)
        try:
            sha = self.file(file_id)["sha256"]
        except UnknownFileError:
            return None
        cached = TokenCache(self.paths.cache_root, self.pipeline_version()).get(sha, page)
        if cached is not None or self.on_miss != "recognize":
            return cached
        return self._fresh.get((file_id, page)) or self.recognize(file_id, page)

    def recognize(self, file_id: str, page: int) -> dict[str, Any]:
        """Recognize one page now with the production pipeline and store it in the PageTokens cache."""
        info = self.file(file_id)
        rec = self.recognizer_for(file_id)
        pg = self.open_page(file_id, page)
        out = rec.recognize_page(pg.parent, page, file_id=file_id, file_sha256=info["sha256"])
        TokenCache(self.paths.cache_root, rec.pipeline_version()).put(info["sha256"], page, out)
        self._fresh[(file_id, page)] = out
        return out

    def words(
        self,
        file_id: str,
        page: int,
        *,
        min_quality: str = "LOW_QUALITY",
        sources: Iterable[str] | None = None,
        exclude_zone_kinds: Iterable[str] = EXCLUDED_ZONE_KINDS,
    ) -> list[dict[str, Any]]:
        """Tokens usable for extraction: quality at least ``min_quality`` (OK > LOW_QUALITY > ABSTAIN), from
        ``sources`` (contract TextSource values; all by default), and not listed in a zone of
        ``exclude_zone_kinds`` (handwriting and QR by default; pass ``{"HANDWRITING", "QR", "SEAL"}`` to also
        drop text under seals)."""
        doc = self.page(file_id, page)
        if doc is None:
            return []
        floor = QUALITY_RANK[min_quality]
        allowed = set(sources) if sources is not None else None
        kinds = set(exclude_zone_kinds)
        dropped = {
            i
            for z in doc.get("zones") or []
            if z.get("kind") in kinds
            for i in (z.get("attrs") or {}).get("token_ids", [])
        }
        return [
            t
            for t in doc.get("tokens", [])
            if QUALITY_RANK.get(t.get("quality_flag", "OK"), 2) >= floor
            and (allowed is None or t.get("source") in allowed)
            and t["id"] not in dropped
        ]

    def zones(self, file_id: str, page: int, kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
        doc = self.page(file_id, page)
        if doc is None:
            return []
        want = set(kinds) if kinds is not None else None
        return [z for z in doc.get("zones") or [] if want is None or z.get("kind") in want]

    # ── region OCR ──────────────────────────────────────────────────────────────────────────────
    def recognizer_for(self, file_id: str) -> Any:
        """The recognizer for ``file_id``'s object: code corrector dictionary from that object's own file names
        (as ``inspector-batch recognize`` does); one per object, created lazily."""
        from inspector_docproc.recognize import PageRecognizer

        obj = str(self.file(file_id).get("object_id") or "")
        rec = self._recognizers.get(obj)
        if rec is None:
            extras: frozenset[str] = frozenset()
            if obj and file_id not in self._registered:
                from inspector_docproc.inputs import object_code_extras

                extras = object_code_extras(self.paths, [obj])
            rec = PageRecognizer(self.cfg, self.exec_cfg, code_extras=extras)
            self._recognizers[obj] = rec
        return rec

    def ocr_region(
        self,
        file_id: str,
        page: int,
        bbox_norm: Sequence[float],
        *,
        dpi: int = 300,
        orientation: bool = False,
    ) -> dict[str, Any]:
        """OCR of a region of the displayed page (contract space) at ``dpi``: ``{"tokens", "lines",
        "render_dpi", "content_rotation", "capped"}`` with boxes normalized to the whole page (see
        :meth:`PageRecognizer.ocr_region`). The text layer is not consulted."""
        rec = self.recognizer_for(file_id)
        return rec.ocr_region(self.open_page(file_id, page), bbox_norm, dpi=dpi, orientation=orientation)

    # ── lifecycle ───────────────────────────────────────────────────────────────────────────────
    def close(self) -> None:
        for rec in self._recognizers.values():
            rec.close()
        self._recognizers.clear()
        while self._docs:
            _, doc = self._docs.popitem()
            doc.close()

    def __enter__(self) -> TokenStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def load_page_tokens(run_dir: Path, file_id: str, page: int) -> dict[str, Any] | None:
    """PageTokens of one page of a run directory (None when the page was not recognized in that run)."""
    p = RunLayout(Path(run_dir)).path("PAGE_TOKENS", file_id=file_id, page=page)
    return load_gz(p) if p.is_file() else None
