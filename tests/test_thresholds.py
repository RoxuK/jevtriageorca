import os
import re
import sqlite3
import unittest

from app.features.decider import Decision
from app.features.thresholds import Thresholds, apply_escalation
from tests.support import AppTestCase

CHEAP = {"name": "cheap", "criteria": "small edits, renames, typos",
         "target_model": "anthropic/claude-haiku-4.5", "price_cents": "100"}
STRONG = {"name": "strong", "criteria": "architecture, multi-file refactors, hard debugging",
          "target_model": "anthropic/claude-opus-4.5", "price_cents": "1500"}
MIXED = "rename a variable and also redesign the storage architecture"
TYPO = "fix the typo in the README title"
DEFAULTS = Thresholds(500, 200)


def _decision(confidence: int, expensive_share: int) -> Decision:
    return Decision(pick=1, probabilities={1: 1000 - expensive_share, 2: expensive_share},
                    confidence=confidence, decider="test")


class EscalationRuleTest(unittest.TestCase):
    ROUTES = [{"id": 1, "price_cents": 100}, {"id": 2, "price_cents": 1500}]

    def test_fires_below_confidence_threshold_at_share_threshold(self):
        self.assertEqual(apply_escalation(_decision(499, 200), self.ROUTES, DEFAULTS), (2, True))

    def test_confidence_at_threshold_does_not_fire(self):
        self.assertEqual(apply_escalation(_decision(500, 200), self.ROUTES, DEFAULTS), (1, False))

    def test_share_below_threshold_does_not_fire(self):
        self.assertEqual(apply_escalation(_decision(499, 199), self.ROUTES, DEFAULTS), (1, False))

    def test_fires_when_decider_already_picked_the_expensive_route(self):
        decision = Decision(pick=2, probabilities={1: 400, 2: 600}, confidence=200, decider="test")
        self.assertEqual(apply_escalation(decision, self.ROUTES, DEFAULTS), (2, True))

    def test_price_tie_goes_to_lowest_id(self):
        routes = [{"id": 3, "price_cents": 900}, {"id": 2, "price_cents": 900}, {"id": 1, "price_cents": 100}]
        decision = Decision(pick=1, probabilities={1: 400, 2: 300, 3: 300}, confidence=100, decider="test")
        self.assertEqual(apply_escalation(decision, routes, DEFAULTS), (2, True))


class ThresholdsTest(AppTestCase):
    def setUp(self) -> None:
        self.get("/tester")  # make sure migrations have run
        self.sql("DELETE FROM decision_probabilities")
        self.sql("DELETE FROM decisions")
        self.sql("DELETE FROM routes")
        self.sql("UPDATE thresholds SET confidence = 500, share = 200")

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

    def decision_page(self, task: str) -> str:
        status, headers, _ = self.post_form("/tester", {"task": task})
        self.assertEqual(status, 303)
        status, _, body = self.get(headers["Location"])
        self.assertEqual(status, 200)
        return body

    def stored_thresholds(self) -> tuple:
        return self.sql("SELECT confidence, share FROM thresholds")[0]

    def test_mixed_task_escalates_to_strong(self):
        self.add_routes(CHEAP, STRONG)
        body = self.decision_page(MIXED)
        self.assertIn("Escalated: yes", body)
        self.assertIn("Chosen route: <strong>strong</strong>", body)

    def test_typo_task_page_says_whether_escalation_fired(self):
        self.add_routes(CHEAP, STRONG)
        self.assertRegex(self.decision_page(TYPO), r"Escalated: (yes|no)")

    def test_escalated_flag_is_stored(self):
        self.add_routes(CHEAP, STRONG)
        self.decision_page(MIXED)
        self.assertEqual(self.sql("SELECT escalated FROM decisions"), [(1,)])

    def test_price_tie_escalates_to_lower_id_route(self):
        small = {**CHEAP, "name": "small"}
        mid = {**STRONG, "name": "mid", "price_cents": "900"}
        big = {**STRONG, "name": "big", "price_cents": "900"}
        self.add_routes(small, mid, big)
        body = self.decision_page(MIXED)
        self.assertIn("Escalated: yes", body)
        self.assertIn("Chosen route: <strong>mid</strong>", body)

    def test_form_prefilled_with_defaults_and_linked_from_tester(self):
        status, _, body = self.get("/thresholds")
        self.assertEqual(status, 200)
        self.assertRegex(body, r'<input name="confidence_threshold" value="0\.5">')
        self.assertRegex(body, r'<input name="share_threshold" value="0\.2">')
        self.assertIn('<a href="/thresholds">Thresholds</a>', body)
        self.add_routes(CHEAP, STRONG)
        self.assertIn('href="/thresholds"', self.get("/tester")[2])

    def test_lowering_confidence_threshold_stops_escalation(self):
        self.add_routes(CHEAP, STRONG)
        status, headers, _ = self.post_form(
            "/thresholds", {"confidence_threshold": "0", "share_threshold": "0.2"})
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/thresholds")
        self.assertIn("Escalated: no", self.decision_page(MIXED))

    def test_raising_share_threshold_stops_escalation(self):
        self.add_routes(CHEAP, STRONG)
        self.assertIn("Escalated: yes", self.decision_page(MIXED))
        status, _, _ = self.post_form(
            "/thresholds", {"confidence_threshold": "1", "share_threshold": "1"})
        self.assertEqual(status, 303)
        self.assertIn("Escalated: no", self.decision_page(MIXED))

    def test_saved_values_show_in_form(self):
        self.post_form("/thresholds", {"confidence_threshold": "0.123", "share_threshold": "1"})
        self.assertEqual(self.stored_thresholds(), (123, 1000))
        body = self.get("/thresholds")[2]
        self.assertIn('name="confidence_threshold" value="0.123"', body)
        self.assertIn('name="share_threshold" value="1"', body)

    def test_invalid_values_are_rejected_and_nothing_changes(self):
        for bad in ("abc", "", "-0.1", "1.5", "0.1234", "1.001", "٣"):
            for field in ("confidence_threshold", "share_threshold"):
                with self.subTest(field=field, value=bad):
                    fields = {"confidence_threshold": "0.3", "share_threshold": "0.4"}
                    fields[field] = bad
                    status, _, body = self.post_form("/thresholds", fields)
                    self.assertEqual(status, 400)
                    self.assertRegex(body, r'class="error"')
                    self.assertIn(f'value="{bad}"', body)
                    self.assertEqual(self.stored_thresholds(), (500, 200))

    def test_missing_fields_are_rejected(self):
        status, _, body = self.post_form("/thresholds", {})
        self.assertEqual(status, 400)
        self.assertIn('class="error"', body)

    def test_submitted_value_is_escaped(self):
        _, _, body = self.post_form(
            "/thresholds", {"confidence_threshold": '"><img src=x>', "share_threshold": "0.2"})
        self.assertNotIn("<img", body)

    def test_old_decisions_keep_flag_and_route_after_threshold_change(self):
        self.add_routes(CHEAP, STRONG)
        _, headers, _ = self.post_form("/tester", {"task": MIXED})
        before = self.get(headers["Location"])[2]
        self.post_form("/thresholds", {"confidence_threshold": "0", "share_threshold": "0.2"})
        self.assertEqual(self.get(headers["Location"])[2], before)
        self.assertIn("Escalated: yes", before)

    def test_decisions_saved_before_the_migration_read_as_not_escalated(self):
        self.sql("INSERT INTO decisions (id, task, chosen_route_id, chosen_route_name, confidence, decider, "
                 "created_at) VALUES (77, 't', 1, 'cheap', 100, 'offline', '2026-01-01T00:00:00Z')")
        self.assertIn("Escalated: no", self.get("/decisions/77")[2])
