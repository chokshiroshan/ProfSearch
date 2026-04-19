from __future__ import annotations

from pathlib import Path

from profsearch.config import default_user_cache_dir, default_user_config_dir, default_user_data_dir
from profsearch.config import load_settings


def test_load_settings_parses_openalex_api_keys_env(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[openalex]\nbase_url = 'https://api.openalex.org'\n", encoding="utf-8")
    monkeypatch.setenv("PROFSEARCH_OPENALEX_API_KEYS", "key-one, key-two ,, key-three")

    settings = load_settings(config_path)

    assert settings.openalex.api_keys == ["key-one", "key-two", "key-three"]


def test_load_settings_uses_xdg_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    settings = load_settings()

    assert settings.config_dir_path == default_user_config_dir()
    assert settings.data_dir_path == default_user_data_dir()
    assert settings.cache_dir_path == default_user_cache_dir()
    assert settings.seed_path == settings.config_dir_path / "universities_seed.json"
    assert settings.db_path == settings.data_dir_path / "profsearch.db"


def test_load_settings_reads_relative_user_config_from_explicit_path(tmp_path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_path = config_dir / "custom.toml"
    config_path.write_text(
        """
[app]
seed_file = "custom-seed.json"
config_dir = "/tmp/override-config"
data_dir = "/tmp/override-data"
cache_dir = "/tmp/override-cache"

[database]
path = "custom.db"
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.config_file_path == config_path
    assert settings.seed_path == Path("/tmp/override-config/custom-seed.json")
    assert settings.db_path == Path("/tmp/override-data/custom.db")


def test_load_settings_auto_loads_repo_local_dotenv(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / ".profsearch"
    config_dir.mkdir()
    config_path = config_dir / "config.toml"
    config_path.write_text(
        """
[embeddings]
backend = "hash"
model_name = "hash"
dimension = 64
""".strip(),
        encoding="utf-8",
    )
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"""
PROFSEARCH_CONFIG_FILE=.profsearch/config.toml
PROFSEARCH_OPENALEX_API_KEYS=key-a, key-b
PROFSEARCH_DB_PATH={tmp_path / ".profsearch" / "data" / "snapshot.db"}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.config_file_path == config_path
    assert settings.openalex.api_keys == ["key-a", "key-b"]
    assert settings.db_path == tmp_path / ".profsearch" / "data" / "snapshot.db"
