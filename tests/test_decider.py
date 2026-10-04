import socket
import unittest

from app.features.decider import Decider, Decision, OfflineDecider

CHEAP = {"id": 1, "criteria": "small edits, renames, typos", "price_cents": 100}
STRONG = {"id": 2, "criteria": "architecture, multi-file refactors, hard debugging", "price_cents": 1500}
TWO = [CHEAP, STRONG]


def decide(task, routes=TWO):
    return OfflineDecider().decide(task, routes)


class OfflineDeciderTest(unittest.TestCase):
    def setUp(self):
        def no_socket(*args, **kwargs):
            raise AssertionError("decider must not open sockets")

        original = socket.socket
        socket.socket = no_socket
        self.addCleanup(setattr, socket, "socket", original)

    def assert_valid(self, decision, routes):
        self.assertIsInstance(decision, Decision)
        self.assertEqual(set(decision.probabilities), {r["id"] for r in routes})
        for value in decision.probabilities.values():
            self.assertIsInstance(value, int)
            self.assertTrue(0 <= value <= 1000)
        self.assertEqual(sum(decision.probabilities.values()), 1000)
        self.assertIsInstance(decision.confidence, int)
        self.assertTrue(0 <= decision.confidence <= 1000)
        self.assertEqual(decision.decider, "offline")

    def test_is_a_decider(self):
        self.assertIsInstance(OfflineDecider(), Decider)

    def test_probabilities_cover_every_route_and_sum_to_1000(self):
        self.assert_valid(decide("fix the typo in the README title"), TWO)

    def test_pick_is_highest_probability_and_confidence_in_range(self):
        d = decide("fix the typo in the README title")
        self.assertEqual(d.pick, max(d.probabilities, key=lambda r: (d.probabilities[r], -r)))

    def test_tie_picks_lowest_id(self):
        routes = [
            {"id": 7, "criteria": "alpha", "price_cents": 5},
            {"id": 3, "criteria": "beta", "price_cents": 5},
        ]
        d = decide("zzz", routes)
        self.assertEqual(d.probabilities[3], d.probabilities[7])
        self.assertEqual(d.pick, 3)

    def test_same_arguments_give_equal_decisions(self):
        self.assertEqual(decide("rename the storage layer"), decide("rename the storage layer"))

    def test_typo_task_picks_cheap(self):
        self.assertEqual(decide("fix the typo in the README title").pick, 1)

    def test_mixed_task_is_low_confidence_with_strong_in_play(self):
        d = decide("rename a variable and also redesign the storage architecture")
        self.assertLess(d.confidence, 500)
        self.assertGreaterEqual(d.probabilities[2], 200)

    def test_task_sharing_no_word_is_valid(self):
        self.assert_valid(decide("zzz"), TWO)

    def test_one_word_task_is_valid(self):
        self.assert_valid(decide("refactor"), TWO)

    def test_multi_paragraph_task_is_valid(self):
        task = ("Please look at the module.\n\n" * 100)
        self.assertGreaterEqual(len(task), 2000)
        self.assert_valid(decide(task), TWO)

    def test_long_task_leans_to_most_expensive_route(self):
        routes = [
            {"id": 1, "criteria": "alpha", "price_cents": 100},
            {"id": 2, "criteria": "beta", "price_cents": 500},
            {"id": 3, "criteria": "gamma", "price_cents": 1500},
        ]
        short = decide("zzz", routes).probabilities[3]
        long = decide("q" * 2000, routes).probabilities[3]
        self.assertGreaterEqual(long, short)

    def test_two_routes_sharing_top_price_sum_to_1000(self):
        routes = [
            {"id": 1, "criteria": "alpha", "price_cents": 100},
            {"id": 2, "criteria": "beta", "price_cents": 900},
            {"id": 3, "criteria": "gamma", "price_cents": 900},
        ]
        self.assert_valid(decide("a long enough task " * 20, routes), routes)

    def test_markup_quotes_and_non_ascii_do_not_raise(self):
        routes = [
            {"id": 1, "criteria": "<script>alert(\"x\")</script> naïve café", "price_cents": 1},
            {"id": 2, "criteria": "'quoted' 日本語 ünïcode", "price_cents": 2},
        ]
        self.assert_valid(decide("<script>'\" café 日本語 \u0000", routes), routes)

    def test_single_route_gets_everything(self):
        d = decide("anything", [CHEAP])
        self.assertEqual(d.probabilities, {1: 1000})
        self.assertEqual(d.pick, 1)

    def test_no_routes_is_rejected(self):
        with self.assertRaises(ValueError):
            decide("anything", [])


if __name__ == "__main__":
    unittest.main()
