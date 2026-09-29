"""Resource budget of the pipeline: at most ``INSPECTOR_RESOURCE_CAP`` (default 0.75) of the machine.

Every process pool (recognition, layout, tables, inventory) takes its size from here, so an analysis never loads the
host above the cap. CPUs honour the affinity mask and a container CPU quota (cgroup v2 ``cpu.max`` / v1 CFS);
memory honours a container limit, and each worker is assumed to need ``INSPECTOR_WORKER_MEM_MB`` (default 1024 MB).
"""

from __future__ import annotations

import math
import os
from pathlib import Path

DEFAULT_CAP = 0.75
DEFAULT_WORKER_MEM_MB = 1024


def resource_cap() -> float:
    try:
        cap = float(os.environ.get("INSPECTOR_RESOURCE_CAP", DEFAULT_CAP))
    except ValueError:
        cap = DEFAULT_CAP
    return min(1.0, max(0.05, cap))


def _cgroup_cpus(root: Path = Path("/sys/fs/cgroup")) -> float | None:
    try:
        quota, period = (root / "cpu.max").read_text().split()[:2]
        if quota != "max":
            return int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        q = int((root / "cpu" / "cpu.cfs_quota_us").read_text())
        p = int((root / "cpu" / "cpu.cfs_period_us").read_text())
        if q > 0 and p > 0:
            return q / p
    except (OSError, ValueError):
        pass
    return None


def available_cpus(root: Path = Path("/sys/fs/cgroup")) -> float:
    try:
        n: float = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    quota = _cgroup_cpus(root)
    return min(n, quota) if quota else n


def _cgroup_memory(root: Path = Path("/sys/fs/cgroup")) -> int | None:
    for f in (root / "memory.max", root / "memory" / "memory.limit_in_bytes"):
        try:
            v = f.read_text().strip()
            if v != "max" and int(v) < 1 << 60:
                return int(v)
        except (OSError, ValueError):
            continue
    return None


def total_memory_bytes(root: Path = Path("/sys/fs/cgroup")) -> int | None:
    phys: int | None = None
    try:
        phys = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        try:  # Windows
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]  # fmt: skip

            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                phys = int(st.ullTotalPhys)
        except Exception:
            phys = None
    limit = _cgroup_memory(root)
    if limit and phys:
        return min(limit, phys)
    return limit or phys


def cpu_budget() -> int:
    """CPUs the pipeline may keep busy: floor(cap × available CPUs), at least 1."""
    return max(1, math.floor(available_cpus() * resource_cap()))


def worker_budget(threads_per_worker: int = 1, requested: int | None = None) -> int:
    """Process-pool size within the budget: CPU (workers × threads ≤ cpu_budget) and memory (cap × RAM / per-worker
    estimate). ``requested`` (an explicit --workers) is honoured only below the budget."""
    n = max(1, cpu_budget() // max(1, threads_per_worker))
    mem = total_memory_bytes()
    if mem:
        try:
            per = int(os.environ.get("INSPECTOR_WORKER_MEM_MB", DEFAULT_WORKER_MEM_MB)) * 1024 * 1024
        except ValueError:
            per = DEFAULT_WORKER_MEM_MB * 1024 * 1024
        n = min(n, max(1, math.floor(mem * resource_cap() / max(per, 1))))
    if requested and requested > 0:
        n = min(n, requested)
    return max(1, n)


__all__ = ["available_cpus", "cpu_budget", "resource_cap", "total_memory_bytes", "worker_budget"]
