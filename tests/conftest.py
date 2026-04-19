from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from profsearch.config import Settings
from profsearch.db.session import create_sqlalchemy_engine, initialize_database


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    settings = Settings.model_validate(
        {
            "app": {
                "seed_file": str(tmp_path / "seed.json"),
                "data_dir": str(data_dir),
                "config_dir": str(config_dir),
                "cache_dir": str(cache_dir),
                "runs_dir": "runs",
            },
            "database": {"path": str(data_dir / "profsearch.db")},
            "http": {"timeout_seconds": 5, "request_delay_seconds": 0, "concurrent_requests": 1, "user_agent": "tests"},
            "openalex": {"base_url": "https://api.openalex.org", "per_page": 5, "max_candidates": 5},
            "matching": {"threshold": 0.82, "ambiguity_margin": 0.05},
            "publications": {"start_year": 2021, "per_page": 5, "max_pages_per_author": 2},
            "embeddings": {"backend": "hash", "model_name": "hash", "dimension": 64, "batch_size": 8},
            "search": {"result_limit": 5, "work_limit": 3, "candidate_pool": 25},
        }
    )
    Path(settings.app.seed_file).write_text(json.dumps([]), encoding="utf-8")
    return settings


@pytest.fixture()
def session_factory(test_settings: Settings):
    initialize_database(test_settings)
    engine = create_sqlalchemy_engine(test_settings)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
