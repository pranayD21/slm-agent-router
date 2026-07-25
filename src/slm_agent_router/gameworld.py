from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


MODEL_LABELS = {
    "cascade": "SLM Cascade",
    "openai": "OpenAI Agent",
    "claude": "Claude Agent",
}


DEMO_REPORT: dict[str, Any] = {
    "benchmark": "GameWorld",
    "mode": "demo",
    "source": "Bundled normalized sample. Set SLM_ROUTER_GAMEWORLD_RESULTS to a GameWorld JSON report for real runs.",
    "summary": {
        "tasks": 40,
        "games": 8,
        "interfaces": ["computer-use", "semantic-action"],
        "winner": "cascade",
    },
    "models": [
        {
            "id": "cascade",
            "label": "SLM Cascade",
            "pass_rate": 0.68,
            "avg_score": 72,
            "median_time_s": 18.4,
            "avg_tokens": 3720,
            "estimated_cost_usd": 1.42,
            "cost_per_success_usd": 0.052,
            "valid_action_rate": 0.91,
            "wins": 27,
            "tasks": 40,
            "slm_actions": 248,
            "llm_actions": 91,
        },
        {
            "id": "openai",
            "label": "OpenAI Agent",
            "pass_rate": 0.74,
            "avg_score": 78,
            "median_time_s": 25.9,
            "avg_tokens": 5980,
            "estimated_cost_usd": 3.86,
            "cost_per_success_usd": 0.130,
            "valid_action_rate": 0.94,
            "wins": 30,
            "tasks": 40,
            "slm_actions": 0,
            "llm_actions": 412,
        },
        {
            "id": "claude",
            "label": "Claude Agent",
            "pass_rate": 0.71,
            "avg_score": 76,
            "median_time_s": 28.7,
            "avg_tokens": 6410,
            "estimated_cost_usd": 4.21,
            "cost_per_success_usd": 0.148,
            "valid_action_rate": 0.93,
            "wins": 28,
            "tasks": 40,
            "slm_actions": 0,
            "llm_actions": 428,
        },
    ],
    "games": [
        {
            "name": "2048",
            "genre": "Puzzle",
            "task": "Reach a 512 tile",
            "scores": {"cascade": 0.88, "openai": 0.90, "claude": 0.87},
            "cost_usd": {"cascade": 0.018, "openai": 0.046, "claude": 0.052},
        },
        {
            "name": "Baba Is You",
            "genre": "Puzzle",
            "task": "Solve a rule-shift level",
            "scores": {"cascade": 0.58, "openai": 0.68, "claude": 0.66},
            "cost_usd": {"cascade": 0.054, "openai": 0.121, "claude": 0.136},
        },
        {
            "name": "Pac-Man",
            "genre": "Arcade",
            "task": "Clear dots while avoiding ghosts",
            "scores": {"cascade": 0.62, "openai": 0.70, "claude": 0.69},
            "cost_usd": {"cascade": 0.041, "openai": 0.104, "claude": 0.116},
        },
        {
            "name": "Super Mario",
            "genre": "Platformer",
            "task": "Reach the flag",
            "scores": {"cascade": 0.57, "openai": 0.63, "claude": 0.61},
            "cost_usd": {"cascade": 0.048, "openai": 0.126, "claude": 0.139},
        },
        {
            "name": "Slay the Spire",
            "genre": "Strategy",
            "task": "Win an early combat",
            "scores": {"cascade": 0.76, "openai": 0.82, "claude": 0.80},
            "cost_usd": {"cascade": 0.033, "openai": 0.093, "claude": 0.101},
        },
        {
            "name": "Minecraft",
            "genre": "Sandbox",
            "task": "Collect wood and craft planks",
            "scores": {"cascade": 0.71, "openai": 0.75, "claude": 0.73},
            "cost_usd": {"cascade": 0.062, "openai": 0.157, "claude": 0.171},
        },
        {
            "name": "Street Fighter III",
            "genre": "Fighting",
            "task": "Win a short round",
            "scores": {"cascade": 0.52, "openai": 0.57, "claude": 0.56},
            "cost_usd": {"cascade": 0.029, "openai": 0.081, "claude": 0.087},
        },
        {
            "name": "Temple Run 2",
            "genre": "Runner",
            "task": "Survive 90 seconds",
            "scores": {"cascade": 0.79, "openai": 0.84, "claude": 0.82},
            "cost_usd": {"cascade": 0.024, "openai": 0.066, "claude": 0.074},
        },
    ],
    "traces": [
        {"model": "cascade", "label": "SLM observe", "start": 0, "duration": 9, "kind": "slm"},
        {"model": "cascade", "label": "LLM plan", "start": 9, "duration": 7, "kind": "llm"},
        {"model": "cascade", "label": "SLM actions", "start": 16, "duration": 18, "kind": "slm"},
        {"model": "cascade", "label": "LLM recover", "start": 34, "duration": 8, "kind": "llm"},
        {"model": "openai", "label": "Plan", "start": 0, "duration": 13, "kind": "llm"},
        {"model": "openai", "label": "Act", "start": 13, "duration": 22, "kind": "llm"},
        {"model": "openai", "label": "Reflect", "start": 35, "duration": 11, "kind": "llm"},
        {"model": "claude", "label": "Plan", "start": 0, "duration": 15, "kind": "llm"},
        {"model": "claude", "label": "Act", "start": 15, "duration": 24, "kind": "llm"},
        {"model": "claude", "label": "Recover", "start": 39, "duration": 10, "kind": "llm"},
    ],
}


def gameworld_report() -> dict[str, Any]:
    configured = os.getenv("SLM_ROUTER_GAMEWORLD_RESULTS", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return normalize_report(json.loads(path.read_text(encoding="utf-8")), source=str(path))
    default_path = Path("benchmark_runs/gameworld_results.json")
    if default_path.exists():
        return normalize_report(json.loads(default_path.read_text(encoding="utf-8")), source=str(default_path))
    return DEMO_REPORT


def normalize_report(raw: dict[str, Any], source: str) -> dict[str, Any]:
    if "models" in raw and "games" in raw:
        report = dict(raw)
        report.setdefault("benchmark", "GameWorld")
        report.setdefault("mode", "imported")
        report["source"] = source
        return report
    runs = raw.get("runs") or raw.get("trials") or []
    models = summarize_models(runs)
    games = summarize_games(runs)
    return {
        "benchmark": "GameWorld",
        "mode": "imported",
        "source": source,
        "summary": {
            "tasks": len(runs),
            "games": len(games),
            "interfaces": sorted({str(run.get("interface", "unknown")) for run in runs}),
            "winner": max(models, key=lambda row: row["pass_rate"])["id"] if models else "",
        },
        "models": models,
        "games": games,
        "traces": raw.get("traces", []),
    }


def summarize_models(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in sorted({str(run.get("model") or run.get("agent") or "") for run in runs if run.get("model") or run.get("agent")}):
        model_runs = [run for run in runs if str(run.get("model") or run.get("agent")) == model_id]
        tasks = len(model_runs)
        wins = sum(1 for run in model_runs if bool(run.get("passed") or run.get("success")))
        total_cost = sum(float(run.get("estimated_cost_usd") or run.get("cost_usd") or 0) for run in model_runs)
        avg_tokens = sum(int(run.get("tokens") or run.get("total_tokens") or 0) for run in model_runs) / max(1, tasks)
        median_time = sorted(float(run.get("elapsed_s") or run.get("time_s") or 0) for run in model_runs)[tasks // 2] if tasks else 0
        rows.append(
            {
                "id": model_id,
                "label": MODEL_LABELS.get(model_id, model_id),
                "pass_rate": wins / max(1, tasks),
                "avg_score": round(sum(float(run.get("score") or 0) for run in model_runs) / max(1, tasks), 3),
                "median_time_s": median_time,
                "avg_tokens": int(avg_tokens),
                "estimated_cost_usd": round(total_cost, 4),
                "cost_per_success_usd": round(total_cost / max(1, wins), 4),
                "valid_action_rate": round(sum(float(run.get("valid_action_rate") or 0) for run in model_runs) / max(1, tasks), 3),
                "wins": wins,
                "tasks": tasks,
                "slm_actions": sum(int(run.get("slm_actions") or 0) for run in model_runs),
                "llm_actions": sum(int(run.get("llm_actions") or 0) for run in model_runs),
            }
        )
    return rows


def summarize_games(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for game in sorted({str(run.get("game") or "Unknown") for run in runs}):
        game_runs = [run for run in runs if str(run.get("game") or "Unknown") == game]
        scores: dict[str, float] = {}
        cost_usd: dict[str, float] = {}
        for model_id in sorted({str(run.get("model") or run.get("agent") or "") for run in game_runs}):
            rows = [run for run in game_runs if str(run.get("model") or run.get("agent")) == model_id]
            scores[model_id] = round(sum(float(run.get("score") or int(bool(run.get("passed") or run.get("success")))) for run in rows) / max(1, len(rows)), 3)
            cost_usd[model_id] = round(sum(float(run.get("estimated_cost_usd") or run.get("cost_usd") or 0) for run in rows), 4)
        games.append(
            {
                "name": game,
                "genre": str(game_runs[0].get("genre") or "Game"),
                "task": str(game_runs[0].get("task") or "GameWorld task"),
                "scores": scores,
                "cost_usd": cost_usd,
            }
        )
    return games
