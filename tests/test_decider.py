import json
import socket
import http.client
import unittest
import urllib.error

from app.features.decider import JEV_MODEL, JEV_URL, Decider, Decision, JevDecider, OfflineDecider

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

    def test_shared_word_lets_a_higher_id_route_win(self):
        decision = self.decider.decide("redesign the architecture", TWO)
        self.assertEqual(decision.pick, 2)
        self.assertGreater(decision.probabilities[2], decision.probabilities[1])

    def test_plural_in_criteria_matches_singular_in_task(self):
        routes = [_route(1, 100), _route(2, 100, "typos and spelling")]
        decision = self.decider.decide("fix the typo", routes)
        self.assertEqual(decision.pick, 2)
        self.assertGreater(decision.probabilities[2], decision.probabilities[1])

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
        self.assertGreater(long, short)

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


THREE = [_route(1, 100, "typo fixes"), _route(2, 500, "features"), _route(3, 1500, "architecture")]


def _answer(choice="route_1", confidence=0.67, probabilities=None):
    probabilities = {"route_1": 0.78, "route_2": 0.22, "route_3": 0} if probabilities is None else probabilities
    body = {"answers": {"route": {"choice": choice, "confidence": confidence, "probabilities": probabilities}}}
    return 200, json.dumps(body).encode()


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.requests = response or _answer(), error, []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class JevDeciderTest(unittest.TestCase):
    def decide(self, transport, routes=THREE):
        return JevDecider("test-key", transport).decide("fix the typo", routes)

    def test_request_shape(self):
        transport = FakeTransport()
        self.decide(transport)
        (request,) = transport.requests
        self.assertEqual(request.full_url, JEV_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data)
        self.assertEqual(body["model"], JEV_MODEL)
        self.assertEqual(body["state"], {"task": "fix the typo"})
        (question,) = body["questions"].values()
        self.assertEqual(question["type"], "choice")
        self.assertEqual(sorted(question["criteria"].values()), ["architecture", "features", "typo fixes"])
        self.assertEqual(len(question["criteria"]), 3)

    def test_option_keys_are_unique_when_names_share(self):
        transport = FakeTransport()
        self.decide(transport, [dict(r, name="same") for r in THREE])
        (question,) = json.loads(transport.requests[0].data)["questions"].values()
        self.assertEqual(len(question["criteria"]), 3)

    def test_canned_answer_becomes_thousandths(self):
        decision = self.decide(FakeTransport())
        self.assertEqual(decision.pick, 1)
        self.assertEqual(decision.confidence, 670)
        self.assertEqual(dict(decision.probabilities), {1: 780, 2: 220, 3: 0})
        self.assertEqual(decision.decider, "jev")

    def test_probabilities_are_normalised_to_1000(self):
        third = {"route_1": 0.3333, "route_2": 0.3333, "route_3": 0.3333}
        decision = self.decide(FakeTransport(_answer(probabilities=third)))
        self.assertEqual(sum(decision.probabilities.values()), 1000)
        self.assertEqual(decision.decider, "jev")

    def assert_falls_back(self, transport):
        decision = self.decide(transport)
        self.assertEqual(decision.decider, "offline")
        self.assertEqual(sum(decision.probabilities.values()), 1000)

    def test_url_error_falls_back(self):
        self.assert_falls_back(FakeTransport(error=urllib.error.URLError("down")))

    def test_timeout_falls_back(self):
        self.assert_falls_back(FakeTransport(error=socket.timeout("slow")))

    def test_truncated_response_falls_back(self):
        self.assert_falls_back(FakeTransport(error=http.client.IncompleteRead(b"{")))

    def test_non_200_falls_back(self):
        self.assert_falls_back(FakeTransport((500, b"{}")))

    def test_invalid_json_falls_back(self):
        self.assert_falls_back(FakeTransport((200, b"not json")))

    def test_missing_route_in_probabilities_falls_back(self):
        self.assert_falls_back(FakeTransport(_answer(probabilities={"route_1": 0.5, "route_2": 0.5})))

    def test_unknown_choice_falls_back(self):
        self.assert_falls_back(FakeTransport(_answer(choice="nope")))

    def test_out_of_range_probability_falls_back(self):
        self.assert_falls_back(FakeTransport(_answer(probabilities={"route_1": 2, "route_2": 0, "route_3": 0})))

    def test_all_zero_probabilities_fall_back(self):
        self.assert_falls_back(FakeTransport(_answer(probabilities={"route_1": 0, "route_2": 0, "route_3": 0})))


if __name__ == "__main__":
    unittest.main()
