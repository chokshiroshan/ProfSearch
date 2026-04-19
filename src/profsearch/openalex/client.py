"""Async OpenAlex API wrapper."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date

import httpx

from profsearch.config import Settings
from profsearch.utils.rate_limiter import RateLimiter


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    slots: dict[int, str] = {}
    for token, positions in inverted_index.items():
        for position in positions:
            slots[position] = token
    return " ".join(slots[index] for index in sorted(slots))


@dataclass(slots=True)
class OpenAlexCandidate:
    payload: dict
    score: float
    evidence: dict


class OpenAlexClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {"User-Agent": settings.http.user_agent}
        self._client = httpx.AsyncClient(
            base_url=settings.openalex.base_url,
            timeout=settings.http.timeout_seconds,
            headers=headers,
        )
        self._limiter = RateLimiter(max(settings.http.request_delay_seconds, 1.0))
        self._api_keys = self._collect_api_keys(settings)
        self._api_key_index = 0
        self._api_key_blocked_until: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _collect_api_keys(settings: Settings) -> list[str]:
        keys: list[str] = []
        for candidate in [settings.openalex.api_key, *settings.openalex.api_keys]:
            cleaned = (candidate or "").strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
        return keys

    def _next_api_key(self) -> str | None:
        if not self._api_keys:
            return None
        now = time.monotonic()
        for _ in range(len(self._api_keys)):
            key = self._api_keys[self._api_key_index % len(self._api_keys)]
            self._api_key_index += 1
            if self._api_key_blocked_until.get(key, 0.0) <= now:
                return key
        return None

    def _next_key_retry_after(self) -> float:
        if not self._api_key_blocked_until:
            return 0.0
        now = time.monotonic()
        wait_values = [blocked_until - now for blocked_until in self._api_key_blocked_until.values()]
        positive_waits = [wait for wait in wait_values if wait > 0.0]
        if not positive_waits:
            return 0.0
        return min(positive_waits)

    def _params(self, params: dict[str, str | int], *, api_key: str | None = None) -> dict[str, str | int]:
        final_params = dict(params)
        if self.settings.openalex.email:
            final_params["mailto"] = self.settings.openalex.email
        active_key = api_key if api_key is not None else self._next_api_key()
        if active_key:
            final_params["api_key"] = active_key
        return final_params

    @staticmethod
    def _retry_after_seconds(exc: httpx.HTTPStatusError, attempt: int) -> float:
        header_value = exc.response.headers.get("retry-after")
        if header_value:
            try:
                return max(float(header_value), 0.0)
            except ValueError:
                pass
        return min(60.0, float(2**attempt))

    async def _get_json(self, path: str, params: dict[str, str | int]) -> dict:
        attempt = 0
        while True:
            api_key = self._next_api_key()
            if api_key is None and self._api_keys:
                await asyncio.sleep(self._next_key_retry_after())
                continue
            try:
                await self._limiter.wait()
                response = await self._client.get(path, params=self._params(params, api_key=api_key))
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                attempt += 1
                if exc.response.status_code == 429 and api_key:
                    retry_after = self._retry_after_seconds(exc, attempt)
                    self._api_key_blocked_until[api_key] = time.monotonic() + retry_after
                    if len(self._api_keys) > 1:
                        continue
                    await asyncio.sleep(retry_after)
                    continue
                if exc.response.status_code != 429 or attempt > max(6, len(self._api_keys) + 2):
                    raise
                await asyncio.sleep(self._retry_after_seconds(exc, attempt))
            except httpx.HTTPError:
                attempt += 1
                if attempt > 3:
                    raise
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

    async def search_authors(self, query: str, *, per_page: int | None = None) -> list[dict]:
        payload = await self._get_json(
            "/authors",
            {"search": query, "per-page": per_page or self.settings.openalex.per_page},
        )
        return payload.get("results", [])

    async def iter_author_works(self, author_id: str, from_year: int) -> AsyncIterator[dict]:
        page = 1
        from_date = date(from_year, 1, 1).isoformat()
        while page <= self.settings.publications.max_pages_per_author:
            payload = await self._get_json(
                "/works",
                {
                    "filter": f"author.id:{author_id},from_publication_date:{from_date}",
                    "per-page": self.settings.publications.per_page,
                    "page": page,
                },
            )
            results = payload.get("results", [])
            if not results:
                return
            for item in results:
                yield item
            meta = payload.get("meta", {})
            if page >= int(meta.get("count", 0) / self.settings.publications.per_page) + 1:
                return
            page += 1
