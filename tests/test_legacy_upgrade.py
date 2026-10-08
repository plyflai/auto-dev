#!/usr/bin/env python3
"""Regression coverage for versioned legacy control-plane upgrades."""

from __future__ import annotations

import json
import argparse
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
SCRIPTS = CLI.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import runctl  # noqa: E402
from auto_dev_internal.legacy import orchestration as legacy_orchestration  # noqa: E402


class LegacyUpgradeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-legacy-upgrade-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.run_command("git", "init", "-q")
        self.run_command("git", "config", "user.name", "Auto Dev Test")
        self.run_command("git", "config", "user.email", "auto-dev@example.com")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.run_command("git", "add", "README.md")
        self.run_command("git", "commit", "-qm", "initial")
        self.run_command("git", "checkout", "-qb", "legacy-upgrade")
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
        result = self.run_command(
            sys.executable,
            str(CLI),
            *arguments,
            "--repo-root",
            str(self.repo),
            check=check,
        )
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def make_legacy_control(self) -> dict[str, Any]:
        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Preserve the original English task wording",
            "--requirement-receipt", "REQ-LEGACY-UPGRADE",
            "--confirmation-source", "original user confirmation",
            "--acceptance", "The original task remains readable after upgrade.",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "legacy fixture",
        )
        plan = {
            "goal": {
                "statement": "Preserve the original English task wording",
                "acceptance": ["The original task remains readable after upgrade."],
                "source": "original user confirmation",
            },
            "nodes": [{
                "id": "legacy-node",
                "title": "Keep the original English plan title",
                "status": "active",
                "outcome": {
                    "kind": "knowledge_gain",
                    "primary": "The legacy plan remains intact.",
                    "proofs": [{"id": "legacy-proof", "description": "Retain legacy evidence"}],
                },
            }],
            "current_node": "legacy-node",
            "next_action": "Keep the original English next action",
        }
        self.cli(
            "plan",
            "--base-revision", "0",
            "--reason", "legacy English plan",
            "--plan-json", json.dumps(plan),
        )
        control = self.repo / ".auto-dev"
        active_path = control / "active.json"
        task_path = control / "tasks" / f"{started['id']}.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(active, task)
        for receipt in (active, task):
            receipt["schema_version"] = 9
            receipt.pop("project_context_id", None)
            receipt.pop("primary_outcome_id", None)
            receipt.pop("intake_id", None)
        active_path.write_text(json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        project_path = control / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["schema_version"] = 1
        project["state_revision"] = 8
        project["contexts"] = {}
        project["default_context_id"] = None
        project.pop("control_plane_upgrade_version", None)
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(control / "projects")

        run_path = control / "runs" / "LEGACY-HISTORICAL-RUN.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(
            json.dumps({
                "schema_version": 4,
                "id": "LEGACY-HISTORICAL-RUN",
                "task": "Historical English evidence must remain immutable.",
                "status": "passed",
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "task_id": str(started["id"]),
            "active": active,
            "task": task,
            "run_bytes": run_path.read_bytes(),
        }

    def make_state_contract_v1(self, *, completed: bool = False) -> dict[str, Any]:
        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Adopt the versioned state contract",
            "--requirement-receipt", "REQ-STATE-CONTRACT-V2",
            "--confirmation-source", "state contract fixture",
            "--acceptance", "All persisted state surfaces are governed",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "state contract fixture",
        )
        self.cli(
            "plan",
            "--base-revision", "0",
            "--reason", "state contract fixture",
            "--plan-json", json.dumps({
                "goal": {
                    "statement": "Adopt the versioned state contract",
                    "acceptance": ["All persisted state surfaces are governed"],
                    "source": "state contract fixture",
                },
                "nodes": [{
                    "id": "verify-upgrade",
                    "title": "Verify the upgrade",
                    "status": "active",
                    "outcome": {
                        "kind": "behavior_change",
                        "primary": "The control plane can be upgraded safely",
                        "proofs": [{"id": "upgrade-proof", "description": "Run upgrade proof"}],
                    },
                }],
                "current_node": "verify-upgrade",
                "next_action": "run the upgrade proof",
            }),
        )
        if completed:
            status = self.cli("status", "--compact")
            self.cli(
                "proof",
                "--node", "verify-upgrade",
                "--proof-id", "upgrade-proof",
                "--plan-revision", str(status["continuity_summary"]["plan_revision"]),
                "--state-revision", str(status["state_revision"]),
                "--command", "python3 -c pass",
            )
            status = self.cli("status", "--compact")
            self.cli(
                "checkpoint",
                "--node", "verify-upgrade",
                "--status", "done",
                "--plan-revision", str(status["continuity_summary"]["plan_revision"]),
                "--state-revision", str(status["state_revision"]),
                "--summary", "upgrade proof completed",
                "--evidence", "upgrade fixture",
            )

        control = self.repo / ".auto-dev"
        active_path = control / "active.json"
        task_path = control / "tasks" / f"{started['id']}.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        for proof in active.get("continuity", {}).get("proofs", []):
            for key in (
                "attempt_id", "attempt_index", "outcome_sha256", "plan_revision",
                "scope_sha256", "fresh",
            ):
                proof.pop(key, None)
        active["schema_version"] = 11
        active["continuity"]["schema_version"] = 4
        active_path.write_text(json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        task_path.write_text(json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        inactive = json.loads(json.dumps(active))
        inactive["id"] = "AUTO-DEV-INACTIVE-V1"
        inactive["task"] = "Preserve an inactive task while upgrading"
        inactive["status"] = "paused"
        inactive["state_revision"] = 3
        inactive_path = control / "tasks" / "AUTO-DEV-INACTIVE-V1.json"
        inactive_path.write_text(json.dumps(inactive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        project_path = control / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["control_plane_upgrade_version"] = 1
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (control / "project-memory.json").write_text(json.dumps({
            "schema_version": 2,
            "updated_at": None,
            "entries": [],
            "attempts": [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "task_id": str(started["id"]),
            "active_revision": int(active["state_revision"]),
            "plan_revision": int(active["continuity"]["plan"]["revision"]),
            "completed": completed,
        }

    def control_snapshot(self) -> dict[str, bytes]:
        control = self.repo / ".auto-dev"
        return {
            path.relative_to(control).as_posix(): path.read_bytes()
            for path in sorted(control.rglob("*"))
            if path.is_file() and not path.name.endswith(".lock") and "legacy-upgrade-backups" not in path.parts
        }

    def apply_arguments(self, inspection: dict[str, Any]) -> list[str]:
        contract = inspection["apply_contract"]
        arguments = [
            "legacy-upgrade",
            "apply",
            "--project-revision", str(contract["project_revision"]),
            "--expected-upgrade-version", str(contract["upgrade_version"]),
            "--expected-fingerprint", str(contract["fingerprint"]),
            "--reason", "用户确认按当前标准接手旧控制面",
            "--confirmation-source", "legacy upgrade test confirmation",
        ]
        if contract["active_task_revision"] is not None:
            arguments.extend(["--active-task-revision", str(contract["active_task_revision"])])
        for step in contract["expected_steps"]:
            arguments.extend(["--expected-step", str(step)])
        return arguments

    def test_inspect_is_read_only_and_reports_exact_upgrade_contract(self) -> None:
        legacy = self.make_legacy_control()
        before = self.control_snapshot()

        inspection = self.cli("legacy-upgrade", "inspect")
        status = self.cli("status", "--compact")
        bootstrap = self.cli("bootstrap", "inspect")

        self.assertEqual(inspection["status"], "upgrade_available")
        self.assertEqual(inspection["project"]["schema_version"], 1)
        self.assertEqual(inspection["project"]["control_plane_upgrade_version"], 0)
        self.assertEqual(
            inspection["project"]["target_upgrade_version"],
            runctl.CONTROL_PLANE_UPGRADE_VERSION,
        )
        self.assertEqual(inspection["active_task"]["id"], legacy["task_id"])
        self.assertEqual(inspection["apply_contract"]["project_revision"], 8)
        self.assertEqual(inspection["apply_contract"]["active_task_revision"], legacy["active"]["state_revision"])
        self.assertEqual(
            inspection["apply_contract"]["expected_steps"],
            [
                "hierarchy-adoption-v1",
                "state-contract-adoption-v2",
                "verification-gate-policy-v3",
                "environment-domain-memory-v4",
                "rolling-plan-envelope-v5",
            ],
        )
        self.assertTrue(inspection["upgrade"]["fingerprint"])
        self.assertTrue(inspection["historical_runs"]["preserved"])
        self.assertIn("旧控制面可以升级", inspection["receipt"])
        self.assertEqual(status["hierarchy"]["control_plane_upgrade"]["status"], "upgrade_available")
        self.assertEqual(bootstrap["legacy_upgrade"]["status"], "upgrade_available")
        self.assertEqual(before, self.control_snapshot())

    def test_inspect_command_uses_one_evaluation_scope_without_changing_output(self) -> None:
        self.make_legacy_control()
        observed: list[bool] = []
        original = legacy_orchestration.legacy_upgrade_inspection_payload

        def wrapped(control, repo, state, *, include_legacy_material=False):
            observed.append(runctl.current_evaluation(repo) is not None)
            return original(
                control,
                repo,
                state,
                include_legacy_material=include_legacy_material,
            )

        arguments = argparse.Namespace(repo_root=str(self.repo))
        output = io.StringIO()
        with mock.patch.object(
            legacy_orchestration, "legacy_upgrade_inspection_payload", side_effect=wrapped
        ):
            with contextlib.redirect_stdout(output):
                self.assertEqual(runctl.command_legacy_upgrade_inspect(arguments), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "upgrade_available")
        self.assertEqual(observed, [True])

    def test_status_uses_active_upgrade_projection_without_building_historical_plan(self) -> None:
        self.make_legacy_control()
        with mock.patch.object(
            runctl,
            "build_legacy_upgrade_plan",
            side_effect=AssertionError("status must defer historical legacy audit"),
        ):
            status = self.cli("status", "--compact")
        self.assertEqual(status["hierarchy"]["control_plane_upgrade"]["status"], "upgrade_available")
        self.assertEqual(
            status["hierarchy"]["control_plane_upgrade"]["audit_scope"],
            "active_task",
        )
        self.assertEqual(
            status["hierarchy"]["control_plane_upgrade"]["historical_audit"],
            "deferred",
        )

    def test_new_project_is_marked_at_the_current_upgrade_version(self) -> None:
        project = json.loads((self.repo / ".auto-dev" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project["control_plane_upgrade_version"], runctl.CONTROL_PLANE_UPGRADE_VERSION)

    def test_apply_requires_fresh_confirmation_and_preserves_legacy_evidence(self) -> None:
        legacy = self.make_legacy_control()
        inspection = self.cli("legacy-upgrade", "inspect")
        arguments = self.apply_arguments(inspection)

        missing_confirmation = self.cli(*[arg for arg in arguments if arg != "--confirmation-source" and arg != "legacy upgrade test confirmation"], check=False)
        self.assertNotEqual(missing_confirmation["returncode"], 0)
        stale = list(arguments)
        stale[stale.index("--project-revision") + 1] = "7"
        stale_result = self.cli(*stale, check=False)
        self.assertNotEqual(stale_result["returncode"], 0)
        self.assertIn("project revision conflict", stale_result["stderr"])
        stale_fingerprint = list(arguments)
        stale_fingerprint[stale_fingerprint.index("--expected-fingerprint") + 1] = "stale"
        stale_fingerprint_result = self.cli(*stale_fingerprint, check=False)
        self.assertNotEqual(stale_fingerprint_result["returncode"], 0)
        self.assertIn("fingerprint is stale", stale_fingerprint_result["stderr"])

        result = self.cli(*arguments)
        self.assertEqual(result["status"], "upgraded")
        self.assertIn("旧控制面已升级", result["receipt"])
        self.assertTrue((self.repo / ".auto-dev" / result["backup"]).is_dir())

        control = self.repo / ".auto-dev"
        project = json.loads((control / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project["schema_version"], runctl.PROJECT_SCHEMA_VERSION)
        self.assertEqual(project["control_plane_upgrade_version"], runctl.CONTROL_PLANE_UPGRADE_VERSION)
        self.assertEqual(project["state_revision"], 9)
        context_id = str(project["default_context_id"])
        entry = project["contexts"][context_id]
        frame = json.loads((control / "projects" / context_id / "frame.json").read_text(encoding="utf-8"))
        outcome = json.loads(
            (control / "projects" / context_id / "outcomes" / f"{entry['unlinked_outcome_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(frame["title"], "仓库交付上下文")
        self.assertEqual(outcome["title"], "未归属工作收件箱")

        upgraded = json.loads((control / "tasks" / f"{legacy['task_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(upgraded["task"], legacy["task"]["task"])
        self.assertEqual(
            upgraded["continuity"]["plan"]["nodes"],
            legacy["task"]["continuity"]["plan"]["nodes"],
        )
        self.assertEqual(upgraded["continuity"]["plan"]["revision"], legacy["task"]["continuity"]["plan"]["revision"])
        self.assertEqual(upgraded["continuity"]["plan"]["strategy"], "legacy")
        self.assertEqual(upgraded["continuity"]["plan"]["relations"], [])
        self.assertEqual(
            upgraded["continuity"]["plan"]["graph_sha256"],
            legacy["task"]["continuity"]["plan"]["graph_sha256"],
        )
        self.assertIsNone(upgraded["continuity"]["compilation_focus"])
        self.assertEqual(upgraded["continuity"]["execution_focus"], "legacy-node")
        self.assertEqual(upgraded["continuity"]["exit_snapshots"], [])
        self.assertEqual(upgraded["continuity"]["schema_version"], runctl.CONTINUITY_SCHEMA_VERSION)
        self.assertEqual(upgraded["project_context_id"], context_id)
        self.assertEqual(upgraded["primary_outcome_id"], entry["unlinked_outcome_id"])
        self.assertEqual(upgraded["state_revision"], legacy["task"]["state_revision"] + 2)
        self.assertEqual((control / "runs" / "LEGACY-HISTORICAL-RUN.json").read_bytes(), legacy["run_bytes"])

        current = self.cli("legacy-upgrade", "inspect")
        self.assertEqual(current["status"], "current")
        self.assertEqual(current["changes"], [])

    def test_failed_apply_restores_mutated_control_files(self) -> None:
        self.make_legacy_control()
        inspection = self.cli("legacy-upgrade", "inspect")
        arguments = [*self.apply_arguments(inspection), "--repo-root", str(self.repo)]
        parsed = runctl.build_parser().parse_args(arguments)
        before = self.control_snapshot()
        project_path = (self.repo / ".auto-dev" / "project.json").resolve()
        original_write_json = runctl.write_json

        def interrupted_write(path: Path, payload: dict[str, Any], *, backup: bool = False) -> None:
            if path.resolve() == project_path:
                raise OSError("simulated project write interruption")
            original_write_json(path, payload, backup=backup)

        with mock.patch.object(runctl, "write_json", side_effect=interrupted_write):
            with self.assertRaisesRegex(OSError, "simulated project write interruption"):
                runctl.command_legacy_upgrade_apply(parsed)

        self.assertEqual(before, self.control_snapshot())
        self.assertFalse((self.repo / ".auto-dev" / "projects").exists())
        self.assertTrue((self.repo / ".auto-dev" / "legacy-upgrade-backups").is_dir())
        fix_inspection = self.cli("fix", "inspect")
        rolled_back = [
            transaction
            for transaction in fix_inspection["upgrade_transactions"]
            if transaction.get("status") == "rolled_back"
        ]
        self.assertEqual(len(rolled_back), 1)
        self.assertEqual(rolled_back[0]["operations"], [])

    def test_fix_rolls_back_an_upgrade_interrupted_after_its_backup(self) -> None:
        legacy = self.make_legacy_control()
        state = runctl.paths(self.repo.resolve())
        project_before = state["project"].read_bytes()
        plan = runctl.build_legacy_upgrade_plan(self.repo.resolve(), state)
        upgrade_id = "LEGACY-UPGRADE-INTERRUPTED-FIXTURE"
        affected = [*plan.writes.keys(), state["upgrade_history"]]
        created_directories = runctl.legacy_upgrade_created_directories(
            state, affected
        )
        backup_root = runctl.legacy_upgrade_backup(
            state, upgrade_id, affected, created_directories
        )
        first_path, first_payload = sorted(
            plan.writes.items(),
            key=lambda item: (
                item[0] == state["project"],
                runctl.upgrade_relative_path(state, item[0]),
            ),
        )[0]
        first_path.parent.mkdir(parents=True, exist_ok=True)
        runctl.write_json(first_path, first_payload)

        inspection = self.cli("fix", "inspect")
        self.assertEqual(inspection["status"], "ready")
        self.assertIn("recover-interrupted-upgrade", inspection["operations"])
        transaction = next(
            item
            for item in inspection["upgrade_transactions"]
            if item.get("upgrade_id") == upgrade_id
        )
        self.assertEqual(transaction["status"], "interrupted")
        self.assertEqual(
            transaction["operations"],
            [{"operation": "recover-interrupted-upgrade", "upgrade_id": upgrade_id}],
        )

        stale = self.cli(
            "fix",
            "apply",
            "--operation",
            "recover-interrupted-upgrade",
            "--upgrade-id",
            upgrade_id,
            "--expected-upgrade-manifest-sha256",
            transaction["manifest_sha256"],
            "--expected-current-fingerprint",
            "stale",
            "--reason",
            "recover an interrupted control-plane upgrade",
            "--confirmation-source",
            "user explicitly approved upgrade recovery",
            check=False,
        )
        self.assertNotEqual(stale["returncode"], 0)
        self.assertTrue(first_path.exists())

        repaired = self.cli(
            "fix",
            "apply",
            "--operation",
            "recover-interrupted-upgrade",
            "--upgrade-id",
            upgrade_id,
            "--expected-upgrade-manifest-sha256",
            transaction["manifest_sha256"],
            "--expected-current-fingerprint",
            transaction["current_fingerprint"],
            "--reason",
            "recover an interrupted control-plane upgrade",
            "--confirmation-source",
            "user explicitly approved upgrade recovery",
        )
        self.assertEqual(repaired["status"], "repaired")
        self.assertEqual(
            repaired["readback"]["upgrade_transaction"]["status"], "rolled_back"
        )
        self.assertEqual(repaired["readback"]["legacy_upgrade_status"], "upgrade_available")
        self.assertTrue(backup_root.is_dir())
        active = json.loads(state["active"].read_text(encoding="utf-8"))
        self.assertEqual(active["id"], legacy["task_id"])
        self.assertEqual(state["project"].read_bytes(), project_before)
        self.assertTrue(state["repair_history"].is_file())

    def test_future_registry_step_is_discovered_without_rewriting_orchestration(self) -> None:
        self.make_legacy_control()

        def future_step(plan: runctl.LegacyUpgradePlan) -> None:
            plan.project["future_upgrade_fixture"] = True

        future = runctl.LegacyUpgradeStep(
            version=6,
            identifier="future-fixture-v6",
            title="未来升级步骤",
            description="验证升级注册表可继续追加步骤。",
            planner=future_step,
        )
        with mock.patch.object(runctl, "CONTROL_PLANE_UPGRADE_VERSION", 6), mock.patch.object(
            runctl, "LEGACY_UPGRADE_STEPS", (*runctl.LEGACY_UPGRADE_STEPS, future),
        ):
            inspection = runctl.legacy_upgrade_inspection_payload(self.repo.resolve(), runctl.paths(self.repo.resolve()))

        self.assertEqual(inspection["status"], "upgrade_available")
        self.assertEqual(
            [step["id"] for step in inspection["upgrade"]["pending_steps"]],
            [
                "hierarchy-adoption-v1",
                "state-contract-adoption-v2",
                "verification-gate-policy-v3",
                "environment-domain-memory-v4",
                "rolling-plan-envelope-v5",
                "future-fixture-v6",
            ],
        )
        self.assertEqual(inspection["project"]["target_upgrade_version"], 6)

    def test_state_surface_registry_is_complete_and_bound_to_migration_steps(self) -> None:
        runctl.validate_control_plane_state_surface_registry()
        self.assertEqual(
            {surface.identifier for surface in runctl.CONTROL_PLANE_STATE_SURFACES},
            {
                "project", "task_receipts", "continuity", "proof_attempts",
                "project_memory", "environment_projection", "domain_projection",
                "dependency_lease", "runtime_diagnostics",
                "workspace_policy", "handoff_packet", "verification_gate_policy",
                "plan_strategy",
            },
        )

    def test_v2_detects_and_upgrades_all_persisted_state_surfaces(self) -> None:
        fixture = self.make_state_contract_v1()
        inspection = self.cli("legacy-upgrade", "inspect")

        self.assertEqual(inspection["status"], "upgrade_available")
        self.assertEqual(
            [step["id"] for step in inspection["upgrade"]["pending_steps"]],
            [
                "state-contract-adoption-v2",
                "verification-gate-policy-v3",
                "environment-domain-memory-v4",
                "rolling-plan-envelope-v5",
            ],
        )
        surfaces = {surface["id"]: surface for surface in inspection["state_surfaces"]}
        self.assertEqual(surfaces["task_receipts"]["status"], "upgrade_available")
        self.assertEqual(surfaces["continuity"]["status"], "upgrade_available")
        self.assertEqual(surfaces["project_memory"]["status"], "upgrade_available")
        self.assertEqual(surfaces["runtime_diagnostics"]["status"], "current")
        self.assertEqual(surfaces["verification_gate_policy"]["status"], "upgrade_available")
        self.assertEqual(inspection["revalidation_targets"], [])

        result = self.cli(*self.apply_arguments(inspection))
        self.assertEqual(result["readback"]["upgrade_status"], "current")
        control = self.repo / ".auto-dev"
        for task_id in (fixture["task_id"], "AUTO-DEV-INACTIVE-V1"):
            receipt = json.loads((control / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema_version"], runctl.SCHEMA_VERSION)
            self.assertEqual(receipt["continuity"]["schema_version"], runctl.CONTINUITY_SCHEMA_VERSION)
        memory = json.loads((control / "project-memory.json").read_text(encoding="utf-8"))
        self.assertEqual(memory["schema_version"], runctl.project_memory.REGISTRY_SCHEMA_VERSION)
        self.assertTrue((control / "path.md").is_file())
        self.assertTrue((control / "project-domain.md").is_file())
        project = json.loads((control / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project["verification_gate_policy"], runctl.VERIFICATION_GATE_POLICY)
        self.assertEqual(self.cli("legacy-upgrade", "inspect")["status"], "current")

    def test_upgrade_requires_real_revalidation_for_completed_legacy_proof(self) -> None:
        fixture = self.make_state_contract_v1(completed=True)
        inspection = self.cli("legacy-upgrade", "inspect")
        result = self.cli(*self.apply_arguments(inspection))

        self.assertEqual(result["readback"]["upgrade_status"], "reverification_required")
        pending = self.cli("legacy-upgrade", "inspect")
        self.assertEqual(pending["status"], "reverification_required")
        self.assertEqual(len(pending["revalidation_targets"]), 1)
        target = pending["revalidation_targets"][0]
        self.assertEqual(target["kind"], "migration_revalidation_required")
        self.assertEqual(
            (target["task_id"], target["node_id"], target["proof_id"]),
            (fixture["task_id"], "verify-upgrade", "upgrade-proof"),
        )

        status = self.cli("status", "--compact")
        self.assertIn("verification_reconcile", status["product_write_blockers"])
        self.assertEqual(status["verification_reconcile_mode"], "strict")
        without_revalidation = self.cli(
            "proof",
            "--node", "verify-upgrade",
            "--proof-id", "upgrade-proof",
            "--plan-revision", str(status["continuity_summary"]["plan_revision"]),
            "--state-revision", str(status["state_revision"]),
            "--command", "python3 -c pass",
            check=False,
        )
        self.assertNotEqual(without_revalidation["returncode"], 0)

        revalidated = self.cli(
            "proof",
            "--revalidate",
            "--node", "verify-upgrade",
            "--proof-id", "upgrade-proof",
            "--plan-revision", str(status["continuity_summary"]["plan_revision"]),
            "--state-revision", str(status["state_revision"]),
            "--command", "python3 -c pass",
        )
        self.assertEqual(revalidated["status"], "passed")
        self.assertTrue(revalidated["revalidation"])
        after = self.cli("status", "--compact")
        node = after["continuity"]["plan"]["nodes"][0]
        self.assertEqual(node["status"], "done")
        self.assertEqual(after["continuity_summary"]["plan_revision"], fixture["plan_revision"])
        self.assertEqual(self.cli("legacy-upgrade", "inspect")["status"], "current")

    def test_revalidation_uses_active_proof_state_without_rebuilding_history(self) -> None:
        self.make_state_contract_v1(completed=True)
        inspection = self.cli("legacy-upgrade", "inspect")
        self.cli(*self.apply_arguments(inspection))
        status = self.cli("status", "--compact")
        parsed = runctl.build_parser().parse_args(
            [
                "proof",
                "--revalidate",
                "--node",
                "verify-upgrade",
                "--proof-id",
                "upgrade-proof",
                "--plan-revision",
                str(status["continuity_summary"]["plan_revision"]),
                "--state-revision",
                str(status["state_revision"]),
                "--command",
                "python3 -c pass",
                "--repo-root",
                str(self.repo),
            ]
        )
        with mock.patch.object(
            runctl,
            "build_legacy_upgrade_plan",
            side_effect=AssertionError("active revalidation must not rebuild inactive history"),
        ), contextlib.redirect_stdout(io.StringIO()):
            runctl.command_proof(parsed)
        self.assertEqual(self.cli("legacy-upgrade", "inspect")["status"], "current")

    def test_newer_control_plane_is_reported_separately_from_blocked(self) -> None:
        project_path = self.repo / ".auto-dev" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["control_plane_upgrade_version"] = runctl.CONTROL_PLANE_UPGRADE_VERSION + 1
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        inspection = self.cli("legacy-upgrade", "inspect")
        self.assertEqual(inspection["status"], "newer_than_cli")


if __name__ == "__main__":
    unittest.main()
