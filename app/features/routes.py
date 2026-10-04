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

_MAX_PRICE_CENTS = 2**63 - 1  # SQLite INTEGER ceiling

_TEXT_FIELDS = (("name", "Name"), ("criteria", "Criteria"), ("target_model", "Target model"))


def _list_routes() -> list:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT id, name, criteria, target_model, price_cents FROM routes ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _find_route(raw_id: str):
    """The stored route for a path id, or None when the id is malformed or unknown."""
    route_id = _parse_uint(raw_id)
    if route_id is None:
        return None
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT id, name, criteria, target_model, price_cents FROM routes WHERE id = ?",
            (route_id,),
        ).fetchone()
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


def _update_route(route_id: int, name: str, criteria: str, target_model: str, price_cents: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute(
                "UPDATE routes SET name = ?, criteria = ?, target_model = ?, price_cents = ? WHERE id = ?",
                (name, criteria, target_model, price_cents, route_id),
            )
    finally:
        conn.close()


def _delete_route(route_id: int) -> None:
    conn = db.connect()
    try:
        with conn:
            conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
    finally:
        conn.close()


def _parse_uint(text: str) -> int | None:
    """A non-negative whole number in SQLite's integer range, or None."""
    if not (text.isascii() and text.isdigit()) or len(text) > len(str(_MAX_PRICE_CENTS)):
        return None
    price = int(text)
    return price if price <= _MAX_PRICE_CENTS else None


def _validate(values: dict[str, str]) -> str:
    """Return an error message, or "" when the submitted values are acceptable."""
    for key, label in _TEXT_FIELDS:
        if not values[key]:
            return f"{label} is required."
    if _parse_uint(values["price_cents"]) is None:
        return "Price (cents per million tokens) must be a whole number of cents, 0 or more."
    return ""


def _not_found() -> Response:
    return html_response(page("Not found", "<h1>Route not found</h1>"), 404)


def _form_values(req: Request) -> dict[str, str]:
    form = req.form
    return {k: form.get(k, "") for k in ("name", "criteria", "target_model", "price_cents")}


def _render(
    values: dict[str, str], error: str = "", status: int = 200, edit_id: int | None = None
) -> Response:
    """The routes page; the form adds a route, or edits route `edit_id` when given."""
    rows = "".join(
        f"<tr><td>{h(r['name'])}</td><td>{h(r['criteria'])}</td>"
        f"<td>{h(r['target_model'])}</td><td>{h(r['price_cents'])}</td>"
        f'<td><a href="/routes/{r["id"]}/edit">Edit</a> '
        f'<form method="post" action="/routes/{r["id"]}/delete">'
        '<button type="submit">Delete</button></form></td></tr>'
        for r in _list_routes()
    )
    listing = (
        "<table><thead><tr><th>Name</th><th>Criteria</th><th>Target model</th>"
        f"<th>Price (cents per million tokens)</th><th></th></tr></thead><tbody>{rows}</tbody></table>"
        if rows
        else '<p class="muted">No routes exist yet.</p>'
    )
    message = f'<p class="error" role="alert">{h(error)}</p>' if error else ""

    def field(key: str, label: str) -> str:
        return f'<label>{h(label)}<input name="{key}" value="{h(values[key])}"></label>'

    action, button = ("/routes", "Add route") if edit_id is None else (f"/routes/{edit_id}/edit", "Save route")
    form = (
        f'<form method="post" action="{action}">{message}'
        + field("name", "Name")
        + field("criteria", "Criteria (what kinds of task this route handles)")
        + field("target_model", "Target model")
        + field("price_cents", "Price (cents per million tokens)")
        + f'<button type="submit">{button}</button></form>'
    )
    body = f'<h1>Routes</h1><div class="card">{listing}</div><div class="card">{form}</div>'
    return html_response(page("Routes", body), status)


@route("GET", "/routes")
def list_routes(req: Request) -> Response:
    return _render({"name": "", "criteria": "", "target_model": "", "price_cents": ""})


@route("POST", "/routes")
def add_route(req: Request) -> Response:
    values = _form_values(req)
    error = _validate(values)
    if error:
        return _render(values, error, 400)
    _insert_route(values["name"], values["criteria"], values["target_model"], _parse_uint(values["price_cents"]))
    return redirect("/routes")


@route("GET", "/routes/{route_id}/edit")
def edit_route_form(req: Request) -> Response:
    stored = _find_route(req.params["route_id"])
    if stored is None:
        return _not_found()
    values = {k: str(stored[k]) for k in ("name", "criteria", "target_model", "price_cents")}
    return _render(values, edit_id=stored["id"])


@route("POST", "/routes/{route_id}/edit")
def edit_route(req: Request) -> Response:
    stored = _find_route(req.params["route_id"])
    if stored is None:
        return _not_found()
    values = _form_values(req)
    error = _validate(values)
    if error:
        return _render(values, error, 400, edit_id=stored["id"])
    _update_route(
        stored["id"], values["name"], values["criteria"], values["target_model"], _parse_uint(values["price_cents"])
    )
    return redirect("/routes")


@route("POST", "/routes/{route_id}/delete")
def delete_route(req: Request) -> Response:
    stored = _find_route(req.params["route_id"])
    if stored is None:
        return _not_found()
    _delete_route(stored["id"])
    return redirect("/routes")
