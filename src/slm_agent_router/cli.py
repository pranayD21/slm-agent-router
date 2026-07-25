from __future__ import annotations

import argparse

from .agent_loop import run_tasks
from .models.mock import MockModel
from .reporting import write_report
from .schemas import load_tasks, parse_policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slm-router")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--suite", required=True)
    run.add_argument("--policy", required=True)
    run.add_argument("--output", required=True)
    report = sub.add_parser("report")
    report.add_argument("runs")
    report.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "run":
        policy = parse_policy(args.policy)
        result = run_tasks(load_tasks(args.suite), policy, MockModel(policy.get("local_model", "mock-local"), "local"), MockModel(policy.get("fallback_model", "mock-cloud"), "cloud"), args.output)
        print(result["metrics"])
    elif args.cmd == "report":
        print(write_report(args.runs, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
