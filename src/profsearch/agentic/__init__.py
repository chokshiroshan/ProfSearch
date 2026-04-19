"""Agentic helpers: LLM-backed utilities for applicant workflows."""

from profsearch.agentic.backends import (
    AnthropicBackend,
    EchoBackend,
    FakeBackend,
    LLMBackend,
    LLMError,
    build_backend,
)
from profsearch.agentic.email_draft import (
    DraftedEmail,
    EmailDraftRequest,
    UserProfile,
    draft_outreach_email,
)

__all__ = [
    "AnthropicBackend",
    "DraftedEmail",
    "EchoBackend",
    "EmailDraftRequest",
    "FakeBackend",
    "LLMBackend",
    "LLMError",
    "UserProfile",
    "build_backend",
    "draft_outreach_email",
]
