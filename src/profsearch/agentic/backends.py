"""LLM backends for the ProfSearch email drafter.

Backends are BYO-key and transport-direct — no vendor SDK required. Supported:
  - anthropic  : POST /v1/messages via httpx, default model claude-haiku-4-5-20251001
  - echo       : deterministic, returns the rendered prompt (for local debugging)
  - fake       : returns a canned fixture response (tests; demo without a key)

Add a new backend by implementing the `LLMBackend` protocol and registering it in
`build_backend`. Keys are read from env — never persisted, never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import httpx


class LLMError(RuntimeError):
    """Raised when an LLM backend fails in a user-actionable way."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    backend: str
    model: str


class LLMBackend(Protocol):
    name: str

    def complete(self, system: str, user: str, *, max_tokens: int = 600) -> LLMResponse: ...


@dataclass
class AnthropicBackend:
    """Anthropic Messages API via httpx. Reads ANTHROPIC_API_KEY from env.

    Default model is claude-haiku-4-5-20251001 — cheap, fast, strong enough
    for 150-word outreach emails grounded in provided context.
    """

    model: str = "claude-haiku-4-5-20251001"
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com"
    timeout_seconds: float = 30.0
    name: str = "anthropic"

    def complete(self, system: str, user: str, *, max_tokens: int = 600) -> LLMResponse:
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("PROFSEARCH_LLM_API_KEY")
        if not api_key:
            raise LLMError(
                "Anthropic backend requires ANTHROPIC_API_KEY (or PROFSEARCH_LLM_API_KEY). "
                "Get one at https://console.anthropic.com or use --llm-backend fake for a demo."
            )
        try:
            resp = httpx.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc

        if resp.status_code != 200:
            snippet = resp.text[:400]
            raise LLMError(f"Anthropic returned HTTP {resp.status_code}: {snippet}")

        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()
        if not text:
            raise LLMError("Anthropic returned an empty response.")
        return LLMResponse(text=text, backend=self.name, model=data.get("model", self.model))


@dataclass
class EchoBackend:
    """Returns the rendered prompt verbatim. Useful for debugging the prompt template."""

    name: str = "echo"

    def complete(self, system: str, user: str, *, max_tokens: int = 600) -> LLMResponse:
        rendered = f"[system]\n{system}\n\n[user]\n{user}"
        return LLMResponse(text=rendered, backend=self.name, model="echo")


@dataclass
class FakeBackend:
    """Deterministic stub used in tests and for no-key demos.

    Pulls concrete details from the user prompt (first referenced paper title,
    applicant interest) so the output is self-evidently grounded in the inputs.
    """

    reply: str | None = None
    name: str = "fake"

    def complete(self, system: str, user: str, *, max_tokens: int = 600) -> LLMResponse:
        if self.reply is not None:
            return LLMResponse(text=self.reply, backend=self.name, model="fake")

        interest = _extract(user, "Applicant research interest:")
        first_paper = _extract(user, "- Paper 1 title:")
        prof_name = _extract(user, "Professor name:")
        applicant_name = _extract(user, "Applicant name:") or "[Your name]"

        reply = (
            f"Subject: Prospective PhD student — interest in {interest or 'your research'}\n"
            f"\n"
            f"Dear Professor {prof_name.split()[-1] if prof_name else '[Last name]'},\n"
            f"\n"
            f"I read your recent paper \"{first_paper}\" with great interest. "
            f"My own work on {interest or 'related topics'} aligns closely with that direction, "
            f"and I would welcome the chance to discuss whether your group is taking on new "
            f"students for the upcoming cycle.\n"
            f"\n"
            f"I've attached my CV and a short research statement. Happy to share more on request.\n"
            f"\n"
            f"Best regards,\n"
            f"{applicant_name}\n"
        )
        return LLMResponse(text=reply, backend=self.name, model="fake")


def _extract(haystack: str, needle: str) -> str:
    idx = haystack.find(needle)
    if idx < 0:
        return ""
    start = idx + len(needle)
    end = haystack.find("\n", start)
    return haystack[start:end if end >= 0 else None].strip().strip('"')


def build_backend(name: str | None = None, *, model: str | None = None) -> LLMBackend:
    """Factory. Reads PROFSEARCH_LLM_BACKEND / PROFSEARCH_LLM_MODEL env vars when args are None."""
    resolved = (name or os.environ.get("PROFSEARCH_LLM_BACKEND") or "anthropic").strip().lower()
    resolved_model = model or os.environ.get("PROFSEARCH_LLM_MODEL")

    if resolved == "anthropic":
        return AnthropicBackend(model=resolved_model or AnthropicBackend.model)
    if resolved == "echo":
        return EchoBackend()
    if resolved == "fake":
        return FakeBackend()
    raise LLMError(f"Unknown LLM backend: {resolved!r}. Supported: anthropic, echo, fake.")
