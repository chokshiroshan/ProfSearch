from __future__ import annotations

import httpx
import pytest

from profsearch.config import Settings
from profsearch.openalex.client import OpenAlexClient


@pytest.mark.asyncio
async def test_openalex_client_retries_rate_limit() -> None:
    settings = Settings.model_validate(
        {
            "http": {"request_delay_seconds": 0.0, "timeout_seconds": 5.0},
            "openalex": {"base_url": "https://api.openalex.org"},
        }
    )
    client = OpenAlexClient(settings)
    request = httpx.Request("GET", "https://api.openalex.org/authors")
    responses = [
        httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"}, request=request),
        httpx.Response(200, json={"results": [{"id": "https://openalex.org/A1"}]}, request=request),
    ]

    async def fake_get(path: str, params: dict | None = None) -> httpx.Response:
        return responses.pop(0)

    async def no_wait() -> None:
        return None

    client._client.get = fake_get  # type: ignore[method-assign]
    client._limiter.wait = no_wait  # type: ignore[method-assign]
    try:
        results = await client.search_authors("Jane Doe", per_page=5)
    finally:
        await client.aclose()

    assert results == [{"id": "https://openalex.org/A1"}]


@pytest.mark.asyncio
async def test_openalex_client_rotates_keys_after_rate_limit() -> None:
    settings = Settings.model_validate(
        {
            "http": {"request_delay_seconds": 0.0, "timeout_seconds": 5.0},
            "openalex": {
                "base_url": "https://api.openalex.org",
                "api_keys": ["key-one", "key-two"],
            },
        }
    )
    client = OpenAlexClient(settings)
    request = httpx.Request("GET", "https://api.openalex.org/authors")
    seen_keys: list[str] = []

    async def fake_get(path: str, params: dict | None = None) -> httpx.Response:
        assert params is not None
        seen_keys.append(str(params["api_key"]))
        if params["api_key"] == "key-one":
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"}, request=request)
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/A2"}]}, request=request)

    async def no_wait() -> None:
        return None

    client._client.get = fake_get  # type: ignore[method-assign]
    client._limiter.wait = no_wait  # type: ignore[method-assign]
    try:
        results = await client.search_authors("Jane Doe", per_page=5)
    finally:
        await client.aclose()

    assert seen_keys == ["key-one", "key-two"]
    assert results == [{"id": "https://openalex.org/A2"}]
