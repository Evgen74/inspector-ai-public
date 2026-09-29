"""Supervised worker pool and detection-server client: faults never stop a run or corrupt a result.

Faults are injected into spawned workers through ``INSPECTOR_DOCPROC_FAULT`` (test-only hook in
``runner._maybe_fault``); pages are synthetic vector pages, so no OCR model is loaded.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np
import pytest

from inspector_docproc.cache import load_gz
from inspector_docproc.config import ExecutionConfig, RecognitionConfig
from inspector_docproc.inputs import FileJob
from inspector_docproc.ocr.detserver import DetectionServerGone, RemoteCanvasRunner
from inspector_docproc.runner import FAULT_ENV, run_recognition
from inspector_docproc.testing import make_pdf

TEXT = [(60, 90 + 18 * i, f"Лист {i} исполнительной документации объекта", 11) for i in range(10)]


def _pdf(path: Path, n: int) -> Path:
    import pymupdf

    out = pymupdf.open()
    single = make_pdf(path.with_suffix(".one.pdf"), TEXT)
    for _ in range(n):
        with pymupdf.open(single) as d:
            out.insert_pdf(d)
    out.save(path)
    return path


def test_crash_hang_and_page_error_are_isolated(tmp_path, monkeypatch) -> None:
    pdf = _pdf(tmp_path / "doc.pdf", 7)
    job = FileJob("F9200", "OBJ-TEST", "ID", "doc.pdf", pdf, "f" * 64, 7)
    monkeypatch.setenv(FAULT_ENV, "crash:F9200:2;hang:F9200:5;raise:F9200:6")
    exec_cfg = ExecutionConfig(providers="cpu", workers=2, page_timeout_s=3.0, warmup=False, keep_awake=False)
    res = run_recognition(
        [job],
        pages_spec=None,
        cfg=RecognitionConfig(),
        exec_cfg=exec_cfg,
        run_dir=tmp_path / "run",
        cache_root=tmp_path / "cache",
        chunk_pages=3,
    )
    by_page = {r["page_no"]: r for r in res.index}
    assert sorted(by_page) == [1, 2, 3, 4, 5, 6, 7]  # every page accounted for exactly once
    assert len(res.index) == 7
    assert by_page[2]["error"] == "WORKER_CRASHED"  # crashed its worker twice (retried once)
    assert by_page[5]["error"] == "PROCESSING_TIMEOUT"  # hung: worker killed, not retried
    assert by_page[6]["error"] == "PAGE_UNREADABLE"  # Python exception: only this page
    for p in (1, 3, 4, 7):  # the rest of the interrupted tasks was requeued and finished
        assert "error" not in by_page[p], by_page[p]
        assert (tmp_path / "run" / "tokens" / "F9200" / f"p{p:05d}.json.gz").is_file()
    sup = res.summary["supervision"]
    assert sup["pages_crashed"] == 1 and sup["pages_timed_out"] == 1
    assert sup["worker_restarts"] == 3  # two crashes + one timeout
    assert res.summary["error_codes"] == {"PAGE_UNREADABLE": 1, "PROCESSING_TIMEOUT": 1, "WORKER_CRASHED": 1}
    doc = load_gz(tmp_path / "run" / "tokens" / "F9200" / "p00004.json.gz")
    assert doc["page_no"] == 4 and doc["page_class"] == "VECTOR"

    # Resume: the failed pages are recomputed (no fault now), the good ones come from the cache.
    monkeypatch.delenv(FAULT_ENV)
    again = run_recognition(
        [job],
        pages_spec=None,
        cfg=RecognitionConfig(),
        exec_cfg=exec_cfg,
        run_dir=tmp_path / "run2",
        cache_root=tmp_path / "cache",
        chunk_pages=3,
    )
    assert again.summary["pages_cached"] == 4 and again.summary["pages_processed"] == 3
    assert again.summary["pages_failed"] == 0


def _shm(size: int) -> shared_memory.SharedMemory:
    return shared_memory.SharedMemory(create=True, size=size)


def test_remote_runner_ignores_stale_answers() -> None:
    """A replacement worker on a slot must never read the answer to its dead predecessor's request."""
    h = w = 8
    inp, out = _shm(3 * h * w * 4), _shm(h * w * 4)
    ours, theirs = mp.Pipe(duplex=True)
    try:
        runner = RemoteCanvasRunner(ours, inp.name, out.name, server_pid=mp.current_process().pid)

        def server() -> None:
            seq, which, hh, ww = theirs.recv()
            assert (which, hh, ww) == ("small", h, w)
            theirs.send((seq - 7, True))  # late answer to an older request
            np.ndarray((1, 1, h, w), np.float32, buffer=out.buf)[...] = 7.0
            theirs.send((seq, True))

        t = threading.Thread(target=server)
        t.start()
        got = runner.run("small", np.zeros((1, 3, h, w), np.float32))
        t.join()
        assert got.shape == (1, 1, h, w) and float(got.min()) == 7.0
    finally:
        for s in (inp, out):
            s.close()
            s.unlink()


def test_remote_runner_detects_a_dead_server() -> None:
    h = w = 8
    inp, out = _shm(3 * h * w * 4), _shm(h * w * 4)
    ours, _theirs = mp.Pipe(duplex=True)
    ctx = mp.get_context("spawn")
    gone = ctx.Process(target=int)  # exits immediately: its pid is a server that no longer runs
    gone.start()
    gone.join()
    try:
        runner = RemoteCanvasRunner(ours, inp.name, out.name, server_pid=gone.pid)
        with pytest.raises(DetectionServerGone):
            runner.run("small", np.zeros((1, 3, h, w), np.float32))
    finally:
        for s in (inp, out):
            s.close()
            s.unlink()
