"""Focused regression tests for the read-only Auto Dev refresh command."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
SCRIPTS = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from auto_dev_internal.continuity.refresh import (  # noqa: E402
    _rolling_snapshot,
    _transition_snapshot,
)


class RefreshTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-refresh-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.plugin_data = self.root / "plugin-data"
        self.run_command("git", "init", "-q")
        self.run_command("git", "config", "user.name", "Auto Dev Refresh Test")
        self.run_command("git", "config", "user.email", "refresh@example.com")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.run_command("git", "add", "README.md")
        self.run_command("git", "commit", "-qm", "initial")
        self.run_command("git", "checkout", "-qb", "refresh-test")

    def tearDown(self) -> None:
        registry = self.plugin_data / "progress-servers"
        if registry.exists():
            for record_path in registry.glob("*.json"):
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    pid = record.get("pid")
                    if isinstance(pid, int):
                        os.kill(pid, signal.SIGTERM)
                except (OSError, json.JSONDecodeError):
                    continue
        self.temporary.cleanup()

    def run_command(self, *arguments: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments),
            cwd=self.repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *arguments: str, env: dict[str, str] | None = None, check: bool = True) -> tuple[subprocess.CompletedProcess[str], dict]:
        merged = dict(os.environ)
        merged["PLUGIN_DATA"] = str(self.plugin_data)
        if env:
            merged.update(env)
        result = self.run_command(
            sys.executable,
            str(CLI),
            *arguments,
            "--repo-root",
            str(self.repo),
            env=merged,
            check=False,
        )
        if check:
            self.assertIn(result.returncode, (0, 2), msg=result.stderr)
        payload = json.loads(result.stdout)
        return result, payload

    def make_active_task(self) -> None:
        self.cli(
            "start",
            "--tier", "direct",
            "--task", "Exercise refresh",
            "--requirement-receipt", "REQ-REFRESH",
            "--confirmation-source", "refresh fixture",
            "--acceptance", "Refresh reports the existing task",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "refresh fixture",
        )
        plan = {
            "goal": {
                "statement": "Exercise refresh",
                "acceptance": ["Refresh reports the existing task"],
                "source": "refresh fixture",
            },
            "nodes": [{
                "id": "implement",
                "title": "Exercise refresh",
                "status": "active",
                "outcome": {
                    "kind": "behavior_change",
                    "primary": "Refresh reports the existing task",
                    "proofs": [{"id": "refresh-proof", "description": "Run refresh regression"}],
                },
            }],
            "current_node": "implement",
            "next_action": "continue the refresh fixture",
        }
        self.cli(
            "plan",
            "--base-revision", "0",
            "--reason", "refresh fixture plan",
            "--plan-json", json.dumps(plan),
        )

    def test_ready_has_deterministic_receipt_and_does_not_mutate_control(self) -> None:
        self.make_active_task()
        before = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*")
            if path.is_file()
        }
        result, payload = self.cli("refresh")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["receipt"], "⬆️ Auto Dev Refresh: ready")
        self.assertEqual(payload["next"], "continue current task")
        self.assertEqual(payload["links"]["project"]["path"], str(self.repo.resolve()))
        control_plane_url = payload["links"]["control_plane"]["url"]
        self.assertIsInstance(control_plane_url, str)
        with urllib.request.urlopen(control_plane_url + "api/health", timeout=1) as response:
            health = json.loads(response.read().decode("utf-8"))
        self.assertEqual(health["bundle_version"], payload["runtime"]["source"]["version"])
        self.assertEqual(payload["project"]["transition"]["status"], "ready")
        self.assertEqual(payload["project"]["transition"]["available_routes"], ["switch-superseded"])
        self.assertEqual(payload["handoff"]["import_required"], False)
        self.assertEqual(payload["handoff"]["task_creation"], False)
        after = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_agent_focus_status_preserves_authoritative_decision(self) -> None:
        self.make_active_task()
        _, compact = self.cli("status", "--compact")
        _, focus = self.cli("status", "--view", "agent-focus")

        for key in (
            "status",
            "continuity_status",
            "bootstrap_status",
            "strict_blockers",
            "completion_blockers",
            "product_write_blockers",
            "state_revision",
            "project_revision",
            "id",
        ):
            self.assertEqual(focus.get(key), compact.get(key), msg=key)
        self.assertEqual(focus["current"]["node"], compact["continuity_summary"]["current_node"])
        self.assertEqual(focus["current"]["next_action"], compact["continuity_summary"]["next_action"])
        self.assertEqual(focus["view"], "agent-focus")
        self.assertNotIn("continuity", focus)
        self.assertLess(
            len(json.dumps(focus, ensure_ascii=False)),
            len(json.dumps(compact, ensure_ascii=False)),
        )

    def test_agent_focus_status_preserves_blockers(self) -> None:
        self.make_active_task()
        (self.repo / "outside.txt").write_text("out of scope\n", encoding="utf-8")
        _, compact = self.cli("status", "--compact")
        _, focus = self.cli("status", "--view", "agent-focus")
        self.assertEqual(focus["continuity_status"], compact["continuity_status"])
        self.assertEqual(focus["strict_blockers"], compact["strict_blockers"])
        self.assertIn("out_of_scope_changes", focus["strict_blockers"])

    def test_agent_focus_refresh_preserves_default_contract_and_top_level_decision(self) -> None:
        self.make_active_task()
        _, full = self.cli("refresh")
        _, focus = self.cli("refresh", "--view", "agent-focus")

        self.assertEqual(focus["view"], "agent-focus")
        self.assertEqual(focus["status"], full["status"])
        self.assertEqual(focus["next"], full["next"])
        self.assertEqual(focus["project"]["status"], full["project"]["status"])
        self.assertEqual(focus["project"]["strict_exit_code"], full["project"]["strict_exit_code"])
        self.assertEqual(focus["project"]["transition"], {
            key: full["project"]["transition"].get(key)
            for key in ("status", "suggested_route", "available_routes")
        })
        self.assertEqual(focus["project"]["readback"]["view"], "agent-focus")
        self.assertNotIn("continuity", focus["project"]["readback"])
        self.assertIn("continuity", full["project"]["readback"])

    def test_rolling_roadmap_projects_frontier_without_mutating_control(self) -> None:
        self.cli(
            "start",
            "--tier", "team",
            "--task", "Exercise rolling refresh",
            "--requirement-receipt", "REQ-REFRESH-ROLLING",
            "--confirmation-source", "refresh rolling fixture",
            "--acceptance", "Refresh exposes the rolling frontier",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--skip", "architecture=fixture", "--skip", "compliance=fixture",
            "--skip", "data-contract=fixture", "--skip", "debug-observability=fixture",
            "--skip", "gui=fixture", "--skip", "parallel-work=fixture", "--skip", "release=fixture",
        )
        self.cli(
            "plan", "--base-revision", "0", "--reason", "rolling refresh roadmap",
            "--plan-json", json.dumps({
                "strategy": "rolling_graph",
                "goal": {
                    "statement": "Exercise rolling refresh",
                    "acceptance": ["Refresh exposes the rolling frontier"],
                    "source": "refresh rolling fixture",
                },
                "nodes": [
                    {
                        "id": "m1", "title": "M1: Compile next", "node_role": "milestone",
                        "status": "planned", "acceptance": ["M1 accepted"],
                    },
                    {
                        "id": "m2", "title": "M2: Follow M1", "node_role": "milestone",
                        "status": "planned", "depends_on": ["m1"], "acceptance": ["M2 accepted"],
                    },
                ],
                "relations": [],
            }),
        )
        before = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*") if path.is_file()
        }
        result, payload = self.cli("refresh")
        self.assertEqual(result.returncode, 0)
        rolling = payload["project"]["rolling_graph"]
        self.assertEqual(rolling["strategy"], "rolling_graph")
        self.assertEqual(rolling["compilation_focus"], "m1")
        self.assertEqual(rolling["ready_frontier"]["milestones"], ["m1"])
        self.assertEqual(rolling["compiler_inputs"]["status"], "awaiting_compilation")
        self.assertEqual(payload["project"]["transition"]["status"], "ready")
        after = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)

    def test_incomplete_configured_runtime_requires_fresh_session(self) -> None:
        self.make_active_task()
        stale = self.root / "stale-bundle"
        stale.mkdir()
        result, payload = self.cli("refresh", env={"PLUGIN_ROOT": str(stale)})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "fresh_session_required")
        self.assertEqual(payload["receipt"], "⬆️ Auto Dev Refresh: fresh_session_required")
        self.assertIn("configured_hook_bundle_incomplete", payload["runtime"]["reasons"])
        self.assertEqual(payload["project"]["status"], "ready")
        self.assertIsInstance(payload["links"]["control_plane"]["url"], str)

    def test_old_session_cli_schema_requires_fresh_session(self) -> None:
        self.make_active_task()
        result, payload = self.cli("refresh", env={"AUTO_DEV_CLI_SCHEMA_VERSION": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "fresh_session_required")
        self.assertIn(
            "current_session_cli_schema_differs_from_source",
            payload["runtime"]["reasons"],
        )
        self.assertEqual(payload["project"]["status"], "ready")

    def test_old_control_plane_is_routed_to_legacy_upgrade_without_mutation(self) -> None:
        self.make_active_task()
        project_path = self.repo / ".auto-dev" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["control_plane_upgrade_version"] = 0
        project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        before = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*")
            if path.is_file()
        }

        result, payload = self.cli("refresh")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "work_blocked")
        self.assertEqual(payload["project"]["upgrade"]["status"], "upgrade_available")
        self.assertEqual(payload["project"]["transition"]["status"], "repair_required")
        self.assertIn("legacy-upgrade inspect", payload["next"])
        after = {
            path.relative_to(self.repo).as_posix(): path.read_bytes()
            for path in (self.repo / ".auto-dev").rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_refresh_projects_compiled_packet_policy_and_worker_readback(self) -> None:
        class FakeControl:
            def codegraph_index_fingerprint(self, repo: Path) -> str:
                return "idx-1"

            def paths(self, repo: Path) -> dict[str, Path]:
                return {"workers": repo / "workers"}

        workers = self.root / "workers"
        workers.mkdir()
        (workers / "worker-p1.json").write_text(
            json.dumps({
                "id": "worker-p1",
                "packet_id": "p1",
                "status": "prepared",
                "changed_paths": [],
            }),
            encoding="utf-8",
        )
        status = {
            "continuity": {
                "plan": {
                    "strategy": "rolling_graph",
                    "nodes": [
                        {
                            "id": "m1",
                            "node_role": "milestone",
                            "title": "M1",
                            "status": "active",
                            "milestone_state": {
                                "compilation_status": "compiled",
                                "compilation_revision": 1,
                                "compilation_policy": {
                                    "execution_topology": "multi_agent",
                                    "dispatch_status": "planned",
                                    "merge_mode": "worktree_merge_queue",
                                    "review_budget": 2,
                                    "conflict_owner": "integrator",
                                    "integration_required": True,
                                },
                                "merge_mode": "worktree_merge_queue",
                                "compilation_snapshot": {
                                    "codegraph": {"index_fingerprint": "idx-1"},
                                    "packet_contracts_sha256": "contracts-1",
                                },
                                "execution_decision": {
                                    "version": 1,
                                    "status": "selected",
                                    "recommended_mode": "multi_worker",
                                    "selected_mode": "multi_worker",
                                    "compilation_revision": 1,
                                    "packet_contracts_sha256": "contracts-1",
                                    "boundary": "before_integration",
                                    "confirmation_source": "refresh fixture",
                                },
                            },
                        },
                        {
                            "id": "p1",
                            "parent_id": "m1",
                            "node_role": "work_packet",
                            "title": "Packet 1",
                            "status": "active",
                            "integration_wave": 1,
                            "execution_profile": "governed",
                            "required_capabilities": ["parallel-work"],
                            "verification_policy": {"required": ["unit"], "blocking": True},
                            "review_policy": "strong",
                            "merge_policy": {"mode": "worktree_merge_queue", "conflict_owner": "integrator"},
                            "model_profile": "bounded_worker",
                            "contract_sha256": "packet-1",
                            "execution_base": {"compilation_revision": 1, "head": "head-1"},
                        },
                    ],
                },
                "compilation_focus": "m1",
                "execution_focus": "p1",
                "ready_frontier": {
                    "execution_topology": "multi_agent",
                    "dispatch_status": "planned",
                },
                "exit_snapshots": [],
            }
        }

        projected = _rolling_snapshot(FakeControl(), self.repo, status, {"workers": workers})

        self.assertEqual(projected["execution_topology"], "multi_agent")
        self.assertEqual(projected["dispatch_status"], "multi_worker")
        self.assertEqual(projected["execution_decision"]["selected_mode"], "multi_worker")
        self.assertEqual(projected["policy_revalidation"]["status"], "current")
        self.assertEqual(projected["integration"]["mode"], "worktree_merge_queue")
        self.assertEqual(projected["compilation_policy"]["review_budget"], 2)
        self.assertEqual(projected["packets"][0]["model_profile"], "bounded_worker")
        self.assertEqual(projected["workers"]["status"], "ready")
        self.assertEqual(projected["workers"]["active"][0]["packet_id"], "p1")

    def test_out_of_scope_change_remains_work_blocked(self) -> None:
        self.make_active_task()
        (self.repo / "outside.txt").write_text("out of scope\n", encoding="utf-8")
        result, payload = self.cli("refresh")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "work_blocked")
        self.assertIn("out_of_scope_changes", payload["project"]["readback"]["strict_blockers"])

    def test_empty_managed_project_requires_confirmation(self) -> None:
        self.cli("project", "init", "--confirmation-source", "refresh fixture")
        result, payload = self.cli("refresh")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "confirmation_required")
        self.assertEqual(payload["project"]["readback"]["status"], "idle")
        self.assertEqual(payload["project"]["transition"]["status"], "transition_required")
        self.assertEqual(payload["project"]["transition"]["suggested_route"], "start-new")

    def test_active_task_without_plan_requires_adoption(self) -> None:
        self.cli(
            "start",
            "--tier", "direct",
            "--task", "Legacy active task",
            "--requirement-receipt", "REQ-LEGACY",
            "--confirmation-source", "refresh fixture",
            "--acceptance", "Refresh diagnoses missing plan",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "refresh fixture",
        )
        result, payload = self.cli("refresh")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["project"]["transition"]["status"], "adopt_required")
        self.assertTrue(payload["project"]["transition"]["resume_original_intent"])

    def test_degraded_recovery_requires_repair(self) -> None:
        transition = _transition_snapshot(
            {
                "status": "active",
                "id": "TASK-1",
                "continuity_status": "degraded_recovery",
                "bootstrap_status": "needs_recovery",
                "strict_blockers": ["degraded_recovery"],
                "recovery_source": "active.bak",
            },
            {"status": "current"},
        )
        self.assertEqual(transition["status"], "repair_required")
        self.assertEqual(transition["after_resolution"], "resume_original_intent")

    def test_matching_progress_bundle_is_reused(self) -> None:
        self.make_active_task()
        _, first = self.cli("refresh")
        _, second = self.cli("refresh")
        self.assertEqual(
            first["links"]["control_plane"]["url"],
            second["links"]["control_plane"]["url"],
        )

    def test_stale_progress_bundle_is_replaced(self) -> None:
        self.make_active_task()
        _, first = self.cli("refresh")
        record_path = Path(first["service"]["progress"]["record"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        previous_generation = record["generation"]
        record["bundle_version"] = "0.0.0+codex.stale"
        record_path.write_text(json.dumps(record), encoding="utf-8")

        _, second = self.cli("refresh")
        replacement = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertNotEqual(replacement["generation"], previous_generation)
        self.assertEqual(replacement["bundle_version"], second["runtime"]["source"]["version"])

    def test_progress_record_failure_is_repaired_without_masking_task_state(self) -> None:
        self.make_active_task()
        progress_dir = self.plugin_data / "progress-servers"
        progress_dir.mkdir(parents=True)
        digest = hashlib.sha256(str(self.repo.resolve()).encode("utf-8")).hexdigest()[:24]
        (progress_dir / f"{digest}.json").write_text(
            json.dumps({"repo": "/some/other/repo", "url": "http://127.0.0.1:9/"}),
            encoding="utf-8",
        )
        result, payload = self.cli("refresh", env={"PLUGIN_DATA": str(self.plugin_data)})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["service"]["progress"]["status"], "healthy")
        self.assertIsInstance(payload["links"]["control_plane"]["url"], str)

    def test_unmanaged_checkout_still_returns_json_receipt(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "refresh", "--repo-root", str(self.root / "missing")],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "runtime_unavailable")
        self.assertEqual(payload["receipt"], "⬆️ Auto Dev Refresh: runtime_unavailable")
        self.assertEqual(payload["links"]["control_plane"]["url"], None)


if __name__ == "__main__":
    unittest.main()
