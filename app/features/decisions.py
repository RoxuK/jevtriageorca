"""Decision log: every saved decision, newest first. Read-only."""

from __future__ import annotations

from app import db
from app.features.decider import format_thousandths
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, route

NAV.append(("/decisions", "Log"))


def _load_decisions() -> list:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT id, task, chosen_route_name, confidence, decider, created_at, escalated "
            "FROM decisions ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()


def _row(d) -> str:
    return (
        f"<tr><td>{h(d['created_at'])}</td><td>{h(d['task'])}</td><td>{h(d['chosen_route_name'])}</td>"
        f"<td>{format_thousandths(d['confidence'])}</td><td>{h(d['decider'])}</td>"
        f"<td>{'yes' if d['escalated'] else 'no'}</td>"
        f'<td><a href="/decisions/{d["id"]}">View</a></td></tr>'
    )


@route("GET", "/decisions")
def list_decisions(req: Request) -> Response:
    decisions = _load_decisions()
    if not decisions:
        content = '<p class="muted">No decisions yet. <a href="/tester">Try the tester</a>.</p>'
    else:
        content = (
            "<table><thead><tr><th>Time (UTC)</th><th>Task</th><th>Route</th><th>Confidence</th>"
            "<th>Decider</th><th>Escalated</th><th></th></tr></thead>"
            f"<tbody>{''.join(_row(d) for d in decisions)}</tbody></table>"
        )
    return html_response(page("Log", f'<h1>Log</h1><div class="card">{content}</div>'))
