"""Async HTTP client for official faculty roster scraping."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from profsearch.config import Settings
from profsearch.utils.rate_limiter import RateLimiter
from profsearch.utils.retry import async_retry

SCRAPING_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36"
)


def _is_allowed_domain(url: str, approved_domains: set[str]) -> bool:
    hostname = urlparse(url).hostname or ""
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in approved_domains)


def _scraping_user_agent(configured_user_agent: str) -> str:
    if configured_user_agent and not configured_user_agent.startswith("ProfSearch/"):
        return configured_user_agent
    return SCRAPING_BROWSER_USER_AGENT


@dataclass(slots=True)
class HtmlResponse:
    url: str
    text: str
    status_code: int


class AsyncHtmlClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._headers = {"User-Agent": _scraping_user_agent(settings.http.user_agent)}
        self._client = httpx.AsyncClient(
            timeout=settings.http.timeout_seconds,
            follow_redirects=True,
            headers=self._headers,
        )
        self._limiter = RateLimiter(settings.http.request_delay_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_with_tls_fallback(self, url: str) -> httpx.Response:
        try:
            return await self._client.get(url)
        except httpx.ConnectError as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
        async with httpx.AsyncClient(
            timeout=self.settings.http.timeout_seconds,
            follow_redirects=True,
            headers=self._headers,
            verify=False,
        ) as insecure_client:
            return await insecure_client.get(url)

    async def fetch(self, url: str, approved_domains: set[str]) -> HtmlResponse:
        if not _is_allowed_domain(url, approved_domains):
            raise ValueError(f"Refusing to fetch off-domain URL: {url}")

        async def _do_fetch() -> HtmlResponse:
            await self._limiter.wait()
            response = await self._request_with_tls_fallback(url)
            response.raise_for_status()
            return HtmlResponse(url=str(response.url), text=response.text, status_code=response.status_code)

        return await async_retry(_do_fetch, retries=3, retry_on=(httpx.HTTPError,))
