from __future__ import annotations

import os
import numpy as np

from profsearch.embedding.encoder import EmbeddingEncoder


def test_sentence_transformer_path_coerces_numpy_scalars(test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    encoder.backend = "sentence_transformers"

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True):
            assert texts == ["quantum materials"]
            return np.array([[np.float32(0.5), np.float32(-0.25)]], dtype=np.float32)

    encoder._model = FakeModel()
    vector = encoder.encode_one("quantum materials")

    assert vector == [0.5, -0.25]
    assert all(isinstance(value, float) for value in vector)


def test_sentence_transformer_path_respects_offline_env(monkeypatch, test_settings) -> None:
    encoder = EmbeddingEncoder(test_settings)
    encoder.backend = "sentence_transformers"
    recorded: dict[str, object] = {}

    class FakeSentenceTransformer:
        def __init__(self, model_name, local_files_only=False, **kwargs):
            recorded["model_name"] = model_name
            recorded["local_files_only"] = local_files_only

        def encode(self, texts, normalize_embeddings=True):
            return np.array([[np.float32(1.0), np.float32(0.0)]], dtype=np.float32)

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.setitem(os.sys.modules, "sentence_transformers", type("M", (), {"SentenceTransformer": FakeSentenceTransformer}))

    vector = encoder.encode_one("topological materials")

    assert vector == [1.0, 0.0]
    assert recorded == {
        "model_name": test_settings.embeddings.model_name,
        "local_files_only": True,
    }
