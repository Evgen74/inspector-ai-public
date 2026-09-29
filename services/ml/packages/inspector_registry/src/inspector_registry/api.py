"""Entry points for other packages (AG-02A recognition, AG-04 export, AG-10 scoring).

    from inspector_registry.api import open_registry

    reg, resolver = open_registry()
    for r in resolver.resolve_many(reg.files("OBJ-…")):
        if r.readable:            # PRESENT or RECOVERED; never read MISSING_ON_DISK rows
            process(r.path)       # the bytes are the manifest's (sha256 identity)

    reg.is_citable(file_id)            # organizer rules: PDF only, not excluded, not GROUND_TRUTH_INDEX, …
    reg.page_in_range(file_id, page)   # R6
    reg.stage_accepts(file_id, stage)  # R7 (RD_ID_MIXED accepts RD/ID; UNKNOWN never)
    reg.get(excluded_id)               # raises InspectorError("EXCLUDED_FILE_REFERENCED")

The resolved stage of RD_ID_MIXED/UNKNOWN files is in the inventory report
(``runs/<run_id>/inventory/<object_id>.json`` → ``files[].stage_resolved``) or via
``inspector_registry.stages.resolve_stage``.
"""

from __future__ import annotations

from inspector_common.settings import Settings, get_settings
from inspector_registry.cache import RegistryCache
from inspector_registry.manifest import Registry
from inspector_registry.resolver import PathResolver


def open_registry(
    settings: Settings | None = None, *, use_cache: bool = True
) -> tuple[Registry, PathResolver]:
    """Load the manifest registry and a resolver sharing the ``.cache/registry`` sha256 cache."""
    settings = settings or get_settings()
    registry = Registry.load(settings.paths)
    cache = (
        RegistryCache.at(settings.cache_root) if use_cache and settings.cache_root else RegistryCache(None)
    )
    return registry, PathResolver(registry, settings.paths, cache)
