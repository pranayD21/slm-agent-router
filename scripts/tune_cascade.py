from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from slm_agent_router.web_benchmark import (
    AgentConfig,
    BrowserSafetyProvider,
    CascadeProvider,
    HeuristicProvider,
    OpenAIProvider,
    AnthropicProvider,
    extract_openai_text,
    extract_openai_usage,
    run_agent,
)


TASKS: list[dict[str, str]] = [
    {
        "id": "example-heading",
        "prompt": "Go to https://example.com and report the page heading.",
        "rubric": "The answer should identify the page heading as Example Domain.",
    },
    {
        "id": "iana-reserved",
        "prompt": "Go to https://www.iana.org/domains/reserved and report what the page is about.",
        "rubric": "The answer should say the page is about IANA-managed reserved domains or example domains.",
    },
    {
        "id": "python-downloads",
        "prompt": "Find the official Python downloads page and report the URL you reached.",
        "rubric": "The answer should point to an official python.org downloads URL.",
    },
    {
        "id": "mdn-fetch",
        "prompt": "Find the official MDN Fetch API page and report the page title.",
        "rubric": "The answer should identify an official MDN page about Fetch API or Using Fetch.",
    },
    {
        "id": "running-shoes",
        "prompt": "scrape runnning shoe brands and me the best pair of shoe for an amateur running 75 mi/week",
        "rubric": "The answer should use a real source, name credible running-shoe brands or models, recommend one pair, and mention that 75 miles per week is high volume.",
    },
]

VARIANTS: list[dict[str, float | str]] = [
    {"name": "conservative", "confidence": 0.58, "finish_confidence": 0.86},
    {"name": "balanced", "confidence": 0.52, "finish_confidence": 0.84},
    {"name": "fast", "confidence": 0.45, "finish_confidence": 0.80},
    {"name": "guarded-fast", "confidence": 0.48, "finish_confidence": 0.86},
]

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "passed": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["passed", "score", "reason"],
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run cascade tuning epochs and judge answers with an LLM.")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", default="benchmark_runs/cascade_tuning_latest.json")
    parser.add_argument("--judge-model", default=os.getenv("SLM_ROUTER_JUDGE_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.6-sol"))
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    trials: list[dict[str, Any]] = []
    started_at = time.time()

    for epoch in range(args.epochs):
        variant = VARIANTS[epoch % len(VARIANTS)]
        task = TASKS[(epoch // len(VARIANTS)) % len(TASKS)]
        print(f"[{epoch + 1:02d}/{args.epochs}] {variant['name']} :: {task['id']}", flush=True)
        trial = await run_trial(epoch + 1, variant, task, args.timeout, args.judge_model)
        trials.append(trial)
        print(
            f"  status={trial['status']} score={trial['judge']['score']:.2f} "
            f"elapsed={trial['elapsed_ms']}ms llm_calls={trial['llm_calls']} tokens={trial['llm_tokens_total']}",
            flush=True,
        )

    summary = summarize_trials(trials)
    report = {
        "started_at": started_at,
        "finished_at": time.time(),
        "epochs": args.epochs,
        "timeout_s": args.timeout,
        "judge_model": args.judge_model,
        "tasks": TASKS,
        "variants": VARIANTS,
        "summary": summary,
        "best_variant": best_variant(summary),
        "trials": trials,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {output}")
    print(json.dumps(report["best_variant"], indent=2))
    return 0


async def run_trial(
    epoch: int,
    variant: dict[str, float | str],
    task: dict[str, str],
    timeout_s: int,
    judge_model: str,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    provider = CascadeProvider(
        [HeuristicProvider()],
        fallback_provider(),
        confidence_threshold=float(variant["confidence"]),
        finish_confidence_threshold=float(variant["finish_confidence"]),
    )
    config = AgentConfig(
        "cascade",
        f"Cascade {variant['name']}",
        provider,
        str(variant["name"]),
    )
    result = await run_agent(config, task["prompt"], None, emit, headless=True, timeout_s=timeout_s)
    judge = await judge_answer(task, result, events, judge_model)
    action_events = [event for event in events if event.get("type") == "action"]
    input_tokens = sum(int(event.get("input_tokens") or 0) for event in action_events)
    output_tokens = sum(int(event.get("output_tokens") or 0) for event in action_events)
    return {
        "epoch": epoch,
        "variant": variant["name"],
        "task_id": task["id"],
        "prompt": task["prompt"],
        "status": result.get("status"),
        "answer": result.get("answer", ""),
        "steps": result.get("steps", 0),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "llm_calls": sum(1 for event in action_events if event.get("route_kind") == "llm"),
        "slm_calls": sum(1 for event in action_events if event.get("route_kind") == "slm"),
        "llm_input_tokens": input_tokens,
        "llm_output_tokens": output_tokens,
        "llm_tokens_total": input_tokens + output_tokens,
        "judge": judge,
        "route_trace": [
            {
                "step": event.get("step"),
                "action": (event.get("action") or {}).get("action"),
                "route_kind": event.get("route_kind"),
                "route_label": event.get("route_label"),
                "routing_reasons": event.get("routing_reasons"),
            }
            for event in action_events
        ],
        "visited_urls": visited_urls(events),
    }


def fallback_provider():
    if os.getenv("OPENAI_API_KEY"):
        return BrowserSafetyProvider(OpenAIProvider())
    return BrowserSafetyProvider(AnthropicProvider())


async def judge_answer(
    task: dict[str, str],
    result: dict[str, Any],
    events: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        return heuristic_judge(task, result)

    prompt = json.dumps(
        {
            "task": task["prompt"],
            "rubric": task["rubric"],
            "status": result.get("status"),
            "answer": result.get("answer", ""),
            "visited_urls": visited_urls(events),
            "actions": [
                {
                    "step": event.get("step"),
                    "action": (event.get("action") or {}).get("action"),
                    "route_kind": event.get("route_kind"),
                }
                for event in events
                if event.get("type") == "action"
            ],
        },
        ensure_ascii=True,
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Grade whether a browser agent's final answer satisfies the task. "
                    "Be strict about wrong pages, empty answers, blocked pages, and unsupported recommendations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "judge_result",
                "strict": True,
                "schema": JUDGE_SCHEMA,
            }
        },
        "max_output_tokens": 320,
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')}/responses",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        judged = json.loads(extract_openai_text(data))
        input_tokens, output_tokens = extract_openai_usage(data)
        return {
            "passed": bool(judged["passed"]),
            "score": float(judged["score"]),
            "reason": str(judged["reason"]),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    except Exception as exc:
        fallback = heuristic_judge(task, result)
        fallback["reason"] = f"LLM judge failed ({exc}); heuristic fallback: {fallback['reason']}"
        return fallback


def heuristic_judge(task: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    answer = str(result.get("answer", "")).lower()
    prompt = task["prompt"].lower()
    passed = result.get("status") == "completed" and bool(answer.strip())
    if "example.com" in prompt:
        passed = passed and "example domain" in answer
    if "python" in prompt:
        passed = passed and "python.org" in answer
    if "running" in prompt:
        passed = passed and any(term in answer for term in ("brooks", "nike", "saucony", "adidas", "new balance"))
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "Heuristic judge result.",
        "input_tokens": 0,
        "output_tokens": 0,
    }


def summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        by_variant.setdefault(str(trial["variant"]), []).append(trial)
    summary: dict[str, Any] = {}
    for name, rows in by_variant.items():
        scores = [float(row["judge"]["score"]) for row in rows]
        elapsed = [int(row["elapsed_ms"]) for row in rows]
        llm_tokens = [int(row["llm_tokens_total"]) for row in rows]
        judge_tokens = [
            int(row["judge"].get("input_tokens") or 0) + int(row["judge"].get("output_tokens") or 0)
            for row in rows
        ]
        pass_rate = sum(1 for row in rows if row["judge"]["passed"]) / len(rows)
        avg_score = sum(scores) / len(scores)
        avg_elapsed_ms = sum(elapsed) / len(elapsed)
        avg_llm_tokens = sum(llm_tokens) / len(llm_tokens)
        avg_judge_tokens = sum(judge_tokens) / len(judge_tokens)
        summary[name] = {
            "trials": len(rows),
            "pass_rate": round(pass_rate, 4),
            "avg_score": round(avg_score, 4),
            "median_elapsed_ms": int(statistics.median(elapsed)),
            "avg_elapsed_ms": int(avg_elapsed_ms),
            "avg_llm_calls": round(sum(int(row["llm_calls"]) for row in rows) / len(rows), 2),
            "avg_slm_calls": round(sum(int(row["slm_calls"]) for row in rows) / len(rows), 2),
            "avg_llm_tokens": int(avg_llm_tokens),
            "avg_judge_tokens": int(avg_judge_tokens),
            "balance_score": round(balance_score(avg_score, pass_rate, avg_elapsed_ms, avg_llm_tokens), 3),
        }
    return summary


def balance_score(avg_score: float, pass_rate: float, avg_elapsed_ms: float, avg_llm_tokens: float) -> float:
    return (avg_score * 700) + (pass_rate * 300) - (avg_elapsed_ms / 120) - (avg_llm_tokens / 220)


def best_variant(summary: dict[str, Any]) -> dict[str, Any]:
    name, metrics = max(summary.items(), key=lambda item: item[1]["balance_score"])
    settings = next(variant for variant in VARIANTS if variant["name"] == name)
    return {"name": name, "settings": settings, "metrics": metrics}


def visited_urls(events: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for event in events:
        if event.get("type") != "screenshot":
            continue
        url = str(event.get("url") or "")
        if url and url not in urls:
            urls.append(url)
    return urls[-8:]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
