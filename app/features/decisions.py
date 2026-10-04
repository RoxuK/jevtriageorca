"""Decision log: every saved decision, newest first, with a right/wrong label per decision."""

from __future__ import annotations

from app import db
from app.features.decider import format_thousandths
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, redirect, route

db.migration(
    "decisions_001_labels",
    "CREATE TABLE IF NOT EXISTS decision_labels ("
    "decision_id INTEGER PRIMARY KEY, verdict TEXT NOT NULL, "
    "correct_route_id INTEGER, correct_route_name TEXT)",
)
NAV.append(("/decisions", "Log"))


_MAX_ID_DIGITS = len(str(2**63 - 1))  # SQLite INTEGER ceiling


def _parse_id(text: str) -> int | None:
    """A whole number in SQLite's integer range, or None."""
    if not (text.isascii() and text.isdigit()) or len(text) > _MAX_ID_DIGITS:
        return None
    value = int(text)
    return value if value <= 2**63 - 1 else None


def _load_decisions() -> list:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT d.id, d.task, d.chosen_route_name, d.confidence, d.decider, d.created_at, d.escalated, "
            "l.verdict, l.correct_route_name "
            "FROM decisions d LEFT JOIN decision_labels l ON l.decision_id = d.id ORDER BY d.id DESC"
        ).fetchall()
    finally:
        conn.close()


def _load_routes() -> list:
    conn = db.connect()
    try:
        return conn.execute("SELECT id, name FROM routes ORDER BY id").fetchall()
    finally:
        conn.close()


def _save_label(raw_id: str, verdict: str, raw_route_id: str) -> str | None:
    """Look up the decision and write its label. Returns None on success, or "missing"
    for an unknown decision, or a validation message. Nothing is stored unless it returns None."""
    decision_id = _parse_id(raw_id)
    conn = db.connect()
    try:
        if decision_id is None or not conn.execute(
            "SELECT 1 FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone():
            return "missing"
        if verdict not in ("right", "wrong"):
            return "Choose a verdict: right or wrong."
        route_id, route_name = None, None
        if verdict == "wrong":
            parsed = _parse_id(raw_route_id)
            found = conn.execute("SELECT name FROM routes WHERE id = ?", (parsed,)).fetchone() if parsed is not None else None
            if found is None:
                return "Pick the route it should have been."
            route_id, route_name = parsed, found["name"]
        with conn:
            conn.execute(
                "INSERT INTO decision_labels (decision_id, verdict, correct_route_id, correct_route_name) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(decision_id) DO UPDATE SET verdict = excluded.verdict, "
                "correct_route_id = excluded.correct_route_id, correct_route_name = excluded.correct_route_name",
                (decision_id, verdict, route_id, route_name),
            )
        return None
    finally:
        conn.close()


def _label_cell(d, routes: list) -> str:
    if d["verdict"] == "right":
        status = "Labelled right"
    elif d["verdict"] == "wrong":
        status = f"Labelled wrong: should be {h(d['correct_route_name'])}"
    else:
        status = "Unlabelled"
    options = "".join(f'<option value="{r["id"]}">{h(r["name"])}</option>' for r in routes)
    return (
        f'<td><span class="badge">{status}</span>'
        f'<form method="post" action="/decisions/{d["id"]}/label">'
        '<select name="verdict"><option value="right">right</option><option value="wrong">wrong</option></select>'
        f'<select name="correct_route_id"><option value="">correct route</option>{options}</select>'
        '<button type="submit">Label</button></form></td>'
    )


def _row(d, routes: list) -> str:
    return (
        f"<tr><td>{h(d['created_at'])}</td><td>{h(d['task'])}</td><td>{h(d['chosen_route_name'])}</td>"
        f"<td>{format_thousandths(d['confidence'])}</td><td>{h(d['decider'])}</td>"
        f"<td>{'yes' if d['escalated'] else 'no'}</td>"
        f'<td><a href="/decisions/{d["id"]}">View</a></td>{_label_cell(d, routes)}</tr>'
    )


_BANDS = ("below 0.5", "0.5 to 0.8", "above 0.8")


def _band(confidence: int) -> str:
    """The summary band for a confidence in stored thousandths."""
    if confidence < 500:
        return _BANDS[0]
    return _BANDS[1] if confidence <= 800 else _BANDS[2]


def _tally(labelled: int, right: int) -> str:
    """"N labelled" plus whole-percent accuracy rounded half up, once something is labelled."""
    if labelled == 0:
        return "0 labelled"
    return f"{labelled} labelled, {(200 * right + labelled) // (2 * labelled)}%"


def _summary(decisions: list) -> str:
    counts = {band: [0, 0] for band in _BANDS}
    for d in decisions:
        if d["verdict"] is None:
            continue
        tally = counts[_band(d["confidence"])]
        tally[0] += 1
        tally[1] += d["verdict"] == "right"
    overall = [sum(t[0] for t in counts.values()), sum(t[1] for t in counts.values())]
    bands = "".join(f"<li>{band}: {_tally(*tally)}</li>" for band, tally in counts.items())
    return f'<div class="summary"><p>Accuracy: {_tally(*overall)}</p><ul>{bands}</ul></div>'


def _render(error: str = "", status: int = 200) -> Response:
    decisions = _load_decisions()
    routes = _load_routes()
    if not decisions:
        content = '<p class="muted">No decisions yet. <a href="/tester">Try the tester</a>.</p>'
    else:
        content = (
            "<table><thead><tr><th>Time (UTC)</th><th>Task</th><th>Route</th><th>Confidence</th>"
            "<th>Decider</th><th>Escalated</th><th></th><th>Label</th></tr></thead>"
            f"<tbody>{''.join(_row(d, routes) for d in decisions)}</tbody></table>"
        )
    banner = f'<p class="error">{h(error)}</p>' if error else ""
    return html_response(
        page("Log", f'<h1>Log</h1>{banner}<div class="card">{_summary(decisions)}{content}</div>'), status
    )


@route("GET", "/decisions")
def list_decisions(req: Request) -> Response:
    return _render()


@route("POST", "/decisions/{decision_id}/label")
def label_decision(req: Request) -> Response:
    form = req.form
    result = _save_label(req.params["decision_id"], form.get("verdict", ""), form.get("correct_route_id", ""))
    if result is None:
        return redirect("/decisions")
    if result == "missing":
        return html_response(page("Not found", "<h1>Decision not found</h1>"), 404)
    return _render(result, 400)
