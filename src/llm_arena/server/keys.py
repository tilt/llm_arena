"""API keys for the local app: read from the environment (.env), or set for this session only.

Keys never leave the server process: the API reports only *where* a key comes from (env, session,
missing). A session key lives in process memory and is gone when `arena ui` stops — nothing is
written to disk.
"""

from __future__ import annotations

import os

from llm_arena.api import KeySource

KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "typesafe": "TYPESAFE_API_KEY",  # Jev decision model
    "tavily": "TAVILY_API_KEY",
}


class KeyStore:
    def __init__(self) -> None:
        # Remember what the environment had, so clearing a session key restores it.
        self._original = {provider: os.environ.get(name) for provider, name in KEY_ENV.items()}
        self._session: set[str] = set()

    def status(self) -> dict[str, KeySource]:
        return {provider: self._source(provider) for provider in KEY_ENV}

    def set(self, provider: str, key: str) -> None:
        if provider not in KEY_ENV:
            raise KeyError(f"unknown provider {provider!r}; known: {sorted(KEY_ENV)}")
        if not key.strip():
            raise ValueError("empty key")
        # The model clients resolve keys from the environment at construction time, so setting it here
        # makes every new client (and the next discovery) use it.
        os.environ[KEY_ENV[provider]] = key.strip()
        self._session.add(provider)

    def clear(self, provider: str) -> None:
        if provider not in KEY_ENV:
            raise KeyError(f"unknown provider {provider!r}")
        self._session.discard(provider)
        original = self._original[provider]
        if original:
            os.environ[KEY_ENV[provider]] = original
        else:
            os.environ.pop(KEY_ENV[provider], None)

    def _source(self, provider: str) -> KeySource:
        if provider in self._session:
            return "session"
        return "env" if os.environ.get(KEY_ENV[provider]) else "missing"
