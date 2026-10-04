"""Route tester: ask the decider where a task would go, and keep the decision.

A decision snapshots route names and has no foreign key to routes, so editing or
deleting a route never changes a saved decision.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from app import db
from app.features.decider import (
    Decider,
    Decision,
    JevDecider,
    OfflineDecider,
    Transport,
    format_thousandths,
    urllib_transport,
)
from app.features.thresholds import apply_escalation, load_thresholds
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, redirect, route

db.migration(
    "tester_001_create_decisions",
    "CREATE TABLE IF NOT EXISTS decisions ("
    "id INTEGER PRIMARY KEY, task TEXT NOT NULL, chosen_route_id INTEGER NOT NULL, "
    "chosen_route_name TEXT NOT NULL, confidence INTEGER NOT NULL, "
    "decider TEXT NOT NULL, created_at TEXT NOT NULL)",
)
db.migration(
    "tester_002_create_decision_probabilities",
    "CREATE TABLE IF NOT EXISTS decision_probabilities ("
    "decision_id INTEGER NOT NULL REFERENCES decisions(id), route_id INTEGER NOT NULL, "
    "route_name TEXT NOT NULL, probability INTEGER NOT NULL, "
    "PRIMARY KEY (decision_id, route_id))",
)
db.migration(
    "tester_003_decisions_escalated",
    "ALTER TABLE decisions ADD COLUMN escalated INTEGER NOT NULL DEFAULT 0",
)
NAV.append(("/tester", "Tester"))

_MAX_ID = 2**63 - 1  # SQLite INTEGER ceiling
_MAX_ID_DIGITS = len(str(_MAX_ID))  # checked before int() to stay under Python's digit limit
_OFFLINE = OfflineDecider()
_jev_transport: Transport = urllib_transport  # replaced by tests so none reaches the network


def _select_decider() -> Decider:
    """Jev when OPENROUTER_API_KEY is set and non-empty, read per request; else offline."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    return JevDecider(api_key, _jev_transport) if api_key else _OFFLINE


def _load_routes() -> list:
    conn = db.connect()
    try:
        return conn.execute("SELECT id, name, criteria, price_cents FROM routes ORDER BY id").fetchall()
    finally:
        conn.close()


def _save_decision(task: str, routes: list, decision: Decision, pick: int, escalated: bool) -> int:
    names = {r["id"]: r["name"] for r in routes}
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.connect()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO decisions "
                "(task, chosen_route_id, chosen_route_name, confidence, decider, created_at, escalated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task, pick, names[pick], decision.confidence, decision.decider, created_at, int(escalated)),
            )
            conn.executemany(
                "INSERT INTO decision_probabilities (decision_id, route_id, route_name, probability) "
                "VALUES (?, ?, ?, ?)",
                [(cursor.lastrowid, rid, names[rid], p) for rid, p in decision.probabilities.items()],
            )
            return cursor.lastrowid
    finally:
        conn.close()


def _find_decision(raw_id: str):
    """(decision row, its probability rows), or None when the id is malformed or unknown."""
    if not (raw_id.isascii() and raw_id.isdigit()) or len(raw_id) > _MAX_ID_DIGITS or int(raw_id) > _MAX_ID:
        return None
    conn = db.connect()
    try:
        decision = conn.execute(
            "SELECT id, task, chosen_route_name, confidence, decider, created_at, escalated FROM decisions WHERE id = ?",
            (int(raw_id),),
        ).fetchone()
        if decision is None:
            return None
        probabilities = conn.execute(
            "SELECT route_name, probability FROM decision_probabilities WHERE decision_id = ? ORDER BY route_id",
            (decision["id"],),
        ).fetchall()
        return decision, probabilities
    finally:
        conn.close()


def _too_few_routes(routes: list) -> bool:
    return len(routes) < 2


def _render_tester(task: str = "", error: str = "", status: int = 200) -> Response:
    if _too_few_routes(_load_routes()):
        error = error or "The tester needs at least two routes."
        body = (
            '<h1>Tester</h1><div class="card">'
            f'<p class="error" role="alert">{h(error)} <a href="/routes">Add routes</a></p></div>'
        )
        return html_response(page("Tester", body), status)
    message = f'<p class="error" role="alert">{h(error)}</p>' if error else ""
    form = (
        f'<form method="post" action="/tester">{message}'
        f'<label>Coding task<textarea name="task" rows="6">{h(task)}</textarea></label>'
        '<button type="submit">Decide route</button></form>'
        '<p><a href="/thresholds">Edit escalation thresholds</a></p>'
    )
    return html_response(page("Tester", f'<h1>Tester</h1><div class="card">{form}</div>'), status)


@route("GET", "/tester")
def tester_form(req: Request) -> Response:
    return _render_tester()


@route("POST", "/tester")
def decide_task(req: Request) -> Response:
    task = req.form.get("task", "")
    routes = _load_routes()
    if _too_few_routes(routes):
        return _render_tester(task, status=400)
    if not task:
        return _render_tester(task, "Task is required.", 400)
    decision = _select_decider().decide(task, routes)
    pick, escalated = apply_escalation(decision, routes, load_thresholds())
    return redirect(f"/decisions/{_save_decision(task, routes, decision, pick, escalated)}")


@route("GET", "/decisions/{decision_id}")
def show_decision(req: Request) -> Response:
    found = _find_decision(req.params["decision_id"])
    if found is None:
        return html_response(page("Not found", "<h1>Decision not found</h1>"), 404)
    decision, probabilities = found
    rows = "".join(
        f"<tr><td>{h(p['route_name'])}</td><td>{format_thousandths(p['probability'])}</td></tr>"
        for p in probabilities
    )
    body = (
        "<h1>Decision</h1>"
        f'<div class="card"><h2>Task</h2><p>{h(decision["task"])}</p>'
        f'<p>Chosen route: <strong>{h(decision["chosen_route_name"])}</strong></p>'
        f'<p>Confidence: {format_thousandths(decision["confidence"])}</p>'
        f'<p>Escalated: {"yes" if decision["escalated"] else "no"}</p>'
        f'<p>Decider: {h(decision["decider"])}</p>'
        f'<p class="muted">Decided at {h(decision["created_at"])}</p></div>'
        '<div class="card"><table><thead><tr><th>Route</th><th>Probability</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )
    return html_response(page("Decision", body))
