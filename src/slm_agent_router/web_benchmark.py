from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse


ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["goto", "click", "fill", "press", "wait", "finish"],
        },
        "target": {
            "type": "string",
            "description": "Visible element id from the page snapshot, such as 12.",
        },
        "selector": {
            "type": "string",
            "description": "Optional CSS selector when an element id is not available.",
        },
        "text": {
            "type": "string",
            "description": "Text to enter, key to press, URL to visit, or final answer.",
        },
        "reason": {
            "type": "string",
            "description": "Brief explanation of why this action is next.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },
    "required": ["action", "target", "selector", "text", "reason", "confidence"],
}

ALLOWED_ACTIONS = set(ACTION_SCHEMA["properties"]["action"]["enum"])
TEXT_ACTIONS = {"goto", "fill", "press", "finish"}
TARGET_ACTIONS = {"click", "fill"}

SYSTEM_PROMPT = """You are a browser-navigation agent.
Choose exactly one next browser action that moves toward completing the user's task.

Rules:
- Return only JSON matching the browser_action schema.
- Use element ids from the page snapshot when clicking or filling.
- Prefer a single direct action over narration.
- Use finish only when the requested web task is complete or clearly impossible.
- If you need a web page and the browser is blank, use goto.
- Avoid Google/Bing for generic searches unless the user explicitly requires them; use direct URLs or https://search.brave.com/search?q=... to reduce bot-protection blocks.
- If the page shows CAPTCHA, unusual traffic, or bot protection, do not solve it. Navigate to a less bot-prone route or finish with a clear blocked message.
- Do not finish from 404, not-found, unavailable, forbidden, or generic error pages.
- If the user asks for a recommendation, comparison, or "best" choice, use a relevant source page as evidence and synthesize a concise recommendation; do not return raw page text.
- Follow fast_plan.subtasks in order. Treat them as the checklist for completing the user's task, and do not finish until the checklist is satisfied.
- If fast_plan.source_ready is true for a synthesis/recommendation task, finish with the best answer from the current source instead of clicking deeper.
- Keep the final answer short and factual."""

BROWSER_START_TIMEOUT_S = 20
BROWSER_SNAPSHOT_TIMEOUT_S = 8
BROWSER_SCREENSHOT_TIMEOUT_S = 8
BROWSER_ACTION_TIMEOUT_S = 15
MODEL_DECISION_TIMEOUT_S = 28


@dataclass
class ProviderDecision:
    action: dict[str, Any]
    raw: str
    model: str
    latency_ms: int
    routed_from: str | None = None
    route_kind: str | None = None
    route_label: str | None = None
    routing_reasons: list[str] | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgentConfig:
    agent_id: str
    label: str
    provider: "ActionProvider"
    badge: str


class ActionProvider:
    name = "provider"
    model = "unknown"

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        raise NotImplementedError


class UnavailableProvider(ActionProvider):
    def __init__(self, name: str, message: str):
        self.name = name
        self.model = "unavailable"
        self.message = message

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        started = time.perf_counter()
        action = {
            "action": "finish",
            "text": self.message,
            "reason": self.message,
            "confidence": 1,
        }
        return ProviderDecision(
            action,
            json.dumps(action),
            self.model,
            elapsed_ms(started),
            route_kind="unavailable",
            route_label="Fallback unavailable",
        )


class HeuristicProvider(ActionProvider):
    name = "local-heuristic"
    model = "rules"

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        started = time.perf_counter()
        action = choose_heuristic_action(task, snapshot, history)
        return ProviderDecision(
            action,
            json.dumps(action),
            self.model,
            elapsed_ms(started),
            route_kind="slm",
            route_label="SLM",
        )


class BrowserSafetyProvider(ActionProvider):
    def __init__(self, provider: ActionProvider):
        self.provider = provider
        self.name = provider.name
        self.model = provider.model
        self.api_key = getattr(provider, "api_key", None)

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        started = time.perf_counter()
        guarded = choose_browser_safety_action(task, snapshot, history)
        if guarded:
            raw = json.dumps(guarded)
            return ProviderDecision(
                guarded,
                raw,
                self.model,
                elapsed_ms(started),
                "browser-safety",
                route_kind="safety",
                route_label="Safety rule",
            )
        return await self.provider.decide(task, snapshot, history)


class OllamaProvider(ActionProvider):
    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 60,
    ):
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.1")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout_s = timeout_s

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        import httpx

        started = time.perf_counter()
        prompt = build_model_prompt(task, snapshot, history)
        payload = {
            "model": self.model,
            "stream": False,
            "format": ACTION_SCHEMA,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        raw = response.json().get("message", {}).get("content", "")
        return ProviderDecision(
            parse_action(raw),
            raw,
            self.model,
            elapsed_ms(started),
            route_kind="slm",
            route_label="SLM",
        )


class OpenAIProvider(ActionProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 90,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout_s = timeout_s

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        if not self.api_key:
            return await UnavailableProvider(
                "openai",
                "Set OPENAI_API_KEY to run the OpenAI comparison agent.",
            ).decide(task, snapshot, history)

        import httpx

        started = time.perf_counter()
        prompt = build_model_prompt(task, snapshot, history)
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "browser_action",
                    "strict": True,
                    "schema": ACTION_SCHEMA,
                }
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.base_url}/responses", headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        raw = extract_openai_text(data)
        input_tokens, output_tokens = extract_openai_usage(data)
        return ProviderDecision(
            parse_action(raw),
            raw,
            self.model,
            elapsed_ms(started),
            route_kind="llm",
            route_label="LLM",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class AnthropicProvider(ActionProvider):
    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 90,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")).rstrip("/")
        self.timeout_s = timeout_s

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        if not self.api_key:
            return await UnavailableProvider(
                "claude",
                "Set ANTHROPIC_API_KEY to run the Claude comparison agent.",
            ).decide(task, snapshot, history)

        import httpx

        started = time.perf_counter()
        prompt = build_model_prompt(task, snapshot, history)
        payload = {
            "model": self.model,
            "max_tokens": 1200,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": "browser_action",
                    "description": "Choose the next browser action.",
                    "input_schema": ACTION_SCHEMA,
                }
            ],
            "tool_choice": {"type": "tool", "name": "browser_action"},
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.base_url}/messages", headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        action, raw = extract_anthropic_action(data)
        input_tokens, output_tokens = extract_anthropic_usage(data)
        return ProviderDecision(
            normalize_action(action),
            raw,
            self.model,
            elapsed_ms(started),
            route_kind="llm",
            route_label="LLM",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class CascadeProvider(ActionProvider):
    name = "slm-cascade"

    def __init__(
        self,
        local_providers: list[ActionProvider],
        fallback_provider: ActionProvider,
        confidence_threshold: float = 0.58,
        finish_confidence_threshold: float = 0.82,
    ):
        self.local_providers = local_providers
        self.fallback_provider = fallback_provider
        self.confidence_threshold = confidence_threshold
        self.finish_confidence_threshold = finish_confidence_threshold
        self.model = f"{' + '.join(provider.model for provider in local_providers)} -> {fallback_provider.model}"

    async def decide(
        self,
        task: str,
        snapshot: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> ProviderDecision:
        started = time.perf_counter()
        reasons: list[str] = []
        if is_dead_end(history):
            reasons.append("dead_end")
            decision = await self.fallback_provider.decide(task, snapshot, history)
            decision.routed_from = f"fallback after {', '.join(reasons)}"
            decision.route_kind = "llm" if getattr(self.fallback_provider, "api_key", None) else "unavailable"
            decision.route_label = "LLM fallback" if decision.route_kind == "llm" else "Fallback unavailable"
            decision.routing_reasons = reasons
            decision.latency_ms = elapsed_ms(started)
            return decision
        for provider in self.local_providers:
            decision = await provider.decide(task, snapshot, history)
            ok, reason = validate_local_action(decision.action, task, snapshot, history)
            confidence = float(decision.action.get("confidence", 0))
            threshold = (
                self.finish_confidence_threshold
                if decision.action.get("action") == "finish"
                else self.confidence_threshold
            )
            if ok and confidence >= threshold:
                decision.routed_from = provider.name
                decision.route_kind = "slm"
                decision.route_label = f"SLM: {provider.name}"
                decision.routing_reasons = []
                decision.latency_ms = elapsed_ms(started)
                return decision
            reasons.append(f"{provider.name}:{reason or 'low_confidence'}")

        decision = await self.fallback_provider.decide(task, snapshot, history)
        decision.routed_from = f"fallback after {', '.join(reasons)}"
        decision.route_kind = "llm" if getattr(self.fallback_provider, "api_key", None) else "unavailable"
        decision.route_label = "LLM fallback" if decision.route_kind == "llm" else "Fallback unavailable"
        decision.routing_reasons = reasons
        decision.latency_ms = elapsed_ms(started)
        return decision


class BrowserController:
    def __init__(self, viewport: dict[str, int] | None = None, headless: bool = True):
        self.viewport = viewport or {"width": 1280, "height": 860}
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self, start_url: str | None = None) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run `python3 -m pip install -e '.[web]'` "
                "and `python3 -m playwright install chromium`."
            ) from exc

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport=self.viewport,
            locale="en-US",
            timezone_id=os.getenv("TZ", "America/Los_Angeles"),
            color_scheme="light",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self.page = await self.context.new_page()
        if start_url:
            await self.goto(start_url)

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def goto(self, url: str) -> None:
        assert self.page is not None
        await self.page.goto(ensure_url(url), wait_until="domcontentloaded", timeout=25000)
        await self.page.wait_for_timeout(350)

    async def snapshot(self) -> dict[str, Any]:
        assert self.page is not None
        elements = await self.page.evaluate(
            """
            () => {
              const candidates = Array.from(document.querySelectorAll(
                'a,button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"]'
              ));
              const visible = [];
              for (const el of candidates) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (rect.width < 2 || rect.height < 2 || style.visibility === 'hidden' || style.display === 'none') {
                  continue;
                }
                const id = String(visible.length + 1);
                el.setAttribute('data-agent-target', id);
                const label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
                  el.getAttribute('name') || el.value || el.href || '').replace(/\\s+/g, ' ').trim();
                visible.push({
                  id,
                  tag: el.tagName.toLowerCase(),
                  role: el.getAttribute('role') || '',
                  type: el.getAttribute('type') || '',
                  label: label.slice(0, 180),
                  href: el.href || '',
                  placeholder: el.getAttribute('placeholder') || '',
                  value: el.value || '',
                  x: Math.round(rect.x),
                  y: Math.round(rect.y)
                });
                if (visible.length >= 90) break;
              }
              return visible;
            }
            """
        )
        headings = await self.page.evaluate(
            """
            () => Array.from(document.querySelectorAll('h1,h2'))
              .map((el) => (el.innerText || '').replace(/\\s+/g, ' ').trim())
              .filter(Boolean)
              .slice(0, 8)
            """
        )
        title = await self.page.title()
        try:
            body_text = await self.page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        return {
            "url": self.page.url,
            "title": title,
            "text": compact_text(body_text, 2500),
            "headings": headings,
            "elements": elements,
        }

    async def screenshot_data_url(self) -> str:
        assert self.page is not None
        data = await self.page.screenshot(type="jpeg", quality=72, full_page=False)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    async def apply_action(self, action: dict[str, Any]) -> str:
        assert self.page is not None
        normalized = normalize_action(action)
        kind = normalized["action"]
        target = normalized.get("target", "")
        selector = normalized.get("selector", "")
        text = normalized.get("text", "")

        if kind == "goto":
            await self.goto(text)
            return f"Visited {ensure_url(text)}"
        if kind == "wait":
            await self.page.wait_for_timeout(900)
            return "Waited for page changes"
        if kind == "press":
            await self.page.keyboard.press(text or "Enter")
            await self.page.wait_for_timeout(450)
            return f"Pressed {text or 'Enter'}"
        if kind == "click":
            locator = self._locator(target, selector, text)
            await locator.click(timeout=10000)
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            await self.page.wait_for_timeout(450)
            return f"Clicked {target or selector or text}"
        if kind == "fill":
            locator = self._locator(target, selector, "")
            await locator.fill(text, timeout=10000)
            await self.page.wait_for_timeout(200)
            return f"Filled {target or selector} with {text[:80]}"
        if kind == "finish":
            return "Finished"
        raise ValueError(f"Unsupported action: {kind}")

    def _locator(self, target: str, selector: str, text: str):
        assert self.page is not None
        if target:
            return self.page.locator(f'[data-agent-target="{target}"]').first
        if selector:
            return self.page.locator(selector).first
        if text:
            return self.page.get_by_text(text, exact=False).first
        raise ValueError("Action needs target, selector, or text.")


EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class AgentTimeoutError(TimeoutError):
    pass


async def run_with_deadline(awaitable, deadline: float, label: str, cap_s: float | None = None):
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        raise AgentTimeoutError(f"{label} timed out because the agent reached its run deadline.")
    timeout = remaining if cap_s is None else min(remaining, cap_s)
    try:
        return await asyncio.wait_for(awaitable, timeout=max(0.001, timeout))
    except asyncio.TimeoutError as exc:
        raise AgentTimeoutError(f"{label} timed out after {timeout:.1f}s.") from exc


async def run_agent(
    config: AgentConfig,
    task: str,
    start_url: str | None,
    event_cb: EventCallback,
    headless: bool = True,
    timeout_s: int = 75,
) -> dict[str, Any]:
    run_started = time.perf_counter()
    deadline = run_started + max(1, timeout_s)
    history: list[dict[str, Any]] = []
    controller = BrowserController(headless=headless)
    status = "running"
    answer = ""
    steps = 0
    await event_cb(
        {
            "type": "agent_started",
            "agent_id": config.agent_id,
            "label": config.label,
            "badge": config.badge,
            "model": config.provider.model,
            "started_at": time.time(),
        }
    )
    try:
        await run_with_deadline(controller.start(start_url), deadline, "Browser startup", BROWSER_START_TIMEOUT_S)
        initial_snapshot = await run_with_deadline(
            controller.snapshot(),
            deadline,
            "Initial browser snapshot",
            BROWSER_SNAPSHOT_TIMEOUT_S,
        )
        plan = build_fast_plan(task, initial_snapshot)
        await event_cb(
            {
                "type": "plan",
                "agent_id": config.agent_id,
                "items": plan["steps"],
                "subtasks": plan["subtasks"],
                "strategy": plan["strategy"],
            }
        )
        await run_with_deadline(
            emit_screenshot(config, controller, event_cb),
            deadline,
            "Initial screenshot",
            BROWSER_SCREENSHOT_TIMEOUT_S,
        )
        while True:
            if time.perf_counter() >= deadline:
                status = "timeout"
                answer = f"Stopped after {timeout_s}s because the browser agent timed out."
                break
            step_index = steps + 1
            steps = step_index
            snapshot = await run_with_deadline(
                controller.snapshot(),
                deadline,
                "Browser snapshot",
                BROWSER_SNAPSHOT_TIMEOUT_S,
            )
            decision = await run_with_deadline(
                config.provider.decide(task, snapshot, history),
                deadline,
                "Model decision",
                MODEL_DECISION_TIMEOUT_S,
            )
            action = normalize_action(decision.action)
            ok, reason = validate_runtime_action(action, task, snapshot)
            if not ok:
                raise ValueError(f"Provider returned invalid action: {reason}")
            action_event = {
                "type": "action",
                "agent_id": config.agent_id,
                "step": step_index,
                "action": action,
                "reason": action.get("reason", ""),
                "model": decision.model,
                "routed_from": decision.routed_from,
                "route_kind": decision.route_kind or infer_route_kind(config.agent_id, decision.routed_from),
                "route_label": decision.route_label,
                "routing_reasons": decision.routing_reasons or [],
                "decision_latency_ms": decision.latency_ms,
                "llm_latency_ms": decision.latency_ms,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "elapsed_ms": elapsed_ms(run_started),
            }
            await event_cb(action_event)
            history.append(action_event)
            if action["action"] == "finish":
                answer = action.get("text", "")
                status = "blocked" if is_blocked_answer(answer) else "completed"
                break
            try:
                result = await run_with_deadline(
                    controller.apply_action(action),
                    deadline,
                    "Browser action",
                    BROWSER_ACTION_TIMEOUT_S,
                )
                failed = False
            except Exception as step_exc:
                result = f"Action failed: {step_exc}"
                failed = True
            observation_event = {
                "type": "observation",
                "agent_id": config.agent_id,
                "step": step_index,
                "message": result,
                "failed": failed,
                "elapsed_ms": elapsed_ms(run_started),
            }
            await event_cb(observation_event)
            history.append(observation_event)
            await run_with_deadline(
                emit_screenshot(config, controller, event_cb),
                deadline,
                "Screenshot",
                BROWSER_SCREENSHOT_TIMEOUT_S,
            )
    except AgentTimeoutError as exc:
        status = "timeout"
        answer = str(exc)
        await event_cb(
            {
                "type": "error",
                "agent_id": config.agent_id,
                "message": answer,
                "elapsed_ms": elapsed_ms(run_started),
            }
        )
    except Exception as exc:
        status = "error"
        answer = str(exc)
        await event_cb(
            {
                "type": "error",
                "agent_id": config.agent_id,
                "message": answer,
                "elapsed_ms": elapsed_ms(run_started),
            }
        )
    finally:
        await controller.close()

    result = {
        "type": "agent_finished",
        "agent_id": config.agent_id,
        "label": config.label,
        "status": status,
        "answer": answer,
        "steps": steps,
        "elapsed_ms": elapsed_ms(run_started),
    }
    await event_cb(result)
    return result


async def run_benchmark(
    task: str,
    start_url: str | None,
    agents: list[AgentConfig],
    event_cb: EventCallback,
    headless: bool = True,
    timeout_s: int = 75,
) -> list[dict[str, Any]]:
    await event_cb(
        {
            "type": "run_started",
            "run_id": str(uuid.uuid4()),
            "task": task,
            "start_url": start_url or "",
            "agent_count": len(agents),
            "started_at": time.time(),
        }
    )
    results = await asyncio.gather(
        *(
            run_agent(
                agent,
                task,
                start_url,
                event_cb,
                headless=headless,
                timeout_s=timeout_s,
            )
            for agent in agents
        )
    )
    await event_cb({"type": "run_finished", "results": results, "finished_at": time.time()})
    return results


async def emit_screenshot(config: AgentConfig, controller: BrowserController, event_cb: EventCallback) -> None:
    snapshot = await controller.snapshot()
    await event_cb(
        {
            "type": "screenshot",
            "agent_id": config.agent_id,
            "url": snapshot["url"],
            "title": snapshot["title"],
            "image": await controller.screenshot_data_url(),
            "elements": len(snapshot["elements"]),
        }
    )


def infer_route_kind(agent_id: str, routed_from: str | None) -> str:
    route = (routed_from or "").lower()
    if route.startswith("fallback"):
        return "llm"
    if route == "browser-safety":
        return "safety"
    if agent_id in {"openai", "claude"}:
        return "llm"
    if route:
        return "slm"
    return "unknown"


def build_agent_configs(
    agent_ids: list[str],
    provider_keys: dict[str, str] | None = None,
    allow_server_keys: bool = True,
) -> list[AgentConfig]:
    provider_keys = provider_keys or {}
    openai_key = provider_keys.get("openai") or (os.getenv("OPENAI_API_KEY") if allow_server_keys else None)
    claude_key = provider_keys.get("claude") or (os.getenv("ANTHROPIC_API_KEY") if allow_server_keys else None)
    openai = BrowserSafetyProvider(OpenAIProvider(api_key=openai_key))
    claude = BrowserSafetyProvider(AnthropicProvider(api_key=claude_key))
    local_providers: list[ActionProvider] = [HeuristicProvider()]
    if os.getenv("OLLAMA_MODEL"):
        local_providers.append(OllamaProvider())
    cascade_fallback: ActionProvider = openai if openai.api_key else claude
    if not getattr(cascade_fallback, "api_key", None):
        cascade_fallback = UnavailableProvider(
            "fallback",
            "The cascade local policy could not finish confidently, and no fallback API key is configured.",
        )
    registry = {
        "cascade": AgentConfig(
            "cascade",
            "SLM Cascade",
            CascadeProvider(
                local_providers,
                cascade_fallback,
                confidence_threshold=float(os.getenv("SLM_ROUTER_CONFIDENCE_THRESHOLD", "0.52")),
                finish_confidence_threshold=float(os.getenv("SLM_ROUTER_FINISH_CONFIDENCE_THRESHOLD", "0.84")),
            ),
            "local-first",
        ),
        "openai": AgentConfig("openai", "OpenAI", openai, "frontier"),
        "claude": AgentConfig("claude", "Claude", claude, "frontier"),
    }
    return [registry[agent_id] for agent_id in agent_ids if agent_id in registry]


def provider_status() -> dict[str, Any]:
    return {
        "cascade": {
            "enabled": True,
            "model": "heuristic"
            + (f" + {os.getenv('OLLAMA_MODEL')}" if os.getenv("OLLAMA_MODEL") else "")
            + " -> "
            + (os.getenv("OPENAI_MODEL", "gpt-5.6-sol") if os.getenv("OPENAI_API_KEY") else os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5") if os.getenv("ANTHROPIC_API_KEY") else "unconfigured fallback"),
            "confidence_threshold": float(os.getenv("SLM_ROUTER_CONFIDENCE_THRESHOLD", "0.52")),
            "finish_confidence_threshold": float(os.getenv("SLM_ROUTER_FINISH_CONFIDENCE_THRESHOLD", "0.84")),
        },
        "openai": {
            "enabled": bool(os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
            "hint": "Set OPENAI_API_KEY to enable.",
        },
        "claude": {
            "enabled": bool(os.getenv("ANTHROPIC_API_KEY")),
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            "hint": "Set ANTHROPIC_API_KEY to enable.",
        },
    }


def build_model_prompt(task: str, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> str:
    recent = [
        {
            "type": item.get("type"),
            "step": item.get("step"),
            "action": item.get("action"),
            "observation": item.get("message"),
            "failed": item.get("failed"),
            "routed_from": item.get("routed_from"),
            "route_kind": item.get("route_kind"),
            "routing_reasons": item.get("routing_reasons"),
        }
        for item in history[-6:]
    ]
    elements = snapshot.get("elements", [])[:80]
    plan = build_fast_plan(task, snapshot)
    return json.dumps(
        {
            "task": task,
            "fast_plan": plan,
            "page": {
                "url": snapshot.get("url"),
                "title": snapshot.get("title"),
                "text": snapshot.get("text", ""),
                "headings": snapshot.get("headings", []),
                "elements": elements,
            },
            "recent_history": recent,
            "available_actions": {
                "goto": "Open a URL. Put the URL in text.",
                "click": "Click an element. Use target id, selector, or text.",
                "fill": "Fill an input. Use target id or selector, and put the value in text.",
                "press": "Press a keyboard key such as Enter.",
                "wait": "Wait briefly for dynamic content.",
                "finish": "End the task. Put final answer in text.",
            },
        },
        ensure_ascii=True,
    )


def build_fast_plan(task: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    explicit_url = find_url(task)
    domain = find_domain(task)
    search_query = clean_search_query(task) if wants_search(task.lower()) else ""
    click_target = extract_click_target(task) or ""
    subtasks = decompose_task(task, search_query)
    steps: list[str] = []
    if explicit_url:
        steps.append(f"Open {explicit_url}.")
    elif domain:
        steps.append(f"Open https://{domain}.")
    elif search_query:
        steps.append("Use a lighter search results page instead of Google/Bing.")
        steps.append(f"Search for: {search_query}.")
    else:
        steps.append("Inspect the current page and choose the most direct visible control.")
    if click_target:
        steps.append(f"Find and click a visible control matching: {click_target}.")
    if wants_answer(task.lower()):
        steps.append("Only finish after the page contains information that answers the prompt.")
    if is_blocked_page(snapshot):
        steps.append("The current page appears blocked; switch route instead of attempting CAPTCHA.")
    if is_error_page(snapshot):
        steps.append("The current page appears to be an error or not-found page; do not finish from it.")
    if needs_synthesis(task):
        steps.append("This task requires synthesis/recommendation, so local raw-text finish is not enough.")
    source_ready = source_ready_for_synthesis(task, snapshot)
    if source_ready:
        steps.append("The current source appears to contain enough evidence; synthesize now.")
    return {
        "strategy": "direct-url" if explicit_url or domain else "search-route" if search_query else "page-inspection",
        "explicit_url": explicit_url or "",
        "domain": domain or "",
        "search_query": search_query,
        "click_target": click_target,
        "expects_answer": wants_answer(task.lower()),
        "blocked_page": is_blocked_page(snapshot),
        "error_page": is_error_page(snapshot),
        "requires_synthesis": needs_synthesis(task),
        "source_ready": source_ready,
        "subtasks": subtasks,
        "steps": steps,
    }


def decompose_task(task: str, search_query: str) -> list[str]:
    subtasks = ["Normalize the user's request and identify the target outcome."]
    if search_query:
        subtasks.append(f"Find a credible source for: {search_query}.")
    elif find_url(task) or find_domain(task):
        subtasks.append("Open the named site or URL directly.")
    else:
        subtasks.append("Inspect the current page and identify the next useful control.")
    subtasks.append("Reject search snippets, CAPTCHA pages, not-found pages, and generic error pages.")
    if needs_synthesis(task):
        subtasks.append("Collect concrete candidates, constraints, and evidence from the source page.")
        subtasks.append("Synthesize a recommendation with a short reason and caveat.")
    elif wants_answer(task.lower()):
        subtasks.append("Extract the exact requested fact from the source page.")
    else:
        subtasks.append("Complete the requested browser action.")
    return subtasks


def choose_browser_safety_action(
    task: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not is_blocked_page(snapshot):
        return None
    next_search = next_search_url(task, history)
    if next_search:
        return {
            "action": "goto",
            "target": "",
            "selector": "",
            "text": next_search,
            "reason": "The page appears to be bot protection, so switching to a less captcha-prone route.",
            "confidence": 0.9,
        }
    return {
        "action": "finish",
        "target": "",
        "selector": "",
        "text": "Blocked by bot protection or CAPTCHA before the task could be completed.",
        "reason": "The page is blocked and no safer alternate route remains.",
        "confidence": 0.95,
    }


def choose_heuristic_action(
    task: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    lower_task = task.lower()
    current_url = snapshot.get("url", "")
    elements = snapshot.get("elements", [])
    page_text = snapshot.get("text", "")
    plan = build_fast_plan(task, snapshot)

    guarded = choose_browser_safety_action(task, snapshot, history)
    if guarded:
        return guarded
    if is_error_page(snapshot):
        return {
            "action": "wait",
            "target": "",
            "selector": "",
            "text": "",
            "reason": "The page appears to be an error or not-found page, so the local policy should not finish.",
            "confidence": 0.2,
        }

    if not history:
        explicit_url = find_url(task)
        if explicit_url and not same_url(current_url, explicit_url):
            return {
                "action": "goto",
                "target": "",
                "selector": "",
                "text": explicit_url,
                "reason": "The task names a specific URL, so opening it is the fastest first step.",
                "confidence": 0.95,
            }
        domain = find_domain(task)
        if domain:
            return {
                "action": "goto",
                "target": "",
                "selector": "",
                "text": f"https://{domain}",
                "reason": "The task names a web domain, so opening it directly is likely correct.",
                "confidence": 0.9,
            }
        if plan["search_query"]:
            return {
                "action": "goto",
                "target": "",
                "selector": "",
                "text": next_search_url(task, history) or search_url(plan["search_query"], "brave"),
                "reason": "The task needs web lookup, so using a lightweight search page to reduce bot protection.",
                "confidence": 0.86,
            }

    if page_text and wants_answer(lower_task) and history and not is_search_results_page(snapshot):
        return {
            "action": "finish",
            "target": "",
            "selector": "",
            "text": local_answer_from_page(task, snapshot),
            "reason": "The page has loaded information that answers the prompt.",
            "confidence": 0.88,
        }

    if wants_search(lower_task):
        if is_search_results_page(snapshot):
            result = first_search_result(elements)
            if result and not recently_clicked(history, result["id"]):
                result_url = search_result_url(result)
                if result_url:
                    return {
                        "action": "goto",
                        "target": "",
                        "selector": "",
                        "text": result_url,
                        "reason": "A search result URL is visible; opening it directly avoids a fragile click.",
                        "confidence": 0.83,
                    }
                return {
                    "action": "click",
                    "target": result["id"],
                    "selector": "",
                    "text": "",
                    "reason": "A search result is visible; opening it is more reliable than editing the search box.",
                    "confidence": 0.8,
                }
        search_input = first_matching_element(elements, ["search", "query", "q"], tags={"input", "textarea"})
        if search_input and not recently_filled(history, search_input["id"]):
            return {
                "action": "fill",
                "target": search_input["id"],
                "selector": "",
                "text": clean_search_query(task),
                "reason": "A search input is visible and the task asks to find information.",
                "confidence": 0.82,
            }
        if history and history[-1].get("action", {}).get("action") == "fill":
            return {
                "action": "press",
                "target": "",
                "selector": "",
                "text": "Enter",
                "reason": "Submit the filled search field.",
                "confidence": 0.82,
            }
    click_text = extract_click_target(task)
    if click_text:
        match = first_matching_element(elements, [click_text])
        if match:
            return {
                "action": "click",
                "target": match["id"],
                "selector": "",
                "text": "",
                "reason": f"The visible element appears to match '{click_text}'.",
                "confidence": 0.84,
            }

    return {
        "action": "wait",
        "target": "",
        "selector": "",
        "text": "",
        "reason": "No high-confidence local browser move matched the current page.",
        "confidence": 0.35,
    }


def normalize_action(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Action must be a JSON object.")
    action = str(raw.get("action", "")).strip().lower()
    normalized = {
        "action": action,
        "reason": str(raw.get("reason", "")).strip() or "No reason supplied.",
        "confidence": float(raw.get("confidence", 0)),
    }
    for key in ("target", "selector", "text"):
        if raw.get(key) is not None:
            normalized[key] = str(raw[key]).strip()
    return normalized


def validate_action(raw: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        action = normalize_action(raw)
    except (TypeError, ValueError):
        return False, "invalid_json_shape"
    kind = action.get("action")
    if kind not in ALLOWED_ACTIONS:
        return False, "unknown_action"
    if kind in TEXT_ACTIONS and not action.get("text") and kind != "press":
        return False, "missing_text"
    if kind in TARGET_ACTIONS and not (action.get("target") or action.get("selector") or action.get("text")):
        return False, "missing_target"
    if not 0 <= float(action.get("confidence", -1)) <= 1:
        return False, "invalid_confidence"
    return True, None


def validate_local_action(
    raw: dict[str, Any],
    task: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    ok, reason = validate_action(raw)
    if not ok:
        return ok, reason
    action = normalize_action(raw)
    if action["action"] == "finish":
        if is_blocked_page(snapshot) and "blocked by bot protection" not in action.get("text", "").lower():
            return False, "blocked_page"
        if is_error_page(snapshot):
            return False, "error_page"
        if wants_answer(task.lower()) and is_search_results_page(snapshot):
            return False, "search_result_not_source"
        if needs_synthesis(task):
            return False, "synthesis_required"
        if wants_answer(task.lower()) and not page_seems_relevant(task, snapshot):
            return False, "irrelevant_page"
        if wants_answer(task.lower()) and not has_meaningful_progress(history, snapshot):
            return False, "premature_finish"
        if answer_looks_empty(action.get("text", "")):
            return False, "empty_answer"
    if action["action"] == "wait" and count_recent_actions(history, "wait") >= 1:
        return False, "repeated_wait"
    return True, None


def validate_runtime_action(
    raw: dict[str, Any],
    task: str,
    snapshot: dict[str, Any],
) -> tuple[bool, str | None]:
    ok, reason = validate_action(raw)
    if not ok:
        return ok, reason
    action = normalize_action(raw)
    if action["action"] != "finish":
        return True, None
    if is_blocked_page(snapshot) and not is_blocked_answer(action.get("text", "")):
        return False, "blocked_page"
    if is_error_page(snapshot):
        return False, "error_page"
    if wants_answer(task.lower()) and is_search_results_page(snapshot):
        return False, "search_result_not_source"
    if answer_looks_empty(action.get("text", "")):
        return False, "empty_answer"
    return True, None


def local_answer_from_page(task: str, snapshot: dict[str, Any]) -> str:
    lower_task = task.lower()
    title = str(snapshot.get("title", "")).strip()
    headings = [str(item).strip() for item in snapshot.get("headings", []) if str(item).strip()]
    if "title" in lower_task and title:
        return title
    if "heading" in lower_task and headings:
        return headings[0]
    if any(word in lower_task for word in ("url", "link")) and snapshot.get("url"):
        return str(snapshot["url"])
    return compact_text(snapshot.get("text", ""), 600)


def has_meaningful_progress(history: list[dict[str, Any]], snapshot: dict[str, Any]) -> bool:
    if snapshot.get("url") and snapshot["url"] != "about:blank":
        return True
    return any(
        item.get("type") == "action" and item.get("action", {}).get("action") in {"goto", "click", "fill", "press"}
        for item in history
    )


def answer_looks_empty(text: str) -> bool:
    cleaned = compact_text(text, 80).lower()
    return not cleaned or cleaned in {"n/a", "none", "unknown", "no answer"}


def is_blocked_answer(text: str) -> bool:
    return "blocked by bot protection" in text.lower() or "captcha" in text.lower()


def is_dead_end(history: list[dict[str, Any]]) -> bool:
    if repeated_failures(history):
        return True
    recent_actions = [
        item.get("action", {}).get("action")
        for item in history[-4:]
        if item.get("type") == "action"
    ]
    return len(recent_actions) >= 2 and len(set(recent_actions[-2:])) == 1 and recent_actions[-1] in {"wait", "click"}


def repeated_failures(history: list[dict[str, Any]]) -> bool:
    recent = [item for item in history[-4:] if item.get("type") == "observation"]
    return len(recent) >= 2 and all(item.get("failed") for item in recent[-2:])


def count_recent_actions(history: list[dict[str, Any]], action: str) -> int:
    count = 0
    for item in reversed(history[-4:]):
        if item.get("type") != "action":
            continue
        if item.get("action", {}).get("action") == action:
            count += 1
        else:
            break
    return count


def is_blocked_page(snapshot: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(snapshot.get(key, ""))
        for key in ("url", "title", "text")
    ).lower()
    return any(
        phrase in haystack
        for phrase in (
            "unusual traffic",
            "captcha",
            "not a robot",
            "verify you are human",
            "are you a human",
            "bot protection",
            "automated queries",
            "automated traffic",
            "checking if the site connection is secure",
            "attention required",
        )
    )


def is_error_page(snapshot: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(snapshot.get(key, ""))
        for key in ("url", "title", "text")
    ).lower()
    return any(
        phrase in haystack
        for phrase in (
            "oops! we can't find this page",
            "we can't find this page",
            "cannot find this page",
            "can't find this page",
            "page not found",
            "404 not found",
            "404 error",
            "not found",
            "doesn't exist",
            "page is unavailable",
            "this page is unavailable",
            "access denied",
            "forbidden",
            "server error",
            "temporarily unavailable",
        )
    )


def is_search_results_page(snapshot: dict[str, Any]) -> bool:
    url = snapshot.get("url", "").lower()
    title = snapshot.get("title", "").lower()
    return any(
        marker in url
        for marker in (
            "duckduckgo.com/html",
            "duckduckgo.com/?q=",
            "search.brave.com/search",
            "google.com/search",
            "bing.com/search",
            "ecosia.org/search",
        )
    ) or "search results" in title


def needs_synthesis(task: str) -> bool:
    lowered = task.lower()
    return any(
        phrase in lowered
        for phrase in (
            "best",
            "recommend",
            "recommendation",
            "which",
            "compare",
            "versus",
            " vs ",
            "should i buy",
            "should i get",
            "pair for",
            "good for",
            "amateur",
            "beginner",
            "mi/week",
            "miles/week",
            "miles per week",
        )
    )


def page_seems_relevant(task: str, snapshot: dict[str, Any]) -> bool:
    if not wants_answer(task.lower()):
        return True
    if is_error_page(snapshot) or is_blocked_page(snapshot):
        return False
    haystack = " ".join(
        str(snapshot.get(key, ""))
        for key in ("url", "title", "text")
    ).lower()
    terms = content_terms(task)
    if not terms:
        return True
    hits = sum(1 for term in terms if term in haystack)
    return hits >= min(2, len(terms))


def source_ready_for_synthesis(task: str, snapshot: dict[str, Any]) -> bool:
    if not needs_synthesis(task):
        return False
    if is_search_results_page(snapshot) or is_error_page(snapshot) or is_blocked_page(snapshot):
        return False
    text = str(snapshot.get("text", ""))
    if len(text) < 450:
        return False
    return page_seems_relevant(task, snapshot)


def content_terms(task: str) -> list[str]:
    normalized = normalize_query_text(task)
    raw_terms = re.findall(r"[a-z0-9][a-z0-9-]{2,}", normalized.lower())
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "what",
        "who",
        "when",
        "where",
        "best",
        "give",
        "tell",
        "find",
        "search",
        "look",
        "scrape",
        "report",
        "title",
        "heading",
        "page",
        "pair",
        "shoe",
        "shoes",
    }
    terms = []
    for term in raw_terms:
        if term in stopwords or term in terms:
            continue
        terms.append(term)
    return terms[:8]


def search_url(query: str, provider: str) -> str:
    encoded = quote_plus(query)
    if provider == "brave":
        return f"https://search.brave.com/search?q={encoded}"
    if provider == "ecosia":
        return f"https://www.ecosia.org/search?q={encoded}"
    return f"https://duckduckgo.com/html/?q={encoded}"


def next_search_url(task: str, history: list[dict[str, Any]]) -> str | None:
    if not wants_search(task.lower()) and not wants_answer(task.lower()):
        return None
    query = clean_search_query(task)
    tried_text = json.dumps(history).lower()
    for provider in ("brave", "duckduckgo-html", "ecosia"):
        url = search_url(query, provider)
        if provider not in tried_text and url.lower() not in tried_text:
            return url
    return None


def first_search_result(elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    for element in elements:
        href = str(element.get("href", "")).lower()
        label = str(element.get("label", "")).strip()
        if element.get("tag") != "a" or not href or not label:
            continue
        if "javascript:" in href or href.endswith("#"):
            continue
        if "search.brave.com" in href:
            continue
        if "ecosia.org" in href and "/search" in href:
            continue
        if "duckduckgo.com" in href and "uddg=" not in href:
            continue
        if any(blocked in href for blocked in ("google.com", "bing.com")):
            continue
        return element
    return None


def search_result_url(element: dict[str, Any]) -> str:
    href = str(element.get("href", "")).strip()
    if not href:
        return ""
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and "uddg" in parsed.query:
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target)
    return href


def recently_clicked(history: list[dict[str, Any]], target_id: str) -> bool:
    for item in history[-5:]:
        action = item.get("action", {})
        if action.get("action") == "click" and action.get("target") == target_id:
            return True
    return False


def parse_action(raw: str) -> dict[str, Any]:
    try:
        return normalize_action(json.loads(raw))
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = raw.find("{")
        if start == -1:
            raise
        action, _ = decoder.raw_decode(raw[start:])
        return normalize_action(action)


def extract_openai_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and "text" in content:
                chunks.append(content["text"])
            elif "text" in content:
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def extract_openai_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return input_tokens, output_tokens


def extract_anthropic_action(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    text_chunks: list[str] = []
    for item in data.get("content", []):
        if item.get("type") == "tool_use" and item.get("name") == "browser_action":
            raw = json.dumps(item.get("input", {}))
            return item.get("input", {}), raw
        if item.get("type") == "text":
            text_chunks.append(item.get("text", ""))
    raw = "\n".join(text_chunks).strip()
    return parse_action(raw), raw


def extract_anthropic_usage(data: dict[str, Any]) -> tuple[int, int]:
    usage = data.get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def find_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]\"']+", text)
    return match.group(0).rstrip(".,") if match else None


def find_domain(text: str) -> str | None:
    match = re.search(r"\b((?:[a-z0-9-]+\.)+(?:com|org|net|edu|gov|io|ai|co|dev))\b", text, re.I)
    return match.group(1).lower().rstrip(".,") if match else None


def same_url(a: str, b: str) -> bool:
    return ensure_url(a).rstrip("/") == ensure_url(b).rstrip("/")


def ensure_url(url: str) -> str:
    url = url.strip()
    if not url:
        return "about:blank"
    parsed = urlparse(url)
    if parsed.scheme:
        return url
    return f"https://{url}"


def wants_search(task: str) -> bool:
    return any(word in task for word in ("search", "find", "look up", "google", "research", "scrape", "browse"))


def wants_answer(task: str) -> bool:
    return any(
        word in task
        for word in (
            "what",
            "who",
            "when",
            "where",
            "summarize",
            "find",
            "look up",
            "tell me",
            "report",
            "heading",
            "title",
            "best",
            "recommend",
            "recommendation",
            "which",
            "compare",
        )
    )


def normalize_query_text(task: str) -> str:
    query = task
    replacements = {
        "runnning": "running",
        "shoee": "shoe",
        "shooe": "shoe",
        "mi/week": "miles per week",
    }
    for source, target in replacements.items():
        query = re.sub(source, target, query, flags=re.I)
    query = re.sub(r"https?://\S+", "", query)
    query = re.sub(
        r"\b(search for|find|look up|google|research|scrape|browse|crawl|tell me|give me|report|show me)\b",
        " ",
        query,
        flags=re.I,
    )
    query = re.sub(r"\b(and me|for me|to me)\b", " ", query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip()
    return query


def clean_search_query(task: str) -> str:
    query = normalize_query_text(task)
    return compact_text(query.strip(" :.-") or task, 220)


def extract_click_target(task: str) -> str | None:
    match = re.search(r"\bclick(?: on)? ['\"]?([^'\".]+)", task, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bopen ['\"]?([^'\".]+)", task, re.I)
    return match.group(1).strip() if match else None


def first_matching_element(
    elements: list[dict[str, Any]],
    needles: list[str],
    tags: set[str] | None = None,
) -> dict[str, Any] | None:
    lowered = [needle.lower() for needle in needles if needle]
    for element in elements:
        if tags and element.get("tag") not in tags:
            continue
        haystack = " ".join(
            str(element.get(key, ""))
            for key in ("label", "placeholder", "type", "role", "href", "value")
        ).lower()
        if any(needle in haystack for needle in lowered):
            return element
    return None


def recently_filled(history: list[dict[str, Any]], target_id: str) -> bool:
    for item in history[-3:]:
        action = item.get("action", {})
        if action.get("action") == "fill" and action.get("target") == target_id:
            return True
    return False


def compact_text(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
