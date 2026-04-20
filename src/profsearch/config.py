"""Typed application configuration with packaged defaults and env overrides."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from profsearch.assets import asset_exists, read_asset_text

APP_NAME = "profsearch"
DEFAULT_PROFILE = "default"
DEFAULT_CONFIG_FILENAME = "config.toml"
DEFAULT_SEED_FILENAME = "universities_seed.json"
DEFAULT_ENV_FILENAME = ".env"


def _xdg_dir(env: dict[str, str], key: str, fallback_suffix: str) -> Path:
    configured = env.get(key)
    if configured:
        return Path(configured).expanduser() / APP_NAME
    return Path.home() / fallback_suffix / APP_NAME


def default_user_config_dir(env: dict[str, str] | None = None) -> Path:
    return _xdg_dir(env or dict(os.environ), "XDG_CONFIG_HOME", ".config")


def default_user_data_dir(env: dict[str, str] | None = None) -> Path:
    return _xdg_dir(env or dict(os.environ), "XDG_DATA_HOME", ".local/share")


def default_user_cache_dir(env: dict[str, str] | None = None) -> Path:
    return _xdg_dir(env or dict(os.environ), "XDG_CACHE_HOME", ".cache")


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seed_file: str = DEFAULT_SEED_FILENAME
    data_dir: str = ""
    config_dir: str = ""
    cache_dir: str = ""
    runs_dir: str = "runs"


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = "profsearch.db"
    sqlite_vec_extension: str | None = None
    echo: bool = False


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeout_seconds: float = 20.0
    request_delay_seconds: float = 0.35
    concurrent_requests: int = 4
    user_agent: str = "ProfSearch/0.1"


class OpenAlexConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = "https://api.openalex.org"
    email: str | None = None
    api_key: str | None = None
    api_keys: list[str] = Field(default_factory=list)
    per_page: int = 10
    max_candidates: int = 5


class MatchingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    threshold: float = 0.82
    ambiguity_margin: float = 0.05


class PublicationsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start_year: int = 2021
    per_page: int = 50
    max_pages_per_author: int = 5


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    backend: str = "hash"
    model_name: str = "allenai/specter2_base"
    dimension: int = 768
    batch_size: int = 16


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    result_limit: int | None = None
    work_limit: int = 5
    candidate_pool: int = 250


class FundingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nih_base_url: str = "https://api.reporter.nih.gov/v2"
    nsf_base_url: str = "https://api.nsf.gov/services/v1"
    per_page: int = 50
    max_pages: int = 5


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    openalex: OpenAlexConfig = Field(default_factory=OpenAlexConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    publications: PublicationsConfig = Field(default_factory=PublicationsConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    funding: FundingConfig = Field(default_factory=FundingConfig)

    _config_file: Path | None = PrivateAttr(default=None)
    _selected_profile: str = PrivateAttr(default=DEFAULT_PROFILE)

    @property
    def project_root(self) -> Path:
        return Path.cwd()

    @property
    def config_file_path(self) -> Path | None:
        return self._config_file

    @property
    def selected_profile(self) -> str:
        return self._selected_profile

    @property
    def config_dir_path(self) -> Path:
        return Path(self.app.config_dir).expanduser()

    @property
    def data_dir_path(self) -> Path:
        return Path(self.app.data_dir).expanduser()

    @property
    def cache_dir_path(self) -> Path:
        return Path(self.app.cache_dir).expanduser()

    @property
    def runs_path(self) -> Path:
        path = Path(self.app.runs_dir).expanduser()
        if path.is_absolute():
            return path
        return self.data_dir_path / path

    @property
    def db_path(self) -> Path:
        path = Path(self.database.path).expanduser()
        if path.is_absolute():
            return path
        return self.data_dir_path / path

    @property
    def seed_path(self) -> Path:
        path = Path(self.app.seed_file).expanduser()
        if path.is_absolute():
            return path
        return self.config_dir_path / path


ENV_OVERRIDES: dict[str, tuple[str, str, type[Any]]] = {
    "PROFSEARCH_CONFIG_DIR": ("app", "config_dir", str),
    "PROFSEARCH_DATA_DIR": ("app", "data_dir", str),
    "PROFSEARCH_CACHE_DIR": ("app", "cache_dir", str),
    "PROFSEARCH_RUNS_DIR": ("app", "runs_dir", str),
    "PROFSEARCH_DB_PATH": ("database", "path", str),
    "PROFSEARCH_SQLITE_VEC_EXTENSION": ("database", "sqlite_vec_extension", str),
    "PROFSEARCH_DB_ECHO": ("database", "echo", bool),
    "PROFSEARCH_HTTP_TIMEOUT": ("http", "timeout_seconds", float),
    "PROFSEARCH_REQUEST_DELAY_SECONDS": ("http", "request_delay_seconds", float),
    "PROFSEARCH_CONCURRENT_REQUESTS": ("http", "concurrent_requests", int),
    "PROFSEARCH_HTTP_USER_AGENT": ("http", "user_agent", str),
    "PROFSEARCH_OPENALEX_EMAIL": ("openalex", "email", str),
    "PROFSEARCH_OPENALEX_API_KEY": ("openalex", "api_key", str),
    "PROFSEARCH_OPENALEX_API_KEYS": ("openalex", "api_keys", str),
    "PROFSEARCH_OPENALEX_PER_PAGE": ("openalex", "per_page", int),
    "PROFSEARCH_OPENALEX_MAX_CANDIDATES": ("openalex", "max_candidates", int),
    "PROFSEARCH_MATCH_THRESHOLD": ("matching", "threshold", float),
    "PROFSEARCH_AMBIGUITY_MARGIN": ("matching", "ambiguity_margin", float),
    "PROFSEARCH_PUBLICATION_START_YEAR": ("publications", "start_year", int),
    "PROFSEARCH_PUBLICATION_PER_PAGE": ("publications", "per_page", int),
    "PROFSEARCH_EMBEDDING_BACKEND": ("embeddings", "backend", str),
    "PROFSEARCH_EMBEDDING_MODEL": ("embeddings", "model_name", str),
    "PROFSEARCH_EMBEDDING_DIMENSION": ("embeddings", "dimension", int),
    "PROFSEARCH_SEARCH_RESULT_LIMIT": ("search", "result_limit", int),
    "PROFSEARCH_SEARCH_WORK_LIMIT": ("search", "work_limit", int),
}

_RUNTIME_OVERRIDES: dict[str, str | None] = {"config_path": None, "profile": None}


def _coerce_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cast(raw: str, value_type: type[Any]) -> Any:
    if value_type is bool:
        return _coerce_bool(raw)
    return value_type(raw)


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        payload[key] = value
    return payload


def _load_runtime_env(project_root: Path | None = None) -> dict[str, str]:
    env = _load_dotenv((project_root or Path.cwd()) / DEFAULT_ENV_FILENAME)
    env.update(os.environ)
    return env


def _resolve_runtime_path(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _load_packaged_profile(profile: str) -> dict[str, Any]:
    resource_name = f"{profile}.toml"
    if not asset_exists(resource_name):
        raise ValueError(f"Unknown ProfSearch profile: {profile}")
    return tomllib.loads(read_asset_text(resource_name))


def _apply_env_overrides(config: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    merged = dict(config)
    for env_key, (section, field_name, value_type) in ENV_OVERRIDES.items():
        raw = env.get(env_key)
        if raw is None or raw == "":
            continue
        section_payload = dict(merged.get(section, {}))
        if env_key == "PROFSEARCH_OPENALEX_API_KEYS":
            section_payload[field_name] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            section_payload[field_name] = _cast(raw, value_type)
        merged[section] = section_payload
    return merged


def _default_config_file(env: dict[str, str]) -> Path:
    return default_user_config_dir(env) / DEFAULT_CONFIG_FILENAME


def _apply_default_dirs(settings: Settings, env: dict[str, str], *, explicit_config: bool, config_file: Path) -> None:
    if explicit_config:
        default_config_dir = config_file.parent
        default_data_dir = config_file.parent / "data"
        default_cache_dir = config_file.parent / "cache"
    else:
        default_config_dir = default_user_config_dir(env)
        default_data_dir = default_user_data_dir(env)
        default_cache_dir = default_user_cache_dir(env)
    if not settings.app.config_dir:
        settings.app.config_dir = str(default_config_dir)
    if not settings.app.data_dir:
        settings.app.data_dir = str(default_data_dir)
    if not settings.app.cache_dir:
        settings.app.cache_dir = str(default_cache_dir)


def configure_runtime(*, config_path: str | None = None, profile: str | None = None) -> None:
    _RUNTIME_OVERRIDES["config_path"] = config_path
    _RUNTIME_OVERRIDES["profile"] = profile
    get_settings.cache_clear()


def load_settings(
    config_path: str | os.PathLike[str] | None = None,
    profile: str | None = None,
) -> Settings:
    env = _load_runtime_env()
    selected_profile = profile or env.get("PROFSEARCH_PROFILE", DEFAULT_PROFILE)
    raw = _load_packaged_profile(DEFAULT_PROFILE)
    if selected_profile != DEFAULT_PROFILE:
        raw = _deep_merge(raw, _load_packaged_profile(selected_profile))

    configured_path = config_path or env.get("PROFSEARCH_CONFIG_FILE")
    config_file = _resolve_runtime_path(configured_path) if configured_path else _default_config_file(env)
    if config_file.exists():
        raw = _deep_merge(raw, _load_toml(config_file))
    raw = _apply_env_overrides(raw, env)

    settings = Settings.model_validate(raw)
    _apply_default_dirs(settings, env, explicit_config=bool(configured_path), config_file=config_file)
    settings._config_file = config_file
    settings._selected_profile = selected_profile
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings(_RUNTIME_OVERRIDES["config_path"], _RUNTIME_OVERRIDES["profile"])
