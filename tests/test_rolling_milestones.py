"""Phase 1 rolling Milestone and Work Packet graph coverage."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"


class RollingMilestoneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-rolling-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.execute("git", "init", "-q")
        self.execute("git", "config", "user.name", "Auto Dev Rolling Test")
        self.execute("git", "config", "user.email", "auto-dev-rolling@example.com")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.repo / "src" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.execute("git", "add", ".")
        self.execute("git", "commit", "-qm", "initial")
        self.execute("git", "checkout", "-qb", "rolling-test")
        self.cli("project", "init", "--confirmation-source", "rolling fixture")
        self.cli(
            "start", "--tier", "team", "--task", "Rolling fixture",
            "--requirement-receipt", "REQ-ROLLING", "--confirmation-source", "rolling fixture",
            "--acceptance", "All rolling milestones are accepted",
            "--scope", "src/a.py", "--scope", "src/b.py", "--validation", "python3 -c pass",
            "--skip", "architecture=fixture", "--skip", "compliance=fixture",
            "--skip", "data-contract=fixture", "--skip", "debug-observability=fixture",
            "--skip", "gui=fixture", "--skip", "parallel-work=fixture", "--skip", "release=fixture",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def execute(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(args), cwd=self.repo, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *args: str, check: bool = True) -> dict[str, Any]:
        result = self.execute(sys.executable, str(CLI), *args, "--repo-root", str(self.repo), check=check)
        payload: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
        if not check:
            payload["returncode"] = result.returncode
            payload["stderr"] = result.stderr
        return payload

    def rolling_plan(self) -> dict[str, Any]:
        return self.cli(
            "plan", "--base-revision", "0", "--reason", "rolling roadmap",
            "--plan-json", json.dumps({
                "strategy": "rolling_graph",
                "goal": {
                    "statement": "Execute rolling graph",
                    "acceptance": ["All rolling milestones are accepted"],
                    "source": "rolling fixture",
                },
                "nodes": [
                    {"id": "m1", "title": "M1: First milestone", "node_role": "milestone", "status": "planned", "acceptance": ["M1 accepted"]},
                    {"id": "m2", "title": "M2: Second milestone", "node_role": "milestone", "status": "planned", "depends_on": ["m1"], "acceptance": ["M2 accepted"]},
                ],
                "relations": [],
            }),
        )

    def enable_parallel_work(self) -> None:
        self.cli(
            "capabilities",
            "--enable", "parallel-work",
            "--capability-evidence", "parallel-work=explicit rolling fixture",
            "--skip", "architecture=fixture",
            "--skip", "compliance=fixture",
            "--skip", "data-contract=fixture",
            "--skip", "debug-observability=fixture",
            "--skip", "gui=fixture",
            "--skip", "release=fixture",
        )

    def select_execution(
        self, milestone: str, mode: str, *, boundary: str = "before_integration"
    ) -> dict[str, Any]:
        state = self.cli("status", "--compact")
        return self.cli(
            "milestone", "execution", "select", "--milestone", milestone,
            "--mode", mode,
            "--plan-revision", str(state["continuity"]["plan"]["revision"]),
            "--state-revision", str(state["state_revision"]),
            "--confirmation-source", "rolling fixture execution choice",
            "--boundary", boundary,
        )

    @staticmethod
    def packets(prefix: str = "") -> dict[str, Any]:
        p1 = prefix + "p1"
        p2 = prefix + "p2"
        integrate = prefix + "integrate"
        return {
            "nodes": [
                {
                    "id": p1, "title": "Implement A", "node_role": "work_packet", "status": "planned",
                    "target": "src/a.py", "write_scope": ["src/a.py"], "owns": ["a"],
                    "provides": ["a-ready"], "consumes": [], "exclusive_claims": ["src/a.py"],
                    "assertions": [{"id": "a-value", "observable": "src/a.py", "predicate": "contains VALUE = 2", "expected": "VALUE = 2", "proof_ids": ["p1-proof"], "blocking": True}],
                    "escalation": {"rework": "repair p1", "recompile": "recompile M1", "roadmap_revision": "revise roadmap"},
                    "outcome": {"kind": "behavior_change", "primary": "A is updated", "proofs": [{"id": "p1-proof", "description": "Run p1", "recipe": {"argv": ["python3", "-c", "pass"]}}]},
                },
                {
                    "id": p2, "title": "Implement B", "node_role": "work_packet", "status": "planned",
                    "target": "src/b.py", "write_scope": ["src/b.py"], "owns": ["b"],
                    "provides": ["b-ready"], "consumes": [], "exclusive_claims": ["src/b.py"],
                    "assertions": [{"id": "b-value", "observable": "src/b.py", "predicate": "contains VALUE = 2", "expected": "VALUE = 2", "proof_ids": ["p2-proof"], "blocking": True}],
                    "escalation": {"rework": "repair p2", "recompile": "recompile M1", "roadmap_revision": "revise roadmap"},
                    "outcome": {"kind": "behavior_change", "primary": "B is updated", "proofs": [{"id": "p2-proof", "description": "Run p2", "recipe": {"argv": ["python3", "-c", "pass"]}}]},
                },
                {
                    "id": integrate, "title": "Integrate milestone", "node_role": "integration", "status": "planned",
                    "target": "accumulated workspace", "write_scope": ["src/a.py", "src/b.py"], "owns": ["integration"],
                    "provides": [], "consumes": ["a-ready", "b-ready"], "exclusive_claims": [],
                    "depends_on": [p1, p2],
                    "assertions": [{"id": "integration-green", "observable": "workspace", "predicate": "integration proof passes", "expected": "exit 0", "proof_ids": ["integration-proof"], "blocking": True}],
                    "escalation": {"rework": "repair integration", "recompile": "recompile M1", "roadmap_revision": "revise roadmap"},
                    "outcome": {"kind": "behavior_change", "primary": "M1 integrates", "proofs": [{"id": "integration-proof", "description": "Run integration", "recipe": {"argv": ["python3", "-c", "pass"]}}]},
                },
            ],
            "relations": [],
            "next_action": "Execute M1",
        }

    def test_rolls_from_m1_to_m2_without_staling_m1_proof(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        self.assertEqual(state["continuity"]["plan"]["strategy"], "rolling_graph")
        self.assertEqual(self.cli("milestone", "frontier")["milestones"], ["m1"])
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        compiled = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile M1", "--packet-json", json.dumps(self.packets()),
        )
        self.assertIsNone(compiled["current_node"])
        self.assertEqual(compiled["execution_decision"]["status"], "pending")
        self.assertEqual(compiled["frontier"]["dispatch_status"], "confirmation_required")
        selected = self.select_execution("m1", "main_session")
        self.assertEqual(selected["current_node"], "p1")
        current = self.cli("status", "--compact")
        self.cli("proof", "--node", "p1", "--proof-id", "p1-proof", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--command", "python3 -c pass")
        current = self.cli("status", "--compact")
        self.cli("checkpoint", "--node", "p1", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--status", "done", "--summary", "p1 done", "--evidence", "p1 proof")
        current = self.cli("status", "--compact")
        self.cli("proof", "--node", "p2", "--proof-id", "p2-proof", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--command", "python3 -c pass")
        current = self.cli("status", "--compact")
        self.cli("checkpoint", "--node", "p2", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--status", "done", "--summary", "p2 done", "--evidence", "p2 proof")
        current = self.cli("status", "--compact")
        self.assertEqual(current["continuity"]["current_node"], "integrate")
        milestone_state = next(
            node["milestone_state"] for node in current["continuity"]["plan"]["nodes"]
            if node.get("id") == "m1"
        )
        self.assertEqual(milestone_state["execution_decision"]["status"], "selected")
        current = self.cli("status", "--compact")
        self.cli("proof", "--node", "integrate", "--proof-id", "integration-proof", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--command", "python3 -c pass")
        current = self.cli("status", "--compact")
        self.cli("checkpoint", "--node", "integrate", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--status", "done", "--summary", "integration done", "--evidence", "integration proof")
        current = self.cli("status", "--compact")
        self.assertEqual(self.cli("milestone", "integration", "inspect", "--milestone", "m1")["status"], "ready")
        self.cli("milestone", "integration", "record", "--milestone", "m1", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--result", "integrated", "--summary", "M1 integrated", "--evidence", "integration proof")
        current = self.cli("status", "--compact")
        review = self.cli("milestone", "review", "record", "--milestone", "m1", "--plan-revision", "2", "--state-revision", str(current["state_revision"]), "--result", "accepted", "--summary", "M1 accepted", "--evidence", "all assertions passed")
        self.assertEqual(review["review_result"], "accepted")
        current = self.cli("status", "--compact")
        self.assertTrue(current["continuity"]["exit_snapshots"])
        self.assertEqual(self.cli("milestone", "frontier")["milestones"], ["m2"])
        m2_inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m2")
        self.cli("milestone", "compile", "apply", "--milestone", "m2", "--plan-revision", "3", "--state-revision", str(current["state_revision"]), "--expected-facts-sha256", m2_inspection["repository_facts_sha256"], "--reason", "compile M2", "--packet-json", json.dumps(self.packets("m2-")))
        final = self.cli("status", "--compact")
        p1 = next(proof for proof in final["continuity"]["proofs"] if proof.get("node_id") == "p1")
        p1_node = next(node for node in final["continuity"]["plan"]["nodes"] if node.get("id") == "p1")
        self.assertTrue(p1["fresh"], msg=json.dumps({"proof": p1, "node": p1_node}, ensure_ascii=False, indent=2))
        (self.repo / "src" / "a.py").write_text("VALUE = 9\n", encoding="utf-8")
        upgrade = self.cli("legacy-upgrade", "inspect", check=False)
        self.assertEqual(upgrade.get("revalidation_targets", []), [])

    def test_compile_apply_rejects_stale_repository_facts(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        (self.repo / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "stale compile", "--packet-json", json.dumps(self.packets()),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("compiler facts are stale", rejected["stderr"])

    def test_compile_derives_packet_policy_and_integration_waves(self) -> None:
        self.rolling_plan()
        self.enable_parallel_work()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["policy"] = {
            "execution_topology": "multi_agent",
            "merge_mode": "worktree_merge_queue",
            "verification_floor": ["packet_proof", "integration_proof"],
            "review_budget": 2,
            "conflict_owner": "integrator",
        }
        packets["nodes"][0].update({
            "execution_profile": "bounded",
            "review_policy": "quick",
            "model_profile": "bounded_worker",
            "verification_policy": {
                "required": ["unit"],
                "post_merge": ["integration"],
                "blocking": True,
            },
        })
        packets["nodes"][1].update({
            "execution_profile": "governed",
            "required_capabilities": ["parallel-work"],
            "review_policy": "strong",
            "merge_policy": {
                "mode": "worktree_merge_queue",
                "conflict_owner": "integrator",
                "pre_merge": True,
            },
        })
        packets["nodes"][2]["merge_policy"] = {
            "mode": "worktree_merge_queue",
            "conflict_owner": "integrator",
            "pre_merge": False,
        }
        compiled = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile packet policy", "--packet-json", json.dumps(packets),
        )
        self.assertEqual(compiled["compilation_policy"]["execution_topology"], "multi_agent")
        self.assertEqual(compiled["compilation_policy"]["dispatch_status"], "planned")
        self.assertEqual(compiled["execution_decision"]["recommended_mode"], "multi_worker")
        self.assertEqual(compiled["execution_decision"]["status"], "pending")
        self.assertEqual(compiled["frontier"]["execution_topology"], "multi_agent")
        self.assertEqual(compiled["frontier"]["dispatch_status"], "confirmation_required")
        self.assertEqual(compiled["frontier"]["phase1_execution_mode"], "serial")
        current = self.cli("status", "--compact")
        nodes = {node["id"]: node for node in current["continuity"]["plan"]["nodes"]}
        self.assertEqual(nodes["p1"]["review_policy"], "quick")
        self.assertEqual(nodes["p2"]["execution_profile"], "governed")
        self.assertEqual(nodes["p2"]["required_capabilities"], ["parallel-work"])
        self.assertEqual(nodes["p1"]["integration_wave"], 1)
        self.assertEqual(nodes["p2"]["integration_wave"], 1)
        self.assertIsNone(nodes["integrate"].get("integration_wave"))
        self.assertEqual(
            current["continuity"]["plan"]["nodes"][0].get("node_role"), "milestone"
        )
        milestone = nodes["m1"]["milestone_state"]
        self.assertEqual(milestone["merge_mode"], "worktree_merge_queue")
        self.assertEqual(milestone["compilation_policy"]["review_budget"], 2)
        selected = self.select_execution("m1", "multi_worker")
        active_ids = {
            node["id"] for node in self.cli("status", "--compact")["continuity"]["plan"]["nodes"]
            if node.get("status") == "active" and node.get("node_role") == "work_packet"
        }
        self.assertEqual(active_ids, {"p1", "p2"})
        self.assertEqual(selected["execution_decision"]["selected_mode"], "multi_worker")

    def test_single_agent_cannot_select_worktree_merge_queue(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["policy"] = {
            "execution_topology": "single_agent",
            "merge_mode": "worktree_merge_queue",
        }
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "invalid merge topology", "--packet-json", json.dumps(packets),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("requires execution_topology=multi_agent", rejected["stderr"])

    def test_packet_capability_must_be_enabled_at_root(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][0]["required_capabilities"] = ["gui"]
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "missing root capability", "--packet-json", json.dumps(packets),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("Root capabilities that are not enabled", rejected["stderr"])
        self.assertIn('"gui"', rejected["stderr"])

    def test_compile_rejects_unordered_overlapping_write_scopes(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][1]["write_scope"] = ["src/a.py"]
        packets["nodes"][1]["exclusive_claims"] = ["src/a.py"]
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "conflicting compile", "--packet-json", json.dumps(packets),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("unordered_write_conflict", rejected["stderr"])

    def test_compile_rejects_scope_outside_task_and_unsupported_glob(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        outside = self.packets()
        outside["nodes"][0]["write_scope"] = ["README.md"]
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "outside task scope", "--packet-json", json.dumps(outside),
            check=False,
        )
        self.assertIn("outside the Task planned_scope", rejected["stderr"])

        globbed = self.packets()
        globbed["nodes"][0]["write_scope"] = ["src/*.py"]
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "unsupported glob scope", "--packet-json", json.dumps(globbed),
            check=False,
        )
        self.assertIn("does not support glob patterns", rejected["stderr"])

    def test_compile_requires_typed_evidence_recipe(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][0]["outcome"]["proofs"][0]["recipe"]["evidence_file"] = "report.json"
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "untyped evidence", "--packet-json", json.dumps(packets),
            check=False,
        )
        self.assertIn("requires a supported evidence_schema", rejected["stderr"])

    def test_single_worker_does_not_require_parallel_work(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile single worker", "--packet-json", json.dumps(self.packets()),
        )
        self.select_execution("m1", "single_worker")
        prepared = self.cli(
            "milestone", "worker", "prepare", "--packet", "p1", "--worker-id", "worker-single"
        )
        self.assertEqual(prepared["worker"]["execution_mode"], "single_worker")
        self.assertEqual(prepared["worker"]["worker_profile"], "light_worker")
        self.assertEqual(prepared["worker"]["executor"]["model"], "gpt-5.6-luna")
        self.cli("milestone", "worker", "cleanup", "--worker-id", "worker-single")

    def test_external_worker_requires_explicit_executor_and_preserves_it(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile external worker", "--packet-json", json.dumps(self.packets()),
        )
        state = self.cli("status", "--compact")
        rejected = self.cli(
            "milestone", "execution", "select", "--milestone", "m1",
            "--mode", "single_worker", "--worker-profile", "external_worker",
            "--plan-revision", str(state["continuity"]["plan"]["revision"]),
            "--state-revision", str(state["state_revision"]),
            "--confirmation-source", "external worker fixture",
            check=False,
        )
        self.assertIn("requires explicit executor fields", rejected["stderr"])
        selected = self.cli(
            "milestone", "execution", "select", "--milestone", "m1",
            "--mode", "single_worker", "--worker-profile", "external_worker",
            "--worker-provider", "deepseek", "--worker-model", "deepseek-v4-flash",
            "--worker-reasoning", "max",
            "--plan-revision", str(state["continuity"]["plan"]["revision"]),
            "--state-revision", str(state["state_revision"]),
            "--confirmation-source", "external worker fixture",
        )
        self.assertEqual(selected["execution_decision"]["executor"]["model"], "deepseek-v4-flash")
        prepared = self.cli(
            "milestone", "worker", "prepare", "--packet", "p1",
            "--worker-id", "worker-external",
        )
        self.assertEqual(prepared["worker"]["worker_profile"], "external_worker")
        self.assertEqual(prepared["worker"]["executor"]["source"], "explicit")
        self.cli("milestone", "worker", "cleanup", "--worker-id", "worker-external")

    def test_task_glob_scope_contains_exact_packet_path(self) -> None:
        (self.repo / "tools").mkdir()
        (self.repo / "tools" / "reverse_one.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.execute("git", "add", "tools/reverse_one.py")
        self.execute("git", "commit", "-qm", "add reverse tool")
        current = self.cli("status", "--compact")
        self.cli(
            "task", "amend-scope", "--state-revision", str(current["state_revision"]),
            "--kind", "adjacent", "--reason", "cover reverse tool family",
            "--scope", "tools/reverse_*.py",
        )
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][0]["target"] = "tools/reverse_one.py"
        packets["nodes"][0]["write_scope"] = ["tools/reverse_one.py"]
        packets["nodes"][0]["exclusive_claims"] = ["tools/reverse_one.py"]
        packets["nodes"][2]["write_scope"] = ["tools/reverse_one.py", "src/b.py"]
        compiled = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile glob-backed scope", "--packet-json", json.dumps(packets),
        )
        self.assertEqual(compiled["status"], "compiled")

    def test_compile_rejects_failed_proof_preflight_without_state_write(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][0]["outcome"]["proofs"][0]["recipe"]["preflight_argv"] = [
            "python3", "-c", "import sys; sys.exit(7)",
        ]
        rejected = self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "reject broken preflight", "--packet-json", json.dumps(packets),
            check=False,
        )
        self.assertIn("preflight failed", rejected["stderr"])
        after = self.cli("status", "--compact")
        self.assertEqual(after["state_revision"], state["state_revision"])
        self.assertEqual(self.cli("milestone", "frontier")["milestones"], ["m1"])

    def test_observed_paths_ignore_unrelated_sibling_changes(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        packets = self.packets()
        packets["nodes"][0]["outcome"]["proofs"][0]["recipe"]["observed_paths"] = [
            "src/a.py"
        ]
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile observed paths", "--packet-json", json.dumps(packets),
        )
        self.select_execution("m1", "main_session")
        current = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "p1", "--proof-id", "p1-proof",
            "--plan-revision", "2", "--state-revision", str(current["state_revision"]),
            "--command", "python3 -c pass",
        )
        (self.repo / "src" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
        sibling = self.cli("status", "--compact")
        proof = next(
            item for item in sibling["continuity"]["latest_proofs"]
            if item["node_id"] == "p1"
        )
        self.assertTrue(proof["fresh"])
        (self.repo / "src" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
        changed = self.cli("status", "--compact")
        proof = next(
            item for item in changed["continuity"]["latest_proofs"]
            if item["node_id"] == "p1"
        )
        self.assertFalse(proof["fresh"])

    def test_old_compiled_milestone_can_be_revalidated_locally(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile legacy simulation", "--packet-json", json.dumps(self.packets()),
        )
        current = self.cli("status", "--compact")
        task_id = current["id"]
        task_path = self.repo / ".auto-dev" / "tasks" / f"{task_id}.json"
        receipt = json.loads(task_path.read_text(encoding="utf-8"))
        milestone = next(
            node for node in receipt["continuity"]["plan"]["nodes"] if node.get("id") == "m1"
        )
        milestone["milestone_state"].pop("execution_decision", None)
        milestone["milestone_state"]["compilation_snapshot"].pop("packet_contracts_sha256", None)
        task_path.write_text(json.dumps(receipt), encoding="utf-8")
        (self.repo / ".auto-dev" / "active.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        rejected = self.cli(
            "milestone", "execution", "inspect", "--milestone", "m1", check=False
        )
        self.assertEqual(rejected["status"], "policy_revalidation_required")
        revalidated = self.cli(
            "milestone", "execution", "revalidate", "--milestone", "m1",
            "--plan-revision", "2", "--state-revision", str(receipt["state_revision"]),
        )
        self.assertEqual(revalidated["status"], "revalidated")
        self.assertEqual(revalidated["execution_decision"]["status"], "pending")

    def test_packet_rework_invalidates_old_packet_proof(self) -> None:
        self.rolling_plan()
        state = self.cli("status", "--compact")
        inspection = self.cli("milestone", "compile", "inspect", "--milestone", "m1")
        self.cli(
            "milestone", "compile", "apply", "--milestone", "m1",
            "--plan-revision", "1", "--state-revision", str(state["state_revision"]),
            "--expected-facts-sha256", inspection["repository_facts_sha256"],
            "--reason", "compile M1", "--packet-json", json.dumps(self.packets()),
        )
        self.select_execution("m1", "main_session")
        current = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "p1", "--proof-id", "p1-proof",
            "--plan-revision", "2", "--state-revision", str(current["state_revision"]),
            "--command", "python3 -c pass",
        )
        current = self.cli("status", "--compact")
        self.cli(
            "checkpoint", "--node", "p1", "--plan-revision", "2",
            "--state-revision", str(current["state_revision"]), "--status", "done",
            "--summary", "p1 done", "--evidence", "p1 proof",
        )
        current = self.cli("status", "--compact")
        self.cli(
            "milestone", "review", "record", "--milestone", "m1",
            "--plan-revision", "2", "--state-revision", str(current["state_revision"]),
            "--result", "packet_rework_required", "--packet", "p1",
            "--summary", "p1 requires rework", "--evidence", "review finding",
        )
        after = self.cli("status", "--compact")
        proof = next(item for item in after["continuity"]["proofs"] if item.get("node_id") == "p1")
        node = next(item for item in after["continuity"]["plan"]["nodes"] if item.get("id") == "p1")
        self.assertFalse(proof["fresh"])
        self.assertEqual(node["status"], "active")
        self.assertEqual(after["continuity"]["current_node"], "p1")


if __name__ == "__main__":
    unittest.main()
