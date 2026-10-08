#!/usr/bin/env python3
"""Snapshot retention policy and receipt-compatibility regressions."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "skills" / "auto-dev" / "scripts" / "auto_dev.py"
SCRIPTS = CLI.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import runctl  # noqa: E402


class SnapshotPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="auto-dev-snapshot-")
        self.root = pathlib.Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.execute("git", "init", "-q")
        self.execute("git", "config", "user.name", "Auto Dev Test")
        self.execute("git", "config", "user.email", "auto-dev@example.com")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.execute("git", "add", "tracked.txt")
        self.execute("git", "commit", "-qm", "initial")
        self.execute("git", "checkout", "-qb", "snapshot-policy")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def execute(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments),
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result

    def cli(self, *arguments: str) -> dict[str, object]:
        return json.loads(
            self.execute(sys.executable, str(CLI), *arguments, "--repo-root", str(self.repo)).stdout
        )

    def test_git_auto_snapshot_externalizes_stat_manifest_without_copying_untracked(self) -> None:
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        generated = self.repo / "tmp" / "generated.bin"
        generated.parent.mkdir()
        generated.write_bytes(b"x" * 8192)
        destination = self.repo / ".auto-dev" / "snapshots" / "AUTO-DEV-MANIFEST"

        snapshot = runctl.capture_snapshot(
            self.repo, destination, ["tracked.txt", "tmp"], mode="auto"
        )

        self.assertEqual(snapshot["mode"], "manifest")
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["size_bytes"], 8192)
        self.assertEqual(snapshot["untracked"], [])
        self.assertTrue((destination / "manifest.json").is_file())
        self.assertTrue((destination / "baseline.patch").is_file())
        self.assertFalse((destination / "untracked").exists())
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["entries"][0]["path"], "tmp/generated.bin")
        self.assertEqual(manifest["entries"][0]["size_bytes"], 8192)
        self.assertNotIn("sha256", manifest["entries"][0])
        self.assertEqual(
            snapshot["snapshot_ref"],
            ".auto-dev/snapshots/AUTO-DEV-MANIFEST/manifest.json",
        )

    def test_clean_git_snapshot_creates_no_directory_and_full_remains_explicit(self) -> None:
        clean_destination = self.repo / ".auto-dev" / "snapshots" / "AUTO-DEV-CLEAN"
        clean = runctl.capture_snapshot(self.repo, clean_destination, ["tracked.txt"])
        self.assertEqual(clean["mode"], "none")
        self.assertFalse(clean_destination.exists())

        generated = self.repo / "tmp" / "recovery.bin"
        generated.parent.mkdir()
        generated.write_bytes(b"recovery")
        full_destination = self.repo / ".auto-dev" / "snapshots" / "AUTO-DEV-FULL"
        full = runctl.capture_snapshot(
            self.repo, full_destination, ["tmp"], mode="full"
        )
        self.assertEqual(full["mode"], "full")
        self.assertTrue((full_destination / "untracked" / "tmp" / "recovery.bin").is_file())
        self.assertTrue((full_destination / "manifest.json").is_file())

    def test_no_git_workspace_keeps_a_full_scoped_recovery_copy(self) -> None:
        local = self.root / "local"
        local.mkdir()
        (local / "draft.txt").write_text("local draft\n", encoding="utf-8")
        destination = local / ".auto-dev" / "snapshots" / "LOCAL"

        snapshot = runctl.capture_snapshot(local, destination, ["draft.txt"], mode="manifest")

        self.assertEqual(snapshot["mode"], "full")
        self.assertTrue((destination / "local" / "draft.txt").is_file())
        self.assertTrue((destination / "manifest.json").is_file())

    def test_start_keeps_write_scope_but_can_narrow_snapshot_scope(self) -> None:
        self.cli("project", "init", "--confirmation-source", "snapshot policy fixture")
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        generated = self.repo / "tmp" / "large.bin"
        generated.parent.mkdir()
        generated.write_bytes(b"x" * 4096)
        started = self.cli(
            "start",
            "--tier", "direct",
            "--task", "Keep delivery scope separate from preservation scope",
            "--requirement-receipt", "REQ-SNAPSHOT",
            "--confirmation-source", "snapshot policy fixture",
            "--acceptance", "The task has a compact preservation receipt",
            "--scope", "tracked.txt",
            "--scope", "tmp",
            "--snapshot-scope", "tracked.txt",
            "--validation", "python3 -c pass",
        )
        task_id = str(started["id"])
        receipt = json.loads(
            (self.repo / ".auto-dev" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["planned_scope"], ["tracked.txt", "tmp"])
        self.assertEqual(receipt["preservation_scope"], ["tracked.txt"])
        self.assertEqual(receipt["snapshot"]["mode"], "manifest")
        self.assertEqual(receipt["snapshot"]["count"], 0)
        self.assertFalse(
            (self.repo / ".auto-dev" / "snapshots" / task_id / "untracked").exists()
        )

    def test_snapshot_prune_is_read_only_and_keeps_indirectly_referenced_directories(self) -> None:
        snapshots = self.repo / ".auto-dev" / "snapshots"
        referenced = snapshots / "AUTO-DEV-REFERENCED"
        orphan = snapshots / "AUTO-DEV-ORPHAN"
        referenced.mkdir(parents=True)
        orphan.mkdir(parents=True)
        (referenced / "data.bin").write_bytes(b"reference")
        (orphan / "data.bin").write_bytes(b"orphan")
        runs = self.repo / ".auto-dev" / "runs"
        runs.mkdir(parents=True)
        (runs / "history.json").write_text(
            '{"snapshot":".auto-dev/snapshots/AUTO-DEV-REFERENCED/manifest.json"}\n',
            encoding="utf-8",
        )

        before = {path: path.read_bytes() for path in snapshots.rglob("*") if path.is_file()}
        report = self.cli("snapshot", "prune")

        by_id = {entry["id"]: entry for entry in report["snapshots"]}
        self.assertEqual(report["status"], "dry_run")
        self.assertFalse(report["deletion_performed"])
        self.assertEqual(by_id["AUTO-DEV-REFERENCED"]["classification"], "referenced")
        self.assertEqual(by_id["AUTO-DEV-ORPHAN"]["classification"], "orphan_candidate")
        self.assertEqual(
            before,
            {path: path.read_bytes() for path in snapshots.rglob("*") if path.is_file()},
        )


if __name__ == "__main__":
    unittest.main()
