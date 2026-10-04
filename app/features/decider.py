"""The Decider interface and the deterministic OfflineDecider.

Every decider returns a `Decision`: probabilities and confidence are integer
thousandths (0..1000) and the probabilities sum to exactly 1000.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence

THOUSAND = 1000

_WORD = re.compile(r"[^\W_]+")
_MIN_WORD_LENGTH = 3
_BASE_WEIGHT = 100
_SHARED_WORD_WEIGHT = 300
_LENGTH_WEIGHT = 100
# Task length (characters) at which each further step of length bias starts.
_LENGTH_CUTOFFS = (200, 800)


@dataclass(frozen=True)
class Decision:
    pick: int
    probabilities: Mapping[int, int]
    confidence: int
    decider: str


class Decider(ABC):
    name: str

    @abstractmethod
    def decide(self, task: str, routes: Sequence[Mapping]) -> Decision:
        """Choose among routes, each readable as `id`, `criteria` and `price_cents`."""


def _words(text: str) -> set[str]:
    """Lowercased words of 3+ characters, with a plural 's' removed ("typos" -> "typo")."""
    found = set()
    for word in _WORD.findall(text.lower()):
        if len(word) > _MIN_WORD_LENGTH and word.endswith("s"):
            word = word[:-1]
        if len(word) >= _MIN_WORD_LENGTH:
            found.add(word)
    return found


def _length_tier(task: str) -> int:
    return sum(len(task) >= cutoff for cutoff in _LENGTH_CUTOFFS)


def _price_ranks(routes: Sequence[Mapping]) -> dict[int, int]:
    """Route id -> position of its price among the distinct prices, cheapest at 0."""
    prices = sorted({r["price_cents"] for r in routes})
    return {r["id"]: prices.index(r["price_cents"]) for r in routes}


def _to_thousandths(weights: Mapping[int, int]) -> dict[int, int]:
    """Scale positive weights to integers summing to 1000; the remainder goes to the
    largest fractional parts, lowest route id first."""
    total = sum(weights.values())
    shares = {rid: w * THOUSAND // total for rid, w in weights.items()}
    by_fraction = sorted(weights, key=lambda rid: (-(weights[rid] * THOUSAND % total), rid))
    for rid in by_fraction[: THOUSAND - sum(shares.values())]:
        shares[rid] += 1
    return shares


class OfflineDecider(Decider):
    """Keyword-and-length heuristic: each route starts equal, gains weight for every
    distinct word its criteria share with the task, and longer tasks add weight in
    proportion to the route's price rank. Confidence is the lead over the runner-up."""

    name = "offline"

    def decide(self, task: str, routes: Sequence[Mapping]) -> Decision:
        if not routes:
            raise ValueError("decide() needs at least one route")
        task_words = _words(task)
        tier = _length_tier(task)
        ranks = _price_ranks(routes)
        weights = {
            r["id"]: _BASE_WEIGHT
            + _SHARED_WORD_WEIGHT * len(task_words & _words(r["criteria"]))
            + _LENGTH_WEIGHT * tier * ranks[r["id"]]
            for r in routes
        }
        probabilities = _to_thousandths(weights)
        ordered = sorted(probabilities, key=lambda rid: (-probabilities[rid], rid))
        runner_up = probabilities[ordered[1]] if len(ordered) > 1 else 0
        return Decision(
            pick=ordered[0],
            probabilities=probabilities,
            confidence=probabilities[ordered[0]] - runner_up,
            decider=self.name,
        )
