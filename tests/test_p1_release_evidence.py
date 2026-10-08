"""P1 regression coverage for release proof and product-facing evidence."""

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
CAPABILITIES = (
    "architecture", "compliance", "data-contract", "debug-observability",
    "gui", "parallel-work", "release",
)


class P1ReleaseEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-release-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "artifacts").mkdir()
        (self.repo / "src" / "app.py").write_text("VERSION = 'v2.4.1'\n", encoding="utf-8")
        self.write_manifest()
        self.exec("git", "init", "-q")
        self.exec("git", "config", "user.name", "Auto Dev Release Test")
        self.exec("git", "config", "user.email", "auto-dev-release@example.com")
        self.exec("git", "add", ".")
        self.exec("git", "commit", "-qm", "initial")
        self.exec("git", "checkout", "-qb", "release-proof")
        self.cli("project", "init", "--confirmation-source", "release fixture")

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

    def start(self, *, release_enabled: bool = True) -> None:
        arguments = [
            "start", "--tier", "team", "--task", "Verify staging release",
            "--requirement-receipt", "REQ-RELEASE", "--confirmation-source", "release fixture",
            "--acceptance", "The staged version is releasable", "--scope", "src/app.py",
            "--validation", "release health and user-flow smoke",
        ]
        for capability in CAPABILITIES:
            if capability == "release" and release_enabled:
                arguments.extend(["--capability", capability])
                arguments.extend(["--capability-evidence", "release=the task deploys to staging"])
            else:
                arguments.extend(["--skip", f"{capability}=not needed in release fixture"])
        self.cli(*arguments)

    def plan(self, *, node_kind: str = "release") -> None:
        self.cli(
            "plan", "--base-revision", "0", "--reason", "release proof",
            "--plan-json", json.dumps({
                "goal": {
                    "statement": "Verify staging release",
                    "acceptance": ["The staged version is releasable"],
                    "source": "release fixture",
                },
                "nodes": [{
                    "id": "release", "title": "Release staging", "status": "active",
                    "node_kind": node_kind,
                    "outcome": {
                        "kind": "behavior_change", "primary": "Staging release is verified",
                        "proofs": [{"id": "release-smoke", "description": "Verify release health and smoke"}],
                    },
                    "verification": {
                        "scope": ["staging release"],
                        "phase_refs": ["release"],
                        "scenario_refs": ["health", "user-flow"],
                        "gate": "blocking",
                        "placement_reason": "Release evidence belongs after the authorized deployment",
                        "expected": "Health and key user flow pass with rollback ready",
                        "actual": "Release evidence has not been attached",
                    },
                }],
                "current_node": "release",
                "next_action": "attach release evidence",
            }),
        )

    def write_manifest(
        self, *, result: str = "succeeded", rollback_status: str = "ready",
    ) -> Path:
        path = self.repo / "artifacts" / "release.json"
        path.write_text(json.dumps({
            "schema": "auto-dev/release-evidence/v1",
            "source_ref": "ci/run/123",
            "result": result,
            "environment": "staging",
            "version": "v2.4.1",
            "health": {"status": "passed", "summary": "Service and dependencies are healthy"},
            "user_flow": {"status": "passed", "summary": "Login and checkout smoke passed"},
            "rollback": {
                "status": rollback_status,
                "trigger": "Health or checkout smoke fails",
                "target": "v2.4.0",
            },
            "unverified": ["Real payment"],
            "next_step": "Product can begin staging acceptance",
        }), encoding="utf-8")
        return path

    def record_proof(self, *, check: bool = True) -> dict[str, Any]:
        state = self.status()
        return self.cli(
            "proof", "--node", "release", "--proof-id", "release-smoke",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'", "--evidence-file", "artifacts/release.json",
            check=check,
        )

    def test_release_manifest_flows_through_review_status_handoff_and_staleness(self) -> None:
        self.start()
        self.plan()
        proof = self.record_proof()
        self.assertEqual(proof["status"], "passed")
        self.assertEqual(proof["release_evidence"]["version"], "v2.4.1")

        state = self.status()
        self.cli(
            "checkpoint", "--node", "release", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "Release verified", "--evidence", "release evidence passed",
        )
        review = self.cli(
            "task", "review", "--state-revision", str(self.status()["state_revision"]),
            "--summary", "Staging release is ready", "--validation", "release checks passed",
            "--product-review-json", json.dumps({
                "completed": "完成预发发布", "purpose": "交付产品验收",
                "next_step": "产品开始验收", "user_impact": "新版本已在预发可用",
                "test": {"status": "not_applicable", "reason": "发布烟测已完成"},
            }),
        )
        self.assertEqual(review["review"]["release_evidence"][0]["environment"], "staging")
        self.assertIn("部署版本：v2.4.1", review["product_receipt"])
        status = self.status()
        self.assertIn("回滚准备：就绪", status["product_receipt"])
        self.assertEqual(
            status["continuity"]["latest_proofs"][0]["release_evidence"]["result"],
            "succeeded",
        )

        handoff = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(handoff))
        packet = json.loads(handoff.read_text(encoding="utf-8"))
        self.assertEqual(packet["continuity"]["proofs"][0]["release_evidence"]["version"], "v2.4.1")

        manifest = self.repo / "artifacts" / "release.json"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        stale = self.status()
        self.assertFalse(stale["continuity"]["latest_proofs"][0]["fresh"])
        self.assertNotIn("发布验证", stale["product_receipt"])

    def test_non_green_release_results_cannot_become_green_proofs(self) -> None:
        self.start()
        self.plan()
        for result, rollback_status in (
            ("partial", "ready"), ("blocked", "ready"), ("rolled_back", "executed"),
        ):
            with self.subTest(result=result):
                self.write_manifest(result=result, rollback_status=rollback_status)
                recorded = self.record_proof(check=False)
                self.assertEqual(recorded["returncode"], 1)
                proof = json.loads(recorded["stdout"])
                self.assertEqual(proof["status"], "failed")
                self.assertEqual(proof["release_evidence"]["result"], result)

    def test_release_evidence_requires_the_release_capability(self) -> None:
        self.start(release_enabled=False)
        self.plan()
        result = self.record_proof(check=False)
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("enabled release capability", result["stderr"])

    def test_release_evidence_requires_a_release_node(self) -> None:
        self.start()
        self.plan(node_kind="delivery")
        result = self.record_proof(check=False)
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("release plan node", result["stderr"])


if __name__ == "__main__":
    unittest.main()
