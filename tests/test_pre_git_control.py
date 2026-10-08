"""Regression coverage for pre-Git and durable local No-Git control."""

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
HOOK = PLUGIN_ROOT / "scripts" / "hook_dispatch.py"
SESSION_KEY = "abcdef0123456789abcdef01"


class PreGitControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-pre-git-")
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "README.md").write_text("fixture\n", encoding="utf-8")
        self.plugin_data = Path(self.temporary.name) / "plugin-data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(
        self,
        *arguments: str,
        check: bool = True,
        repo_root: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        target = repo_root or self.workspace
        result = subprocess.run(
            [sys.executable, str(CLI), *arguments, "--repo-root", str(target)],
            cwd=target,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(
        self,
        *arguments: str,
        check: bool = True,
        repo_root: Path | None = None,
    ) -> dict[str, Any]:
        result = self.command(*arguments, check=check, repo_root=repo_root)
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def hook(self, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        event = {
            "session_id": "pre-git-session",
            "turn_id": "pre-git-turn-1",
            "cwd": str(self.workspace),
            "model": "gpt-test",
            **payload,
        }
        environment = os.environ.copy()
        environment["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        environment["PLUGIN_DATA"] = str(self.plugin_data)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=self.workspace,
            input=json.dumps(event),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def clear_intake(self) -> dict[str, Any]:
        self.cli("intake", "turn", "--session-key", SESSION_KEY, "--turn-id", "local-turn")
        return self.cli(
            "intake", "assess",
            "--session-key", SESSION_KEY,
            "--turn-id", "local-turn",
            "--depth", "clear",
            "--summary", "bounded local workspace change",
            "--goal", "update the local README",
            "--inference", "the work has no unresolved product decision",
            "--scope", "README.md",
            "--acceptance", "the local file is updated",
        )

    def test_inspect_recommends_git_without_writing_and_local_control_runs_a_task(self) -> None:
        before = sorted(path.relative_to(self.workspace).as_posix() for path in self.workspace.rglob("*"))
        inspected = self.cli("project", "inspect")
        after = sorted(path.relative_to(self.workspace).as_posix() for path in self.workspace.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(inspected["status"], "git_setup_recommended")
        self.assertEqual(inspected["recommended_storage"], "git")

        project = self.cli(
            "project", "init", "--mode", "local", "--confirmation-source", "test local choice"
        )
        self.assertEqual(project["storage_mode"], "local")
        self.assertFalse((self.workspace / ".git").exists())
        self.assertEqual(self.cli("project", "inspect")["status"], "ready")
        nested = self.workspace / "nested"
        nested.mkdir()
        nested_inspect = self.cli("project", "inspect", repo_root=nested)
        self.assertEqual(nested_inspect["status"], "ready")
        self.assertEqual(Path(nested_inspect["workspace_root"]).resolve(), self.workspace.resolve())
        nested_init = self.cli(
            "project", "init", "--mode", "local", "--confirmation-source", "nested local choice",
            check=False,
            repo_root=nested,
        )
        self.assertNotEqual(nested_init["returncode"], 0)
        self.assertIn("nested control", nested_init["stderr"])
        self.assertFalse((nested / ".auto-dev").exists())

        intake = self.clear_intake()
        self.assertEqual(intake["gate"]["status"], "authorized")
        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Update the local README",
            "--requirement-receipt", "REQ-LOCAL",
            "--confirmation-source", "test local task",
            "--acceptance", "README update is verified",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "local test fixture",
        )
        self.assertEqual(started["status"], "active")
        status = self.cli("status", "--compact")
        self.assertEqual(status["workspace"]["storage_mode"], "local")
        self.assertEqual(status["workspace"]["vcs"], "none")
        self.assertEqual(status["delivery_contract"]["planned_scope"], ["README.md"])

    def test_local_control_requires_explicit_migration_after_git_is_added(self) -> None:
        (self.workspace / "preexisting.md").write_text("pre-existing fixture\n", encoding="utf-8")
        self.cli("project", "init", "--mode", "local", "--confirmation-source", "test local choice")
        self.clear_intake()
        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Migrate an active local task",
            "--requirement-receipt", "REQ-MIGRATE",
            "--confirmation-source", "test local task",
            "--acceptance", "The task survives Git adoption",
            "--scope", "README.md",
            "--validation", "python3 -c pass",
            "--evidence", "local migration fixture",
        )
        git_adoption = self.cli(
            "project", "init", "--mode", "git", "--confirmation-source", "test Git choice"
        )
        self.assertEqual(git_adoption["status"], "migration_available")
        self.assertTrue(git_adoption["git_initialized"])
        self.assertIsNone(git_adoption["head"])
        inspected = self.cli("project", "inspect")
        self.assertEqual(inspected["status"], "migration_available")
        migrated = self.cli(
            "project", "migrate",
            "--project-revision", str(inspected["project_revision"]),
            "--confirmation-source", "test explicit migration",
        )
        self.assertEqual(migrated["storage_mode"], "git")
        self.assertIsNone(migrated["head"])
        self.assertIn("project_migrated", migrated["receipt"])
        self.assertEqual(self.cli("project", "inspect")["storage_mode"], "git")
        status = self.cli("status", "--compact")
        self.assertEqual(status["id"], started["id"])
        self.assertEqual(status["workspace"]["storage_mode"], "git")
        self.assertNotIn("out_of_scope_changes", status["state_drift"])
        self.assertIn("preexisting.md", status["current_state"]["preexisting_changes"])

    def test_explicit_pre_git_auto_dev_blocks_product_writes_but_plain_prompt_does_not_enroll(self) -> None:
        plain = self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "write a note"})
        self.assertEqual(plain.stdout, "")
        self.assertFalse((self.plugin_data / "pre-git").exists())

        prompt = self.hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "[$auto-dev:auto-dev] build a new app"}
        )
        prompt_payload = json.loads(prompt.stdout)
        self.assertIn("pre_git_intake_pending", prompt_payload["systemMessage"])
        self.assertIn("initialize Git", prompt_payload["hookSpecificOutput"]["additionalContext"])

        write = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: app.py\n+print(1)\n*** End Patch"},
        })
        write_payload = json.loads(write.stdout)
        output = write_payload["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Pre-Git project discovery is active", output["permissionDecisionReason"])

    def test_pre_git_reports_when_post_initialization_activation_cannot_be_persisted(self) -> None:
        self.plugin_data.mkdir()
        (self.plugin_data / "session-activations").write_text("blocked\n", encoding="utf-8")

        prompt = self.hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "[$auto-dev] build a new app"}
        )
        payload = json.loads(prompt.stdout)
        self.assertIn("session_activation_unavailable", payload["systemMessage"])
        self.assertIn("pre-Git discovery gate", payload["hookSpecificOutput"]["additionalContext"])

        write = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: app.py\n+print(1)\n*** End Patch"},
        })
        output = json.loads(write.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Pre-Git project discovery is active", output["permissionDecisionReason"])

    def test_explicit_pre_git_activation_survives_project_initialization(self) -> None:
        prompt = self.hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "[$auto-dev] build a new app"}
        )
        self.assertIn("pre_git_intake_pending", prompt.stdout)

        self.cli("project", "init", "--mode", "local", "--confirmation-source", "test local choice")

        write = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    "*** Begin Patch\n"
                    "*** Update File: README.md\n+managed work\n"
                    "*** Add File: app.py\n+print(1)\n"
                    "*** Add File: tests/test_app.py\n+def test_app(): pass\n"
                    "*** End Patch"
                )
            },
        })
        output = json.loads(write.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn(
            "Product writes require an active Auto Dev task selected",
            output["permissionDecisionReason"],
        )


if __name__ == "__main__":
    unittest.main()
