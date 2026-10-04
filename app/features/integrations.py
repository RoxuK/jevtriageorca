"""Integrations: renders the text of a local route proxy built from the saved routes and
thresholds. The app only shows the text; it never runs, writes or installs it."""

from __future__ import annotations

from app.features.decider import JEV_MODEL, JEV_URL
from app.features.routes import _list_routes
from app.features.thresholds import Thresholds, load_thresholds
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, route

NAV.append(("/integrations", "Integrations"))

PROXY_FILE = "route_proxy.py"
PROXY_PORT = 8787
UPSTREAM_BASE_URL = "https://openrouter.ai/api"

_PROXY_TEMPLATE = '''\
"""Local route proxy: asks Jev which route fits each request, then forwards the request
with that route's target model. Standard library only. Run: python route_proxy.py
Needs the OPENROUTER_API_KEY environment variable."""

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = @PORT@
UPSTREAM_BASE_URL = @UPSTREAM@
JEV_URL = @JEV_URL@
JEV_MODEL = @JEV_MODEL@
# Thresholds in thousandths: escalate to the most expensive route when confidence is below
# CONFIDENCE_THRESHOLD and that route's probability is at least SHARE_THRESHOLD.
CONFIDENCE_THRESHOLD = @CONFIDENCE@
SHARE_THRESHOLD = @SHARE@
# (id, name, criteria, target model, price in cents per million tokens)
ROUTES = [
@ROUTES@
]


def task_text(body):
    """The last user message, as plain text."""
    for message in reversed(body.get("messages", [])):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content)
    return ""


def ask_jev(task):
    question = {
        "type": "choice",
        "instructions": "Which route should handle this coding task?",
        "criteria": {"route_%d" % r[0]: r[2] for r in ROUTES},
    }
    payload = {"model": JEV_MODEL, "state": {"task": task}, "questions": {"route": question}}
    request = urllib.request.Request(
        JEV_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())["answers"]["route"]


def choose_route(task):
    """The route to use. Falls back to the most expensive route when Jev cannot answer."""
    expensive = min(ROUTES, key=lambda r: (-r[4], r[0]))
    try:
        answer = ask_jev(task)
        confidence = round(answer["confidence"] * 1000)
        share = round(answer["probabilities"]["route_%d" % expensive[0]] * 1000)
        if confidence < CONFIDENCE_THRESHOLD and share >= SHARE_THRESHOLD:
            return expensive
        chosen = int(answer["choice"].split("_", 1)[1])
        return next(r for r in ROUTES if r[0] == chosen)
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as err:
        print("route_proxy: Jev failed (%s: %s); using route %d" % (type(err).__name__, err, expensive[0]), file=sys.stderr)
        return expensive


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            self.send_error(400, "request body must be JSON")
            return
        if not isinstance(body, dict):
            self.send_error(400, "request body must be a JSON object")
            return
        body["model"] = choose_route(task_text(body))[3]
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "accept-encoding")}
        forward = urllib.request.Request(
            UPSTREAM_BASE_URL + self.path, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(forward, timeout=300) as upstream:
                status, data, kind = upstream.status, upstream.read(), upstream.headers.get("Content-Type")
        except urllib.error.HTTPError as err:
            status, data, kind = err.code, err.read(), err.headers.get("Content-Type")
        except OSError:
            self.send_error(502, "upstream unreachable")
            return
        self.send_response(status)
        self.send_header("Content-Type", kind or "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
'''


def generate_proxy(routes, thresholds: Thresholds) -> str:
    """The text of route_proxy.py. Every stored value is embedded with repr(), so no route
    text can change the structure of the program."""
    route_lines = "".join(
        f"    {(r['id'], r['name'], r['criteria'], r['target_model'], r['price_cents'])!r},\n" for r in routes
    )
    replacements = {
        "@PORT@": repr(PROXY_PORT),
        "@UPSTREAM@": repr(UPSTREAM_BASE_URL),
        "@JEV_URL@": repr(JEV_URL),
        "@JEV_MODEL@": repr(JEV_MODEL),
        "@CONFIDENCE@": repr(thresholds.confidence),
        "@SHARE@": repr(thresholds.share),
        "@ROUTES@": route_lines.rstrip("\n"),
    }
    text = _PROXY_TEMPLATE
    # @ROUTES@ comes last so route text is never scanned for placeholders.
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


@route("GET", "/integrations")
def integrations_index(req: Request) -> Response:
    body = (
        "<h1>Integrations</h1>"
        '<div class="card"><h2><a href="/integrations/proxy">CLI</a></h2>'
        f'<p class="muted">The generated {h(PROXY_FILE)} route proxy.</p></div>'
    )
    return html_response(page("Integrations", body))


@route("GET", "/integrations/proxy")
def integrations_proxy(req: Request) -> Response:
    routes = _list_routes()
    if routes:
        text = generate_proxy(routes, load_thresholds())
        content = f'<div class="card"><pre>{h(text)}</pre></div>'
    else:
        content = '<p class="muted">Routes are needed first: <a href="/routes">add routes</a>.</p>'
    body = (
        f"<h1>CLI: {h(PROXY_FILE)}</h1>"
        f'<p class="muted">Save this text as {h(PROXY_FILE)} and run it yourself. '
        "This app only shows the text; it does not run or install it.</p>"
        f"{content}"
    )
    return html_response(page("CLI proxy", body))
