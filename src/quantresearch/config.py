"""Validated, environment-aware project configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    """Return the repository root from this installed source location."""
    return Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    """Filesystem and runtime settings.

    Paths can be overridden with ``QUANTRESEARCH_*`` environment variables.
    No directory is created during import; call :meth:`ensure_directories` at
    an application boundary when writes are intended.
    """

    project_root: Path
    data_dir: Path
    raw_data_dir: Path
    validated_data_dir: Path
    feature_data_dir: Path
    market_data_dir: Path
    research_db_path: Path
    cache_dir: Path
    reports_dir: Path
    logs_dir: Path
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or _project_root()).expanduser().resolve()
        data = _env_path("QUANTRESEARCH_DATA_DIR", root / "data")
        log_level = os.getenv("QUANTRESEARCH_LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid QUANTRESEARCH_LOG_LEVEL: {log_level}")

        return cls(
            project_root=root,
            data_dir=data,
            raw_data_dir=_env_path("QUANTRESEARCH_RAW_DATA_DIR", data / "raw"),
            validated_data_dir=_env_path("QUANTRESEARCH_VALIDATED_DATA_DIR", data / "validated"),
            feature_data_dir=_env_path("QUANTRESEARCH_FEATURE_DATA_DIR", data / "features"),
            market_data_dir=_env_path("QUANTRESEARCH_MARKET_DATA_DIR", data / "market"),
            research_db_path=_env_path(
                "QUANTRESEARCH_RESEARCH_DB", data / "features" / "research.duckdb"
            ),
            cache_dir=_env_path("QUANTRESEARCH_CACHE_DIR", root / "cache"),
            reports_dir=_env_path("QUANTRESEARCH_REPORTS_DIR", root / "reports"),
            logs_dir=_env_path("QUANTRESEARCH_LOGS_DIR", root / "logs"),
            log_level=log_level,
        )

    def ensure_directories(self) -> None:
        for path in (
            self.raw_data_dir,
            self.validated_data_dir,
            self.feature_data_dir,
            self.market_data_dir,
            self.cache_dir,
            self.reports_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings(project_root: Path | None = None) -> Settings:
    """Build settings from the current environment."""
    return Settings.from_env(project_root=project_root)
