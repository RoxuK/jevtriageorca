import os
import re
import sqlite3

from tests.support import AppTestCase


class DecisionLogTest(AppTestCase):
    def setUp(self) -> None:
        self.get("/decisions")  # make sure migrations have run
        self.sql("DELETE FROM decision_probabilities")
        self.sql("DELETE FROM decisions")

    def sql(self, statement: str, args: tuple = ()) -> None:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            with conn:
                conn.execute(statement, args)
        finally:
            conn.close()

    def add(self, task: str = "a task", route: str = "cheap", confidence: int = 870,
            decider: str = "offline", created_at: str = "2026-01-02T03:04:05Z", escalated: int = 0) -> int:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            with conn:
                return conn.execute(
                    "INSERT INTO decisions (task, chosen_route_id, chosen_route_name, confidence, decider, "
                    "created_at, escalated) VALUES (?, 1, ?, ?, ?, ?, ?)",
                    (task, route, confidence, decider, created_at, escalated),
                ).lastrowid
        finally:
            conn.close()

    def test_nav_has_log_entry(self):
        _, _, body = self.get("/decisions")
        self.assertIn('<a href="/decisions">Log</a>', body)

    def test_empty_state(self):
        status, _, body = self.get("/decisions")
        self.assertEqual(status, 200)
        self.assertIn("No decisions yet", body)
        self.assertNotIn("<table>", body)

    def test_row_shows_every_column(self):
        did = self.add(task="rename a var", route="cheap", confidence=870, decider="offline",
                       created_at="2026-01-02T03:04:05Z")
        _, _, body = self.get("/decisions")
        self.assertIn("<td>2026-01-02T03:04:05Z</td><td>rename a var</td><td>cheap</td>"
                      "<td>0.870</td><td>offline</td><td>no</td>", body)
        self.assertIn(f'<a href="/decisions/{did}">', body)

    def test_escalated_shows_yes(self):
        self.add(escalated=1)
        _, _, body = self.get("/decisions")
        self.assertIn("<td>yes</td>", body)

    def test_newest_first_even_with_equal_timestamps(self):
        self.add(task="first")
        self.add(task="second")
        self.add(task="third")
        _, _, body = self.get("/decisions")
        self.assertEqual(re.findall(r"<td>(first|second|third)</td>", body), ["third", "second", "first"])

    def test_deleted_route_keeps_its_name(self):
        self.post_form("/routes", {"name": "gone", "criteria": "x", "target_model": "m", "price_cents": "1"})
        self.add(route="gone")
        self.sql("DELETE FROM routes")
        _, _, body = self.get("/decisions")
        self.assertIn("<td>gone</td>", body)

    def test_task_and_route_name_are_escaped(self):
        self.add(task="<script>alert(1)</script>", route="<img src=x>")
        _, _, body = self.get("/decisions")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertNotIn("<img src=x>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img src=x&gt;", body)

    def test_post_is_not_allowed(self):
        status, _, _ = self.post_form("/decisions", {})
        self.assertIn(status, (404, 405))
