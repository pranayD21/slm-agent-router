import tempfile
import unittest
from pathlib import Path

from slm_agent_router.agent_loop import run_tasks
from slm_agent_router.models.mock import MockModel
from slm_agent_router.reporting import write_report
from slm_agent_router.schemas import load_tasks, parse_policy

ROOT = Path(__file__).resolve().parents[1]


class RouterTests(unittest.TestCase):
    def test_escalation_metrics_and_report(self):
        tasks = load_tasks(ROOT / "examples" / "tasks.json")
        policy = parse_policy(ROOT / "examples" / "policy.toml")
        with tempfile.TemporaryDirectory() as td:
            run_path = Path(td) / "runs.jsonl"
            result = run_tasks(tasks, policy, MockModel("local", "local"), MockModel("cloud", "cloud"), run_path)
            self.assertGreater(result["metrics"]["escalation_rate"], 0)
            out = write_report(run_path, Path(td) / "report.html")
            self.assertIn("Agent-step routing", out.read_text())


if __name__ == "__main__":
    unittest.main()
