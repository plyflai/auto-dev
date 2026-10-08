"""P1 regression tests for conditional impact and preservation receipts."""

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
if str(HOOK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(HOOK_SCRIPTS))

import hook_dispatch  # noqa: E402


class P1ImpactTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-p1-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.log = self.root / "codegraph.log"
        self.mode = self.root / "codegraph.mode"
        self.fake_codegraph = self.root / "codegraph"
        self.fake_codegraph.write_text(
            """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

arguments = sys.argv[1:]
with pathlib.Path(os.environ["AUTO_DEV_CODEGRAPH_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments) + "\\n")
mode = pathlib.Path(os.environ["AUTO_DEV_CODEGRAPH_MODE"]).read_text(encoding="utf-8").strip()
if arguments == ["status", "-j"]:
    print(json.dumps({
        "initialized": True,
        "version": "1.1.0",
        "projectPath": str(pathlib.Path.cwd() / "other") if mode == "project_mismatch" else str(pathlib.Path.cwd()),
        "lastIndexed": "2026-09-04T00:00:00.000Z",
        "languages": ["python"],
        "pendingChanges": {"added": 0, "modified": 1 if mode == "stale" else 0, "removed": 0},
        "worktreeMismatch": {"expected": "main", "actual": "other"} if mode == "worktree_mismatch" else None,
        "index": {
            "builtWithExtractionVersion": 23 if mode == "extraction_mismatch" else 24,
            "currentExtractionVersion": 24,
            "reindexRecommended": mode == "reindex_recommended",
        },
    }))
elif arguments[:1] == ["impact"] and arguments[-1:] == ["-j"]:
    symbol = arguments[1]
    depth = int(arguments[arguments.index("-d") + 1])
    dependent_count = depth if mode == "growing" else (0 if mode == "empty" else 1)
    affected = [{"name": symbol, "kind": "function", "filePath": "src/feature.py", "startLine": 1}]
    for index in range(dependent_count):
        affected.append({
            "name": f"feature_consumer_{index + 1}",
            "kind": "function",
            "filePath": "src/consumer.py",
            "startLine": index + 1,
        })
    print(json.dumps({"symbol": symbol, "nodeCount": len(affected), "edgeCount": dependent_count, "affected": affected}))
elif arguments[:1] == ["affected"] and arguments[-1:] == ["-j"]:
    filter_index = arguments.index("-f") if "-f" in arguments else len(arguments) - 1
    print(json.dumps({"changedFiles": arguments[1:filter_index], "affectedTests": [] if mode == "empty" else ["tests/test_feature.py"], "totalDependentsTraversed": 0 if mode == "empty" else 2}))
else:
    print("unsupported fake CodeGraph invocation", file=sys.stderr)
    raise SystemExit(2)
""",
            encoding="utf-8",
        )
        self.fake_codegraph.chmod(0o755)
        self.mode.write_text("signal\n", encoding="utf-8")
        self._init_repo(self.repo)
        self.cli("project", "init", "--confirmation-source", "p1 project")
        self.cli(
            "start",
            "--tier", "team",
            "--task", "Exercise P1 impact continuity",
            "--requirement-receipt", "REQ-P1",
            "--confirmation-source", "p1 task",
            "--acceptance", "Impact and preservation survive handoff",
            "--scope", "src/feature.py",
            "--scope", "src/consumer.py",
            "--scope", "tests/test_feature.py",
            "--validation", "python3 -m unittest tests/test_feature.py",
            *self.skip_capabilities(),
        )
        plan = {
            "goal": {
                "statement": "Exercise P1 impact continuity",
                "acceptance": ["Impact and preservation survive handoff"],
                "source": "p1 task",
            },
            "nodes": [{
                "id": "implement",
                "title": "Refactor feature",
                "status": "active",
                "outcome": {
                    "kind": "behavior_change",
                    "primary": "The feature behavior is preserved",
                    "proofs": [{"id": "feature-proof", "description": "Run affected feature tests"}],
                },
            }],
            "current_node": "implement",
            "next_action": "record impact before refactoring",
        }
        self.cli("plan", "--base-revision", "0", "--reason", "p1 fixture", "--plan-json", json.dumps(plan))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def skip_capabilities() -> list[str]:
        values: list[str] = []
        for name in (
            "architecture", "compliance", "data-contract", "debug-observability",
            "gui", "parallel-work", "release",
        ):
            values.extend(["--skip", f"{name}=not required by P1 fixture"])
        return values

    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "AUTO_DEV_CODEGRAPH_BIN": str(self.fake_codegraph),
            "AUTO_DEV_CODEGRAPH_LOG": str(self.log),
            "AUTO_DEV_CODEGRAPH_MODE": str(self.mode),
        }

    def _init_repo(self, repo: Path) -> None:
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / ".codegraph").mkdir()
        (repo / "src" / "feature.py").write_text("def feature_symbol():\n    return 1\n", encoding="utf-8")
        (repo / "src" / "consumer.py").write_text("from .feature import feature_symbol\n", encoding="utf-8")
        (repo / "tests" / "test_feature.py").write_text("# affected test\n", encoding="utf-8")
        (repo / ".codegraph" / "codegraph.db").write_bytes(b"index-v1")
        self.exec("git", "init", "-q", cwd=repo)
        self.exec("git", "config", "user.name", "Auto Dev P1 Test", cwd=repo)
        self.exec("git", "config", "user.email", "auto-dev-p1@example.com", cwd=repo)
        self.exec("git", "add", "src", "tests", cwd=repo)
        self.exec("git", "commit", "-qm", "initial", cwd=repo)
        self.exec("git", "checkout", "-qb", "p1-test", cwd=repo)

    def exec(
        self, *arguments: str, cwd: Path | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), cwd=cwd or self.repo, env=self.environment(), text=True,
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

    def workspace_snapshot(self, repo: Path | None = None) -> dict[str, str]:
        root = repo or self.repo
        result: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file() or ".git" in path.relative_to(root).parts:
                continue
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def record(self, *, state_revision: int | None = None, uncertainty: str | None = None) -> dict[str, Any]:
        status = self.cli("status", "--compact")
        arguments = [
            "impact", "record",
            "--node", "implement",
            "--state-revision", str(status["state_revision"] if state_revision is None else state_revision),
            "--symbol", "feature_symbol",
            "--file", "src/feature.py",
            "--preserve", "feature_symbol keeps returning the same public value",
            "--verify", "run tests/test_feature.py after the refactor",
        ]
        if uncertainty:
            arguments.extend(["--uncertainty", uncertainty])
        return self.cli(*arguments)

    def codegraph_calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_inspect_is_read_only_and_uses_only_bounded_codegraph_commands(self) -> None:
        before = self.workspace_snapshot()
        inspected = self.cli(
            "impact", "inspect", "--symbol", "feature_symbol", "--file", "src/feature.py",
        )
        self.assertEqual(before, self.workspace_snapshot())
        self.assertEqual(inspected["status"], "inspected")
        self.assertFalse(inspected["needs_uncertainty"])
        self.assertEqual(inspected["coverage_status"], "complete")
        self.assertEqual(inspected["test_discovery"]["source"], "inferred")
        self.assertEqual(inspected["test_discovery"]["status"], "verified")
        self.assertTrue(inspected["receipt"].startswith("💥 Auto Dev Impact: impact_inspected"))
        self.assertEqual(self.codegraph_calls(), [
            ["status", "-j"],
            ["impact", "feature_symbol", "-d", "2", "-j"],
            ["impact", "feature_symbol", "-d", "4", "-j"],
            ["affected", "src/feature.py", "-f", "tests/test_*.py", "-j"],
        ])

    def test_explicit_test_filter_overrides_language_inference(self) -> None:
        inspected = self.cli(
            "impact", "inspect", "--file", "src/feature.py",
            "--test-filter", "tests/**/*_spec.py",
        )
        self.assertEqual(inspected["test_discovery"]["source"], "configured")
        self.assertIn(
            ["affected", "src/feature.py", "-f", "tests/**/*_spec.py", "-j"],
            self.codegraph_calls(),
        )

    def test_symbol_depth_limit_marks_coverage_partial(self) -> None:
        self.mode.write_text("growing\n", encoding="utf-8")
        inspected = self.cli(
            "impact", "inspect", "--symbol", "feature_symbol", "--max-depth", "6",
        )
        self.assertEqual(inspected["coverage_status"], "partial")
        self.assertTrue(inspected["needs_uncertainty"])
        self.assertIn("symbol_depth_limit_reached:feature_symbol", inspected["coverage_reasons"])
        self.assertEqual(
            inspected["codegraph"]["symbol_results"][0]["depths_checked"], [2, 4, 6]
        )

    def test_file_only_dependents_are_partial_and_require_uncertainty(self) -> None:
        inspected = self.cli("impact", "inspect", "--file", "src/feature.py")
        self.assertTrue(inspected["impact_signal"])
        self.assertEqual(inspected["known_scope"], ["src/feature.py", "tests/test_feature.py"])
        self.assertEqual(inspected["coverage_status"], "partial")
        self.assertTrue(inspected["needs_uncertainty"])
        self.assertIn("file_dependents_not_enumerated", inspected["coverage_reasons"])

        state = self.cli("status", "--compact")
        rejected = self.cli(
            "impact", "record", "--node", "implement",
            "--state-revision", str(state["state_revision"]),
            "--file", "src/feature.py",
            "--preserve", "preserve behavior", "--verify", "run tests", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("--uncertainty", rejected["stderr"])

    def test_structured_status_rejects_non_fresh_states(self) -> None:
        for mode in (
            "stale", "project_mismatch", "worktree_mismatch",
            "extraction_mismatch", "reindex_recommended",
        ):
            with self.subTest(mode=mode):
                self.mode.write_text(f"{mode}\n", encoding="utf-8")
                rejected = self.cli(
                    "impact", "inspect", "--symbol", "feature_symbol", check=False,
                )
                self.assertEqual(rejected["returncode"], 2)
                self.assertIn("CodeGraph index is not up to date", rejected["stderr"])

    def test_record_requires_current_revision_node_preservation_and_verification(self) -> None:
        state = self.cli("status", "--compact")
        stale = self.cli(
            "impact", "record", "--node", "implement",
            "--state-revision", str(state["state_revision"] - 1),
            "--symbol", "feature_symbol", "--preserve", "preserve behavior", "--verify", "run tests",
            check=False,
        )
        self.assertNotEqual(stale["returncode"], 0)
        wrong_node = self.cli(
            "impact", "record", "--node", "missing",
            "--state-revision", str(state["state_revision"]),
            "--symbol", "feature_symbol", "--preserve", "preserve behavior", "--verify", "run tests",
            check=False,
        )
        self.assertNotEqual(wrong_node["returncode"], 0)
        missing_preservation = self.cli(
            "impact", "record", "--node", "implement",
            "--state-revision", str(state["state_revision"]),
            "--symbol", "feature_symbol", "--verify", "run tests", check=False,
        )
        self.assertEqual(missing_preservation["returncode"], 2)
        missing_verification = self.cli(
            "impact", "record", "--node", "implement",
            "--state-revision", str(state["state_revision"]),
            "--symbol", "feature_symbol", "--preserve", "preserve behavior", check=False,
        )
        self.assertEqual(missing_verification["returncode"], 2)

    def test_record_projects_fresh_then_scope_and_index_changes_are_stale(self) -> None:
        recorded = self.record()
        self.assertTrue(recorded["receipt"].startswith("💥 Auto Dev Impact: impact_recorded"))
        calls_after_record = list(self.codegraph_calls())
        status = self.cli("status", "--compact")
        self.assertEqual(calls_after_record, self.codegraph_calls(), "status projection must not invoke CodeGraph")
        impact = status["continuity_summary"]["impact"]
        self.assertEqual(impact["status"], "fresh")
        self.assertTrue(impact["latest"]["fresh"])
        self.assertEqual(impact["latest"]["affected_tests"], ["tests/test_feature.py"])
        self.assertEqual(len(status["continuity"]["impact_receipts"]), 1)
        context = hook_dispatch.control_context(self.repo, status, "p1-test")
        self.assertIn(impact["latest"]["receipt_id"], context)
        self.assertEqual(calls_after_record, self.codegraph_calls(), "Hook projection must not invoke CodeGraph")
        progress_page = (PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "progress_page.html").read_text(encoding="utf-8")
        self.assertIn('id="impact-summary"', progress_page)
        self.assertNotIn("codegraph status", progress_page.casefold())

        feature = self.repo / "src" / "feature.py"
        original = feature.read_text(encoding="utf-8")
        feature.write_text(original + "# changed\n", encoding="utf-8")
        stale_scope = self.cli("status", "--compact")["continuity_summary"]["impact"]["latest"]
        self.assertFalse(stale_scope["fresh"])
        self.assertIn("scope_changed", stale_scope["stale_reasons"])
        feature.write_text(original, encoding="utf-8")
        (self.repo / ".codegraph" / "codegraph.db").write_bytes(b"index-v2")
        stale_index = self.cli("status", "--compact")["continuity_summary"]["impact"]["latest"]
        self.assertFalse(stale_index["fresh"])
        self.assertIn("codegraph_index_changed", stale_index["stale_reasons"])

    def test_empty_graph_requires_explicit_uncertainty(self) -> None:
        self.mode.write_text("empty\n", encoding="utf-8")
        state = self.cli("status", "--compact")
        rejected = self.cli(
            "impact", "record", "--node", "implement",
            "--state-revision", str(state["state_revision"]),
            "--symbol", "feature_symbol", "--file", "src/feature.py",
            "--preserve", "preserve behavior", "--verify", "run tests", check=False,
        )
        self.assertNotEqual(rejected["returncode"], 0)
        self.assertIn("--uncertainty", rejected["stderr"])
        recorded = self.record(uncertainty="dynamic callers may not be visible in the static graph")
        self.assertEqual(recorded["impact"]["uncertainty"], ["dynamic callers may not be visible in the static graph"])
        self.assertIn("no_dependents_reported", recorded["impact"]["dynamic_risks"])

    def test_handoff_preserves_receipt_and_recomputes_freshness(self) -> None:
        self.record()
        packet = self.root / "handoff.json"
        self.cli("handoff", "export", "--out", str(packet))

        target = self.root / "target"
        self._init_repo(target)
        self.cli_for(target, "project", "init", "--confirmation-source", "target project")
        self.cli_for(target, "handoff", "import", "--file", str(packet))
        imported = self.cli_for(target, "status", "--compact")
        self.assertEqual(len(imported["continuity"]["impact_receipts"]), 1)
        self.assertEqual(imported["continuity_summary"]["impact"]["status"], "fresh")
        (target / ".codegraph" / "codegraph.db").write_bytes(b"target-index-changed")
        stale = self.cli_for(target, "status", "--compact")["continuity_summary"]["impact"]["latest"]
        self.assertIn("codegraph_index_changed", stale["stale_reasons"])


if __name__ == "__main__":
    unittest.main()
