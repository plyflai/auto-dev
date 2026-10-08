"""End-to-end coverage for atomic execution-focus transitions."""

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
from types import SimpleNamespace
from typing import Any
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
sys.path.insert(0, str(CLI.parent))

from auto_dev_internal import transition as transition_module
from auto_dev_internal.foundation import progress as progress_module


class TransitionProgressReadbackTest(unittest.TestCase):
    def clock(self) -> tuple[SimpleNamespace, list[float]]:
        elapsed = [0.0]

        def advance(seconds: float) -> None:
            elapsed[0] += seconds

        return SimpleNamespace(monotonic=lambda: elapsed[0], sleep=advance), elapsed

    def test_progress_readback_waits_for_cached_previous_task(self) -> None:
        clock, elapsed = self.clock()
        current = {"id": "previous-task"}
        snapshots = progress_module.ProgressSnapshotStore(
            fingerprint=lambda _session: current["id"],
            payload=lambda _session, _context: dict(current),
            identity=lambda: {"task_id": current["id"]},
        )

        def readback(_url):
            snapshot = snapshots.snapshot(session_key=None, project_context_id=None)
            return {"status": "ok"}, snapshot.payload

        with mock.patch.object(progress_module, "time", clock), mock.patch.object(
            transition_module, "time", clock
        ), mock.patch.object(transition_module, "_progress_state", side_effect=readback):
            readback(None)
            current["id"] = "next-task"
            self.assertEqual(readback(None)[1]["id"], "previous-task")
            self.assertTrue(transition_module._verify_progress("http://fixture/", "next-task"))
            self.assertEqual(readback(None)[1]["id"], "next-task")
            self.assertLessEqual(elapsed[0], 3.1)

    def test_progress_readback_rejects_persistent_unavailable_or_wrong_state(self) -> None:
        for readback in (
            (None, None),
            ({"status": "ok"}, {"id": "previous-task"}),
            ({"status": "unavailable"}, {"id": "next-task"}),
        ):
            with self.subTest(readback=readback):
                clock, elapsed = self.clock()
                with mock.patch.object(transition_module, "time", clock), mock.patch.object(
                    transition_module, "_progress_state", return_value=readback
                ):
                    self.assertFalse(transition_module._verify_progress("http://fixture/", "next-task"))
                    self.assertLessEqual(elapsed[0], 3.1)


class TransitionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-transition-test-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.plugin_data = self.root / "plugin-data"
        self.execute("git", "init", "-q")
        self.execute("git", "config", "user.name", "Auto Dev Transition Test")
        self.execute("git", "config", "user.email", "auto-dev@example.com")
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.execute("git", "add", "README.md")
        self.execute("git", "commit", "-qm", "initial")
        self.execute("git", "checkout", "-qb", "transition-test")
        self.cli("project", "init", "--confirmation-source", "transition fixture")

    def tearDown(self) -> None:
        registry = self.plugin_data / "progress-servers"
        if registry.is_dir():
            for path in registry.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    pid = payload.get("pid")
                    if isinstance(pid, int):
                        os.kill(pid, signal.SIGTERM)
                except (OSError, json.JSONDecodeError):
                    pass
        self.temporary.cleanup()

    def execute(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PLUGIN_DATA"] = str(self.plugin_data)
        result = subprocess.run(
            list(arguments),
            cwd=self.repo,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
        return result

    def cli(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        result = self.execute(
            sys.executable,
            str(CLI),
            *arguments,
            "--repo-root",
            str(self.repo),
            check=check,
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        if not check:
            payload["returncode"] = result.returncode
            payload["stderr"] = result.stderr
        return payload

    def project(self) -> dict[str, Any]:
        return json.loads((self.repo / ".auto-dev" / "project.json").read_text(encoding="utf-8"))

    def status(self) -> dict[str, Any]:
        return self.cli("status", "--compact")

    def spec(
        self,
        *,
        request_id: str,
        route: str,
        outcome_id: str,
        task_title: str,
        current: dict[str, Any] | None = None,
        valid_plan: bool = True,
    ) -> dict[str, Any]:
        project = self.project()
        context_id = str(project["default_context_id"])
        expected: dict[str, Any] = {"project_revision": project["state_revision"]}
        if current:
            expected.update({"task_id": current["id"], "task_revision": current["state_revision"]})
        node_id = "implement-" + request_id
        plan: dict[str, Any] = {
            "goal": {
                "statement": task_title,
                "acceptance": ["The transition target is executable."],
                "source": "transition fixture",
            },
            "nodes": [
                {
                    "id": node_id,
                    "title": "Implement transition target",
                    "status": "active",
                    "outcome": {
                        "kind": "behavior_change",
                        "primary": "The transition target is active.",
                        "proofs": [
                            {"id": "target-proof", "description": "Run the target proof."}
                        ],
                    },
                }
            ],
            "current_node": node_id,
            "next_action": "Implement the target.",
            "reason": "transition fixture",
        }
        if not valid_plan:
            plan["current_node"] = "missing-node"
        return {
            "request_id": request_id,
            "route": route,
            "expected": expected,
            "confirmation_source": "User explicitly confirmed the transition.",
            "target": {
                "context": {"id": context_id},
                "outcomes": [
                    {
                        "id": outcome_id,
                        "title": task_title,
                        "statement": task_title,
                        "status": "active",
                        "acceptance": ["The target task is ready."],
                    }
                ],
                "intake": {
                    "summary": task_title,
                    "goal": task_title,
                    "inference": "This is a bounded transition fixture.",
                    "scope": ["README.md"],
                    "acceptance": ["The transition target is executable."],
                    "non_goals": ["Do not change product behavior outside the fixture."],
                    "assumptions": [],
                    "repository_facts": ["README.md exists."],
                    "expert_completions": [],
                },
                "task": {
                    "tier": "direct",
                    "title": task_title,
                    "outcome_id": outcome_id,
                    "acceptance": ["The transition target is executable."],
                    "scope": ["README.md"],
                    "validation": ["python3 -c pass"],
                    "evidence": ["transition fixture"],
                },
                "plan": plan,
            },
        }

    def transition(self, spec: dict[str, Any], *, check: bool = True) -> dict[str, Any]:
        return self.cli("transition", "--spec-json", json.dumps(spec), check=check)

    def test_start_new_creates_a_ready_focus_and_verified_ui(self) -> None:
        spec = self.spec(
                request_id="start-new",
                route="start-new",
                outcome_id="OUTCOME-TRANSITION-START",
                task_title="Start a new executable focus",
            )
        result = self.transition(spec)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["route"], "start-new")
        self.assertEqual(result["proof_policy"], "target-only")
        self.assertTrue(result["current_node"])
        with urllib.request.urlopen(result["control_plane_url"] + "api/state", timeout=2) as response:
            ui = json.loads(response.read().decode("utf-8"))
        self.assertEqual(ui["id"], result["task_id"])
        self.assertEqual(ui["continuity_status"], "ready")
        self.assertEqual(ui["project_context_id"], result["project_context_id"])
        self.assertEqual(ui["primary_outcome_id"], result["primary_outcome_id"])
        self.assertEqual(ui["intake_id"], result["intake_id"])
        self.assertEqual(ui["last_transition"]["status"], "ready")
        repeated = self.transition(spec)
        self.assertEqual(repeated["task_id"], result["task_id"])
        self.assertEqual(repeated["state_revision"], result["state_revision"])

    def test_switch_superseded_does_not_revalidate_old_proofs(self) -> None:
        first = self.transition(
            self.spec(
                request_id="first-focus",
                route="start-new",
                outcome_id="OUTCOME-TRANSITION-FIRST",
                task_title="First focus",
            )
        )
        current = self.status()
        second = self.transition(
            self.spec(
                request_id="second-focus",
                route="switch-superseded",
                outcome_id="OUTCOME-TRANSITION-SECOND",
                task_title="Second focus",
                current=current,
            )
        )

        old = json.loads(
            (self.repo / ".auto-dev" / "tasks" / f"{first['task_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(second["source_task_id"], first["task_id"])
        self.assertEqual(second["proof_policy"], "target-only")
        self.assertFalse(
            any(event.get("type") == "outcome_proof_revalidated" for event in old.get("events", []))
        )
        self.assertEqual(self.status()["id"], second["task_id"])

    def test_invalid_target_rolls_back_the_previous_focus(self) -> None:
        first = self.transition(
            self.spec(
                request_id="rollback-source",
                route="start-new",
                outcome_id="OUTCOME-ROLLBACK-SOURCE",
                task_title="Rollback source",
            )
        )
        before_active = (self.repo / ".auto-dev" / "active.json").read_bytes()
        before_project = (self.repo / ".auto-dev" / "project.json").read_bytes()
        before_tasks = sorted(path.name for path in (self.repo / ".auto-dev" / "tasks").glob("*.json"))
        before_outcomes = sorted(
            path.relative_to(self.repo / ".auto-dev").as_posix()
            for path in (self.repo / ".auto-dev" / "projects").glob("*/outcomes/*.json")
        )
        before_snapshots = sorted(path.name for path in (self.repo / ".auto-dev" / "snapshots").iterdir())
        failed = self.transition(
            self.spec(
                request_id="rollback-target",
                route="switch-superseded",
                outcome_id="OUTCOME-ROLLBACK-TARGET",
                task_title="Invalid rollback target",
                current=self.status(),
                valid_plan=False,
            ),
            check=False,
        )

        self.assertEqual(failed["returncode"], 2)
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(failed["committed"])
        self.assertEqual(failed["rollback_status"], "restored")
        self.assertEqual((self.repo / ".auto-dev" / "active.json").read_bytes(), before_active)
        self.assertEqual((self.repo / ".auto-dev" / "project.json").read_bytes(), before_project)
        self.assertEqual(
            sorted(path.name for path in (self.repo / ".auto-dev" / "tasks").glob("*.json")),
            before_tasks,
        )
        self.assertEqual(
            sorted(
                path.relative_to(self.repo / ".auto-dev").as_posix()
                for path in (self.repo / ".auto-dev" / "projects").glob("*/outcomes/*.json")
            ),
            before_outcomes,
        )
        self.assertEqual(
            sorted(path.name for path in (self.repo / ".auto-dev" / "snapshots").iterdir()),
            before_snapshots,
        )
        self.assertEqual(self.status()["id"], first["task_id"])
        failure_record = json.loads(
            (self.repo / ".auto-dev" / "last-transition.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failure_record["status"], "failed")

    def test_switch_passed_uses_existing_completion_gate(self) -> None:
        first = self.transition(
            self.spec(
                request_id="passed-source",
                route="start-new",
                outcome_id="OUTCOME-PASSED-SOURCE",
                task_title="Passed source",
            )
        )
        status = self.status()
        plan_revision = status["continuity_summary"]["plan_revision"]
        state_revision = status["state_revision"]
        current_node = status["continuity_summary"]["current_node"]
        self.cli(
            "proof",
            "--node", current_node,
            "--proof-id", "target-proof",
            "--plan-revision", str(plan_revision),
            "--state-revision", str(state_revision),
            "--command", f"{sys.executable} -c 'pass'",
        )
        status = self.status()
        self.cli(
            "checkpoint",
            "--node", current_node,
            "--status", "done",
            "--summary", "Source completed.",
            "--evidence", "Target proof passed.",
            "--plan-revision", str(status["continuity_summary"]["plan_revision"]),
            "--state-revision", str(status["state_revision"]),
        )
        status = self.status()
        self.cli(
            "task",
            "review",
            "--state-revision", str(status["state_revision"]),
            "--summary", "Ready for transition.",
            "--validation", "Target proof passed.",
            "--product-review-json",
            json.dumps(
                {
                    "completed": "The source task completed.",
                    "purpose": "Verify strict completion transition.",
                    "next_step": "Accept and switch.",
                    "user_impact": "The next focus can begin.",
                    "test": {
                        "status": "ready",
                        "entry": "CLI",
                        "role": "developer",
                        "steps": ["Inspect the result."],
                        "expected": "The task is complete.",
                        "prerequisites": [],
                    },
                }
            ),
        )
        review_ready = self.status()
        result = self.transition(
            self.spec(
                request_id="passed-target",
                route="switch-passed",
                outcome_id="OUTCOME-PASSED-TARGET",
                task_title="Passed target",
                current=review_ready,
            )
        )

        old = json.loads(
            (self.repo / ".auto-dev" / "tasks" / f"{first['task_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(old["status"], "passed")
        self.assertEqual(result["proof_policy"], "strict-completion")

    def test_preflight_failure_is_structured_and_keeps_the_ui_link(self) -> None:
        project = self.project()
        failed = self.transition(
            {
                "request_id": "bad-revision",
                "route": "start-new",
                "expected": {"project_revision": project["state_revision"] + 1},
                "confirmation_source": "User confirmed the fixture.",
                "target": {},
            },
            check=False,
        )

        self.assertEqual(failed["returncode"], 2)
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(failed["committed"])
        self.assertEqual(failed["rollback_status"], "not_started")
        self.assertTrue(failed["control_plane_url"].startswith("http://127.0.0.1:"))


if __name__ == "__main__":
    unittest.main()
