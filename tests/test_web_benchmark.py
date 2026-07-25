import unittest

from slm_agent_router.web_benchmark import (
    ActionProvider,
    AgentTimeoutError,
    CascadeProvider,
    ProviderDecision,
    build_fast_plan,
    choose_heuristic_action,
    clean_search_query,
    infer_route_kind,
    is_error_page,
    is_blocked_page,
    parse_action,
    provider_status,
    run_with_deadline,
    source_ready_for_synthesis,
    validate_local_action,
    validate_runtime_action,
    validate_action,
)
from slm_agent_router.gameworld import gameworld_report, normalize_report
import asyncio
import time


class StaticProvider(ActionProvider):
    def __init__(self, action, name="static", model="test", api_key=None):
        self.action = action
        self.name = name
        self.model = model
        self.api_key = api_key

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

    def test_heuristic_opens_visible_search_result_url_directly(self):
        action = choose_heuristic_action(
            "Find the official Python download page.",
            {
                "url": "https://search.brave.com/search?q=python+downloads",
                "title": "Search results",
                "text": "Python Releases for Windows",
                "elements": [
                    {
                        "id": "4",
                        "tag": "a",
                        "label": "Python Releases for Windows",
                        "href": "https://www.python.org/downloads/windows/",
                    }
                ],
            },
            [{"type": "action", "action": {"action": "goto", "text": "https://search.brave.com/search?q=python"}}],
        )
        self.assertEqual(action["action"], "goto")
        self.assertEqual(action["text"], "https://www.python.org/downloads/windows/")

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

    def test_fast_plan_breaks_synthesis_task_into_subtasks(self):
        plan = build_fast_plan(
            "scrape runnning shoe brands and me the best pair for 75 mi/week",
            {"url": "about:blank", "title": "", "text": "", "elements": []},
        )
        self.assertGreaterEqual(len(plan["subtasks"]), 4)
        self.assertTrue(plan["requires_synthesis"])
        self.assertTrue(any("Synthesize" in item for item in plan["subtasks"]))

    def test_source_ready_for_synthesis_requires_relevant_source_page(self):
        self.assertTrue(
            source_ready_for_synthesis(
                "recommend the best running shoe for high mileage",
                {
                    "url": "https://example.com/best-running-shoes",
                    "title": "Best Running Shoes",
                    "text": "Running shoes for high mileage runners need durable cushioning. "
                    * 20,
                    "headings": ["Best Running Shoes"],
                },
            )
        )
        self.assertFalse(
            source_ready_for_synthesis(
                "recommend the best running shoe for high mileage",
                {
                    "url": "https://search.brave.com/search?q=running+shoes",
                    "title": "Search results",
                    "text": "Running shoes high mileage",
                },
            )
        )

    async def test_deadline_helper_times_out(self):
        with self.assertRaises(AgentTimeoutError):
            await run_with_deadline(asyncio.sleep(0.05), time.perf_counter() + 0.001, "tiny task")

    async def test_cascade_uses_fallback_after_low_confidence(self):
        local = StaticProvider({"action": "wait", "reason": "unsure", "confidence": 0.1}, name="local")
        fallback = StaticProvider(
            {"action": "finish", "text": "done", "reason": "fallback", "confidence": 1},
            name="fallback",
            model="cloud",
            api_key="test-key",
        )
        cascade = CascadeProvider([local], fallback, confidence_threshold=0.7)
        decision = await cascade.decide("task", {"elements": []}, [])
        self.assertEqual(decision.action["action"], "finish")
        self.assertIn("fallback", decision.routed_from)
        self.assertEqual(decision.route_kind, "llm")
        self.assertEqual(decision.route_label, "LLM fallback")
        self.assertEqual(decision.routing_reasons, ["local:low_confidence"])

    async def test_cascade_marks_local_selection_as_slm(self):
        local = StaticProvider(
            {
                "action": "goto",
                "text": "https://example.com",
                "reason": "direct",
                "confidence": 0.95,
            },
            name="local-fast",
        )
        fallback = StaticProvider({"action": "finish", "text": "fallback", "reason": "fallback", "confidence": 1})
        cascade = CascadeProvider([local], fallback, confidence_threshold=0.7)
        decision = await cascade.decide("go to example.com", {"elements": []}, [])
        self.assertEqual(decision.action["action"], "goto")
        self.assertEqual(decision.route_kind, "slm")
        self.assertEqual(decision.route_label, "SLM: local-fast")
        self.assertEqual(decision.routing_reasons, [])

    def test_infers_route_kind_for_legacy_events(self):
        self.assertEqual(infer_route_kind("cascade", "fallback after local:low_confidence"), "llm")
        self.assertEqual(infer_route_kind("cascade", "local-heuristic"), "slm")
        self.assertEqual(infer_route_kind("openai", ""), "llm")

    def test_provider_status_includes_comparison_agents(self):
        status = provider_status()
        self.assertIn("cascade", status)
        self.assertIn("openai", status)
        self.assertIn("claude", status)

    def test_gameworld_report_compares_three_models(self):
        report = gameworld_report()
        model_ids = {model["id"] for model in report["models"]}
        self.assertEqual({"cascade", "openai", "claude"}, model_ids)
        self.assertGreaterEqual(len(report["games"]), 3)
        self.assertIn("winner", report["summary"])
        playback_ids = {playback["id"] for playback in report["playbacks"]}
        self.assertIn("2048", playback_ids)
        self.assertIn("minecraft", playback_ids)

    def test_gameworld_normalizes_run_logs(self):
        report = normalize_report(
            {
                "playbacks": [{"id": "2048", "models": {}}],
                "runs": [
                    {
                        "model": "cascade",
                        "game": "2048",
                        "genre": "Puzzle",
                        "task": "Reach 128",
                        "passed": True,
                        "score": 1,
                        "elapsed_s": 8,
                        "total_tokens": 1000,
                        "estimated_cost_usd": 0.01,
                        "slm_actions": 4,
                    },
                    {
                        "model": "openai",
                        "game": "2048",
                        "passed": False,
                        "score": 0.4,
                        "elapsed_s": 12,
                        "total_tokens": 2000,
                        "estimated_cost_usd": 0.04,
                    },
                ]
            },
            source="inline",
        )
        self.assertEqual(report["mode"], "imported")
        self.assertEqual(len(report["models"]), 2)
        self.assertEqual(report["games"][0]["scores"]["cascade"], 1.0)
        self.assertEqual(report["playbacks"][0]["id"], "2048")


if __name__ == "__main__":
    unittest.main()
