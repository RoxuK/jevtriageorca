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


_FIELD_KEYS = ("name", "criteria", "target_model", "price_cents")


def _list_routes() -> list:
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT id, name, criteria, target_model, price_cents FROM routes ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _get_route(route_id: int):
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT id, name, criteria, target_model, price_cents FROM routes WHERE id = ?",
            (route_id,),
        ).fetchone()
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


def _parse_price(text: str) -> int | None:
    """Whole cents in SQLite's integer range, or None."""
    if not (text.isascii() and text.isdigit()) or len(text) > len(str(_MAX_PRICE_CENTS)):
        return None
    price = int(text)
    return price if price <= _MAX_PRICE_CENTS else None


def _validate(values: dict[str, str]) -> str:
    """Return an error message, or "" when the submitted values are acceptable."""
    for key, label in _TEXT_FIELDS:
        if not values[key]:
            return f"{label} is required."
    if _parse_price(values["price_cents"]) is None:
        return "Price (cents per million tokens) must be a whole number of cents, 0 or more."
    return ""


def _form(action: str, values: dict[str, str], button: str, error: str = "") -> str:
    message = f'<p class="error" role="alert">{h(error)}</p>' if error else ""

    def field(key: str, label: str) -> str:
        return f'<label>{h(label)}<input name="{key}" value="{h(values[key])}"></label>'

    return (
        f'<form method="post" action="{h(action)}">{message}'
        + field("name", "Name")
        + field("criteria", "Criteria (what kinds of task this route handles)")
        + field("target_model", "Target model")
        + field("price_cents", "Price (cents per million tokens)")
        + f'<button type="submit">{h(button)}</button></form>'
    )


def _row(r) -> str:
    rid = r["id"]
    return (
        f"<tr><td>{h(r['name'])}</td><td>{h(r['criteria'])}</td>"
        f"<td>{h(r['target_model'])}</td><td>{h(r['price_cents'])}</td>"
        f'<td><a href="/routes/{rid}/edit">Edit</a> '
        f'<form method="post" action="/routes/{rid}/delete"><button type="submit">Delete</button></form></td></tr>'
    )


def _render(values: dict[str, str], error: str = "", status: int = 200) -> Response:
    rows = "".join(_row(r) for r in _list_routes())
    listing = (
        "<table><thead><tr><th>Name</th><th>Criteria</th><th>Target model</th>"
        f"<th>Price (cents per million tokens)</th><th></th></tr></thead><tbody>{rows}</tbody></table>"
        if rows
        else '<p class="muted">No routes exist yet.</p>'
    )
    form = _form("/routes", values, "Add route", error)
    body = f'<h1>Routes</h1><div class="card">{listing}</div><div class="card">{form}</div>'
    return html_response(page("Routes", body), status)


def _render_edit(route_id: int, values: dict[str, str], error: str = "", status: int = 200) -> Response:
    form = _form(f"/routes/{route_id}/edit", values, "Save route", error)
    body = f'<h1>Edit route</h1><div class="card">{form}</div><p><a href="/routes">Back to routes</a></p>'
    return html_response(page("Edit route", body), status)


def _find_route(req: Request):
    """The stored route named by the {route_id} path segment, or None for a non-numeric or unknown id."""
    raw = req.params["route_id"]
    route_id = _parse_price(raw)  # same bounds as a price: ASCII digits that fit SQLite's integer
    return None if route_id is None else _get_route(route_id)


def _submitted(req: Request) -> dict[str, str]:
    return {k: req.form.get(k, "") for k in _FIELD_KEYS}


@route("GET", "/routes")
def list_routes(req: Request) -> Response:
    return _render(dict.fromkeys(_FIELD_KEYS, ""))


@route("POST", "/routes")
def add_route(req: Request) -> Response:
    values = _submitted(req)
    error = _validate(values)
    if error:
        return _render(values, error, 400)
    _insert_route(values["name"], values["criteria"], values["target_model"], _parse_price(values["price_cents"]))
    return redirect("/routes")


@route("GET", "/routes/{route_id}/edit")
def edit_route_form(req: Request) -> Response:
    stored = _find_route(req)
    if stored is None:
        return html_response(page("Not found", "<h1>Route not found</h1>"), 404)
    return _render_edit(stored["id"], {k: str(stored[k]) for k in _FIELD_KEYS})


@route("POST", "/routes/{route_id}/edit")
def edit_route(req: Request) -> Response:
    stored = _find_route(req)
    if stored is None:
        return html_response(page("Not found", "<h1>Route not found</h1>"), 404)
    values = _submitted(req)
    error = _validate(values)
    if error:
        return _render_edit(stored["id"], values, error, 400)
    _update_route(stored["id"], values["name"], values["criteria"], values["target_model"], _parse_price(values["price_cents"]))
    return redirect("/routes")


@route("POST", "/routes/{route_id}/delete")
def delete_route(req: Request) -> Response:
    stored = _find_route(req)
    if stored is None:
        return html_response(page("Not found", "<h1>Route not found</h1>"), 404)
    _delete_route(stored["id"])
    return redirect("/routes")
