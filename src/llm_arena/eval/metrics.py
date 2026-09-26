"""Aggregate statistics: pass@k, pass^k, bootstrap CIs, paired tests, Cohen's kappa, Bradley–Terry."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimate of P(at least one of k samples passes) from n samples with c passes."""
    if k > n:
        raise ValueError("k must not exceed n")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """τ-bench pass^k: P(all k samples pass) — reliability rather than capability."""
    if k > n:
        raise ValueError("k must not exceed n")
    return math.comb(c, k) / math.comb(n, k)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float, float]:
    """(mean, lower, upper) percentile bootstrap interval."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    return mean(values), percentile(means, alpha / 2), percentile(means, 1 - alpha / 2)


def paired_permutation_test(a: Sequence[float], b: Sequence[float], *, resamples: int = 5000, seed: int = 0) -> float:
    """Two-sided p-value for mean(a - b) == 0 on paired observations (same tasks, two configs).

    Pairing matters: task difficulty varies far more than config quality, and an unpaired test
    would drown the config effect in that variance.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    if not diffs:
        return float("nan")
    observed = abs(mean(diffs))
    rng = random.Random(seed)
    extreme = sum(
        1 for _ in range(resamples) if abs(mean([d if rng.random() < 0.5 else -d for d in diffs])) >= observed - 1e-12
    )
    return (extreme + 1) / (resamples + 1)


def cohen_kappa(labels_a: Sequence[object], labels_b: Sequence[object]) -> float:
    """Agreement beyond chance between two raters (e.g. LLM judge vs human labels)."""
    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("need two non-empty label sequences of equal length")
    n = len(labels_a)
    observed = sum(x == y for x, y in zip(labels_a, labels_b, strict=True)) / n
    categories = set(labels_a) | set(labels_b)
    expected = sum((list(labels_a).count(c) / n) * (list(labels_b).count(c) / n) for c in categories)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def bradley_terry(
    battles: Sequence[tuple[str, str, str]], *, iterations: int = 200, base: float = 1000.0
) -> dict[str, float]:
    """Fit Bradley–Terry strengths from (a, b, winner) with winner in {"a", "b", "tie"}.

    Uses the MM algorithm (Hunter 2004); a tie counts as half a win for each side. A small
    prior of one virtual tie against a reference player keeps ratings finite for undefeated
    players. Returns Elo-scaled ratings (400 · log10 strength, centred on `base`).
    """
    players = sorted({p for a, b, _ in battles for p in (a, b)})
    if not players:
        return {}
    wins: dict[str, float] = defaultdict(float)
    pair_counts: dict[tuple[str, str], float] = defaultdict(float)
    for a, b, winner in battles:
        wins[a] += 1.0 if winner == "a" else 0.5 if winner == "tie" else 0.0
        wins[b] += 1.0 if winner == "b" else 0.5 if winner == "tie" else 0.0
        pair_counts[(a, b)] += 1
        pair_counts[(b, a)] += 1
    strength = dict.fromkeys(players, 1.0)
    for _ in range(iterations):
        updated = {}
        for player in players:
            denominator = sum(
                count / (strength[player] + strength[other])
                for (first, other), count in pair_counts.items()
                if first == player
            )
            denominator += 1.0 / (strength[player] + 1.0)  # virtual tie vs reference strength 1
            updated[player] = (wins[player] + 0.5) / denominator
        geometric_mean = math.exp(mean([math.log(s) for s in updated.values()]))
        strength = {p: s / geometric_mean for p, s in updated.items()}
    return {p: base + 400 * math.log10(s) for p, s in strength.items()}
