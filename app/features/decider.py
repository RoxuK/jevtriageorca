"""The Decider interface and the deterministic OfflineDecider.

Every decider returns a `Decision`: probabilities and confidence are integer
thousandths (0..1000) and the probabilities sum to exactly 1000.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

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


JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"
_JEV_TIMEOUT_SECONDS = 10
_MICRO = 1_000_000

# Sends a prepared request and returns (HTTP status, response body).
Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def urllib_transport(request: urllib.request.Request) -> tuple[int, bytes]:
    with urllib.request.urlopen(request, timeout=_JEV_TIMEOUT_SECONDS) as response:
        return response.status, response.read()


def _option_key(route_id: int) -> str:
    return f"route_{route_id}"


def _fraction(value: object) -> float:
    """A JSON number within 0..1, else ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"expected a number between 0 and 1, got {value!r}")
    return float(value)


class JevDecider(Decider):
    """Asks Jev on OpenRouter one `choice` question whose options are the routes. Any
    failure (network, HTTP status, malformed answer) is answered by the OfflineDecider
    instead, so a decision is always made."""

    name = "jev"

    def __init__(self, api_key: str, transport: Transport = urllib_transport) -> None:
        self._api_key = api_key
        self._transport = transport
        self._fallback = OfflineDecider()

    def decide(self, task: str, routes: Sequence[Mapping]) -> Decision:
        if not routes:
            raise ValueError("decide() needs at least one route")
        try:
            return self._ask(task, routes)
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, AttributeError):
            # OSError covers URLError, HTTPError and timeouts; HTTPException covers truncated
            # or malformed responses; ValueError covers bad JSON.
            return self._fallback.decide(task, routes)

    def _ask(self, task: str, routes: Sequence[Mapping]) -> Decision:
        body = {
            "model": JEV_MODEL,
            "state": {"task": task},
            "questions": {
                "route": {
                    "type": "choice",
                    "instructions": "Which route should handle this coding task?",
                    "criteria": {_option_key(r["id"]): r["criteria"] for r in routes},
                }
            },
        }
        request = urllib.request.Request(
            JEV_URL,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        status, payload = self._transport(request)
        if status != 200:
            raise ValueError(f"unexpected HTTP status {status}")
        answer = json.loads(payload)["answers"]["route"]
        keys = {_option_key(r["id"]): r["id"] for r in routes}
        weights = {rid: round(_fraction(answer["probabilities"][key]) * _MICRO) for key, rid in keys.items()}
        if not sum(weights.values()):
            raise ValueError("all probabilities are zero")
        return Decision(
            pick=keys[answer["choice"]],
            probabilities=_to_thousandths(weights),
            confidence=round(_fraction(answer["confidence"]) * THOUSAND),
            decider=self.name,
        )
