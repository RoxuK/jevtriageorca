"""Integrations: renders the text of a local route proxy built from the saved routes and
thresholds. The app only shows the text; it never runs, writes or installs it."""

from __future__ import annotations

import json

from app.features.decider import JEV_MODEL, JEV_URL
from app.features.routes import _list_routes
from app.features.thresholds import Thresholds, load_thresholds
from app.layout import NAV, page
from app.web import Request, Response, h, html_response, route

NAV.append(("/integrations", "Integrations"))

PROXY_FILE = "route_proxy.py"
HOOK_FILE = "route_hook.py"
PROXY_PORT = 8787
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
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


_HOOK_TEMPLATE = '''\
"""UserPromptSubmit hook: asks Jev which route fits the prompt and adds the answer to the
context of the Claude Code session. Standard library only.
Needs the OPENROUTER_API_KEY environment variable."""

import json
import os
import sys
import urllib.request

JEV_URL = @JEV_URL@
JEV_MODEL = @JEV_MODEL@
# (id, name, criteria, target model, price in cents per million tokens)
ROUTES = [
@ROUTES@
]


def main():
    prompt = str(json.load(sys.stdin).get("prompt", ""))
    question = {
        "type": "choice",
        "instructions": "Which route should handle this coding task?",
        "criteria": {"route_%d" % r[0]: r[2] for r in ROUTES},
    }
    payload = {"model": JEV_MODEL, "state": {"task": prompt}, "questions": {"route": question}}
    request = urllib.request.Request(
        JEV_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            chosen = int(json.loads(response.read())["answers"]["route"]["choice"].split("_", 1)[1])
        route = next(r for r in ROUTES if r[0] == chosen)
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as err:
        print("route_hook: Jev failed (%s: %s)" % (type(err).__name__, err), file=sys.stderr)
        return
    note = "Jev suggests route %s (model %s) for this task." % (route[1], route[3])
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}))


main()
'''


def _route_lines(routes) -> str:
    return "".join(
        f"    {(r['id'], r['name'], r['criteria'], r['target_model'], r['price_cents'])!r},\n" for r in routes
    ).rstrip("\n")


def generate_hook(routes) -> str:
    """The text of route_hook.py; stored values are embedded with repr(), as in generate_proxy."""
    text = _HOOK_TEMPLATE
    for placeholder, value in (("@JEV_URL@", repr(JEV_URL)), ("@JEV_MODEL@", repr(JEV_MODEL)), ("@ROUTES@", _route_lines(routes))):
        text = text.replace(placeholder, value)
    return text


def settings_env_snippet() -> str:
    """settings.json env block pointing Claude Code at the local proxy; carries no key value."""
    env = {"ANTHROPIC_BASE_URL": PROXY_URL}
    return json.dumps({"env": env}, indent=2)


def settings_hook_snippet() -> str:
    command = f"python3 {HOOK_FILE}"
    hooks = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}
    return json.dumps({"hooks": hooks}, indent=2)


def generate_proxy(routes, thresholds: Thresholds) -> str:
    """The text of route_proxy.py. Every stored value is embedded with repr(), so no route
    text can change the structure of the program."""
    replacements = {
        "@PORT@": repr(PROXY_PORT),
        "@UPSTREAM@": repr(UPSTREAM_BASE_URL),
        "@JEV_URL@": repr(JEV_URL),
        "@JEV_MODEL@": repr(JEV_MODEL),
        "@CONFIDENCE@": repr(thresholds.confidence),
        "@SHARE@": repr(thresholds.share),
        "@ROUTES@": _route_lines(routes),
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
        '<div class="card"><h2><a href="/integrations/claude-code">CLI: Claude Code</a></h2>'
        '<p class="muted">Settings, an optional hook and the proxy for Claude Code.</p></div>'
        '<div class="card"><h2><a href="/integrations/codex">CLI: Codex</a></h2>'
        '<p class="muted">A config.toml provider, a hook and the proxy for Codex.</p></div>'
        '<div class="card"><h2><a href="/integrations/hermes">CLI: Hermes</a></h2>'
        '<p class="muted">A config.yaml custom provider, a shell hook and the proxy for Hermes.</p></div>'
    )
    return html_response(page("Integrations", body))


HOOK_LIMIT_NOTE = "Hooks cannot switch the model; routing needs the proxy."
LABELS = ("CLI", "Desktop", "not verified on Desktop")
UNVERIFIED = LABELS[2]
CODEX_CONFIG_FILE = "config.toml"
HERMES_CONFIG_FILE = "config.yaml"


def codex_provider_snippet() -> str:
    """config.toml block pointing Codex at the local proxy; the key is named, never valued."""
    return (
        'model_provider = "jevroute"\n\n'
        "[model_providers.jevroute]\n"
        'name = "Jev route proxy"\n'
        f'base_url = "{PROXY_URL}"\n'
        'env_key = "OPENROUTER_API_KEY"\n'
    )


def codex_hook_snippet() -> str:
    return (
        "[[hooks.UserPromptSubmit]]\n\n"
        "[[hooks.UserPromptSubmit.hooks]]\n"
        'type = "command"\n'
        f'command = "python3 {HOOK_FILE}"\n'
    )


def hermes_provider_snippet() -> str:
    return (
        "custom_providers:\n"
        "  - name: jevroute\n"
        f"    base_url: {PROXY_URL}\n"
        "    key_env: OPENROUTER_API_KEY\n"
    )


def hermes_hook_snippet() -> str:
    return (
        "hooks:\n"
        "  pre_llm_call:\n"
        f'    - command: "python3 {HOOK_FILE}"\n'
    )


def _snippet(label: str, title: str, text: str) -> str:
    if label not in LABELS:
        raise ValueError(f"unknown snippet label: {label}")
    return f'<div class="card"><h2>{h(label)}: {h(title)}</h2><pre>{h(text)}</pre></div>'


def _tool_page(heading: str, intro: str, snippets) -> Response:
    """A text-only setup page. `snippets` are (label, title, text) built from the saved routes."""
    routes = _list_routes()
    if routes:
        content = "".join(_snippet(label, title, text) for label, title, text in snippets(routes))
    else:
        content = '<p class="muted">Routes are needed first: <a href="/routes">add routes</a>.</p>'
    body = (
        f"<h1>{h(heading)}</h1>"
        f'<p class="muted">{h(intro)} Set OPENROUTER_API_KEY in your own environment; '
        "it is never part of these snippets. This app only shows the text; it does not run or install it.</p>"
        f'<p class="muted">{h(HOOK_LIMIT_NOTE)}</p>'
        f"{content}"
    )
    return html_response(page(heading, body))


@route("GET", "/integrations/claude-code")
def integrations_claude_code(req: Request) -> Response:
    return _tool_page(
        "Claude Code",
        f"Run {PROXY_FILE} yourself and merge the settings into your settings.json.",
        lambda routes: (
            ("CLI", "settings.json env", settings_env_snippet()),
            ("CLI", f"optional settings.json hook for {HOOK_FILE}", settings_hook_snippet()),
            ("CLI", HOOK_FILE, generate_hook(routes)),
            ("CLI", PROXY_FILE, generate_proxy(routes, load_thresholds())),
        ),
    )


@route("GET", "/integrations/codex")
def integrations_codex(req: Request) -> Response:
    return _tool_page(
        "Codex",
        f"Run {PROXY_FILE} yourself and merge the blocks into your {CODEX_CONFIG_FILE}.",
        lambda routes: (
            (UNVERIFIED, f"{CODEX_CONFIG_FILE} provider", codex_provider_snippet()),
            (UNVERIFIED, f"{CODEX_CONFIG_FILE} hook for {HOOK_FILE}", codex_hook_snippet()),
            ("CLI", HOOK_FILE, generate_hook(routes)),
            ("CLI", PROXY_FILE, generate_proxy(routes, load_thresholds())),
        ),
    )


@route("GET", "/integrations/hermes")
def integrations_hermes(req: Request) -> Response:
    return _tool_page(
        "Hermes",
        f"Run {PROXY_FILE} yourself and merge the entries into your {HERMES_CONFIG_FILE}.",
        lambda routes: (
            (UNVERIFIED, f"{HERMES_CONFIG_FILE} custom provider", hermes_provider_snippet()),
            (UNVERIFIED, f"{HERMES_CONFIG_FILE} shell hook for {HOOK_FILE}", hermes_hook_snippet()),
            ("CLI", HOOK_FILE, generate_hook(routes)),
            ("CLI", PROXY_FILE, generate_proxy(routes, load_thresholds())),
        ),
    )


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
