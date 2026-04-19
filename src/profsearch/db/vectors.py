"""Optional sqlite-vec integration with a portable SQL fallback."""

from __future__ import annotations

import json
from typing import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


def initialize_vector_support(engine: Engine, extension_path: str | None, dimension: int) -> bool:
    with engine.begin() as connection:
        raw = connection.connection
        loaded = False
        try:
            raw.enable_load_extension(True)
            if extension_path:
                raw.load_extension(extension_path)
                loaded = True
        except Exception:
            loaded = False
        finally:
            try:
                raw.enable_load_extension(False)
            except Exception:
                pass
        if loaded:
            connection.exec_driver_sql(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS work_embeddings
                USING vec0(work_id INTEGER PRIMARY KEY, embedding float[{dimension}])
                """
            )
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS work_embedding_store (
                work_id INTEGER PRIMARY KEY,
                dimension INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                backend TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    return loaded


def _execute_embedding_upsert(connection: Connection, work_id: int, embedding: Sequence[float], backend: str) -> None:
    payload = json.dumps(list(embedding))
    connection.execute(
        text(
            """
            INSERT INTO work_embedding_store (work_id, dimension, embedding_json, backend, updated_at)
            VALUES (:work_id, :dimension, :embedding_json, :backend, CURRENT_TIMESTAMP)
            ON CONFLICT(work_id) DO UPDATE SET
                dimension = excluded.dimension,
                embedding_json = excluded.embedding_json,
                backend = excluded.backend,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "work_id": work_id,
            "dimension": len(embedding),
            "embedding_json": payload,
            "backend": backend,
        },
    )
    try:
        connection.execute(
            text(
                """
                INSERT INTO work_embeddings (work_id, embedding)
                VALUES (:work_id, :embedding)
                ON CONFLICT(work_id) DO UPDATE SET embedding = excluded.embedding
                """
            ),
            {"work_id": work_id, "embedding": payload},
        )
    except Exception:
        pass


def upsert_embedding(engine: Engine | Connection, work_id: int, embedding: Sequence[float], backend: str) -> None:
    if isinstance(engine, Connection):
        _execute_embedding_upsert(engine, work_id, embedding, backend)
        return
    with engine.begin() as connection:
        _execute_embedding_upsert(connection, work_id, embedding, backend)


def fetch_embeddings(engine: Engine, work_ids: Iterable[int] | None = None) -> dict[int, list[float]]:
    query = "SELECT work_id, embedding_json FROM work_embedding_store"
    params: dict[str, object] = {}
    if work_ids is not None:
        ids = list(work_ids)
        if not ids:
            return {}
        placeholders = ", ".join(f":id_{index}" for index, _ in enumerate(ids))
        query += f" WHERE work_id IN ({placeholders})"
        params = {f"id_{index}": value for index, value in enumerate(ids)}
    with engine.begin() as connection:
        rows = connection.execute(text(query), params).mappings().all()
    return {int(row["work_id"]): json.loads(row["embedding_json"]) for row in rows}
