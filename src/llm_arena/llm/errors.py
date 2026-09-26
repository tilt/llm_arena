"""Errors raised by the LLM client layer."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for client-layer errors."""


class ProviderError(LLMError):
    """A model call failed after retries."""


class StructuredOutputError(LLMError):
    """The model did not return output matching the requested schema."""
