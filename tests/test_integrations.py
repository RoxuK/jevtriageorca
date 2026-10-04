import ast
import html
import re
import sys

from tests.support import AppTestCase

CHEAP = {"name": "cheap", "criteria": "small edits, renames, typos",
         "target_model": "anthropic/claude-haiku-4.5", "price_cents": "100"}
STRONG = {"name": "strong", "criteria": "architecture, multi-file refactors, hard debugging",
          "target_model": "anthropic/claude-opus-4.5", "price_cents": "1500"}
HOSTILE = {"name": "<script>alert(1)</script>", "criteria": '"><img src=x onerror=alert(2)>',
           "target_model": "m/host", "price_cents": "5"}
NASTY = {"name": 'quo"te\'s', "criteria": "back\\slash\nnew line\r\nand '''triple\"\"\"",
         "target_model": "m/nasty", "price_cents": "7"}


class IntegrationsTest(AppTestCase):
    def setUp(self) -> None:
        self.get("/routes")  # make sure migrations have run
        self.sql_clear()

    def sql_clear(self) -> None:
        import sqlite3
        import os
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            with conn:
                conn.execute("DELETE FROM routes")
                conn.execute("UPDATE thresholds SET confidence = 500, share = 200")
        finally:
            conn.close()

    def add(self, *routes: dict) -> None:
        for fields in routes:
            self.assertEqual(self.post_form("/routes", fields)[0], 303)

    def proxy_text(self) -> str:
        status, _, body = self.get("/integrations/proxy")
        self.assertEqual(status, 200)
        match = re.search(r"<pre>(.*?)</pre>", body, re.S)
        self.assertIsNotNone(match)
        return html.unescape(match.group(1))

    def test_index_links_to_proxy_and_nav_lists_integrations(self):
        status, _, body = self.get("/integrations")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/integrations">Integrations</a>', body)
        self.assertIn('href="/integrations/proxy"', body)

    def test_proxy_page_names_file_labels_cli_and_says_not_run(self):
        self.add(CHEAP)
        status, _, body = self.get("/integrations/proxy")
        self.assertEqual(status, 200)
        self.assertIn("route_proxy.py", body)
        self.assertIn("CLI", body)
        self.assertIn("does not run or install it", body)

    def test_text_contains_routes_and_jev_details(self):
        self.add(CHEAP, STRONG)
        text = self.proxy_text()
        for needle in ("anthropic/claude-haiku-4.5", "anthropic/claude-opus-4.5", CHEAP["criteria"],
                       STRONG["criteria"], "typesafe/jev-1.13", "https://openrouter.ai/api/alpha/decisions",
                       "OPENROUTER_API_KEY", "8787"):
            self.assertIn(needle, text)

    def test_proxy_does_not_forward_accept_encoding(self):
        self.add(CHEAP)
        self.assertIn('("host", "content-length", "accept-encoding")', self.proxy_text())

    def test_proxy_logs_jev_failure_to_stderr(self):
        self.add(CHEAP)
        text = self.proxy_text()
        self.assertIn("file=sys.stderr", text)
        self.assertIn("import sys", text)

    def test_text_never_contains_a_key_value(self):
        self.add(CHEAP)
        self.assertNotRegex(self.proxy_text(), r"sk-or-")

    def test_editing_a_route_updates_the_page(self):
        self.add(CHEAP)
        self.sql_edit_target()
        _, _, body = self.get("/integrations/proxy")
        self.assertIn("m/new", body)
        self.assertNotIn("anthropic/claude-haiku-4.5", body)

    def sql_edit_target(self) -> None:
        _, _, body = self.get("/routes")
        route_id = re.search(r"/routes/(\d+)/edit", body).group(1)
        edited = dict(CHEAP, target_model="m/new")
        self.assertEqual(self.post_form(f"/routes/{route_id}/edit", edited)[0], 303)

    def test_text_reflects_saved_thresholds(self):
        self.add(CHEAP)
        text = self.proxy_text()
        self.assertIn("CONFIDENCE_THRESHOLD = 500", text)
        self.assertIn("SHARE_THRESHOLD = 200", text)
        self.assertEqual(
            self.post_form("/thresholds", {"confidence_threshold": "0.3", "share_threshold": "0.2"})[0], 303)
        self.assertIn("CONFIDENCE_THRESHOLD = 300", self.proxy_text())

    def test_text_compiles_with_hostile_and_awkward_values(self):
        self.add(CHEAP, HOSTILE, NASTY)
        text = self.proxy_text()
        compile(text, "route_proxy.py", "exec")  # compiled, never executed
        for value in (HOSTILE["name"], HOSTILE["criteria"], NASTY["name"], NASTY["criteria"]):
            self.assertIn(repr(value), text)

    def test_page_has_no_literal_markup_from_values(self):
        self.add(HOSTILE)
        _, _, body = self.get("/integrations/proxy")
        self.assertNotIn("<script>", body)
        self.assertNotIn("<img", body)

    def test_every_import_is_standard_library(self):
        self.add(CHEAP, HOSTILE)
        modules = set()
        for node in ast.walk(ast.parse(self.proxy_text())):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module.split(".")[0])
        self.assertTrue(modules)
        self.assertLessEqual(modules, set(sys.stdlib_module_names))

    def test_no_routes_says_routes_are_needed(self):
        status, _, body = self.get("/integrations/proxy")
        self.assertEqual(status, 200)
        self.assertIn("Routes are needed", body)
        self.assertIn('href="/routes"', body)
        self.assertNotIn("<pre>", body)

    def page(self) -> str:
        status, _, body = self.get("/integrations/claude-code")
        self.assertEqual(status, 200)
        return body

    def snippets(self) -> list:
        return [html.unescape(m) for m in re.findall(r"<pre>(.*?)</pre>", self.page(), re.S)]

    def test_index_links_to_claude_code(self):
        self.assertIn('href="/integrations/claude-code"', self.get("/integrations")[2])

    def test_states_hooks_cannot_switch_the_model(self):
        sentence = "Hooks cannot switch the model; routing needs the proxy."
        self.assertIn(sentence, self.page())
        self.add(CHEAP)
        self.assertIn(sentence, self.page())

    def test_without_routes_asks_for_routes(self):
        body = self.page()
        self.assertIn('href="/routes"', body)
        self.assertNotIn("<pre>", body)

    def test_four_labelled_snippets_with_cli_labels(self):
        self.add(CHEAP)
        body = self.page()
        self.assertEqual(len(self.snippets()), 4)
        self.assertEqual(body.count("<h2>CLI: "), 4)
        self.assertIn("does not run or install it", body)

    def test_env_and_hook_settings_are_valid_json(self):
        import json
        self.add(CHEAP)
        env, hook, _, _ = self.snippets()
        self.assertEqual(json.loads(env)["env"]["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787")
        command = json.loads(hook)["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn("route_hook.py", command)

    def test_generated_scripts_parse_and_embed_routes(self):
        self.add(CHEAP, NASTY)
        _, _, hook, proxy = self.snippets()
        for text in (hook, proxy):
            tree = ast.parse(text)
            routes = next(
                ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and n.targets[0].id == "ROUTES"
            )
            self.assertEqual([r[1] for r in routes], ["cheap", NASTY["name"]])
            self.assertEqual(routes[1][2], NASTY["criteria"])

    def test_hostile_route_text_is_escaped(self):
        self.add(HOSTILE)
        body = self.page()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img", body)

    def test_api_key_value_never_appears(self):
        import os
        os.environ["OPENROUTER_API_KEY"] = "sk-secret-value"
        try:
            self.add(CHEAP)
            self.assertNotIn("sk-secret-value", self.page())
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    def run_hook(self, jev_url: str, prompt: str = "rename a variable"):
        import json
        import os
        import subprocess
        import tempfile
        from app.features.decider import JEV_URL
        self.add(CHEAP, STRONG)
        hook = self.snippets()[2].replace(repr(JEV_URL), repr(jev_url))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "route_hook.py")
            with open(path, "w") as handle:
                handle.write(hook)
            return subprocess.run(
                [sys.executable, path], input=json.dumps({"prompt": prompt}), capture_output=True,
                text=True, timeout=30, env={**os.environ, "OPENROUTER_API_KEY": "x"},
            )

    def test_hook_prints_claude_code_context_for_jev_choice(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        seen = []

        class Stub(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                reply = json.dumps({"answers": {"route": {"choice": "route_2"}}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = self.run_hook(f"http://127.0.0.1:{server.server_port}/", "redesign the module layout")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn("strong", output["additionalContext"])
        self.assertIn("anthropic/claude-opus-4.5", output["additionalContext"])
        question = seen[0]["questions"]["route"]
        self.assertEqual(seen[0]["state"], {"task": "redesign the module layout"})
        self.assertEqual(question["type"], "choice")
        self.assertEqual(list(question["criteria"]), ["route_1", "route_2"])

    def test_hook_fails_soft_when_jev_is_unreachable(self):
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        result = self.run_hook(f"http://127.0.0.1:{port}/")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("route_hook: Jev failed", result.stderr)
