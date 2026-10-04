"""The Decider interface and the deterministic offline heuristic (no routes, no HTTP)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Sequence

THOUSAND = 1000

# Words shorter than this carry no routing signal ("a", "in", "to").
_MIN_WORD_LENGTH = 3
# A shared word is worth three baseline shares: clearly decisive, never absolute.
_BASE_SCORE = 100
_MATCH_SCORE = 300
# Tasks of this many characters or more lean as far towards expensive routes as they ever will.
_LENGTH_CAP = 2000
_MAX_LENGTH_BONUS = 100


@dataclass(frozen=True)
class Decision:
    pick: int
    probabilities: Mapping[int, int]
    confidence: int
    decider: str


class Decider(ABC):
    """Every decider returns this shape: route id, per-route thousandths, confidence, name."""

    @abstractmethod
    def decide(self, task: str, routes: Sequence[Mapping]) -> Decision:
        """Routes are rows or dicts with `id`, `criteria` and `price_cents`."""


def _words(text: str) -> set[str]:
    """Lowercased word set; a trailing plural "s" is dropped so "typos" matches "typo"."""
    found = set()
    for word in re.findall(r"\w+", text.casefold()):
        if len(word) < _MIN_WORD_LENGTH:
            continue
        found.add(word[:-1] if len(word) > _MIN_WORD_LENGTH and word.endswith("s") else word)
    return found


def _shares_of_thousand(scores: Mapping[int, int]) -> dict[int, int]:
    """Largest-remainder rounding, so the shares always sum to exactly 1000."""
    total = sum(scores.values())
    shares = {rid: score * THOUSAND // total for rid, score in scores.items()}
    leftover = THOUSAND - sum(shares.values())
    by_remainder = sorted(scores, key=lambda rid: (-(scores[rid] * THOUSAND % total), rid))
    for rid in by_remainder[:leftover]:
        shares[rid] += 1
    return shares


class OfflineDecider(Decider):
    """Keyword-and-length heuristic.

    Each route scores a baseline, plus a bonus per distinct word its criteria share with
    the task, plus a length bonus that grows with the task's length and the route's price
    rank (the number of routes strictly cheaper, so equal prices rank equally).
    """

    name = "offline"

    def decide(self, task: str, routes: Sequence[Mapping]) -> Decision:
        if not routes:
            raise ValueError("at least one route is required")
        task_words = _words(task)
        length = min(len(task), _LENGTH_CAP)
        prices = [r["price_cents"] for r in routes]
        scores = {}
        for r in routes:
            rank = sum(1 for p in prices if p < r["price_cents"])
            bonus = _MAX_LENGTH_BONUS * length * rank // (_LENGTH_CAP * max(len(routes) - 1, 1))
            matches = len(task_words & _words(r["criteria"]))
            scores[r["id"]] = _BASE_SCORE + _MATCH_SCORE * matches + bonus
        probabilities = _shares_of_thousand(scores)
        ranked = sorted(probabilities, key=lambda rid: (-probabilities[rid], rid))
        runner_up = probabilities[ranked[1]] if len(ranked) > 1 else 0
        return Decision(
            pick=ranked[0],
            probabilities=probabilities,
            confidence=probabilities[ranked[0]] - runner_up,
            decider=self.name,
        )
