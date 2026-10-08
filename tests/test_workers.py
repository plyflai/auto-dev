"""Worker worktree and merge-queue lifecycle coverage."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"


class WorkerLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-worker-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.execute("git", "init", "-q")
        self.execute("git", "config", "user.name", "Auto Dev Worker Test")
        self.execute("git", "config", "user.email", "auto-dev-worker@example.com")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.execute("git", "add", ".")
        self.execute("git", "commit", "-qm", "initial")
        self.execute("git", "checkout", "-qb", "worker-test")
        self.cli("project", "init", "--confirmation-source", "worker fixture")
        self.cli(
            "start", "--tier", "team", "--task", "Worker fixture",
            "--requirement-receipt", "REQ-WORKER", "--confirmation-source", "worker fixture",
            "--acceptance", "Worker packet is applied",
            "--scope", "src/a.py", "--validation", "python3 -c pass",
            "--skip", "architecture=fixture", "--skip", "compliance=fixture",
            "--skip", "data-contract=fixture", "--skip", "debug-observability=fixture",
            "--skip", "gui=fixture", "--skip", "release=fixture",
            "--capability", "parallel-work", "--capability-evidence", "parallel-work=worker fixture",
        )
        self.cli(
            "plan", "--base-revision", "0", "--reason", "worker roadmap",
            "--plan-json", json.dumps({
                "strategy": "rolling_graph",
                "goal": {"statement": "Worker lifecycle", "acceptance": ["Worker packet is applied"], "source": "worker fixture"},
                "nodes": [{"id": "m1", "title": "M1: Worker milestone", "node_role": "milestone", "status": "planned", "acceptance": ["M1 accepted"]}],
                "relations": [],
            }),
        )
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = {
            "policy": {
                "execution_topology": "multi_agent",
                "merge_mode": "worktree_merge_queue",
                "verification_floor": ["packet_proof", "integration_proof"],
                "conflict_owner": "integrator",
            },
            "nodes": [
                {
                    "id": "p1", "title": "Implement A", "node_role": "work_packet", "status": "planned",
                    "target": "src/a.py", "write_scope": ["src/a.py"], "owns": ["a"],
                    "provides": ["a-ready"], "consumes": [], "exclusive_claims": ["src/a.py"],
                    "assertions": [{"id": "a-value", "observable": "src/a.py", "predicate": "contains VALUE = 2", "expected": "VALUE = 2", "proof_ids": ["p1-proof"], "blocking": True}],
                    "escalation": {"rework": "repair p1", "recompile": "recompile M1", "roadmap_revision": "revise roadmap"},
                    "outcome": {"kind": "behavior_change", "primary": "A is updated", "proofs": [{"id": "p1-proof", "description": "Run p1", "recipe": {"argv": ["python3", "-c", "pass"]}}]},
                    "execution_profile": "bounded", "review_policy": "quick",
                    "verification_policy": {"required": ["unit"], "post_merge": ["integration"], "blocking": True},
                    "merge_policy": {"mode": "worktree_merge_queue", "conflict_owner": "integrator", "pre_merge": True},
                },
                {
                    "id": "integrate", "title": "Integrate worker packet", "node_role": "integration", "status": "planned",
                    "target": "accumulated workspace", "write_scope": ["src/a.py"], "owns": ["integration"],
                    "provides": [], "consumes": ["a-ready"], "exclusive_claims": [], "depends_on": ["p1"],
                    "assertions": [{"id": "integration-green", "observable": "workspace", "predicate": "integration proof passes", "expected": "exit 0", "proof_ids": ["integration-proof"], "blocking": True}],
                    "escalation": {"rework": "repair integration", "recompile": "recompile M1", "roadmap_revision": "revise roadmap"},
                    "outcome": {"kind": "behavior_change", "primary": "M1 integrates", "proofs": [{"id": "integration-proof", "description": "Run integration", "recipe": {"argv": ["python3", "-c", "pass"]}}]},
                    "merge_policy": {"mode": "worktree_merge_queue", "conflict_owner": "integrator", "pre_merge": False},
                },
            ],
            "next_action": "Prepare worker",
        }
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile worker packet", "--packet-json", json.dumps(packets),
        )
        state = self.cli("status", "--compact")
        self.cli(
            "milestone", "execution", "select", "--milestone", "m1",
            "--mode", "multi_worker",
            "--plan-revision", str(state["continuity"]["plan"]["revision"]),
            "--state-revision", str(state["state_revision"]),
            "--confirmation-source", "worker fixture execution choice",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def execute(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(list(args), cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *args: str, check: bool = True) -> dict:
        result = self.execute(sys.executable, str(CLI), *args, "--repo-root", str(self.repo), check=check)
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        if not check:
            payload["returncode"] = result.returncode
            payload["stderr"] = result.stderr
        return payload

    def bind_worker(self, worker_id: str) -> dict:
        return self.cli(
            "milestone", "worker", "bind", "--worker-id", worker_id,
            "--executor-ref", f"fixture-{worker_id}",
        )

    def test_prepare_capture_apply_cleanup(self) -> None:
        prepared = self.cli("milestone", "worker", "prepare", "--packet", "p1", "--worker-id", "worker-p1")
        worker = prepared["worker"]
        self.assertEqual(prepared["status"], "dispatch_required")
        self.assertEqual(worker["capsule"]["schema"], "auto-dev/worker-context/v1")
        self.assertIn("write_scope", worker["capsule"]["packet"])
        worktree = Path(worker["worktree_path"])
        self.assertTrue(worktree.is_dir())
        self.assertEqual(self.cli("milestone", "worker", "inspect", "--worker-id", "worker-p1")["status"], "dispatch_required")
        self.assertEqual(self.bind_worker("worker-p1")["status"], "running")

        (worktree / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
        result_file = self.repo / "worker-result.json"
        result_file.write_text(json.dumps({"summary": "updated A", "proof_refs": ["p1-proof"], "next_action": "integrate"}), encoding="utf-8")
        captured = self.cli("milestone", "worker", "capture", "--worker-id", "worker-p1", "--result-file", str(result_file))
        self.assertEqual(captured["status"], "captured")
        self.assertEqual(captured["worker"]["status"], "awaiting_main")
        self.assertEqual(captured["worker"]["changed_paths"], ["src/a.py"])
        applied = self.cli("milestone", "worker", "apply", "--worker-id", "worker-p1")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual((self.repo / "src" / "a.py").read_text(encoding="utf-8"), "VALUE = 2\n")
        cleaned = self.cli("milestone", "worker", "cleanup", "--worker-id", "worker-p1")
        self.assertEqual(cleaned["status"], "cleaned")
        self.assertFalse(worktree.exists())

    def test_worker_profile_requires_real_bind_before_capture(self) -> None:
        prepared = self.cli(
            "milestone", "worker", "prepare", "--packet", "p1",
            "--worker-id", "worker-profile",
        )
        worker = prepared["worker"]
        self.assertEqual(worker["worker_profile"], "light_worker")
        self.assertEqual(worker["executor"]["model"], "gpt-5.6-luna")
        rejected_capture = self.cli(
            "milestone", "worker", "capture", "--worker-id", "worker-profile",
            check=False,
        )
        self.assertIn("not capture-ready", rejected_capture["stderr"])
        rejected_bind = self.cli(
            "milestone", "worker", "bind", "--worker-id", "worker-profile",
            "--executor-ref", "wrong-model", "--model", "gpt-5.6-terra",
            check=False,
        )
        self.assertIn("does not match", rejected_bind["stderr"])
        running = self.bind_worker("worker-profile")
        self.assertEqual(running["worker"]["executor_ref"], "fixture-worker-profile")

    def test_dispatch_blocked_is_structured_and_terminal_for_capture(self) -> None:
        self.cli(
            "milestone", "worker", "prepare", "--packet", "p1",
            "--worker-id", "worker-unavailable",
        )
        blocked = self.cli(
            "milestone", "worker", "bind", "--worker-id", "worker-unavailable",
            "--blocked-reason", "host model catalog has no selected model",
            check=False,
        )
        self.assertEqual(blocked["status"], "dispatch_blocked")
        inspected = self.cli(
            "milestone", "worker", "inspect", "--worker-id", "worker-unavailable"
        )
        self.assertEqual(inspected["launch_status"], "dispatch_blocked")
        rejected = self.cli(
            "milestone", "worker", "capture", "--worker-id", "worker-unavailable",
            check=False,
        )
        self.assertIn("not capture-ready", rejected["stderr"])

    def test_capture_rejects_out_of_scope_change(self) -> None:
        prepared = self.cli("milestone", "worker", "prepare", "--packet", "p1", "--worker-id", "worker-scope")
        worktree = Path(prepared["worker"]["worktree_path"])
        self.bind_worker("worker-scope")
        (worktree / "README.md").write_text("out of scope\n", encoding="utf-8")
        rejected = self.cli("milestone", "worker", "capture", "--worker-id", "worker-scope", check=False)
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("out-of-scope", rejected["stderr"])
        self.assertEqual(self.cli("milestone", "worker", "inspect", "--worker-id", "worker-scope")["status"], "blocked")

    def test_apply_rejects_base_drift(self) -> None:
        prepared = self.cli("milestone", "worker", "prepare", "--packet", "p1", "--worker-id", "worker-drift")
        worktree = Path(prepared["worker"]["worktree_path"])
        self.bind_worker("worker-drift")
        (worktree / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.cli("milestone", "worker", "capture", "--worker-id", "worker-drift")
        (self.repo / "src" / "a.py").write_text("VALUE = 3\n", encoding="utf-8")
        self.execute("git", "add", "src/a.py")
        self.execute("git", "commit", "-qm", "drift")
        rejected = self.cli("milestone", "worker", "apply", "--worker-id", "worker-drift", check=False)
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("base HEAD drifted", rejected["stderr"])
        self.assertEqual(self.cli("milestone", "worker", "inspect", "--worker-id", "worker-drift")["status"], "conflicted")

    def test_finalize_runs_proof_checkpoint_and_stops_before_integration(self) -> None:
        prepared = self.cli(
            "milestone", "worker", "prepare", "--packet", "p1", "--worker-id", "worker-finalize"
        )
        worktree = Path(prepared["worker"]["worktree_path"])
        self.bind_worker("worker-finalize")
        (worktree / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
        result_file = self.repo / "worker-finalize-result.json"
        result_file.write_text(
            json.dumps({"summary": "updated A", "proof_refs": ["p1-proof"]}),
            encoding="utf-8",
        )
        self.cli(
            "milestone", "worker", "capture", "--worker-id", "worker-finalize",
            "--result-file", str(result_file),
        )
        inspection = self.cli(
            "milestone", "worker", "finalize", "inspect", "--worker-id", "worker-finalize"
        )
        finalized = self.cli(
            "milestone", "worker", "finalize", "apply", "--worker-id", "worker-finalize",
            "--plan-revision", str(inspection["plan_revision"]),
            "--state-revision", str(inspection["state_revision"]),
            "--summary", "p1 complete", "--evidence", "worker patch and declared proof",
        )
        self.assertEqual(finalized["status"], "finalized")
        self.assertEqual((self.repo / "src" / "a.py").read_text(encoding="utf-8"), "VALUE = 2\n")
        status = self.cli("status", "--compact")
        nodes = {node["id"]: node for node in status["continuity"]["plan"]["nodes"]}
        self.assertEqual(nodes["p1"]["status"], "done")
        self.assertIsNone(status["continuity"]["current_node"])
        self.assertEqual(
            nodes["m1"]["milestone_state"]["execution_decision"]["status"],
            "awaiting_main",
        )
        current = self.cli("status", "--compact")
        handoff = self.cli(
            "milestone", "handoff", "take", "--milestone", "m1",
            "--plan-revision", str(current["continuity"]["plan"]["revision"]),
            "--state-revision", str(current["state_revision"]),
            "--confirmation-source", "worker fixture main-session takeover",
        )
        self.assertEqual(handoff["status"], "taken")
        self.assertEqual(handoff["current_node"], "integrate")
        self.assertEqual(handoff["execution_decision"]["selected_mode"], "multi_worker")


if __name__ == "__main__":
    unittest.main()
