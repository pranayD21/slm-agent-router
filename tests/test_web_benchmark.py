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
from slm_agent_router.inbox_benchmark import (
    InboxCascadeProvider,
    InboxProviderOutput,
    analyze_prompt,
    deterministic_inbox_providers,
    inbox_context_for_agent,
    inbox_snapshot,
    run_inbox_comparison,
    select_emails,
)
from slm_agent_router.webui_benchmarks import normalize_report as normalize_webui_report
from slm_agent_router.webui_benchmarks import webui_benchmark_report
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


class StaticInboxProvider:
    def __init__(self, outputs, provider="ollama", model="test-inbox"):
        self.outputs = list(outputs)
        self.provider = provider
        self.model = model
        self.calls = []

    async def complete(self, prompt, intent, emails):
        self.calls.append({"prompt": prompt, "messages": len(emails)})
        index = min(len(self.calls) - 1, len(self.outputs) - 1)
        return self.outputs[index]


def inbox_provider_output(provider="ollama", model="test", ids=None, answer="", confidence=0.5):
    return InboxProviderOutput(
        provider=provider,
        model=model,
        selected_email_ids=ids or [],
        answer=answer,
        drafts=[],
        operations=[],
        raw="{}",
        input_tokens=100,
        output_tokens=40,
        confidence=confidence,
    )


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

    def test_webui_report_has_supported_suites_and_playbacks(self):
        report = webui_benchmark_report()
        suite_ids = {suite["id"] for suite in report["suites"]}
        self.assertEqual({"miniwob", "webarena", "visualwebarena", "workarena"}, suite_ids)
        model_ids = {model["id"] for model in report["models"]}
        self.assertEqual({"cascade", "openai", "claude"}, model_ids)
        self.assertGreaterEqual(len(report["playbacks"]), 4)

    def test_webui_normalizes_run_logs(self):
        report = normalize_webui_report(
            {
                "playbacks": [{"id": "miniwob-contact-form", "suite": "miniwob"}],
                "runs": [
                    {
                        "model": "cascade",
                        "suite": "miniwob",
                        "suite_name": "MiniWoB++",
                        "passed": True,
                        "elapsed_s": 5,
                        "total_tokens": 600,
                        "estimated_cost_usd": 0.004,
                        "steps": 4,
                        "slm_actions": 4,
                    },
                    {
                        "model": "openai",
                        "suite": "miniwob",
                        "suite_name": "MiniWoB++",
                        "passed": False,
                        "elapsed_s": 9,
                        "total_tokens": 1500,
                        "estimated_cost_usd": 0.02,
                        "steps": 5,
                    },
                ],
            },
            source="inline",
        )
        self.assertEqual(report["mode"], "imported")
        self.assertEqual(report["suites"][0]["success"]["cascade"], 1.0)
        self.assertEqual(report["playbacks"][0]["suite"], "miniwob")

    def test_inbox_snapshot_is_detailed(self):
        snapshot = inbox_snapshot()
        self.assertGreaterEqual(snapshot["stats"]["total"], 30)
        self.assertGreaterEqual(snapshot["stats"]["needs_response"], 20)
        self.assertIn("Customer", snapshot["categories"])
        self.assertGreaterEqual(len(snapshot["suggested_prompts"]), 4)

    async def test_inbox_run_compares_three_agents(self):
        run = await run_inbox_comparison(
            "Summarize the most important emails I need to respond to today.",
            providers=deterministic_inbox_providers(),
        )
        self.assertEqual({"cascade", "openai", "claude"}, {result["agent_id"] for result in run["results"]})
        self.assertNotIn("winner", run)
        self.assertIn("summary", run)
        for result in run["results"]:
            self.assertNotIn("effectiveness", result)
            self.assertIn("tokens", result)
            self.assertIn("cost_usd", result)
            self.assertGreaterEqual(result["runtime_ms"], 0)
            self.assertIn(result["status"], {"complete", "needs_review"})
            self.assertGreaterEqual(result["work"]["messages_scanned"], 30)
            self.assertGreaterEqual(len(result["selected_emails"]), 1)

    async def test_inbox_direct_sender_prompt_returns_matching_summary(self):
        run = await run_inbox_comparison("what did nora say", providers=deterministic_inbox_providers())
        self.assertEqual(["E-1005"], [email["id"] for email in run["matched_emails"]])
        for result in run["results"]:
            self.assertEqual(["E-1005"], [email["id"] for email in result["selected_emails"]])
            self.assertEqual("complete", result["status"])
            answer = result["answer"].lower()
            self.assertIn("summit bank", answer)
            self.assertIn("liability", answer)
            self.assertIn("uncapped", answer)

    async def test_inbox_reply_prompt_creates_drafts(self):
        run = await run_inbox_comparison(
            "Draft replies to the 3 highest priority customer emails.",
            providers=deterministic_inbox_providers(),
        )
        for result in run["results"]:
            self.assertGreaterEqual(len(result["drafts"]), 1)
            self.assertLessEqual(len(result["drafts"]), 3)

    async def test_inbox_cascade_accepts_high_confidence_ollama_without_fallback(self):
        prompt = "what did nora say"
        intent = analyze_prompt(prompt)
        local_context = inbox_context_for_agent(prompt, intent, "cascade")
        local = StaticInboxProvider(
            [
                inbox_provider_output(
                    model="llama-test",
                    ids=["E-1005"],
                    answer="Nora Patel said Summit Bank returned MSA redlines around liability cap, audit rights, and data retention.",
                    confidence=0.92,
                )
            ],
            provider="ollama",
            model="llama-test",
        )
        fallback = StaticInboxProvider(
            [
                inbox_provider_output(
                    provider="openai",
                    model="gpt-test",
                    ids=["E-1005"],
                    answer="Fallback should not be called.",
                    confidence=0.95,
                )
            ],
            provider="openai",
            model="gpt-test",
        )
        cascade = InboxCascadeProvider(local, [fallback], confidence_threshold=0.72, max_local_retries=1)

        output = await cascade.complete(prompt, intent, local_context)

        self.assertEqual("cascade", output.provider)
        self.assertIn("ollama:llama-test", output.model)
        self.assertEqual(["E-1005"], output.selected_email_ids)
        self.assertEqual(1, len(local.calls))
        self.assertEqual(0, len(fallback.calls))
        labels = [event["label"] for event in output.route_events]
        self.assertIn("Validate SLM plan", labels)
        self.assertIn("Local compose", labels)

    async def test_inbox_cascade_retries_then_falls_back_after_weak_local_answers(self):
        prompt = "what did nora say"
        intent = analyze_prompt(prompt)
        local_context = inbox_context_for_agent(prompt, intent, "cascade")
        local = StaticInboxProvider(
            [
                inbox_provider_output(answer="I am not sure.", confidence=0.2),
                inbox_provider_output(model="llama-test", ids=["E-1001"], answer="Maya asked for metrics.", confidence=0.48),
            ],
            provider="ollama",
            model="llama-test",
        )
        fallback = StaticInboxProvider(
            [
                inbox_provider_output(
                    provider="openai",
                    model="gpt-test",
                    ids=["E-1005"],
                    answer="Nora Patel said Summit Bank returned MSA redlines around liability cap, audit rights, and data retention.",
                    confidence=0.91,
                )
            ],
            provider="openai",
            model="gpt-test",
        )
        cascade = InboxCascadeProvider(local, [fallback], confidence_threshold=0.72, max_local_retries=1)

        output = await cascade.complete(prompt, intent, local_context)

        self.assertEqual("cascade", output.provider)
        self.assertIn("-> openai:gpt-test", output.model)
        self.assertEqual(["E-1005"], output.selected_email_ids)
        self.assertEqual(2, len(local.calls))
        self.assertEqual(1, len(fallback.calls))
        labels = [event["label"] for event in output.route_events]
        self.assertIn("Retry/replan", labels)
        self.assertIn("OpenAI synthesize", labels)
        self.assertGreater(output.cost_usd, 0)

    async def test_inbox_cascade_uses_llm_only_for_selected_summary_context(self):
        prompt = "Summarize the most important emails I need to respond to today."
        intent = analyze_prompt(prompt)
        matched_ids = [email["id"] for email in select_emails(prompt, intent, agent_id="evaluator")]
        local_context = inbox_context_for_agent(prompt, intent, "cascade")
        local = StaticInboxProvider(
            [
                inbox_provider_output(
                    model="llama-test",
                    ids=matched_ids,
                    answer="",
                    confidence=0.9,
                )
            ],
            provider="ollama",
            model="llama-test",
        )
        fallback = StaticInboxProvider(
            [
                inbox_provider_output(
                    provider="openai",
                    model="gpt-test",
                    ids=matched_ids,
                    answer="Maya Chen and Jordan Lee are important response targets today, along with the other selected deadline emails.",
                    confidence=0.95,
                )
            ],
            provider="openai",
            model="gpt-test",
        )
        cascade = InboxCascadeProvider(local, [fallback], confidence_threshold=0.72, max_local_retries=1)

        output = await cascade.complete(prompt, intent, local_context)

        self.assertIn("-> openai:gpt-test", output.model)
        self.assertEqual(1, len(local.calls))
        self.assertEqual(1, len(fallback.calls))
        self.assertEqual(len(matched_ids), fallback.calls[0]["messages"])
        self.assertLess(fallback.calls[0]["messages"], 30)
        labels = [event["label"] for event in output.route_events]
        self.assertIn("Ollama plan 1", labels)
        self.assertIn("OpenAI synthesize", labels)


if __name__ == "__main__":
    unittest.main()
