"""Content hashes of the reference data a compare run depends on (part of its ``config_hash``)."""

from __future__ import annotations

from inspector_common.hashing import sha256_file
from inspector_common.params import SEED_FILES, load_params, seed_dir
from inspector_compare.recommendations import load_templates


def seed_hashes() -> dict[str, str]:
    registry = load_params()
    out = {"params_content_sha256": registry.content_sha256}
    if registry.overrides.get("sha256"):
        out["matrix_overrides_sha256"] = str(registry.overrides["sha256"])
    for key, name in SEED_FILES.items():
        path = seed_dir() / name
        if path.is_file():
            out[f"seed_{key}_sha256"] = sha256_file(path)
    templates = load_templates()
    if templates.sha256:
        out["recommendation_templates_sha256"] = templates.sha256
    return out
