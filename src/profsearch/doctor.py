"""Deterministic install and runtime checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from profsearch.config import Settings


def _status_from_condition(ok: bool) -> str:
    return "ok" if ok else "error"


def _check(name: str, ok: bool, detail: str, *, hint: str | None = None) -> dict[str, str]:
    payload = {"name": name, "status": _status_from_condition(ok), "detail": detail}
    if hint:
        payload["hint"] = hint
    return payload


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def build_doctor_report(settings: Settings) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    checks.append(
        _check(
            "python_version",
            sys.version_info >= (3, 11),
            f"Running Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            hint="Use Python 3.11+ for supported installs.",
        )
    )
    checks.append(
        _check(
            "config_dir",
            _is_writable(settings.config_dir_path),
            f"Config dir: {settings.config_dir_path}",
        )
    )
    checks.append(
        _check(
            "data_dir",
            _is_writable(settings.data_dir_path),
            f"Data dir: {settings.data_dir_path}",
        )
    )
    checks.append(
        _check(
            "cache_dir",
            _is_writable(settings.cache_dir_path),
            f"Cache dir: {settings.cache_dir_path}",
        )
    )
    checks.append(
        _check(
            "config_file",
            bool(settings.config_file_path and settings.config_file_path.exists()),
            f"Config file: {settings.config_file_path}",
            hint="Run `profsearch init` to create a starter config.",
        )
    )
    checks.append(
        _check(
            "seed_file",
            settings.seed_path.exists(),
            f"Seed file: {settings.seed_path}",
            hint="Run `profsearch init` to install the bundled starter seed file.",
        )
    )
    checks.append(
        _check(
            "database",
            settings.db_path.exists(),
            f"Database path: {settings.db_path}",
            hint="Create a corpus with `profsearch pipeline run` or point PROFSEARCH_DB_PATH to an existing DB.",
        )
    )

    web_ready = _module_available("fastapi") and _module_available("uvicorn")
    checks.append(
        _check(
            "web_extra",
            web_ready,
            "FastAPI/uvicorn available." if web_ready else "FastAPI/uvicorn not installed.",
            hint="Install the web extra: pip install 'profsearch[web]'",
        )
    )

    if settings.embeddings.backend == "sentence_transformers":
        embeddings_ready = _module_available("sentence_transformers") and _module_available("torch")
        detail = f"Embedding backend '{settings.embeddings.backend}' using model {settings.embeddings.model_name}"
        hint = "Install the embeddings extra: pip install 'profsearch[embeddings]'"
    else:
        embeddings_ready = True
        detail = f"Embedding backend '{settings.embeddings.backend}' is built in."
        hint = None
    checks.append(_check("embeddings", embeddings_ready, detail, hint=hint))

    extension_path = (settings.database.sqlite_vec_extension or "").strip()
    if extension_path:
        extension_ok = Path(extension_path).expanduser().exists()
        detail = f"sqlite-vec extension: {extension_path}"
    else:
        extension_ok = True
        detail = "sqlite-vec extension not configured; portable JSON-backed vector store will still work."
    checks.append(_check("sqlite_vec_extension", extension_ok, detail))

    error_count = sum(1 for item in checks if item["status"] == "error")
    return {
        "ok": error_count == 0,
        "profile": settings.selected_profile,
        "config_file": str(settings.config_file_path) if settings.config_file_path else None,
        "paths": {
            "config_dir": str(settings.config_dir_path),
            "data_dir": str(settings.data_dir_path),
            "cache_dir": str(settings.cache_dir_path),
            "runs_dir": str(settings.runs_path),
            "db_path": str(settings.db_path),
            "seed_path": str(settings.seed_path),
        },
        "checks": checks,
        "summary": {
            "errors": error_count,
            "ok": len(checks) - error_count,
        },
    }
