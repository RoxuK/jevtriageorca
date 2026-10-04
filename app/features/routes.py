"""Model routes: the routing policy (name, criteria, target model, price)."""

from __future__ import annotations

from app import db
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, redirect, route

db.migration(
    "routes_001_create",
    "CREATE TABLE IF NOT EXISTS routes ("
    "id INTEGER PRIMARY KEY, name TEXT NOT NULL, criteria TEXT NOT NULL, "
    "target_model TEXT NOT NULL, price_cents INTEGER NOT NULL)",
)
NAV.append(("/routes", "Routes"))

_TEXT_FIELDS = (("name", "Name"), ("criteria", "Criteria"), ("target_model", "Target model"))


def _list_routes() -> list:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT name, criteria, target_model, price_cents FROM routes ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _insert_route(name: str, criteria: str, target_model: str, price_cents: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO routes (name, criteria, target_model, price_cents) VALUES (?, ?, ?, ?)",
                (name, criteria, target_model, price_cents),
            )
    finally:
        conn.close()


def _validate(values: dict[str, str]) -> str:
    """Return an error message, or "" when the submitted values are acceptable."""
    for key, label in _TEXT_FIELDS:
        if not values[key]:
            return f"{label} is required."
    price = values["price_cents"]
    if not (price.isascii() and price.isdigit()):
        return "Price (cents per million tokens) must be a whole number of cents, 0 or more."
    return ""


def _render(values: dict[str, str], error: str = "", status: int = 200) -> Response:
    rows = "".join(
        f"<tr><td>{h(r['name'])}</td><td>{h(r['criteria'])}</td>"
        f"<td>{h(r['target_model'])}</td><td>{h(r['price_cents'])}</td></tr>"
        for r in _list_routes()
    )
    listing = (
        "<table><thead><tr><th>Name</th><th>Criteria</th><th>Target model</th>"
        f"<th>Price (cents per million tokens)</th></tr></thead><tbody>{rows}</tbody></table>"
        if rows
        else '<p class="muted">No routes exist yet.</p>'
    )
    message = f'<p class="error" role="alert">{h(error)}</p>' if error else ""

    def field(key: str, label: str) -> str:
        return f'<label>{h(label)}<input name="{key}" value="{h(values[key])}"></label>'

    form = (
        f'<form method="post" action="/routes">{message}'
        + field("name", "Name")
        + field("criteria", "Criteria (what kinds of task this route handles)")
        + field("target_model", "Target model")
        + field("price_cents", "Price (cents per million tokens)")
        + "<button type=\"submit\">Add route</button></form>"
    )
    body = f'<h1>Routes</h1><div class="card">{listing}</div><div class="card">{form}</div>'
    return html_response(page("Routes", body), status)


@route("GET", "/routes")
def list_routes(req: Request) -> Response:
    return _render({"name": "", "criteria": "", "target_model": "", "price_cents": ""})


@route("POST", "/routes")
def add_route(req: Request) -> Response:
    form = req.form
    values = {k: form.get(k, "") for k in ("name", "criteria", "target_model", "price_cents")}
    error = _validate(values)
    if error:
        return _render(values, error, 400)
    _insert_route(values["name"], values["criteria"], values["target_model"], int(values["price_cents"]))
    return redirect("/routes")
