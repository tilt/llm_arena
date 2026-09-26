"""Search port plus the default backend: BM25 over a seeded corpus.

Mocked search makes retrieval scores reproducible across models. Live web/arXiv search are
server adapters (`adapters.server.live_search`) used for realism checks with `arena run --live`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str
    url: str = ""
    published: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class SearchBackend(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]: ...

    async def fetch(self, doc_id: str) -> dict[str, Any]: ...


class CorpusSearch:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = {doc.id: doc for doc in documents}
        self._order = list(self.documents)
        self._bm25 = BM25([tokenize(f"{doc.title} {doc.title} {doc.text}") for doc in documents])

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        hits = [self.documents[self._order[i]] for i in ranked[:max_results] if scores[i] > 0]
        return [
            {"id": doc.id, "title": doc.title, "url": doc.url, "published": doc.published, "snippet": doc.text[:160]}
            for doc in hits
        ]

    async def fetch(self, doc_id: str) -> dict[str, Any]:
        doc = self.documents.get(doc_id) or next(
            (d for d in self.documents.values() if d.title.lower() == doc_id.lower()), None
        )
        if doc is None:
            raise KeyError(f"no document {doc_id!r}")
        return {"id": doc.id, "title": doc.title, "url": doc.url, "published": doc.published, "text": doc.text}


class BM25:
    """Okapi BM25 (k1=1.5, b=0.75) — vendored so the engine has no third-party search dependency."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.frequencies = [Counter(document) for document in corpus]
        self.lengths = [len(document) for document in corpus]
        self.average_length = sum(self.lengths) / len(corpus) if corpus else 0.0
        document_frequency: Counter[str] = Counter(term for document in corpus for term in set(document))
        n = len(corpus)
        self.idf = {term: math.log((n - df + 0.5) / (df + 0.5) + 1.0) for term, df in document_frequency.items()}

    def get_scores(self, query: list[str]) -> list[float]:
        scores = []
        for frequencies, length in zip(self.frequencies, self.lengths, strict=True):
            norm = self.k1 * (1 - self.b + self.b * length / (self.average_length or 1.0))
            scores.append(
                sum(
                    self.idf.get(term, 0.0) * frequencies[term] * (self.k1 + 1) / (frequencies[term] + norm)
                    for term in query
                    if term in frequencies
                )
            )
        return scores
