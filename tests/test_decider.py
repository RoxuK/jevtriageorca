import socket
import unittest

from app.features.decider import Decider, Decision, OfflineDecider

CHEAP = {"id": 1, "name": "cheap", "criteria": "small edits, renames, typos", "price_cents": 100}
STRONG = {
    "id": 2,
    "name": "strong",
    "criteria": "architecture, multi-file refactors, hard debugging",
    "price_cents": 1500,
}
TWO = [CHEAP, STRONG]


def _route(route_id, price, criteria="unrelated"):
    return {"id": route_id, "criteria": criteria, "price_cents": price}


class OfflineDeciderTest(unittest.TestCase):
    def setUp(self):
        self.decider = OfflineDecider()

    def test_is_a_decider_named_offline(self):
        decision = self.decider.decide("anything", TWO)
        self.assertIsInstance(self.decider, Decider)
        self.assertIsInstance(decision, Decision)
        self.assertEqual(decision.decider, "offline")

    def test_probabilities_cover_every_route_and_sum_to_1000(self):
        for task in ("fix the typo", "architecture " * 40, "zzz"):
            for routes in (TWO, [_route(i, 100 * i) for i in range(1, 6)]):
                probs = self.decider.decide(task, routes).probabilities
                self.assertEqual(set(probs), {r["id"] for r in routes})
                self.assertTrue(all(isinstance(v, int) and 0 <= v <= 1000 for v in probs.values()))
                self.assertEqual(sum(probs.values()), 1000)

    def test_confidence_is_in_range_and_pick_is_top_with_lowest_id_on_tie(self):
        decision = self.decider.decide("fix the typo in the README title", TWO)
        self.assertTrue(isinstance(decision.confidence, int) and 0 <= decision.confidence <= 1000)
        self.assertEqual(decision.probabilities[decision.pick], max(decision.probabilities.values()))
        tied = self.decider.decide("zzz", [_route(7, 100), _route(3, 100), _route(5, 100)])
        self.assertEqual(tied.pick, 3)

    def test_same_arguments_give_equal_results(self):
        task = "rename a variable and also redesign the storage architecture"
        self.assertEqual(self.decider.decide(task, TWO), self.decider.decide(task, TWO))

    def test_typo_task_picks_cheap(self):
        self.assertEqual(self.decider.decide("fix the typo in the README title", TWO).pick, 1)

    def test_mixed_task_is_low_confidence_with_real_share_for_strong(self):
        decision = self.decider.decide(
            "rename a variable and also redesign the storage architecture", TWO
        )
        self.assertLess(decision.confidence, 500)
        self.assertGreaterEqual(decision.probabilities[2], 200)

    def test_unmatched_one_word_and_multi_paragraph_tasks_are_valid(self):
        long_task = ("First paragraph about nothing.\n\n" * 80)
        self.assertGreaterEqual(len(long_task), 2000)
        for task in ("zzz", "refactor", long_task, ""):
            probs = self.decider.decide(task, TWO).probabilities
            self.assertEqual(sum(probs.values()), 1000)

    def test_longer_tasks_do_not_lower_the_most_expensive_route(self):
        routes = [_route(1, 100), _route(2, 500), _route(3, 1500)]
        short = self.decider.decide("zzz", routes).probabilities[3]
        long = self.decider.decide("x" * 2000, routes).probabilities[3]
        self.assertGreaterEqual(long, short)

    def test_tied_top_price_still_sums_to_1000(self):
        routes = [_route(1, 100), _route(2, 1500), _route(3, 1500)]
        for task in ("zzz", "x" * 2000):
            probs = self.decider.decide(task, routes).probabilities
            self.assertEqual(len(probs), 3)
            self.assertEqual(sum(probs.values()), 1000)

    def test_markup_quotes_and_non_ascii_do_not_raise(self):
        nasty = '<script>alert("x")</script> \'quoted\' naïve café 日本語'
        routes = [_route(1, 100, nasty), _route(2, 200, "ünïcode <b>bold</b> \"q\"")]
        decision = self.decider.decide(nasty, routes)
        self.assertEqual(sum(decision.probabilities.values()), 1000)

    def test_no_socket_is_opened(self):
        original = socket.socket.connect
        socket.socket.connect = lambda *a, **k: self.fail("network used")
        try:
            self.decider.decide("fix the typo", TWO)
        finally:
            socket.socket.connect = original


if __name__ == "__main__":
    unittest.main()
