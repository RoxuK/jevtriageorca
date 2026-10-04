import sqlite3
import os
import unittest

from tests.support import AppTestCase

CHEAP = {"name": "cheap", "criteria": "small edits, renames, typos",
         "target_model": "anthropic/claude-haiku-4.5", "price_cents": "100"}
STRONG = {"name": "strong", "criteria": "architecture, multi-file refactors, hard debugging",
          "target_model": "anthropic/claude-opus-4.5", "price_cents": "1500"}


class RoutesTest(AppTestCase):
    def setUp(self) -> None:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            with conn:
                conn.execute("DELETE FROM routes")
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    def count(self) -> int:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            return conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        finally:
            conn.close()

    def test_page_ok_and_linked_in_nav(self):
        status, _, body = self.get("/routes")
        self.assertEqual(status, 200)
        self.assertIn('<a href="/routes">Routes</a>', body)

    def test_form_inputs_and_labels(self):
        _, _, body = self.get("/routes")
        for name in ("name", "criteria", "target_model", "price_cents"):
            self.assertIn(f'name="{name}"', body)
        self.assertIn("cents per million tokens", body)
        self.assertEqual(body.count("<label>"), 4)

    def test_empty_state(self):
        status, _, body = self.get("/routes")
        self.assertEqual(status, 200)
        self.assertIn("No routes exist yet", body)

    def test_add_route_redirects_and_lists_values(self):
        status, headers, _ = self.post_form("/routes", CHEAP)
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/routes")
        _, _, body = self.get("/routes")
        for value in CHEAP.values():
            self.assertIn(value, body)
        self.assertNotIn("No routes exist yet", body)

    def test_routes_listed_in_creation_order(self):
        self.post_form("/routes", CHEAP)
        self.post_form("/routes", STRONG)
        _, _, body = self.get("/routes")
        self.assertLess(body.index("cheap"), body.index("strong"))
        self.assertIn(STRONG["target_model"], body)

    def test_empty_text_fields_rejected(self):
        for key, label in (("name", "Name"), ("criteria", "Criteria"), ("target_model", "Target model")):
            with self.subTest(field=key):
                fields = dict(CHEAP, **{key: ""})
                status, _, body = self.post_form("/routes", fields)
                self.assertEqual(status, 400)
                self.assertIn(f'class="error" role="alert">{label} is required.', body)
                for other, value in fields.items():
                    if other != key:
                        self.assertIn(f'name="{other}" value="{value}"', body)
                self.assertEqual(self.count(), 0)

    def test_invalid_prices_rejected(self):
        for price in ("abc", "1.5", "-1", "", "²"):
            with self.subTest(price=price):
                status, _, body = self.post_form("/routes", dict(CHEAP, price_cents=price))
                self.assertEqual(status, 400)
                self.assertIn('class="error"', body)
                self.assertEqual(self.count(), 0)

    def test_zero_and_hundred_prices_accepted(self):
        for price in ("0", "100"):
            with self.subTest(price=price):
                status, _, _ = self.post_form("/routes", dict(CHEAP, price_cents=price))
                self.assertEqual(status, 303)
        self.assertEqual(self.count(), 2)

    def test_missing_fields_rejected_not_500(self):
        status, _, _ = self.post_form("/routes", {})
        self.assertEqual(status, 400)

    def test_user_values_are_escaped(self):
        fields = dict(CHEAP, name="<script>alert(1)</script>", criteria='"><img src=x onerror=alert(2)>')
        self.assertEqual(self.post_form("/routes", fields)[0], 303)
        _, _, body = self.get("/routes")
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>", body)
        self.assertNotIn("<img", body)

    def test_escaped_in_error_rerender(self):
        fields = dict(CHEAP, name="<script>x</script>", price_cents="abc")
        status, _, body = self.post_form("/routes", fields)
        self.assertEqual(status, 400)
        self.assertNotIn("<script>", body)


if __name__ == "__main__":
    unittest.main()
