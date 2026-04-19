"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.embedding.encoder import EmbeddingEncoder


def get_session(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_encoder(request: Request) -> EmbeddingEncoder:
    return request.app.state.encoder


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
