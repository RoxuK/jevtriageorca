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
