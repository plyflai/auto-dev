"""Regression coverage for keeping Auto Dev from adopting its own Plugin source."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
HOOK = PLUGIN_ROOT / "scripts" / "hook_dispatch.py"


class SelfTargetGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-self-target-")
        self.root = Path(self.temporary.name)
        self.plugin = self.root / "auto-dev"
        (self.plugin / ".codex-plugin").mkdir(parents=True)
        (self.plugin / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "auto-dev", "version": "test"}), encoding="utf-8"
        )
        self.plugin_data = self.root / "plugin-data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def hook(self, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        event = {
            "session_id": "self-target-session",
            "turn_id": "self-target-turn",
            "cwd": str(self.plugin),
            "model": "gpt-test",
            **payload,
        }
        environment = os.environ.copy()
        environment["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        environment["PLUGIN_DATA"] = str(self.plugin_data)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=self.plugin,
            input=json.dumps(event),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    def cli(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(CLI), *arguments, "--repo-root", str(self.plugin)],
            cwd=self.plugin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def test_session_start_protects_plugin_source_without_reading_control_state(self) -> None:
        (self.plugin / ".auto-dev").mkdir()
        (self.plugin / ".auto-dev" / "project.json").write_text("{}", encoding="utf-8")

        result = self.hook({"hook_event_name": "SessionStart", "source": "startup"})

        payload = json.loads(result.stdout)
        self.assertIn("plugin_self_target", payload["systemMessage"])
        self.assertIn("do not create .auto-dev", payload["hookSpecificOutput"]["additionalContext"])
        self.assertFalse((self.plugin_data / "progress-servers").exists())

    def test_user_prompt_does_not_recreate_pre_git_marker_in_plugin_source(self) -> None:
        result = self.hook({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "[$auto-dev] inspect this source tree",
        })

        self.assertEqual(result.stdout, "")
        self.assertFalse((self.plugin_data / "pre-git").exists())

    def test_hook_denies_source_auto_dev_control_mutation(self) -> None:
        result = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    f"python3 {PLUGIN_ROOT / 'skills/auto-dev/scripts/auto_dev.py'} project init "
                    "--mode local --confirmation-source test"
                )
            },
        })

        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("own Plugin source", payload["hookSpecificOutput"]["permissionDecisionReason"])

    def test_cli_inspect_and_init_refuse_plugin_source(self) -> None:
        inspected = self.cli("project", "inspect")
        self.assertIn('"status": "plugin_self_target"', inspected.stdout)
        initialized = self.cli(
            "project", "init", "--mode", "local", "--confirmation-source", "test", check=False
        )
        self.assertNotEqual(initialized.returncode, 0)
        self.assertIn("will not initialize its own Plugin source", initialized.stderr)
        self.assertFalse((self.plugin / ".auto-dev").exists())


if __name__ == "__main__":
    unittest.main()
