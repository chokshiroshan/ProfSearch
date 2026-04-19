"""Embedding encoder abstraction with a deterministic local fallback."""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Iterable

from profsearch.config import Settings


class EmbeddingEncoder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = settings.embeddings.backend
        self.dimension = settings.embeddings.dimension
        self._model = None

    def _ensure_model(self):
        if self.backend != "sentence_transformers":
            return None
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.settings.embeddings.model_name,
                local_files_only=_offline_model_loading_enabled(),
            )
        return self._model

    def _hash_embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [token.lower() for token in text.split() if token.strip()]
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in range(0, min(len(digest), 32), 4):
                index = int.from_bytes(digest[offset : offset + 4], "big") % self.dimension
                sign = 1.0 if digest[offset] % 2 == 0 else -1.0
                vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def encode_one(self, text: str) -> list[float]:
        if self.backend == "sentence_transformers":
            model = self._ensure_model()
            return [float(value) for value in model.encode([text], normalize_embeddings=True)[0]]
        return self._hash_embed(text)

    def encode_many(self, texts: Iterable[str]) -> list[list[float]]:
        if self.backend == "sentence_transformers":
            model = self._ensure_model()
            return [[float(value) for value in item] for item in model.encode(list(texts), normalize_embeddings=True)]
        return [self._hash_embed(text) for text in texts]


def _offline_model_loading_enabled() -> bool:
    return any(
        os.environ.get(env_name, "").strip().lower() in {"1", "true", "yes", "on"}
        for env_name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    )
