"""Parallel page recognition for ``inspector-batch recognize`` (R-14): cache, resume, supervision, throughput.

Pages are split into tasks (≤ 8 pages of one file, one open document per task) and processed by worker
processes (spawn), each with its own OCR engine: CPU recogniser at 1 thread and, on a macOS host, the
detector on CoreML through one shared detection server (:mod:`inspector_docproc.ocr.detserver`). Results
are cached by file sha256 + pipeline version and hard-linked into ``runs/<run_id>/tokens/<file_id>/``;
``tokens/index.json`` (contract ``tokens_index``) and ``tokens/index.jsonl`` (one summary per page) list every
page, and ``recognize_summary.json`` reports counts, stage timings and
throughput.

Supervision (the frozen hidden run is one shot and must finish): the supervisor talks to every worker over
a private pipe and knows which page each worker is on.
- A worker that dies (native crash, killed) loses only its current page, which is retried in a fresh
  worker; after ``max_page_attempts`` deaths on the same page it is reported as ``WORKER_CRASHED``. The rest
  of its task is requeued.
- A page that runs longer than ``page_timeout_s`` has its worker killed and is reported as
  ``PROCESSING_TIMEOUT`` (not retried).
- If the CoreML detection server dies, the workers and the server are rebuilt (at most
  ``max_server_restarts`` times); pages in flight count an attempt.
- A Python exception on a page is ``PAGE_UNREADABLE`` for that page only; an unreadable file is
  ``FILE_CORRUPTED``. Nothing of this is fatal for the run, and a rerun resumes from the cache.
"""

from __future__ import annotations

import contextlib
import logging
import math
import multiprocessing as mp
import os
import platform
import shutil
import subprocess
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any

import orjson

from inspector_common.runlayout import RunLayout, artifact_path
from inspector_docproc.cache import TokenCache, link_into, load_gz
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.inputs import FileJob, parse_pages
from inspector_docproc.recognize import OCR_SOURCES, PageRecognizer

log = logging.getLogger("inspector_docproc.runner")

_W: dict[str, Any] = {}
EXIT_SERVER_GONE = 75  # worker exit code: the detection server disappeared (not the page's fault)
FAULT_ENV = "INSPECTOR_DOCPROC_FAULT"  # test-only fault injection, see _maybe_fault


def _keep_awake_command(system: str, pid: int) -> list[str] | None:
    """The command that holds a no-sleep assertion for ``pid``, or None when the platform has no such tool
    (a headless Linux server without systemd/logind simply never suspends)."""
    if system == "Darwin":
        exe = shutil.which("caffeinate") or (
            "/usr/bin/caffeinate" if Path("/usr/bin/caffeinate").is_file() else None
        )
        return [exe, "-i", "-s", "-w", str(pid)] if exe else None
    if system == "Linux":
        inhibit, tail = shutil.which("systemd-inhibit"), shutil.which("tail")
        if inhibit and tail:
            return [inhibit, "--what=sleep:idle", "--who=inspector", "--why=recognition batch", "--mode=block",
                    tail, f"--pid={pid}", "-f", "/dev/null"]  # fmt: skip
    return None


@contextmanager
def keep_awake(enabled: bool = True) -> Iterator[bool]:
    """Hold a power assertion while a batch runs: macOS ``caffeinate -i -s -w <pid>``, Linux
    ``systemd-inhibit`` (a ``tail --pid`` child keeps the inhibitor for as long as this process lives).

    An idle Mac goes to sleep in the middle of a long run (measured: a 100-page run suspended for 16 min
    at 03:15), which stretches a frozen multi-hour run unpredictably. The assertion only prevents idle
    system sleep while this process lives; it changes no system setting and ends with the process. It is a
    no-op elsewhere, and yields whether an assertion is held.
    """
    proc: subprocess.Popen | None = None
    cmd = _keep_awake_command(platform.system(), os.getpid()) if enabled else None
    if cmd:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.warning("recognize.keep_awake_failed", extra={"error": str(exc)})
    try:
        yield proc is not None
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def auto_chunk(n_pages: int, workers: int, chunk_pages: int | None) -> int:
    """Pages per task: the explicit value, or ≤ 8 pages with at least 3 tasks per worker (load balance:
    with one task per worker the slowest chunk sets the wall time of a small run)."""
    if chunk_pages:
        return max(1, chunk_pages)
    return max(1, min(8, math.ceil(n_pages / max(1, 3 * workers))))


def page_summary(doc: dict[str, Any]) -> dict[str, Any]:
    ext = doc.get("ext") or {}
    ocr = ext.get("ocr") or {}
    zones = Counter(z.get("kind") for z in doc.get("zones") or [])
    return {
        "file_id": doc["file_id"],
        "page_no": doc["page_no"],
        "page_class": doc.get("page_class"),
        "text_source": doc.get("text_source"),
        "quality_flag": doc.get("quality_flag"),
        "tokens": len(doc.get("tokens", [])),
        "ocr_tokens": sum(1 for t in doc.get("tokens", []) if t.get("source") in OCR_SOURCES),
        "mean_conf": doc.get("mean_conf"),
        "coverage": doc.get("coverage"),
        "content_rotation": (doc.get("page") or {}).get("content_rotation"),
        "render_dpi": (doc.get("page") or {}).get("render_dpi"),
        "warnings": doc.get("warnings", []),
        "fallback_used": bool(ocr.get("fallback_used")),
        "route": (ext.get("route") or {}).get("reason"),
        "timings_ms": doc.get("timings_ms", {}),
        "rotate": (doc.get("page") or {}).get("rotate"),
        "text_sources": sorted({t.get("source") for t in doc.get("tokens", []) if t.get("source")}),
        "has_layers": bool(doc.get("layers")),
        "zones": dict(sorted(zones.items())),
    }


def tokens_index(
    run_id: str,
    pipeline_version: str,
    jobs: list[FileJob],
    pages_total: dict[str, int],
    index: list[dict[str, Any]],
) -> dict[str, Any]:
    """``tokens/index.json`` (contract ``tokens_index``): per file, the recognized pages with their class,
    text sources, quality and rotation, so layout/tables can plan work without opening every page."""
    import datetime as _dt

    by_file: dict[str, list[dict[str, Any]]] = {}
    for s in index:
        if "error" in s:
            continue
        entry: dict[str, Any] = {
            "pdf_page_number": s["page_no"],
            "path": artifact_path("PAGE_TOKENS", file_id=s["file_id"], page=s["page_no"]),
            "tokens": int(s.get("tokens") or 0),
            "has_layers": bool(s.get("has_layers")),
            "cache_hit": bool(s.get("cache_hit")),
        }
        for key, src in (
            ("page_class", "page_class"),
            ("quality_flag", "quality_flag"),
            ("rotation", "rotate"),
        ):
            if s.get(src) is not None:
                entry[key] = s[src]
        if s.get("text_sources"):
            entry["text_sources"] = list(s["text_sources"])
        by_file.setdefault(s["file_id"], []).append(entry)
    files = []
    for job in jobs:
        if job.file_id not in pages_total:
            continue
        stage = job.stage if job.stage in ("PD", "RD", "ID") else None  # mixed/unknown: AG-01 resolves
        files.append(
            {
                "file_id": job.file_id,
                "object_id": job.object_id,
                "file_sha256": job.sha256,
                "stage": stage,
                "pages_total": pages_total[job.file_id],
                "pages": sorted(by_file.get(job.file_id, []), key=lambda e: e["pdf_page_number"]),
            }
        )
    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "pipeline_version": pipeline_version,
        "generated_at": now,
        "files": files,
    }


def _error(file_id: str, page_no: int, code: str, detail: str) -> dict[str, Any]:
    return {"file_id": file_id, "page_no": page_no, "error": code, "detail": detail[:300]}


# ── Worker side ──────────────────────────────────────────────────────────────────────────────


def _worker_init(
    cfg: RecognitionConfig,
    exec_cfg: ExecutionConfig,
    cache_root: str,
    pipeline_version: str,
    extras: frozenset[str],
    server_args: tuple | None = None,
    in_process: bool = False,
) -> None:
    import cv2
    import pymupdf

    from inspector_docproc.ocr.engine import OcrEngine

    pymupdf.TOOLS.mupdf_display_errors(False)
    if not in_process:  # a worker process owns its globals; the in-process path must not change the caller's
        cv2.setNumThreads(max(1, exec_cfg.threads))  # workers are processes: no nested thread pools
        logging.getLogger().setLevel(logging.WARNING)
    engine = None
    if server_args is not None:
        from inspector_docproc.ocr.detserver import attach_client

        engine = OcrEngine(
            cfg=cfg.ocr,
            providers="coreml",
            threads=exec_cfg.threads,
            remote=attach_client(server_args),
            strict_providers=exec_cfg.strict_providers,
        )
    _W["rec"] = PageRecognizer(cfg, exec_cfg, engine=engine, code_extras=extras)
    if exec_cfg.warmup:
        _W["rec"].engine.warmup(medium=cfg.ocr.medium_mode != "off")  # load models before the first page
    _W["cache"] = TokenCache(Path(cache_root), pipeline_version)


def _maybe_fault(file_id: str, page_no: int) -> None:
    """Test-only fault injection: ``INSPECTOR_DOCPROC_FAULT="crash:F9100:2;hang:F9100:3"``."""
    spec = os.environ.get(FAULT_ENV)
    if not spec:
        return
    for item in spec.split(";"):
        kind, fid, page = item.split(":")
        if fid == file_id and int(page) == page_no:
            if kind == "crash":
                os._exit(99)
            if kind == "hang":
                time.sleep(3600)
            if kind == "raise":
                raise RuntimeError("injected page failure")


def _iter_pages(
    file_id: str, path: str, sha256: str, pages: list[int], on_start: Callable[[int], None] | None = None
) -> Iterator[dict[str, Any]]:
    """Recognise ``pages`` of one file, caching each result; yields one summary (or error) per page."""
    import pymupdf

    from inspector_docproc.ocr.detserver import DetectionServerGone

    rec: PageRecognizer = _W["rec"]
    cache: TokenCache = _W["cache"]
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # corrupt file: every page fails the same way
        for p in pages:
            yield _error(file_id, p, "FILE_CORRUPTED", f"{type(exc).__name__}: {exc}")
        return
    with doc:
        for p in pages:
            if on_start is not None:
                on_start(p)
            t0, c0 = time.perf_counter(), time.process_time()
            try:
                _maybe_fault(file_id, p)
                result = rec.recognize_page(doc, p, file_id=file_id, file_sha256=sha256)
                cpath = cache.put(sha256, p, result)
                s = page_summary(result)
                s.update(cache_path=str(cpath), cache_hit=False)
            except DetectionServerGone:
                raise  # infrastructure, not the page: the supervisor rebuilds the server
            except Exception as exc:
                s = _error(file_id, p, "PAGE_UNREADABLE", f"{type(exc).__name__}: {exc}")
            s["wall_s"] = round(time.perf_counter() - t0, 3)
            s["cpu_s"] = round(time.process_time() - c0, 3)
            yield s


def _work(file_id: str, path: str, sha256: str, pages: list[int]) -> list[dict[str, Any]]:
    """In-process variant (one worker, no subprocess)."""
    return list(_iter_pages(file_id, path, sha256, pages))


def _worker_main(conn: Any, init_args: tuple) -> None:
    """Worker process loop: ``("task", file_id, path, sha, pages)`` in; start/page/idle messages out."""
    from inspector_docproc.ocr.detserver import DetectionServerGone

    try:
        _worker_init(*init_args)
    except BaseException as exc:
        code = getattr(exc, "code", None)
        details = getattr(exc, "details", None)
        conn.send(("init_error", code, details, f"{type(exc).__name__}: {exc}"[:500]))
        return
    conn.send(("ready",))
    try:
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                return  # the supervisor is gone
            if msg is None:
                return
            _, file_id, path, sha, pages = msg
            try:
                for s in _iter_pages(file_id, path, sha, pages, on_start=lambda p: conn.send(("start", p))):
                    conn.send(("page", s))
            except DetectionServerGone:
                os._exit(EXIT_SERVER_GONE)
            conn.send(("idle",))
    finally:
        release_worker()


def release_worker() -> None:
    """Release this process's recognizer (its ONNX Runtime sessions) before the interpreter exits."""
    rec = _W.pop("rec", None)
    if rec is not None:
        rec.close()


# ── Supervisor ───────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Task:
    file_id: str
    path: str
    sha256: str
    pages: list[int]


@dataclass(slots=True)
class _Slot:
    wid: int
    proc: Any
    conn: Any
    started: float
    state: str = "starting"  # starting | idle | busy
    task: _Task | None = None
    page: int | None = None
    page_t0: float = 0.0


@dataclass(slots=True)
class _SupervisorStats:
    worker_restarts: int = 0
    server_restarts: int = 0
    pages_timed_out: int = 0
    pages_crashed: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


class WorkerInitError(RuntimeError):
    """A worker could not start (e.g. a model is missing); raised by the supervisor, fatal for the run."""

    def __init__(self, code: str | None, details: dict | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _supervise(
    tasks: list[_Task],
    *,
    workers: int,
    exec_cfg: ExecutionConfig,
    init_args: Callable[[Any, int], tuple],
    make_server: Callable[[], Any] | None,
    collect: Callable[[list[dict[str, Any]]], None],
    stats: _SupervisorStats,
) -> None:
    """Run ``tasks`` on ``workers`` supervised processes (see the module docstring)."""
    ctx = mp.get_context("spawn")
    queue: deque[_Task] = deque(tasks)
    attempts: Counter[tuple[str, int]] = Counter()
    start_failures = 0

    def fail(fid: str, page: int, code: str, detail: str) -> None:
        collect([_error(fid, page, code, detail)])

    while queue:
        server = make_server() if make_server is not None else None
        slots: dict[int, _Slot] = {}

        def spawn(wid: int, server: Any = server, slots: dict[int, _Slot] = slots) -> None:
            parent, child = ctx.Pipe(duplex=True)
            proc = ctx.Process(
                target=_worker_main, args=(child, init_args(server, wid)), daemon=True, name=f"docproc-w{wid}"
            )
            proc.start()
            child.close()
            slots[wid] = _Slot(wid, proc, parent, time.monotonic())

        def lost(slot: _Slot, reason: str, slots: dict[int, _Slot] = slots) -> None:
            """The worker of ``slot`` is gone: settle its current page, requeue the rest of its task."""
            task, page = slot.task, slot.page
            with contextlib.suppress(OSError):
                slot.conn.close()
            del slots[slot.wid]
            stats.events.append({"worker": slot.wid, "reason": reason, "file_id": task and task.file_id,
                                 "page_no": page, "exitcode": slot.proc.exitcode})  # fmt: skip
            log.warning(
                "recognize.worker_lost",
                extra={"reason": reason, "file_id": task and task.file_id, "page_no": page,
                       "exitcode": slot.proc.exitcode},
            )  # fmt: skip
            if task is None:
                return
            rest = list(task.pages)
            if page is not None and page in rest:
                key = (task.file_id, page)
                if reason == "timeout":
                    rest.remove(page)
                    stats.pages_timed_out += 1
                    fail(
                        task.file_id,
                        page,
                        "PROCESSING_TIMEOUT",
                        f"страница дольше {exec_cfg.page_timeout_s:.0f} с",
                    )
                else:
                    attempts[key] += 1
                    if attempts[key] >= exec_cfg.max_page_attempts:
                        rest.remove(page)
                        stats.pages_crashed += 1
                        fail(task.file_id, page, "WORKER_CRASHED",
                             f"процесс обработки завершился аварийно {attempts[key]} раза ({reason})")  # fmt: skip
            if rest:
                queue.append(_Task(task.file_id, task.path, task.sha256, rest))

        for wid in range(min(workers, len(queue))):
            spawn(wid)
        server_dead = False
        try:
            while queue or any(s.state == "busy" for s in slots.values()):
                for s in list(slots.values()):  # dispatch
                    if s.state == "idle" and queue:
                        s.task = queue.popleft()
                        s.state, s.page = "busy", None
                        s.conn.send(("task", s.task.file_id, s.task.path, s.task.sha256, s.task.pages))
                by_conn = {id(s.conn): s for s in slots.values()}
                for conn in wait([s.conn for s in slots.values()], timeout=1.0):
                    s = by_conn[id(conn)]
                    if s.wid not in slots:
                        continue
                    try:
                        msg = conn.recv()
                    except (EOFError, OSError):
                        s.proc.join(timeout=5)
                        reason = "server_gone" if s.proc.exitcode == EXIT_SERVER_GONE else "crash"
                        if s.state == "starting" and reason == "crash":
                            start_failures += 1
                            if start_failures > 3:
                                raise WorkerInitError(
                                    None, None, "процессы обработки аварийно завершаются при запуске"
                                ) from None
                        lost(s, reason)
                        if reason != "server_gone":
                            stats.worker_restarts += 1
                            spawn(s.wid)
                        continue
                    kind = msg[0]
                    if kind == "ready":
                        s.state = "idle"
                    elif kind == "start":
                        s.page, s.page_t0 = msg[1], time.monotonic()
                    elif kind == "page":
                        summary = msg[1]
                        if s.task is not None and summary["page_no"] in s.task.pages:
                            s.task.pages.remove(summary["page_no"])
                        s.page = None
                        collect([summary])
                    elif kind == "idle":
                        s.state, s.task, s.page = "idle", None, None
                    elif kind == "init_error":
                        raise WorkerInitError(msg[1], msg[2], msg[3])
                now = time.monotonic()
                for s in list(slots.values()):  # watchdog
                    if s.state == "busy" and s.page is not None and now - s.page_t0 > exec_cfg.page_timeout_s:
                        s.proc.kill()
                        s.proc.join(timeout=5)
                        lost(s, "timeout")
                        stats.worker_restarts += 1
                        spawn(s.wid)
                    elif s.state == "starting" and now - s.started > exec_cfg.worker_start_timeout_s:
                        s.proc.kill()
                        s.proc.join(timeout=5)
                        raise WorkerInitError(None, None, "процесс обработки не запустился вовремя")
                if server is not None and not server.alive():
                    server_dead = True
                    break
        finally:
            for s in list(slots.values()):
                with contextlib.suppress(OSError):
                    s.conn.send(None)
            deadline = time.monotonic() + 10
            for s in list(slots.values()):
                s.proc.join(timeout=max(0.1, deadline - time.monotonic()))
                if s.proc.is_alive():
                    s.proc.kill()
                    s.proc.join(timeout=5)
            if server is not None:
                server.close()
        if not server_dead:
            break
        # The detection server died: settle every slot's current page (an attempt each) and rebuild.
        stats.server_restarts += 1
        log.error("recognize.server_died", extra={"restart": stats.server_restarts})
        for s in list(slots.values()):
            lost(s, "server_died")
        if stats.server_restarts > exec_cfg.max_server_restarts:
            while queue:
                t = queue.popleft()
                for p in t.pages:
                    fail(
                        t.file_id,
                        p,
                        "WORKER_CRASHED",
                        "сервер детекции CoreML неоднократно завершался аварийно",
                    )
            break


# ── Entry point ──────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RecognizeResult:
    summary: dict[str, Any]
    index: list[dict[str, Any]]


def run_recognition(
    jobs: list[FileJob],
    *,
    pages_spec: str | None,
    cfg: RecognitionConfig,
    exec_cfg: ExecutionConfig,
    run_dir: Path,
    cache_root: Path,
    code_extras: frozenset[str] = frozenset(),
    use_cache: bool = True,
    chunk_pages: int | None = None,
    progress_every_s: float = 20.0,
    pages_by_file: dict[str, str] | None = None,
) -> RecognizeResult:
    """Recognise the selected pages of ``jobs``; ``chunk_pages`` None = :func:`auto_chunk`.

    ``pages_by_file`` (file_id → page spec such as «3,17-20») overrides ``pages_spec`` per file, so pages of
    several files share one worker pool (layout/tables re-reads, sampled timing runs)."""
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    probe = PageRecognizer(cfg, exec_cfg, code_extras=code_extras)
    pv = probe.pipeline_version()
    cache = TokenCache(cache_root, pv)
    layout = RunLayout(run_dir)
    pages_total: dict[str, int] = {}
    t_plan = time.perf_counter()
    index: list[dict[str, Any]] = []
    file_errors: list[dict[str, Any]] = []
    todo_by_job: list[tuple[FileJob, list[int]]] = []
    n_pages_total = 0
    for job in jobs:
        try:
            with pymupdf.open(job.path) as doc:
                n = doc.page_count
        except Exception as exc:  # a corrupt file is reported, never fatal for the run
            file_errors.append(
                {
                    "file_id": job.file_id,
                    "error": "FILE_CORRUPTED",
                    "detail": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
            continue
        spec = pages_by_file.get(job.file_id, pages_spec) if pages_by_file else pages_spec
        pages = parse_pages(spec, n)
        pages_total[job.file_id] = n
        n_pages_total += len(pages)
        todo: list[int] = []
        for p in pages:
            cached = cache.path(job.sha256, p)
            if use_cache and cached.is_file():
                try:
                    s = page_summary(load_gz(cached))
                except (OSError, ValueError, EOFError):
                    todo.append(p)
                    continue
                link_into(cached, layout.path("PAGE_TOKENS", file_id=job.file_id, page=p))
                s.update(cache_path=str(cached), cache_hit=True, wall_s=0.0, cpu_s=0.0)
                index.append(s)
            else:
                todo.append(p)
        if todo:
            todo_by_job.append((job, todo))
    n_todo = sum(len(t) for _, t in todo_by_job)
    mode = probe.engine_mode()
    chunk = auto_chunk(n_todo, exec_cfg.resolved_workers(mode), chunk_pages)
    tasks = [
        _Task(job.file_id, str(job.path), job.sha256, todo[i : i + chunk])
        for job, todo in todo_by_job
        for i in range(0, len(todo), chunk)
    ]
    plan_s = time.perf_counter() - t_plan
    workers = max(1, min(exec_cfg.resolved_workers(mode), len(tasks))) if tasks else 0
    if mode == "cuda" and tasks and exec_cfg.workers > exec_cfg.max_gpu_workers:
        log.info("recognize.gpu_workers_capped",
                 extra={"requested": exec_cfg.workers, "workers": workers, "cap": exec_cfg.max_gpu_workers})  # fmt: skip
    log.info(
        "recognize.plan",
        extra={"files": len(jobs), "pages": n_pages_total, "cached": n_pages_total - n_todo, "to_process": n_todo,
               "tasks": len(tasks), "chunk_pages": chunk, "workers": workers, "pipeline_version": pv,
               "provider_mode": probe.engine_mode()},
    )  # fmt: skip

    t0 = time.perf_counter()
    t0_clock = time.time()
    done_pages = 0
    last_report = t0

    def collect(results: list[dict[str, Any]]) -> None:
        nonlocal done_pages, last_report
        for s in results:
            if "cache_path" in s:
                link_into(
                    Path(s["cache_path"]), layout.path("PAGE_TOKENS", file_id=s["file_id"], page=s["page_no"])
                )
            index.append(s)
            done_pages += 1
        now = time.perf_counter()
        if now - last_report >= progress_every_s:
            rate = done_pages / max(now - t0, 1e-6) * 60
            log.info(
                "recognize.progress",
                extra={"done": done_pages, "total": n_todo, "pages_per_min": round(rate, 1)},
            )
            last_report = now

    sup = _SupervisorStats()
    use_server = probe.engine_mode() == "coreml" and workers > 1
    medium = cfg.ocr.medium_mode != "off"

    def make_server() -> Any:
        # one process owns the CoreML detector sessions (GPU memory), the workers stay on the CPU
        from inspector_docproc.ocr.detserver import DetServer

        return DetServer(workers, warm_medium=medium, strict=exec_cfg.strict_providers)

    def init_args(server: Any, wid: int) -> tuple:
        return (cfg, exec_cfg, str(cache_root), pv, code_extras, server.client_args(wid) if server else None)

    with keep_awake(exec_cfg.keep_awake and bool(tasks)) as awake:
        if tasks and workers == 1:
            _worker_init(cfg, exec_cfg, str(cache_root), pv, code_extras, in_process=True)
            try:
                for t in tasks:
                    collect(_work(t.file_id, t.path, t.sha256, t.pages))
            finally:
                release_worker()
        elif tasks:
            _supervise(
                tasks,
                workers=workers,
                exec_cfg=exec_cfg,
                init_args=init_args,
                make_server=make_server if use_server else None,
                collect=collect,
                stats=sup,
            )
    wall = time.perf_counter() - t0  # monotonic: excludes time the machine spent asleep
    wall_clock = time.time() - t0_clock

    index.sort(key=lambda s: (s["file_id"], s["page_no"]))
    index_json = layout.ensure_parent("TOKENS_INDEX")
    (index_json.parent / "index.jsonl").write_bytes(b"".join(orjson.dumps(s) + b"\n" for s in index))
    index_json.write_bytes(
        orjson.dumps(tokens_index(run_dir.name, pv, jobs, pages_total, index), option=orjson.OPT_INDENT_2)
    )
    processed = [s for s in index if not s.get("cache_hit") and "error" not in s]
    errors = [s for s in index if "error" in s]
    ocr_pages = [s for s in processed if s.get("ocr_tokens") or (s.get("timings_ms") or {}).get("det_ms")]
    classes = Counter(s.get("page_class") for s in index if "error" not in s)
    stage_ms: Counter[str] = Counter()
    for s in processed:
        for k, v in (s.get("timings_ms") or {}).items():
            stage_ms[k] += v
    summary = {
        "pipeline_version": pv,
        "provider_mode": probe.engine_mode(),
        "providers_requested": exec_cfg.providers,
        "strict_providers": exec_cfg.strict_providers,
        "workers": workers,
        "threads_per_worker": exec_cfg.threads,
        "files": len(jobs),
        "pages_total": n_pages_total,
        "pages_cached": sum(1 for s in index if s.get("cache_hit")),
        "pages_processed": len(processed),
        "pages_with_ocr": len(ocr_pages),
        "pages_failed": len(errors),
        "page_classes": dict(classes.most_common()),
        "wall_s": round(wall, 2),
        "wall_clock_s": round(wall_clock, 2),
        "suspended_s": round(max(0.0, wall_clock - wall), 2),  # > 0: the machine slept during the run
        "keep_awake": awake,
        "chunk_pages": chunk,
        "plan_s": round(plan_s, 2),
        "pages_per_min": round(len(processed) / wall * 60, 1) if wall > 0 and processed else None,
        "ocr_pages_per_min": round(len(ocr_pages) / wall * 60, 1) if wall > 0 and ocr_pages else None,
        "cpu_s_total": round(sum(s.get("cpu_s", 0.0) for s in processed), 1),
        "stage_ms_total": {k: round(v, 1) for k, v in sorted(stage_ms.items())},
        "fallback_used_pages": sum(1 for s in processed if s.get("fallback_used")),
        "rotated_pages": sum(1 for s in processed if s.get("content_rotation")),
        "warnings": dict(Counter(w for s in index for w in s.get("warnings", [])).most_common()),
        "zones": dict(sum((Counter(s.get("zones") or {}) for s in index), Counter()).most_common()),
        "supervision": {
            "worker_restarts": sup.worker_restarts,
            "server_restarts": sup.server_restarts,
            "pages_timed_out": sup.pages_timed_out,
            "pages_crashed": sup.pages_crashed,
            "events": sup.events[:50],
        },
        "error_codes": dict(Counter(s["error"] for s in errors).most_common()),
        "file_errors": file_errors,
        "errors": errors[:50],
    }
    layout.ensure_parent("RECOGNIZE_SUMMARY").write_bytes(orjson.dumps(summary, option=orjson.OPT_INDENT_2))
    return RecognizeResult(summary, index)
