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


def demo_report() -> dict[str, Any]:
    return {
    "benchmark": "Web UI Benchmarks",
    "mode": "demo",
    "source": "Bundled normalized sample. Set SLM_ROUTER_WEBUI_RESULTS to a benchmark JSON report for real runs.",
    "summary": {
        "tasks": 96,
        "suites": 4,
        "winner": "cascade",
    },
    "models": [
        {
            "id": "cascade",
            "label": "SLM Cascade",
            "success_rate": 0.71,
            "median_time_s": 21.4,
            "avg_tokens": 3260,
            "estimated_cost_usd": 1.18,
            "cost_per_success_usd": 0.017,
            "avg_actions": 8.7,
            "slm_actions": 436,
            "llm_actions": 128,
        },
        {
            "id": "openai",
            "label": "OpenAI Agent",
            "success_rate": 0.76,
            "median_time_s": 29.8,
            "avg_tokens": 6420,
            "estimated_cost_usd": 3.92,
            "cost_per_success_usd": 0.054,
            "avg_actions": 10.9,
            "slm_actions": 0,
            "llm_actions": 704,
        },
        {
            "id": "claude",
            "label": "Claude Agent",
            "success_rate": 0.74,
            "median_time_s": 31.6,
            "avg_tokens": 6880,
            "estimated_cost_usd": 4.37,
            "cost_per_success_usd": 0.062,
            "avg_actions": 11.3,
            "slm_actions": 0,
            "llm_actions": 732,
        },
    ],
    "suites": [
        {
            "id": "miniwob",
            "name": "MiniWoB++",
            "focus": "Compact browser tasks on synthetic pages",
            "tasks": 24,
            "success": {"cascade": 0.86, "openai": 0.89, "claude": 0.87},
            "median_time_s": {"cascade": 8.2, "openai": 12.9, "claude": 13.7},
            "avg_tokens": {"cascade": 780, "openai": 1610, "claude": 1740},
            "cost_usd": {"cascade": 0.094, "openai": 0.298, "claude": 0.322},
            "cost_per_success_usd": {"cascade": 0.0045, "openai": 0.014, "claude": 0.0154},
        },
        {
            "id": "webarena",
            "name": "WebArena",
            "focus": "Realistic self-hosted websites and tools",
            "tasks": 24,
            "success": {"cascade": 0.64, "openai": 0.71, "claude": 0.69},
            "median_time_s": {"cascade": 27.6, "openai": 38.2, "claude": 40.5},
            "avg_tokens": {"cascade": 3710, "openai": 7460, "claude": 7890},
            "cost_usd": {"cascade": 0.318, "openai": 0.991, "claude": 1.112},
            "cost_per_success_usd": {"cascade": 0.0207, "openai": 0.0582, "claude": 0.0671},
        },
        {
            "id": "visualwebarena",
            "name": "VisualWebArena",
            "focus": "Visually grounded web navigation tasks",
            "tasks": 24,
            "success": {"cascade": 0.58, "openai": 0.67, "claude": 0.65},
            "median_time_s": {"cascade": 33.4, "openai": 44.7, "claude": 46.8},
            "avg_tokens": {"cascade": 4980, "openai": 8610, "claude": 9020},
            "cost_usd": {"cascade": 0.421, "openai": 1.326, "claude": 1.479},
            "cost_per_success_usd": {"cascade": 0.0302, "openai": 0.0825, "claude": 0.0948},
        },
        {
            "id": "workarena",
            "name": "WorkArena",
            "focus": "Knowledge work flows in enterprise software",
            "tasks": 24,
            "success": {"cascade": 0.75, "openai": 0.77, "claude": 0.75},
            "median_time_s": {"cascade": 36.1, "openai": 41.8, "claude": 43.6},
            "avg_tokens": {"cascade": 5570, "openai": 8090, "claude": 8870},
            "cost_usd": {"cascade": 0.347, "openai": 1.305, "claude": 1.457},
            "cost_per_success_usd": {"cascade": 0.0193, "openai": 0.0706, "claude": 0.0809},
        },
    ],
    "playbacks": [
        {
            "id": "miniwob-contact-form",
            "suite": "miniwob",
            "name": "MiniWoB++ Contact Form",
            "task": "Fill the form with the target contact and submit it.",
            "surface": "Synthetic form",
            "models": {
                "cascade": {
                    "outcome": "Submitted",
                    "time_s": 7.8,
                    "tokens": 620,
                    "cost_usd": 0.004,
                    "frames": [
                        {
                            "step": 1,
                            "action": "read target values",
                            "route": "SLM",
                            "tokens": 72,
                            "cost_usd": 0.000,
                            "screen": form_screen("Contact Form", "Target: Riley Park, riley@example.com, 415-0104", {}, "Name"),
                        },
                        {
                            "step": 2,
                            "action": "type name",
                            "route": "SLM",
                            "tokens": 86,
                            "cost_usd": 0.000,
                            "screen": form_screen("Contact Form", "Target: Riley Park, riley@example.com, 415-0104", {"Name": "Riley Park"}, "Email"),
                        },
                        {
                            "step": 3,
                            "action": "type email and phone",
                            "route": "SLM",
                            "tokens": 114,
                            "cost_usd": 0.000,
                            "screen": form_screen(
                                "Contact Form",
                                "Target: Riley Park, riley@example.com, 415-0104",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Submit",
                            ),
                        },
                        {
                            "step": 4,
                            "action": "submit form",
                            "route": "SLM",
                            "tokens": 128,
                            "cost_usd": 0.000,
                            "screen": form_screen(
                                "Contact Form",
                                "Submitted successfully",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Done",
                            ),
                        },
                    ],
                },
                "openai": {
                    "outcome": "Submitted",
                    "time_s": 11.4,
                    "tokens": 1480,
                    "cost_usd": 0.014,
                    "frames": [
                        {
                            "step": 1,
                            "action": "parse instruction",
                            "route": "LLM",
                            "tokens": 310,
                            "cost_usd": 0.003,
                            "screen": form_screen("Contact Form", "Target: Riley Park, riley@example.com, 415-0104", {}, "Name"),
                        },
                        {
                            "step": 2,
                            "action": "fill visible fields",
                            "route": "LLM",
                            "tokens": 420,
                            "cost_usd": 0.004,
                            "screen": form_screen(
                                "Contact Form",
                                "Target: Riley Park, riley@example.com, 415-0104",
                                {"Name": "Riley Park", "Email": "riley@example.com"},
                                "Phone",
                            ),
                        },
                        {
                            "step": 3,
                            "action": "complete phone",
                            "route": "LLM",
                            "tokens": 360,
                            "cost_usd": 0.003,
                            "screen": form_screen(
                                "Contact Form",
                                "Target: Riley Park, riley@example.com, 415-0104",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Submit",
                            ),
                        },
                        {
                            "step": 4,
                            "action": "click submit",
                            "route": "LLM",
                            "tokens": 390,
                            "cost_usd": 0.004,
                            "screen": form_screen(
                                "Contact Form",
                                "Submitted successfully",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Done",
                            ),
                        },
                    ],
                },
                "claude": {
                    "outcome": "Submitted",
                    "time_s": 12.0,
                    "tokens": 1560,
                    "cost_usd": 0.015,
                    "frames": [
                        {
                            "step": 1,
                            "action": "inspect target text",
                            "route": "LLM",
                            "tokens": 350,
                            "cost_usd": 0.003,
                            "screen": form_screen("Contact Form", "Target: Riley Park, riley@example.com, 415-0104", {}, "Name"),
                        },
                        {
                            "step": 2,
                            "action": "enter contact",
                            "route": "LLM",
                            "tokens": 470,
                            "cost_usd": 0.005,
                            "screen": form_screen(
                                "Contact Form",
                                "Target: Riley Park, riley@example.com, 415-0104",
                                {"Name": "Riley Park", "Email": "riley@example.com"},
                                "Phone",
                            ),
                        },
                        {
                            "step": 3,
                            "action": "verify field values",
                            "route": "LLM",
                            "tokens": 370,
                            "cost_usd": 0.004,
                            "screen": form_screen(
                                "Contact Form",
                                "Target: Riley Park, riley@example.com, 415-0104",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Submit",
                            ),
                        },
                        {
                            "step": 4,
                            "action": "submit",
                            "route": "LLM",
                            "tokens": 370,
                            "cost_usd": 0.003,
                            "screen": form_screen(
                                "Contact Form",
                                "Submitted successfully",
                                {"Name": "Riley Park", "Email": "riley@example.com", "Phone": "415-0104"},
                                "Done",
                            ),
                        },
                    ],
                },
            },
        },
        {
            "id": "webarena-order-admin",
            "suite": "webarena",
            "name": "WebArena Order Admin",
            "task": "Find order 1047 and update the status to refunded.",
            "surface": "Shop admin",
            "models": {
                "cascade": {
                    "outcome": "Order refunded",
                    "time_s": 26.8,
                    "tokens": 3420,
                    "cost_usd": 0.021,
                    "frames": webarena_frames("cascade", ["SLM", "SLM", "LLM", "SLM", "SLM"]),
                },
                "openai": {
                    "outcome": "Order refunded",
                    "time_s": 37.2,
                    "tokens": 7190,
                    "cost_usd": 0.058,
                    "frames": webarena_frames("openai", ["LLM", "LLM", "LLM", "LLM", "LLM"]),
                },
                "claude": {
                    "outcome": "Order refunded",
                    "time_s": 39.4,
                    "tokens": 7680,
                    "cost_usd": 0.064,
                    "frames": webarena_frames("claude", ["LLM", "LLM", "LLM", "LLM", "LLM"]),
                },
            },
        },
        {
            "id": "visualwebarena-product-match",
            "suite": "visualwebarena",
            "name": "VisualWebArena Product Match",
            "task": "Use the reference image to choose the matching lamp and add it to cart.",
            "surface": "Visual shopping task",
            "models": {
                "cascade": {
                    "outcome": "Matching item added",
                    "time_s": 32.9,
                    "tokens": 4760,
                    "cost_usd": 0.030,
                    "frames": visual_frames(["SLM", "LLM", "SLM", "SLM", "SLM"], [660, 1410, 720, 610, 590]),
                },
                "openai": {
                    "outcome": "Matching item added",
                    "time_s": 43.8,
                    "tokens": 8350,
                    "cost_usd": 0.083,
                    "frames": visual_frames(["LLM", "LLM", "LLM", "LLM", "LLM"], [1580, 1840, 1690, 1550, 1690]),
                },
                "claude": {
                    "outcome": "Matching item added",
                    "time_s": 45.1,
                    "tokens": 8740,
                    "cost_usd": 0.091,
                    "frames": visual_frames(["LLM", "LLM", "LLM", "LLM", "LLM"], [1720, 1880, 1810, 1590, 1740]),
                },
            },
        },
        {
            "id": "workarena-incident",
            "suite": "workarena",
            "name": "WorkArena Incident Flow",
            "task": "Create an incident for network latency and assign it to network operations.",
            "surface": "Service desk workflow",
            "models": {
                "cascade": {
                    "outcome": "Incident created",
                    "time_s": 35.4,
                    "tokens": 5260,
                    "cost_usd": 0.019,
                    "frames": workarena_frames(["SLM", "SLM", "LLM", "SLM", "SLM", "SLM"], [560, 670, 1590, 790, 820, 830]),
                },
                "openai": {
                    "outcome": "Incident created",
                    "time_s": 40.9,
                    "tokens": 7960,
                    "cost_usd": 0.071,
                    "frames": workarena_frames(["LLM", "LLM", "LLM", "LLM", "LLM", "LLM"], [1320, 1400, 1370, 1240, 1320, 1310]),
                },
                "claude": {
                    "outcome": "Incident created",
                    "time_s": 42.8,
                    "tokens": 8540,
                    "cost_usd": 0.081,
                    "frames": workarena_frames(["LLM", "LLM", "LLM", "LLM", "LLM", "LLM"], [1420, 1490, 1450, 1340, 1390, 1450]),
                },
            },
        },
    ],
}


def form_screen(title: str, notice: str, values: dict[str, str], active: str) -> dict[str, Any]:
    fields = [
        {"kind": "field", "label": "Name", "value": values.get("Name", ""), "state": state_for("Name", active)},
        {"kind": "field", "label": "Email", "value": values.get("Email", ""), "state": state_for("Email", active)},
        {"kind": "field", "label": "Phone", "value": values.get("Phone", ""), "state": state_for("Phone", active)},
        {"kind": "button", "text": "Submit", "state": "active" if active == "Submit" else "primary"},
    ]
    if active == "Done":
        fields.append({"kind": "message", "text": "Submission complete", "state": "success"})
    return {"title": title, "address": "miniwob.local/contact", "notice": notice, "elements": fields}


def state_for(label: str, active: str) -> str:
    if label == active:
        return "active"
    return "filled"


def webarena_frames(model_id: str, routes: list[str]) -> list[dict[str, Any]]:
    actions = ["open orders", "search 1047", "inspect order", "set refunded", "save change"]
    tokens = {
        "cascade": [430, 520, 1340, 610, 520],
        "openai": [1360, 1480, 1510, 1400, 1440],
        "claude": [1490, 1550, 1580, 1500, 1560],
    }[model_id]
    screens = [
        order_screen("Orders", "", 0, "Open"),
        order_screen("Orders", "Search: 1047", 1, "Open"),
        order_screen("Order #1047", "Customer: Jordan Lee", 1, "Open"),
        order_screen("Order #1047", "Status selected: Refunded", 1, "Refunded"),
        order_screen("Order #1047", "Saved: order #1047 refunded", 1, "Refunded"),
    ]
    return [
        {
            "step": index + 1,
            "action": actions[index],
            "route": routes[index],
            "tokens": tokens[index],
            "cost_usd": round(tokens[index] * 0.000008, 4),
            "screen": screens[index],
        }
        for index in range(len(actions))
    ]


def order_screen(title: str, notice: str, active_row: int, status: str) -> dict[str, Any]:
    rows = [
        ["1042", "Morgan Chen", "Shipped"],
        ["1047", "Jordan Lee", status],
        ["1051", "Casey Patel", "Processing"],
    ]
    return {
        "title": title,
        "address": "webarena.shop/admin/orders",
        "notice": notice,
        "elements": [
            {"kind": "toolbar", "text": "Admin / Orders / Refunds"},
            {"kind": "table", "columns": ["Order", "Customer", "Status"], "rows": rows, "activeRow": active_row},
            {"kind": "button", "text": "Save changes", "state": "active" if status == "Refunded" else "primary"},
        ],
    }


def visual_frames(routes: list[str], tokens: list[int]) -> list[dict[str, Any]]:
    actions = ["inspect reference", "scan products", "select matching lamp", "open item", "add to cart"]
    selected_by_step = [-1, -1, 1, 1, 1]
    notices = [
        "Reference: brass desk lamp with green shade",
        "Compare shape, color, and base",
        "Match selected",
        "Product detail loaded",
        "Added to cart",
    ]
    return [
        {
            "step": index + 1,
            "action": actions[index],
            "route": routes[index],
            "tokens": tokens[index],
            "cost_usd": round(tokens[index] * 0.00001, 4),
            "screen": visual_screen(notices[index], selected_by_step[index]),
        }
        for index in range(len(actions))
    ]


def visual_screen(notice: str, selected: int) -> dict[str, Any]:
    items = [
        {"title": "Matte black task lamp", "meta": "dark shade", "tone": "dark", "selected": selected == 0},
        {"title": "Brass lamp, green shade", "meta": "reference match", "tone": "green", "selected": selected == 1},
        {"title": "White ceramic table lamp", "meta": "round shade", "tone": "light", "selected": selected == 2},
    ]
    return {
        "title": "Visual Shop",
        "address": "visualwebarena.shop/search",
        "notice": notice,
        "elements": [
            {"kind": "visual-reference", "text": "Reference image"},
            {"kind": "cards", "items": items},
            {"kind": "button", "text": "Add to cart", "state": "active" if selected == 1 else "primary"},
        ],
    }


def workarena_frames(routes: list[str], tokens: list[int]) -> list[dict[str, Any]]:
    actions = ["open incidents", "create record", "enter short description", "set priority", "assign group", "submit incident"]
    statuses = [
        ("Incidents", "List loaded", {}),
        ("New Incident", "Blank record", {"Caller": "Pat Nguyen"}),
        ("New Incident", "Network latency entered", {"Caller": "Pat Nguyen", "Short description": "Network latency in west office"}),
        (
            "New Incident",
            "Priority set",
            {"Caller": "Pat Nguyen", "Short description": "Network latency in west office", "Priority": "2 - High"},
        ),
        (
            "New Incident",
            "Assignment group selected",
            {
                "Caller": "Pat Nguyen",
                "Short description": "Network latency in west office",
                "Priority": "2 - High",
                "Assignment group": "Network Operations",
            },
        ),
        (
            "Incident INC0010423",
            "Submitted to Network Operations",
            {
                "Caller": "Pat Nguyen",
                "Short description": "Network latency in west office",
                "Priority": "2 - High",
                "Assignment group": "Network Operations",
                "State": "New",
            },
        ),
    ]
    return [
        {
            "step": index + 1,
            "action": actions[index],
            "route": routes[index],
            "tokens": tokens[index],
            "cost_usd": round(tokens[index] * 0.0000095, 4),
            "screen": record_screen(statuses[index][0], statuses[index][1], statuses[index][2]),
        }
        for index in range(len(actions))
    ]


def record_screen(title: str, notice: str, values: dict[str, str]) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [{"kind": "toolbar", "text": "Service Desk / Incident"}]
    for label in ["Caller", "Short description", "Priority", "Assignment group", "State"]:
        if label in values:
            elements.append({"kind": "field", "label": label, "value": values[label], "state": "filled"})
    elements.append({"kind": "button", "text": "Submit", "state": "active" if title.startswith("New") else "primary"})
    if title.startswith("Incident"):
        elements.append({"kind": "message", "text": "Record saved", "state": "success"})
    return {"title": title, "address": "workarena.service-now.local/incident", "notice": notice, "elements": elements}


def webui_benchmark_report() -> dict[str, Any]:
    configured = os.getenv("SLM_ROUTER_WEBUI_RESULTS", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return normalize_report(json.loads(path.read_text(encoding="utf-8")), source=str(path))
    default_path = Path("benchmark_runs/webui_results.json")
    if default_path.exists():
        return normalize_report(json.loads(default_path.read_text(encoding="utf-8")), source=str(default_path))
    return demo_report()


def normalize_report(raw: dict[str, Any], source: str) -> dict[str, Any]:
    if "models" in raw and "suites" in raw:
        report = dict(raw)
        report.setdefault("benchmark", "Web UI Benchmarks")
        report.setdefault("mode", "imported")
        report.setdefault("playbacks", [])
        report["source"] = source
        return report

    runs = raw.get("runs") or raw.get("trials") or []
    models = summarize_models(runs)
    suites = summarize_suites(runs)
    return {
        "benchmark": "Web UI Benchmarks",
        "mode": "imported",
        "source": source,
        "summary": {
            "tasks": len(runs),
            "suites": len(suites),
            "winner": max(models, key=lambda row: row["success_rate"])["id"] if models else "",
        },
        "models": models,
        "suites": suites,
        "playbacks": raw.get("playbacks", []),
    }


def summarize_models(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in sorted({str(run.get("model") or run.get("agent") or "") for run in runs if run.get("model") or run.get("agent")}):
        model_runs = [run for run in runs if str(run.get("model") or run.get("agent")) == model_id]
        tasks = len(model_runs)
        wins = sum(1 for run in model_runs if bool(run.get("passed") or run.get("success")))
        total_cost = sum(float(run.get("estimated_cost_usd") or run.get("cost_usd") or 0) for run in model_runs)
        total_tokens = sum(int(run.get("tokens") or run.get("total_tokens") or 0) for run in model_runs)
        elapsed = sorted(float(run.get("elapsed_s") or run.get("time_s") or 0) for run in model_runs)
        rows.append(
            {
                "id": model_id,
                "label": MODEL_LABELS.get(model_id, model_id),
                "success_rate": wins / max(1, tasks),
                "median_time_s": elapsed[tasks // 2] if tasks else 0,
                "avg_tokens": int(total_tokens / max(1, tasks)),
                "estimated_cost_usd": round(total_cost, 4),
                "cost_per_success_usd": round(total_cost / max(1, wins), 4),
                "avg_actions": round(sum(float(run.get("actions") or run.get("steps") or 0) for run in model_runs) / max(1, tasks), 2),
                "slm_actions": sum(int(run.get("slm_actions") or 0) for run in model_runs),
                "llm_actions": sum(int(run.get("llm_actions") or 0) for run in model_runs),
            }
        )
    return rows


def summarize_suites(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suites: list[dict[str, Any]] = []
    for suite_id in sorted({str(run.get("suite") or run.get("benchmark") or "webui") for run in runs}):
        suite_runs = [run for run in runs if str(run.get("suite") or run.get("benchmark") or "webui") == suite_id]
        success: dict[str, float] = {}
        median_time_s: dict[str, float] = {}
        avg_tokens: dict[str, int] = {}
        cost_usd: dict[str, float] = {}
        cost_per_success_usd: dict[str, float] = {}
        for model_id in sorted({str(run.get("model") or run.get("agent") or "") for run in suite_runs}):
            rows = [run for run in suite_runs if str(run.get("model") or run.get("agent")) == model_id]
            wins = sum(1 for run in rows if bool(run.get("passed") or run.get("success")))
            total_cost = sum(float(run.get("estimated_cost_usd") or run.get("cost_usd") or 0) for run in rows)
            elapsed = sorted(float(run.get("elapsed_s") or run.get("time_s") or 0) for run in rows)
            success[model_id] = round(wins / max(1, len(rows)), 3)
            median_time_s[model_id] = elapsed[len(rows) // 2] if rows else 0
            avg_tokens[model_id] = int(sum(int(run.get("tokens") or run.get("total_tokens") or 0) for run in rows) / max(1, len(rows)))
            cost_usd[model_id] = round(total_cost, 4)
            cost_per_success_usd[model_id] = round(total_cost / max(1, wins), 4)
        suites.append(
            {
                "id": suite_id,
                "name": str(suite_runs[0].get("suite_name") or suite_id),
                "focus": str(suite_runs[0].get("focus") or "Web UI task benchmark"),
                "tasks": len(suite_runs),
                "success": success,
                "median_time_s": median_time_s,
                "avg_tokens": avg_tokens,
                "cost_usd": cost_usd,
                "cost_per_success_usd": cost_per_success_usd,
            }
        )
    return suites
