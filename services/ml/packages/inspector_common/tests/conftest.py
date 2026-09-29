from __future__ import annotations

import pytest

from inspector_common.settings import Settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def data_paths(settings: Settings):
    """Organizer data paths; tests marked `data` skip when the package is absent."""
    paths = settings.paths
    if not paths.has_package():
        pytest.skip(f"organizer data not found under {paths.data_root}")
    return paths
