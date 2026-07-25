from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from starlette.requests import Request

from .web_benchmark import build_agent_configs, provider_status, run_benchmark


STATIC_DIR = Path(__file__).with_name("static")


class BenchmarkManager:
    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.ip_windows: dict[str, deque[float]] = defaultdict(deque)
        self.active_runs = 0
        self.max_active_runs = int(os.getenv("SLM_ROUTER_MAX_ACTIVE_RUNS", "3"))
        self.runs_per_hour = int(os.getenv("SLM_ROUTER_RUNS_PER_HOUR", "20"))
        self.max_steps = int(os.getenv("SLM_ROUTER_MAX_STEPS", "15"))
        self.allow_server_keys = os.getenv("SLM_ROUTER_ALLOW_SERVER_KEYS", "true").lower() != "false"

    async def start(self, payload: dict[str, Any], client_ip: str = "unknown") -> str:
        self.enforce_rate_limit(client_ip)
        if self.active_runs >= self.max_active_runs:
            raise ValueError("The benchmark is busy. Try again in a moment.")
        task = str(payload.get("task", "")).strip()
        if not task:
            raise ValueError("Task prompt is required.")
        agents = payload.get("agents") or ["cascade", "openai", "claude"]
        provider_keys = {
            "openai": str((payload.get("provider_keys") or {}).get("openai") or "").strip(),
            "claude": str((payload.get("provider_keys") or {}).get("claude") or "").strip(),
        }
        provider_keys = {key: value for key, value in provider_keys.items() if value}
        configs = build_agent_configs(
            [str(agent) for agent in agents],
            provider_keys=provider_keys,
            allow_server_keys=self.allow_server_keys,
        )
        if not configs:
            raise ValueError("Select at least one valid agent.")

        run_id = str(uuid.uuid4())
        self.runs[run_id] = {
            "events": [],
            "done": False,
            "results": None,
        }

        async def emit(event: dict[str, Any]) -> None:
            event["run_id"] = run_id
            self.runs[run_id]["events"].append(event)

        async def execute() -> None:
            self.active_runs += 1
            try:
                results = await run_benchmark(
                    task,
                    normalize_start_url(payload.get("start_url")),
                    configs,
                    emit,
                    max_steps=max(1, min(int(payload.get("max_steps") or 12), self.max_steps)),
                    headless=True,
                )
                self.runs[run_id]["results"] = results
            except Exception as exc:
                await emit({"type": "run_error", "message": str(exc)})
            finally:
                self.active_runs = max(0, self.active_runs - 1)
                self.runs[run_id]["done"] = True
                await emit({"type": "stream_closed"})

        self.runs[run_id]["task"] = asyncio.create_task(execute())
        return run_id

    async def stream(self, run_id: str):
        if run_id not in self.runs:
            yield sse({"type": "run_error", "message": "Unknown run id.", "run_id": run_id})
            return
        cursor = 0
        while True:
            run = self.runs[run_id]
            while cursor < len(run["events"]):
                event = run["events"][cursor]
                cursor += 1
                yield sse(event)
                if event.get("type") == "stream_closed":
                    return
            if run["done"]:
                return
            await asyncio.sleep(0.1)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run_id,
            "done": run["done"],
            "results": run["results"],
            "events": run["events"],
        }

    def enforce_rate_limit(self, client_ip: str) -> None:
        now = time.time()
        window = self.ip_windows[client_ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= self.runs_per_hour:
            raise ValueError("This device has reached the hourly run limit. Try again later.")
        window.append(now)


manager = BenchmarkManager()


def create_app():
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            "The web app dependencies are not installed. Run `python3 -m pip install -e '.[web]'`."
        ) from exc

    app = FastAPI(title="SLM Agent Router Browser Benchmark")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def config():
        data = provider_status()
        data["limits"] = {
            "max_active_runs": manager.max_active_runs,
            "runs_per_hour": manager.runs_per_hour,
            "max_steps": manager.max_steps,
            "allow_server_keys": manager.allow_server_keys,
        }
        return JSONResponse(data)

    @app.post("/api/runs")
    async def start_run(payload: dict[str, Any], request: Request):
        try:
            run_id = await manager.start(payload, client_ip=request.client.host if request.client else "unknown")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        run = manager.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found.")
        return run

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str):
        return StreamingResponse(manager.stream(run_id), media_type="text/event-stream")

    return app


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=True)}\n\n"


def normalize_start_url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def main(argv: list[str] | None = None) -> int:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(prog="slm-router-web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)
    uvicorn.run(
        "slm_agent_router.server:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=True,
    )
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
