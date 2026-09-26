from __future__ import annotations

import pytest

from llm_arena.eval.compare import last_number, result_columns_cover, token_f1
from llm_arena.eval.metrics import (
    bootstrap_ci,
    bradley_terry,
    cohen_kappa,
    paired_permutation_test,
    pass_at_k,
    pass_hat_k,
)


def test_pass_at_k_and_pass_hat_k() -> None:
    assert pass_at_k(4, 2, 1) == pytest.approx(0.5)
    assert pass_at_k(4, 2, 3) == 1.0
    assert pass_hat_k(4, 2, 2) == pytest.approx(1 / 6)
    assert pass_hat_k(3, 3, 3) == 1.0 and pass_hat_k(3, 2, 3) == 0.0


def test_bootstrap_ci_contains_mean() -> None:
    mean, low, high = bootstrap_ci([0, 1, 1, 1, 0, 1, 1, 0])
    assert low <= mean <= high and mean == pytest.approx(0.625)


def test_paired_permutation_detects_consistent_difference() -> None:
    assert paired_permutation_test([1.0] * 20, [0.0] * 20) < 0.01
    assert paired_permutation_test([1, 0, 1, 0], [0, 1, 0, 1]) > 0.5


def test_cohen_kappa() -> None:
    assert cohen_kappa(["p", "f", "p", "f"], ["p", "f", "p", "f"]) == 1.0
    assert cohen_kappa(["p", "p", "f", "f"], ["p", "f", "p", "f"]) == pytest.approx(0.0)


def test_bradley_terry_orders_players_and_handles_ties() -> None:
    # winner is positional: "a" = first player of the pair won
    battles = [("a", "b", "a")] * 6 + [("b", "c", "a")] * 6 + [("a", "c", "tie")]
    ratings = bradley_terry(battles)
    assert ratings["a"] > ratings["b"] > ratings["c"]


def test_result_columns_cover_ignores_order_and_extra_columns() -> None:
    gold = [("e-bike", 123.456)]
    assert result_columns_cover(gold, [(123.46, "E-bike ", 99)])
    assert not result_columns_cover(gold, [("e-bike", 12345.6)])
    assert not result_columns_cover(gold, [])


def test_answer_helpers() -> None:
    assert last_number("so the total is $1,234.50.") == 1234.5
    assert token_f1("the river Selm", "Selm") == pytest.approx(2 / 3)
