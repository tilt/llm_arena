""" "System One" decision services as a DecisionPolicy: TypeSafe's hosted Jev, or a local Ollaya server.

API (both): POST <base>/v1/systemone {model, state, questions} -> {answers, usage}. The service
returns only values from the question schema, with probabilities; noul answers have no confidence
field (we derive it). Jev is priced per input token; Ollaya runs local models (e.g. winnow:e4b) for
free and needs no key. Pure module over an injected ChatTransport (httpx on the server). TypeSafe
does not serve CORS, so browser mode cannot call it.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from llm_arena.decisions.types import Answer, DecisionRequest, DecisionResult, noul_answer
from llm_arena.llm.errors import ProviderError
from llm_arena.llm.transport import ChatTransport, TransportError

JEV_BASE_URL = os.getenv("ARENA_TYPESAFE_BASE_URL", "https://api.typesafe.ai")
OLLAYA_BASE_URL = os.getenv("ARENA_OLLAYA_BASE_URL", "http://localhost:11435")
JEV_INPUT_USD_PER_MTOK = 0.042
PRICED_RESERVE_USD = 0.01  # held per priced decision: ~240k input tokens at Jev's price
_TRANSIENT = {429, 529, 500, 502, 503}


class JevDecisionPolicy:
    def __init__(self, transport: ChatTransport, api_key: str | None, *, model: str = "jev-latest",
                 base_url: str = JEV_BASE_URL, service: str = "jev", usd_per_mtok: float = JEV_INPUT_USD_PER_MTOK,
                 max_retries: int = 3, timeout_s: float = 30.0, backoff_s: float = 1.0) -> None:  # fmt: skip
        self._transport = transport
        self._api_key = api_key
        self.model = model
        self.url = base_url.rstrip("/") + "/v1/systemone"
        self.service = service
        self._usd_per_mtok = usd_per_mtok
        self.reserve_usd = PRICED_RESERVE_USD if usd_per_mtok else 0.0  # Ollaya is free, so a $0 limit admits it
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._backoff_s = backoff_s

    @property
    def name(self) -> str:
        return f"{self.service}:{self.model}"

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        body = {
            "model": self.model,
            "state": request.state,
            "questions": {name: q.model_dump(exclude_none=True) for name, q in request.questions.items()},
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        started = time.perf_counter()
        data = await self._post(body, headers)
        answers = {
            name: self._answer(raw) for name, raw in (data.get("answers") or {}).items() if name in request.questions
        }
        usage = data.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0)
        cost = float(usage["cost"]) if "cost" in usage else tokens * self._usd_per_mtok / 1_000_000
        return DecisionResult(answers=answers, cost_usd=cost, tokens=tokens, latency_s=time.perf_counter() - started)

    async def _post(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        last = ""
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(self._backoff_s * 2 ** (attempt - 1))
            try:
                response = await self._transport.post_json(self.url, headers, body, self._timeout_s)
            except TransportError as exc:
                last = f"connection error: {exc}"
                continue
            if 200 <= response.status < 300:
                return dict(response.data)
            last = f"HTTP {response.status}: {json.dumps(response.data)[:300]}"
            if response.status not in _TRANSIENT:
                break
        raise ProviderError(f"{self.name}: {last}")

    def _answer(self, raw: dict[str, Any]) -> Answer:
        kind = raw.get("type")
        if kind == "noul":
            return noul_answer(float(raw.get("noul", 0.5)), self.name)
        probabilities = {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()}
        return Answer(
            type="score" if kind == "score" else "choice",
            probabilities=probabilities,
            choice=raw.get("choice"),
            score=raw.get("score"),
            confidence=float(raw.get("confidence", max(probabilities.values(), default=0.0))),
            source=self.name,
        )
