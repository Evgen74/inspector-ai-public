"""AG-00 placeholder tests for inspector_compare (AG-04 replaces/extends them)."""

from __future__ import annotations

import inspector_compare
from inspector_compare import batch


def test_package_imports_and_owner() -> None:
    assert inspector_compare.__version__
    assert batch.OWNER == "AG-04"
