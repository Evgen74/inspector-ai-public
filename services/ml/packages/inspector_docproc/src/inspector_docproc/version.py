"""Recognition pipeline version: the cache key of PageTokens (97: «cache by sha256 + pipeline version»).

``RECOGNITION_VERSION`` is bumped by hand whenever code changes alter PageTokens. The full pipeline
version adds a short hash of everything else that changes output: the recognition config, the model
sha256s, the execution provider (CoreML, CUDA and CPU differ in the last float digits) and the lexicon.
"""

from __future__ import annotations

import hashlib
from typing import Any

from inspector_common.hashing import sha256_json
from inspector_docproc.config import RecognitionConfig

RECOGNITION_VERSION = "2.3.0"


def _lexicon_digest() -> str:
    """Lexicon and word frequencies (both steer the post-correction); the frequency part is appended only
    when the resource exists, so the digest of a lexicon-only install is unchanged."""
    from inspector_docproc.lexicon import FREQ_RESOURCE, RESOURCE

    lex = hashlib.sha256(RESOURCE.read_bytes()).hexdigest()[:16] if RESOURCE.is_file() else "none"
    if FREQ_RESOURCE.is_file():
        lex += "+" + hashlib.sha256(FREQ_RESOURCE.read_bytes()).hexdigest()[:16]
    return lex


def pipeline_fingerprint(
    cfg: RecognitionConfig, model_shas: dict[str, str], provider_mode: str
) -> dict[str, Any]:
    return {
        "recognition_version": RECOGNITION_VERSION,
        "config": cfg.to_dict(),
        "models": dict(sorted(model_shas.items())),
        "provider": provider_mode,
        "lexicon": _lexicon_digest(),
    }


def pipeline_version(cfg: RecognitionConfig, model_shas: dict[str, str], provider_mode: str) -> str:
    digest = sha256_json(pipeline_fingerprint(cfg, model_shas, provider_mode))[:10]
    return f"docproc-{RECOGNITION_VERSION}+{provider_mode}.{digest}"
