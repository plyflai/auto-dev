"""P1 regression tests for governed workspace path policy."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))

import hook_dispatch  # noqa: E402
import hook_session_state  # noqa: E402


class P1WorkspacePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-p1-policy-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.plugin_data = self.root / "plugin-data"
        self.environment = patch.dict(
            os.environ,
            {"PLUGIN_ROOT": str(PLUGIN_ROOT), "PLUGIN_DATA": str(self.plugin_data)},
        )
        self.environment.start()
        self.init_repo(self.repo)
        self.cli("project", "init", "--confirmation-source", "policy fixture")
        self.cli(
            "start",
            "--tier", "direct",
            "--task", "Exercise governed workspace policy",
            "--requirement-receipt", "REQ-P1-POLICY",
            "--confirmation-source", "policy fixture",
            "--acceptance", "Path rules are enforced before product writes",
            "--scope", "src",
            "--scope", "production",
            "--scope", "migrations",
            "--scope", "auth",
            "--scope", ".env",
            "--validation", "python3 -m unittest tests.test_policy_feature",
        )
        self.cli(
            "plan",
            "--base-revision", "0",
            "--reason", "policy fixture",
            "--plan-json", json.dumps(self.plan_payload()),
        )
        self.set_policy(self.policy_payload(), revision=0)
        self.assertTrue(hook_session_state.activate_session(self.repo, {"session_id": "policy-session"}))

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    @staticmethod
    def plan_payload(*, current_node: str = "implement") -> dict[str, Any]:
        return {
            "goal": {
                "statement": "Exercise governed workspace policy",
                "acceptance": ["Path rules are enforced before product writes"],
                "source": "policy fixture",
            },
            "nodes": [
                {
                    "id": "implement",
                    "title": "Implement protected change",
                    "status": "active" if current_node == "implement" else "planned",
                    "outcome": {
                        "kind": "behavior_change",
                        "primary": "Protected changes follow confirmed policy",
                        "proofs": [{"id": "policy-proof", "description": "Run focused policy tests"}],
                    },
                },
                {
                    "id": "verify",
                    "title": "Verify protected change",
                    "status": "active" if current_node == "verify" else "planned",
                    "outcome": {
                        "kind": "decision",
                        "primary": "Policy behavior is accepted or blocked",
                        "proofs": [{"id": "review-proof", "description": "Review policy gate output"}],
                    },
                },
            ],
            "current_node": current_node,
            "next_action": "exercise path policy",
        }

    @staticmethod
    def policy_payload() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "protected_branches": ["main", "master", "production", "release/*"],
            "forbidden_paths": [
                {"id": "production", "pattern": "production/**", "reason": "Production is deployment-owned"},
            ],
            "approval_paths": [
                {"id": "migrations", "pattern": "migrations/**", "reason": "Schema changes need user approval"},
            ],
            "sensitive_paths": [
                {"id": "auth", "pattern": "auth/**", "reason": "Auth changes need strengthened proof"},
            ],
        }

    def init_repo(self, repo: Path) -> None:
        repo.mkdir()
        for directory in ("src", "production", "migrations", "auth", "tests"):
            (repo / directory).mkdir()
        files = {
            "src/app.py": "VALUE = 1\n",
            "production/config.py": "ENABLED = True\n",
            "migrations/001.sql": "select 1;\n",
            "auth/session.py": "def session(): return None\n",
            "tests/test_policy_feature.py": "# focused policy test\n",
            ".env": "EXAMPLE=placeholder\n",
        }
        for relative, content in files.items():
            (repo / relative).write_text(content, encoding="utf-8")
        self.exec("git", "init", "-q", cwd=repo)
        self.exec("git", "config", "user.name", "Auto Dev Policy Test", cwd=repo)
        self.exec("git", "config", "user.email", "auto-dev-policy@example.com", cwd=repo)
        self.exec("git", "add", ".", cwd=repo)
        self.exec("git", "commit", "-qm", "initial", cwd=repo)
        self.exec("git", "checkout", "-qb", "p1-policy", cwd=repo)

    def exec(
        self, *arguments: str, cwd: Path | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), cwd=cwd or self.repo, env=os.environ, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli_for(self, repo: Path, *arguments: str, check: bool = True) -> dict[str, Any]:
        result = self.exec(
            sys.executable, str(CLI), *arguments, "--repo-root", str(repo), cwd=repo, check=check,
        )
        if not check:
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        return json.loads(result.stdout)

    def cli(self, *arguments: str, check: bool = True) -> dict[str, Any]:
        return self.cli_for(self.repo, *arguments, check=check)

    def set_policy(
        self, payload: dict[str, Any], *, revision: int, check: bool = True,
    ) -> dict[str, Any]:
        return self.cli(
            "policy", "set",
            "--policy-revision", str(revision),
            "--policy-json", json.dumps(payload),
            "--confirmation-source", "user confirmed project policy",
            "--reason", "protect governed workspace paths",
            check=check,
        )

    def approve(self, *paths: str) -> dict[str, Any]:
        status = self.cli("status", "--compact")
        arguments = [
            "policy", "approve",
            "--policy-revision", str(status["workspace_policy"]["revision"]),
            "--state-revision", str(status["state_revision"]),
            "--node", str(status["continuity_summary"]["current_node"]),
            "--confirmation-source", "user approved this task crossing",
            "--reason", "apply the confirmed migration",
        ]
        for path in paths:
            arguments.extend(["--path", path])
        return self.cli(*arguments)

    def hook(self, tool_name: str, command: str, *, repo: Path | None = None) -> dict[str, Any] | None:
        target = repo or self.repo
        return hook_dispatch.dispatch({
            "session_id": "policy-session",
            "turn_id": "policy-turn",
            "hook_event_name": "PreToolUse",
            "cwd": str(target),
            "tool_name": tool_name,
            "tool_input": {"command": command},
        })

    @staticmethod
    def patch(path: str) -> str:
        return (
            "*** Begin Patch\n"
            f"*** Update File: {path}\n"
            "@@\n"
            "+policy change\n"
            "*** End Patch"
        )

    @staticmethod
    def workspace_snapshot(repo: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in repo.rglob("*"):
            if not path.is_file() or ".git" in path.relative_to(repo).parts:
                continue
            result[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_inspect_is_zero_side_effect_and_system_rules_are_always_effective(self) -> None:
        repo = self.root / "uninitialized"
        repo.mkdir()
        (repo / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.exec("git", "init", "-q", cwd=repo)
        before = self.workspace_snapshot(repo)
        result = self.cli_for(
            repo, "policy", "inspect", "--path", "src.py", "--path", ".git/config",
        )
        self.assertEqual(before, self.workspace_snapshot(repo))
        self.assertFalse((repo / ".auto-dev").exists())
        self.assertEqual(result["paths"][0]["classification"], "allowed")
        self.assertEqual(result["paths"][1]["classification"], "forbidden")
        self.assertTrue(result["receipt"].startswith("🚧 Auto Dev Policy: policy_inspected"))

    def test_set_requires_initialized_project_confirmation_and_current_revision(self) -> None:
        repo = self.root / "no-project"
        repo.mkdir()
        self.exec("git", "init", "-q", cwd=repo)
        rejected = self.cli_for(
            repo,
            "policy", "set", "--policy-revision", "0",
            "--policy-json", json.dumps(self.policy_payload()),
            "--confirmation-source", "user", "--reason", "project policy",
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertFalse((repo / ".auto-dev").exists())

        config = self.repo / ".auto-dev" / "config.json"
        before = config.read_bytes()
        stale = self.set_policy(self.policy_payload(), revision=0, check=False)
        self.assertNotEqual(stale["returncode"], 0)
        self.assertEqual(before, config.read_bytes())
        missing_confirmation = self.cli(
            "policy", "set", "--policy-revision", "1",
            "--policy-json", json.dumps(self.policy_payload()),
            "--reason", "project policy", check=False,
        )
        self.assertEqual(missing_confirmation["returncode"], 2)
        self.assertEqual(before, config.read_bytes())

    def test_invalid_patterns_duplicate_ids_and_unknown_allow_fields_leave_policy_unchanged(self) -> None:
        config = self.repo / ".auto-dev" / "config.json"
        before = config.read_bytes()
        invalid_documents = [
            {**self.policy_payload(), "forbidden_paths": [{"pattern": "/tmp/**", "reason": "absolute"}]},
            {**self.policy_payload(), "forbidden_paths": [{"pattern": "../outside/**", "reason": "escape"}]},
            {
                **self.policy_payload(),
                "forbidden_paths": [
                    {"id": "duplicate", "pattern": "one/**", "reason": "one"},
                    {"id": "duplicate", "pattern": "two/**", "reason": "two"},
                ],
            },
            {
                **self.policy_payload(),
                "forbidden_paths": [{"id": "same-a", "pattern": "same/**", "reason": "one"}],
                "approval_paths": [{"id": "same-b", "pattern": "same/**", "reason": "two"}],
            },
            {**self.policy_payload(), "allowed_paths": ["production/**"]},
        ]
        for document in invalid_documents:
            with self.subTest(document=document):
                result = self.set_policy(document, revision=1, check=False)
                self.assertNotEqual(result["returncode"], 0)
                self.assertEqual(before, config.read_bytes())

    def test_project_rules_cannot_weaken_system_forbidden_paths(self) -> None:
        payload = {
            "schema_version": 1,
            "sensitive_paths": [
                {"id": "pretend-git-sensitive", "pattern": ".git/**", "reason": "attempted downgrade"},
            ],
        }
        self.set_policy(payload, revision=1)
        inspected = self.cli("policy", "inspect", "--path", ".git/config")
        evaluation = inspected["paths"][0]
        self.assertTrue(evaluation["forbidden"])
        self.assertTrue(evaluation["sensitive"])
        self.assertEqual(evaluation["classification"], "forbidden")

    def test_malformed_policy_is_visible_and_fails_closed_without_repair_side_effects(self) -> None:
        config = self.repo / ".auto-dev" / "config.json"
        config.write_text("{malformed", encoding="utf-8")
        status = self.cli("status", "--compact")
        self.assertEqual(status["workspace_policy"]["status"], "unavailable")
        self.assertIn("workspace_policy_unavailable", status["strict_blockers"])
        denied = self.hook("apply_patch", self.patch("src/app.py"))
        self.assertIn("policy_unavailable", denied["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(config.read_text(encoding="utf-8"), "{malformed")

    def test_hook_denies_forbidden_and_requires_fresh_exact_path_approval(self) -> None:
        forbidden = self.hook("apply_patch", self.patch("production/config.py"))
        self.assertEqual(forbidden["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("forbidden_path", forbidden["hookSpecificOutput"]["permissionDecisionReason"])

        pending = self.hook("apply_patch", self.patch("migrations/001.sql"))
        self.assertEqual(pending["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("approval_required", pending["hookSpecificOutput"]["permissionDecisionReason"])
        approved = self.approve("migrations/001.sql")
        self.assertTrue(approved["receipt"].startswith("🚧 Auto Dev Policy: policy_approved"))
        self.assertIsNone(self.hook("apply_patch", self.patch("migrations/001.sql")))

        another = self.repo / "migrations" / "002.sql"
        another.write_text("select 2;\n", encoding="utf-8")
        exact_only = self.hook("apply_patch", self.patch("migrations/002.sql"))
        self.assertIn("approval_required", exact_only["hookSpecificOutput"]["permissionDecisionReason"])

    def test_policy_plan_and_node_changes_make_approval_stale(self) -> None:
        self.approve("migrations/001.sql")
        self.set_policy(self.policy_payload(), revision=1)
        policy_stale = self.cli("status", "--compact")["workspace_policy"]["approvals"]["latest"]
        self.assertFalse(policy_stale["fresh"])
        self.assertIn("policy_revision_changed", policy_stale["stale_reasons"])

        self.approve("migrations/001.sql")
        status = self.cli("status", "--compact")
        self.cli(
            "plan", "--base-revision", str(status["continuity_summary"]["plan_revision"]),
            "--reason", "move to verification",
            "--plan-json", json.dumps(self.plan_payload(current_node="verify")),
        )
        node_stale = self.cli("status", "--compact")["workspace_policy"]["approvals"]["latest"]
        self.assertFalse(node_stale["fresh"])
        self.assertIn("plan_revision_changed", node_stale["stale_reasons"])
        self.assertIn("current_node_changed", node_stale["stale_reasons"])

    def test_sensitive_paths_require_strengthened_evidence_and_redaction_contract(self) -> None:
        allowed = self.hook("apply_patch", self.patch("auth/session.py"))
        self.assertIsNone(allowed)
        active_path = self.repo / ".auto-dev" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        active["validation_plan"] = []
        active["continuity"]["plan"]["nodes"][0]["outcome"]["proofs"] = []
        active_path.write_text(json.dumps(active), encoding="utf-8")
        task_path = self.repo / ".auto-dev" / "tasks" / f"{active['id']}.json"
        task_path.write_text(json.dumps(active), encoding="utf-8")
        denied = self.hook("apply_patch", self.patch("auth/session.py"))
        reason = denied["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("sensitive_evidence_required", reason)
        self.assertIn("redacted evidence", reason)

    def test_active_policy_fails_closed_for_unknown_bash_write_and_precedes_quick_write(self) -> None:
        unknown = self.hook("Bash", "printf 'change' > src/app.py")
        self.assertIn("path_required", unknown["hookSpecificOutput"]["permissionDecisionReason"])

        status = self.cli("status", "--compact")
        self.cli(
            "task", "pause", "--task-id", status["id"],
            "--state-revision", str(status["state_revision"]),
            "--reason", "exercise policy-aware Quick Write",
        )
        forbidden = self.hook("apply_patch", self.patch("production/config.py"))
        self.assertIn("forbidden_path", forbidden["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.hook("apply_patch", self.patch("src/app.py")))

    def test_canonical_policy_commands_are_allowed_and_legacy_runctl_policy_is_denied(self) -> None:
        canonical = self.hook(
            "Bash",
            f"{sys.executable} {CLI} policy set --policy-revision 1 --policy-json '{{}}' "
            "--confirmation-source user --reason update --repo-root .",
        )
        self.assertIsNone(canonical)
        legacy = self.hook(
            "Bash",
            "python3 skills/auto-dev/scripts/runctl.py policy inspect --path src/app.py --repo-root .",
        )
        self.assertEqual(legacy["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("canonical auto_dev.py policy", legacy["hookSpecificOutput"]["permissionDecisionReason"])

    def test_handoff_preserves_approval_history_but_recomputes_target_freshness(self) -> None:
        self.approve("migrations/001.sql")
        packet = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(packet))

        target = self.root / "target"
        self.init_repo(target)
        self.cli_for(target, "project", "init", "--confirmation-source", "target fixture")
        self.cli_for(
            target,
            "policy", "set", "--policy-revision", "0",
            "--policy-json", json.dumps(self.policy_payload()),
            "--confirmation-source", "user confirmed target policy",
            "--reason", "mirror source policy",
        )
        self.cli_for(target, "handoff", "import", "--file", str(packet))
        status = self.cli_for(target, "status", "--compact")
        self.assertEqual(len(status["continuity"]["policy_approvals"]), 1)
        approval = status["workspace_policy"]["approvals"]["latest"]
        self.assertFalse(approval["fresh"])
        self.assertIn("workspace_changed", approval["stale_reasons"])

    def test_status_session_context_and_progress_page_expose_bounded_policy_summary(self) -> None:
        status = self.cli("status", "--compact")
        policy = status["workspace_policy"]
        self.assertEqual(policy["revision"], 1)
        self.assertEqual(policy["rule_counts"], {
            "forbidden_paths": 1, "approval_paths": 1, "sensitive_paths": 1,
        })
        context = hook_dispatch.control_context(self.repo, status, "policy_fixture")
        self.assertIn('"workspace_policy"', context)
        self.assertNotIn('"effective_rules"', context)
        progress = (PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "progress_page.html").read_text(
            encoding="utf-8",
        )
        self.assertIn('id="policy-summary"', progress)
        self.assertIn("policyApprovals", progress)


if __name__ == "__main__":
    unittest.main()
