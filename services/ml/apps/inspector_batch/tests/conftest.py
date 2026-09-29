from __future__ import annotations

import pytest

from inspector_common.settings import Settings


@pytest.fixture(scope="session")
def data_paths_or_skip():
    paths = Settings().paths
    if not paths.has_package():
        pytest.skip(f"organizer data not found under {paths.data_root}")
    return paths
