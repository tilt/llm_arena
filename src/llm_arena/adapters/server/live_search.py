"""Live search backends for `arena run --live` (extra `live`): Tavily web search and arXiv."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from llm_arena.mocks.search import SearchBackend


def live_search(name: str) -> SearchBackend:
    if name == "tavily":
        return TavilySearch()
    if name == "arxiv":
        return ArxivSearch()
    raise ValueError(f"unknown live search backend {name!r} (tavily, arxiv)")


class TavilySearch:  # pragma: no cover - live network
    """Live web search (extra `live`, TAVILY_API_KEY). Results are cached for `fetch`."""

    def __init__(self) -> None:
        from tavily import TavilyClient

        self._client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
        self._seen: dict[str, dict[str, Any]] = {}

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        response = await asyncio.to_thread(self._client.search, query=query, max_results=max_results)
        hits = []
        for index, item in enumerate(response.get("results", [])):
            doc_id = f"web-{len(self._seen) + index}"
            self._seen[doc_id] = {
                "id": doc_id,
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "text": item.get("content", ""),
            }
            hits.append({**self._seen[doc_id], "snippet": item.get("content", "")[:160]})
        return hits

    async def fetch(self, doc_id: str) -> dict[str, Any]:
        return self._seen[doc_id]


class ArxivSearch:  # pragma: no cover - live network
    def __init__(self) -> None:
        import arxiv

        self._arxiv = arxiv
        self._client = arxiv.Client()
        self._seen: dict[str, dict[str, Any]] = {}

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        search = self._arxiv.Search(query=query, max_results=max_results)
        papers = await asyncio.to_thread(lambda: list(self._client.results(search)))
        hits = []
        for paper in papers:
            doc_id = paper.get_short_id()
            self._seen[doc_id] = {
                "id": doc_id,
                "title": paper.title,
                "url": paper.entry_id,
                "published": paper.published.date().isoformat(),
                "text": paper.summary,
            }
            hits.append({**self._seen[doc_id], "snippet": paper.summary[:160]})
        return hits

    async def fetch(self, doc_id: str) -> dict[str, Any]:
        return self._seen[doc_id]
