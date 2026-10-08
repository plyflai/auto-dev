"""Integration tests for Auto Dev's lifecycle Hook dispatcher."""

from __future__ import annotations

import json
import importlib.util
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
HOOK = PLUGIN_ROOT / "scripts" / "hook_dispatch.py"
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))
SCRIPTS = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contract_lineage import contract_hash  # noqa: E402
import hook_session_state  # noqa: E402

HOOK_SPEC = importlib.util.spec_from_file_location("auto_dev_hook_dispatch", HOOK)
assert HOOK_SPEC is not None and HOOK_SPEC.loader is not None
hook_dispatch = importlib.util.module_from_spec(HOOK_SPEC)
HOOK_SPEC.loader.exec_module(hook_dispatch)


class AutoDevHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-hook-test-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.plugin_data = self.root / "plugin-data"
        self.execute("git", "init", "-q", cwd=self.repo)
        self.execute("git", "config", "user.name", "Auto Dev Hook Test", cwd=self.repo)
        self.execute("git", "config", "user.email", "auto-dev@example.com", cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.execute("git", "add", "README.md", cwd=self.repo)
        self.execute("git", "commit", "-qm", "init", cwd=self.repo)
        self.execute("git", "checkout", "-qb", "hook-test", cwd=self.repo)
        self.cli(
            "start",
            "--tier",
            "team",
            "--task",
            "Deliver the hook-aware feature",
            "--requirement-receipt",
            "REQ-HOOK",
            "--confirmation-source",
            "test fixture",
            "--acceptance",
            "Hooks restore current control state",
            "--scope",
            "README.md",
            "--validation",
            "python3 -m unittest",
            "--capability",
            "parallel-work",
            "--capability-evidence",
            "parallel-work=two independent workstreams",
            *self.skip_capabilities(),
        )
        plan = {
            "goal": {
                "statement": "Deliver the hook-aware feature",
                "acceptance": ["Hooks restore current control state"],
                "source": "test fixture",
            },
            "nodes": [
                {
                    "id": "implement",
                    "title": "Implement hooks",
                    "status": "active",
                    "outcome": {
                        "kind": "behavior_change",
                        "primary": "Hook state is restored for the active task",
                        "proofs": [{"id": "hook-contract", "description": "Run hook contract tests"}],
                    },
                },
                {
                    "id": "verify",
                    "title": "Verify hooks",
                    "status": "planned",
                    "depends_on": ["implement"],
                    "outcome": {
                        "kind": "decision",
                        "primary": "Hook behavior is accepted or a gap is recorded",
                        "proofs": [{"id": "review", "description": "Review hook contract output"}],
                    },
                },
            ],
            "current_node": "implement",
            "next_action": "run hook contract tests",
        }
        self.cli(
            "plan",
            "--base-revision",
            "0",
            "--reason",
            "hook fixture",
            "--plan-json",
            json.dumps(plan),
        )
        self.activate_session()

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

    @staticmethod
    def skip_capabilities() -> list[str]:
        values: list[str] = []
        for name in (
            "architecture",
            "data-contract",
            "debug-observability",
            "gui",
            "release",
            "compliance",
        ):
            values.extend(["--skip", f"{name}=not required by fixture"])
        return values

    def execute(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments),
            cwd=cwd or self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.execute(sys.executable, str(CLI), *arguments, "--repo-root", str(self.repo))

    def compact_status(self) -> dict[str, Any]:
        return json.loads(self.cli("status", "--compact").stdout)

    def test_gate_profile_preserves_all_pre_tool_decision_fields(self) -> None:
        full = self.compact_status()
        gate, error = hook_dispatch.read_status(self.repo, profile="gate")
        self.assertIsNone(error)
        self.assertIsInstance(gate, dict)
        for key in (
            "status",
            "id",
            "state_revision",
            "project_revision",
            "context_key",
            "protected_branch",
            "continuity_status",
            "bootstrap_status",
            "contract_gate",
            "contract_capsule",
            "delivery_contract",
            "current_state",
            "state_drift",
            "strict_blockers",
            "product_write_blockers",
            "workspace_policy",
            "workspace_checkpoint_protection",
            "intake_gate",
        ):
            self.assertEqual(gate.get(key), full.get(key), msg=key)
        for key in ("current_node", "pending_action"):
            self.assertEqual(
                gate.get("continuity_summary", {}).get(key),
                full.get("continuity_summary", {}).get(key),
                msg=f"continuity_summary.{key}",
            )

    def test_hook_profile_keeps_control_context_without_full_hierarchy_projection(self) -> None:
        full = self.compact_status()
        with patch.object(
            hook_dispatch.runctl,
            "list_outcome_records",
            side_effect=AssertionError("hook profile must not enumerate the outcome graph"),
        ):
            hook, error = hook_dispatch.read_status(self.repo)
        self.assertIsNone(error)
        self.assertIsInstance(hook, dict)
        for key in (
            "status",
            "id",
            "state_revision",
            "project_revision",
            "context_key",
            "continuity_status",
            "contract_gate",
            "contract_capsule",
            "delivery_contract",
            "workspace_policy",
            "strict_blockers",
        ):
            self.assertEqual(hook.get(key), full.get(key), msg=key)
        hierarchy = hook.get("hierarchy", {})
        self.assertIn("control_plane_upgrade", hierarchy)
        self.assertIn("execution_focus", hierarchy)
        self.assertNotIn("outcome_graph", hierarchy)
        self.assertNotIn("capability_map", hierarchy)
        self.assertNotIn("activities", hierarchy)

    def test_hook_read_cache_reuses_status_identity_and_lease_then_invalidates(self) -> None:
        event = {"session_id": "cache-session"}
        with hook_dispatch.hook_evaluation_scope(), patch.object(
            hook_dispatch.runctl,
            "build_status_payload",
            wraps=hook_dispatch.runctl.build_status_payload,
        ) as status_call, patch.object(
            hook_dispatch.runctl,
            "build_status_identity",
            wraps=hook_dispatch.runctl.build_status_identity,
        ) as identity_call, patch.object(
            hook_dispatch,
            "writer_lease_status",
            return_value={"status": "available"},
        ) as lease_call:
            self.assertIsNotNone(hook_dispatch.read_status(self.repo)[0])
            self.assertIsNotNone(hook_dispatch.read_status(self.repo)[0])
            self.assertIsNotNone(hook_dispatch.read_status_identity(self.repo)[0])
            self.assertIsNotNone(hook_dispatch.read_status_identity(self.repo)[0])
            self.assertEqual(
                hook_dispatch.read_writer_lease_status(
                    self.repo, event, branch_key="hook-test"
                ),
                {"status": "available"},
            )
            self.assertEqual(
                hook_dispatch.read_writer_lease_status(
                    self.repo, event, branch_key="hook-test"
                ),
                {"status": "available"},
            )
            self.assertEqual(status_call.call_count, 1)
            self.assertEqual(identity_call.call_count, 1)
            self.assertEqual(lease_call.call_count, 1)

            hook_dispatch.invalidate_hook_control_cache(self.repo)
            self.assertIsNotNone(hook_dispatch.read_status(self.repo)[0])
            self.assertIsNotNone(hook_dispatch.read_status_identity(self.repo)[0])
            hook_dispatch.read_writer_lease_status(self.repo, event, branch_key="hook-test")
            self.assertEqual(status_call.call_count, 2)
            self.assertEqual(identity_call.call_count, 2)
            self.assertEqual(lease_call.call_count, 2)

    def install_strict_contract(self, *, stale_parent: bool = False) -> None:
        contract = {
            "id": "SKINCARD-BASELINE",
            "mode": "legacy-parity",
            "mainline": "Fork the legacy backend and replace only order entry with card redemption.",
            "hard_constraints": [
                {"id": "H-FORK", "kind": "must_preserve", "text": "Do not replace the legacy backend with a greenfield admin.", "anchor": True},
            ],
            "forbidden_moves": ["Do not invent overview, jobs, or audit product surfaces without legacy coverage."],
            "replacement_map": [
                {"id": "R-ORDER", "from": "order identity", "to": "card redemption identity"},
            ],
            "required_coverage": [
                {"id": "C-ROUTES", "description": "Legacy route matrix", "evidence_kind": "route-matrix", "write_gate": "before_product_write"},
            ],
        }
        active_path = self.repo / ".auto-dev" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        active["contract_snapshot"] = contract
        active["contract_status"] = "strict"
        active["contract_coverage_ids"] = ["C-ROUTES"]
        active["contract_parent_hash"] = "outdated-parent-contract" if stale_parent else None
        active["continuity"]["plan"]["contract_hash"] = contract_hash(contract)
        active_path.write_text(json.dumps(active), encoding="utf-8")
        task_path = self.repo / ".auto-dev" / "tasks" / f"{active['id']}.json"
        task_path.write_text(json.dumps(active), encoding="utf-8")

    def make_review_ready(self, *, include_product_review: bool = True) -> dict[str, Any]:
        state = self.compact_status()
        self.cli(
            "proof",
            "--node",
            "implement",
            "--proof-id",
            "hook-contract",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--command",
            "python3 -c 'pass'",
        )
        state = self.compact_status()
        self.cli(
            "checkpoint",
            "--node",
            "implement",
            "--status",
            "done",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--summary",
            "hook implementation proved",
            "--evidence",
            "hook contract passed",
            "--next-node",
            "verify",
            "--next-action",
            "run final hook review",
        )
        state = self.compact_status()
        self.cli(
            "proof",
            "--node",
            "verify",
            "--proof-id",
            "review",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--command",
            "python3 -c 'pass'",
        )
        state = self.compact_status()
        self.cli(
            "checkpoint",
            "--node",
            "verify",
            "--status",
            "done",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--summary",
            "hook review proved",
            "--evidence",
            "review proof passed",
        )
        state = self.compact_status()
        review_arguments = [
            "task",
            "review",
            "--state-revision",
            str(state["state_revision"]),
            "--summary",
            "hook behavior is ready for user review",
            "--file",
            "README.md",
            "--validation",
            "python3 -m unittest tests.test_hooks",
        ]
        if include_product_review:
            review_arguments.extend([
                "--product-review-json",
                json.dumps({
                    "completed": "已完成 Hook 行为验证和 review_ready 状态交接",
                    "purpose": "确保产品写入在用户审阅前受到保护",
                    "next_step": "产品可以先检查控制面状态，再决定接受或提出相关反馈",
                    "user_impact": "普通用户暂时看不到界面变化，本阶段主要增强交付保护和可审阅性",
                    "test": {
                        "status": "ready",
                        "entry": "Auto Dev 控制面状态",
                        "role": "产品验收人",
                        "steps": ["查看任务状态为 review_ready", "确认相关产品写入会等待用户审阅"],
                        "expected": "状态清晰显示待审阅，未接受前不会继续写入产品文件",
                    },
                }, ensure_ascii=False),
            ])
        self.cli(*review_arguments)
        return self.compact_status()

    def hook(
        self,
        payload: dict[str, Any],
        *,
        cwd: Path | None = None,
        plugin_root: Path = PLUGIN_ROOT,
        include_plugin_data: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        event = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": str(cwd or self.repo),
            "model": "gpt-test-one",
            **payload,
        }
        environment = os.environ.copy()
        environment["PLUGIN_ROOT"] = str(plugin_root)
        if include_plugin_data:
            environment["PLUGIN_DATA"] = str(self.plugin_data)
        else:
            environment.pop("PLUGIN_DATA", None)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            cwd=cwd or self.repo,
            input=json.dumps(event),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def activate_session(self, *, session_id: str = "session-1", root: Path | None = None) -> None:
        with patch.dict(os.environ, {"PLUGIN_DATA": str(self.plugin_data)}):
            self.assertTrue(
                hook_session_state.activate_session(root or self.repo, {"session_id": session_id})
            )

    def session_is_active(self, *, session_id: str, root: Path | None = None) -> bool:
        with patch.dict(os.environ, {"PLUGIN_DATA": str(self.plugin_data)}):
            return hook_session_state.session_is_active(root or self.repo, {"session_id": session_id})

    @staticmethod
    def output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        return json.loads(result.stdout)

    def assert_hook_receipt(
        self,
        result: subprocess.CompletedProcess[str],
        trigger: str,
    ) -> dict[str, Any]:
        output = self.output(result)
        receipt = output["systemMessage"]
        self.assertTrue(receipt.startswith("🪝 Auto Dev Hook:"))
        self.assertIn(trigger, receipt)
        self.assertRegex(receipt, r"\| [^|]+ / [^|]+")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("verbatim exactly once", context)
        self.assertIn(receipt, context)
        return output

    def test_compact_status_contains_delivery_contract(self) -> None:
        status = self.compact_status()
        contract = status["delivery_contract"]
        self.assertEqual(contract["planned_scope"], ["README.md"])
        self.assertEqual(contract["scope_amendments"], [])
        self.assertEqual(contract["validation_plan"], ["python3 -m unittest"])
        self.assertEqual(contract["capabilities"]["enabled"], ["parallel-work"])
        self.assertIn("parallel_agents", contract["budgets"])
        self.assertEqual(contract["stop_conditions"], [
            "出现新的产品行为，需要进行需求差异确认",
            "同类失败连续出现两次",
            "实现修复预算已耗尽",
        ])

    def test_rolling_graph_gate_enforces_active_packet_write_scope(self) -> None:
        status = {
            "status": "active",
            "id": "AUTO-DEV-ROLLING",
            "state_revision": 5,
            "strict_blockers": [],
            "product_write_blockers": [],
            "workspace_checkpoint_protection": {
                "before_pending": [], "before_invalid": [],
            },
            "contract_gate": {"status": "legacy", "prewrite_missing": []},
            "contract_capsule": {"status": "legacy"},
            "continuity_summary": {
                "plan_strategy": "rolling_graph",
                "current_node": "packet-a",
                "current_node_role": "work_packet",
                "active_write_scope": ["src/a.py"],
            },
            "delivery_contract": {"planned_scope": ["src"]},
        }
        with patch.object(hook_dispatch, "product_write_paths", return_value=["src/a.py"]):
            allowed = hook_dispatch.product_write_reason(self.repo, {}, status)
        self.assertIsNone(allowed)
        with patch.object(hook_dispatch, "product_write_paths", return_value=["src/b.py"]):
            denied = hook_dispatch.product_write_reason(self.repo, {}, status)
        self.assertIn("escapes active node packet-a write_scope", denied or "")
        status["continuity_summary"]["current_node"] = None
        status["continuity_summary"]["current_node_role"] = None
        with patch.object(hook_dispatch, "product_write_paths", return_value=["src/a.py"]):
            no_focus = hook_dispatch.product_write_reason(self.repo, {}, status)
        self.assertIn("require an active work_packet or integration node", no_focus or "")

    def test_strict_contract_capsule_is_injected_and_incomplete_plan_blocks_product_writes(self) -> None:
        self.install_strict_contract()

        result = self.hook({"hook_event_name": "SessionStart", "source": "compact"})
        output = self.assert_hook_receipt(result, "session_compact")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"contract":{"status":"strict"', context)
        self.assertIn('"mainline":"Fork the legacy backend', context)
        self.assertIn('"forbidden_moves":["Do not invent overview', context)
        self.assertIn('"contract_gate":{"status":"plan_incomplete"', context)
        self.assertIn("Preserve the effective contract capsule", context)

        denied = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+wrong surface\n*** End Patch"},
        })
        output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn("contract_plan_incomplete", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_user_prompt_uses_a_short_mainline_pulse(self) -> None:
        self.install_strict_contract()

        result = self.hook({"hook_event_name": "UserPromptSubmit", "turn_id": "pulse-turn"})
        output = self.assert_hook_receipt(result, "hook_activated")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Auto Dev mainline pulse", context)
        self.assertIn("Fork the legacy backend", context)
        self.assertIn("Do not replace the legacy backend", context)
        self.assertNotIn('"delivery_contract"', context)
        self.assertLess(len(context), 2400)

    def test_prewrite_coverage_blocks_product_write_after_plan_is_complete(self) -> None:
        self.install_strict_contract()
        active_path = self.repo / ".auto-dev" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        node = active["continuity"]["plan"]["nodes"][0]
        node["coverage_ids"] = ["C-ROUTES"]
        node["outcome"]["proofs"][0]["coverage_ids"] = ["C-ROUTES"]
        node["outcome"]["proofs"][0]["evidence_kind"] = "route-matrix"
        active["continuity"]["plan"]["contract_hash"] = contract_hash(active["contract_snapshot"])
        active_path.write_text(json.dumps(active), encoding="utf-8")
        task_path = self.repo / ".auto-dev" / "tasks" / f"{active['id']}.json"
        task_path.write_text(json.dumps(active), encoding="utf-8")

        status = self.compact_status()
        self.assertEqual(status["contract_gate"]["status"], "strict")
        self.assertEqual(status["contract_gate"]["prewrite_missing"], ["C-ROUTES"])
        denied = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+blocked\n*** End Patch"},
        })
        output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("prewrite coverage", reason)
        self.assertIn("C-ROUTES", reason)

    def test_stale_strict_contract_blocks_product_writes_before_execution(self) -> None:
        self.install_strict_contract(stale_parent=True)

        status = self.compact_status()
        self.assertEqual(status["contract_gate"]["status"], "stale")
        self.assertIn("contract_stale", status["strict_blockers"])
        denied = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+stale contract write\n*** End Patch"},
        })
        output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn("contract_stale", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_strict_plan_is_stale_when_its_contract_snapshot_hash_is_missing(self) -> None:
        self.install_strict_contract()
        active_path = self.repo / ".auto-dev" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        active["continuity"]["plan"].pop("contract_hash")
        active_path.write_text(json.dumps(active), encoding="utf-8")
        task_path = self.repo / ".auto-dev" / "tasks" / f"{active['id']}.json"
        task_path.write_text(json.dumps(active), encoding="utf-8")

        status = self.compact_status()
        self.assertEqual(status["contract_gate"]["status"], "plan_stale")
        self.assertIn("contract_plan_stale", status["strict_blockers"])

    def test_session_compact_rehydrates_authoritative_context(self) -> None:
        result = self.hook({"hook_event_name": "SessionStart", "source": "compact"})
        payload = self.assert_hook_receipt(result, "session_compact")
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        context = output["additionalContext"]
        self.assertIn('"trigger":"session_compact"', context)
        self.assertIn('"current_node":{"id":"implement"', context)
        self.assertIn('"verification_summary":{"node_id":"implement"', context)
        self.assertIn('"planned_scope":["README.md"]', context)
        self.assertIn('"enabled_capabilities":["parallel-work"]', context)
        self.assertRegex(payload["systemMessage"], r"state=R\d+")
        self.assertIn("node=implement", payload["systemMessage"])
        self.assertRegex(payload["systemMessage"], r"milestone=M\d+:delivery")
        match = re.search(
            r"\[control-plane\]\((http://127\.0\.0\.1:\d+/)(?:\?session_key=([a-f0-9]{24}))?\)",
            payload["systemMessage"],
        )
        self.assertIsNotNone(match)
        control_plane_url = match.group(1) if match else ""
        self.assertTrue(match.group(2) if match else "")
        with urllib.request.urlopen(control_plane_url + "api/health", timeout=1) as response:
            health = json.load(response)
        self.assertEqual(health["task_id"], self.compact_status()["id"])

        restarted = self.hook({"hook_event_name": "SessionStart", "source": "resume"})
        restarted_output = self.assert_hook_receipt(restarted, "session_resume")
        restarted_match = re.search(
            r"\[control-plane\]\((http://127\.0\.0\.1:\d+/)(?:\?session_key=([a-f0-9]{24}))?\)",
            restarted_output["systemMessage"],
        )
        self.assertIsNotNone(restarted_match)
        self.assertEqual(restarted_match.group(1) if restarted_match else "", control_plane_url)
        self.assertEqual(restarted_match.group(2) if restarted_match else "", match.group(2) if match else "")

    def test_activated_user_prompt_reports_hook_activation(self) -> None:
        result = self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "continue"})
        output = self.assert_hook_receipt(result, "hook_activated")
        self.assertNotIn("[control-plane]", output["systemMessage"])

    def test_managed_project_auto_resumes_without_an_explicit_auto_dev_reference(self) -> None:
        inactive_session = "inactive-session"
        control_snapshot = {
            path.relative_to(self.repo / ".auto-dev").as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in (self.repo / ".auto-dev").rglob("*")
            if path.is_file()
        }
        startup = self.hook({
            "session_id": inactive_session,
            "hook_event_name": "SessionStart",
            "source": "startup",
        })
        startup_output = self.assert_hook_receipt(startup, "session_startup")
        self.assertIn("session-role=writer-available", startup_output["systemMessage"])
        self.assertTrue(self.session_is_active(session_id=inactive_session))
        self.assertEqual(
            control_snapshot,
            {
                path.relative_to(self.repo / ".auto-dev").as_posix(): (
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
                for path in (self.repo / ".auto-dev").rglob("*")
                if path.is_file()
            },
        )

        prompt = self.hook({
            "session_id": inactive_session,
            "turn_id": "inactive-turn",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "replace the inline form",
        })
        self.assert_hook_receipt(prompt, "hook_activated")
        self.assertTrue(self.session_is_active(session_id=inactive_session))

        product_patch = self.hook({
            "session_id": inactive_session,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+ordinary work\n*** End Patch"},
        })
        product_output = self.assert_hook_receipt(product_patch, "pre_tool_use_denied")
        self.assertIn("Requirement intake is incomplete", product_output["hookSpecificOutput"]["permissionDecisionReason"])

        control_patch = self.hook({
            "session_id": inactive_session,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: .auto-dev/active.json\n*** End Patch"},
        })
        control_output = self.assert_hook_receipt(control_patch, "pre_tool_use_denied")
        self.assertIn("Direct edits to .auto-dev state", control_output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_explicit_auto_dev_reference_activates_only_the_current_session(self) -> None:
        explicit_session = "explicit-session"
        prompt = self.hook({
            "session_id": explicit_session,
            "turn_id": "explicit-turn",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "[$auto-dev] update the delivery flow",
        })
        self.assert_hook_receipt(prompt, "hook_activated")
        self.assertTrue(self.session_is_active(session_id=explicit_session))

        pending_patch = self.hook({
            "session_id": explicit_session,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+managed work\n*** End Patch"},
        })
        pending_output = self.assert_hook_receipt(pending_patch, "pre_tool_use_denied")
        self.assertIn("Requirement intake is incomplete", pending_output["hookSpecificOutput"]["permissionDecisionReason"])

        fresh_session_patch = self.hook({
            "session_id": "fresh-session",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+fresh ordinary work\n*** End Patch"},
        })
        self.assertEqual(fresh_session_patch.stdout, "")

    def test_explicit_auto_dev_reports_when_session_activation_cannot_be_persisted(self) -> None:
        unavailable_session = "activation-storage-unavailable"
        prompt = self.hook(
            {
                "session_id": unavailable_session,
                "turn_id": "activation-storage-turn",
                "hook_event_name": "UserPromptSubmit",
                "prompt": "[$auto-dev] update the delivery flow",
            },
            include_plugin_data=False,
        )
        self.assert_hook_receipt(prompt, "session_activation_unavailable")
        self.assertFalse(self.session_is_active(session_id=unavailable_session))

        product_patch = self.hook({
            "session_id": unavailable_session,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+ordinary work\n*** End Patch"},
        })
        self.assertEqual(product_patch.stdout, "")

    def test_compaction_and_subagent_start_auto_resume_existing_session(self) -> None:
        inactive_session = "inactive-session"
        compact = self.hook({
            "session_id": inactive_session,
            "hook_event_name": "SessionStart",
            "source": "compact",
        })
        compact_output = self.assert_hook_receipt(compact, "session_compact")
        self.assertIn("session-role=writer-available", compact_output["systemMessage"])
        self.assertTrue(self.session_is_active(session_id=inactive_session))

        subagent = self.hook({
            "session_id": inactive_session,
            "hook_event_name": "SubagentStart",
            "agent_id": "inactive-agent",
            "agent_type": "worker",
        })
        self.assert_hook_receipt(subagent, "subagent_worker")

    def test_new_session_takes_over_after_contention_and_old_session_becomes_observer(self) -> None:
        old_session = "old-writer-session"
        new_session = "new-writer-session"
        self.assert_hook_receipt(
            self.hook({
                "session_id": old_session,
                "hook_event_name": "SessionStart",
                "source": "startup",
            }),
            "session_startup",
        )
        patch = {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: README.md\n+old writer\n*** End Patch"
            },
        }
        self.assertEqual(self.hook({**patch, "session_id": old_session}).stdout, "")

        # The old owner has no PostToolUse callback in the host. The bounded
        # contention window expires, after which a new session may take over.
        time.sleep(hook_session_state.WRITER_LEASE_INFLIGHT_SECONDS + 0.2)
        self.assert_hook_receipt(
            self.hook({
                "session_id": new_session,
                "hook_event_name": "SessionStart",
                "source": "startup",
            }),
            "session_startup",
        )
        self.assertEqual(self.hook({**patch, "session_id": new_session}).stdout, "")

        old_resume = self.hook({
            "session_id": old_session,
            "hook_event_name": "SessionStart",
            "source": "resume",
        })
        old_resume_output = self.assert_hook_receipt(old_resume, "session_resume")
        self.assertIn("session-role=observer", old_resume_output["systemMessage"])

        denied = self.hook({**patch, "session_id": old_session})
        denied_output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn("observer after writer handoff", denied_output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_user_prompt_creates_an_intake_gate_for_each_new_turn(self) -> None:
        self.hook({"hook_event_name": "SessionStart", "source": "startup"})
        first = self.hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue", "turn_id": "intake-turn-1"}
        )
        first_output = self.assert_hook_receipt(first, "hook_activated")
        first_context = first_output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"pending_turn_id":"intake-turn-1"', first_context)
        self.assertIn("Requirement intake awaiting classification", first_output["systemMessage"])

        second = self.hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "continue",
                "model": "gpt-test-two",
                "turn_id": "intake-turn-2",
            }
        )
        second_output = self.assert_hook_receipt(second, "hook_activated")
        second_context = second_output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"pending_turn_id":"intake-turn-2"', second_context)

    def test_pending_intake_blocks_product_write_until_clear_assessment(self) -> None:
        prompt = self.hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "correct the label", "turn_id": "intake-clear"}
        )
        output = self.assert_hook_receipt(prompt, "hook_activated")
        context = output["hookSpecificOutput"]["additionalContext"]
        match = re.search(r'"session_key":"([a-f0-9]+)"', context)
        self.assertIsNotNone(match)
        session_key = match.group(1) if match else ""

        pending_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+pending\n*** End Patch"},
            }
        )
        pending_output = self.assert_hook_receipt(pending_patch, "pre_tool_use_denied")
        self.assertIn("Requirement intake is incomplete", pending_output["hookSpecificOutput"]["permissionDecisionReason"])

        self.cli(
            "intake",
            "assess",
            "--session-key",
            session_key,
            "--turn-id",
            "intake-clear",
            "--depth",
            "clear",
            "--summary",
            "one local correction",
            "--goal",
            "correct the label",
            "--inference",
            "the existing task only needs a bounded correction",
            "--scope",
            "README.md",
            "--acceptance",
            "the corrected label is visible",
        )
        allowed_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n+authorized\n*** End Patch"},
            }
        )
        self.assertEqual(allowed_patch.stdout, "")

    def test_subagent_receives_contract_only_when_parallel_work_is_enabled(self) -> None:
        result = self.hook(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-1",
                "agent_type": "worker",
            }
        )
        output = self.assert_hook_receipt(result, "subagent_worker")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Auto Dev subagent contract", context)
        self.assertIn('"validation_plan":["python3 -m unittest"]', context)

        active_path = self.repo / ".auto-dev" / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        active["capabilities"]["enabled"] = []
        task_path = self.repo / ".auto-dev" / "tasks" / f"{active['id']}.json"
        task_path.write_text(json.dumps(active), encoding="utf-8")
        skipped = self.hook(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-2",
                "agent_type": "worker",
            }
        )
        self.assertEqual(skipped.stdout, "")

    def test_branch_switch_does_not_restore_the_previous_branch_task(self) -> None:
        active = json.loads((self.repo / ".auto-dev" / "active.json").read_text(encoding="utf-8"))
        subprocess.run(
            ["git", "checkout", "-qb", "other-hook-branch"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        result = self.hook({"hook_event_name": "SessionStart", "source": "startup"})
        output = self.assert_hook_receipt(result, "session_startup")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"branch":"other-hook-branch"', context)
        self.assertIn('"id":null', context)
        self.assertNotIn(active["task"], context)
        denied = self.hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n*** End Patch"},
        })
        denied_output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn(
            "active Auto Dev task selected for the current branch",
            denied_output["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_unreadable_control_state_reports_status_failure(self) -> None:
        result = self.hook(
            {"hook_event_name": "SessionStart", "source": "resume"},
            plugin_root=self.root / "missing-plugin",
        )
        output = self.assert_hook_receipt(result, "status_unavailable")
        self.assertIn("event=SessionStart", output["systemMessage"])
        self.assertIn("recover or reconcile", output["hookSpecificOutput"]["additionalContext"])

    def test_pre_tool_use_protects_state_without_blocking_reads_or_normal_patches(self) -> None:
        blocked_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_use_id": "tool-1",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: .auto-dev/active.json\n*** End Patch"},
            }
        )
        blocked_patch_output = self.assert_hook_receipt(blocked_patch, "pre_tool_use_denied")
        decision = blocked_patch_output["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")

        blocked_move = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_use_id": "tool-move",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: README.md\n*** Move to: .auto-dev/active.json\n*** End Patch"
                },
            }
        )
        blocked_move_output = self.assert_hook_receipt(blocked_move, "pre_tool_use_denied")
        self.assertEqual(blocked_move_output["hookSpecificOutput"]["permissionDecision"], "deny")

        normal_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_use_id": "tool-2",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: README.md\n+Mention .auto-dev safely\n*** End Patch"
                },
            }
        )
        self.assertEqual(normal_patch.stdout, "")

        outside_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: OUTSIDE.md\n*** End Patch"},
            }
        )
        outside_output = self.assert_hook_receipt(outside_patch, "pre_tool_use_denied")
        self.assertIn("escapes the active task scope", outside_output["hookSpecificOutput"]["permissionDecisionReason"])

        state_read = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_use_id": "tool-3",
                "tool_input": {"command": "cat .auto-dev/active.json"},
            }
        )
        self.assertEqual(state_read.stdout, "")

        sed_read = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "sed -n '1,120p' skills/auto-dev/references/control-plane/code-navigation.md",
                },
            }
        )
        self.assertEqual(sed_read.stdout, "")

        state_write = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_use_id": "tool-4",
                "tool_input": {"command": "printf '{}' > .auto-dev/active.json"},
            }
        )
        state_write_output = self.assert_hook_receipt(state_write, "pre_tool_use_denied")
        self.assertEqual(state_write_output["hookSpecificOutput"]["permissionDecision"], "deny")

        sed_state_write = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "sed -i '' -e 's/active/review_ready/' .auto-dev/active.json",
                },
            }
        )
        sed_state_write_output = self.assert_hook_receipt(sed_state_write, "pre_tool_use_denied")
        self.assertEqual(sed_state_write_output["hookSpecificOutput"]["permissionDecision"], "deny")

        legacy_write = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_use_id": "tool-5",
                "tool_input": {"command": "python3 scripts/runctl.py checkpoint --summary bypass"},
            }
        )
        legacy_write_output = self.assert_hook_receipt(legacy_write, "pre_tool_use_denied")
        self.assertEqual(legacy_write_output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_external_action_requires_a_node_bound_pending_action(self) -> None:
        before = self.compact_status()
        unbound = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "event",
                "--repo-root",
                str(self.repo),
                "--type",
                "android_capture",
                "--summary",
                "unbound capture attempt",
                "--action-id",
                "capture-0",
                "--phase",
                "started",
            ],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(unbound.returncode, 0)
        self.assertIn("--node", unbound.stderr)
        self.assertEqual(self.compact_status()["state_revision"], before["state_revision"])

        safe_read = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "adb devices"},
            }
        )
        self.assertEqual(safe_read.stdout, "")

        denied = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "adb -s emulator-5554 shell input tap 10 10"},
            }
        )
        denied_output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn("opened action record", denied_output["hookSpecificOutput"]["permissionDecisionReason"])

        quoted_denied = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "adb -s emulator-5554 shell 'input tap 10 10'"},
            }
        )
        quoted_output = self.assert_hook_receipt(quoted_denied, "pre_tool_use_denied")
        self.assertIn("opened action record", quoted_output["hookSpecificOutput"]["permissionDecisionReason"])

        started = self.cli(
            "event",
            "--type",
            "android_capture",
            "--summary",
            "capture started",
            "--node",
            "implement",
            "--action-id",
            "capture-1",
            "--phase",
            "started",
        )
        self.assertEqual(json.loads(started.stdout)["node_id"], "implement")
        allowed = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "adb -s emulator-5554 shell input tap 10 10"},
            }
        )
        self.assertEqual(allowed.stdout, "")

        self.cli(
            "event",
            "--type",
            "android_capture",
            "--summary",
            "capture completed",
            "--node",
            "implement",
            "--action-id",
            "capture-1",
            "--phase",
            "result",
        )
        self.assertEqual(self.compact_status()["unattributed_actions"], [])

    def test_managed_instrumentation_requires_a_matching_lease_or_preflight(self) -> None:
        started = self.cli(
            "event",
            "--type",
            "android_capture",
            "--summary",
            "capture started",
            "--node",
            "implement",
            "--action-id",
            "capture-1",
            "--phase",
            "started",
        )
        self.assertEqual(json.loads(started.stdout)["node_id"], "implement")

        no_lease = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "frida-ps -Uai"},
            }
        )
        no_lease_output = self.assert_hook_receipt(no_lease, "pre_tool_use_denied")
        self.assertIn("Managed dependency lease required", no_lease_output["hookSpecificOutput"]["permissionDecisionReason"])

        runtime = ["/opt/frida17/bin/python", "tools/frida/run_probe.py"]
        self.cli(
            "deps",
            "record",
            "dependency",
            "--id",
            "frida17-candidate",
            "--name",
            "Frida 17",
            "--purpose",
            "Android instrumentation",
            "--capability",
            "android-instrumentation",
            "--source",
            "https://frida.re",
            "--version",
            "17.16.4",
            "--scope",
            "reverse",
            "--command",
            "run probe",
            "--runtime-argv",
            json.dumps(runtime),
            "--success",
            "probe_ready",
            "--evidence",
            "fixture candidate",
            "--status",
            "candidate",
            "--role",
            "candidate",
        )
        self.cli(
            "deps",
            "preflight",
            "open",
            "--permit-id",
            "wrong-action-preflight",
            "--dependency-id",
            "frida17-candidate",
            "--capability",
            "android-instrumentation",
            "--scope",
            "reverse",
            "--action-id",
            "capture-other",
            "--argv-json",
            json.dumps([*runtime, "--script", "probe.js"]),
        )
        wrong_action = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "/opt/frida17/bin/python tools/frida/run_probe.py --script probe.js"},
            }
        )
        wrong_action_output = self.assert_hook_receipt(wrong_action, "pre_tool_use_denied")
        self.assertIn("does not match the current node-bound pending action", wrong_action_output["hookSpecificOutput"]["permissionDecisionReason"])
        self.cli(
            "deps",
            "preflight",
            "close",
            "--permit-id",
            "wrong-action-preflight",
            "--result",
            "inconclusive",
            "--classification",
            "input",
            "--summary",
            "wrong action binding was rejected",
            "--evidence",
            "fixture mismatch",
        )
        self.cli(
            "deps",
            "preflight",
            "open",
            "--permit-id",
            "frida17-preflight",
            "--dependency-id",
            "frida17-candidate",
            "--capability",
            "android-instrumentation",
            "--scope",
            "reverse",
            "--action-id",
            "capture-1",
            "--argv-json",
            json.dumps([*runtime, "--script", "probe.js"]),
        )

        wrong_runtime = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "/usr/bin/python3 tools/frida/run_probe.py --script probe.js"},
            }
        )
        wrong_runtime_output = self.assert_hook_receipt(wrong_runtime, "pre_tool_use_denied")
        self.assertIn("preflight_runtime_binding_mismatch", wrong_runtime_output["hookSpecificOutput"]["permissionDecisionReason"])

        preflight_allowed = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "/opt/frida17/bin/python tools/frida/run_probe.py --script probe.js"},
            }
        )
        self.assertEqual(preflight_allowed.stdout, "")

        self.cli(
            "deps",
            "preflight",
            "close",
            "--permit-id",
            "frida17-preflight",
            "--result",
            "passed",
            "--classification",
            "output",
            "--summary",
            "probe ready",
            "--evidence",
            "fixture probe_ready",
            "--promote",
        )
        lease_allowed = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "/opt/frida17/bin/python tools/frida/run_probe.py --script probe.js"},
            }
        )
        self.assertEqual(lease_allowed.stdout, "")

    def test_hook_allows_canonical_dependency_preflight_and_blocks_legacy_equivalent(self) -> None:
        canonical = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} deps preflight open --repo-root {self.repo} "
                        "--permit-id fixture-preflight --dependency-id fixture --capability fixture "
                        "--action-id fixture-action --argv-json '[\"/opt/fixture\"]'"
                    ),
                },
            }
        )
        self.assertEqual(canonical.stdout, "")

        legacy = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python3 scripts/project_memory.py preflight open --permit-id bypass",
                },
            }
        )
        output = self.assert_hook_receipt(legacy, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_canonical_control_command_is_not_a_product_write_while_idle(self) -> None:
        subprocess.run(
            ["git", "checkout", "-qb", "idle-hook-branch"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        command = (
            f"{sys.executable} {CLI} start --repo-root {self.repo} --tier direct "
            "--task 'feature exposed by sed -n inspection' --requirement-receipt REQ-IDLE "
            "--confirmation-source fixture --acceptance 'state command is allowed' "
            "--scope README.md --validation smoke"
        )
        result = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
        )
        self.assertEqual(result.stdout, "")

    def test_hook_allows_canonical_workspace_checkpoint_create_and_blocks_legacy_equivalent(self) -> None:
        canonical = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} workspace checkpoint create --repo-root {self.repo} "
                        "--kind archive --scope README.md --confirmation-source user"
                    ),
                },
            }
        )
        self.assertEqual(canonical.stdout, "")
        legacy = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python3 scripts/runctl.py workspace checkpoint create --kind archive --scope README.md --confirmation-source user",
                },
            }
        )
        output = self.assert_hook_receipt(legacy, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

        canonical_protect = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} workspace checkpoint protect --repo-root {self.repo} "
                        "--node implement --scope README.md --confirmation-source user"
                    ),
                },
            }
        )
        self.assertEqual(canonical_protect.stdout, "")
        legacy_protect = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "python3 scripts/runctl.py workspace checkpoint protect --node implement --scope README.md --confirmation-source user",
                },
            }
        )
        output = self.assert_hook_receipt(legacy_protect, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_blocks_product_writes_until_protected_baseline_exists(self) -> None:
        armed = json.loads(self.cli(
            "workspace", "checkpoint", "protect", "--node", "implement",
            "--scope", "README.md", "--confirmation-source", "user requires pre-write point",
        ).stdout)
        protection_id = armed["protection"]["id"]
        product_patch = {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "\n".join([
                    "*** Begin Patch",
                    "*** Update File: README.md",
                    "@@",
                    "-fixture",
                    "+blocked until baseline",
                    "*** End Patch",
                ]),
            },
        }
        blocked = self.hook(product_patch)
        output = self.assert_hook_receipt(blocked, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("protected baseline checkpoint", output["systemMessage"])

        control_metadata_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "\n".join([
                        "*** Begin Patch",
                        "*** Add File: .conductor/m5.md",
                        "+control-plane note",
                        "*** End Patch",
                    ]),
                },
            }
        )
        self.assertEqual(control_metadata_patch.stdout, "")

        self.cli(
            "workspace", "checkpoint", "create", "--kind", "baseline",
            "--protection-id", protection_id,
            "--confirmation-source", "user confirms protected baseline",
        )
        allowed = self.hook(product_patch)
        self.assertEqual(allowed.stdout, "")

    def test_hook_allows_canonical_impact_record_and_blocks_legacy_equivalent(self) -> None:
        canonical = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} impact record --repo-root {self.repo} "
                        "--node implement --state-revision 2 --symbol hook_target "
                        "--preserve 'keep hook behavior' --verify 'run hook tests'"
                    ),
                },
            }
        )
        self.assertEqual(canonical.stdout, "")
        legacy = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 scripts/runctl.py impact record --node implement --state-revision 2 "
                        "--symbol hook_target --preserve behavior --verify tests"
                    ),
                },
            }
        )
        output = self.assert_hook_receipt(legacy, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_review_ready_preserves_context_and_blocks_product_writes_until_resumed(self) -> None:
        review_ready = self.make_review_ready()
        self.assertEqual(review_ready["status"], "review_ready")
        self.assertEqual(review_ready["continuity_status"], "review_ready")
        self.assertIn("review_ready", review_ready["strict_blockers"])
        self.assertEqual(review_ready["product_review"]["test"]["status"], "ready")
        self.assertTrue(review_ready["product_receipt"].startswith("💡 Auto Dev 产品验收回执"))
        self.assertTrue((self.repo / ".auto-dev" / "active.json").exists())

        denied = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n*** End Patch"},
            }
        )
        output = self.assert_hook_receipt(denied, "pre_tool_use_denied")
        self.assertIn("review_ready", output["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("task resume", output["hookSpecificOutput"]["permissionDecisionReason"])

        resumed = self.cli(
            "task",
            "resume",
            "--state-revision",
            str(review_ready["state_revision"]),
            "--reason",
            "user requested a related follow-up",
            "--confirmation-source",
            "user follow-up",
        )
        self.assertEqual(json.loads(resumed.stdout)["status"], "active")
        self.assertEqual(self.compact_status()["status"], "active")

    def test_legacy_review_ready_without_product_summary_is_explicit(self) -> None:
        review_ready = self.make_review_ready(include_product_review=False)
        self.assertIsNone(review_ready["product_review"])
        self.assertIn("产品验收摘要未提供", review_ready["product_receipt"])
        self.assertEqual(review_ready["product_review_status"], "missing")

    def test_fix_restores_terminal_task_with_backup_audit_and_revision_guards(self) -> None:
        review_ready = self.make_review_ready()
        task_id = review_ready["id"]
        self.cli(
            "finish",
            "--status",
            "passed",
            "--summary",
            "user accepted hook result",
            "--confirmation-source",
            "user accepted review",
        )
        self.assertFalse((self.repo / ".auto-dev" / "active.json").exists())

        inspection = json.loads(self.cli("fix", "inspect").stdout)
        candidate = next(item for item in inspection["repair_candidates"] if item["id"] == task_id)
        self.assertEqual(candidate["status"], "passed")
        self.assertIn(
            {"operation": "restore-task", "target_statuses": ["active", "review_ready"]},
            candidate["operations"],
        )
        repaired = self.cli(
            "fix",
            "apply",
            "--operation",
            "restore-task",
            "--task-id",
            task_id,
            "--expected-task-revision",
            str(candidate["state_revision"]),
            "--expected-project-revision",
            str(inspection["project_revision"]),
            "--target-status",
            "review_ready",
            "--reason",
            "user reported an unexpected archive and asked to continue",
            "--confirmation-source",
            "user message: restore the work we were just doing",
        )
        repair = json.loads(repaired.stdout)
        self.assertEqual(repair["status"], "repaired")
        self.assertEqual(repair["readback"]["status"], "review_ready")
        backup = self.repo / ".auto-dev" / repair["backup"]
        self.assertTrue((backup / "manifest.json").is_file())
        self.assertTrue((self.repo / ".auto-dev" / "repair-history.jsonl").is_file())
        self.assertEqual(self.compact_status()["status"], "review_ready")

        archived = json.loads((self.repo / ".auto-dev" / "runs" / f"{task_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["status"], "passed")
        restored = json.loads((self.repo / ".auto-dev" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(restored["status"], "review_ready")
        self.assertTrue(any(event["type"] == "control_repaired" for event in restored["events"]))

        stale = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "fix",
                "apply",
                "--repo-root",
                str(self.repo),
                "--operation",
                "restore-task",
                "--task-id",
                task_id,
                "--expected-task-revision",
                str(candidate["state_revision"]),
                "--expected-project-revision",
                str(inspection["project_revision"]),
                "--target-status",
                "active",
                "--reason",
                "stale retry",
                "--confirmation-source",
                "user message: retry",
            ],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("project revision conflict", stale.stderr)

    def test_fix_rebuilds_a_corrupted_selected_projection(self) -> None:
        review_ready = self.make_review_ready()
        active = self.repo / ".auto-dev" / "active.json"
        active.write_text("{broken", encoding="utf-8")

        inspection = json.loads(self.cli("fix", "inspect").stdout)
        self.assertIsNotNone(inspection["projection"]["active_projection_error"])
        repaired = self.cli(
            "fix",
            "apply",
            "--operation",
            "reconcile-projection",
            "--task-id",
            review_ready["id"],
            "--expected-task-revision",
            str(review_ready["state_revision"]),
            "--expected-project-revision",
            str(inspection["project_revision"]),
            "--reason",
            "repair the selected task projection",
            "--confirmation-source",
            "user message: fix the stuck control plane",
        )
        result = json.loads(repaired.stdout)
        self.assertEqual(result["readback"]["status"], "review_ready")
        self.assertEqual(self.compact_status()["id"], review_ready["id"])

    def test_fix_can_replace_a_selected_task_only_with_its_revision(self) -> None:
        review_ready = self.make_review_ready()
        archived_task_id = review_ready["id"]
        self.cli(
            "finish",
            "--status",
            "passed",
            "--summary",
            "user accepted hook result",
            "--confirmation-source",
            "user accepted review",
        )
        self.cli(
            "start",
            "--tier",
            "direct",
            "--task",
            "Deliver a later unrelated task",
            "--requirement-receipt",
            "REQ-LATER",
            "--confirmation-source",
            "test fixture",
            "--acceptance",
            "Later task remains recoverable",
            "--scope",
            "README.md",
            "--validation",
            "python3 -m unittest",
        )
        selected = self.compact_status()
        self.assertEqual(selected["status"], "active")

        inspection = json.loads(self.cli("fix", "inspect").stdout)
        archived = next(item for item in inspection["repair_candidates"] if item["id"] == archived_task_id)
        repaired = self.cli(
            "fix",
            "apply",
            "--operation",
            "restore-task",
            "--task-id",
            archived_task_id,
            "--expected-task-revision",
            str(archived["state_revision"]),
            "--expected-project-revision",
            str(inspection["project_revision"]),
            "--target-status",
            "review_ready",
            "--replace-selected-task-id",
            selected["id"],
            "--expected-selected-task-revision",
            str(selected["state_revision"]),
            "--reason",
            "user chose the earlier task over the current one",
            "--confirmation-source",
            "user message: restore the earlier task instead",
        )
        result = json.loads(repaired.stdout)
        self.assertEqual(result["displaced_task_id"], selected["id"])
        self.assertEqual(self.compact_status()["id"], archived_task_id)
        displaced = json.loads(
            (self.repo / ".auto-dev" / "tasks" / f"{selected['id']}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(displaced["status"], "paused")
        self.assertTrue(any(event["type"] == "control_repair_displaced" for event in displaced["events"]))

    def test_hook_allows_canonical_fix_apply_and_blocks_legacy_equivalent(self) -> None:
        canonical = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} fix apply --operation reconcile-projection "
                        "--task-id task --expected-task-revision 1 --expected-project-revision 1 "
                        "--reason repair --confirmation-source user"
                    ),
                },
            }
        )
        self.assertEqual(canonical.stdout, "")

        legacy = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 scripts/runctl.py fix apply --operation reconcile-projection "
                        "--task-id task --expected-task-revision 1 --expected-project-revision 1 "
                        "--reason repair --confirmation-source user"
                    ),
                },
            }
        )
        output = self.assert_hook_receipt(legacy, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_allows_canonical_legacy_upgrade_apply_and_blocks_legacy_equivalent(self) -> None:
        canonical = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {CLI} legacy-upgrade apply --project-revision 1 "
                        "--expected-upgrade-version 0 --expected-step hierarchy-adoption-v1 "
                        "--expected-fingerprint fixture --reason upgrade --confirmation-source user"
                    ),
                },
            }
        )
        self.assertEqual(canonical.stdout, "")

        legacy = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 scripts/runctl.py legacy-upgrade apply --project-revision 1 "
                        "--expected-upgrade-version 0 --expected-step hierarchy-adoption-v1 "
                        "--expected-fingerprint fixture --reason upgrade --confirmation-source user"
                    ),
                },
            }
        )
        output = self.assert_hook_receipt(legacy, "pre_tool_use_denied")
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_session_projection_names_each_actionable_upgrade_status(self) -> None:
        expected = {
            "upgrade_available": "旧控制面可以升级",
            "reverification_required": "升级后需要真实复验",
            "manual_decision_required": "升级需要人工决策",
            "blocked": "控制面升级受阻",
            "newer_than_cli": "项目控制面版本高于当前工具",
        }
        for status, label in expected.items():
            detail = hook_dispatch.legacy_upgrade_detail({
                "hierarchy": {
                    "control_plane_upgrade": {
                        "status": status,
                        "pending_step_ids": ["state-contract-adoption-v2"],
                    },
                },
            })
            self.assertIsNotNone(detail)
            self.assertIn(label, str(detail))
            self.assertIn("action=legacy-upgrade inspect", str(detail))
        self.assertIsNone(hook_dispatch.legacy_upgrade_detail({
            "hierarchy": {"control_plane_upgrade": {"status": "current"}},
        }))

    def test_absolute_patch_scope_and_strict_blockers_are_enforced(self) -> None:
        allowed = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": f"*** Begin Patch\n*** Update File: {self.repo / 'README.md'}\n*** End Patch",
                },
            }
        )
        self.assertEqual(allowed.stdout, "")

        outside = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": f"*** Begin Patch\n*** Update File: {self.repo / 'OUTSIDE.md'}\n*** End Patch",
                },
            }
        )
        outside_output = self.assert_hook_receipt(outside, "pre_tool_use_denied")
        self.assertIn("escapes the active task scope", outside_output["hookSpecificOutput"]["permissionDecisionReason"])

        (self.repo / "OUTSIDE.md").write_text("drift\n", encoding="utf-8")
        strict = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n*** End Patch"},
            }
        )
        strict_output = self.assert_hook_receipt(strict, "pre_tool_use_denied")
        self.assertIn("unresolved Auto Dev strict state", strict_output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_historical_stale_proof_blocks_completion_without_deadlocking_active_repairs(self) -> None:
        state = self.compact_status()
        self.cli(
            "proof",
            "--node",
            "implement",
            "--proof-id",
            "hook-contract",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--command",
            "python3 -c 'pass'",
        )
        state = self.compact_status()
        self.cli(
            "checkpoint",
            "--node",
            "implement",
            "--status",
            "done",
            "--plan-revision",
            str(state["continuity_summary"]["plan_revision"]),
            "--state-revision",
            str(state["state_revision"]),
            "--summary",
            "implementation proved before later work",
            "--evidence",
            "hook contract passed",
            "--next-node",
            "verify",
            "--next-action",
            "continue planned verification work",
        )

        (self.repo / "README.md").write_text("later in-scope work\n", encoding="utf-8")
        stale = self.compact_status()
        self.assertEqual(stale["strict_blockers"], ["verification_reconcile"])
        self.assertEqual(stale["completion_blockers"], ["verification_reconcile"])
        self.assertEqual(stale["product_write_blockers"], [])
        self.assertEqual(stale["verification_reconcile_mode"], "completion_only")

        repair = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: README.md\n*** End Patch"
                },
            }
        )
        self.assertEqual(repair.stdout, "")

    def test_quick_write_allows_bounded_patch_without_selected_task(self) -> None:
        subprocess.run(
            ["git", "checkout", "-qb", "quick-write-branch"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        result = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": (
                        "*** Begin Patch\n"
                        "*** Update File: README.md\n"
                        "@@\n"
                        "+quick write\n"
                        "*** End Patch"
                    )
                },
            }
        )
        self.assertEqual(result.stdout, "")

    def test_quick_write_allows_paused_project_without_resuming_task(self) -> None:
        state = self.compact_status()
        self.cli(
            "task",
            "pause",
            "--task-id",
            state["id"],
            "--state-revision",
            str(state["state_revision"]),
            "--reason",
            "quick write fixture",
        )
        self.assertEqual(self.compact_status()["status"], "selection_required")
        result = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": (
                        "*** Begin Patch\n"
                        "*** Update File: README.md\n"
                        "@@\n"
                        "+paused project quick write\n"
                        "*** End Patch"
                    )
                },
            }
        )
        self.assertEqual(result.stdout, "")

    def test_quick_write_rejects_high_risk_patch_and_bash_write(self) -> None:
        subprocess.run(
            ["git", "checkout", "-qb", "quick-write-risk-branch"],
            cwd=self.repo,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        package_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": (
                        "*** Begin Patch\n"
                        "*** Update File: package.json\n"
                        "@@\n"
                        "+{\"scripts\":{}}\n"
                        "*** End Patch"
                    )
                },
            }
        )
        package_output = self.assert_hook_receipt(package_patch, "pre_tool_use_denied")
        self.assertIn("active Auto Dev task", package_output["hookSpecificOutput"]["permissionDecisionReason"])

        bash_write = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "printf 'write' > README.md"},
            }
        )
        self.assert_hook_receipt(bash_write, "pre_tool_use_denied")

        branches = subprocess.check_output(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=self.repo,
            text=True,
        ).splitlines()
        protected = next((name for name in ("main", "master") if name in branches), None)
        self.assertIsNotNone(protected)
        subprocess.run(["git", "checkout", protected], cwd=self.repo, check=True, stdout=subprocess.DEVNULL)
        protected_patch = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": (
                        "*** Begin Patch\n"
                        "*** Update File: README.md\n"
                        "@@\n"
                        "+protected branch\n"
                        "*** End Patch"
                    )
                },
            }
        )
        protected_output = self.assert_hook_receipt(protected_patch, "pre_tool_use_denied")
        self.assertIn("active Auto Dev task", protected_output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_stderr_redirection_is_not_classified_as_product_write(self) -> None:
        result = self.hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "find .auto-dev -maxdepth 2 -type f -print 2>/dev/null | sed -n '1,160p'",
                },
            }
        )
        self.assertEqual(result.stdout, "")

    def test_direct_baseline_ignores_preexisting_drift_but_detects_new_drift(self) -> None:
        repo = self.root / "baseline-repo"
        repo.mkdir()

        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            result = subprocess.run(
                list(arguments),
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
            return result

        run("git", "init", "-q")
        run("git", "config", "user.name", "Auto Dev Baseline Test")
        run("git", "config", "user.email", "auto-dev@example.com")
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        (repo / "OUTSIDE.md").write_text("preexisting\n", encoding="utf-8")
        run("git", "add", "README.md", "OUTSIDE.md")
        run("git", "commit", "-qm", "init")
        run("git", "checkout", "-qb", "baseline-test")
        (repo / "OUTSIDE.md").write_text("preexisting edit\n", encoding="utf-8")

        start = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "start",
                "--repo-root",
                str(repo),
                "--tier",
                "direct",
                "--task",
                "baseline fixture",
                "--requirement-receipt",
                "REQ-BASELINE",
                "--confirmation-source",
                "fixture",
                "--acceptance",
                "scoped write is allowed",
                "--scope",
                "README.md",
                "--validation",
                "smoke",
            ],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(start.returncode, 0, msg=f"stdout:\n{start.stdout}\nstderr:\n{start.stderr}")
        status = json.loads(run(sys.executable, str(CLI), "status", "--repo-root", str(repo), "--compact").stdout)
        self.assertEqual(status["strict_blockers"], [])
        self.assertEqual(status["current_state"]["out_of_scope_changes"], [])
        self.assertEqual(status["current_state"]["preexisting_changes"], ["OUTSIDE.md"])

        (repo / "OUTSIDE.md").write_text("new edit after task start\n", encoding="utf-8")
        (repo / "NEW.md").write_text("new drift\n", encoding="utf-8")
        drift = json.loads(run(sys.executable, str(CLI), "status", "--repo-root", str(repo), "--compact").stdout)
        self.assertIn("OUTSIDE.md", drift["current_state"]["out_of_scope_changes"])
        self.assertIn("NEW.md", drift["current_state"]["out_of_scope_changes"])
        self.assertIn("out_of_scope_changes", drift["strict_blockers"])

    def test_non_auto_dev_project_is_silent(self) -> None:
        other = self.root / "other"
        other.mkdir()
        result = self.hook({"hook_event_name": "SessionStart", "source": "startup"}, cwd=other)
        self.assertEqual(result.stdout, "")

    def test_hook_configuration_registers_the_expected_events(self) -> None:
        configuration = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(configuration["hooks"]),
            {"SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse"},
        )
        commands = [
            hook["command"]
            for groups in configuration["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertTrue(commands)
        self.assertTrue(all("runtime_bootstrap.py" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
