"""One GPU owner for all workers: a CoreML detection server fed through shared memory.

Why: a CoreML detector session pins its buffers in wired memory — measured 1.2 GB for v6-small at a
1600² canvas, ~2.3 GB more at 3200², and ~5 GB more for v6-medium at 3200² (≈ 8 GB per process with both
detectors). Ten worker processes cannot each own those sessions (the first attempt wired 24 GB and the
machine thrashed). So one server process owns the CoreML sessions and runs only ``session.run``; the
workers keep everything else (rendering, pre/post-processing, recognition on the CPU).

Protocol (one slot per worker; a slot = an input block, an output block and a private duplex pipe):
- the worker writes the normalised canvas (float32 [1, 3, H, W], H×W one of ``DET_CANVASES``) into its
  slot's input block and sends ``(seq, detector, H, W)`` on its pipe;
- the server runs the matching static-shape session, writes the probability map (float32 [1, 1, H, W])
  into the slot's output block and answers ``(seq, True)`` (or ``(seq, error text)``).

Failure handling (the frozen hidden run must never hang):
- no lock is shared between processes (no ``multiprocessing.Queue``): a worker killed mid-request cannot
  block the others, and one small message is a single atomic pipe write;
- ``seq`` is unique per worker incarnation, so a replacement worker on the same slot discards the late
  answer to its dead predecessor's request (the output block is read only after the matching answer);
- a worker waiting for an answer checks every second that the server is alive and raises
  :class:`DetectionServerGone` otherwise (the supervisor then rebuilds the server and the workers);
- the server exits when its parent process is gone.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as mp
import os
import random
import time
import traceback
from multiprocessing import shared_memory
from multiprocessing.connection import wait
from typing import Any

import numpy as np

from inspector_docproc.ocr.engine import DET_CANVASES

log = logging.getLogger("inspector_docproc.detserver")

_MAX_H, _MAX_W = max(c[0] for c in DET_CANVASES), max(c[1] for c in DET_CANVASES)
IN_BYTES = 3 * _MAX_H * _MAX_W * 4
OUT_BYTES = _MAX_H * _MAX_W * 4
POLL_S = 1.0


class DetectionServerGone(RuntimeError):
    """The detection server process is not running any more (the caller's page cannot be finished)."""


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by someone else (cannot happen for our child, kept for safety)
        return True
    return True


def _serve(
    conns: list[Any],
    control: Any,
    in_names: list[str],
    out_names: list[str],
    threads: int,
    warm_medium: bool,
    parent_pid: int,
    strict: bool = False,
) -> None:
    import pymupdf  # noqa: F401  (keeps the import graph identical to the workers)

    from inspector_docproc.models import ROLE_DET_FALLBACK, ROLE_DET_PRIMARY, ModelRegistry

    registry = ModelRegistry(strict=strict)
    specs = {"small": registry.by_role(ROLE_DET_PRIMARY), "medium": registry.by_role(ROLE_DET_FALLBACK)}
    sessions: dict[tuple[str, int, int], Any] = {}
    ins = [shared_memory.SharedMemory(name=n) for n in in_names]
    outs = [shared_memory.SharedMemory(name=n) for n in out_names]
    slot_of = {id(c): i for i, c in enumerate(conns)}
    busy = 0.0
    calls = 0

    def session(which: str, h: int, w: int) -> Any:
        key = (which, h, w)
        sess = sessions.get(key)
        if sess is None:
            sess = registry.session(
                specs[which], mode="coreml", threads=threads, static_dims={0: 1, 2: h, 3: w}
            )
            sessions[key] = sess
        return sess

    warm = [("small", DET_CANVASES)] + ([("medium", DET_CANVASES[:1])] if warm_medium else [])
    for which, canvases in warm:  # compile/load before the first page (medium: 1600² union pass only)
        for h, w in canvases:
            sess = session(which, h, w)
            sess.run(None, {sess.get_inputs()[0].name: np.ones((1, 3, h, w), np.float32)})
    live = list(conns)
    try:
        while True:
            if os.getppid() != parent_pid:  # orphaned: the supervisor is gone
                break
            ready = wait([control, *live], timeout=POLL_S)
            if control in ready:
                break
            for conn in ready:
                try:
                    msg = conn.recv()
                except (EOFError, OSError):
                    live.remove(conn)  # the parent closed this slot
                    continue
                slot = slot_of[id(conn)]
                seq, which, h, w = msg
                try:
                    sess = session(which, h, w)
                    x = np.ndarray((1, 3, h, w), dtype=np.float32, buffer=ins[slot].buf)
                    t0 = time.perf_counter()
                    y = sess.run(None, {sess.get_inputs()[0].name: x})[0]
                    busy += time.perf_counter() - t0
                    calls += 1
                    np.ndarray((1, 1, h, w), dtype=np.float32, buffer=outs[slot].buf)[...] = y
                    conn.send((seq, True))
                except Exception:  # report to the waiting worker instead of dying
                    conn.send((seq, traceback.format_exc(limit=3)))
    finally:
        sessions.clear()  # release the CoreML sessions before the interpreter exits
        for s in ins + outs:
            s.close()
        log.info("detserver.stopped", extra={"calls": calls, "gpu_busy_s": round(busy, 2)})


class DetServer:
    """Parent-side handle: shared memory blocks, one pipe per slot, the server process."""

    def __init__(
        self, n_slots: int, threads: int = 2, warm_medium: bool = True, strict: bool = False
    ) -> None:
        ctx = mp.get_context("spawn")
        pipes = [ctx.Pipe(duplex=True) for _ in range(n_slots)]
        self._server_conns = [a for a, _ in pipes]
        self.client_conns = [b for _, b in pipes]
        control_srv, self._control = ctx.Pipe(duplex=True)
        self.ins = [shared_memory.SharedMemory(create=True, size=IN_BYTES) for _ in range(n_slots)]
        self.outs = [shared_memory.SharedMemory(create=True, size=OUT_BYTES) for _ in range(n_slots)]
        self.proc = ctx.Process(
            target=_serve,
            args=(
                self._server_conns,
                control_srv,
                [s.name for s in self.ins],
                [s.name for s in self.outs],
                threads,
                warm_medium,
                os.getpid(),
                strict,
            ),
            daemon=True,
            name="docproc-detserver",
        )
        self.proc.start()
        control_srv.close()

    @property
    def pid(self) -> int:
        return int(self.proc.pid or 0)

    def alive(self) -> bool:
        return self.proc.is_alive()

    def client_args(self, slot: int) -> tuple[Any, ...]:
        """Picklable-at-spawn arguments of one slot for :func:`attach_client` in a worker process."""
        return (self.client_conns[slot], self.ins[slot].name, self.outs[slot].name, self.pid)

    def close(self, timeout: float = 30.0) -> None:
        try:
            if self.proc.is_alive():
                with contextlib.suppress(OSError):
                    self._control.send(None)
                self.proc.join(timeout=timeout)
        finally:
            if self.proc.is_alive():
                self.proc.terminate()
                self.proc.join(timeout=5)
            for c in (*self._server_conns, *self.client_conns, self._control):
                c.close()
            for s in self.ins + self.outs:
                s.close()
                s.unlink()


class RemoteCanvasRunner:
    """Worker-side replacement of ``_SessionPool.run_static`` for the detectors (one slot)."""

    def __init__(self, conn: Any, in_name: str, out_name: str, server_pid: int) -> None:
        self.conn = conn
        self.server_pid = server_pid
        self.inp = shared_memory.SharedMemory(name=in_name)
        self.out = shared_memory.SharedMemory(name=out_name)
        self.seq = random.getrandbits(40) << 20  # unique per incarnation: stale answers are recognisable
        self.wait_s = 0.0

    def run(self, which: str, canvas: np.ndarray) -> np.ndarray:
        _, _, h, w = canvas.shape
        np.ndarray((1, 3, h, w), dtype=np.float32, buffer=self.inp.buf)[...] = canvas
        self.seq += 1
        t0 = time.perf_counter()
        self.conn.send((self.seq, which, h, w))
        while True:
            if self.conn.poll(POLL_S):
                seq, ok = self.conn.recv()
                if seq == self.seq:
                    break
                continue  # the late answer to a dead predecessor's request on this slot
            if not pid_alive(self.server_pid):
                raise DetectionServerGone(f"detection server (pid {self.server_pid}) is not running")
        self.wait_s += time.perf_counter() - t0
        if ok is not True:
            raise RuntimeError(f"detection server error: {ok}")
        return np.array(np.ndarray((1, 1, h, w), dtype=np.float32, buffer=self.out.buf))


_CLIENT: RemoteCanvasRunner | None = None


def attach_client(args: tuple[Any, ...]) -> RemoteCanvasRunner:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = RemoteCanvasRunner(*args)
    return _CLIENT
