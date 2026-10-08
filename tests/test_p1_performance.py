"""P1 regression coverage for conditional performance proof history."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
SCRIPTS = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))

from runctl import read_performance_evidence  # noqa: E402
import hook_dispatch  # noqa: E402


class P1PerformanceEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-performance-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "artifacts").mkdir()
        (self.repo / "src" / "service.py").write_text("BATCH_SIZE = 1\n", encoding="utf-8")
        self.write_evidence(phase="baseline", samples=[810, 790, 800])
        self.exec("git", "init", "-q")
        self.exec("git", "config", "user.name", "Auto Dev Performance Test")
        self.exec("git", "config", "user.email", "auto-dev-performance@example.com")
        self.exec("git", "add", ".")
        self.exec("git", "commit", "-qm", "initial")
        self.exec("git", "checkout", "-qb", "performance-proof")
        self.cli("project", "init", "--confirmation-source", "performance fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def exec(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), cwd=self.repo, env=os.environ, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        result = self.exec(sys.executable, str(CLI), *arguments, "--repo-root", str(self.repo), check=check)
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def status(self) -> dict[str, Any]:
        return self.cli("status", "--compact")

    def start(self) -> None:
        self.cli(
            "start", "--tier", "direct", "--task", "Reduce checkout latency",
            "--requirement-receipt", "REQ-PERF", "--confirmation-source", "performance fixture",
            "--acceptance", "Checkout latency is below 500 ms",
            "--scope", "src/service.py", "--scope", "artifacts/perf-baseline.json",
            "--scope", "artifacts/perf-after.json", "--validation", "checkout benchmark",
        )

    def plan(self, *, outcome_kind: str = "measured_improvement") -> None:
        self.cli(
            "plan", "--base-revision", "0", "--reason", "performance proof",
            "--plan-json", json.dumps({
                "goal": {
                    "statement": "Reduce checkout latency",
                    "acceptance": ["Checkout latency is below 500 ms"],
                    "source": "performance fixture",
                },
                "nodes": [{
                    "id": "optimize", "title": "Optimize checkout", "status": "active",
                    "outcome": {
                        "kind": outcome_kind,
                        "primary": "Checkout latency is reliably below 500 ms",
                        "proofs": [{"id": "latency", "description": "Compare checkout latency"}],
                    },
                }],
                "current_node": "optimize",
                "next_action": "record the performance baseline",
            }),
        )

    def write_evidence(
        self, *, phase: str, samples: list[float], baseline_attempt_id: str | None = None,
        target_value: float = 500, noise_tolerance_pct: float = 5,
        workload: str = "100 sequential checkout requests",
    ) -> Path:
        path = self.repo / "artifacts" / f"perf-{'baseline' if phase == 'baseline' else 'after'}.json"
        payload: dict[str, Any] = {
            "schema": "auto-dev/performance-evidence/v1",
            "phase": phase,
            "source_ref": f"benchmark/{phase}.json",
            "hypothesis": "Batching checkout work reduces latency",
            "metric": "checkout_latency",
            "unit": "ms",
            "direction": "lower",
            "target_value": target_value,
            "workload": workload,
            "environment": "local Python 3.12",
            "samples": samples,
            "noise_tolerance_pct": noise_tolerance_pct,
        }
        if baseline_attempt_id is not None:
            payload["baseline_attempt_id"] = baseline_attempt_id
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def record(self, evidence_file: str, *, check: bool = True) -> dict[str, Any]:
        state = self.status()
        return self.cli(
            "proof", "--node", "optimize", "--proof-id", "latency",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", evidence_file,
            check=check,
        )

    def test_baseline_and_comparison_flow_through_proof_review_handoff_and_staleness(self) -> None:
        self.start()
        self.plan()
        baseline = self.record("artifacts/perf-baseline.json")
        self.assertEqual(baseline["status"], "recorded")
        self.assertTrue(baseline["fresh"])
        self.assertEqual(baseline["performance_evidence"]["sample_count"], 3)
        self.assertEqual(self.status()["outcome_summary"]["pending_proofs"], 1)

        (self.repo / "src" / "service.py").write_text("BATCH_SIZE = 20\n", encoding="utf-8")
        self.write_evidence(
            phase="comparison", samples=[430, 420, 425],
            baseline_attempt_id=baseline["attempt_id"],
        )
        comparison = self.record("artifacts/perf-after.json")
        self.assertEqual(comparison["status"], "passed")
        self.assertEqual(comparison["performance_evidence"]["result"], "passed")
        self.assertTrue(comparison["performance_evidence"]["target_met"])
        self.assertTrue(comparison["performance_evidence"]["change_exceeds_noise"])

        state = self.status()
        self.assertEqual([item["status"] for item in state["continuity"]["proofs"]], ["recorded", "passed"])
        self.assertEqual(state["continuity"]["latest_proofs"][0]["attempt_count"], 2)
        self.assertEqual(state["outcome_summary"]["passed_proofs"], 1)
        self.cli(
            "checkpoint", "--node", "optimize", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "Performance target met", "--evidence", "benchmark comparison passed",
        )
        self.cli(
            "task", "review", "--state-revision", str(self.status()["state_revision"]),
            "--summary", "Checkout latency target met", "--validation", "benchmark comparison passed",
        )
        context = hook_dispatch.control_context(self.repo, self.status(), "session_compact")
        self.assertIn('"performance"', context)
        self.assertIn('"sample_count":3', context)
        self.assertIn('"review"', context)
        self.assertIn("💡 Auto Dev 产品验收回执", context)
        handoff = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(handoff))
        packet = json.loads(handoff.read_text(encoding="utf-8"))
        self.assertEqual(packet["continuity"]["proofs"][1]["performance_evidence"]["result"], "passed")

        baseline_path = self.repo / "artifacts" / "perf-baseline.json"
        baseline_path.write_text(baseline_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertFalse(self.status()["continuity"]["latest_proofs"][0]["fresh"])

    def test_comparison_below_target_but_inside_noise_cannot_become_green(self) -> None:
        self.start()
        self.plan()
        self.write_evidence(phase="baseline", samples=[810, 790, 800], target_value=799)
        baseline = self.record("artifacts/perf-baseline.json")
        self.write_evidence(
            phase="comparison", samples=[795, 790, 792], target_value=799,
            noise_tolerance_pct=5, baseline_attempt_id=baseline["attempt_id"],
        )
        recorded = self.record("artifacts/perf-after.json", check=False)
        self.assertEqual(recorded["returncode"], 1)
        proof = json.loads(recorded["stdout"])
        self.assertEqual(proof["status"], "failed")
        self.assertTrue(proof["performance_evidence"]["target_met"])
        self.assertFalse(proof["performance_evidence"]["change_exceeds_noise"])

    def test_comparison_requires_a_matching_recorded_baseline(self) -> None:
        self.start()
        self.plan()
        self.write_evidence(
            phase="comparison", samples=[430, 420], baseline_attempt_id="attempt-missing",
        )
        missing = self.record("artifacts/perf-after.json", check=False)
        self.assertNotEqual(missing["returncode"], 0)
        self.assertIn("recorded baseline attempt", missing["stderr"])

        baseline = self.record("artifacts/perf-baseline.json")
        self.write_evidence(
            phase="comparison", samples=[430, 420], baseline_attempt_id=baseline["attempt_id"],
            workload="a different workload",
        )
        mismatch = self.record("artifacts/perf-after.json", check=False)
        self.assertNotEqual(mismatch["returncode"], 0)
        self.assertIn("must match baseline", mismatch["stderr"])

    def test_performance_evidence_requires_measured_improvement_outcome(self) -> None:
        self.start()
        self.plan(outcome_kind="behavior_change")
        result = self.record("artifacts/perf-baseline.json", check=False)
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("measured_improvement outcome", result["stderr"])

    def test_manifest_rejects_single_sample_and_sensitive_text(self) -> None:
        path = self.write_evidence(phase="baseline", samples=[800])
        with self.assertRaisesRegex(ValueError, "at least two samples"):
            read_performance_evidence(self.repo, str(path))

        path = self.write_evidence(phase="baseline", samples=[800, 805], workload="password=secret")
        with self.assertRaisesRegex(ValueError, "credential or secret"):
            read_performance_evidence(self.repo, str(path))


if __name__ == "__main__":
    unittest.main()
