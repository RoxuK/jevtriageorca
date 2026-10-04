"""Escalation rule and its two editable thresholds, stored as integer thousandths.

An unsure decision (confidence below the confidence threshold) goes to the most
expensive route when that route holds at least the share threshold of probability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from app import db
from app.features.decider import THOUSAND, Decision
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, redirect, route

db.migration(
    "thresholds_001_create",
    "CREATE TABLE IF NOT EXISTS thresholds ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), confidence INTEGER NOT NULL, share INTEGER NOT NULL);"
    "INSERT OR IGNORE INTO thresholds (id, confidence, share) VALUES (1, 500, 200)",
)
NAV.append(("/thresholds", "Thresholds"))

_DECIMAL = re.compile(r"[0-9](?:\.[0-9]{1,3})?")
_FIELDS = (("confidence_threshold", "Confidence threshold"), ("share_threshold", "Share threshold"))


@dataclass(frozen=True)
class Thresholds:
    confidence: int
    share: int


def load_thresholds() -> Thresholds:
    conn = db.connect()
    try:
        row = conn.execute("SELECT confidence, share FROM thresholds WHERE id = 1").fetchone()
        return Thresholds(row["confidence"], row["share"])
    finally:
        conn.close()


def _save_thresholds(thresholds: Thresholds) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE thresholds SET confidence = ?, share = ? WHERE id = 1",
                (thresholds.confidence, thresholds.share),
            )
    finally:
        conn.close()


def most_expensive_route_id(routes: Sequence[Mapping]) -> int:
    """Highest price; the lowest id wins a tie."""
    return min(routes, key=lambda r: (-r["price_cents"], r["id"]))["id"]


def apply_escalation(
    decision: Decision, routes: Sequence[Mapping], thresholds: Thresholds
) -> tuple[int, bool]:
    """The route to use and whether escalation fired. Fires whenever both conditions hold,
    even if the decider already picked the most expensive route."""
    expensive = most_expensive_route_id(routes)
    fires = (
        decision.confidence < thresholds.confidence
        and decision.probabilities[expensive] >= thresholds.share
    )
    return (expensive, True) if fires else (decision.pick, False)


def _parse_decimal(text: str) -> int | None:
    """Thousandths for a decimal from 0 to 1 with up to three places, or None."""
    if not _DECIMAL.fullmatch(text):
        return None
    whole, _, fraction = text.partition(".")
    value = int(whole) * THOUSAND + int(fraction.ljust(3, "0") or 0)
    return value if value <= THOUSAND else None


def _format_decimal(value: int) -> str:
    return f"{value // THOUSAND}.{value % THOUSAND:03d}".rstrip("0").rstrip(".")


def _render(values: dict[str, str], error: str = "", status: int = 200) -> Response:
    message = f'<p class="error" role="alert">{h(error)}</p>' if error else ""
    fields = "".join(
        f'<label>{h(label)}<input name="{key}" value="{h(values[key])}"></label>' for key, label in _FIELDS
    )
    form = (
        f'<form method="post" action="/thresholds">{message}{fields}'
        '<button type="submit">Save thresholds</button></form>'
    )
    body = (
        "<h1>Thresholds</h1>"
        '<p class="muted">Decimals from 0 to 1. A decision escalates to the most expensive route when '
        "its confidence is below the confidence threshold and that route's probability is at least "
        "the share threshold.</p>"
        f'<div class="card">{form}</div>'
    )
    return html_response(page("Thresholds", body), status)


@route("GET", "/thresholds")
def thresholds_form(req: Request) -> Response:
    stored = load_thresholds()
    return _render(
        {
            "confidence_threshold": _format_decimal(stored.confidence),
            "share_threshold": _format_decimal(stored.share),
        }
    )


@route("POST", "/thresholds")
def update_thresholds(req: Request) -> Response:
    values = {key: req.form.get(key, "") for key, _ in _FIELDS}
    parsed = {key: _parse_decimal(values[key]) for key, _ in _FIELDS}
    for key, label in _FIELDS:
        if parsed[key] is None:
            return _render(values, f"{label} must be a decimal from 0 to 1 with at most three places.", 400)
    _save_thresholds(Thresholds(parsed["confidence_threshold"], parsed["share_threshold"]))
    return redirect("/thresholds")
