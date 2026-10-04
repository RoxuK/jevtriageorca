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

    def test_oversized_prices_rejected_not_500(self):
        for price in (str(2**63), "9" * 30, "9" * 5000):
            with self.subTest(digits=len(price)):
                status, _, body = self.post_form("/routes", dict(CHEAP, price_cents=price))
                self.assertEqual(status, 400)
                self.assertIn('class="error"', body)

    def test_largest_price_accepted(self):
        status, _, _ = self.post_form("/routes", dict(CHEAP, price_cents=str(2**63 - 1)))
        self.assertEqual(status, 303)

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

    def add(self, fields=CHEAP) -> int:
        self.post_form("/routes", fields)
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            return conn.execute("SELECT MAX(id) FROM routes").fetchone()[0]
        finally:
            conn.close()

    def test_rows_have_edit_link_and_delete_button(self):
        rid = self.add()
        _, _, body = self.get("/routes")
        self.assertIn(f'<a href="/routes/{rid}/edit">Edit</a>', body)
        self.assertIn(f'<form method="post" action="/routes/{rid}/delete">', body)

    def test_edit_form_prefilled(self):
        rid = self.add()
        status, _, body = self.get(f"/routes/{rid}/edit")
        self.assertEqual(status, 200)
        for key, value in CHEAP.items():
            self.assertIn(f'name="{key}" value="{value}"', body)
        self.assertIn(f'action="/routes/{rid}/edit"', body)

    def test_edit_form_escapes_hostile_values(self):
        rid = self.add(dict(CHEAP, name="<script>alert(1)</script>"))
        _, _, body = self.get(f"/routes/{rid}/edit")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_edit_updates_route_keeping_id_and_others(self):
        rid = self.add()
        other = self.add(STRONG)
        status, headers, _ = self.post_form(f"/routes/{rid}/edit", dict(STRONG, name="renamed", price_cents="7"))
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/routes")
        _, _, body = self.get(f"/routes/{rid}/edit")
        self.assertIn('name="name" value="renamed"', body)
        self.assertIn('name="price_cents" value="7"', body)
        _, _, body = self.get(f"/routes/{other}/edit")
        self.assertIn('name="name" value="strong"', body)
        self.assertIn('name="price_cents" value="1500"', body)

    def test_edit_invalid_rejected_and_route_unchanged(self):
        rid = self.add()
        for key, bad in (("name", ""), ("criteria", ""), ("target_model", ""), ("price_cents", "abc")):
            with self.subTest(field=key):
                status, _, body = self.post_form(f"/routes/{rid}/edit", dict(STRONG, **{key: bad}))
                self.assertEqual(status, 400)
                self.assertIn('class="error" role="alert"', body)
                self.assertIn(f'action="/routes/{rid}/edit"', body)
                _, _, body = self.get(f"/routes/{rid}/edit")
                self.assertIn('name="name" value="cheap"', body)
                self.assertIn('name="price_cents" value="100"', body)

    def test_edit_error_rerenders_submitted_values(self):
        rid = self.add()
        _, _, body = self.post_form(f"/routes/{rid}/edit", dict(STRONG, price_cents="abc"))
        self.assertIn('name="price_cents" value="abc"', body)
        self.assertIn('name="name" value="strong"', body)

    def test_edit_error_rerender_escaped(self):
        rid = self.add()
        status, _, body = self.post_form(f"/routes/{rid}/edit", dict(CHEAP, name="<script>x</script>", price_cents="abc"))
        self.assertEqual(status, 400)
        self.assertNotIn("<script>", body)

    def test_edit_missing_fields_rejected_not_500(self):
        rid = self.add()
        self.assertEqual(self.post_form(f"/routes/{rid}/edit", {})[0], 400)

    def test_delete_removes_only_that_route(self):
        rid = self.add()
        self.add(STRONG)
        status, headers, _ = self.post_form(f"/routes/{rid}/delete", {})
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/routes")
        _, _, body = self.get("/routes")
        self.assertNotIn(CHEAP["target_model"], body)
        self.assertIn(STRONG["target_model"], body)
        self.assertEqual(self.count(), 1)

    def test_unknown_id_is_404(self):
        self.assertEqual(self.get("/routes/999999/edit")[0], 404)
        self.assertEqual(self.post_form("/routes/999999/edit", CHEAP)[0], 404)
        self.assertEqual(self.post_form("/routes/999999/delete", {})[0], 404)

    def test_non_numeric_id_is_404(self):
        for bad in ("abc", "1.5", "-1", "9" * 5000):
            with self.subTest(id=bad[:10]):
                self.assertEqual(self.get(f"/routes/{bad}/edit")[0], 404)
                self.assertEqual(self.post_form(f"/routes/{bad}/edit", CHEAP)[0], 404)
                self.assertEqual(self.post_form(f"/routes/{bad}/delete", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
