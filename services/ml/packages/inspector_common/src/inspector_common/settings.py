"""Runtime settings (environment variables with the ``INSPECTOR_`` prefix, see .env.example).

Local-only runtime: nothing here points to a network service except the local PostgreSQL/Redis
used by the web mode. The batch mode needs neither.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inspector_common.paths import DataPaths, repo_root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSPECTOR_",
        env_file=None,  # the Makefile/shell loads .env; the library never reads files implicitly
        extra="ignore",
        frozen=True,
    )

    # Data roots. Defaults are relative to the repository root.
    data_root: Path | None = Field(
        default=None, description="Decoded organizer mirror (data_utf8/). Read-only."
    )
    models_root: Path | None = Field(
        default=None, description="OCR/NLP models (.models/), pinned by tools/models/manifest.json."
    )
    cache_root: Path | None = Field(default=None, description="sha256-keyed caches (.cache/).")
    runs_root: Path | None = Field(default=None, description="Batch run directories (runs/).")

    # Logging.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Execution.
    workers: int = Field(default=0, ge=0, description="Process-pool size; 0 = cpu_count - 2.")
    ort_providers: str = Field(
        default="CoreMLExecutionProvider,CPUExecutionProvider",
        description="ONNX Runtime providers in priority order (comma-separated).",
    )

    # Web mode (not used by inspector-batch).
    database_url: str = "postgresql://localhost:5432/inspector"
    redis_url: str = "redis://localhost:6379/0"

    @model_validator(mode="after")
    def _fill_defaults(self) -> Settings:
        root = repo_root()
        defaults = {
            "data_root": root / "data_utf8",
            "models_root": root / ".models",
            "cache_root": root / ".cache",
            "runs_root": root / "runs",
        }
        for name, default in defaults.items():
            value = getattr(self, name)
            object.__setattr__(self, name, (value.expanduser() if value else default).resolve())
        return self

    @property
    def paths(self) -> DataPaths:
        assert self.data_root and self.models_root and self.cache_root and self.runs_root
        return DataPaths(
            data_root=self.data_root,
            models_root=self.models_root,
            cache_root=self.cache_root,
            runs_root=self.runs_root,
        )

    @property
    def ort_provider_list(self) -> list[str]:
        return [p.strip() for p in self.ort_providers.split(",") if p.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Tests construct ``Settings(...)`` directly instead."""
    return Settings()
