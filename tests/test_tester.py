import os
import re
import sqlite3

from tests.support import AppTestCase

CHEAP = {"name": "cheap", "criteria": "small edits, renames, typos",
         "target_model": "anthropic/claude-haiku-4.5", "price_cents": "100"}
STRONG = {"name": "strong", "criteria": "architecture, multi-file refactors, hard debugging",
          "target_model": "anthropic/claude-opus-4.5", "price_cents": "1500"}
TASK = "fix the typo in the README title"


class TesterTest(AppTestCase):
    def setUp(self) -> None:
        self.get("/tester")  # make sure migrations have run
        self.sql("DELETE FROM decision_probabilities")
        self.sql("DELETE FROM decisions")
        self.sql("DELETE FROM routes")

    def sql(self, statement: str, args: tuple = ()) -> list:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            with conn:
                return conn.execute(statement, args).fetchall()
        finally:
            conn.close()

    def add_routes(self, *routes: dict) -> None:
        for r in routes:
            self.post_form("/routes", r)

    def decide(self, task: str = TASK) -> str:
        status, headers, _ = self.post_form("/tester", {"task": task})
        self.assertEqual(status, 303)
        return headers["Location"]

    def test_form_page_nav_textarea_and_button(self):
        self.add_routes(CHEAP, STRONG)
        status, _, body = self.get("/tester")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/tester">Tester</a>', body)
        self.assertIn('<textarea name="task"', body)
        self.assertIn('<button type="submit">', body)

    def test_post_redirects_to_decision(self):
        self.add_routes(CHEAP, STRONG)
        self.assertRegex(self.decide(), r"^/decisions/\d+$")

    def test_decision_page_content(self):
        self.add_routes(CHEAP, STRONG)
        status, _, body = self.get(self.decide())
        self.assertEqual(status, 200)
        self.assertIn(TASK, body)
        self.assertRegex(body, r"Chosen route: <strong>(cheap|strong)</strong>")
        self.assertRegex(body, r"<td>cheap</td><td>\d\.\d{3}</td>")
        self.assertRegex(body, r"<td>strong</td><td>\d\.\d{3}</td>")
        confidence = float(re.search(r"Confidence: (\d\.\d{3})", body).group(1))
        self.assertTrue(0.0 <= confidence <= 1.0)
        self.assertIn("Decider: offline", body)

    def test_stored_row_holds_integer_thousandths(self):
        self.add_routes(CHEAP, STRONG)
        self.decide()
        (confidence, decider), = self.sql("SELECT confidence, decider FROM decisions")
        self.assertIsInstance(confidence, int)
        self.assertEqual(decider, "offline")
        probabilities = self.sql("SELECT typeof(probability), probability FROM decision_probabilities")
        self.assertEqual(len(probabilities), 2)
        self.assertTrue(all(t == "integer" for t, _ in probabilities))
        self.assertEqual(sum(p for _, p in probabilities), 1000)

    def test_empty_task_is_rejected(self):
        self.add_routes(CHEAP, STRONG)
        status, _, body = self.post_form("/tester", {"task": ""})
        self.assertEqual(status, 400)
        self.assertIn('class="error"', body)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM decisions"), [(0,)])

    def test_whitespace_task_is_rejected(self):
        self.add_routes(CHEAP, STRONG)
        status, _, body = self.post_form("/tester", {"task": "  \t "})
        self.assertEqual(status, 400)
        self.assertIn('class="error"', body)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM decisions"), [(0,)])

    def test_missing_task_field_is_rejected(self):
        self.add_routes(CHEAP, STRONG)
        status, _, _ = self.post_form("/tester", {})
        self.assertEqual(status, 400)

    def test_invalid_task_is_kept_in_the_form(self):
        self.add_routes(CHEAP, STRONG)
        _, _, body = self.post_form("/tester", {"task": ""})
        self.assertIn('<textarea name="task"', body)

    def check_too_few_routes(self):
        status, _, body = self.get("/tester")
        self.assertEqual(status, 200)
        self.assertIn("at least two routes", body)
        self.assertIn('href="/routes"', body)
        status, _, body = self.post_form("/tester", {"task": TASK})
        self.assertEqual(status, 400)
        self.assertIn('class="error"', body)
        self.assertIn('href="/routes"', body)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM decisions"), [(0,)])

    def test_zero_routes(self):
        self.check_too_few_routes()

    def test_one_route(self):
        self.add_routes(CHEAP)
        self.check_too_few_routes()

    def test_user_values_are_escaped(self):
        self.add_routes(CHEAP, {**STRONG, "name": "<script>alert(1)</script>"})
        _, _, body = self.get(self.decide("<b>fix</b> the login bug"))
        self.assertIn("&lt;b&gt;fix&lt;/b&gt; the login bug", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        for literal in ("<b>", "<script>", "<img"):
            self.assertNotIn(literal, body)

    def test_task_is_escaped_when_form_is_re_rendered(self):
        self.add_routes(CHEAP)
        _, _, body = self.post_form("/tester", {"task": "<img src=x>"})
        self.assertNotIn("<img", body)

    def test_decision_survives_route_deletion(self):
        self.add_routes(CHEAP, STRONG)
        location = self.decide()
        _, _, before = self.get(location)
        for (route_id,) in self.sql("SELECT id FROM routes"):
            status, _, _ = self.post_form(f"/routes/{route_id}/delete", {})
            self.assertEqual(status, 303)
        status, _, after = self.get(location)
        self.assertEqual(status, 200)
        self.assertEqual(before, after)
        self.assertIn("<td>cheap</td>", after)
        self.assertIn("<td>strong</td>", after)

    def test_decision_keeps_name_after_route_edit(self):
        self.add_routes(CHEAP, STRONG)
        location = self.decide()
        (route_id,), = self.sql("SELECT id FROM routes WHERE name = 'cheap'")
        self.post_form(f"/routes/{route_id}/edit", {**CHEAP, "name": "renamed"})
        _, _, body = self.get(location)
        self.assertIn("<td>cheap</td>", body)
        self.assertNotIn("renamed", body)

    def test_unknown_decision_is_404(self):
        self.assertEqual(self.get("/decisions/999999")[0], 404)

    def test_non_numeric_decision_is_404(self):
        self.assertEqual(self.get("/decisions/abc")[0], 404)

    def test_oversized_decision_id_is_404(self):
        self.assertEqual(self.get("/decisions/" + "9" * 40)[0], 404)

    def test_decision_id_beyond_int_digit_limit_is_404(self):
        self.assertEqual(self.get("/decisions/" + "9" * 5000)[0], 404)
