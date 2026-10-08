"""P0 regression tests for verification continuity and Git archive points."""

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


class P0MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-p0-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.exec("git", "init", "-q")
        self.exec("git", "config", "user.name", "Auto Dev P0 Test")
        self.exec("git", "config", "user.email", "auto-dev-p0@example.com")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.exec("git", "add", "README.md")
        self.exec("git", "commit", "-qm", "initial")
        self.exec("git", "checkout", "-qb", "p0-test")
        self.cli("project", "init", "--confirmation-source", "p0 project")
        self.cli(
            "start",
            "--tier", "team",
            "--task", "Exercise P0 continuity",
            "--requirement-receipt", "REQ-P0",
            "--confirmation-source", "p0 task",
            "--acceptance", "P0 state is durable",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--skip", "architecture=not needed in P0 fixture",
            "--skip", "compliance=not needed in P0 fixture",
            "--skip", "data-contract=not needed in P0 fixture",
            "--skip", "debug-observability=not needed in P0 fixture",
            "--skip", "gui=not needed in P0 fixture",
            "--skip", "parallel-work=not needed in P0 fixture",
            "--skip", "release=not needed in P0 fixture",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def exec(self, *arguments: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), cwd=cwd or self.repo, text=True,
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

    def plan(self, *, node_kind: str = "delivery", status: str = "active") -> dict[str, Any]:
        plan = {
            "goal": {
                "statement": "Exercise P0 continuity",
                "acceptance": ["P0 state is durable"],
                "source": "p0 task",
            },
            "nodes": [{
                "id": "implement",
                "title": "Implement P0",
                "status": status,
                "node_kind": node_kind,
                "outcome": {
                    "kind": "behavior_change",
                    "primary": "P0 state is durable",
                    "proofs": [{"id": "p0-proof", "description": "Run P0 proof"}],
                },
                "verification": {
                    "scope": ["p0"],
                    "phase_refs": ["targeted", "observation"],
                    "scenario_refs": ["p0-evidence-contract"],
                    "gate": "blocking",
                    "placement_reason": "P0 regression fixture",
                    "expected": "P0 proof records the current outcome",
                    "actual": "P0 fixture has not yet run the proof",
                },
                **({"historical_completion": {
                    "summary": "P0 fixture was already recorded",
                    "evidence": ["P0 migration test"],
                    "confirmation_source": "P0 fixture",
                }} if status == "done" else {}),
            }],
            "current_node": None if status == "done" else "implement",
            "next_action": "run P0 proof",
        }
        return self.cli("plan", "--base-revision", "0", "--reason", "P0 fixture", "--plan-json", json.dumps(plan))

    def test_proof_attempts_are_append_only_and_latest_projection_is_fresh(self) -> None:
        self.plan()
        first = self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", "1", "--state-revision", "2",
            "--command", "python3 -c 'raise SystemExit(1)'", check=False,
        )
        self.assertNotEqual(first["returncode"], 0)
        second = self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", "1", "--state-revision", "3",
            "--command", "python3 -c 'pass'",
        )
        self.assertEqual(second["status"], "passed")
        status = self.cli("status", "--compact")
        proofs = status["continuity"]["proofs"]
        self.assertEqual(len(proofs), 2)
        self.assertEqual([proof["status"] for proof in proofs], ["failed", "passed"])
        self.assertEqual(proofs[-1]["attempt_index"], 2)
        self.assertTrue(proofs[-1]["fresh"])
        self.assertEqual(status["continuity"]["latest_proofs"][-1]["attempt_count"], 2)

    def test_latest_failed_attempt_is_not_hidden_by_an_earlier_green(self) -> None:
        self.plan()
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        state = self.cli("status", "--compact")
        failed = self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'raise SystemExit(1)'",
            "--failure-classification", "environment",
            check=False,
        )
        self.assertNotEqual(failed["returncode"], 0)
        failed_proof = json.loads(failed["stdout"])
        self.assertEqual(failed_proof["task_id"], self.cli("status", "--compact")["id"])
        self.assertEqual(failed_proof["failure_classification"], "environment")

        status = self.cli("status", "--compact")
        latest = status["continuity"]["latest_proofs"][-1]
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["attempt_count"], 2)
        self.assertEqual(status["outcome_summary"]["passed_proofs"], 0)
        self.assertEqual(status["outcome_summary"]["failed_proofs"], 1)
        self.assertEqual(status["outcome_summary"]["pending_proofs"], 0)

    def test_typed_milestone_metadata_round_trips_through_plan_and_handoff(self) -> None:
        self.plan(node_kind="verification")
        status = self.cli("status", "--compact")
        node = status["continuity"]["plan"]["nodes"][0]
        self.assertEqual(node["node_kind"], "verification")
        self.assertEqual(node["verification"]["gate"], "blocking")
        self.assertEqual(node["verification"]["scenario_refs"], ["p0-evidence-contract"])
        self.assertEqual(node["verification"]["expected"], "P0 proof records the current outcome")
        handoff = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(handoff))
        packet = json.loads(handoff.read_text(encoding="utf-8"))
        packet_node = packet["continuity"]["plan"]["nodes"][0]
        self.assertEqual(packet_node["node_kind"], "verification")
        self.assertEqual(packet_node["verification"]["placement_reason"], "P0 regression fixture")
        self.assertEqual(packet_node["verification"]["actual"], "P0 fixture has not yet run the proof")

    def test_done_node_without_proof_is_needs_reconcile_after_handoff_import(self) -> None:
        self.plan(status="done")
        handoff = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(handoff))
        target = self.root / "target"
        target.mkdir()
        result = self.exec("git", "clone", "-q", "-b", "p0-test", str(self.repo), str(target))
        self.assertEqual(result.returncode, 0)
        imported = subprocess.run(
            [sys.executable, str(CLI), "handoff", "import", "--repo-root", str(target), "--file", str(handoff)],
            cwd=target, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(imported.returncode, 0, msg=imported.stderr)
        payload = json.loads(imported.stdout)
        self.assertEqual(payload["continuity_status"], "needs_reconcile")

    def test_handoff_preserves_attempt_history_and_recomputes_latest_projection(self) -> None:
        self.plan()
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'raise SystemExit(1)'",
            "--failure-classification", "flaky",
            check=False,
        )
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        handoff = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(handoff))
        target = self.root / "target"
        target.mkdir()
        self.exec("git", "clone", "-q", "-b", "p0-test", str(self.repo), str(target))
        imported = subprocess.run(
            [sys.executable, str(CLI), "handoff", "import", "--repo-root", str(target), "--file", str(handoff)],
            cwd=target, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(imported.returncode, 0, msg=imported.stderr)
        status = subprocess.run(
            [sys.executable, str(CLI), "status", "--compact", "--repo-root", str(target)],
            cwd=target, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(status.returncode, 0, msg=status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual([proof["status"] for proof in payload["continuity"]["proofs"]], ["failed", "passed"])
        self.assertEqual(payload["continuity"]["proofs"][0]["failure_classification"], "flaky")
        latest = payload["continuity"]["latest_proofs"][-1]
        self.assertEqual(latest["attempt_count"], 2)
        self.assertTrue(latest["fresh"])

    def test_workspace_checkpoint_inspect_is_read_only_and_create_is_scoped(self) -> None:
        before = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        inspected = self.cli("workspace", "checkpoint", "inspect")
        after = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(inspected["status"], "ready")

        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")
        preview = self.cli(
            "workspace", "checkpoint", "inspect", "--kind", "archive", "--scope", "README.md",
        )
        self.assertEqual(preview["status"], "ready")
        created = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive",
            "--scope", "README.md", "--confirmation-source", "user approved p0 archive",
        )
        self.assertTrue(created["ref"].startswith("refs/tags/auto-dev/"))
        self.assertTrue(created["receipt"].startswith("💾 Auto Dev 存档点：成果固化"))
        self.assertEqual(created["checkpoint"]["archive_phase"], "after_change")
        self.assertEqual(created["checkpoint"]["receipt_key"], "workspace_checkpoint_after")
        self.assertEqual(self.exec("git", "rev-parse", "--verify", created["ref"]).returncode, 0)
        before_rollback = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        rollback = self.cli("workspace", "rollback", "inspect", "--target", created["ref"])
        after_rollback = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        self.assertEqual(before_rollback, after_rollback)
        self.assertEqual(rollback["apply"], "deferred")
        self.assertEqual(rollback["archive_point"]["status"], "recorded")
        self.assertEqual(rollback["task_owned_paths"], ["README.md"])

    def test_workspace_checkpoint_list_reconciles_refs_and_receipts(self) -> None:
        baseline = self.cli(
            "workspace", "checkpoint", "create", "--kind", "baseline",
            "--confirmation-source", "user approved before implementation",
        )
        self.assertTrue(baseline["receipt"].startswith("💾 Auto Dev 存档点：开工保护"))
        self.assertIn(f"commit={baseline['checkpoint']['object'][:8]}", baseline["receipt"])
        self.assertEqual(baseline["checkpoint"]["archive_phase"], "before_change")
        self.assertEqual(baseline["checkpoint"]["receipt_key"], "workspace_checkpoint_before")
        self.assertEqual(baseline["checkpoint"]["scope"], ["README.md"])

        before_list = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        listed = self.cli("workspace", "checkpoint", "list")
        after_list = sorted(path.relative_to(self.repo).as_posix() for path in self.repo.rglob("*"))
        self.assertEqual(before_list, after_list)
        recorded = next(point for point in listed["checkpoints"] if point["ref"] == baseline["ref"])
        self.assertEqual(recorded["status"], "recorded")
        self.assertEqual(recorded["checkpoint"]["receipt"], baseline["receipt"])
        self.assertEqual(recorded["task_ids"], [self.cli("status", "--compact")["id"]])
        status = self.cli("status", "--compact")
        projected = next(
            point for point in status["continuity_summary"]["workspace_points"]
            if point["ref"] == baseline["ref"]
        )
        self.assertEqual(projected["status"], "recorded")
        self.assertEqual(status["continuity_summary"]["workspace_point_counts"]["recorded"], 1)

        self.exec("git", "tag", "-a", "auto-dev/manual-untracked", "-m", "manual untracked point")
        listed = self.cli("workspace", "checkpoint", "list")
        untracked = next(point for point in listed["checkpoints"] if point["ref"] == "refs/tags/auto-dev/manual-untracked")
        self.assertEqual(untracked["status"], "untracked")
        self.assertIsNone(untracked["checkpoint"])

        self.exec("git", "tag", "-d", baseline["ref"].removeprefix("refs/tags/"))
        listed = self.cli("workspace", "checkpoint", "list")
        missing = next(point for point in listed["checkpoints"] if point["ref"] == baseline["ref"])
        self.assertEqual(missing["status"], "missing_ref")
        self.assertEqual(missing["checkpoint"]["id"], baseline["checkpoint"]["id"])

    def test_standalone_baseline_projects_to_its_unique_proof_node(self) -> None:
        self.plan()
        baseline = self.cli(
            "workspace", "checkpoint", "create", "--kind", "baseline",
            "--confirmation-source", "user approved legacy-compatible baseline",
        )
        self.assertEqual(baseline["checkpoint"]["proof_refs"], ["implement:p0-proof"])

        status = self.cli("status", "--compact")
        self.assertEqual(status["workspace_checkpoint_protection"]["status"], "unprotected")
        milestone = status["workspace_checkpoint_nodes"]["implement"][0]
        self.assertEqual(milestone["projection"], "standalone")
        self.assertIsNone(milestone["protection_id"])
        self.assertEqual(milestone["before"]["status"], "recorded")
        self.assertEqual(milestone["before"]["ref"], baseline["ref"])
        self.assertEqual(milestone["before"]["object"], baseline["checkpoint"]["object"])
        self.assertEqual(
            milestone["before"]["short_hash"], baseline["checkpoint"]["object"][:8]
        )
        self.assertEqual(milestone["after"]["status"], "pending")

    def test_workspace_checkpoint_rejects_broad_staged_user_and_sensitive_scope(self) -> None:
        broad = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive", "--scope", ".",
            "--confirmation-source", "user approved broad", check=False,
        )
        self.assertNotEqual(broad["returncode"], 0)
        (self.repo / "README.md").write_text("staged\n", encoding="utf-8")
        self.exec("git", "add", "README.md")
        staged = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive", "--scope", "README.md",
            "--confirmation-source", "user approved staged", check=False,
        )
        self.assertNotEqual(staged["returncode"], 0)
        self.exec("git", "reset", "-q", "HEAD", "--", "README.md")
        (self.repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
        sensitive = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive", "--scope", ".env",
            "--confirmation-source", "user approved secret", check=False,
        )
        self.assertNotEqual(sensitive["returncode"], 0)

    def test_workspace_checkpoint_ignores_control_metadata_and_exact_sensitive_names(self) -> None:
        (self.repo / ".codegraph").mkdir()
        (self.repo / ".codegraph" / "index.json").write_text("{}\n", encoding="utf-8")
        (self.repo / ".conductor").mkdir()
        (self.repo / ".conductor" / "m5.md").write_text("control notes\n", encoding="utf-8")
        self.exec("git", "add", ".codegraph", ".conductor")

        controls_only = self.cli("workspace", "checkpoint", "inspect", "--kind", "baseline")
        self.assertEqual(controls_only["status"], "ready")
        self.assertEqual(controls_only["dirty"], [])
        self.assertEqual(controls_only["staged"], [])
        self.assertEqual(
            controls_only["control_metadata_staged"],
            [".codegraph/index.json", ".conductor/m5.md"],
        )

        (self.repo / "credentialResolver.js").write_text("export default null;\n", encoding="utf-8")
        normal_baseline = self.cli(
            "workspace", "checkpoint", "inspect", "--kind", "baseline",
            "--scope", "credentialResolver.js",
        )
        self.assertEqual(normal_baseline["status"], "blocked")
        self.assertTrue(normal_baseline["dirty_baseline_requires_protection"])
        preview = self.cli(
            "workspace", "checkpoint", "inspect", "--kind", "archive",
            "--scope", "credentialResolver.js",
        )
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["forbidden"], [])
        self.assertEqual(preview["dirty"], ["credentialResolver.js"])

    def test_protected_checkpoint_transaction_requires_before_and_after_points(self) -> None:
        self.plan()
        armed = self.cli(
            "workspace", "checkpoint", "protect", "--node", "implement",
            "--scope", "README.md", "--confirmation-source", "user requires M5 protection",
        )
        protection_id = armed["protection"]["id"]
        self.assertEqual(armed["status"], "armed")
        self.assertTrue(armed["receipt"].startswith("💾 Auto Dev 存档保护："))
        self.assertEqual(
            self.cli("status", "--compact")["workspace_checkpoint_protection"]["before_pending"],
            [protection_id],
        )

        (self.repo / "README.md").write_text("user-owned baseline\n", encoding="utf-8")
        before_preview = self.cli(
            "workspace", "checkpoint", "inspect", "--kind", "baseline",
            "--protection-id", protection_id,
        )
        self.assertEqual(before_preview["status"], "ready")
        self.assertTrue(before_preview["allow_dirty_baseline"])
        before = self.cli(
            "workspace", "checkpoint", "create", "--kind", "baseline",
            "--protection-id", protection_id,
            "--confirmation-source", "user confirms pre-write checkpoint",
        )
        self.assertEqual(before["checkpoint"]["protection_id"], protection_id)
        self.assertIn(f"commit={before['checkpoint']['object'][:8]}", before["receipt"])
        self.assertEqual(self.exec("git", "status", "--short").stdout, "")
        before_status = self.cli("status", "--compact")
        before_points = before_status["workspace_checkpoint_nodes"]["implement"][0]
        self.assertEqual(before_points["protection_id"], protection_id)
        self.assertEqual(before_points["before"]["object"], before["checkpoint"]["object"])
        self.assertEqual(before_points["before"]["short_hash"], before["checkpoint"]["object"][:8])
        self.assertEqual(before_points["after"]["status"], "pending")

        (self.repo / "README.md").write_text("implemented\n", encoding="utf-8")
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        state = self.cli("status", "--compact")
        self.cli(
            "checkpoint", "--node", "implement", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "protected M5 proof passed",
            "--evidence", "P0 proof passed",
        )

        state = self.cli("status", "--compact")
        review_before_after = self.cli(
            "task", "review", "--state-revision", str(state["state_revision"]),
            "--summary", "protected delivery pending archive", "--file", "README.md",
            "--validation", "python3 -c pass", check=False,
        )
        self.assertNotEqual(review_before_after["returncode"], 0)
        self.assertIn("requires a recorded archive", review_before_after["stderr"])

        after_preview = self.cli(
            "workspace", "checkpoint", "inspect", "--kind", "archive",
            "--protection-id", protection_id,
        )
        self.assertEqual(after_preview["required_proofs"], ["implement:p0-proof"])
        self.assertEqual(after_preview["missing_proofs"], [])
        after = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive",
            "--protection-id", protection_id,
            "--confirmation-source", "user confirms post-write checkpoint",
        )
        self.assertEqual(after["checkpoint"]["protection_id"], protection_id)
        self.assertIn(f"commit={after['checkpoint']['object'][:8]}", after["receipt"])
        protected_status = self.cli("status", "--compact")
        protected = protected_status["workspace_checkpoint_protection"]
        self.assertEqual(protected["status"], "protected")
        self.assertEqual(protected["after_pending"], [])
        milestone_points = protected_status["workspace_checkpoint_nodes"]["implement"][0]
        self.assertEqual(milestone_points["before"]["short_hash"], before["checkpoint"]["object"][:8])
        self.assertEqual(milestone_points["after"]["object"], after["checkpoint"]["object"])
        self.assertEqual(milestone_points["after"]["short_hash"], after["checkpoint"]["object"][:8])

        state = self.cli("status", "--compact")
        reviewed = self.cli(
            "task", "review", "--state-revision", str(state["state_revision"]),
            "--summary", "protected delivery reviewed", "--file", "README.md",
            "--validation", "python3 -c pass",
        )
        self.assertEqual(reviewed["status"], "review_ready")
        finished = self.cli(
            "finish", "--status", "passed", "--summary", "protected delivery accepted",
            "--confirmation-source", "user accepted protected review",
        )
        self.assertEqual(finished["status"], "passed")

    def test_protected_checkpoint_ref_loss_blocks_completion(self) -> None:
        self.plan()
        armed = self.cli(
            "workspace", "checkpoint", "protect", "--node", "implement",
            "--scope", "README.md", "--confirmation-source", "user requires tag readback",
        )
        protection_id = armed["protection"]["id"]
        self.cli(
            "workspace", "checkpoint", "create", "--kind", "baseline",
            "--protection-id", protection_id,
            "--confirmation-source", "user confirms baseline",
        )
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        state = self.cli("status", "--compact")
        self.cli(
            "checkpoint", "--node", "implement", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "proof passed", "--evidence", "P0 proof passed",
        )
        after = self.cli(
            "workspace", "checkpoint", "create", "--kind", "archive",
            "--protection-id", protection_id,
            "--confirmation-source", "user confirms archive",
        )
        self.exec("git", "tag", "-d", after["ref"].removeprefix("refs/tags/"))
        status = self.cli("status", "--compact")
        self.assertEqual(status["workspace_checkpoint_protection"]["after_invalid"], [protection_id])
        self.assertIn("workspace_checkpoint_protection_invalid", status["strict_blockers"])
        review = self.cli(
            "task", "review", "--state-revision", str(status["state_revision"]),
            "--summary", "missing protected tag", "--file", "README.md",
            "--validation", "python3 -c pass", check=False,
        )
        self.assertNotEqual(review["returncode"], 0)
        self.assertIn("archive ref is missing or mismatched", review["stderr"])

    def test_proof_becomes_stale_when_scoped_file_changes(self) -> None:
        self.plan()
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", "1", "--state-revision", "2",
            "--command", "python3 -c 'pass'",
        )
        (self.repo / "README.md").write_text("changed after proof\n", encoding="utf-8")
        status = self.cli("status", "--compact")
        self.assertFalse(status["continuity"]["proofs"][-1]["fresh"])
        self.assertEqual(status["outcome_summary"]["pending_proofs"], 1)

    def test_checkpointed_proof_becomes_stale_when_its_scope_changes(self) -> None:
        self.plan()
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "implement", "--proof-id", "p0-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        state = self.cli("status", "--compact")
        self.cli(
            "checkpoint", "--node", "implement", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "P0 proof checkpointed",
            "--evidence", "P0 proof passed",
        )
        (self.repo / "README.md").write_text("changed after checkpoint\n", encoding="utf-8")

        status = self.cli("status", "--compact")
        self.assertEqual(status["continuity_status"], "needs_reconcile")
        self.assertFalse(status["continuity"]["latest_proofs"][-1]["fresh"])
        self.assertEqual(status["outcome_summary"]["pending_proofs"], 1)
        self.assertEqual(status["verification_issues"][0]["kind"], "stale_proof")


if __name__ == "__main__":
    unittest.main()
