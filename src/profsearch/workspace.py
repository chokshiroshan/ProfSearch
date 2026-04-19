"""Workspace bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from profsearch.assets import read_asset_text
from profsearch.config import DEFAULT_CONFIG_FILENAME, DEFAULT_SEED_FILENAME, Settings


def _write_if_needed(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def initialize_workspace(settings: Settings, *, force: bool = False) -> dict[str, object]:
    settings.config_dir_path.mkdir(parents=True, exist_ok=True)
    settings.data_dir_path.mkdir(parents=True, exist_ok=True)
    settings.cache_dir_path.mkdir(parents=True, exist_ok=True)
    settings.runs_path.mkdir(parents=True, exist_ok=True)

    config_path = settings.config_file_path or (settings.config_dir_path / DEFAULT_CONFIG_FILENAME)
    seed_path = settings.seed_path
    created = {
        "config_dir": str(settings.config_dir_path),
        "data_dir": str(settings.data_dir_path),
        "cache_dir": str(settings.cache_dir_path),
        "runs_dir": str(settings.runs_path),
        "config_file": str(config_path),
        "seed_file": str(seed_path),
        "config_written": _write_if_needed(config_path, read_asset_text("default.toml"), force=force),
        "seed_written": _write_if_needed(seed_path, read_asset_text(DEFAULT_SEED_FILENAME), force=force),
        "profile": settings.selected_profile,
    }
    return created
