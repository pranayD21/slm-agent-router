import unittest

from slm_agent_router.web_benchmark import (
    ActionProvider,
    CascadeProvider,
    ProviderDecision,
    choose_heuristic_action,
    clean_search_query,
    is_error_page,
    is_blocked_page,
    parse_action,
    provider_status,
    validate_local_action,
    validate_runtime_action,
    validate_action,
)


class StaticProvider(ActionProvider):
    def __init__(self, action, name="static", model="test"):
        self.action = action
        self.name = name
        self.model = model

    async def decide(self, task, snapshot, history):
        return ProviderDecision(self.action, "{}", self.model, 1)


class WebBenchmarkTests(unittest.IsolatedAsyncioTestCase):
    def test_validate_action_rejects_unknown_action(self):
        ok, reason = validate_action({"action": "dance", "reason": "nope", "confidence": 1})
        self.assertFalse(ok)
        self.assertEqual(reason, "unknown_action")

    def test_parse_action_extracts_json_from_text(self):
        action = parse_action('next: {"action":"wait","reason":"loading","confidence":0.4}')
        self.assertEqual(action["action"], "wait")

    def test_heuristic_opens_explicit_url_first(self):
        action = choose_heuristic_action(
            "Go to https://example.com and report the page heading.",
            {"url": "about:blank", "elements": [], "text": ""},
            [],
        )
        self.assertEqual(action["action"], "goto")
        self.assertEqual(action["text"], "https://example.com")
        self.assertGreater(action["confidence"], 0.9)

    def test_heuristic_uses_lighter_search_route(self):
        action = choose_heuristic_action(
            "Find the official Python download page.",
            {"url": "about:blank", "elements": [], "text": ""},
            [],
        )
        self.assertEqual(action["action"], "goto")
        self.assertIn("search.brave.com/search", action["text"])

    def test_local_finish_rejected_on_search_results(self):
        ok, reason = validate_local_action(
            {"action": "finish", "text": "Some snippet", "reason": "done", "confidence": 0.9},
            "Find the official Python download page.",
            {"url": "https://duckduckgo.com/html/?q=python", "title": "Search results", "text": "results"},
            [{"type": "action", "action": {"action": "goto"}}],
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "search_result_not_source")

    def test_detects_unusual_traffic_pages(self):
        self.assertTrue(
            is_blocked_page(
                {
                    "url": "https://www.google.com/sorry/index",
                    "title": "Unusual traffic",
                    "text": "Our systems have detected unusual traffic from your computer network.",
                }
            )
        )

    def test_local_finish_rejected_on_not_found_page(self):
        ok, reason = validate_local_action(
            {"action": "finish", "text": "Oops! We can't find this page.", "reason": "done", "confidence": 0.9},
            "Find the best high mileage running shoe.",
            {
                "url": "https://runrepeat.com/guides/best-high-mileage-running-shoes",
                "title": "Page not found",
                "text": "Oops! We can't find this page. Categories Running Sneakers Hiking",
            },
            [{"type": "action", "action": {"action": "goto"}}],
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "error_page")

    def test_recommendation_tasks_cascade_instead_of_local_finish(self):
        ok, reason = validate_local_action(
            {
                "action": "finish",
                "text": "A shoe page with lots of running shoe text.",
                "reason": "done",
                "confidence": 0.9,
            },
            "Recommend the best pair of shoes for an amateur running 75 mi/week.",
            {
                "url": "https://example.com/running-shoes",
                "title": "Best Running Shoes",
                "text": "Running shoes, high mileage, neutral trainers, plated shoes, cushioning.",
            },
            [{"type": "action", "action": {"action": "goto"}}],
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "synthesis_required")

    def test_detects_not_found_pages(self):
        self.assertTrue(
            is_error_page(
                {
                    "url": "https://example.com/missing",
                    "title": "Page not found",
                    "text": "Oops! We can't find this page.",
                }
            )
        )

    def test_runtime_finish_rejected_on_not_found_page(self):
        ok, reason = validate_runtime_action(
            {"action": "finish", "text": "Oops! We can't find this page.", "reason": "done", "confidence": 1},
            "Summarize the page.",
            {
                "url": "https://example.com/missing",
                "title": "Page not found",
                "text": "Oops! We can't find this page.",
            },
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "error_page")

    def test_clean_search_query_removes_scrape_noise(self):
        query = clean_search_query("scrape runnning shoe brands and me the best pair for 75 mi/week")
        self.assertIn("running", query)
        self.assertIn("75 miles per week", query)
        self.assertNotIn("scrape", query)
        self.assertNotIn("and me", query)

    async def test_cascade_uses_fallback_after_low_confidence(self):
        local = StaticProvider({"action": "wait", "reason": "unsure", "confidence": 0.1}, name="local")
        fallback = StaticProvider(
            {"action": "finish", "text": "done", "reason": "fallback", "confidence": 1},
            name="fallback",
            model="cloud",
        )
        cascade = CascadeProvider([local], fallback, confidence_threshold=0.7)
        decision = await cascade.decide("task", {"elements": []}, [])
        self.assertEqual(decision.action["action"], "finish")
        self.assertIn("fallback", decision.routed_from)

    def test_provider_status_includes_comparison_agents(self):
        status = provider_status()
        self.assertIn("cascade", status)
        self.assertIn("openai", status)
        self.assertIn("claude", status)


if __name__ == "__main__":
    unittest.main()
