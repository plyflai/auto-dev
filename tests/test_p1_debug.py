"""P1 regression tests for conditional Deep Debug and incident-case memory."""

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


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
HOOK_SCRIPTS = PLUGIN_ROOT / "scripts"
SKILL_SCRIPTS = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts"
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

import hook_dispatch  # noqa: E402
import project_memory  # noqa: E402


class P1DeepDebugTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-p1-debug-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.init_repo(self.repo)
        self.cli("project", "init", "--confirmation-source", "deep debug fixture")
        self.cli(
            "start",
            "--tier", "team",
            "--task", "Diagnose an intermittent feature failure",
            "--requirement-receipt", "REQ-P1-DEBUG",
            "--confirmation-source", "deep debug fixture",
            "--acceptance", "The cause is evidenced or the diagnostic limit is explicit",
            "--scope", "src/feature.py",
            "--scope", "tests/test_feature.py",
            "--validation", "python3 -m unittest tests.test_feature",
            "--capability", "debug-observability",
            "--capability-evidence", "debug-observability=root cause requires multiple probes",
            *self.skip_capabilities(),
        )
        self.cli(
            "plan",
            "--base-revision", "0",
            "--reason", "deep debug fixture",
            "--plan-json", json.dumps(self.plan_payload()),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def skip_capabilities() -> list[str]:
        values: list[str] = []
        for name in (
            "architecture", "compliance", "data-contract", "gui", "parallel-work", "release",
        ):
            values.extend(["--skip", f"{name}=not required by deep debug fixture"])
        return values

    @staticmethod
    def plan_payload() -> dict[str, Any]:
        return {
            "goal": {
                "statement": "Diagnose an intermittent feature failure",
                "acceptance": ["The cause is evidenced or the diagnostic limit is explicit"],
                "source": "deep debug fixture",
            },
            "nodes": [{
                "id": "diagnose",
                "title": "Diagnose and recover the feature",
                "status": "active",
                "outcome": {
                    "kind": "behavior_change",
                    "primary": "The feature failure is explained and recovered",
                    "proofs": [{"id": "debug-loop", "description": "Run the diagnostic feedback loop"}],
                },
            }],
            "current_node": "diagnose",
            "next_action": "start the deep diagnostic feedback loop",
        }

    def init_repo(self, repo: Path) -> None:
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "feature.py").write_text("def feature():\n    return 1\n", encoding="utf-8")
        (repo / "tests" / "test_feature.py").write_text("# diagnostic fixture\n", encoding="utf-8")
        self.exec("git", "init", "-q", cwd=repo)
        self.exec("git", "config", "user.name", "Auto Dev Debug Test", cwd=repo)
        self.exec("git", "config", "user.email", "auto-dev-debug@example.com", cwd=repo)
        self.exec("git", "add", ".", cwd=repo)
        self.exec("git", "commit", "-qm", "initial", cwd=repo)
        self.exec("git", "checkout", "-qb", "p1-debug", cwd=repo)

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

    def status(self) -> dict[str, Any]:
        return self.cli("status", "--compact")

    def state_revision(self) -> int:
        return int(self.status()["state_revision"])

    def memory_revision(self) -> int:
        return int(project_memory.load(project_memory.registry_path(self.repo))["memory_revision"])

    def workspace_snapshot(self, repo: Path | None = None) -> dict[str, str]:
        root = repo or self.repo
        result: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file() or ".git" in path.relative_to(root).parts:
                continue
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def begin(self) -> dict[str, Any]:
        return self.cli(
            "debug", "begin",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--symptom", "The feature fails after an intermittent state transition",
            "--environment-ref", "local deterministic fixture",
            "--next-probe", "search project cases and run the minimal loop",
        )

    def bind_empty_search(self) -> dict[str, Any]:
        search = self.cli("memory", "case", "search", "--symptom", "intermittent state transition")
        return self.cli(
            "debug", "case-search", "bind",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", search["status"],
            "--memory-revision", str(search["memory_revision"]),
            "--memory-digest", search["memory_digest"],
            "--query-digest", search["query_digest"],
        )

    def proof(self, *, passed: bool) -> dict[str, Any]:
        state = self.status()
        result = self.cli(
            "proof",
            "--node", "diagnose",
            "--proof-id", "debug-loop",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--command", "python3 -c 'pass'" if passed else "python3 -c 'raise SystemExit(1)'",
            *([] if passed else ["--failure-classification", "product"]),
            check=passed,
        )
        if passed:
            return result
        self.assertEqual(result["returncode"], 1)
        return json.loads(result["stdout"])

    def record_reproduction(self, proof: dict[str, Any], *, gate: str = "ready_red") -> dict[str, Any]:
        return self.cli(
            "debug", "reproduction", "record",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--gate", gate,
            "--proof-ref", proof["attempt_id"],
            "--original-proof-ref", proof["attempt_id"],
            "--minimal-proof-ref", proof["attempt_id"],
            "--runs", "1",
            "--failures", "1" if gate in {"ready_red", "ready_flaky"} else "0",
            "--agent-runnable", "yes",
        )

    def add_hypothesis(
        self, hypothesis_id: str = "h-state", *, check: bool = True,
    ) -> dict[str, Any]:
        return self.cli(
            "debug", "hypothesis", "add",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--hypothesis-id", hypothesis_id,
            "--statement", "A stale state transition bypasses the feature update",
            "--prediction", "The failing loop observes the old state after the transition",
            "--probe", "Run the minimal loop and inspect the returned state",
            check=check,
        )

    def observe(self, proof: dict[str, Any], *, verdict: str = "confirmed") -> dict[str, Any]:
        return self.cli(
            "debug", "observe",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--observation-id", f"obs-{verdict}-{proof['attempt_index']}",
            "--hypothesis-id", "h-state",
            "--expected", "The old state remains visible",
            "--actual", "The old state remained visible in the minimal loop",
            "--verdict", verdict,
            "--proof-ref", proof["attempt_id"],
        )

    def prepare_confirmed_root_cause(self) -> dict[str, Any]:
        self.begin()
        self.bind_empty_search()
        failed = self.proof(passed=False)
        self.record_reproduction(failed)
        self.add_hypothesis()
        self.observe(failed)
        return self.cli(
            "debug", "resolve",
            "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--outcome", "root_cause_confirmed",
            "--summary", "A stale state transition bypasses the feature update",
        )

    def test_begin_requires_team_debug_capability_and_projects_bounded_status(self) -> None:
        started = self.begin()
        self.assertEqual(started["status"], "debug_started")
        status = self.status()
        diagnostic = status["continuity"]["diagnostic"]
        self.assertEqual(diagnostic["profile"], "deep")
        self.assertEqual(diagnostic["status"], "reproducing")
        self.assertEqual(status["continuity_summary"]["diagnostic"]["case_search_status"], "not_run")
        context = hook_dispatch.control_context(self.repo, status, "session_compact")
        self.assertIn('"diagnostic"', context)
        self.assertNotIn("🩺", context)
        receipt = hook_dispatch.hook_receipt("session_compact", status=status)
        self.assertIn("debug=reproducing", receipt)
        self.assertNotIn("debug=unverified", receipt)

        direct = self.root / "direct"
        self.init_repo(direct)
        self.cli_for(direct, "project", "init", "--confirmation-source", "direct fixture")
        self.cli_for(
            direct, "start", "--tier", "direct", "--task", "Known-root fix",
            "--requirement-receipt", "REQ-DIRECT", "--confirmation-source", "direct fixture",
            "--acceptance", "Known root stays light", "--scope", "src/feature.py",
            "--validation", "python3 -m unittest tests.test_feature",
        )
        direct_status = self.cli_for(direct, "status", "--compact")
        direct_context = hook_dispatch.control_context(direct, direct_status, "session_compact")
        self.assertNotIn('"diagnostic":', direct_context)
        rejected = self.cli_for(
            direct, "debug", "begin", "--node", "run", "--state-revision", "1",
            "--symptom", "Known root", "--next-probe", "none", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)

    def test_case_search_is_read_only_and_must_be_bound_before_hypotheses(self) -> None:
        self.begin()
        before = self.workspace_snapshot()
        search = self.cli("memory", "case", "search", "--symptom", "intermittent state transition")
        self.assertEqual(before, self.workspace_snapshot())
        self.assertEqual(search["status"], "miss")
        self.assertEqual(search["memory_revision"], self.memory_revision())
        premature = self.add_hypothesis(check=False)
        self.assertNotEqual(premature["returncode"], 0)

    def test_failed_proof_can_confirm_a_hypothesis_without_becoming_green_proof(self) -> None:
        self.begin()
        self.bind_empty_search()
        failed = self.proof(passed=False)
        self.record_reproduction(failed)
        self.add_hypothesis()
        observed = self.observe(failed)
        self.assertEqual(observed["status"], "observation_recorded")
        status = self.status()
        hypothesis = status["continuity"]["diagnostic"]["hypotheses"][0]
        self.assertEqual(hypothesis["status"], "confirmed")
        self.assertFalse(status["continuity"]["latest_proofs"][0]["fresh"])
        self.assertTrue(status["continuity"]["diagnostic"]["observations"][0]["fresh"])

    def test_no_defect_requires_clean_workspace_and_skips_product_fix(self) -> None:
        self.begin()
        self.bind_empty_search()
        passed = self.proof(passed=True)
        self.record_reproduction(passed, gate="ready_green_no_defect")
        feature = self.repo / "src" / "feature.py"
        original = feature.read_text(encoding="utf-8")
        feature.write_text(original + "# unjustified change\n", encoding="utf-8")
        rejected = self.cli(
            "debug", "resolve", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--outcome", "no_defect_observed",
            "--summary", "The representative loop remained green", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        feature.write_text(original, encoding="utf-8")
        resolved = self.cli(
            "debug", "resolve", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--outcome", "no_defect_observed",
            "--summary", "The representative loop remained green",
        )
        self.assertEqual(resolved["outcome"], "no_defect_observed")
        self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "not_applicable", "--probe-cleanup", "not_applicable",
        )

    def test_recovery_requires_fresh_green_proof_and_probe_cleanup(self) -> None:
        self.prepare_confirmed_root_cause()
        failed = self.status()["continuity"]["proofs"][0]
        rejected = self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "verified", "--proof-ref", failed["attempt_id"],
            "--probe-cleanup", "complete", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        passed = self.proof(passed=True)
        missing_cleanup = self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "verified", "--proof-ref", passed["attempt_id"],
            "--probe-cleanup", "pending", check=False,
        )
        self.assertNotEqual(missing_cleanup["returncode"], 0)
        recovered = self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "verified", "--proof-ref", passed["attempt_id"],
            "--probe-cleanup", "complete",
        )
        self.assertEqual(recovered["status"], "recovery_recorded")
        self.assertEqual(recovered["recovery_status"], "verified")

    def test_awaiting_confirmation_cannot_promote_an_incident_case(self) -> None:
        self.prepare_confirmed_root_cause()
        passed = self.proof(passed=True)
        self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "awaiting_confirmation", "--proof-ref", passed["attempt_id"],
            "--probe-cleanup", "complete", "--confirmation-owner", "user",
        )
        rejected = self.promote_case(memory_revision=self.memory_revision(), check=False)
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("awaiting_confirmation", rejected["stderr"])

    def test_awaiting_confirmation_rejects_failed_recovery_proof(self) -> None:
        self.prepare_confirmed_root_cause()
        failed = self.proof(passed=False)
        rejected = self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "awaiting_confirmation", "--proof-ref", failed["attempt_id"],
            "--probe-cleanup", "complete", "--confirmation-owner", "user", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("fresh passing proof or valid external evidence", rejected["stderr"])

    def test_confirmed_recovery_promotes_searchable_case_with_memory_cas(self) -> None:
        self.prepare_confirmed_root_cause()
        passed = self.proof(passed=True)
        self.cli(
            "debug", "recovery", "--node", "diagnose",
            "--state-revision", str(self.state_revision()),
            "--status", "verified", "--proof-ref", passed["attempt_id"],
            "--probe-cleanup", "complete",
        )
        state = self.status()
        self.cli(
            "checkpoint", "--node", "diagnose", "--status", "done",
            "--plan-revision", str(state["continuity_summary"]["plan_revision"]),
            "--state-revision", str(state["state_revision"]),
            "--summary", "root cause recovered", "--evidence", "debug loop passed",
        )
        state = self.status()
        self.cli(
            "task", "review", "--state-revision", str(state["state_revision"]),
            "--summary", "diagnostic result is ready", "--file", "src/feature.py",
            "--validation", "debug loop passed",
        )
        initial_memory_revision = self.memory_revision()
        mismatch = self.promote_case(
            memory_revision=initial_memory_revision,
            root_cause="A different explanation that was not resolved by this task",
            check=False,
        )
        self.assertNotEqual(mismatch["returncode"], 0)
        self.assertIn("must match the diagnostic resolution summary", mismatch["stderr"])
        promoted = self.promote_case(memory_revision=initial_memory_revision)
        self.assertEqual(promoted["status"], "case_promoted")
        self.assertEqual(promoted["memory_revision"], initial_memory_revision + 1)
        repeated = self.promote_case(memory_revision=initial_memory_revision + 1)
        self.assertEqual(repeated["status"], "already_promoted")
        self.assertEqual(repeated["memory_revision"], initial_memory_revision + 1)
        stale = self.promote_case(
            memory_revision=initial_memory_revision,
            case_id="stale-case",
            check=False,
        )
        self.assertNotEqual(stale["returncode"], 0)
        search = self.cli(
            "memory", "case", "search", "--symptom", "stale state transition",
            "--scope", "src/feature.py", "--component", "feature",
        )
        self.assertEqual(search["status"], "match")
        self.assertEqual(search["cases"][0]["id"], "state-transition-case")

    def promote_case(
        self,
        *,
        memory_revision: int,
        case_id: str = "state-transition-case",
        root_cause: str = "A stale state transition bypasses the feature update",
        check: bool = True,
    ) -> dict[str, Any]:
        return self.cli(
            "memory", "case", "promote",
            "--state-revision", str(self.state_revision()),
            "--memory-revision", str(memory_revision),
            "--case-id", case_id,
            "--title", "Stale state transition bypasses feature update",
            "--keyword", "stale-state",
            "--keyword", "transition",
            "--symptom-signal", "feature fails after state transition",
            "--scope", "src/feature.py",
            "--component", "feature",
            "--environment", "local deterministic fixture",
            "--observed-version", "fixture-v1",
            "--cause-class", "state-transition-gap",
            "--root-cause", root_cause,
            "--resolution", "Update the transition before reading the feature state",
            "--protective-test", "minimal state transition loop",
            "--lesson", "State transitions must update their canonical state before dependent reads",
            "--evidence-ref", "debug-loop",
            "--confirmation-source", "user accepted the recovered result",
            check=check,
        )

    def test_project_memory_registry_keeps_backup_and_verifies_readback(self) -> None:
        path = project_memory.registry_path(self.repo)
        initial_memory_revision = self.memory_revision()
        first = project_memory.load(path)
        first["updated_at"] = "first"
        self.assertEqual(
            project_memory.write_registry(
                self.repo,
                first,
                expected_revision=initial_memory_revision,
            ),
            initial_memory_revision + 1,
        )
        second = project_memory.load(path)
        second["updated_at"] = "second"
        self.assertEqual(
            project_memory.write_registry(
                self.repo,
                second,
                expected_revision=initial_memory_revision + 1,
            ),
            initial_memory_revision + 2,
        )
        backup = json.loads(path.with_suffix(".bak").read_text(encoding="utf-8"))
        self.assertEqual(backup["memory_revision"], initial_memory_revision + 1)
        self.assertEqual(
            project_memory.load(path)["memory_revision"],
            initial_memory_revision + 2,
        )

    def test_handoff_preserves_diagnostic_and_recomputes_observation_freshness(self) -> None:
        self.prepare_confirmed_root_cause()
        packet = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(packet))
        target = self.root / "target"
        self.init_repo(target)
        self.cli_for(target, "project", "init", "--confirmation-source", "target fixture")
        self.cli_for(target, "handoff", "import", "--file", str(packet))
        imported = self.cli_for(target, "status", "--compact")
        self.assertEqual(imported["continuity"]["diagnostic"]["resolution"]["outcome"], "root_cause_confirmed")
        self.assertTrue(imported["continuity"]["diagnostic"]["observations"][0]["fresh"])
        path = target / "src" / "feature.py"
        path.write_text(path.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        stale = self.cli_for(target, "status", "--compact")["continuity"]["diagnostic"]
        self.assertFalse(stale["observations"][0]["fresh"])
        self.assertFalse(stale["resolution"]["fresh"])

    def test_memory_case_search_is_zero_write_without_auto_dev_project(self) -> None:
        repo = self.root / "unmanaged"
        self.init_repo(repo)
        before = self.workspace_snapshot(repo)
        result = self.cli_for(repo, "memory", "case", "search", "--symptom", "unknown failure")
        self.assertEqual(result["status"], "miss")
        self.assertEqual(before, self.workspace_snapshot(repo))
        self.assertFalse((repo / ".auto-dev").exists())

    def test_hook_recognizes_only_mutating_debug_and_memory_case_commands(self) -> None:
        self.assertTrue(hook_dispatch.mutating_control_parts(["debug", "observe"]))
        self.assertTrue(hook_dispatch.mutating_control_parts(["memory", "case", "promote"]))
        self.assertFalse(hook_dispatch.mutating_control_parts(["debug", "inspect"]))
        self.assertFalse(hook_dispatch.mutating_control_parts(["memory", "case", "search"]))


if __name__ == "__main__":
    unittest.main()
