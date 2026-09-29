"""Shared fixtures of the inspector_layout tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _private_vocab_cache(tmp_path, monkeypatch) -> None:
    """The room stage caches per-file vocabularies; tests keep theirs in their own tmp dir (xdist-safe)."""
    monkeypatch.setenv("INSPECTOR_LAYOUT_VOCAB_CACHE", str(tmp_path / "vocab-cache"))
