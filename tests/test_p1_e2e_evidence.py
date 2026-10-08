"""P1 regression coverage for E2E proof and product-facing evidence."""

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


class P1E2EEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-e2e-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "artifacts").mkdir()
        (self.repo / "src" / "checkout.py").write_text("def checkout():\n    return True\n", encoding="utf-8")
        self.write_manifest()
        self.exec("git", "init", "-q")
        self.exec("git", "config", "user.name", "Auto Dev E2E Test")
        self.exec("git", "config", "user.email", "auto-dev-e2e@example.com")
        self.exec("git", "add", ".")
        self.exec("git", "commit", "-qm", "initial")
        self.exec("git", "checkout", "-qb", "e2e-proof")
        self.cli("project", "init", "--confirmation-source", "e2e fixture")
        self.cli(
            "start", "--tier", "direct", "--task", "Verify checkout E2E",
            "--requirement-receipt", "REQ-E2E", "--confirmation-source", "e2e fixture",
            "--acceptance", "The checkout flow is verified", "--scope", "src/checkout.py",
            "--scope", "artifacts/e2e.json", "--validation", "checkout E2E",
        )
        self.cli(
            "plan", "--base-revision", "0", "--reason", "e2e proof",
            "--plan-json", json.dumps({
                "goal": {
                    "statement": "Verify checkout E2E",
                    "acceptance": ["The checkout flow is verified"],
                    "source": "e2e fixture",
                },
                "nodes": [{
                    "id": "verify", "title": "Verify checkout flow", "status": "active",
                    "outcome": {
                        "kind": "behavior_change", "primary": "Checkout flow is verified",
                        "proofs": [{"id": "checkout-flow", "description": "Run checkout E2E"}],
                    },
                }],
                "current_node": "verify",
                "next_action": "run checkout E2E",
            }),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def exec(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), cwd=self.repo, env=os.environ, text=True,
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

    def status(self) -> dict[str, Any]:
        return self.cli("status", "--compact")

    def write_manifest(self, *, result: str = "passed", gui: dict[str, Any] | None = None) -> Path:
        path = self.repo / "artifacts" / "e2e.json"
        payload = {
            "schema": "auto-dev/e2e-evidence/v1",
            "source_ref": "playwright-report/checkout.html",
            "result": result,
            "user_flow": "A customer submits an order",
            "environment": "staging",
            "checks": {
                "page": "The order confirmation is visible",
                "data_interaction": "The submit request returns successfully",
                "system_result": "The order is recorded with the expected total",
            },
            "unverified": ["Real payment"],
            "next_step": "Product can verify with a test account",
        }
        if gui is not None:
            payload["gui"] = gui
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_e2e_manifest_flows_through_proof_review_and_staleness(self) -> None:
        manifest = self.write_manifest()
        state = self.status()
        proof = self.cli(
            "proof", "--node", "verify", "--proof-id", "checkout-flow",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", str(manifest.relative_to(self.repo)),
        )
        self.assertEqual(proof["status"], "passed")
        self.assertEqual(proof["e2e_evidence"]["environment"], "staging")

        state = self.status()
        self.cli(
            "checkpoint", "--node", "verify", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "E2E passed", "--evidence", "checkout E2E passed",
        )
        review = self.cli(
            "task", "review", "--state-revision", str(self.status()["state_revision"]),
            "--summary", "Checkout E2E is ready", "--validation", "checkout E2E passed",
            "--product-review-json", json.dumps({
                "completed": "完成下单流程验证", "purpose": "确认用户可以下单",
                "next_step": "产品验收", "user_impact": "用户可以提交订单",
                "test": {"status": "not_applicable", "reason": "E2E 已自动验证"},
            }),
        )
        self.assertEqual(review["review"]["e2e_evidence"][0]["user_flow"], "A customer submits an order")
        self.assertIn("测试环境：staging", review["product_receipt"])
        self.assertIn("页面表现：The order confirmation is visible", review["product_receipt"])
        self.assertIn("尚未验证：Real payment", review["product_receipt"])
        status_receipt = self.status()["product_receipt"]
        self.assertIn("数据交互：The submit request returns successfully", status_receipt)
        self.assertEqual(
            self.status()["continuity"]["latest_proofs"][0]["e2e_evidence"]["result"],
            "passed",
        )

        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        stale_status = self.status()
        latest = stale_status["continuity"]["latest_proofs"][0]
        self.assertFalse(latest["fresh"])
        self.assertNotIn("E2E 自动验证", stale_status["product_receipt"])

    def test_partial_e2e_result_cannot_become_a_green_proof(self) -> None:
        manifest = self.write_manifest(result="partial")
        state = self.status()
        result = self.cli(
            "proof", "--node", "verify", "--proof-id", "checkout-flow",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", str(manifest.relative_to(self.repo)),
            check=False,
        )
        self.assertEqual(result["returncode"], 1)
        proof = json.loads(result["stdout"])
        self.assertEqual(proof["status"], "failed")
        self.assertEqual(proof["e2e_evidence"]["result"], "partial")

    def test_gui_evidence_requires_visible_passed_cases_and_is_projected_to_review(self) -> None:
        gui = {
            "executor": "playwright",
            "visual_mode": "required",
            "cases": [
                {"id": "checkout-happy", "type": "happy", "status": "passed", "scope": "submit"},
                {"id": "checkout-invalid", "type": "negative", "status": "passed", "scope": "validation"},
            ],
            "evidence": {
                "action_timeline": ["artifacts/gui/timeline.json"],
                "screenshots": ["artifacts/gui/checkout.png"],
                "browser_console": [],
                "network_trace": ["artifacts/gui/checkout.har"],
                "page_state": ["artifacts/gui/page.json"],
                "backend_trace": ["request-id=checkout-1"],
            },
        }
        manifest = self.write_manifest(gui=gui)
        state = self.status()
        proof = self.cli(
            "proof", "--node", "verify", "--proof-id", "checkout-flow",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", str(manifest.relative_to(self.repo)),
        )
        self.assertEqual(proof["status"], "passed")
        self.assertEqual(proof["e2e_evidence"]["gui"]["executor"], "playwright")
        self.assertEqual(proof["e2e_evidence"]["gui"]["cases"][1]["type"], "negative")

        invalid = dict(gui)
        invalid["visual_mode"] = "unavailable"
        invalid["executor"] = "manual_only"
        invalid["cases"] = [{"id": "manual", "type": "happy", "status": "manual_only"}]
        invalid["manual_fallback"] = {
            "reason": "window host is unavailable",
            "steps": ["Open checkout in a supported browser"],
            "expected": ["Confirmation appears after submit"],
            "evidence_request": ["Return a screenshot and request ID"],
        }
        self.write_manifest(gui=invalid)
        state = self.status()
        rejected = self.cli(
            "proof", "--node", "verify", "--proof-id", "checkout-flow",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", "artifacts/e2e.json",
            check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0, msg=rejected)
        self.assertIn("passed E2E evidence requires", rejected["stderr"])

        self.write_manifest(gui=gui)
        state = self.status()
        self.cli(
            "checkpoint", "--node", "verify", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "GUI E2E passed", "--evidence", "checkout GUI passed",
        )
        review = self.cli(
            "task", "review", "--state-revision", str(self.status()["state_revision"]),
            "--summary", "Checkout GUI is ready", "--validation", "checkout GUI passed",
            "--product-review-json", json.dumps({
                "completed": "完成下单界面验证", "purpose": "确认用户可以下单",
                "next_step": "产品验收", "user_impact": "用户可以提交订单",
                "test": {"status": "not_applicable", "reason": "GUI E2E 已自动验证"},
            }),
        )
        self.assertIn("GUI 执行：playwright", review["product_receipt"])
        self.assertIn("GUI 用例：checkout-happy=passed", review["product_receipt"])


if __name__ == "__main__":
    unittest.main()
