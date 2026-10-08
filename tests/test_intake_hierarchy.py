#!/usr/bin/env python3
"""Regression coverage for Intake and hierarchical Auto Dev control state."""

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
SESSION_KEY = "0123456789abcdef01234567"


class IntakeHierarchyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.run_command("git", "init", "-q")
        self.run_command("git", "config", "user.name", "Auto Dev Test")
        self.run_command("git", "config", "user.email", "auto-dev@example.com")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.run_command("git", "add", "README.md")
        self.run_command("git", "commit", "-qm", "initial")
        self.run_command("git", "checkout", "-qb", "intake-hierarchy")
        self.cli("project", "init", "--confirmation-source", "test project initialization")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_command(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments),
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        result = self.run_command(sys.executable, str(CLI), *arguments, "--repo-root", str(self.repo), check=check)
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def project_context(self) -> tuple[str, int]:
        payload = self.cli("project-context", "list")
        return str(payload["default_context_id"]), int(payload["project_revision"])

    def clear_intake(
        self,
        *,
        turn_id: str = "turn-clear",
        contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.cli("intake", "turn", "--session-key", SESSION_KEY, "--turn-id", turn_id)
        arguments = [
            "intake",
            "assess",
            "--session-key", SESSION_KEY,
            "--turn-id", turn_id,
            "--depth", "clear",
            "--summary", "bounded existing behavior correction",
            "--goal", "correct one local behavior",
            "--inference", "the user needs a scoped correction without a product decision",
            "--scope", "README.md",
            "--acceptance", "the corrected behavior is observable",
        ]
        if contract is not None:
            arguments.extend(["--contract-json", json.dumps(contract)])
        return self.cli(*arguments)

    def test_generated_control_plane_defaults_are_chinese(self) -> None:
        project = json.loads((self.repo / ".auto-dev" / "project.json").read_text(encoding="utf-8"))
        context_id = str(project["default_context_id"])
        frame = json.loads(
            (self.repo / ".auto-dev" / "projects" / context_id / "frame.json").read_text(encoding="utf-8")
        )
        outcome_id = str(project["contexts"][context_id]["unlinked_outcome_id"])
        outcome = json.loads(
            (self.repo / ".auto-dev" / "projects" / context_id / "outcomes" / f"{outcome_id}.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(frame["title"], "仓库交付上下文")
        self.assertEqual(frame["authority_boundary"], "尚未建立")
        self.assertEqual(frame["delivery_boundary"], "当前仓库与当前分支的交付范围")
        self.assertEqual(frame["context_boundary"], "由 Auto Dev 逐步发现的仓库内工作")
        self.assertEqual(outcome["title"], "未归属工作收件箱")
        self.assertEqual(outcome["statement"], "尚未关联到产品结果的有界工作")

    def test_intake_clear_is_autonomous_and_deep_requires_later_turn(self) -> None:
        clear = self.clear_intake()
        self.assertEqual(clear["gate"]["status"], "authorized")
        self.assertEqual(clear["intake"]["depth"], "clear")
        self.assertIn("Requirement intake cleared", clear["receipt"])

        self.cli("intake", "turn", "--session-key", SESSION_KEY, "--turn-id", "turn-deep-1")
        deep = self.cli(
            "intake",
            "assess",
            "--session-key", SESSION_KEY,
            "--turn-id", "turn-deep-1",
            "--intake-id", "INTAKE-DEEP",
            "--depth", "deep",
            "--summary", "workflow policy has a product choice",
            "--goal", "introduce the policy-aware workflow",
            "--inference", "the user needs a durable product behavior",
            "--decision-json",
            json.dumps({
                "id": "policy",
                "question": "Which policy should apply?",
                "impact": "The visible workflow differs.",
                "recommendation": "Use the repository default.",
            }),
        )
        self.assertEqual(deep["gate"]["status"], "awaiting_user")
        rejected = self.cli(
            "intake",
            "confirm",
            "--session-key", SESSION_KEY,
            "--turn-id", "turn-deep-1",
            "--intake-id", "INTAKE-DEEP",
            "--intake-revision", "1",
            "--confirmation-source", "same turn",
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("later user turn", rejected["stderr"])

        self.cli("intake", "turn", "--session-key", SESSION_KEY, "--turn-id", "turn-deep-2")
        resolved = self.cli(
            "intake",
            "resolve",
            "--session-key", SESSION_KEY,
            "--turn-id", "turn-deep-2",
            "--intake-id", "INTAKE-DEEP",
            "--intake-revision", "1",
            "--decision-id", "policy",
            "--status", "accepted",
            "--resolution", "Use the repository default.",
            "--source", "user choice",
        )
        self.assertEqual(resolved["gate"]["status"], "awaiting_confirmation")
        confirmed = self.cli(
            "intake",
            "confirm",
            "--session-key", SESSION_KEY,
            "--turn-id", "turn-deep-2",
            "--intake-id", "INTAKE-DEEP",
            "--intake-revision", "2",
            "--confirmation-source", "user confirmed baseline",
        )
        self.assertEqual(confirmed["gate"]["status"], "authorized")
        self.assertIn("Requirement baseline confirmed", confirmed["receipt"])

    def test_outcome_dag_task_attribution_and_focus_are_separate(self) -> None:
        intake = self.clear_intake()
        intake_id = str(intake["intake"]["id"])
        context_id, project_revision = self.project_context()
        root = self.cli(
            "outcome",
            "add",
            "--project-revision", str(project_revision),
            "--project-context", context_id,
            "--outcome-id", "OUTCOME-ROOT",
            "--title", "Checkout result",
            "--statement", "Customers can complete checkout.",
            "--status", "active",
            "--intake-id", intake_id,
        )
        child = self.cli(
            "outcome",
            "add",
            "--project-revision", str(root["project_revision"]),
            "--project-context", context_id,
            "--outcome-id", "OUTCOME-CHILD",
            "--title", "Checkout validation",
            "--statement", "Checkout validation is observable.",
            "--parent-id", "OUTCOME-ROOT",
        )
        cycle = self.cli(
            "outcome",
            "link",
            "--project-revision", str(child["project_revision"]),
            "--project-context", context_id,
            "--source-id", "OUTCOME-CHILD",
            "--target-id", "OUTCOME-ROOT",
            "--relation", "depends_on",
            "--outcome-revision", "1",
            check=False,
        )
        self.assertNotEqual(cycle["returncode"], 0)
        self.assertIn("acyclic", cycle["stderr"])

        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Deliver the checkout slice",
            "--requirement-receipt", intake_id,
            "--confirmation-source", "user accepted the clear intake",
            "--project-context", context_id,
            "--outcome-id", "OUTCOME-ROOT",
            "--intake-id", intake_id,
            "--acceptance", "The checkout slice is delivered.",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "bounded delivery",
        )
        task_id = str(started["id"])
        focus = self.cli(
            "focus",
            "set",
            "--session-key", SESSION_KEY,
            "--project-context", context_id,
            "--kind", "outcome",
            "--focus-id", "OUTCOME-CHILD",
        )
        self.assertFalse(focus["execution_focus_changed"])
        status = self.cli("status", "--compact", "--session-key", SESSION_KEY)
        self.assertEqual(status["hierarchy"]["view_focus"]["id"], "OUTCOME-CHILD")
        self.assertEqual(status["hierarchy"]["execution_focus"]["task_id"], task_id)
        self.assertEqual(status["hierarchy"]["execution_focus"]["outcome_id"], "OUTCOME-ROOT")

    def test_skincard_strict_contract_blocks_greenfield_plan_and_requires_parity_proofs(self) -> None:
        contract = {
            "id": "SKINCARD-BASELINE",
            "mode": "legacy-parity",
            "mainline": "Fork skin-distributor-backend and replace only order entry with card redemption.",
            "hard_constraints": [
                {"id": "H-FORK", "text": "This is a fork/migration, not a greenfield admin."},
                {"id": "H-DELIVERY", "text": "Legacy delivery and risk controls need compatibility evidence."},
            ],
            "forbidden_moves": ["Do not create unreferenced overview, jobs, or audit product surfaces."],
            "replacement_map": [
                {"id": "R-ORDER", "from": "order entry", "to": "card redemption entry"},
            ],
            "required_coverage": [
                {"id": "C-ROUTES", "description": "Legacy admin route matrix", "evidence_kind": "route-matrix"},
                {"id": "C-DELIVERY", "description": "Legacy download and risk compatibility", "evidence_kind": "compatibility"},
            ],
        }
        intake = self.clear_intake(contract=contract)
        intake_id = str(intake["intake"]["id"])
        context_id, _ = self.project_context()
        frame = self.cli("project-context", "show", "--context-id", context_id)
        self.assertEqual(frame["context"]["contract"]["id"], "SKINCARD-BASELINE")

        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Migrate the first sample author path",
            "--requirement-receipt", intake_id,
            "--confirmation-source", "user confirmed fork migration baseline",
            "--project-context", context_id,
            "--intake-id", intake_id,
            "--acceptance", "The first migrated path preserves the declared legacy contract.",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "bounded migration fixture",
            "--coverage-id", "C-ROUTES",
            "--coverage-id", "C-DELIVERY",
        )
        self.assertEqual(started["status"], "active")

        missing_coverage_plan = {
            "goal": {"statement": "Migrate the sample author path", "acceptance": ["Parity is proven"], "source": "fixture"},
            "nodes": [
                {
                    "id": "M0", "title": "Legacy route inventory", "status": "active", "coverage_ids": ["C-ROUTES"],
                    "outcome": {
                        "kind": "knowledge_gain", "primary": "Legacy routes are mapped",
                        "proofs": [{"id": "route-proof", "description": "Record route matrix", "evidence_kind": "route-matrix", "coverage_ids": ["C-ROUTES"]}],
                    },
                },
            ],
            "current_node": "M0", "next_action": "record legacy routes",
        }
        rejected = self.cli(
            "plan", "--base-revision", "0", "--reason", "incorrect greenfield foundation", "--plan-json", json.dumps(missing_coverage_plan), check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("missing required coverage", rejected["stderr"])
        self.assertIn("C-DELIVERY", rejected["stderr"])

        wrong_evidence_plan = {
            **missing_coverage_plan,
            "nodes": [
                {
                    **missing_coverage_plan["nodes"][0],
                    "outcome": {
                        "kind": "knowledge_gain", "primary": "Legacy routes are mapped",
                        "proofs": [{"id": "route-proof", "description": "Build only", "evidence_kind": "build", "coverage_ids": ["C-ROUTES"]}],
                    },
                },
                {
                    "id": "M1", "title": "Delivery compatibility", "status": "planned", "depends_on": ["M0"], "coverage_ids": ["C-DELIVERY"],
                    "outcome": {
                        "kind": "behavior_change", "primary": "Delivery compatibility is proven",
                        "proofs": [{"id": "delivery-proof", "description": "Check compatibility", "evidence_kind": "compatibility", "coverage_ids": ["C-DELIVERY"]}],
                    },
                },
            ],
        }
        rejected = self.cli(
            "plan", "--base-revision", "0", "--reason", "build proof cannot claim parity", "--plan-json", json.dumps(wrong_evidence_plan), check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("requires evidence kind route-matrix", rejected["stderr"])

        valid_plan = {
            **wrong_evidence_plan,
            "nodes": [
                {
                    **wrong_evidence_plan["nodes"][0],
                    "outcome": {
                        "kind": "knowledge_gain", "primary": "Legacy routes are mapped",
                        "proofs": [{"id": "route-proof", "description": "Record route matrix", "evidence_kind": "route-matrix", "coverage_ids": ["C-ROUTES"]}],
                    },
                },
                wrong_evidence_plan["nodes"][1],
            ],
        }
        self.cli("plan", "--base-revision", "0", "--reason", "parity-aware migration plan", "--plan-json", json.dumps(valid_plan))
        state = self.cli("status", "--compact")
        self.assertEqual(state["contract_gate"]["status"], "strict")
        self.assertEqual(state["contract_gate"]["unplanned_coverage"], [])
        self.assertIn("C-ROUTES", state["contract_capsule"]["task_coverage"])

        self.cli(
            "proof", "--node", "M0", "--proof-id", "route-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'",
        )
        state = self.cli("status", "--compact")
        self.cli(
            "checkpoint", "--node", "M0", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "route inventory proved", "--evidence", "route matrix", "--next-node", "M1",
        )
        state = self.cli("status", "--compact")
        self.assertEqual(state["continuity_summary"]["current_node"], "M1")
        self.assertIn("C-DELIVERY", state["contract_gate"]["missing_coverage"])
        review = self.cli(
            "task", "review", "--state-revision", str(state["state_revision"]),
            "--summary", "incorrectly claiming migration completion", "--validation", "python3 -c pass", check=False,
        )
        self.assertNotEqual(review["returncode"], 0)
        self.assertIn("unfinished continuity nodes: M1", review["stderr"])

    def test_strict_parent_outcome_change_requires_diff_and_stales_existing_task(self) -> None:
        intake = self.clear_intake(contract={
            "id": "STRICT-BASELINE",
            "mode": "migration",
            "mainline": "Preserve the legacy product path while replacing only its entry mechanism.",
            "required_coverage": [
                {"id": "C-PARITY", "description": "Legacy parity", "evidence_kind": "compatibility"},
            ],
        })
        intake_id = str(intake["intake"]["id"])
        context_id, project_revision = self.project_context()
        outcome = self.cli(
            "outcome", "add", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-PARITY", "--title", "Legacy parity", "--statement", "Keep the legacy author workflow.",
            "--intake-id", intake_id,
        )
        started = self.cli(
            "start", "--tier", "direct", "--task", "Migrate the bounded author workflow",
            "--requirement-receipt", intake_id, "--confirmation-source", "user confirmed migration baseline",
            "--project-context", context_id, "--outcome-id", "OUTCOME-PARITY", "--intake-id", intake_id,
            "--acceptance", "The bounded migrated path preserves the parent outcome.",
            "--scope", "README.md", "--validation", "python3 -c pass", "--evidence", "fixture", "--coverage-id", "C-PARITY",
        )
        self.assertEqual(started["status"], "active")
        state = self.cli("status", "--compact")
        self.assertEqual(state["contract_gate"]["status"], "strict")
        project_revision = self.project_context()[1]

        rejected = self.cli(
            "outcome", "set", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-PARITY", "--outcome-revision", "1",
            "--statement", "Replace the legacy workflow with a generic admin.",
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("Requirement Diff confirmation", rejected["stderr"])

        changed = self.cli(
            "outcome", "set", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-PARITY", "--outcome-revision", "1",
            "--statement", "Replace the legacy workflow with a generic admin.",
            "--requirement-diff-confirmation", "user explicitly changed the parent outcome",
        )
        self.assertEqual(changed["outcome"]["state_revision"], 2)
        state = self.cli("status", "--compact")
        self.assertEqual(state["contract_gate"]["status"], "stale")
        self.assertIn("contract_stale", state["strict_blockers"])

    def test_strict_parent_outcome_cannot_complete_from_one_child_coverage(self) -> None:
        intake = self.clear_intake(contract={
            "id": "OUTCOME-ROLLUP",
            "mode": "migration",
            "mainline": "Preserve the migrated product path.",
            "required_coverage": [
                {"id": "C-ROUTES", "description": "Reference routes", "evidence_kind": "route-matrix"},
                {"id": "C-DELIVERY", "description": "Delivery compatibility", "evidence_kind": "compatibility"},
            ],
        })
        intake_id = str(intake["intake"]["id"])
        context_id, project_revision = self.project_context()
        outcome = self.cli(
            "outcome", "add", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-MIGRATION", "--title", "Migration", "--statement", "Preserve the product path.",
            "--intake-id", intake_id,
        )
        started = self.cli(
            "start", "--tier", "direct", "--task", "Inventory legacy routes",
            "--requirement-receipt", intake_id, "--confirmation-source", "user confirmed baseline",
            "--project-context", context_id, "--outcome-id", "OUTCOME-MIGRATION", "--intake-id", intake_id,
            "--acceptance", "Reference routes are mapped.", "--scope", "README.md", "--validation", "python3 -c pass",
            "--coverage-id", "C-ROUTES",
        )
        self.assertEqual(started["status"], "active")
        plan = {
            "goal": {
                "statement": "Inventory legacy routes",
                "acceptance": ["Reference routes are mapped."],
                "source": "test fixture",
            },
            "nodes": [{
                "id": "M0", "title": "Legacy routes", "status": "active", "coverage_ids": ["C-ROUTES"],
                "outcome": {
                    "kind": "knowledge_gain", "primary": "Reference routes are mapped",
                    "proofs": [{
                        "id": "route-proof", "description": "Verify the route inventory",
                        "evidence_kind": "route-matrix", "coverage_ids": ["C-ROUTES"],
                    }],
                },
            }],
            "current_node": "M0",
            "next_action": "run route proof",
        }
        self.cli("plan", "--base-revision", "0", "--reason", "route-only contribution", "--plan-json", json.dumps(plan))
        state = self.cli("status", "--compact")
        self.cli(
            "proof", "--node", "M0", "--proof-id", "route-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]), "--command", "python3 -c pass",
        )
        project_revision = self.project_context()[1]
        rejected = self.cli(
            "outcome", "set", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-MIGRATION", "--outcome-revision", str(outcome["outcome"]["state_revision"]),
            "--status", "completed", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("C-DELIVERY", rejected["stderr"])

    def test_artifact_backed_coverage_requires_a_matching_evidence_file(self) -> None:
        intake = self.clear_intake(contract={
            "id": "ARTIFACT-BASELINE",
            "mode": "strict",
            "mainline": "Keep reference evidence traceable.",
            "required_coverage": [{
                "id": "C-REFERENCE",
                "description": "Reference matrix",
                "evidence_kind": "artifact",
                "artifact_schema": "auto-dev/reference-matrix/v1",
            }],
        })
        intake_id = str(intake["intake"]["id"])
        context_id, project_revision = self.project_context()
        self.cli(
            "outcome", "add", "--project-revision", str(project_revision), "--project-context", context_id,
            "--outcome-id", "OUTCOME-ARTIFACT", "--title", "Artifact", "--statement", "Keep traceable evidence.",
            "--intake-id", intake_id,
        )
        self.cli(
            "start", "--tier", "direct", "--task", "Capture reference evidence",
            "--requirement-receipt", intake_id, "--confirmation-source", "user confirmed baseline",
            "--project-context", context_id, "--outcome-id", "OUTCOME-ARTIFACT", "--intake-id", intake_id,
            "--acceptance", "Reference evidence is recorded.", "--scope", "README.md", "--validation", "python3 -c pass",
            "--coverage-id", "C-REFERENCE",
        )
        plan = {
            "goal": {
                "statement": "Capture reference evidence",
                "acceptance": ["Reference evidence is recorded."],
                "source": "test fixture",
            },
            "nodes": [{
                "id": "M0", "title": "Reference evidence", "status": "active", "coverage_ids": ["C-REFERENCE"],
                "outcome": {
                    "kind": "knowledge_gain", "primary": "Reference evidence is readable",
                    "proofs": [{
                        "id": "reference-proof", "description": "Validate reference manifest",
                        "evidence_kind": "artifact", "coverage_ids": ["C-REFERENCE"],
                    }],
                },
            }],
            "current_node": "M0",
            "next_action": "run reference proof",
        }
        self.cli("plan", "--base-revision", "0", "--reason", "artifact-backed proof", "--plan-json", json.dumps(plan))
        state = self.cli("status", "--compact")
        missing = self.cli(
            "proof", "--node", "M0", "--proof-id", "reference-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]), "--command", "python3 -c pass", check=False,
        )
        self.assertNotEqual(missing["returncode"], 0)
        self.assertIn("--evidence-file", missing["stderr"])
        (self.repo / "reference.json").write_text(json.dumps({
            "schema": "auto-dev/reference-matrix/v1",
            "coverage_ids": ["C-REFERENCE"],
            "source_ref": "legacy@abc123",
            "entries": [{"source": "/legacy", "target": "/new"}],
        }), encoding="utf-8")
        proof = self.cli(
            "proof", "--node", "M0", "--proof-id", "reference-proof",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]), "--command", "python3 -c pass",
            "--evidence-file", "reference.json",
        )
        self.assertEqual(proof["evidence_artifact"]["schema"], "auto-dev/reference-matrix/v1")
        self.assertEqual(proof["evidence_artifact"]["coverage_ids"], ["C-REFERENCE"])

    def test_managed_quick_activity_and_external_reference_are_evidence_bound(self) -> None:
        intake = self.clear_intake()
        intake_id = str(intake["intake"]["id"])
        context_id, project_revision = self.project_context()
        activity = self.cli(
            "activity",
            "record",
            "--project-revision", str(project_revision),
            "--intake-id", intake_id,
            "--summary", "Corrected a local label",
            "--path", "README.md",
            "--validation", "git diff --check",
        )
        self.assertEqual(activity["activity"]["project_context_id"], context_id)
        records = self.cli("activity", "list")
        self.assertEqual(len(records["activities"]), 1)

        foreign = Path(self.temporary.name) / "foreign-state.json"
        foreign.write_text('{"foreign": true}\n', encoding="utf-8")
        rejected = self.cli(
            "project-context",
            "adopt",
            "--project-revision", str(activity["project_revision"]),
            "--context-id", "CTX-EXTERNAL",
            "--title", "External integration",
            "--authority-boundary", "Team may change the local adapter.",
            "--delivery-boundary", "Local repository release boundary.",
            "--context-boundary", "Adapter behavior only.",
            "--external-ref-json",
            json.dumps({
                "repository": "../other-repo",
                "label": "Upstream API",
                "status": "needs-recheck",
                "state_path": str(foreign),
            }),
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("foreign control-state", rejected["stderr"])
        self.assertEqual(foreign.read_text(encoding="utf-8"), '{"foreign": true}\n')


if __name__ == "__main__":
    unittest.main()
