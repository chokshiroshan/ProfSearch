"""Helpers for packaged runtime assets."""

from __future__ import annotations

from importlib.resources import files

_RESOURCE_PACKAGE = "profsearch.resources"


def read_asset_text(name: str) -> str:
    return files(_RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def asset_exists(name: str) -> bool:
    return files(_RESOURCE_PACKAGE).joinpath(name).is_file()


def bundled_profile_names() -> list[str]:
    names: list[str] = []
    for item in files(_RESOURCE_PACKAGE).iterdir():
        if item.is_file() and item.name.endswith(".toml"):
            names.append(item.name.removesuffix(".toml"))
    return sorted(set(names))
