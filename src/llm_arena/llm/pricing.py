"""Token prices for cost reporting. Local models cost 0 $ (wall time is reported separately).

Prices are USD per million tokens (input, output) and drift over time: treat this table as a
default and override per model in models.yaml (`input_cost_per_mtok`, `output_cost_per_mtok`).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from llm_arena.llm.spec import ModelSpec

_SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")

PRICES: dict[str, tuple[float, float]] = {
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "o4-mini": (1.10, 4.40),
    "o3": (2.0, 8.0),
    "o3-mini": (1.10, 4.40),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
}


def load_prices(path: str | Path) -> None:
    """Merge a YAML price list ({model: [input, output]} in USD per Mtok) into the table."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    PRICES.update({str(model): (float(prices[0]), float(prices[1])) for model, prices in raw.items()})


def known_price(model: str) -> tuple[float, float] | None:
    """Exact family match only (a dated snapshot maps to its family). Prefix matching would give
    'gpt-5-pro' the price of 'gpt-5' — an order of magnitude off — so unknown stays unknown."""
    family = _SNAPSHOT.sub("", model)
    return PRICES.get(family)


def max_known_price(provider: str) -> tuple[float, float]:
    """Conservative fallback for best-effort reservations of an unknown official model."""
    prefix = "claude-" if provider == "anthropic" else "gpt-"
    prices = [price for model, price in PRICES.items() if model.startswith(prefix)]
    return max((price[0] for price in prices), default=0.0), max((price[1] for price in prices), default=0.0)


def explicit_or_known_price(spec: ModelSpec) -> tuple[float, float] | None:
    """A paid price only when both sides are known; local/self-hosted models are explicitly free."""
    if spec.input_cost_per_mtok is not None or spec.output_cost_per_mtok is not None:
        if spec.input_cost_per_mtok is None or spec.output_cost_per_mtok is None:
            return None
        return spec.input_cost_per_mtok, spec.output_cost_per_mtok
    if spec.provider not in ("openai", "anthropic"):
        return 0.0, 0.0
    return known_price(spec.model)


def price_per_mtok(spec: ModelSpec) -> tuple[float, float]:
    if spec.input_cost_per_mtok is not None or spec.output_cost_per_mtok is not None:
        return spec.input_cost_per_mtok or 0.0, spec.output_cost_per_mtok or 0.0
    if spec.provider not in ("openai", "anthropic"):
        return 0.0, 0.0  # local and self-hosted models: no per-token price (wall time is reported)
    return known_price(spec.model) or (0.0, 0.0)  # unknown price: add it to configs/prices.yaml


def cost_usd(spec: ModelSpec, prompt_tokens: int, completion_tokens: int) -> float:
    input_price, output_price = price_per_mtok(spec)
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
