"""Resource budget: at most INSPECTOR_RESOURCE_CAP (75 %) of CPUs and memory for every process pool."""

from __future__ import annotations

from inspector_common import resources


def test_cgroup_quota_and_memory_limit(tmp_path) -> None:
    (tmp_path / "cpu.max").write_text("400000 100000\n")
    (tmp_path / "memory.max").write_text(str(8 * 1024**3))
    assert resources._cgroup_cpus(tmp_path) == 4.0
    assert resources._cgroup_memory(tmp_path) == 8 * 1024**3
    (tmp_path / "cpu.max").write_text("max 100000\n")
    (tmp_path / "memory.max").write_text("max\n")
    assert resources._cgroup_cpus(tmp_path) is None and resources._cgroup_memory(tmp_path) is None


def test_worker_budget_caps_cpu_memory_and_explicit_requests(monkeypatch) -> None:
    monkeypatch.setattr(resources, "available_cpus", lambda root=None: 12)
    monkeypatch.setattr(resources, "total_memory_bytes", lambda root=None: 64 * 1024**3)
    monkeypatch.delenv("INSPECTOR_RESOURCE_CAP", raising=False)
    assert resources.cpu_budget() == 9  # 75 % of 12
    assert resources.worker_budget() == 9
    assert resources.worker_budget(threads_per_worker=2) == 4
    assert resources.worker_budget(requested=16) == 9 and resources.worker_budget(requested=3) == 3
    monkeypatch.setattr(resources, "total_memory_bytes", lambda root=None: 4 * 1024**3)
    assert resources.worker_budget() == 3  # 75 % of 4 GB / 1 GB per worker
    monkeypatch.setenv("INSPECTOR_RESOURCE_CAP", "0.5")
    monkeypatch.setattr(resources, "total_memory_bytes", lambda root=None: None)
    assert resources.worker_budget() == 6
    monkeypatch.setattr(resources, "available_cpus", lambda root=None: 1)
    assert resources.worker_budget() == 1  # never below one worker
