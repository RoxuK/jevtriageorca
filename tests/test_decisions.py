import os
import re
import sqlite3

from app.features.decisions import _band
from tests.support import AppTestCase


class DecisionLogTest(AppTestCase):
    def setUp(self) -> None:
        self.get("/decisions")  # make sure migrations have run
        self.sql("DELETE FROM decision_labels")
        self.sql("DELETE FROM routes")
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

    def labels(self, decision_id: int) -> list:
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            return conn.execute(
                "SELECT verdict, correct_route_id FROM decision_labels WHERE decision_id = ?", (decision_id,)
            ).fetchall()
        finally:
            conn.close()

    def add_route(self, name: str) -> int:
        self.post_form("/routes", {"name": name, "criteria": "x", "target_model": "m", "price_cents": "1"})
        conn = sqlite3.connect(os.environ["APP_DATABASE"])
        try:
            return conn.execute("SELECT id FROM routes WHERE name = ?", (name,)).fetchone()[0]
        finally:
            conn.close()

    def test_row_renders_label_form(self):
        did = self.add()
        self.add_route("pricey")
        _, _, body = self.get("/decisions")
        self.assertIn(f'<form method="post" action="/decisions/{did}/label">', body)
        self.assertIn('<select name="verdict"><option value="right">right</option>', body)
        self.assertIn('<option value="wrong">wrong</option>', body)
        self.assertIn('<select name="correct_route_id">', body)
        self.assertIn(">pricey</option>", body)
        self.assertIn("Unlabelled", body)

    def test_right_redirects_and_row_shows_right(self):
        did = self.add()
        status, headers, _ = self.post_form(f"/decisions/{did}/label", {"verdict": "right"})
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/decisions")
        _, _, body = self.get("/decisions")
        self.assertIn("Labelled right", body)

    def test_wrong_with_route_shows_correct_route(self):
        did = self.add()
        rid = self.add_route("pricey")
        status, _, _ = self.post_form(f"/decisions/{did}/label", {"verdict": "wrong", "correct_route_id": str(rid)})
        self.assertEqual(status, 303)
        _, _, body = self.get("/decisions")
        self.assertIn("Labelled wrong: should be pricey", body)

    def test_relabel_replaces_single_label(self):
        did = self.add()
        rid = self.add_route("pricey")
        self.post_form(f"/decisions/{did}/label", {"verdict": "wrong", "correct_route_id": str(rid)})
        self.post_form(f"/decisions/{did}/label", {"verdict": "right"})
        self.assertEqual([tuple(r) for r in self.labels(did)], [("right", None)])
        _, _, body = self.get("/decisions")
        self.assertIn("Labelled right", body)
        self.assertNotIn("Labelled wrong", body)

    def assert_rejected(self, did: int, data: dict) -> None:
        status, _, body = self.post_form(f"/decisions/{did}/label", data)
        self.assertEqual(status, 400)
        self.assertIn('class="error"', body)
        self.assertEqual(self.labels(did), [])

    def test_wrong_without_route_is_400(self):
        self.assert_rejected(self.add(), {"verdict": "wrong"})

    def test_wrong_with_blank_route_is_400(self):
        self.assert_rejected(self.add(), {"verdict": "wrong", "correct_route_id": ""})

    def test_wrong_with_non_numeric_route_is_400(self):
        self.assert_rejected(self.add(), {"verdict": "wrong", "correct_route_id": "abc"})

    def test_wrong_with_unknown_route_is_400(self):
        self.assert_rejected(self.add(), {"verdict": "wrong", "correct_route_id": "999999"})

    def test_missing_verdict_is_400(self):
        self.assert_rejected(self.add(), {})

    def test_invalid_verdict_is_400(self):
        self.assert_rejected(self.add(), {"verdict": "maybe"})

    def test_non_numeric_decision_id_is_404(self):
        status, _, _ = self.post_form("/decisions/abc/label", {"verdict": "right"})
        self.assertEqual(status, 404)

    def test_unknown_decision_id_is_404_and_stores_nothing(self):
        status, _, _ = self.post_form("/decisions/999999/label", {"verdict": "right"})
        self.assertEqual(status, 404)
        self.assertEqual(self.labels(999999), [])

    def test_oversized_decision_id_is_404(self):
        status, _, _ = self.post_form("/decisions/" + "9" * 40 + "/label", {"verdict": "right"})
        self.assertEqual(status, 404)

    def test_labelling_newest_leaves_others_unlabelled(self):
        first, second, third = self.add(task="a"), self.add(task="b"), self.add(task="c")
        self.post_form(f"/decisions/{third}/label", {"verdict": "right"})
        self.assertEqual(len(self.labels(third)), 1)
        self.assertEqual(self.labels(first), [])
        self.assertEqual(self.labels(second), [])
        _, _, body = self.get("/decisions")
        self.assertEqual(body.count("Labelled right"), 1)
        self.assertEqual(body.count("Unlabelled"), 2)

    def summary(self) -> str:
        _, _, body = self.get("/decisions")
        return re.search(r'<div class="summary">.*?</ul></div>', body, re.S).group(0)

    def label(self, did: int, verdict: str) -> None:
        extra = {"correct_route_id": str(self.add_route("pricey"))} if verdict == "wrong" else {}
        self.post_form(f"/decisions/{did}/label", {"verdict": verdict, **extra})

    def labelled(self, verdicts: list, confidence: int = 870) -> list:
        ids = [self.add(confidence=confidence) for _ in verdicts]
        for did, verdict in zip(ids, verdicts):
            self.label(did, verdict)
        return ids

    def test_no_labels_shows_zero_and_no_percentage(self):
        status, _, body = self.get("/decisions")
        self.assertEqual(status, 200)
        self.assertIn("Accuracy: 0 labelled</p>", body)
        self.assertNotIn("%", self.summary())

    def test_no_labels_with_unlabelled_decisions(self):
        self.add()
        self.assertIn("Accuracy: 0 labelled</p>", self.summary())
        self.assertNotIn("%", self.summary())

    def test_two_labelled_of_three_is_fifty_percent(self):
        self.add()
        self.labelled(["right", "wrong"])
        self.assertIn("Accuracy: 2 labelled, 50%</p>", self.summary())

    def test_four_labelled_then_relabel_to_seventy_five(self):
        ids = self.labelled(["right", "right", "wrong", "wrong"])
        self.assertIn("Accuracy: 4 labelled, 50%</p>", self.summary())
        self.label(ids[2], "right")
        self.assertIn("Accuracy: 4 labelled, 75%</p>", self.summary())

    def test_bands_listed_and_counts_sum_to_total(self):
        self.labelled(["right"], confidence=100)
        self.labelled(["wrong", "right"], confidence=650)
        self.labelled(["right"], confidence=950)
        summary = self.summary()
        self.assertIn("<li>below 0.5: 1 labelled, 100%</li>", summary)
        self.assertIn("<li>0.5 to 0.8: 2 labelled, 50%</li>", summary)
        self.assertIn("<li>above 0.8: 1 labelled, 100%</li>", summary)
        self.assertIn("Accuracy: 4 labelled, 75%</p>", summary)

    def test_band_helper_edges(self):
        self.assertEqual(_band(499), "below 0.5")
        self.assertEqual(_band(500), "0.5 to 0.8")
        self.assertEqual(_band(800), "0.5 to 0.8")
        self.assertEqual(_band(801), "above 0.8")

    def test_empty_band_shows_zero_and_no_percentage(self):
        self.labelled(["right"], confidence=900)
        summary = self.summary()
        self.assertIn("<li>below 0.5: 0 labelled</li>", summary)
        self.assertIn("<li>0.5 to 0.8: 0 labelled</li>", summary)

    def test_one_of_three_is_33_percent(self):
        self.labelled(["right", "wrong", "wrong"])
        self.assertIn("Accuracy: 3 labelled, 33%</p>", self.summary())

    def test_two_of_three_is_67_percent(self):
        self.labelled(["right", "right", "wrong"])
        self.assertIn("Accuracy: 3 labelled, 67%</p>", self.summary())

    def test_half_rounds_up(self):
        self.labelled(["right"] + ["wrong"] * 7)
        self.assertIn("Accuracy: 8 labelled, 13%</p>", self.summary())

    def test_bad_label_posts_leave_summary_unchanged(self):
        self.labelled(["right", "wrong"])
        before = self.summary()
        self.post_form("/decisions/abc/label", {"verdict": "right"})
        self.post_form("/decisions/999999/label", {"verdict": "right"})
        self.assertEqual(self.summary(), before)
